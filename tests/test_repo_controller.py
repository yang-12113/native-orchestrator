import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from native_orchestrator.check_runner import input_manifest
from native_orchestrator.codex_sdk_adapter import SdkRoleError
from native_orchestrator.model_policy import load_policy
from native_orchestrator.orchestrator import Controller, EvidenceChangedError, atomic_json, digest
from native_orchestrator.repo_execution import git, KIND

ROOT=Path(__file__).resolve().parents[1]


class FakeSdk:
    def __init__(self):
        self.roles=[]
        self.verdict='PASS'
        self.block=None
        self.bad_first=False
        self.c=None

    def preflight(self,routes,cwd,*,before_dispatch):
        if self.block:raise SdkRoleError(self.block)
        before_dispatch()
        return {'routes':routes,'model_turns':0}

    def run(self,role,model,prompt,cwd,log,*,schema,effort,before_dispatch,before_turn,**kw):
        before_dispatch()
        sid=role+'-'+str(len(self.roles)+1)
        before_turn(sid)
        self.roles.append((role,model,effort))
        cwd=Path(cwd)
        items=[]
        if role=='executor':
            text='def add(a,b):\n    return a + b'+(' + 1' if self.bad_first and len(self.roles)==1 else '')+'\n'
            (cwd/'calculator.py').write_bytes(text.encode())
            payload={'summary':'synthetic direct edit'}
        else:
            payload={k:v['enum'][0] for k,v in schema['properties'].items() if 'enum' in v}
            payload.update(verdict=self.verdict,findings=[] if self.verdict=='PASS' else ['synthetic defect'],summary='synthetic review',checked_evidence_refs=[])
            for name in ['task.json','checks.json']:
                raw=(cwd/'.controller-review'/name).read_bytes()
                items.append({'type':'commandExecution','command':'Get-Content -Raw .controller-review/'+name,'exit_code':0,'aggregated_output':raw.decode()})
                payload['checked_evidence_refs'].append(name)
            for path in sorted(cwd.glob('*.py')):
                ref='git:'+path.name
                items.append({'type':'commandExecution','command':'git show '+payload['candidate_commit']+':'+path.name,'exit_code':0,'aggregated_output':path.read_text(encoding='utf-8')})
                payload['checked_evidence_refs'].append(ref)
            diff_ref='git:'+payload['base_commit']+'..'+payload['candidate_commit']
            payload['checked_evidence_refs'].append(diff_ref)
            diff=git(cwd,['diff','--no-ext-diff',payload['base_commit']+'..'+payload['candidate_commit']])
            items.append({'type':'commandExecution','command':'git diff '+payload['base_commit']+'..'+payload['candidate_commit'],'exit_code':0,'aggregated_output':diff})
        record={'status':'completed','sdk_version':'fake','native_version':None,'role':role,'model':model,'effort':effort,
            'sandbox_requested':'workspace-write' if role=='executor' else 'read-only',
            'thread_id':sid,'turn_id':'turn-'+sid,'duration_ms':7,'activity_counts':{'commandExecution':len(items)},
            'usage':{'total':{'input_tokens':10,'cached_input_tokens':8,'output_tokens':2,'total_tokens':12}},
            'items':items,'final_response':json.dumps(payload)}
        atomic_json(log,record)
        return {**{k:record[k] for k in ['model','effort','thread_id','turn_id','native_version','sdk_version','usage','duration_ms','activity_counts']},'payload':payload,'log':str(log)}


