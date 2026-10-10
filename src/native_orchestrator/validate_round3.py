"""One-shot final live acceptance via production Controller, never manual SDK turns.

Run with the already pinned SDK Python. Refuse existing evidence to prevent replay.
"""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from native_orchestrator.check_runner import input_manifest
from native_orchestrator.model_policy import load_policy
from native_orchestrator.orchestrator import Controller
from native_orchestrator.repo_execution import KIND, git

ROOT = Path(__file__).resolve().parents[2]


def main():
    area = ROOT/'.runtime/frame006-round3-live-20261010'
    if area.exists():
        raise RuntimeError('Existing live acceptance must be reconciled, never replayed')
    if git(ROOT, ['status','--porcelain']):
        raise RuntimeError('Freeze and commit the framework before live validation')
    area.mkdir()
    source = area/'source'
    source.mkdir()
    (source/'calculator.py').write_bytes(b'def add(a, b):\n    return a - b\n')
    (source/'test_calculator.py').write_bytes(
        b'import unittest\nfrom calculator import add\n\nclass Addition(unittest.TestCase):\n'
        b'    def test_positive(self):\n        self.assertEqual(add(2, 3), 5)\n'
        b'    def test_negative(self):\n        self.assertEqual(add(-2, 3), 1)\n'
        b'    def test_zero(self):\n        self.assertEqual(add(0, 4), 4)\n')
    git(source, ['init','--initial-branch=main','--template='])
    git(source, ['add','--','calculator.py','test_calculator.py'])
    git(source, ['-c','user.name=FRAME006 Fixture','-c','user.email=frame006@example.invalid',
                 'commit','--no-verify','--no-gpg-sign','-m','Synthetic addition defect'])
    base = git(source, ['rev-parse','HEAD'])
    protected_hash = hashlib.sha256((source/'test_calculator.py').read_bytes()).hexdigest()
    python = Path('E:/python/python.exe')
    baseline = subprocess.run([str(python),'-B','-m','unittest','-q'],cwd=source,capture_output=True,timeout=30)
    if baseline.returncode != 1:
        raise ValueError('Fixture must expose the intended defect before execution')
    capability = ROOT/'.runtime/root-selftest-20261009-07ebf6a228/native-validation/report.json'
    catalog = {'unit':{'argv':[str(python),'-B','-m','unittest','-q','test_calculator.py'],
        'timeout_seconds':30,'output_bytes_cap':4096,'write_scope':'scratch','network':'disabled','shell':False,
        'verification':'VERIFIED','evidence_sha256':hashlib.sha256(capability.read_bytes()).hexdigest()}}
    config = {'engineering':{'enabled':True,'approved_repo_roots':[str(source)],'check_python':str(python),
        'check_catalog':catalog,'max_turns':3,'max_repairs':1},
        'max_project_turns':3,'max_master_turns':0,'timeout_seconds':150}
    c = Controller(area/'controller-data',config)
    report = {'source_code_commit':git(ROOT,['rev-parse','HEAD']), 'fresh_fixture':True,
              'api':'Controller.submit/run_one/verify_task_accepted/promote_repo_task',
              'remote_used':False,'system_config_acl_runtime_modified':False}
    try:
        spec = {'title':'FRAME006 final Controller acceptance','tasks':[{'id':'addition','task_kind':KIND,
            'objective':'Fix add(a,b) in calculator.py to return the sum.',
            'acceptance_criteria':'Positive, negative and zero additions return the sum; test_calculator.py stays unchanged; only calculator.py changes.',
            'repo_root':str(source),'base_commit':base,'allowed_changes':['calculator.py'],'checks':['unit']}]}
        c.submit(spec,'frame006-round3-live-20261010')
        for _ in range(2):
            if not c.run_one():
                break
            if c.db.execute('SELECT state FROM tasks').fetchone()[0] != 'PENDING':
                break
        task = c.db.execute('SELECT * FROM tasks').fetchone()
        report.update(task_id=task['id'],state=task['state'],error_class=task['error_class'],attempt=task['attempt'])
        if task['state'] == 'ACCEPTED':
            proof = c.verify_task_accepted(task)
            directory = c.task_dir(task)
            candidate = json.loads((directory/'candidate.json').read_bytes())
            checks = json.loads((directory/'checks.json').read_bytes())
            review = json.loads((directory/'review.json').read_bytes())
            promotion = c.promote_repo_task(task['id'])
            identities = {'candidate':candidate['candidate_commit'], 'checks':checks['binding']['candidate_commit'],
                          'review':review['candidate_commit'], 'acceptance':proof['binding']['candidate_commit'],
                          'promotion':promotion['candidate_commit'], 'main':git(source,['rev-parse','HEAD'])}
            if len(set(identities.values())) != 1 or checks['status'] != 'PASS' or review['verdict'] != 'PASS':
                raise ValueError('Candidate identities or gates disagree')
            if git(source,['status','--porcelain']) or protected_hash != hashlib.sha256((source/'test_calculator.py').read_bytes()).hexdigest():
                raise ValueError('Protected fixture or promoted checkout changed')
            report.update(status='PASS',identities=identities,candidate_tree_hash=candidate['candidate_tree_hash'],
                acceptance_receipt=str(directory/'acceptance.json'),proof_hash=digest_bytes(directory/'acceptance.json'),
                role_runtime=proof['role_runtime'],proof_schema=proof['schema_version'],evidence_status=proof['evidence_status'],
                fresh_reviewer=proof['executor_session_id']!=proof['reviewer_session_id'],fixture_main_clean=True,
                source_unchanged=git(ROOT,['status','--porcelain'])=='')
        else:
            report['status']='BLOCKED'
            error=c.task_dir(task)/'error.json'
            report['error_detail']=json.loads(error.read_bytes()) if error.is_file() else None
    finally:
        calls = [dict(x) for x in c.db.execute('SELECT * FROM calls')]
        report.update(reserved_model_turns=len(calls),completed_model_turns=sum(x['completed'] is not None for x in calls),
            roles=[{'role':x['role'],'model':x['model'],'session_id':x['session_id'],
                    'usage':json.loads(x['usage']) if x['usage'] else None} for x in calls],
            model_policy_sha256=load_policy()['sha256'])
        (area/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        c.db.close()
    print(json.dumps(report,ensure_ascii=False))
    if report['reserved_model_turns']>3 or report.get('status')!='PASS':
        raise SystemExit(1)


def digest_bytes(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__=='__main__':
    main()
