"""One owned engineering fixture, not a production queue or generic Git service."""
import argparse
import hashlib
import json
import os
import subprocess
import sqlite3
import sys
import time
import uuid
from pathlib import Path

from codex_sdk_adapter import CodexSdkAdapter
from orchestrator import Controller, atomic_json, digest, encode
from check_runner import input_manifest, run_check

ROOT = Path(__file__).resolve().parent
PILOT = ROOT / '.runtime/sdk-direct-pilot-20261010-52a7'
MODEL = 'gpt-6-luna'
SYSTEM_PYTHON = Path('E:/python/python.exe')
WORKER_SCHEMA = {'type': 'object', 'properties': {'summary': {'type': 'string', 'maxLength': 400}},
                 'required': ['summary'], 'additionalProperties': False}


def git(root, *args):
    env = os.environ.copy()
    for key in list(env):
        if key.upper().startswith('GIT_'):
            env.pop(key)
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_LITERAL_PATHSPECS='1', GIT_TERMINAL_PROMPT='0')
    cmd = ['git', '-c', 'core.hooksPath=NUL', '-c', 'commit.gpgSign=false', '-c', 'core.autocrlf=false',
           '-c', 'user.name=SDK Fixture', '-c', 'user.email=sdk-fixture@example.invalid', '-C', str(root), *args]
    value = subprocess.run(cmd, env=env, capture_output=True, timeout=30)
    if value.returncode:
        raise RuntimeError('GIT_OPERATION_FAILED: ' + value.stderr.decode('utf-8', 'replace')[:400])
    return value.stdout.decode('utf-8').rstrip('\r\n')


def check_only(path):
    packet = json.loads(Path(path).read_text(encoding='utf-8'))
    catalog = {'unit': {'argv': [sys.executable, '-B', '-m', 'unittest', '-q', 'test_calculator.py'],
        'timeout_seconds': 30, 'output_bytes_cap': 4096, 'write_scope': 'scratch', 'network': 'disabled',
        'shell': False, 'verification': 'VERIFIED', 'evidence_sha256': packet['capability_sha256']}}
    observer = sqlite3.connect((Path(packet['context']['control_root']) / 'state.sqlite').as_uri() + '?mode=ro', uri=True)
    def authority():
        row = observer.execute('SELECT owner,lease_until,state FROM fixture_runs WHERE id=?', (packet['project_id'],)).fetchone()
        return row is not None and row[0] == packet['owner'] and row[1] > time.time() and row[2] == 'CANDIDATE'
    try:
        receipt = run_check('unit', catalog, packet['context'], before_dispatch=authority)
    finally:
        observer.close()
    print(json.dumps({'status': receipt['status'], 'code': receipt['code']}))


