"""Round 2: real local Git/SQLite, synthetic SDK, deterministic fault injection."""
import json
import os
import subprocess
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from native_orchestrator import repo_execution as execution
from native_orchestrator import repo_promotion as promotion
import test_repo_controller as fixture
from native_orchestrator.orchestrator import Controller, EvidenceChangedError, atomic_json
from native_orchestrator.check_runner import input_manifest
from native_orchestrator.repo_execution import git

ROOT = Path(__file__).resolve().parents[1]


class Crash(BaseException):
    pass


class Round2Tests(unittest.TestCase):
    def setUp(self):
        fixture.ROOT = ROOT
        fixture.RepoControllerTests.setUp(self)

    tearDown = fixture.RepoControllerTests.tearDown
    submit = fixture.RepoControllerTests.submit
    task = fixture.RepoControllerTests.task

    def restart(self):
        self.c.db.execute('UPDATE tasks SET lease_until=0 WHERE owner IS NOT NULL')
        self.c.db.commit()
        check = self.c.repo_check
        self.c.db.close()
        self.c = Controller(self.root/'data',self.config)
        self.c.repo_adapter = self.sdk
        self.sdk.c = self.c
        self.c.repo_check = check

    def crash_at(self, point):
        self.submit()
        original = execution.write
        def write(c,t,path,value):
            if point == 'B' and path.name == 'candidate.json':
                raise Crash('commit completed before receipt')
            result = original(c,t,path,value)
            if (point == 'C' and path.name == 'checks.json') or (point == 'E' and path.name == 'acceptance.json'):
                raise Crash(point)
            return result
        def crash(*args,**kwargs):
            raise Crash(point)
        with patch.object(execution,'write',write):
            with patch.object(execution,'freeze' if point == 'A' else 'finish_review',crash) if point in ('A','D') else patch.object(execution,'KIND',execution.KIND):
                with self.assertRaises(Crash):
                    self.c.run_one()
        self.restart()

    def assert_recovered(self,checks):
        self.assertEqual(self.c.recover(),1)
        self.assertEqual(self.task()['state'],'ACCEPTED')
        self.c.verify_task_accepted(self.task())
        self.assertEqual([r[0] for r in self.sdk.roles],['executor','reviewer'])
        self.assertEqual(len(self.checks_seen),checks)
        self.assertEqual(self.c.recover(),0)
        self.assertFalse(self.c.run_one())

    def test_crash_A_uncommitted_executor_edits_preserved_without_replay(self):
        self.crash_at('A')
        self.c.recover()
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(self.task()['error_class'],'NEEDS_RECONCILIATION')
        self.assertEqual(len(self.sdk.roles),1)
        path = Path(json.loads((self.c.task_dir(self.task())/'workspace.json').read_bytes())['path'])
        self.assertIn('return a + b',(path/'calculator.py').read_text())
        self.assertTrue(git(path,['status','--porcelain']))
        self.assertFalse(self.c.run_one())

    def test_crash_B_commit_without_candidate_receipt_reconstructed_from_intent(self):
        self.crash_at('B')
        self.assert_recovered(1)

    def test_crash_B_candidate_receipt_without_checks_rechecks(self):
        self.submit()
        with patch.object(execution,'run_candidate',side_effect=Crash('before checks')):
            with self.assertRaises(Crash):self.c.run_one()
        self.restart()
        self.assert_recovered(1)

    def test_crash_C_pass_checks_without_reviewer_reuses_exact_checks(self):
        self.crash_at('C')
        self.assert_recovered(1)

    def test_crash_D_completed_reviewer_without_acceptance_not_replayed(self):
        self.crash_at('D')
        self.assert_recovered(1)

    def test_crash_E_acceptance_without_database_finalize_revalidated(self):
        self.crash_at('E')
        self.assert_recovered(1)

    def test_crash_E_tampered_acceptance_is_never_repaired_by_guess(self):
        self.crash_at('E')
        path = self.c.task_dir(self.task())/'acceptance.json'
        proof = json.loads(path.read_bytes());proof['binding']['candidate_commit']='0'*40
        atomic_json(path,proof)
        self.c.recover()
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(len(self.sdk.roles),2)

    def test_crash_C_stale_pass_not_rebound_to_changed_candidate(self):
        self.crash_at('C')
        path = self.c.task_dir(self.task())/'checks.json'
        checks = json.loads(path.read_bytes());checks['binding']['candidate_commit']='0'*40
        atomic_json(path,checks)
        self.c.recover()
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(len(self.sdk.roles),1)

    def test_interrupted_unknown_reviewer_dispatch_is_not_replayed(self):
        self.submit()
        original = self.sdk.run
        def interrupt(role,*args,**kwargs):
            if role == 'reviewer':
                kwargs['before_turn']('unknown-reviewer')
                raise Crash('unknown external result')
            return original(role,*args,**kwargs)
        with patch.object(self.sdk,'run',interrupt):
            with self.assertRaises(Crash):self.c.run_one()
        self.restart();self.c.recover()
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(self.task()['error_class'],'NEEDS_RECONCILIATION')
        self.assertEqual(len(self.sdk.roles),1)
        self.assertFalse(self.c.run_one())

    def test_live_owner_is_not_stolen(self):
        self.crash_at('C')
        self.c.db.execute('UPDATE tasks SET lease_until=?',(__import__('time').time()+60,));self.c.db.commit()
        self.assertEqual(self.c.recover(),0)
        self.assertEqual(len(self.sdk.roles),1)

    def test_zero_budget_at_start_does_not_start_sdk(self):
        self.config['max_project_turns']=0
        self.c.config['max_project_turns']=0
        self.submit();self.c.run_one()
        self.assertEqual(self.sdk.roles,[])
        self.assertEqual(self.task()['error_class'],'NEEDS_REVIEW')

    def test_zero_remaining_budget_after_checks_preserves_candidate_and_evidence(self):
        self.crash_at('C')
        directory = self.c.task_dir(self.task())
        before = {name:(directory/name).read_bytes() for name in ('candidate.json','checks.json')}
        self.c.config['max_project_turns']=1
        self.c.recover()
        self.assertEqual(self.task()['error_class'],'NEEDS_REVIEW')
        self.assertEqual(len(self.sdk.roles),1)
        for name,data in before.items():self.assertEqual((directory/name).read_bytes(),data)

    def external_commit(self,path,content):
        (self.source/path).write_bytes(content)
        git(self.source,['add','--',path])
        git(self.source,['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--no-verify','--no-gpg-sign','-m','other task'])
        return git(self.source,['rev-parse','HEAD'])

    def ready(self):
        self.submit();self.c.run_one()
        self.assertEqual(self.task()['state'],'ACCEPTED')
        return self.c.verify_task_accepted(self.task())

    def change_main(self):
        return self.external_commit('test_calculator.py',b'# main C: independent protected fixture update\n')

    def test_main_change_B1_rejected_B2_new_checks_review_then_promoted(self):
        b1 = self.ready()
        old_dir = self.c.task_dir(self.task())
        main_c = self.change_main()
        with self.assertRaisesRegex(ValueError,'EXPECTED_MAIN_CHANGED'):
            self.c.promote_repo_task(self.task()['id'])
        self.assertEqual(self.c.integrate_repo_main(self.task()['id']),'ACCEPTED')
        t=self.task();b2=self.c.verify_task_accepted(t)
        self.assertNotEqual(b1['binding']['candidate_commit'],b2['binding']['candidate_commit'])
        self.assertEqual(b2['binding']['attempt'],2)
        self.assertEqual(len(self.checks_seen),2)
        self.assertEqual([r[0] for r in self.sdk.roles],['executor','reviewer','reviewer'])
        self.assertTrue((old_dir/'acceptance.json').is_file())
        receipt=self.c.promote_repo_task(t['id'])
        self.assertEqual(receipt['expected_main'],main_c)
        self.assertEqual(git(self.source,['rev-parse','HEAD']),b2['binding']['candidate_commit'])
        self.assertEqual(git(self.source,['status','--porcelain']),'')

    def test_text_conflict_keeps_both_task_worktrees_and_stops(self):
        b1=self.ready()
        # Task A is a separate branch/worktree from the same main.
        a=self.root/'task-a'
        git(self.source,['worktree','add','-b','fixture-task-a',str(a),self.base])
        (a/'calculator.py').write_bytes(b'def add(a,b):\n    return a + b + 0\n')
        git(a,['add','--','calculator.py'])
        git(a,['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--no-verify','-m','task A'])
        git(self.source,['merge','--ff-only','fixture-task-a'])
        self.assertEqual(self.c.integrate_repo_main(self.task()['id']),'NEEDS_DECISION')
        t=self.task();self.assertEqual(t['error_class'],'GIT_TEXT_CONFLICT')
        descriptor=json.loads((self.c.task_dir(t)/'workspace.json').read_bytes())
        b=Path(descriptor['path'])
        self.assertTrue(git(b,['ls-files','-u']))
        self.assertTrue(a.exists());self.assertTrue(Path(b1['workspace']['path']).exists())
        self.assertIsNone(t['acceptance_proof'])
        self.assertEqual(len(self.sdk.roles),2)
        with self.assertRaises(EvidenceChangedError):self.c.promote_repo_task(t['id'])

    def test_semantic_conflict_merges_cleanly_but_real_deterministic_tests_fail(self):
        # Module 1 owns the return convention; module 2 starts using it in task B.
        self.external_commit('api.py',b'def value():\n    return 3\n')
        self.external_commit('calculator.py',b'from api import value\ndef add(a,b):\n    return value() - b\n')
        self.external_commit('test_calculator.py',b'from calculator import add\nassert add(3,2)==5\n')
        self.base=git(self.source,['rev-parse','HEAD']);self.spec['tasks'][0]['base_commit']=self.base
        original=self.sdk.run
        def executor(role,*args,**kwargs):
            result=original(role,*args,**kwargs)
            if role=='executor':Path(args[2],'calculator.py').write_bytes(b'from api import value\ndef add(a,b):\n    return value() + b\n')
            return result
        def check(c,t,cid,cat,ctx):
            completed=subprocess.run([sys.executable,'-B','test_calculator.py'],cwd=ctx['snapshot_root'],capture_output=True,timeout=10)
            self.checks_seen.append(ctx['candidate_commit'])
            return {'status':'PASS' if completed.returncode==0 else 'FAIL','check_id':cid,'candidate_commit':ctx['candidate_commit'],
                    'input_hash':input_manifest(Path(ctx['snapshot_root']))['sha256'],'input_unchanged':True,'code':'CODE_CHECK_FAILED' if completed.returncode else None}
        self.c.repo_check=check
        with patch.object(self.sdk,'run',executor):self.ready()
        self.external_commit('api.py',b'def value():\n    return {"value":3}\n')
        self.assertEqual(self.c.integrate_repo_main(self.task()['id']),'NEEDS_DECISION')
        t=self.task();self.assertEqual(t['error_class'],'CODE_CHECK_FAILED')
        path=Path(json.loads((self.c.task_dir(t)/'workspace.json').read_bytes())['path'])
        self.assertEqual(git(path,['ls-files','-u']),'')
        self.assertEqual(json.loads((self.c.task_dir(t)/'checks.json').read_bytes())['status'],'FAIL')
        self.assertEqual(len(self.sdk.roles),2)
        self.assertIsNone(t['acceptance_proof'])

    def test_candidate_change_invalidates_checks_review_and_proof(self):
        proof=self.ready();task_id=self.task()['id']
        path=Path(proof['workspace']['path'])
        (path/'calculator.py').write_bytes(b'def add(a,b):\n    return 0\n')
        git(path,['add','--','calculator.py'])
        git(path,['-c','user.name=Fixture','-c','user.email=fixture@example.invalid','commit','--no-verify','-m','candidate drift'])
        with self.assertRaises(EvidenceChangedError):self.c.promote_repo_task(task_id)
        self.assertEqual(self.c.audit_accepted(),1)
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(git(self.source,['rev-parse','HEAD']),self.base)

    def test_promotion_repeated_after_restart_does_not_repeat_git_cas(self):
        self.ready();task_id=self.task()['id']
        first=self.c.promote_repo_task(task_id)
        self.restart()
        with patch.object(promotion,'git',wraps=git) as operations:
            self.assertEqual(self.c.promote_repo_task(task_id),first)
        self.assertFalse(any(call.args[1][0]=='update-ref' for call in operations.call_args_list))
        self.assertEqual(len(self.sdk.roles),2)

    def test_promotion_crash_after_git_cas_before_worktree_update_recovers(self):
        proof=self.ready();task_id=self.task()['id']
        def crash(root,args,before=None):
            result=git(root,args,before)
            if args[0]=='update-ref':raise Crash('after CAS')
            return result
        with patch.object(promotion,'git',crash):
            with self.assertRaises(Crash):self.c.promote_repo_task(task_id)
        self.restart()
        self.c.promote_repo_task(task_id)
        self.assertEqual(git(self.source,['status','--porcelain']),'')
        self.assertEqual(git(self.source,['rev-parse','HEAD']),proof['binding']['candidate_commit'])

    def test_promotion_crash_after_receipt_before_db_event_recovers(self):
        self.ready();task_id=self.task()['id']
        original=self.c.event
        def crash(project,task,kind):
            if kind.startswith('PROMOTED_'):raise Crash('DB finalization')
            return original(project,task,kind)
        with patch.object(self.c,'event',crash):
            with self.assertRaises(Crash):self.c.promote_repo_task(task_id)
        self.restart();self.c.promote_repo_task(task_id)
        self.assertEqual(git(self.source,['status','--porcelain']),'')
        self.assertEqual(self.c.db.execute("SELECT COUNT(*) FROM events WHERE task_id=? AND kind='PROMOTED_1'",(task_id,)).fetchone()[0],1)

    def test_ff_only_is_insufficient_expected_main_rejects_intermediate_ancestor(self):
        proof=self.ready()
        # Advance main to the already accepted candidate: ff-only would succeed.
        git(self.source,['merge','--ff-only',proof['binding']['candidate_commit']])
        with self.assertRaisesRegex(ValueError,'EXPECTED_MAIN_CHANGED'):
            self.c.promote_repo_task(self.task()['id'])

    def test_actual_git_cas_rejects_race_after_final_main_read(self):
        self.ready();task_id=self.task()['id']
        competing=[None]
        def race(root,args,before=None):
            if args[0]=='update-ref':
                competing[0]=self.change_main()
            return git(root,args,before)
        with patch.object(promotion,'git',race):
            with self.assertRaisesRegex(RuntimeError,'GIT_OPERATION_FAILED'):
                self.c.promote_repo_task(task_id)
        self.assertEqual(git(self.source,['rev-parse','HEAD']),competing[0])
        self.assertFalse((self.c.task_dir(self.task())/'promotion.json').exists())

    def test_os_promotion_lock_serializes_different_controllers_and_databases(self):
        self.ready();task_id=self.task()['id']
        code='from native_orchestrator.repo_promotion import promotion_lock; import sys;\nwith promotion_lock(sys.argv[1]):\n print("LOCKED",flush=True); sys.stdin.readline()'
        child=subprocess.Popen([sys.executable,'-B','-c',code,str(self.source)],cwd=Path(execution.__file__).parent.parent,
                               stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        try:
            self.assertEqual(child.stdout.readline().strip(),'LOCKED')
            with self.assertRaisesRegex(RuntimeError,'PROMOTION_BUSY'):
                self.c.promote_repo_task(task_id)
        finally:
            child.communicate('\n',timeout=10)
        self.c.promote_repo_task(task_id)

    def test_promotion_preserves_unknown_dirty_main(self):
        self.ready()
        (self.source/'calculator.py').write_bytes(b'# unknown user modification\n')
        with self.assertRaises(ValueError):self.c.promote_repo_task(self.task()['id'])
        self.assertEqual((self.source/'calculator.py').read_bytes(),b'# unknown user modification\n')

    def test_integration_budget_exhausted_preserves_B2_and_new_checks_not_old_review(self):
        self.ready();self.change_main()
        self.c.config['max_project_turns']=2
        self.c.integrate_repo_main(self.task()['id'])
        t=self.task();self.assertEqual(t['state'],'NEEDS_DECISION');self.assertEqual(t['error_class'],'NEEDS_REVIEW')
        self.assertIsNone(t['acceptance_proof']);self.assertIsNone(t['review_ref'])
        self.assertEqual(len(self.sdk.roles),2)
        self.assertEqual(len(self.checks_seen),2)
        self.assertTrue((self.c.task_dir(t)/'candidate.json').is_file())

    def test_recovery_environment_error_never_calls_reviewer(self):
        self.crash_at('B');self.statuses=['ERROR']
        self.c.recover()
        self.assertEqual(self.task()['error_class'],'BLOCKED_ENVIRONMENT')
        self.assertEqual(len(self.sdk.roles),1)

    def test_partial_check_dispatch_rechecks_in_new_scratch_generation(self):
        self.submit()
        seen=[]
        original=self.c.repo_check
        def crash(c,t,cid,cat,ctx):
            seen.append(ctx['scratch_root'])
            raise Crash('check result not persisted')
        self.c.repo_check=crash
        with self.assertRaises(Crash):self.c.run_one()
        self.restart()
        def check(c,t,cid,cat,ctx):
            seen.append(ctx['scratch_root'])
            return original(c,t,cid,cat,ctx)
        self.c.repo_check=check
        self.assert_recovered(1)
        self.assertEqual(len(seen),2);self.assertNotEqual(seen[0],seen[1])

    def test_completed_reviewer_log_reconciles_unfinished_call_ledger(self):
        self.crash_at('D')
        self.c.db.execute("UPDATE calls SET completed=NULL,usage=NULL WHERE role='reviewer'");self.c.db.commit()
        self.assert_recovered(1)
        self.assertIsNotNone(self.c.db.execute("SELECT completed FROM calls WHERE role='reviewer'").fetchone()[0])

    def test_two_ready_tasks_share_promotion_lock_and_loser_cannot_promote_B1(self):
        self.ready()
        other=Controller(self.root/'other-data',self.config)
        other.repo_adapter=fixture.FakeSdk();other.repo_check=self.c.repo_check
        try:
            pid=other.submit(self.spec,'independent-task')['project_id'];other.run_one()
            other_id=pid+':fix'
            self.assertEqual(other.db.execute('SELECT state FROM tasks WHERE id=?',(other_id,)).fetchone()[0],'ACCEPTED')
            with promotion.promotion_lock(self.source):
                with self.assertRaisesRegex(RuntimeError,'PROMOTION_BUSY'):other.promote_repo_task(other_id)
            self.c.promote_repo_task(self.task()['id'])
            with self.assertRaisesRegex(ValueError,'EXPECTED_MAIN_CHANGED'):other.promote_repo_task(other_id)
            self.assertEqual(len(other.repo_adapter.roles),2)
        finally:
            other.db.close()

    def test_recovery_changed_worktree_preserves_new_bytes_and_never_replays(self):
        self.crash_at('C')
        descriptor=json.loads((self.c.task_dir(self.task())/'workspace.json').read_bytes())
        path=Path(descriptor['path'])/'calculator.py'
        path.write_bytes(b'# intervening user edit\n')
        self.c.recover()
        self.assertEqual(self.task()['state'],'NEEDS_DECISION')
        self.assertEqual(path.read_bytes(),b'# intervening user edit\n')
        self.assertEqual(len(self.sdk.roles),1)


if __name__ == '__main__':
    unittest.main()
