"""Isolated FRAME-002 contract preflight tests.

Run only with bytecode disabled, for example:
    python -B -m unittest -q test_execution_contract

The fixtures use temporary repositories under this worktree's .runtime directory
and a fake repository probe. They never invoke Git, checks, models, or the controller.
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from native_orchestrator.check_runner import run_check
from native_orchestrator.execution_contract import ContractError, canonical_hash, validate_contract


WORKTREE = Path(__file__).resolve().parents[1]
SCRATCH_ROOT = WORKTREE / ".runtime" / "frame-002-tests"
INTEROP_ROOT = WORKTREE / ".runtime" / "frame-004-interop-tests"
BASE_COMMIT = "1" * 40
TREE_HASH = "2" * 40
EVIDENCE_HASH = "a" * 64


class ExecutionContractPreflightTests(unittest.TestCase):
    def setUp(self) -> None:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        self._scratch = tempfile.TemporaryDirectory(prefix="case-", dir=SCRATCH_ROOT)
        self.addCleanup(self._scratch.cleanup)
        self.scratch = Path(self._scratch.name)
        self.repo_root = self.scratch / "repo"
        self.repo_root.mkdir()
        (self.repo_root / "calculator.py").write_text("value = 1\n", encoding="utf-8")
        self.probe_result: dict[str, Any] = {
            "root": str(self.repo_root.resolve()),
            "head": BASE_COMMIT,
            "tree": TREE_HASH,
            "clean": True,
        }
        self.contract, self.policy = self._verified_fixture()

    def _verified_fixture(self) -> tuple[dict[str, Any], dict[str, Any]]:
        """Start from the shipped v0.3 examples and make evidence explicit."""
        contract: dict[str, Any] = {
            "schema_version": "native-orchestrator.execution-contract/0.3",
            "project_id": "isolated-test-project",
            "task_id": "preflight-test",
            "request_id": "preflight-test-v1",
            "spec_version": 1,
            "authorization_ref": "user:isolated-test-project",
            "input": {
                "repo_root": str(self.repo_root.resolve()),
                "base_commit": BASE_COMMIT,
            },
            "allowed_changes": ["calculator.py"],
            "routes": {
                "executor": {
                    "client": "codex",
                    "model": "gpt-6-luna",
                    "reasoning_effort": "max",
                    "native_version": "0.162.0-alpha.2",
                },
                "reviewer": {
                    "client": "codex",
                    "model": "gpt-6-luna",
                    "reasoning_effort": "max",
                    "native_version": "0.162.0-alpha.2",
                },
            },
            "check_ids": ["unit"],
            "budget": {
                "max_native_turns": 60,
                "max_master_turns": 4,
                "max_reworks": 2,
                "planning_turns": 0,
                "notification_turns": 1,
            },
        }
        policy: dict[str, Any] = {
            "schema_version": "native-orchestrator.engineering-policy/0.3",
            # Even an enabled runtime must not turn this preflight into dispatch.
            "runtime_enabled": True,
            "authorization_ref": "user:isolated-test-project",
            "approved_repo_roots": [str(self.repo_root.resolve())],
            "protected_paths": [
                ".git",
                ".runtime",
                "data-live",
                "config.live.json",
                "MAINLINE.md",
                "DEVELOPMENT_STATE.json",
            ],
            "routes": {
                "executor": {
                    "client": "codex",
                    "model": "gpt-6-luna",
                    "native_version": "0.162.0-alpha.2",
                    "supported_efforts": ["max"],
                    "capabilities": ["repo_read", "file_proposal"],
                    "verification": "VERIFIED",
                    "evidence_sha256": EVIDENCE_HASH,
                },
                "reviewer": {
                    "client": "codex",
                    "model": "gpt-6-luna",
                    "native_version": "0.162.0-alpha.2",
                    "supported_efforts": ["max"],
                    "capabilities": ["repo_read", "bound_review"],
                    "verification": "VERIFIED",
                    "evidence_sha256": EVIDENCE_HASH,
                },
            },
            "runner": {
                "capabilities": ["approved_checks"],
                "verification": "VERIFIED",
                "evidence_sha256": EVIDENCE_HASH,
            },
            "check_catalog": {
                "unit": {
                    "argv": [sys.executable, "-B", "-c", "pass"],
                    "timeout_seconds": 120,
                    "output_bytes_cap": 4096,
                    "write_scope": "scratch",
                    "network": "disabled",
                    "shell": False,
                    "verification": "VERIFIED",
                    "evidence_sha256": EVIDENCE_HASH,
                }
            },
            "limits": {
                "max_native_turns": 60,
                "max_master_turns": 4,
                "max_reworks": 2,
                "max_reply_bytes": 8192,
                "max_summary_chars": 400,
                "max_evidence_excerpt_bytes": 2048,
            },
        }
        return contract, policy

    def _probe(self, _repo_root: str | os.PathLike[str]) -> dict[str, Any]:
        return copy.deepcopy(self.probe_result)

    def _assert_rejected(
        self,
        contract: dict[str, Any] | None = None,
        policy: dict[str, Any] | None = None,
        *,
        usage: dict[str, Any] | None = None,
    ) -> ContractError:
        with self.assertRaises(ContractError) as raised:
            validate_contract(
                copy.deepcopy(contract if contract is not None else self.contract),
                copy.deepcopy(policy if policy is not None else self.policy),
                usage=copy.deepcopy(usage),
                repository_probe=self._probe,
            )
        self.assertIsInstance(raised.exception.code, str)
        self.assertTrue(raised.exception.code)
        return raised.exception

    def _validated(self, **kwargs: Any) -> dict[str, Any]:
        result = validate_contract(
            copy.deepcopy(kwargs.pop("contract", self.contract)),
            copy.deepcopy(kwargs.pop("policy", self.policy)),
            repository_probe=kwargs.pop("repository_probe", self._probe),
            **kwargs,
        )
        self.assertEqual(result["status"], "CONTRACT_VALIDATED")
        return result

    def test_canonical_hash_is_stable_across_mapping_order(self) -> None:
        self.assertEqual(
            canonical_hash({"z": 3, "nested": {"b": 2, "a": 1}}),
            canonical_hash({"nested": {"a": 1, "b": 2}, "z": 3}),
        )
        self.assertNotEqual(canonical_hash({"value": 1}), canonical_hash({"value": 2}))

    def test_verified_fixture_validates_but_never_dispatches(self) -> None:
        result = self._validated()
        self.assertFalse(result["dispatchable"])
        self.assertEqual(result["contract_hash"], canonical_hash(self.contract))
        self.assertEqual(result["policy_hash"], canonical_hash(self.policy))
        self.assertEqual(result["minimum_native_turns"], 3)
        self.assertEqual(result["worst_case_native_turns"], 7)
        self.assertTrue(result["input_hash"])

    def test_budget_estimate_accounts_for_execution_review_rework_and_notifications(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["budget"].update(
            {"planning_turns": 2, "notification_turns": 2, "max_reworks": 1}
        )
        result = self._validated(contract=contract)
        self.assertEqual(result["minimum_native_turns"], 6)
        self.assertEqual(result["worst_case_native_turns"], 8)

    def test_invalid_contract_and_policy_versions_are_rejected(self) -> None:
        for target, section, value in (
            ("contract", None, "native-orchestrator.execution-contract/9.9"),
            ("policy", None, "native-orchestrator.engineering-policy/9.9"),
        ):
            with self.subTest(target=target):
                contract = copy.deepcopy(self.contract)
                policy = copy.deepcopy(self.policy)
                (contract if target == "contract" else policy)["schema_version"] = value
                self._assert_rejected(contract, policy)

    def test_unknown_fields_and_boolean_integer_substitutions_are_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["unrecognized"] = True
        self._assert_rejected(contract=contract)

        policy = copy.deepcopy(self.policy)
        policy["unrecognized"] = True
        self._assert_rejected(policy=policy)

        for path in (("spec_version",), ("budget", "max_native_turns")):
            with self.subTest(path=path):
                contract = copy.deepcopy(self.contract)
                node: Any = contract
                for key in path[:-1]:
                    node = node[key]
                node[path[-1]] = True
                self._assert_rejected(contract=contract)

    def test_authorization_and_approved_root_must_match(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["authorization_ref"] = "user:someone-else"
        self._assert_rejected(contract=contract)

        policy = copy.deepcopy(self.policy)
        policy["approved_repo_roots"] = [str(self.scratch / "other-repo")]
        self._assert_rejected(policy=policy)

        self.probe_result["root"] = str(self.scratch / "different-probe-root")
        self._assert_rejected()

    def test_dirty_or_non_git_repository_probe_is_rejected(self) -> None:
        self.probe_result["clean"] = False
        self._assert_rejected()

        self.probe_result = {
            "root": str(self.repo_root.resolve()),
            "head": None,
            "tree": None,
            "clean": False,
        }
        self._assert_rejected()

    def test_contract_must_bind_the_current_base_commit(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["input"]["base_commit"] = "3" * 40
        self._assert_rejected(contract=contract)

    def test_unsafe_paths_are_rejected(self) -> None:
        for path in (
            "../outside.py",
            "calculator.py:alternate-stream",
            "CON.txt",
            "MAINLINE.md",
            ".git/config",
            ".runtime/private.txt",
        ):
            with self.subTest(path=path):
                contract = copy.deepcopy(self.contract)
                contract["allowed_changes"] = [path]
                self._assert_rejected(contract=contract)

    def test_case_insensitive_duplicate_paths_are_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["allowed_changes"] = ["Calculator.py", "calculator.py"]
        self._assert_rejected(contract=contract)

    def test_parent_change_path_cannot_cover_a_protected_child(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["allowed_changes"] = ["src"]
        policy = copy.deepcopy(self.policy)
        policy["protected_paths"].append("src/private.json")
        error = self._assert_rejected(contract=contract, policy=policy)
        self.assertEqual(error.code, "PROTECTED_PATH")

    def test_existing_directory_cannot_be_an_allowed_change_target(self) -> None:
        (self.repo_root / "src").mkdir()
        contract = copy.deepcopy(self.contract)
        contract["allowed_changes"] = ["src"]
        error = self._assert_rejected(contract=contract)
        self.assertEqual(error.code, "INVALID_PATH")

    def test_symbolic_link_paths_are_rejected(self) -> None:
        link = self.repo_root / "linked.py"
        try:
            os.symlink(self.repo_root / "calculator.py", link)
        except (OSError, NotImplementedError) as exc:
            self.skipTest(f"symlink creation unavailable in isolated worktree: {exc}")
        contract = copy.deepcopy(self.contract)
        contract["allowed_changes"] = ["linked.py"]
        self._assert_rejected(contract=contract)

    def test_link_detection_rejects_a_reported_link(self) -> None:
        """Exercise the guard when this host cannot create a real OS symlink."""
        link = self.repo_root / "synthetic-link.py"
        original_is_symlink = Path.is_symlink

        def reported_link(path: Path) -> bool:
            if path == link:
                return True
            return original_is_symlink(path)

        contract = copy.deepcopy(self.contract)
        contract["allowed_changes"] = ["synthetic-link.py"]
        with patch.object(Path, "is_symlink", reported_link):
            error = self._assert_rejected(contract=contract)
        self.assertEqual(error.code, "LINKED_PATH")

    def test_missing_capability_or_unverified_evidence_is_rejected(self) -> None:
        policy = copy.deepcopy(self.policy)
        policy["routes"]["executor"]["capabilities"] = ["repo_read"]
        self._assert_rejected(policy=policy)

        for evidence_change in (
            {"verification": "UNKNOWN"},
            {"evidence_sha256": "not-a-sha256-evidence-reference"},
        ):
            with self.subTest(evidence_change=evidence_change):
                policy = copy.deepcopy(self.policy)
                policy["routes"]["executor"].update(evidence_change)
                self._assert_rejected(policy=policy)

        policy = copy.deepcopy(self.policy)
        policy["runner"]["verification"] = "UNKNOWN"
        self._assert_rejected(policy=policy)

        policy = copy.deepcopy(self.policy)
        policy["check_catalog"]["unit"]["verification"] = "UNKNOWN"
        self._assert_rejected(policy=policy)

        policy = copy.deepcopy(self.policy)
        del policy["check_catalog"]["unit"]["evidence_sha256"]
        self._assert_rejected(policy=policy)

        policy = copy.deepcopy(self.policy)
        policy["check_catalog"]["unit"]["evidence_sha256"] = "not-a-sha256-evidence-reference"
        self._assert_rejected(policy=policy)

    def test_requested_model_effort_and_native_version_must_match_verified_route(self) -> None:
        for route_field, value in (
            ("model", "gpt-6-other"),
            ("reasoning_effort", "high"),
            ("native_version", "0.0.0"),
        ):
            with self.subTest(route_field=route_field):
                contract = copy.deepcopy(self.contract)
                contract["routes"]["executor"][route_field] = value
                self._assert_rejected(contract=contract)

    def test_check_must_be_catalogued_and_shell_execution_is_forbidden(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["check_ids"] = ["unapproved-check"]
        self._assert_rejected(contract=contract)

        policy = copy.deepcopy(self.policy)
        policy["check_catalog"]["unit"]["shell"] = True
        self._assert_rejected(policy=policy)

    def test_catalog_output_bytes_cap_requires_bounded_exact_integer(self) -> None:
        invalid_caps = (
            ("missing", None),
            ("zero", 0),
            ("boolean", True),
            ("string", "4096"),
            ("above_maximum", 1024 * 1024 + 1),
        )
        for label, cap in invalid_caps:
            with self.subTest(cap=label):
                policy = copy.deepcopy(self.policy)
                entry = policy["check_catalog"]["unit"]
                if label == "missing":
                    del entry["output_bytes_cap"]
                else:
                    entry["output_bytes_cap"] = cap
                self._assert_rejected(policy=policy)

    def test_validated_catalog_passes_directly_to_fake_runner_without_translation(self) -> None:
        """The preflight's exact trusted entry is sufficient for the bounded runner."""
        INTEROP_ROOT.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="case-", dir=INTEROP_ROOT) as directory:
            root = Path(directory)
            snapshot = root / "snapshot"
            scratch = root / "scratch"
            control = root / "control"
            evidence = root / "evidence"
            for path in (snapshot, scratch, control):
                path.mkdir()
            (snapshot / "candidate.py").write_text("value = 1\n", encoding="utf-8")
            (control / "controller-data.txt").write_text("unchanged\n", encoding="utf-8")

            contract = copy.deepcopy(self.contract)
            contract["input"]["repo_root"] = str(snapshot.resolve())
            policy = copy.deepcopy(self.policy)
            policy["approved_repo_roots"] = [str(snapshot.resolve())]
            trusted_catalog = policy["check_catalog"]
            original_catalog = copy.deepcopy(trusted_catalog)

            def preflight_probe(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
                return {
                    "root": str(Path(repo_root).resolve()),
                    "head": BASE_COMMIT,
                    "tree": TREE_HASH,
                    "clean": True,
                }

            result = validate_contract(
                contract, policy, repository_probe=preflight_probe
            )
            self.assertFalse(result["dispatchable"])
            self.assertEqual((result["native_calls"], result["authority_writes"]), (0, 0))

            binding = {
                "project_id": result["project_id"],
                "task_id": result["task_id"],
                "spec_version": contract["spec_version"],
                "attempt": 1,
                "contract_hash": result["contract_hash"],
            }
            context = {
                "binding": binding,
                "candidate_commit": BASE_COMMIT,
                "snapshot_root": str(snapshot),
                "scratch_root": str(scratch),
                "control_root": str(control),
                "evidence_root": str(evidence),
            }

            class FakeExecutor:
                def __init__(self) -> None:
                    self.calls: list[tuple[list[str], dict[str, Any]]] = []
                    self.run_root_was_new = False
                    self.fence_accepted = False

                def __call__(self, argv: list[str], **kwargs: Any) -> dict[str, Any]:
                    self.calls.append((list(argv), dict(kwargs)))
                    run_root = Path(kwargs["run_root"])
                    self.run_root_was_new = not run_root.exists()
                    self.fence_accepted = kwargs["before_dispatch"]() is True
                    run_root.mkdir(parents=True)
                    return {
                        "exitCode": 0,
                        "stdout": "fake pass\n",
                        "stderr": "",
                        "native_version": "0.162.0-alpha.2",
                        "permission_profile": "checks",
                        "profile_hash": "e" * 64,
                    }

            fake = FakeExecutor()

            def runner_probe(repo_root: str | os.PathLike[str]) -> dict[str, Any]:
                return {
                    "root": str(Path(repo_root).absolute()),
                    "head": BASE_COMMIT,
                    "tree": TREE_HASH,
                    "clean": True,
                }

            # Only the Git metadata query is mocked; the runner's path and manifest
            # guards still inspect the real isolated fixture directories.
            with patch("native_orchestrator.check_runner.inspect_git_input", side_effect=runner_probe):
                receipt = run_check(
                    "unit",
                    trusted_catalog,
                    context,
                    before_dispatch=lambda: True,
                    native_executor=fake,
                )

            self.assertEqual(receipt["status"], "PASS")
            self.assertEqual(receipt["candidate_commit"], BASE_COMMIT)
            self.assertTrue(receipt["input_unchanged"])
            self.assertEqual(len(fake.calls), 1)
            self.assertTrue(fake.run_root_was_new)
            self.assertTrue(fake.fence_accepted)
            argv, kwargs = fake.calls[0]
            entry = trusted_catalog["unit"]
            self.assertEqual(
                set(entry),
                {
                    "argv", "timeout_seconds", "output_bytes_cap", "write_scope",
                    "network", "shell", "verification", "evidence_sha256",
                },
            )
            self.assertEqual(argv, entry["argv"])
            self.assertEqual(kwargs["cwd"], str(snapshot.resolve()))
            self.assertEqual(kwargs["scratch_root"], str(scratch.resolve()))
            self.assertEqual(kwargs["timeout_ms"], entry["timeout_seconds"] * 1000)
            self.assertEqual(kwargs["output_bytes_cap"], entry["output_bytes_cap"])
            self.assertEqual(kwargs["output_bytes_cap"], 4096)
            self.assertEqual(kwargs["readonly_roots"], [str(snapshot.resolve())])
            self.assertEqual(
                set(kwargs["denied_roots"]),
                {str(control.resolve()), str(evidence.resolve())},
            )
            self.assertEqual(trusted_catalog, original_catalog)

            intent = json.loads((evidence / "intent.json").read_text(encoding="utf-8"))
            self.assertEqual(intent["binding"], binding)
            self.assertEqual(intent["binding"]["contract_hash"], result["contract_hash"])
            self.assertEqual(intent["candidate_commit"], BASE_COMMIT)
            self.assertEqual(intent["check_hash"], canonical_hash(entry))
            self.assertEqual(
                intent["native_policy"]["readonly_roots"], [str(snapshot.resolve())]
            )
            self.assertEqual(
                intent["native_policy"]["writable_roots"], [str(scratch.resolve())]
            )
            self.assertEqual(
                set(intent["native_policy"]["denied_roots"]),
                {str(control.resolve()), str(evidence.resolve())},
            )
            self.assertEqual(intent["native_policy"]["network"], "disabled")
            self.assertEqual(intent["native_policy"]["model_turns"], 0)
            self.assertIs(intent["native_policy"]["auth_copied"], False)

    def test_insufficient_or_already_consumed_budget_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["budget"]["max_native_turns"] = 2
        self._assert_rejected(contract=contract)

        self._assert_rejected(usage={"native_turns": 60, "master_turns": 4})

    def test_unbounded_rework_budget_is_rejected(self) -> None:
        contract = copy.deepcopy(self.contract)
        contract["budget"]["max_reworks"] = None
        self._assert_rejected(contract=contract)


if __name__ == "__main__":
    unittest.main()
