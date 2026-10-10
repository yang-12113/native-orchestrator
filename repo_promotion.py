"""Single-machine Git integration and journaled expected-ref promotion."""
import json
import os
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from orchestrator import atomic_json, digest
from repo_execution import (git, owned, snapshot, write, run_candidate, error_class,
                            root_path, KIND)


@contextmanager
def promotion_lock(source):
    # OS locks release on process death; all data directories share this Git lock.
    common = Path(git(source, ['rev-parse','--path-format=absolute','--git-common-dir']))
    with (common/'orchestrator-promotion.lock').open('a+b') as stream:
        if stream.tell() == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('PROMOTION_BUSY') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def accepted(controller, task_id):
    task = controller.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
    if task is None or json.loads(task['spec']).get('task_kind') != KIND:
        raise ValueError('REPO_TASK_REQUIRED')
    proof = controller.verify_task_accepted(task)
    spec = json.loads(task['spec'])
    source = root_path(spec['repo_root'],'promotion source')
    if controller.config.get('engineering',{}).get('enabled') is not True or source not in {root_path(p,'approved root') for p in controller.config['engineering']['approved_repo_roots']}:
        raise ValueError('REPO_AUTHORIZATION_REVOKED')
    if git(source,['branch','--show-current']) != 'main':
        raise ValueError('CHECKED_OUT_MAIN_REQUIRED')
    return task, proof, spec, source


def integrate_main(controller, task_id):
    with controller.immediate():
        task, proof, spec, source = accepted(controller,task_id)
        with promotion_lock(source):
            latest = git(source,['rev-parse','refs/heads/main'])
            previous_dir = controller.task_dir(task)
            previous = json.loads((previous_dir/'integration.json').read_bytes())['expected_main'] if (previous_dir/'integration.json').is_file() else spec['base_commit']
            if latest == previous:
                return proof
            if not snapshot(source,latest)['candidate_commit'] == latest:
                raise ValueError('MAIN_CHECKOUT_CHANGED')
            controller.db.execute("UPDATE tasks SET state='EXECUTING',attempt=attempt+1,owner=?,lease_until=?,reviewer_id=NULL,manifest_hash=NULL,check_ref=NULL,review_ref=NULL,acceptance_proof=NULL,acceptance_proof_hash=NULL,error_class=NULL WHERE id=?",(controller.owner,time.time()+60,task_id))
            task = controller.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
            controller.event(task['project_id'],task_id,'CANDIDATE_INVALIDATED_'+str(task['attempt']))
    directory = controller.task_dir(task)
    done = threading.Event()
    thread = threading.Thread(target=controller.heartbeat,args=(task_id,done),daemon=True)
    thread.start()
    try:
        owned(controller,task)
        directory.mkdir(parents=True,exist_ok=False)
        write(controller,task,directory/'spec.json',spec)
        worker = json.loads((previous_dir/'executor-sdk.json').read_bytes())
        write(controller,task,directory/'executor-sdk.json',worker)
        dispatch = json.loads((previous_dir/'executor-dispatch.json').read_bytes())
        dispatch['attempt'] = task['attempt']
        write(controller,task,directory/'executor-dispatch.json',dispatch)
        branch = 'orchestrator/'+task['project_id']+'-'+task['local_id']+'-a'+str(task['attempt'])
        workspace = controller.data/'worktrees'/(task['project_id']+'-'+task['local_id'])/str(task['attempt'])
        git(source,['worktree','add','-b',branch,str(workspace),proof['binding']['candidate_commit']],lambda:owned(controller,task))
        descriptor = {'branch':branch,'path':str(workspace),'start_commit':proof['binding']['candidate_commit'],
                      'base_commit':spec['base_commit'],'git_link_hash':digest((workspace/'.git').read_bytes())}
        write(controller,task,directory/'workspace.json',descriptor)
        intent = {'expected_main':latest,'previous_candidate':proof['binding']['candidate_commit'],
                  'previous_proof_hash':digest(proof)}
        write(controller,task,directory/'integration-intent.json',intent)
        try:
            git(workspace,['-c','user.name=Native Orchestrator','-c','user.email=controller@example.invalid',
                           'merge','--no-edit','--no-gpg-sign',latest],lambda:owned(controller,task))
        except RuntimeError:
            if git(workspace,['ls-files','-u']):
                raise RuntimeError('GIT_TEXT_CONFLICT') from None
            raise
        candidate = snapshot(workspace,spec['base_commit'])
        if not set(git(workspace,['diff','--name-only',latest,candidate['candidate_commit']]).splitlines()) <= set(spec['allowed_changes']):
            raise ValueError('INTEGRATION_SCOPE_CHANGED')
        write(controller,task,directory/'integration.json',{**intent,'candidate_commit':candidate['candidate_commit']})
        write(controller,task,directory/'candidate.json',candidate)
        run_candidate(controller,task,spec,workspace,descriptor,candidate)
    except Exception as error:
        controller.decision(task,'GIT_TEXT_CONFLICT' if 'GIT_TEXT_CONFLICT' in str(error) else error_class(error),owned=True)
    finally:
        done.set()
        thread.join(timeout=10)
        controller.export_state(task['project_id'])
    return controller.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()['state']


