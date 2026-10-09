"""FRAME-004 check runner tests with a fake native executor only.

Run with bytecode disabled: ``python -B -m unittest -q test_check_runner``.
The suite never starts a child process, appserver, model, network request, or service.
Every created file lives in this worktree's ``.runtime/frame-004-tests`` directory.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

from check_runner import CheckError, run_check
from native_check_exec import NativeCheckError


WORKTREE = Path(__file__).absolute().parent
TEST_ROOT = WORKTREE / ".runtime" / "frame-004-tests"
CHECK_ID = "fixture_syntax"
CANDIDATE_COMMIT = "a" * 40
TREE_HASH = "b" * 40
CONTRACT_HASH = "c" * 64
EVIDENCE_HASH = "d" * 64
FIXTURE_ARGV = [sys.executable, "-B", "-c", "pass"]
FIXED_GIT = {
    "head": CANDIDATE_COMMIT,
    "tree": TREE_HASH,
    "clean": True,
}


class Fixture:
    """One isolated input/scratch/control/evidence topology."""

    def __init__(self) -> None:
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self._tmp = tempfile.TemporaryDirectory(prefix="case-", dir=TEST_ROOT)
        self.root = Path(self._tmp.name)
        self.snapshot = self.root / "snapshot"
        self.scratch = self.root / "scratch"
        self.control = self.root / "control"
        self.evidence = self.root / "evidence"
        for path in (self.snapshot, self.scratch, self.control):
            path.mkdir()
        (self.snapshot / "candidate.txt").write_bytes(b"fixed candidate bytes\n")
        (self.control / "control.txt").write_bytes(b"fixed control bytes\n")
        self.context: dict[str, Any] = {
            "binding": {
                "project_id": "fixture_project",
                "task_id": "FRAME004_fixture",
                "spec_version": 1,
                "attempt": 1,
                "contract_hash": CONTRACT_HASH,
            },
            "candidate_commit": CANDIDATE_COMMIT,
            "snapshot_root": str(self.snapshot.absolute()),
            "scratch_root": str(self.scratch.absolute()),
            "control_root": str(self.control.absolute()),
            "evidence_root": str(self.evidence.absolute()),
        }
        self.catalog: dict[str, Any] = {
            CHECK_ID: {
                "argv": list(FIXTURE_ARGV),
                "timeout_seconds": 5,
                "output_bytes_cap": 2048,
                "write_scope": "scratch",
                "network": "disabled",
                "shell": False,
                "verification": "VERIFIED",
                "evidence_sha256": EVIDENCE_HASH,
            }
        }

    def close(self) -> None:
        self._tmp.cleanup()


class FakeNativeExecutor:
    """Capture runner policy and emulate only the native executor's return value."""

    def __init__(
        self,
        *,
        result: dict[str, Any] | None = None,
        error: BaseException | None = None,
        mutate_snapshot: Path | None = None,
        on_dispatch=None,
    ) -> None:
        self.result = result or {
            "exitCode": 0,
            "stdout": "fixture stdout\n",
            "stderr": "fixture stderr\n",
            "native_version": "0.162.0-alpha.2",
            "permission_profile": "checks",
            "profile_hash": "e" * 64,
        }
        self.error = error
        self.mutate_snapshot = mutate_snapshot
        self.on_dispatch = on_dispatch
        self.calls: list[tuple[list[str], dict[str, Any]]] = []
        self.dispatches = 0
        self.run_root_was_new: list[bool] = []
        self.fence_results: list[bool] = []

    def __call__(self, command: list[str], **kwargs: Any) -> dict[str, Any]:
        self.calls.append((list(command), dict(kwargs)))
        run_root = Path(kwargs["run_root"])
        self.run_root_was_new.append(not run_root.exists())
        before_dispatch = kwargs.get("before_dispatch")
        if not callable(before_dispatch):
            raise AssertionError("runner must pass the trusted dispatch fence")
        accepted = before_dispatch()
        self.fence_results.append(accepted is True)
        if accepted is not True:
            raise RuntimeError("dispatch fence refused")
        self.dispatches += 1
        # Model the executor-owned fresh diagnostics directory; do not execute argv.
        run_root.mkdir(parents=True, exist_ok=True)
        if self.on_dispatch is not None:
            self.on_dispatch(kwargs)
        if self.mutate_snapshot is not None:
            self.mutate_snapshot.write_bytes(b"mutated candidate bytes\n")
        if self.error is not None:
            raise self.error
        return dict(self.result)


class CheckRunnerFixtureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()
        self.addCleanup(self.fixture.close)

    def _git_patch(self, fixture: Fixture | None = None):
        active = fixture or self.fixture

        def inspect(path: str | os.PathLike[str]) -> dict[str, Any]:
            return {"root": str(Path(path).absolute()), **FIXED_GIT}

        return patch("check_runner.inspect_git_input", side_effect=inspect)

    def _run(
        self,
        *,
        check_id: str = CHECK_ID,
        catalog: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        before_dispatch=lambda: True,
        native_executor: FakeNativeExecutor | None = None,
    ) -> dict[str, Any]:
        with self._git_patch():
            return run_check(
                check_id,
                self.fixture.catalog if catalog is None else catalog,
                self.fixture.context if context is None else context,
                before_dispatch=before_dispatch,
                native_executor=native_executor or FakeNativeExecutor(),
            )

    def _new_fixture(self) -> Fixture:
        fixture = Fixture()
        self.addCleanup(fixture.close)
        return fixture

    def _run_for(
        self,
        fixture: Fixture,
        fake: FakeNativeExecutor,
        *,
        check_id: str = CHECK_ID,
        catalog: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
        before_dispatch=lambda: True,
    ) -> dict[str, Any]:
        with self._git_patch(fixture):
            return run_check(
                check_id,
                fixture.catalog if catalog is None else catalog,
                fixture.context if context is None else context,
                before_dispatch=before_dispatch,
                native_executor=fake,
            )

    def _assert_rejected_before_executor(
        self,
        *,
        check_id: str = CHECK_ID,
        catalog: dict[str, Any] | None = None,
        context: dict[str, Any] | None = None,
    ) -> None:
        fake = FakeNativeExecutor()
        with self.assertRaises(CheckError):
            self._run(
                check_id=check_id,
                catalog=catalog,
                context=context,
                native_executor=fake,
            )
        self.assertEqual(fake.calls, [], "invalid input must not reach the executor")

    def test_check_id_selects_exact_catalog_argv_and_has_no_command_override(self) -> None:
        fake = FakeNativeExecutor()
        receipt = self._run(native_executor=fake)
        self.assertEqual(receipt["status"], "PASS")
        self.assertEqual(fake.calls[0][0], FIXTURE_ARGV)
        self.assertIsInstance(fake.calls[0][0], list)
        self.assertEqual(fake.dispatches, 1)
        self.assertTrue(fake.run_root_was_new[0])
        self.assertEqual(receipt["check_id"], CHECK_ID)

        # The API accepts a check ID and trusted catalog, never argv parameters.
        fake = FakeNativeExecutor()
        with self.assertRaises(TypeError):
            with self._git_patch():
                run_check(
                    CHECK_ID,
                    self.fixture.catalog,
                    self.fixture.context,
                    before_dispatch=lambda: True,
                    native_executor=fake,
                    command=["attacker", "--override"],
                )
        self.assertEqual(fake.calls, [])

        fixture = self._new_fixture()
        fake = FakeNativeExecutor()
        with self.assertRaises(CheckError):
            self._run_for(fixture, fake, check_id="fixture_unknown")
        self.assertEqual(fake.calls, [])

    def test_binding_candidate_catalog_and_capability_errors_reject_before_executor(self) -> None:
        bad_contexts: list[dict[str, Any]] = []
        missing_binding = copy.deepcopy(self.fixture.context)
        del missing_binding["binding"]["attempt"]
        bad_contexts.append(missing_binding)
        blank_binding = copy.deepcopy(self.fixture.context)
        blank_binding["binding"]["project_id"] = " "
        bad_contexts.append(blank_binding)
        bad_candidate = copy.deepcopy(self.fixture.context)
        bad_candidate["candidate_commit"] = "not-a-commit"
        bad_contexts.append(bad_candidate)
        for context in bad_contexts:
            with self.subTest(context=context):
                self._assert_rejected_before_executor(context=context)

        bad_entries = [
            ("write_scope", "candidate"),
            ("network", "enabled"),
            ("shell", True),
            ("verification", "UNVERIFIED"),
            ("evidence_sha256", "bad-hash"),
            ("timeout_seconds", 0),
            ("timeout_seconds", -1),
            ("timeout_seconds", 601),
            ("output_bytes_cap", 0),
            ("output_bytes_cap", -1),
            ("output_bytes_cap", 1024 * 1024 + 1),
            ("argv", "fixture-checker --mode syntax"),
        ]
        for field, invalid_value in bad_entries:
            with self.subTest(field=field, invalid_value=invalid_value):
                fixture = self._new_fixture()
                catalog = copy.deepcopy(fixture.catalog)
                catalog[CHECK_ID][field] = invalid_value
                fake = FakeNativeExecutor()
                with self.assertRaises(CheckError):
                    self._run_for(fixture, fake, catalog=catalog)
                self.assertEqual(fake.calls, [])

        fixture = self._new_fixture()
        incomplete_catalog: dict[str, Any] = {}
        fake = FakeNativeExecutor()
        with self.assertRaises(CheckError):
            self._run_for(fixture, fake, catalog=incomplete_catalog)
        self.assertEqual(fake.calls, [])

    def test_overlapping_paths_and_existing_evidence_root_reject_before_executor(self) -> None:
        overlap = copy.deepcopy(self.fixture.context)
        overlap["scratch_root"] = overlap["snapshot_root"]
        self._assert_rejected_before_executor(context=overlap)

        nested = copy.deepcopy(self.fixture.context)
        nested["scratch_root"] = str((self.fixture.snapshot / "nested").absolute())
        (self.fixture.snapshot / "nested").mkdir()
        self._assert_rejected_before_executor(context=nested)

        # Reusing a consumed per-attempt evidence directory is never a retry.
        fake = FakeNativeExecutor(error=ConnectionError("transport lost after dispatch"))
        receipt = self._run(native_executor=fake)
        self.assertEqual(receipt["status"], "ERROR")
        self.assertEqual(fake.dispatches, 1)
        uncertain_intent = json.loads((self.fixture.evidence / "intent.json").read_text(encoding="utf-8"))
        self.assertEqual(uncertain_intent["state"], "NEEDS_RECONCILIATION")
        self.assertEqual(uncertain_intent["outcome"], "ERROR")
        with self.assertRaises(CheckError):
            self._run(native_executor=fake)
        self.assertEqual(len(fake.calls), 1)

    def test_symlinked_snapshot_root_is_rejected_before_executor(self) -> None:
        link = self.fixture.root / "snapshot-link"
        try:
            link.symlink_to(self.fixture.snapshot, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"platform cannot create the symlink fixture: {error}")
        context = copy.deepcopy(self.fixture.context)
        context["snapshot_root"] = str(link.absolute())
        self._assert_rejected_before_executor(context=context)

    def test_false_dispatch_fence_rejects_before_executor_start(self) -> None:
        fake = FakeNativeExecutor()
        with self.assertRaises(CheckError):
            self._run(native_executor=fake, before_dispatch=lambda: False)
        self.assertEqual(fake.dispatches, 0)
        self.assertEqual(fake.calls, [])
        self.assertFalse(self.fixture.evidence.exists())

    def test_dispatch_intent_binds_candidate_manifest_and_catalog_before_execution(self) -> None:
        fixture = self._new_fixture()
        candidate = fixture.snapshot / "candidate.txt"
        input_bytes_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
        def assert_dispatched_first(kwargs: dict[str, Any]) -> None:
            evidence = Path(kwargs["run_root"]).parent
            intent = json.loads((evidence / "intent.json").read_text(encoding="utf-8"))
            manifest = json.loads((evidence / "input-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(intent["state"], "DISPATCHED")
            self.assertEqual(intent["candidate_commit"], CANDIDATE_COMMIT)
            self.assertEqual(intent["input_hash"], manifest["sha256"])
            self.assertEqual(manifest["files"][0]["sha256"], input_bytes_hash)

        fake = FakeNativeExecutor(on_dispatch=assert_dispatched_first)
        receipt = self._run_for(fixture, fake)
        intent_path = fixture.evidence / "intent.json"
        self.assertTrue(intent_path.is_file())
        intent = json.loads(intent_path.read_text(encoding="utf-8"))
        serialized_intent = json.dumps(intent, sort_keys=True)
        self.assertEqual(intent["state"], "COMPLETED")
        self.assertIn(CANDIDATE_COMMIT, serialized_intent)
        self.assertIn(input_bytes_hash, serialized_intent)
        self.assertIn(CONTRACT_HASH, serialized_intent)
        self.assertIn(receipt["catalog_hash"], serialized_intent)
        self.assertEqual(receipt["candidate_commit"], CANDIDATE_COMMIT)
        self.assertRegex(receipt["input_hash"], r"^[0-9a-f]{64}$")
        self.assertRegex(receipt["catalog_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(fake.calls[0][0], FIXTURE_ARGV)

    def test_exit_zero_is_pass_and_nonzero_is_fail(self) -> None:
        fixture = self._new_fixture()
        passed = self._run_for(fixture, FakeNativeExecutor())
        self.assertEqual((passed["status"], passed["exit_code"]), ("PASS", 0))

        fixture = self._new_fixture()
        failed = self._run_for(
            fixture,
            FakeNativeExecutor(result={
                "exitCode": 7,
                "stdout": "quality failure\n",
                "stderr": "fixture diagnostic\n",
                "native_version": "0.162.0-alpha.2",
                "permission_profile": "checks",
                "profile_hash": "e" * 64,
            }),
        )
        self.assertEqual((failed["status"], failed["exit_code"]), ("FAIL", 7))

    def test_execution_timeout_transport_and_environment_errors_are_error(self) -> None:
        for error, accepted_codes in (
            (TimeoutError("fixture timeout"), {"TIMEOUT", "EXECUTION_ERROR", "RECONCILIATION_REQUIRED"}),
            (ConnectionError("fixture transport failure"), {"EXECUTION_ERROR", "RECONCILIATION_REQUIRED"}),
        ):
            with self.subTest(error=type(error).__name__):
                fixture = self._new_fixture()
                fake = FakeNativeExecutor(error=error)
                receipt = self._run_for(fixture, fake)
                self.assertEqual(receipt["status"], "ERROR")
                self.assertIn(receipt["code"], accepted_codes)
                self.assertEqual(fake.dispatches, 1)

        fixture = self._new_fixture()
        bad_environment = FakeNativeExecutor(result={
            "exitCode": 0,
            "stdout": "must not pass\n",
            "stderr": "",
            "native_version": "",
            "permission_profile": "workspaceWrite",
            "profile_hash": "invalid",
        })
        receipt = self._run_for(fixture, bad_environment)
        self.assertEqual(receipt["status"], "ERROR")
        self.assertNotEqual(receipt["status"], "PASS")

        fixture = self._new_fixture()
        capped_output = FakeNativeExecutor(result={
            "exitCode": 0,
            "stdout": "x" * fixture.catalog[CHECK_ID]["output_bytes_cap"],
            "stderr": "",
            "native_version": "0.162.0-alpha.2",
            "permission_profile": "checks",
            "profile_hash": "e" * 64,
        })
        receipt = self._run_for(fixture, capped_output)
        self.assertEqual(receipt["status"], "ERROR")
        self.assertEqual(receipt["code"], "OUTPUT_INCOMPLETE")

    def test_stdout_stderr_are_separate_bounded_external_bytes_not_receipt_canaries(self) -> None:
        stdout = ("STDOUT-CANARY:" + ("left-only-" * 390)).encode("utf-8")
        stderr = ("STDERR-CANARY:" + ("right-only-" * 350)).encode("utf-8")
        fixture = self._new_fixture()
        catalog = copy.deepcopy(fixture.catalog)
        catalog[CHECK_ID]["output_bytes_cap"] = 16384
        fake = FakeNativeExecutor(result={
            "exitCode": 0,
            "stdout": stdout.decode("utf-8"),
            "stderr": stderr.decode("utf-8"),
            "native_version": "0.162.0-alpha.2",
            "permission_profile": "checks",
            "profile_hash": "e" * 64,
        })
        receipt = self._run_for(fixture, fake, catalog=catalog)
        encoded = json.dumps(receipt, ensure_ascii=True).encode("utf-8")
        self.assertLessEqual(len(encoded), 8192)
        self.assertNotIn(b"STDOUT-CANARY", encoded)
        self.assertNotIn(b"STDERR-CANARY", encoded)
        self.assertEqual(receipt["stdout_bytes"], len(stdout))
        self.assertEqual(receipt["stderr_bytes"], len(stderr))
        self.assertEqual(receipt["stdout_sha256"], hashlib.sha256(stdout).hexdigest())
        self.assertEqual(receipt["stderr_sha256"], hashlib.sha256(stderr).hexdigest())
        self.assertTrue(receipt["stdout_ref"])
        self.assertTrue(receipt["stderr_ref"])
        stdout_path = Path(receipt["stdout_ref"])
        stderr_path = Path(receipt["stderr_ref"])
        if not stdout_path.is_absolute():
            stdout_path = fixture.evidence / stdout_path
        if not stderr_path.is_absolute():
            stderr_path = fixture.evidence / stderr_path
        self.assertEqual(stdout_path.read_bytes(), stdout)
        self.assertEqual(stderr_path.read_bytes(), stderr)
        self.assertNotEqual(stdout_path.absolute(), stderr_path.absolute())
        self.assertEqual(receipt["evidence_ref"], str((fixture.evidence / "receipt.json").absolute()))
        persisted_receipt = json.loads(Path(receipt["evidence_ref"]).read_text(encoding="utf-8"))
        self.assertEqual(persisted_receipt, receipt)

    def test_snapshot_drift_after_execution_is_error(self) -> None:
        fixture = self._new_fixture()
        fake = FakeNativeExecutor(mutate_snapshot=fixture.snapshot / "candidate.txt")
        receipt = self._run_for(fixture, fake)
        self.assertEqual(receipt["status"], "ERROR")
        self.assertEqual(receipt["code"], "INPUT_DRIFT")
        self.assertEqual(fake.dispatches, 1)

    def test_executor_receives_fixed_sandbox_roots_and_catalog_limits(self) -> None:
        fake = FakeNativeExecutor()
        self._run(native_executor=fake)
        command, kwargs = fake.calls[0]
        self.assertEqual(command, FIXTURE_ARGV)
        self.assertEqual(Path(kwargs["cwd"]).absolute(), self.fixture.snapshot.absolute())
        self.assertEqual(Path(kwargs["scratch_root"]).absolute(), self.fixture.scratch.absolute())
        self.assertEqual(kwargs["timeout_ms"], 5000)
        self.assertEqual(kwargs["output_bytes_cap"], 2048)
        self.assertTrue(fake.run_root_was_new[0])
        readonly = {str(Path(value).absolute()) for value in kwargs["readonly_roots"]}
        denied = {str(Path(value).absolute()) for value in kwargs["denied_roots"]}
        self.assertIn(str(self.fixture.snapshot.absolute()), readonly)
        self.assertIn(str(self.fixture.control.absolute()), denied)
        self.assertIn(str(self.fixture.evidence.absolute()), denied)
        self.assertNotIn("env", kwargs, "catalog callers cannot inject environment overrides")
        self.assertEqual(self.fixture.catalog[CHECK_ID]["write_scope"], "scratch")
        self.assertEqual(self.fixture.catalog[CHECK_ID]["network"], "disabled")
        self.assertIs(self.fixture.catalog[CHECK_ID]["shell"], False)

    def test_launcher_error_preserves_diagnostics_and_is_never_quality_failure(self) -> None:
        diagnostic = "MXC launcher: cannot locate required Windows platform directory: HRESULT 0x80070003\n"
        failure = NativeCheckError("NATIVE_SANDBOX_START_FAILED", {
            "exitCode": 1, "stdout": "", "stderr": diagnostic,
            "native_version": "0.162.0-alpha.2", "permission_profile": "checks", "profile_hash": "e" * 64,
        })
        receipt = self._run(native_executor=FakeNativeExecutor(error=failure))
        self.assertEqual((receipt["status"], receipt["code"]), ("ERROR", "NATIVE_SANDBOX_START_FAILED"))
        self.assertTrue(receipt["input_unchanged"])
        self.assertEqual(Path(receipt["stderr_ref"]).read_bytes(), diagnostic.encode("utf-8"))
        self.assertEqual(receipt["stderr_sha256"], hashlib.sha256(diagnostic.encode("utf-8")).hexdigest())
        intent = json.loads((self.fixture.evidence / "intent.json").read_text(encoding="utf-8"))
        self.assertEqual(intent["state"], "NEEDS_RECONCILIATION")

    def test_unverified_prior_native_version_and_unsafe_python_flags_are_rejected(self) -> None:
        for argv in ([sys.executable, "-c", "pass"], [sys.executable, "-B", "-I", "-c", "pass"]):
            fixture = self._new_fixture()
            catalog = copy.deepcopy(fixture.catalog)
            catalog[CHECK_ID]["argv"] = argv
            fake = FakeNativeExecutor()
            with self.assertRaises(CheckError):
                self._run_for(fixture, fake, catalog=catalog)
            self.assertEqual(fake.calls, [])
            self.assertFalse(fixture.evidence.exists())
        fake = FakeNativeExecutor()
        fake.result["native_version"] = "0.160.1"
        receipt = self._run(native_executor=fake)
        self.assertEqual((receipt["status"], receipt["code"]), ("ERROR", "NATIVE_VERSION_CHANGED"))

    def test_authority_loss_after_dispatch_leaves_intent_and_never_replays(self) -> None:
        authority = {"valid": True}
        def revoke(_kwargs):
            authority["valid"] = False
        fake = FakeNativeExecutor(on_dispatch=revoke)
        with self.assertRaises(CheckError):
            self._run(before_dispatch=lambda: authority["valid"], native_executor=fake)
        self.assertEqual(fake.dispatches, 1)
        self.assertFalse((self.fixture.evidence / "receipt.json").exists())
        intent = json.loads((self.fixture.evidence / "intent.json").read_text(encoding="utf-8"))
        self.assertEqual(intent["state"], "DISPATCHED")
        authority["valid"] = True
        with self.assertRaises(CheckError):
            self._run(native_executor=fake)
        self.assertEqual(fake.dispatches, 1)


if __name__ == "__main__":
    unittest.main()
