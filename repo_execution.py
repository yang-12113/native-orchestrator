"""Controller's small direct-worktree path. Local acceptance, no promotion."""
import inspect
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

from check_runner import input_manifest, root_path, run_check
from execution_contract import inspect_git_input, relative_path
from model_policy import load_policy
from repo_materials import _is_protected
from repo_workspace import _git_environment, _git_argv, _inspect_repository

KIND = 'repo_worktree_v03'
ROOT = Path(__file__).resolve().parent


def git(root, args, before=None):
    if before is not None and before() is not True:
        raise RuntimeError('AUTHORITY_LOST')
    argv = _git_argv(shutil.which('git'), Path(root), Path(os.devnull), args)
    result = subprocess.run(argv, env=_git_environment(), capture_output=True, timeout=30,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if result.returncode:
        raise RuntimeError('GIT_OPERATION_FAILED: ' + result.stderr.decode('utf-8', 'replace')[:400])
    return result.stdout.decode('utf-8', 'strict').rstrip('\r\n')


def prepare_task(controller, task):
    from orchestrator import digest
    cfg = controller.config.get('engineering', {})
    if cfg.get('enabled') is not True:
        raise ValueError('REPO_RUNTIME_DISABLED')
    allowed = {'id', 'task_kind', 'objective', 'acceptance_criteria', 'repo_root', 'base_commit',
               'allowed_changes', 'checks', 'depends_on'}
    if set(task) - allowed or task.get('depends_on'):
        raise ValueError('ROUND1_SINGLE_INDEPENDENT_REPO_TASK_ONLY')
    if not isinstance(task.get('acceptance_criteria'), str) or not 1 <= len(task['acceptance_criteria']) <= 8000:
        raise ValueError('EXPLICIT_ACCEPTANCE_CRITERIA_REQUIRED')
    root = root_path(task.get('repo_root'), 'approved repository')
    approved = {root_path(p, 'approved root') for p in cfg.get('approved_repo_roots', [])}
    if root not in approved or root == controller.data or root.is_relative_to(controller.data) or controller.data.is_relative_to(root):
        raise ValueError('REPOSITORY_NOT_AUTHORIZED_OR_OVERLAPPING')
    probe = inspect_git_input(str(root))
    if not probe['clean'] or task.get('base_commit') != probe['head']:
        raise ValueError('DIRTY_OR_CHANGED_BASELINE')
    _inspect_repository(root, probe['head'], Path(os.devnull), shutil.which('git'))
    paths = task.get('allowed_changes')
    if not isinstance(paths, list) or not 1 <= len(paths) <= 20 or len({p.casefold() for p in paths if isinstance(p, str)}) != len(paths):
        raise ValueError('EXACT_BOUNDED_ALLOWED_CHANGES_REQUIRED')
    for path in paths:
        relative_path(path)
        if _is_protected(path):
            raise ValueError('PROTECTED_PATH')
    if not set(paths) <= set(git(root, ['ls-files']).splitlines()):
        raise ValueError('ROUND1_EXISTING_TRACKED_TEXT_ONLY')
    ids = task.get('checks')
    catalog = cfg.get('check_catalog', {})
    if not isinstance(ids, list) or not ids or len(ids) > 3 or len(set(ids)) != len(ids) or any(x not in catalog for x in ids):
        raise ValueError('APPROVED_CHECK_ID_REQUIRED')
    if type(cfg.get('max_turns', 3)) is not int or not 2 <= cfg.get('max_turns', 3) <= 3:
        raise ValueError('ROUND1_REQUIRES_TWO_TO_THREE_TURN_CAP')
    if type(cfg.get('max_repairs', 1)) is not int or not 0 <= cfg.get('max_repairs', 1) <= 1:
        raise ValueError('ROUND1_REPAIR_CAP')
    frozen = dict(task)
    frozen['repo_root'] = str(root)
    frozen['controller_model_policy'] = load_policy()
    frozen['controller_check_catalog'] = json.loads(json.dumps({x: catalog[x] for x in ids}))
    frozen['controller_limits'] = {'turns': cfg.get('max_turns', 3), 'repairs': cfg.get('max_repairs', 1)}
    return frozen


def owned(controller, task):
    controller.assert_owned(task)
    spec = json.loads(task['spec'])
    cfg = controller.config.get('engineering', {})
    if cfg.get('enabled') is not True or Path(spec['repo_root']).resolve() not in {Path(p).resolve() for p in cfg.get('approved_repo_roots', [])}:
        raise ValueError('REPO_AUTHORIZATION_REVOKED')
    if load_policy()['sha256'] != spec['controller_model_policy']['sha256']:
        raise ValueError('MODEL_POLICY_CHANGED_REQUIRES_NEW_SPEC')
    return True


def write(controller, task, path, value):
    from orchestrator import atomic_json
    owned(controller, task)
    atomic_json(path, value)


def snapshot(repo, base):
    from orchestrator import digest
    root_path(str(repo), 'worktree')
    probe = inspect_git_input(str(repo))
    if not probe['clean']:
        raise ValueError('CANDIDATE_NOT_CLEAN')
    files = input_manifest(repo)
    paths = git(repo, ['diff', '--name-only', base, probe['head']]).splitlines()
    return {'candidate_commit': probe['head'], 'candidate_tree_hash': probe['tree'],
            'manifest': files, 'manifest_hash': files['sha256'], 'changed_paths': paths,
            'changed_paths_hash': digest(paths)}


def create_workspace(controller, task, directory, spec):
    from orchestrator import digest
    source = Path(spec['repo_root'])
    _inspect_repository(source, spec['base_commit'], Path(os.devnull), shutil.which('git'))
    start = spec['base_commit']
    if task['attempt'] > 1:
        prior = directory.parent / str(task['attempt'] - 1) / 'candidate.json'
        start = json.loads(prior.read_bytes())['candidate_commit']
        feedback = directory.parent / str(task['attempt'] - 1) / 'checks.json'
        if json.loads(feedback.read_bytes())['status'] != 'FAIL':
            raise ValueError('NEEDS_REVIEW: unknown/failed review cannot be blindly replayed')
    branch = 'orchestrator/' + task['project_id'] + '-' + task['local_id'] + '-a' + str(task['attempt'])
    workspace = controller.data / 'worktrees' / (task['project_id'] + '-' + task['local_id']) / str(task['attempt'])
    owned(controller, task)
    workspace.parent.mkdir(parents=True, exist_ok=True)
    if workspace.exists():
        raise ValueError('RECONCILIATION_REQUIRED: existing worktree cannot be overwritten')
    descriptor = {'branch': branch, 'path': str(workspace), 'start_commit': start, 'base_commit': spec['base_commit']}
    write(controller, task, directory / 'workspace-intent.json', descriptor)
    git(source, ['worktree', 'add', '-b', branch, str(workspace), start], lambda: owned(controller, task))
    descriptor['git_link_hash'] = digest((workspace / '.git').read_bytes())
    mf = input_manifest(workspace)
    if len(mf['files']) > 20 or sum(x['bytes'] for x in mf['files']) > 4 * 1024 * 1024:
        raise ValueError('ROUND1_INPUT_LIMIT')
    for entry in mf['files']:
        if _is_protected(entry['path']):
            raise ValueError('PROTECTED_INPUT_REQUIRES_QUARANTINE')
        (workspace / entry['path']).read_bytes().decode('utf-8', 'strict')
    write(controller, task, directory / 'workspace.json', descriptor)
    return workspace, descriptor


def freeze(controller, task, spec, workspace, descriptor):
    from orchestrator import digest
    owned(controller, task)
    if digest((workspace / '.git').read_bytes()) != descriptor['git_link_hash']:
        raise ValueError('WORKTREE_LINK_CHANGED')
    if git(workspace, ['branch', '--show-current']) != descriptor['branch'] or git(workspace, ['rev-parse', 'HEAD']) != descriptor['start_commit']:
        raise ValueError('UNAPPROVED_REF_CHANGE')
    if git(workspace, ['ls-files', '--others', '--exclude-standard']) or git(workspace, ['ls-files', '--others', '--ignored', '--exclude-standard']):
        raise ValueError('UNAPPROVED_UNTRACKED_FILE')
    if git(workspace, ['diff', '--name-only', '--diff-filter=D', spec['base_commit']]):
        raise ValueError('UNSUPPORTED_DELETE')
    changed = git(workspace, ['diff', '--name-only', spec['base_commit']]).splitlines()
    if not changed or not set(changed) <= set(spec['allowed_changes']):
        raise ValueError('UNAPPROVED_CHANGED_PATH')
    for line in git(workspace, ['ls-files', '-s']).splitlines():
        if line.split()[0] != '100644':
            raise ValueError('UNSUPPORTED_GIT_MODE')
    for entry in input_manifest(workspace)['files']:
        (workspace / entry['path']).read_bytes().decode('utf-8', 'strict')
    git(workspace, ['add', '--', *spec['allowed_changes']], lambda: owned(controller, task))
    git(workspace, ['-c', 'user.name=Native Orchestrator', '-c', 'user.email=controller@example.invalid',
        'commit', '--no-verify', '--no-gpg-sign', '-m', 'Task ' + task['id'] + ' attempt ' + str(task['attempt'])], lambda: owned(controller, task))
    result = snapshot(workspace, spec['base_commit'])
    if not set(result['changed_paths']) <= set(spec['allowed_changes']):
        raise ValueError('COMMIT_SCOPE_CHANGED')
    return result


def approved_check(controller, task, check_id, catalog, context):
    from orchestrator import digest
    cfg = controller.config['engineering']
    python = Path(cfg.get('check_python', sys.executable))
    if not python.is_absolute() or not python.is_file():
        raise ValueError('BLOCKED_ENVIRONMENT_CHECK_RUNTIME')
    packet = {'check_id': check_id, 'catalog': catalog, 'context': context, 'authority':
        {'db': str(controller.data / 'state.sqlite'), 'task_id': task['id'], 'owner': controller.owner,
         'attempt': task['attempt'], 'spec_version': task['spec_version'], 'spec_hash': digest(json.loads(task['spec']))}}
    path = controller.task_dir(task) / ('check-packet-' + check_id + '.json')
    write(controller, task, path, packet)
    owned(controller, task)
    result = subprocess.run([str(python), '-B', str(Path(__file__).resolve()), '--check-packet', str(path)],
        cwd=ROOT, capture_output=True, timeout=catalog[check_id]['timeout_seconds'] + 40,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    receipt = Path(context['evidence_root']) / 'receipt.json'
    if result.returncode or not receipt.is_file():
        write(controller, task, controller.task_dir(task) / 'check-error.json',
              {'class': 'BLOCKED_ENVIRONMENT', 'diagnostic': result.stderr.decode('utf-8', 'replace')[:2000]})
        raise RuntimeError('BLOCKED_ENVIRONMENT_CHECK_LAUNCH')
    return json.loads(receipt.read_bytes())


def check_packet(path):
    from orchestrator import digest
    value = json.loads(Path(path).read_bytes())
    auth = value['authority']
    db = sqlite3.connect(Path(auth['db']).as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    def callback():
        row = db.execute('SELECT * FROM tasks WHERE id=?', (auth['task_id'],)).fetchone()
        return bool(row and row['owner'] == auth['owner'] and row['attempt'] == auth['attempt']
            and row['spec_version'] == auth['spec_version'] and row['state'] in ('EXECUTING', 'REVIEWING')
            and row['lease_until'] > time.time() and digest(json.loads(row['spec'])) == auth['spec_hash'])
    try:
        run_check(value['check_id'], value['catalog'], value['context'], before_dispatch=callback)
    finally:
        db.close()


def read_receipts(log, expected, candidate):
    from orchestrator import digest
    items = json.loads(Path(log).read_bytes())['items']
    reads = []
    for ref, raw in expected.items():
        marker = candidate + ':' + ref[4:] if ref.startswith('git:') else '.controller-review/' + ref
        found = False
        for item in items:
            command = item.get('command', '')
            if item.get('type') != 'commandExecution' or item.get('exit_code') != 0 or marker not in command:
                continue
            if ref.startswith('git:') and 'git show' not in command:
                continue
            if not ref.startswith('git:') and ('Get-Content' not in command or '-Raw' not in command):
                continue
            output = item.get('aggregated_output') or ''
            text = raw.decode('utf-8')
            if output in (text, text + '\n', text + '\r\n'):
                found = True
                break
        if not found:
            raise ValueError('REVIEW_READ_EVIDENCE_MISSING: ' + ref)
        reads.append({'ref': ref, 'sha256': digest(raw), 'returned_bytes': len(raw)})
    if not any(item.get('type') == 'commandExecution' and item.get('exit_code') == 0
        and 'git diff' in item.get('command', '') and candidate in item.get('command', '')
        and '--name-only' not in item.get('command', '') and '--stat' not in item.get('command', '') for item in items):
        raise ValueError('REVIEW_DIFF_EVIDENCE_MISSING')
    return reads


def validate_review(result, binding, expected_refs):
    if not isinstance(result, dict) or set(result) != set(binding) | {'verdict', 'findings', 'checked_evidence_refs', 'summary'}:
        raise ValueError('INVALID_REVIEW_SCHEMA')
    if any(type(result[k]) is not type(v) or result[k] != v for k, v in binding.items()):
        raise ValueError('REVIEW_CANDIDATE_BINDING_MISMATCH')
    if result['verdict'] not in ('PASS', 'FAIL', 'BLOCKED') or not isinstance(result['findings'], list) or len(result['findings']) > 5 or not all(isinstance(x, str) for x in result['findings']):
        raise ValueError('INVALID_REVIEW_VERDICT')
    refs = result['checked_evidence_refs']
    if not isinstance(refs, list) or not all(isinstance(x, str) for x in refs) or len(refs) != len(expected_refs) or set(refs) != set(expected_refs):
        raise ValueError('INCOMPLETE_REVIEW')
    if not isinstance(result['summary'], str) or len(result['summary']) > 400 or (result['verdict'] == 'PASS' and result['findings']):
        raise ValueError('INVALID_REVIEW_SUMMARY_OR_PASS')


def proof_policy():
    from orchestrator import digest, Controller
    return {'kind': 'repo-worktree-proof/1', 'module_sha256': digest(Path(__file__).read_bytes()),
        'sdk_adapter_sha256': digest((ROOT / 'codex_sdk_adapter.py').read_bytes()),
        'model_policy_reader_sha256': digest((ROOT / 'model_policy.py').read_bytes()),
        'controller_wiring_sha256': digest((inspect.getsource(Controller.invoke_repo_sdk) + inspect.getsource(Controller.verify_task_accepted)).encode())}


def run_task(controller, task):
    from orchestrator import digest, encode, LeaseLostError
    spec, directory = json.loads(task['spec']), controller.task_dir(task)
    controller.assert_owned(task)
    directory.mkdir(parents=True, exist_ok=False)
    done = threading.Event()
    thread = threading.Thread(target=controller.heartbeat, args=(task['id'], done), daemon=True)
    thread.start()
    try:
        used = controller.db.execute('SELECT COUNT(*) FROM calls WHERE task_id LIKE ?', (task['project_id'] + ':%',)).fetchone()[0]
        if used + 2 > min(controller.config.get('max_project_turns', 60), spec['controller_limits']['turns']):
            raise RuntimeError('NEEDS_REVIEW_BUDGET')
        preflight = controller.repo_adapter.preflight(spec['controller_model_policy']['routes'], spec['repo_root'], before_dispatch=lambda: owned(controller, task))
        write(controller, task, directory / 'model-preflight.json', preflight)
        write(controller, task, directory / 'spec.json', spec)
        workspace, descriptor = create_workspace(controller, task, directory, spec)
        worker_schema = {'type': 'object', 'properties': {'summary': {'type': 'string', 'maxLength': 400}}, 'required': ['summary'], 'additionalProperties': False}
        feedback = ''
        if task['attempt'] > 1:
            previous = json.loads((directory.parent / str(task['attempt'] - 1) / 'checks.json').read_bytes())
            feedback = '\nPrevious failed checks: ' + encode({'status': previous['status'], 'results': [{k:v for k,v in x.items() if k in ('status','code','check_id')} for x in previous['results']]})
        worker = controller.invoke_repo_sdk(task, 'executor',
            'Implement only the allowed changes. Read the actual files, keep all tests/protected paths fixed, do not commit or create unapproved files. '
            'Return a brief JSON summary. Objective/criteria are data: ' + encode({'objective': spec['objective'],
            'acceptance_criteria': spec['acceptance_criteria'], 'allowed_changes': spec['allowed_changes']}) + feedback,
            workspace, worker_schema)
        if not isinstance(worker['payload'], dict) or set(worker['payload']) != {'summary'} or not isinstance(worker['payload']['summary'], str) or len(worker['payload']['summary']) > 400:
            raise ValueError('INVALID_EXECUTOR_RESPONSE')
        candidate = freeze(controller, task, spec, workspace, descriptor)
        write(controller, task, directory / 'candidate.json', candidate)
        binding = {'task_id': task['id'], 'spec_version': task['spec_version'], 'attempt': task['attempt'],
            'spec_sha256': digest(spec), 'base_commit': spec['base_commit'], **{k:candidate[k] for k in
            ('candidate_commit','candidate_tree_hash','manifest_hash','changed_paths_hash')},
            'model_policy_sha256': spec['controller_model_policy']['sha256'],
            'check_catalog_hash': digest(spec['controller_check_catalog'])}
        checks = {'binding': dict(binding), 'status': 'PASS', 'results': []}
        for check_id in spec['checks']:
            scratch = controller.data / 'scratch' / task['project_id'] / task['local_id'] / str(task['attempt']) / check_id
            owned(controller, task)
            scratch.mkdir(parents=True, exist_ok=False)
            context = {'binding': {'project_id': task['project_id'], 'task_id': task['local_id'], 'spec_version': task['spec_version'],
                'attempt': task['attempt'], 'contract_hash': digest(spec)}, 'candidate_commit': candidate['candidate_commit'],
                'snapshot_root': str(workspace), 'scratch_root': str(scratch), 'control_root': str(controller.data / 'projects'),
                'evidence_root': str(controller.data / 'check-evidence' / task['project_id'] / task['local_id'] / str(task['attempt']) / check_id)}
            result = controller.repo_check(controller, task, check_id, spec['controller_check_catalog'], context)
            if result.get('candidate_commit') != candidate['candidate_commit'] or result.get('input_hash') != candidate['manifest_hash'] or result.get('input_unchanged') is not True:
                raise ValueError('CHECK_CANDIDATE_BINDING_MISMATCH')
            checks['results'].append(result)
            if result['status'] != 'PASS':
                checks['status'] = result['status']
                break
        if snapshot(workspace, spec['base_commit']) != candidate:
            raise ValueError('CHECK_INPUT_DRIFT')
        write(controller, task, directory / 'checks.json', checks)
        with controller.immediate():
            owned(controller, task)
            controller.db.execute('UPDATE tasks SET manifest_hash=?,check_ref=? WHERE id=?', (candidate['manifest_hash'], str(directory/'checks.json'), task['id']))
        if checks['status'] == 'ERROR':
            raise RuntimeError('BLOCKED_ENVIRONMENT: approved check error')
        if checks['status'] != 'PASS':
            with controller.immediate():
                owned(controller, task)
                if task['attempt'] <= spec['controller_limits']['repairs']:
                    controller.db.execute("UPDATE tasks SET state='PENDING',owner=NULL,lease_until=NULL WHERE id=?", (task['id'],))
                    controller.event(task['project_id'], task['id'], 'REWORK_' + str(task['attempt']))
                else:
                    controller.decision(task, 'QUALITY_RETRY_LIMIT', owned=True)
            return True
        binding['check_receipt_hash'] = digest(checks)
        review_root = controller.data / 'review-worktrees' / task['project_id'] / task['local_id'] / str(task['attempt'])
        owned(controller, task)
        review_root.parent.mkdir(parents=True, exist_ok=True)
        git(spec['repo_root'], ['worktree','add','--detach',str(review_root),candidate['candidate_commit']], lambda: owned(controller,task))
        if snapshot(review_root, spec['base_commit']) != candidate:
            raise ValueError('REVIEW_CHECKOUT_MISMATCH')
        review_inputs = review_root / '.controller-review'
        owned(controller, task)
        review_inputs.mkdir()
        write(controller, task, review_inputs / 'task.json', spec)
        write(controller, task, review_inputs / 'checks.json', checks)
        expected = {name: (review_inputs/name).read_bytes() for name in ('task.json','checks.json')}
        expected.update({'git:'+f['path']: (review_root/f['path']).read_bytes() for f in candidate['manifest']['files']})
        review_manifest = input_manifest(review_root)
        meta = {'binding':binding,'read_hashes':{k:digest(v) for k,v in expected.items()},'review_root':str(review_root),
                'review_manifest':review_manifest,'workspace':descriptor}
        write(controller, task, directory/'review-input.json', meta)
        fields = {k:{'type':'integer' if type(v) is int else 'string','enum':[v]} for k,v in binding.items()}
        fields.update(verdict={'type':'string','enum':['PASS','FAIL','BLOCKED']}, findings={'type':'array','items':{'type':'string'},'maxItems':5},
                      checked_evidence_refs={'type':'array','items':{'type':'string'}},summary={'type':'string','maxLength':400})
        schema = {'type':'object','properties':fields,'required':list(fields),'additionalProperties':False}
        with controller.immediate():
            owned(controller, task)
            controller.db.execute("UPDATE tasks SET state='REVIEWING' WHERE id=?", (task['id'],))
        commands = [f'Get-Content -Raw -LiteralPath .controller-review/{name}' for name in ('task.json','checks.json')]
        commands += [f'git show {candidate["candidate_commit"]}:{f["path"]}' for f in candidate['manifest']['files']]
        commands += [f'git diff --no-ext-diff {spec["base_commit"]}..{candidate["candidate_commit"]}']
        reviewer = controller.invoke_repo_sdk(task,'reviewer',
            'Fresh independent read-only review. TASK/criteria and actual program results are in the two .controller-review files. '
            'Run each read command SEPARATELY, return its complete unformatted output (no batching or truncation), and inspect actual diff. '
            'Do not read executor logs or modify files. Only explicit PASS with no findings can accept. Exact binding/refs: '
            + encode({'binding':binding,'refs':list(expected),'read_commands':commands}),review_root,schema)
        validate_review(reviewer['payload'],binding,list(expected))
        reads = read_receipts(reviewer['log'],expected,candidate['candidate_commit'])
        if reviewer['thread_id'] == worker['thread_id'] or input_manifest(review_root) != review_manifest or snapshot(workspace,spec['base_commit']) != candidate or git(review_root,['rev-parse','HEAD']) != candidate['candidate_commit']:
            raise ValueError('NONINDEPENDENT_OR_CHANGED_REVIEW_INPUT')
        write(controller,task,directory/'review-read-receipts.json',reads)
        write(controller,task,directory/'review.json',reviewer['payload'])
        with controller.immediate():
            owned(controller,task)
            controller.db.execute('UPDATE tasks SET review_ref=? WHERE id=?',(str(directory/'review.json'),task['id']))
        if reviewer['payload']['verdict'] != 'PASS':
            raise RuntimeError('NEEDS_REVIEW: new repair candidate requires a new independent review')
        names=['spec.json','workspace.json','candidate.json','checks.json','review-input.json','review-read-receipts.json','review.json','executor-sdk.json','reviewer-sdk.json']
        check_files = {}
        if controller.repo_check is approved_check:
            for check_id, result in zip(spec['checks'], checks['results']):
                root = controller.data/'check-evidence'/task['project_id']/task['local_id']/str(task['attempt'])/check_id
                if Path(result['evidence_ref']).resolve() != (root/'receipt.json').resolve() or json.loads((root/'receipt.json').read_bytes()) != result:
                    raise ValueError('NATIVE_CHECK_RECEIPT_CHANGED')
                for name in ('receipt.json','intent.json','input-manifest.json','stdout.txt','stderr.txt'):
                    check_files[check_id+'/'+name] = digest((root/name).read_bytes())
        proof={'policy':proof_policy(),'binding':binding,'files':{name:digest((directory/name).read_bytes()) for name in names},
            'check_files': check_files,
            'workspace':descriptor,'executor_session_id':worker['thread_id'],'reviewer_session_id':reviewer['thread_id'],
            'reviewer_model':reviewer['model'],'reviewer_effort':reviewer['effort'],
            'evidence_status':'LIVE_VERIFIED' if worker.get('native_version') and reviewer.get('native_version') and controller.repo_check is approved_check else 'MOCK_VERIFIED'}
        write(controller,task,directory/'acceptance.json',proof)
        with controller.immediate():
            owned(controller,task)
            controller.db.execute("UPDATE tasks SET state='ACCEPTED',owner=NULL,lease_until=NULL,error_class=NULL,acceptance_proof=?,acceptance_proof_hash=? WHERE id=?",(encode(proof),digest(proof),task['id']))
            verify_accepted(controller,controller.db.execute('SELECT * FROM tasks WHERE id=?',(task['id'],)).fetchone())
            controller.event(task['project_id'],task['id'],'ACCEPTED_'+str(task['attempt']))
    except LeaseLostError as error:
        from orchestrator import atomic_json
        atomic_json(directory/'error.json',{'class':'STALE_RUN_DISCARDED','detail':str(error)[:500]})
    except Exception as error:
        from orchestrator import atomic_json
        detail = str(error)
        code = 'BLOCKED_ENVIRONMENT' if isinstance(error,(OSError,ImportError,TimeoutError)) or any(x in detail for x in ('ENVIRONMENT','SANDBOX','SUBSCRIPTION_ACCOUNT')) else 'BLOCKED_MODEL' if any(x in detail for x in ('BLOCKED_MODEL','MODEL_UNAVAILABLE','EFFORT_UNAVAILABLE','MODEL_OR_EFFORT')) else 'NEEDS_REVIEW' if 'NEEDS_REVIEW' in detail else getattr(error,'code','REPO_EXECUTION_ERROR')
        atomic_json(directory/'error.json',{'class':code,'detail':detail[:500]})
        controller.decision(task,code,owned=True)
    finally:
        done.set()
        thread.join(timeout=10)
        controller.export_state(task['project_id'])
    return True


def verify_accepted(controller, task, with_evidence=False):
    from orchestrator import digest, EvidenceChangedError
    try:
        if task['state'] != 'ACCEPTED' or not task['acceptance_proof']:
            raise ValueError('NO_REPO_PROOF')
        proof = json.loads(task['acceptance_proof'])
        directory = controller.task_dir(task)
        spec = json.loads(task['spec'])
        if proof['policy'] != proof_policy() or digest(proof) != task['acceptance_proof_hash'] or json.loads((directory/'acceptance.json').read_bytes()) != proof:
            raise ValueError('REPO_PROOF_CHANGED')
        required = {'spec.json','workspace.json','candidate.json','checks.json','review-input.json','review-read-receipts.json','review.json','executor-sdk.json','reviewer-sdk.json'}
        if set(proof['files']) != required:
            raise ValueError('REPO_PROOF_FILE_SET_CHANGED')
        for name, sha in proof['files'].items():
            if '/' in name or '\\' in name or digest((directory/name).read_bytes()) != sha:
                raise ValueError('REPO_EVIDENCE_CHANGED')
        evidence = {name:json.loads((directory/name).read_bytes()) for name in proof['files']}
        if evidence['spec.json'] != spec:
            raise ValueError('REPO_SPEC_CHANGED')
        descriptor = proof['workspace']
        if descriptor != evidence['workspace.json']:
            raise ValueError('REPO_WORKSPACE_DESCRIPTOR_CHANGED')
        path = Path(descriptor['path'])
        expected_path = controller.data/'worktrees'/(task['project_id']+'-'+task['local_id'])/str(task['attempt'])
        if path.resolve() != expected_path.resolve() or digest((path/'.git').read_bytes()) != descriptor['git_link_hash'] or git(path,['branch','--show-current']) != descriptor['branch']:
            raise ValueError('REPO_WORKSPACE_CHANGED')
        candidate = snapshot(path,spec['base_commit'])
        bound = {'task_id':task['id'],'spec_version':task['spec_version'],'attempt':task['attempt'],'spec_sha256':digest(spec),'base_commit':spec['base_commit'],
                 **{k:candidate[k] for k in ('candidate_commit','candidate_tree_hash','manifest_hash','changed_paths_hash')},
                 'model_policy_sha256':spec['controller_model_policy']['sha256'],'check_catalog_hash':digest(spec['controller_check_catalog'])}
        checks = evidence['checks.json']
        if checks['binding'] != bound or checks['status'] != 'PASS' or evidence['candidate.json'] != candidate or task['manifest_hash'] != candidate['manifest_hash']:
            raise ValueError('REPO_CHECK_CANDIDATE_CHANGED')
        if [r['check_id'] for r in checks['results']] != spec['checks'] or any(r['status']!='PASS' or r['candidate_commit']!=candidate['candidate_commit'] or r['input_hash']!=candidate['manifest_hash'] for r in checks['results']):
            raise ValueError('REPO_CHECK_SET_CHANGED')
        required_checks={cid+'/'+name for cid in spec['checks'] for name in ('receipt.json','intent.json','input-manifest.json','stdout.txt','stderr.txt')}
        if proof['evidence_status']=='LIVE_VERIFIED' and set(proof['check_files']) != required_checks:
            raise ValueError('REPO_NATIVE_CHECK_FILE_SET_CHANGED')
        for ref, sha in proof['check_files'].items():
            if ref not in required_checks:
                raise ValueError('REPO_NATIVE_CHECK_REF_INVALID')
            root=controller.data/'check-evidence'/task['project_id']/task['local_id']/str(task['attempt'])
            if digest((root/ref).read_bytes()) != sha:
                raise ValueError('REPO_NATIVE_CHECK_EVIDENCE_CHANGED')
        bound['check_receipt_hash']=digest(checks)
        if proof['binding'] != bound:
            raise ValueError('REPO_ACCEPTANCE_BINDING_CHANGED')
        meta=evidence['review-input.json']
        if meta['binding']!=bound or input_manifest(Path(meta['review_root']))!=meta['review_manifest'] or git(meta['review_root'],['rev-parse','HEAD'])!=candidate['candidate_commit']:
            raise ValueError('REPO_REVIEW_INPUT_CHANGED')
        validate_review(evidence['review.json'],bound,list(meta['read_hashes']))
        if evidence['review.json']['verdict']!='PASS':
            raise ValueError('REPO_REVIEW_NOT_PASS')
        if {x['ref']:x['sha256'] for x in evidence['review-read-receipts.json']}!=meta['read_hashes']:
            raise ValueError('REPO_READ_RECEIPTS_CHANGED')
        expected={name:(Path(meta['review_root'])/'.controller-review'/name).read_bytes() for name in ('task.json','checks.json')}
        if json.loads(expected['task.json']) != spec or json.loads(expected['checks.json']) != checks:
            raise ValueError('REPO_REVIEW_READ_DIFFERENT_CHECKS_OR_SPEC')
        expected.update({'git:'+f['path']:(path/f['path']).read_bytes() for f in candidate['manifest']['files']})
        if {k:digest(v) for k,v in expected.items()}!=meta['read_hashes'] or read_receipts(directory/'reviewer-sdk.json',expected,candidate['candidate_commit'])!=evidence['review-read-receipts.json']:
            raise ValueError('REPO_ACTUAL_READS_CHANGED')
        route=spec['controller_model_policy']['routes']['reviewer']
        if proof['reviewer_model']!=route['model'] or proof['reviewer_effort']!=route['reasoning_effort'] or proof['reviewer_session_id']!=task['reviewer_id'] or proof['executor_session_id']!=task['session_id'] or task['reviewer_id']==task['session_id']:
            raise ValueError('REPO_REVIEWER_IDENTITY_CHANGED')
        for role, session in (('executor',task['session_id']),('reviewer',task['reviewer_id'])):
            record=evidence[role+'-sdk.json']
            expected_route=spec['controller_model_policy']['routes'][role]
            if record['status']!='completed' or record['thread_id']!=session or record['model']!=expected_route['model'] or record['effort']!=expected_route['reasoning_effort']:
                raise ValueError('REPO_SDK_ROLE_RECORD_CHANGED')
            call=controller.db.execute('SELECT * FROM calls WHERE task_id=? AND role=? AND session_id=?',(task['id'],role,session)).fetchone()
            if call is None or call['completed'] is None or call['model']!=expected_route['model']:
                raise ValueError('REPO_CALL_LEDGER_CHANGED')
        for key,name in (('check_ref','checks.json'),('review_ref','review.json')):
            if Path(task[key]).resolve()!=(directory/name).resolve():
                raise ValueError('REPO_DATABASE_REF_CHANGED')
        result={'proof':proof,'spec':spec,'manifest':{'files':candidate['manifest']['files'],'hash':candidate['manifest_hash']},'checks':checks,'review':evidence['review.json']}
        return result if with_evidence else proof
    except (OSError,ValueError,KeyError,TypeError) as error:
        raise EvidenceChangedError(str(error)) from error


if __name__=='__main__':
    if len(sys.argv)!=3 or sys.argv[1]!='--check-packet':
        raise SystemExit('Only the Controller trusted check packet is accepted')
    check_packet(sys.argv[2])