def promote(controller, task_id):
    """Git CAS is the ref authority; journal repairs only proven old/new indexes."""
    with controller.immediate():
        task, proof, spec, source = accepted(controller,task_id)
        with promotion_lock(source):
            directory = controller.task_dir(task)
            integration = directory/'integration.json'
            expected = json.loads(integration.read_bytes())['expected_main'] if integration.is_file() else spec['base_commit']
            candidate = proof['binding']['candidate_commit']
            journal_path = directory/'promotion-intent.json'
            receipt_path = directory/'promotion.json'
            intent = {'task_id':task_id,'attempt':task['attempt'],'expected_main':expected,
                      'candidate_commit':candidate,'proof_hash':digest(proof),'source':str(source)}
            if receipt_path.is_file():
                if json.loads(receipt_path.read_bytes()) != intent or not journal_path.is_file() or json.loads(journal_path.read_bytes()) != intent:
                    raise ValueError('PROMOTION_RECEIPT_CHANGED')
                git(source,['merge-base','--is-ancestor',candidate,'refs/heads/main'])
                controller.event(task['project_id'],task_id,'PROMOTED_'+str(task['attempt']))
                return intent
            actual = git(source,['rev-parse','refs/heads/main'])
            if journal_path.is_file():
                if json.loads(journal_path.read_bytes()) != intent or actual not in (expected,candidate):
                    raise ValueError('PROMOTION_NEEDS_RECONCILIATION')
            else:
                if actual != expected:
                    raise ValueError('EXPECTED_MAIN_CHANGED: '+expected+' != '+actual)
                snapshot(source,expected)
                git(source,['merge-base','--is-ancestor',expected,candidate])
                atomic_json(journal_path,intent)
            # Verify no unknown worktree bytes before repairing a journaled CAS.
            index = git(source,['write-tree'])
            old_tree = git(source,['rev-parse',expected+'^{tree}'])
            new_tree = git(source,['rev-parse',candidate+'^{tree}'])
            if index not in (old_tree,new_tree) or git(source,['diff','--name-only']) or git(source,['ls-files','--others','--exclude-standard']):
                raise ValueError('PROMOTION_WORKTREE_CHANGED')
            # Re-read main at the critical point, and use Git's atomic expected-ref CAS.
            if actual == expected:
                current = controller.db.execute('SELECT * FROM tasks WHERE id=?',(task_id,)).fetchone()
                controller.verify_task_accepted(current)
                if git(source,['rev-parse','refs/heads/main']) != expected:
                    raise ValueError('EXPECTED_MAIN_CHANGED')
                git(source,['update-ref','refs/heads/main',candidate,expected])
            if git(source,['rev-parse','refs/heads/main']) != candidate:
                raise ValueError('PROMOTION_NEEDS_RECONCILIATION')
            # Two-tree read-tree refuses local changes; no reset/clean/stash.
            if index != new_tree:
                git(source,['read-tree','-u','-m',expected,candidate])
            snapshot(source,candidate)
            atomic_json(receipt_path,intent)
            controller.event(task['project_id'],task_id,'PROMOTED_'+str(task['attempt']))
            return intent
