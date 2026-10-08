"""Isolated FRAME-002 contract preflight tests.

Run only with bytecode disabled, for example:
    python -B -m unittest -q test_execution_contract

The fixtures use temporary repositories under this worktree's .runtime directory
and a fake repository probe. They never invoke Git, checks, models, or the controller.
"""
from __future__ import annotations

import copy
import os
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from execution_contract import ContractError, canonical_hash, validate_contract


WORKTREE = Path(__file__).resolve().parent
SCRATCH_ROOT = WORKTREE / ".runtime" / "frame-002-tests"
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
                    "argv": ["E:/python/python.exe", "-B", "-m", "unittest", "-q"],
                    "timeout_seconds": 120,
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