class RepoControllerTests(unittest.TestCase):
    def setUp(self):
        parent=ROOT/'.runtime/repo-controller-tests'
        parent.mkdir(parents=True,exist_ok=True)
        self.root=Path(tempfile.mkdtemp(dir=parent))
        self.source=self.root/'source';self.source.mkdir()
        (self.source/'calculator.py').write_bytes(b'def add(a,b):\n    return a - b\n')
        (self.source/'test_calculator.py').write_bytes(b'# fixed protected test input\n')
        git(self.source,['init','--initial-branch=main','--template='])
        git(self.source,['add','--','calculator.py','test_calculator.py'])
        git(self.source,['-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','--no-verify','-m','base'])
        self.base=git(self.source,['rev-parse','HEAD'])
        catalog={'unit':{'argv':['approved-fixture'],'timeout_seconds':1,'output_bytes_cap':4096,'write_scope':'scratch','network':'disabled','shell':False,'verification':'VERIFIED','evidence_sha256':'a'*64}}
        self.config={'engineering':{'enabled':True,'approved_repo_roots':[str(self.source)],'check_catalog':catalog,'max_turns':3,'max_repairs':1},'max_project_turns':3}
        self.c=Controller(self.root/'data',self.config)
        self.sdk=FakeSdk();self.sdk.c=self.c;self.c.repo_adapter=self.sdk
        self.statuses=['PASS'];self.checks_seen=[]
        def check(c,t,cid,cat,ctx):
            state=self.statuses.pop(0) if self.statuses else 'PASS'
            self.checks_seen.append(ctx['candidate_commit'])
            return {'status':state,'check_id':cid,'candidate_commit':ctx['candidate_commit'],
                    'input_hash':input_manifest(Path(ctx['snapshot_root']))['sha256'],'input_unchanged':True,'code':None}
        self.c.repo_check=check
        self.spec={'title':'small repo','tasks':[{'id':'fix','task_kind':KIND,'objective':'fix addition','acceptance_criteria':'add returns sum; tests unchanged',
            'repo_root':str(self.source),'base_commit':self.base,'allowed_changes':['calculator.py'],'checks':['unit']}]}

    def tearDown(self):
        self.c.db.close()
        # Keep these small, owned real Git fixtures; never recursively remove worktrees.

    def submit(self):
        self.pid=self.c.submit(self.spec,'round1-fixture')['project_id']
        return self.pid

    def task(self):
        return self.c.db.execute('SELECT * FROM tasks').fetchone()

    def test_controller_normal_path_exact_candidate_proof_and_no_extra_database(self):
        self.submit();self.assertTrue(self.c.run_one())
        t=self.task();self.assertEqual(t['state'],'ACCEPTED')
        proof=self.c.verify_task_accepted(t)
        self.assertEqual(proof['binding']['candidate_commit'],self.checks_seen[-1])
        self.assertEqual(git(self.source,['rev-parse','HEAD']),self.base)
        self.assertEqual([r[0] for r in self.sdk.roles],['executor','reviewer'])
        self.assertNotIn('fixture_runs',{r[0] for r in self.c.db.execute("SELECT name FROM sqlite_master WHERE type='table'")})

    def test_roles_and_usage_are_persisted_from_policy_not_business_constants(self):
        self.submit();self.c.run_one()
        policy=load_policy()['routes']
        for role,model,effort in self.sdk.roles:
            self.assertEqual((model,effort),(policy[role]['model'],policy[role]['reasoning_effort']))
        for row in self.c.db.execute('SELECT * FROM calls'):
            usage=json.loads(row['usage']);self.assertEqual(usage['effort'],'high')
            self.assertEqual(usage['duration_ms'],7);self.assertEqual(usage['total']['cached_input_tokens'],8)
            self.assertIsNotNone(row['completed'])

    def test_check_failure_never_calls_reviewer(self):
        self.statuses=['FAIL'];self.submit();self.c.run_one()
        self.assertEqual([r[0] for r in self.sdk.roles],['executor'])
        self.assertNotEqual(self.task()['state'],'ACCEPTED')

    def test_reviewer_failure_never_accepts_or_reuses_pass(self):
        self.sdk.verdict='FAIL';self.submit();self.c.run_one()
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(self.task()['error_class'],'NEEDS_REVIEW')
        self.assertIsNone(self.task()['acceptance_proof'])

    def test_repair_new_candidate_gets_new_check_and_review_within_three_turns(self):
        self.sdk.bad_first=True;self.statuses=['FAIL','PASS'];self.submit()
        self.c.run_one();self.c.run_one()
        self.assertEqual(self.task()['state'],'ACCEPTED')
        self.assertEqual(self.task()['attempt'],2)
        self.assertNotEqual(self.checks_seen[0],self.checks_seen[1])
        self.assertEqual([r[0] for r in self.sdk.roles],['executor','executor','reviewer'])
        self.assertEqual(self.c.verify_task_accepted(self.task())['binding']['attempt'],2)

    def test_git_change_invalidates_old_candidate_proof_and_acceptance(self):
        self.submit();self.c.run_one();t=self.task()
        root=Path(json.loads(t['acceptance_proof'])['workspace']['path'])
        (root/'calculator.py').write_text('def add(a,b):\n    return 0\n',encoding='utf-8')
        git(root,['add','--','calculator.py']);git(root,['-c','user.name=Synthetic','-c','user.email=fixture@example.invalid','commit','--no-verify','-m','new candidate'])
        with self.assertRaises(EvidenceChangedError):self.c.verify_task_accepted(t)
        self.assertEqual(self.c.audit_accepted(),1)
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')

    def test_environment_error_has_no_quality_retry_or_reviewer(self):
        self.statuses=['ERROR'];self.submit();self.c.run_one()
        self.assertEqual(self.task()['error_class'],'BLOCKED_ENVIRONMENT')
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(len(self.sdk.roles),1)

    def test_missing_reviewer_model_blocks_before_executor_no_downgrade(self):
        self.sdk.block='BLOCKED_MODEL: reviewer';self.submit();self.c.run_one()
        self.assertEqual(self.task()['error_class'],'BLOCKED_MODEL')
        self.assertEqual(self.sdk.roles,[])
        self.assertEqual(self.c.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],0)

    def test_wrong_check_candidate_is_rejected_before_review(self):
        old=self.c.repo_check
        def stale(*args):
            result=old(*args);result['candidate_commit']='0'*40;return result
        self.c.repo_check=stale;self.submit();self.c.run_one()
        self.assertNotEqual(self.task()['state'],'ACCEPTED');self.assertEqual(len(self.sdk.roles),1)

    def test_budget_cannot_repair_without_budget_for_new_reviewer(self):
        self.c.config['max_project_turns']=2;self.statuses=['FAIL'];self.submit()
        self.c.run_one();self.c.run_one()
        self.assertEqual(self.task()['error_class'],'NEEDS_REVIEW')
        self.assertEqual(len(self.sdk.roles),1)

    def test_repeated_submit_and_accepted_run_do_not_dispatch_extra_model(self):
        pid=self.submit();self.c.run_one()
        self.assertEqual(self.c.submit(self.spec,'round1-fixture')['project_id'],pid)
        self.assertFalse(self.c.run_one());self.assertEqual(len(self.sdk.roles),2)

    def test_gate_and_unauthorized_or_protected_paths_are_rejected(self):
        self.c.config['engineering']['enabled']=False
        with self.assertRaises(ValueError):self.c.submit(self.spec,'off')
        self.c.config['engineering']['enabled']=True
        self.spec['tasks'][0]['allowed_changes']=['.git/config']
        with self.assertRaises(ValueError):self.c.submit(self.spec,'protected')

    def test_review_proof_or_identity_tampering_is_not_acceptance(self):
        self.submit();self.c.run_one();t=self.task()
        proof=json.loads(t['acceptance_proof']);proof['reviewer_model']=load_policy()['routes']['executor']['model']
        atomic_json(self.c.task_dir(t)/'acceptance.json',proof)
        with self.c.immediate():self.c.db.execute('UPDATE tasks SET acceptance_proof=?,acceptance_proof_hash=? WHERE id=?',(json.dumps(proof),digest(proof),t['id']))
        with self.assertRaises(EvidenceChangedError):self.c.verify_task_accepted(self.task())

    def test_reviewer_reads_exact_frozen_task_and_check_receipt(self):
        self.submit();self.c.run_one();t=self.task()
        path=self.c.task_dir(t)
        checks=json.loads((path/'checks.json').read_bytes())
        meta=json.loads((path/'review-input.json').read_bytes())
        copy=json.loads((Path(meta['review_root'])/'.controller-review/checks.json').read_bytes())
        self.assertEqual(copy,checks)
        self.assertEqual(digest(checks),json.loads(t['acceptance_proof'])['binding']['check_receipt_hash'])

    def test_owner_loss_after_preflight_cannot_dispatch_or_change_new_owner(self):
        original=self.sdk.preflight
        def lose(*args,**kw):
            result=original(*args,**kw)
            with self.c.immediate():self.c.db.execute("UPDATE tasks SET owner='other-owner'")
            return result
        self.sdk.preflight=lose;self.submit();self.c.run_one()
        self.assertEqual(self.task()['owner'],'other-owner')
        self.assertEqual(self.sdk.roles,[])
        self.assertEqual(self.c.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],0)

    def test_sdk_import_environment_failure_is_not_a_quality_retry(self):
        def missing(*args,**kwargs):raise ImportError('synthetic missing SDK dependency')
        self.sdk.preflight=missing;self.submit();self.c.run_one()
        self.assertEqual(self.task()['error_class'],'BLOCKED_ENVIRONMENT')
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(self.sdk.roles,[])

    def test_completed_review_diff_reference_bug_reconciles_without_model_replay(self):
        self.submit();self.c.run_one();t=self.task();path=self.c.task_dir(t)
        candidate=json.loads(t['acceptance_proof'])['binding']['candidate_commit']
        meta=json.loads((path/'review-input.json').read_bytes())
        meta['read_hashes'].pop('git:'+self.base+'..'+candidate)
        atomic_json(path/'review-input.json',meta)
        atomic_json(path/'error.json',{'class':'REPO_EXECUTION_ERROR','detail':'INCOMPLETE_REVIEW'})
        with self.c.immediate():
            self.c.db.execute("UPDATE tasks SET state='NEEDS_DECISION',error_class='REPO_EXECUTION_ERROR',owner=NULL,lease_until=NULL,acceptance_proof=NULL,acceptance_proof_hash=NULL")
        proof=self.c.reconcile_completed_repo_review(t['id'])
        self.assertEqual(self.task()['state'],'ACCEPTED')
        self.assertEqual(proof['binding']['candidate_commit'],candidate)
        self.assertEqual(len(self.sdk.roles),2)
        self.assertEqual(self.c.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0],2)
        self.assertEqual(len(json.loads((path/'review-read-receipts.json').read_bytes())),5)

    def test_completed_review_reconciliation_never_overrides_reviewer_fail(self):
        self.sdk.verdict='FAIL';self.submit();self.c.run_one()
        with self.assertRaises(ValueError):self.c.reconcile_completed_repo_review(self.task()['id'])
        self.assertEqual(self.task()['error_class'],'NEEDS_REVIEW')
        self.assertNotEqual(self.task()['state'],'ACCEPTED')


if __name__=='__main__':unittest.main()
