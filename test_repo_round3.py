"""Final boundaries: real disposable Git/SQLite with deterministic SDK adversaries."""
import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

import repo_execution as execution
import test_repo_controller as fixture
from orchestrator import EvidenceChangedError, atomic_json, digest

ROOT = Path(__file__).resolve().parent


class Round3Tests(unittest.TestCase):
    def setUp(self):
        fixture.ROOT = ROOT
        fixture.RepoControllerTests.setUp(self)

    tearDown = fixture.RepoControllerTests.tearDown
    submit = fixture.RepoControllerTests.submit
    task = fixture.RepoControllerTests.task

    def ready(self):
        self.submit()
        self.c.run_one()
        self.assertEqual(self.task()['state'], 'ACCEPTED')
        return self.c.verify_task_accepted(self.task())

    def replace_proof(self, proof):
        atomic_json(self.c.task_dir(self.task())/'acceptance.json', proof)
        with self.c.immediate():
            self.c.db.execute('UPDATE tasks SET acceptance_proof=?,acceptance_proof_hash=?',
                              (json.dumps(proof), digest(proof)))

    def sdk_adversary(self, mutation):
        original = self.sdk.run
        def run(role, *args, **kwargs):
            result = original(role, *args, **kwargs)
            if role == 'reviewer':
                mutation(Path(args[2]), Path(args[3]), result)
            return result
        self.sdk.run = run
        self.submit()
        self.c.run_one()
        self.assertEqual(self.task()['state'], 'NEEDS_DECISION')
        self.assertIsNone(self.task()['acceptance_proof'])
        self.assertEqual(len(self.sdk.roles), 2)
        with self.assertRaises((ValueError, EvidenceChangedError)):
            self.c.promote_repo_task(self.task()['id'])
        self.assertEqual(execution.git(self.source, ['rev-parse', 'HEAD']), self.base)

    def test_reviewer_modifies_its_source_checkout_cannot_accept(self):
        self.sdk_adversary(lambda root, log, result: (root/'calculator.py').write_bytes(b'# hostile review edit\n'))

    def test_reviewer_changes_check_input_cannot_accept(self):
        self.sdk_adversary(lambda root, log, result: (root/'.controller-review/checks.json').write_bytes(b'{}'))

    def test_reviewer_changes_executor_candidate_cannot_accept(self):
        def mutate(root, log, result):
            descriptor = json.loads((self.c.task_dir(self.task())/'workspace.json').read_bytes())
            (Path(descriptor['path'])/'calculator.py').write_bytes(b'# hostile candidate edit\n')
        self.sdk_adversary(mutate)

    def test_reviewer_commits_changed_candidate_cannot_reuse_pass(self):
        def mutate(root, log, result):
            descriptor = json.loads((self.c.task_dir(self.task())/'workspace.json').read_bytes())
            target = Path(descriptor['path'])
            (target/'calculator.py').write_bytes(b'# replacement candidate\n')
            execution.git(target, ['add', '--', 'calculator.py'])
            execution.git(target, ['-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                                  'commit','--no-verify','--no-gpg-sign','-m','hostile candidate'])
        self.sdk_adversary(mutate)

    def test_reviewer_moves_detached_head_cannot_accept_even_identical_tree(self):
        def mutate(root, log, result):
            execution.git(root, ['-c','user.name=Fixture','-c','user.email=fixture@example.invalid',
                                'commit','--allow-empty','--no-verify','--no-gpg-sign','-m','changed identity'])
        self.sdk_adversary(mutate)

    def test_reviewer_output_cannot_request_file_operations(self):
        def mutate(root, log, result):
            result['payload']['write_files'] = {'calculator.py':'hostile'}
        self.sdk_adversary(mutate)

    def test_missing_or_workspace_write_reviewer_sandbox_evidence_rejected(self):
        def mutate(root, log, result):
            record = json.loads(log.read_bytes())
            record['sandbox_requested'] = 'workspace-write'
            atomic_json(log, record)
        self.sdk_adversary(mutate)

    def test_fresh_readonly_sessions_and_exact_identity_through_promotion(self):
        proof = self.ready()
        self.assertNotEqual(proof['executor_session_id'], proof['reviewer_session_id'])
        self.assertEqual(proof['role_runtime']['reviewer']['sandbox'], 'read-only')
        directory = self.c.task_dir(self.task())
        checks = json.loads((directory/'checks.json').read_bytes())
        review = json.loads((directory/'review.json').read_bytes())
        candidate = proof['binding']['candidate_commit']
        self.assertEqual(checks['binding']['candidate_commit'], candidate)
        self.assertEqual(review['candidate_commit'], candidate)
        self.c.promote_repo_task(self.task()['id'])
        self.assertEqual(execution.git(self.source, ['rev-parse', 'HEAD']), candidate)

    def test_known_legacy_proof_is_readable_but_needs_reconciliation_no_defaults(self):
        proof = self.ready()
        proof['policy']['kind'] = 'repo-worktree-proof/1'
        del proof['schema_version'], proof['role_runtime']
        original = copy.deepcopy(proof)
        self.assertIn('legacy proof/1', execution.proof_compatibility(proof))
        self.assertEqual(proof, original)
        self.replace_proof(proof)
        self.assertEqual(self.c.audit_accepted(), 1)
        self.assertEqual(self.task()['error_class'], 'NEEDS_RECONCILIATION')
        self.assertEqual(len(self.sdk.roles), 2)

    def test_unknown_proof_version_never_passes(self):
        proof = self.ready()
        proof['schema_version'] = proof['policy']['kind'] = 'repo-worktree-proof/999'
        self.replace_proof(proof)
        with self.assertRaisesRegex(EvidenceChangedError, 'unknown'):
            self.c.verify_task_accepted(self.task())

    def test_missing_current_runtime_fields_never_defaulted(self):
        proof = self.ready()
        del proof['role_runtime']['reviewer']['sdk_version']
        original = copy.deepcopy(proof)
        self.replace_proof(proof)
        with self.assertRaisesRegex(EvidenceChangedError, 'incomplete'):
            self.c.verify_task_accepted(self.task())
        self.assertEqual(proof, original)

    def test_schema_policy_version_disagreement_rejected(self):
        proof = self.ready()
        proof['schema_version'] = 'repo-worktree-proof/1'
        self.replace_proof(proof)
        with self.assertRaisesRegex(EvidenceChangedError, 'inconsistent'):
            self.c.verify_task_accepted(self.task())

    def test_live_status_requires_actual_recorded_runtime_version(self):
        proof = self.ready()
        proof['evidence_status'] = 'LIVE_VERIFIED'
        self.replace_proof(proof)
        with self.assertRaisesRegex(EvidenceChangedError, 'runtime versions'):
            self.c.verify_task_accepted(self.task())

    def test_missing_proof_version_is_not_current(self):
        self.assertIn('NEEDS_RECONCILIATION', execution.proof_compatibility({}))

    def test_boundary_code_upgrade_requires_reconciliation_preserves_candidate(self):
        proof = self.ready()
        policy = execution.proof_policy()
        policy['sdk_adapter_sha256'] = '0'*64
        with patch.object(execution, 'proof_policy', return_value=policy):
            self.assertEqual(self.c.audit_accepted(), 1)
        self.assertEqual(self.task()['error_class'], 'NEEDS_RECONCILIATION')
        self.assertEqual(execution.git(proof['workspace']['path'], ['rev-parse','HEAD']), proof['binding']['candidate_commit'])
        self.assertEqual(len(self.sdk.roles), 2)

    def test_runtime_installation_upgrade_alone_does_not_invalidate_recorded_proof(self):
        proof = self.ready()
        # Simulate an updated installed SDK/runtime; validators never consult it.
        with patch.dict('sys.modules', {'openai_codex': type('NewRuntime', (), {'__version__':'999.0'})}):
            self.assertEqual(self.c.verify_task_accepted(self.task()), proof)
        self.assertEqual(proof['role_runtime']['executor']['sdk_version'], 'fake')

    def test_runtime_metadata_must_match_hashed_role_evidence(self):
        proof = self.ready()
        proof['role_runtime']['reviewer']['runtime_version'] = '999.0'
        self.replace_proof(proof)
        with self.assertRaisesRegex(EvidenceChangedError, 'ROLE_RUNTIME_CHANGED'):
            self.c.verify_task_accepted(self.task())


if __name__ == '__main__':
    unittest.main()
