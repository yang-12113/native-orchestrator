"""Isolated FRAME-004 tests for the native checks adapter.

The RPC double returns protocol fixtures and never starts a process. All fixture
files, including the fake codex.exe used by path validation, stay under a fresh
directory in ``.runtime/frame-004-native-tests``.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import tomllib
import unittest
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import patch

import native_check_exec
from native_check_exec import NativeCheckError, execute_native


WORKTREE = Path(__file__).absolute().parent
TEST_ROOT = WORKTREE / ".runtime" / "frame-004-native-tests"
FIXTURE_ARGV = [sys.executable, "-B", "-c", "pass"]
SYNTHETIC_SECRET = "fixture-secret-must-not-enter-private-home"


class FakeRpc:
    """Emulate only the native protocol; this object has no process handle."""

    def __init__(
        self,
        *,
        initialized: dict[str, Any] | None = None,
        profiles: dict[str, Any] | None = None,
        command_result: dict[str, Any] | None = None,
        command_error: BaseException | None = None,
    ) -> None:
        self.initialized = initialized or {
            "userAgent": "Codex/0.162.0-alpha.2",
            "serverInfo": {"version": "0.162.0-alpha.2"},
        }
        self.profiles = profiles or {
            "data": [{"id": "checks", "allowed": True}],
            "nextCursor": None,
        }
        self.command_result = command_result or {
            "exitCode": 0,
            "stdout": "native fixture stdout\n",
            "stderr": "native fixture stderr\n",
        }
        self.command_error = command_error
        self.attached = False
        self.spawned_process = False
        self.argv: list[str] | None = None
        self.cwd: str | None = None
        self.environment: dict[str, str] | None = None
        self.log_path: Path | None = None
        self.calls: list[dict[str, Any]] = []
        self.notifications: list[str] = []
        self.close_count = 0

    def attach(self, argv, cwd, env=None, log=None, **_ignored):
        self.attached = True
        self.argv = list(argv)
        self.cwd = str(cwd)
        self.environment = dict(env or {})
        self.log_path = Path(log)
        self._record("construct", None)
        return self

    def _record(self, method: str, direction: str | None) -> None:
        assert self.log_path is not None
        event = {"method": method, "direction": direction}
        with self.log_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event) + "\n")

    def call(self, method: str, params=None, timeout=30):
        self.calls.append({"method": method, "params": params or {}, "timeout": timeout})
        self._record(method, "call")
        if method == "initialize":
            return self.initialized
        if method == "permissionProfile/list":
            return self.profiles
        if method == "command/exec":
            if self.command_error is not None:
                raise self.command_error
            return dict(self.command_result)
        raise AssertionError(f"unexpected RPC method: {method}")

    def notify(self, method: str, params=None) -> None:
        self.notifications.append(method)
        self._record(method, "notify")

    def close(self) -> None:
        self.close_count += 1


class Fixture:
    """One persistent, unique path topology for each unit test invocation."""

    def __init__(self) -> None:
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = TEST_ROOT / f"case-{uuid.uuid4().hex}"
        self.root.mkdir()
        self.snapshot = self.root / "input"
        self.scratch = self.root / "scratch"
        self.control = self.root / "control"
        self.evidence = self.root / "evidence"
        self.native_bin = self.root / "native-bin"
        for path in (self.snapshot, self.scratch, self.control, self.evidence, self.native_bin):
            path.mkdir()
        (self.snapshot / "candidate.txt").write_bytes(b"fixed candidate bytes\n")
        (self.control / "control.txt").write_bytes(b"fixed controller bytes\n")
        # It is only a regular file for the adapter's executable path checks.
        # The patched Rpc never launches it.
        (self.native_bin / "codex.exe").write_bytes(b"fixture placeholder; never executed\n")
        self.run_root = self.evidence / "native-run"

    def execute(
        self,
        fake: FakeRpc,
        *,
        command=FIXTURE_ARGV,
        cwd=None,
        scratch_root=None,
        readonly_roots=None,
        denied_roots=None,
        run_root=None,
        timeout_ms=5000,
        output_bytes_cap=2048,
        before_dispatch=lambda: True,
        environment_overrides=None,
    ):
        params = {
            "command": command,
            "cwd": self.snapshot if cwd is None else cwd,
            "scratch_root": self.scratch if scratch_root is None else scratch_root,
            "readonly_roots": [self.snapshot] if readonly_roots is None else readonly_roots,
            "denied_roots": [self.control, self.evidence] if denied_roots is None else denied_roots,
            "run_root": self.run_root if run_root is None else run_root,
            "timeout_ms": timeout_ms,
            "output_bytes_cap": output_bytes_cap,
            "before_dispatch": before_dispatch,
        }
        test_environment = {
            "PATH": str(self.native_bin),
            "PATHEXT": ".EXE",
            "SYSTEMROOT": str(self.root / "windows"),
            "LOCALAPPDATA": str(self.root / "local-app-data"),
            "CODEX_HOME": "synthetic-original-home-must-not-be-copied",
            "OPENAI_API_KEY": SYNTHETIC_SECRET,
            "AZURE_OPENAI_API_KEY": "another-synthetic-secret",
            "SERVICE_ACCESS_TOKEN": "synthetic-token",
            "FRAME004_UNTRUSTED_ENV": "arbitrary-value-must-not-be-copied",
        }
        if environment_overrides:
            test_environment.update(environment_overrides)
        # Both patches are scoped to this call and restored even when an assertion
        # or NativeCheckError escapes. No process, model, or network is started.
        with patch.object(native_check_exec, "Rpc", side_effect=fake.attach):
            with patch.dict(os.environ, test_environment):
                return execute_native(**params)


@unittest.skipUnless(os.name == "nt", "the native checks adapter is Windows-only")
class NativeCheckExecTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = Fixture()

    def test_private_profile_and_rpc_result_are_bound_to_fresh_diagnostics_root(self) -> None:
        fake = FakeRpc()
        result = self.fixture.execute(fake)

        self.assertTrue(self.fixture.run_root.is_dir())
        self.assertTrue(self.fixture.run_root.is_relative_to(self.fixture.evidence))
        self.assertEqual(
            [str(fake.argv[0]).casefold(), fake.argv[1]],
            [str(self.fixture.native_bin / "codex.exe").casefold(), "app-server"],
        )
        self.assertEqual(Path(fake.cwd), self.fixture.run_root)
        self.assertEqual(fake.log_path, self.fixture.run_root / "native-rpc.jsonl")
        self.assertTrue(fake.log_path.is_file())
        self.assertEqual(fake.close_count, 1)
        self.assertFalse(fake.spawned_process)
        self.assertEqual([call["method"] for call in fake.calls], [
            "initialize", "permissionProfile/list", "command/exec",
        ])
        self.assertEqual(fake.notifications, ["initialized"])

        config_path = self.fixture.run_root / "home" / "config.toml"
        config_bytes = config_path.read_bytes()
        config = tomllib.loads(config_bytes.decode("utf-8"))
        permissions = config["permissions"]["checks"]
        filesystem = permissions["filesystem"]
        expected_filesystem = {
            ":minimal": "read",
            str(Path(sys.executable).absolute().parent): "read",
            str(self.fixture.snapshot): "read",
            str(self.fixture.scratch): "write",
            str(self.fixture.control): "deny",
            str(self.fixture.evidence): "deny",
        }
        self.assertEqual(filesystem, expected_filesystem)
        self.assertIs(permissions["network"]["enabled"], False)
        self.assertNotIn(SYNTHETIC_SECRET, config_bytes.decode("utf-8"))
        self.assertNotIn("synthetic-original-home", config_bytes.decode("utf-8"))

        self.assertEqual((fake.environment or {}).get("CODEX_HOME"), str(self.fixture.run_root / "home"))
        self.assertEqual((fake.environment or {}).get("LOCALAPPDATA"), str(self.fixture.root / "local-app-data"))
        for forbidden in (
            "OPENAI_API_KEY", "AZURE_OPENAI_API_KEY", "SERVICE_ACCESS_TOKEN",
            "FRAME004_UNTRUSTED_ENV",
        ):
            self.assertNotIn(forbidden, fake.environment or {})
        self.assertEqual((fake.environment or {}).get("TEMP"), str(self.fixture.scratch))
        self.assertEqual((fake.environment or {}).get("TMP"), str(self.fixture.scratch))

        exec_params = fake.calls[-1]["params"]
        self.assertEqual(exec_params["command"], FIXTURE_ARGV)
        self.assertEqual(exec_params["cwd"], str(self.fixture.snapshot))
        self.assertEqual(exec_params["permissionProfile"], "checks")
        self.assertEqual(exec_params["timeoutMs"], 5000)
        self.assertEqual(exec_params["outputBytesCap"], 2048)
        self.assertEqual(exec_params["env"], {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "TEMP": str(self.fixture.scratch),
            "TMP": str(self.fixture.scratch),
        })
        self.assertEqual(result["exitCode"], 0)
        self.assertEqual(result["permission_profile"], "checks")
        self.assertEqual(result["native_version"], "0.162.0-alpha.2")
        self.assertEqual(result["profile_hash"], hashlib.sha256(config_bytes).hexdigest())

    def test_run_root_inside_denied_evidence_is_allowed_but_input_and_scratch_overlap_is_rejected(self) -> None:
        fake = FakeRpc()
        self.fixture.execute(fake)
        self.assertTrue(fake.attached)
        self.assertEqual(fake.calls[-1]["method"], "command/exec")

        for parent_name in ("snapshot", "scratch"):
            with self.subTest(parent=parent_name):
                fixture = Fixture()
                rejected = FakeRpc()
                parent = getattr(fixture, parent_name)
                run_root = parent / "private-diagnostics"
                with self.assertRaises(NativeCheckError) as caught:
                    fixture.execute(rejected, run_root=run_root)
                self.assertEqual(caught.exception.code, "OVERLAPPING_PATHS")
                self.assertFalse(rejected.attached)

    def test_invalid_commands_limits_and_paths_never_construct_rpc(self) -> None:
        invalid_commands = ([], "python -B -c pass", ["cmd.exe", "/c", "echo unsafe"])
        for command in invalid_commands:
            with self.subTest(command=command):
                fixture = Fixture()
                fake = FakeRpc()
                with self.assertRaises(NativeCheckError):
                    fixture.execute(fake, command=command)
                self.assertFalse(fake.attached)

        for overrides in (
            {"timeout_ms": 0},
            {"timeout_ms": True},
            {"output_bytes_cap": 0},
            {"output_bytes_cap": 1024 * 1024 + 1},
        ):
            with self.subTest(overrides=overrides):
                fixture = Fixture()
                fake = FakeRpc()
                with self.assertRaises(NativeCheckError) as caught:
                    fixture.execute(fake, **overrides)
                self.assertEqual(caught.exception.code, "INVALID_LIMIT")
                self.assertFalse(fake.attached)

        fixture = Fixture()
        fake = FakeRpc()
        existing_run_root = fixture.evidence / "already-used"
        existing_run_root.mkdir()
        with self.assertRaises(NativeCheckError) as caught:
            fixture.execute(fake, run_root=existing_run_root)
        self.assertEqual(caught.exception.code, "RUN_ROOT_NOT_FRESH")
        self.assertFalse(fake.attached)

        fixture = Fixture()
        fake = FakeRpc()
        traversal = str(fixture.snapshot / ".." / "input")
        with self.assertRaises(NativeCheckError) as caught:
            fixture.execute(fake, cwd=traversal)
        self.assertEqual(caught.exception.code, "INVALID_PATH")
        self.assertFalse(fake.attached)

    def test_unverified_version_and_disallowed_checks_profile_stop_before_exec_and_close_rpc(self) -> None:
        cases = (
            (
                FakeRpc(initialized={"userAgent": "Codex/9.9.9", "serverInfo": {"version": "9.9.9"}}),
                "NATIVE_VERSION_UNVERIFIED",
            ),
            (
                FakeRpc(profiles={"data": [{"id": "checks", "allowed": False}], "nextCursor": None}),
                "CHECKS_PROFILE_UNAVAILABLE",
            ),
        )
        for fake, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                fixture = Fixture()
                with self.assertRaises(NativeCheckError) as caught:
                    fixture.execute(fake)
                self.assertEqual(caught.exception.code, expected_code)
                self.assertTrue(fake.attached)
                self.assertNotIn("command/exec", [call["method"] for call in fake.calls])
                self.assertEqual(fake.close_count, 1)

    def test_authority_invalidation_after_profile_check_prevents_exec_and_closes_rpc(self) -> None:
        fake = FakeRpc()

        def revoke_after_profile_list() -> bool:
            return not (fake.calls and fake.calls[-1]["method"] == "permissionProfile/list")

        with self.assertRaises(NativeCheckError) as caught:
            self.fixture.execute(fake, before_dispatch=revoke_after_profile_list)
        self.assertEqual(caught.exception.code, "DISPATCH_FENCE")
        self.assertTrue(fake.attached)
        self.assertEqual([call["method"] for call in fake.calls], ["initialize", "permissionProfile/list"])
        self.assertEqual(fake.close_count, 1)

    def test_timeout_truncation_and_output_over_cap_are_errors_and_always_close(self) -> None:
        timeout = FakeRpc(command_error=TimeoutError("fixture timeout"))
        with self.assertRaises(NativeCheckError) as caught:
            self.fixture.execute(timeout)
        self.assertEqual(caught.exception.code, "COMMAND_TIMEOUT")
        self.assertEqual(timeout.close_count, 1)
        self.assertEqual([call["method"] for call in timeout.calls].count("command/exec"), 1)

        truncated = FakeRpc(command_result={
            "exitCode": 0, "stdout": "cut", "stderr": "", "stdoutTruncated": True,
        })
        with self.assertRaises(NativeCheckError) as caught:
            Fixture().execute(truncated)
        self.assertEqual(caught.exception.code, "OUTPUT_INCOMPLETE")
        self.assertIs(caught.exception.captured_result["output_complete"], False)
        self.assertEqual(truncated.close_count, 1)

        too_large = FakeRpc(command_result={"exitCode": 0, "stdout": "五", "stderr": ""})
        with self.assertRaises(NativeCheckError) as caught:
            Fixture().execute(too_large, output_bytes_cap=2)
        self.assertEqual(caught.exception.code, "OUTPUT_INCOMPLETE")
        self.assertIs(caught.exception.captured_result["output_complete"], False)
        self.assertEqual(too_large.close_count, 1)

    def test_each_stream_has_its_own_cap_even_when_combined_output_is_larger(self) -> None:
        fake = FakeRpc(command_result={
            "exitCode": 0,
            "stdout": "1234567",
            "stderr": "abc",
        })
        result = self.fixture.execute(fake, output_bytes_cap=8)
        self.assertEqual(len(result["stdout"].encode("utf-8")), 7)
        self.assertEqual(len(result["stderr"].encode("utf-8")), 3)
        self.assertGreater(len(result["stdout"].encode("utf-8")) + len(result["stderr"].encode("utf-8")), 8)
        self.assertEqual(fake.close_count, 1)

    def test_sandbox_launcher_failure_is_an_execution_error_with_bound_diagnostics(self) -> None:
        fake = FakeRpc(command_result={
            "exitCode": 1,
            "stdout": "",
            "stderr": "MXC launcher: sandbox initialization failed\n",
        })
        with self.assertRaises(NativeCheckError) as caught:
            self.fixture.execute(fake)
        error = caught.exception
        self.assertEqual(error.code, "NATIVE_SANDBOX_START_FAILED")
        self.assertIsInstance(error.captured_result, dict)
        self.assertEqual(error.captured_result["exitCode"], 1)
        self.assertEqual(error.captured_result["stderr"], "MXC launcher: sandbox initialization failed\n")
        self.assertEqual(error.captured_result["native_version"], "0.162.0-alpha.2")
        self.assertEqual(error.captured_result["permission_profile"], "checks")
        self.assertRegex(error.captured_result["profile_hash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("status", error.captured_result)
        self.assertEqual(fake.close_count, 1)

    def test_uncertain_rpc_failure_is_not_retried(self) -> None:
        fake = FakeRpc(command_error=native_check_exec.RpcError("fixture response lost"))
        with self.assertRaises(NativeCheckError) as caught:
            self.fixture.execute(fake)
        self.assertEqual(caught.exception.code, "NATIVE_RPC_ERROR")
        self.assertEqual([call["method"] for call in fake.calls].count("command/exec"), 1)
        self.assertEqual(fake.close_count, 1)

    def test_caller_cannot_supply_an_environment_override(self) -> None:
        fake = FakeRpc()
        with self.assertRaises(TypeError):
            execute_native(
                FIXTURE_ARGV,
                cwd=self.fixture.snapshot,
                scratch_root=self.fixture.scratch,
                readonly_roots=[self.fixture.snapshot],
                denied_roots=[self.fixture.control, self.fixture.evidence],
                run_root=self.fixture.run_root,
                timeout_ms=5000,
                output_bytes_cap=2048,
                before_dispatch=lambda: True,
                env={"OPENAI_API_KEY": SYNTHETIC_SECRET},
            )
        self.assertFalse(fake.attached)

    def test_missing_required_windows_environment_is_rejected_before_rpc_without_leaking_global_changes(self) -> None:
        for missing_key in ("SYSTEMROOT", "LOCALAPPDATA"):
            with self.subTest(missing_key=missing_key):
                fixture = Fixture()
                fake = FakeRpc()
                watched = ("SYSTEMROOT", "LOCALAPPDATA")
                before = {key: os.environ.get(key) for key in watched}
                with self.assertRaises(NativeCheckError) as caught:
                    fixture.execute(fake, environment_overrides={missing_key: ""})
                self.assertEqual(caught.exception.code, "NATIVE_ENVIRONMENT_UNAVAILABLE")
                self.assertFalse(fake.attached)
                self.assertFalse(fixture.run_root.exists())
                self.assertEqual({key: os.environ.get(key) for key in watched}, before)

    def test_native_exit_124_is_timeout_with_captured_output_not_a_quality_result(self) -> None:
        fake = FakeRpc(command_result={
            "exitCode": 124,
            "stdout": "timeout diagnostic stdout\n",
            "stderr": "timeout diagnostic stderr\n",
        })
        with self.assertRaises(NativeCheckError) as caught:
            self.fixture.execute(fake)
        error = caught.exception
        self.assertEqual(error.code, "COMMAND_TIMEOUT")
        self.assertEqual(error.captured_result["exitCode"], 124)
        self.assertEqual(error.captured_result["stdout"], "timeout diagnostic stdout\n")
        self.assertEqual(error.captured_result["stderr"], "timeout diagnostic stderr\n")
        self.assertEqual(error.captured_result["native_version"], "0.162.0-alpha.2")
        self.assertEqual(error.captured_result["permission_profile"], "checks")
        self.assertRegex(error.captured_result["profile_hash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("status", error.captured_result)
        self.assertEqual(fake.close_count, 1)

    def test_permission_traceback_is_rejected_but_ordinary_nonzero_result_is_returned(self) -> None:
        denied = FakeRpc(command_result={
            "exitCode": 1,
            "stdout": "partial diagnostic\n",
            "stderr": (
                "Traceback (most recent call last):\n"
                "  File \"fixture_check.py\", line 4, in run\n"
                "PermissionError: [Errno 13] access denied\n"
            ),
        })
        with self.assertRaises(NativeCheckError) as caught:
            self.fixture.execute(denied)
        error = caught.exception
        self.assertEqual(error.code, "CHECK_PERMISSION_DENIED")
        self.assertEqual(error.captured_result["exitCode"], 1)
        self.assertEqual(error.captured_result["stdout"], "partial diagnostic\n")
        self.assertIn("PermissionError: [Errno 13] access denied", error.captured_result["stderr"])
        self.assertEqual(error.captured_result["native_version"], "0.162.0-alpha.2")
        self.assertEqual(error.captured_result["permission_profile"], "checks")
        self.assertRegex(error.captured_result["profile_hash"], r"^[0-9a-f]{64}$")
        self.assertNotIn("status", error.captured_result)
        self.assertEqual(denied.close_count, 1)

        quality_failure = FakeRpc(command_result={
            "exitCode": 7,
            "stdout": "check completed\n",
            "stderr": "assertion failed: expected 2, got 3\n",
        })
        result = Fixture().execute(quality_failure)
        self.assertEqual(result["exitCode"], 7)
        self.assertEqual(result["stdout"], "check completed\n")
        self.assertEqual(result["stderr"], "assertion failed: expected 2, got 3\n")
        self.assertEqual(result["permission_profile"], "checks")
        self.assertEqual(result["native_version"], "0.162.0-alpha.2")
        self.assertRegex(result["profile_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(quality_failure.close_count, 1)


if __name__ == "__main__":
    unittest.main()