def run():
    if PILOT.exists():
        raise RuntimeError('RECONCILIATION_REQUIRED: existing pilot cannot be replayed')
    PILOT.mkdir()
    source, task, data = [PILOT / n for n in ('source', 'task', 'control')]
    source.mkdir()
    (source / 'calculator.py').write_bytes(b'def add(a, b):\n    return a - b\n')
    (source / 'test_calculator.py').write_bytes(b'import unittest\nfrom calculator import add\n\nclass Addition(unittest.TestCase):\n    def test_positive(self):\n        self.assertEqual(add(2, 3), 5)\n    def test_negative(self):\n        self.assertEqual(add(-2, 3), 1)\n    def test_zero(self):\n        self.assertEqual(add(0, 4), 4)\n')
    git(source, 'init', '--initial-branch=main', '--template=')
    git(source, 'add', '--', 'calculator.py', 'test_calculator.py')
    git(source, 'commit', '--no-gpg-sign', '--no-verify', '-m', 'Synthetic addition defect')
    base = git(source, 'rev-parse', 'HEAD')
    original = input_manifest(source)
    baseline = subprocess.run([str(SYSTEM_PYTHON), '-B', '-m', 'unittest', '-q'], cwd=source, capture_output=True, timeout=30)
    if baseline.returncode != 1:
        raise RuntimeError('FIXTURE_BASELINE_NOT_EXPECTED_FAILURE')
    branch = 'task/sdk-direct-pilot-20261010-52a7'
    git(source, 'worktree', 'add', '-b', branch, str(task), base)
    config = {'executor': {'client': 'mock', 'model': 'mock-executor'},
              'reviewer': {'client': 'mock', 'model': 'mock-reviewer'}, 'max_project_turns': 3}
    controller = Controller(data, config)
    project, owner = 'sdk-fixture-52a7', str(uuid.uuid4())
    packet = {'project_id': project, 'task_id': 'calculator', 'spec_version': 1, 'attempt': 1,
              'base_commit': base, 'allowed_changes': ['calculator.py'], 'model': MODEL, 'effort': 'max', 'max_turns': 3}
    binding = {k: packet[k] for k in ('project_id', 'task_id', 'spec_version', 'attempt')}
    binding['contract_hash'] = digest(packet)
    with controller.immediate():
        controller.db.execute('INSERT INTO projects VALUES(?,?,?,?,?,?)', (project, project, digest(packet), encode(packet), 1, time.time()))
        controller.db.execute('CREATE TABLE fixture_runs(id TEXT PRIMARY KEY, owner TEXT, lease_until REAL, state TEXT, candidate TEXT, receipt_hash TEXT)')
        controller.db.execute('INSERT INTO fixture_runs VALUES(?,?,?,?,?,?)', (project, owner, time.time() + 600, 'EXECUTING', None, None))

    def authority():
        row = controller.db.execute('SELECT * FROM fixture_runs WHERE id=?', (project,)).fetchone()
        return row is not None and row['owner'] == owner and row['lease_until'] > time.time() and row['state'] not in ('ACCEPTED', 'NEEDS_DECISION')

    def stage(state, candidate=None, receipt_hash=None):
        with controller.immediate():
            if not authority():
                raise RuntimeError('AUTHORITY_LOST')
            controller.db.execute('UPDATE fixture_runs SET state=?,candidate=COALESCE(?,candidate),receipt_hash=COALESCE(?,receipt_hash) WHERE id=?',
                                  (state, candidate, receipt_hash, project))

    def turn_intent(role, thread_id):
        with controller.immediate():
            if not authority():
                return False
            call = controller.reserve_call(project, project + ':calculator', role, MODEL)
            controller.db.execute('UPDATE calls SET session_id=? WHERE id=?', (thread_id, call))
        return True

    def invoke(role, prompt, cwd, schema, name):
        result = CodexSdkAdapter().run(role, MODEL, prompt, str(cwd), data / (name + '.json'),
            schema=schema, before_dispatch=authority, before_turn=lambda sid: turn_intent(role, sid))
        with controller.immediate():
            if not authority():
                raise RuntimeError('AUTHORITY_LOST')
            controller.db.execute('UPDATE calls SET completed=?,usage=? WHERE session_id=?',
                                  (time.time(), encode(result['usage']), result['thread_id']))
        return result

    report = {'status': 'STARTING', 'scope': 'OWNED_FIXTURE_SLICE_ONLY', 'production_queue_enabled': False,
              'base_commit': base, 'task_branch': branch, 'baseline_quality_failure_observed': True, 'model_turns': 0}
    try:
        worker = invoke('executor', 'Fix add(a,b) in calculator.py to return the sum. Read the actual files. '
            'Only calculator.py may change. Do not change tests, create files, commit, use network or agents. '
            'Reply as JSON with a brief summary.', task, WORKER_SCHEMA, 'executor')
        if set(worker['payload']) != {'summary'} or not isinstance(worker['payload']['summary'], str) or len(worker['payload']['summary']) > 400:
            raise RuntimeError('INVALID_WORKER_RESPONSE')
        for attempt in (1, 2):
            if not authority() or git(task, 'branch', '--show-current') != branch or git(source, 'rev-parse', 'main') != base:
                raise RuntimeError('AUTHORITY_OR_GIT_DRIFT')
            changed = git(task, 'diff', '--name-only', base).splitlines()
            if changed != ['calculator.py'] or git(task, 'ls-files', '--others', '--exclude-standard') or git(task, 'ls-files', '--others', '--ignored', '--exclude-standard'):
                raise RuntimeError('UNAPPROVED_DIFF')
            if (task / 'test_calculator.py').read_bytes() != (source / 'test_calculator.py').read_bytes():
                raise RuntimeError('PROTECTED_TEST_DRIFT')
            if any(mode.split()[0] != '100644' for mode in git(task, 'ls-files', '-s').splitlines()):
                raise RuntimeError('UNSUPPORTED_GIT_ENTRY')
            input_manifest(task)
            git(task, 'add', '--', 'calculator.py')
            git(task, 'commit', '--no-verify', '--no-gpg-sign', '-m', 'Fix synthetic addition defect')
            candidate = git(task, 'rev-parse', 'HEAD')
            snapshot = input_manifest(task)
            stage('CANDIDATE', candidate)
            scratch, evidence = [PILOT / (n + str(attempt)) for n in ('scratch', 'evidence')]
            scratch.mkdir()
            context = dict(binding=binding, candidate_commit=candidate, snapshot_root=str(task), scratch_root=str(scratch),
                           control_root=str(data), evidence_root=str(evidence))
            check_packet = {'context': context, 'owner': owner, 'project_id': project,
                'capability_sha256': hashlib.sha256((ROOT / '.runtime/root-selftest-20261009-07ebf6a228/native-validation/report.json').read_bytes()).hexdigest()}
            atomic_json(data / ('check-packet' + str(attempt) + '.json'), check_packet)
            child = subprocess.run([str(SYSTEM_PYTHON), '-B', str(Path(__file__).resolve()), '--check-only', str(data / ('check-packet' + str(attempt) + '.json'))],
                cwd=ROOT, capture_output=True, timeout=90)
            (data / ('check-launch' + str(attempt) + '.txt')).write_bytes(child.stdout + child.stderr)
            if child.returncode or not (evidence / 'receipt.json').is_file():
                raise RuntimeError('BLOCKED_ENVIRONMENT_CHECK_LAUNCH')
            checks = json.loads((evidence / 'receipt.json').read_text(encoding='utf-8'))
            if checks['candidate_commit'] != candidate or not checks['input_unchanged'] or input_manifest(task) != snapshot:
                raise RuntimeError('CHECK_BINDING_DRIFT')
            if checks['status'] == 'ERROR':
                raise RuntimeError('BLOCKED_ENVIRONMENT_OR_CHECK_ERROR: ' + str(checks['code']))
            if checks['status'] == 'PASS':
                break
            if attempt == 2:
                raise RuntimeError('QUALITY_FAIL_REPAIR_LIMIT')
            stage('EXECUTING')
            repair = (evidence / 'stderr.txt').read_text(encoding='utf-8')[:1000]
            invoke('executor', 'The approved tests failed. Fix only calculator.py once, keeping all tests fixed. '
                'Do not commit or use external services. Failure: ' + repair, task, WORKER_SCHEMA, 'repair')
        check_sha = hashlib.sha256((evidence / 'receipt.json').read_bytes()).hexdigest()
        stage('CHECKED', candidate, check_sha)
        review_root = PILOT / 'review'
        git(source, 'worktree', 'add', '--detach', str(review_root), candidate)
        bound = dict(binding, base_commit=base, candidate_commit=candidate, input_hash=snapshot['sha256'], check_receipt_sha256=check_sha)
        fields = {k: {'type': 'integer' if type(v) is int else 'string', 'enum': [v]} for k, v in bound.items()}
        fields.update(verdict={'type': 'string', 'enum': ['PASS', 'FAIL']}, findings={'type': 'array', 'items': {'type': 'string'}, 'maxItems': 5},
                      checked_files={'type': 'array', 'items': {'type': 'string'}, 'maxItems': 2}, summary={'type': 'string', 'maxLength': 400})
        schema = {'type': 'object', 'properties': fields, 'required': list(fields), 'additionalProperties': False}
        stage('REVIEWING')
        review = invoke('reviewer', 'Independently review the exact frozen candidate. Read calculator.py and test_calculator.py '
            f'and git diff {base}..{candidate}. Do not write. Determine whether addition is correct and tests are not weakened. '
            'Use PASS only with no findings. Return the supplied structured JSON, including checked_files. Binding: ' + encode(bound),
            review_root, schema, 'reviewer')
        result = review['payload']
        if set(result) != set(fields) or any(type(result[k]) is not type(v) or result[k] != v for k, v in bound.items()):
            raise RuntimeError('REVIEW_BINDING_MISMATCH')
        if result['verdict'] not in ('PASS', 'FAIL') or not isinstance(result['findings'], list) or not all(isinstance(v, str) for v in result['findings']):
            raise RuntimeError('INVALID_REVIEW_VERDICT')
        if not isinstance(result['summary'], str) or len(result['summary']) > 400 or len(result['findings']) > 5:
            raise RuntimeError('INVALID_REVIEW_BOUNDS')
        if (not isinstance(result['checked_files'], list) or len(result['checked_files']) != 2
                or not all(isinstance(v, str) for v in result['checked_files'])
                or set(result['checked_files']) != {'calculator.py', 'test_calculator.py'}):
            raise RuntimeError('INCOMPLETE_REVIEW')
        if result['verdict'] != 'PASS' or result['findings']:
            raise RuntimeError('NEEDS_REVIEW_OR_REPAIR_BUDGET: new candidate needs a new review')
        if input_manifest(review_root) != snapshot or input_manifest(task) != snapshot or git(task, 'rev-parse', 'HEAD') != candidate:
            raise RuntimeError('REVIEW_INPUT_DRIFT')
        if review['thread_id'] == worker['thread_id']:
            raise RuntimeError('NONINDEPENDENT_REVIEWER')
        atomic_json(data / 'review-bound.json', result)
        stage('PROMOTING', candidate, digest(result))
        if git(source, 'rev-parse', 'main') != base or input_manifest(source) != original or not authority():
            raise RuntimeError('EXPECTED_MAIN_CHANGED')
        # This fixture has one writer. General CAS/parallel promotion is not claimed.
        git(source, 'merge', '--ff-only', candidate)
        if git(source, 'rev-parse', 'HEAD') != candidate or input_manifest(source) != snapshot:
            raise RuntimeError('PROMOTION_MISMATCH')
        stage('ACCEPTED', candidate, digest(result))
        report.update(status='LOCAL_CANDIDATE_ACCEPTED', candidate_commit=candidate, final_main_commit=candidate,
            candidate_equals_final=True, checks='PASS', check_receipt_sha256=check_sha,
            review='PASS', reviewer_thread_id=review['thread_id'], executor_thread_id=worker['thread_id'],
            fresh_reviewer=True, input_unchanged_through_review=True, real_project_main_modified=False,
            sdk='0.162.0', runtime='0.162.0', remote='REMOTE_DISABLED',
            check_native_version=checks['native_version'], readonly_policy_requested=True,
            full_controller_queue_and_crash_recovery_verified=False)
    except Exception as error:
        report.update(status='BLOCKED_ENVIRONMENT' if 'ENVIRONMENT' in str(error) else 'NEEDS_DECISION',
                      error_type=type(error).__name__, error_summary=str(error)[:500])
        if authority():
            stage('NEEDS_DECISION')
    finally:
        report['model_turns'] = controller.db.execute('SELECT COUNT(*) FROM calls').fetchone()[0]
        report['sqlite_run_state'] = controller.db.execute('SELECT state FROM fixture_runs WHERE id=?', (project,)).fetchone()[0]
        report['runtime_authority'] = str(data / 'state.sqlite')
        atomic_json(PILOT / 'report.json', report)
        controller.db.close()
        print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--check-only')
    args = parser.parse_args()
    if args.check_only:
        check_only(args.check_only)
    else:
        run()
