"""Windows path-boundary checks using real directory junctions.

Run with ``python -B -m unittest -v test_windows_path_boundaries``. Each
invocation keeps its case directory and PowerShell log under
``.runtime/frame-004-windows-links`` so link evidence is never recursively
removed. File symlinks are deliberately outside this suite.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from native_orchestrator import check_runner
from native_orchestrator import execution_contract
from native_orchestrator import native_check_exec
from native_orchestrator import repo_workspace
from native_orchestrator.check_runner import CheckError, input_manifest, run_check
from native_orchestrator.execution_contract import ContractError
from native_orchestrator.native_check_exec import NativeCheckError, WINDOWS_LAUNCH_ENV_KEYS, execute_native
from native_orchestrator.repo_workspace import WorkspaceError


WORKTREE = Path(__file__).absolute().parents[1]
TEST_ROOT = WORKTREE / ".runtime" / "frame-004-windows-links"
Powershell = Path(os.environ.get("SYSTEMROOT", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
REAL_GIT_OPT_IN = "FRAME003_ENABLE_REAL_GIT_TESTS"
FIXED_JUNCTION_SCRIPT = "; ".join((
    "[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "$OutputEncoding = [System.Text.UTF8Encoding]::new($false)",
    "$ErrorActionPreference = 'Stop'",
    "$CaseRoot = [Environment]::GetEnvironmentVariable('FRAME004_CASE_ROOT')",
    "$LinkPath = [Environment]::GetEnvironmentVariable('FRAME004_LINK_PATH')",
    "$TargetPath = [Environment]::GetEnvironmentVariable('FRAME004_TARGET_PATH')",
    "if (-not $CaseRoot -or -not $LinkPath -or -not $TargetPath -or -not [IO.Path]::IsPathRooted($CaseRoot)) { throw 'Three absolute fixture paths are required.' }",
    "$root = [IO.Path]::GetFullPath($CaseRoot).TrimEnd([char[]]@('\\', '/'))",
    "$link = [IO.Path]::GetFullPath($LinkPath)",
    "$target = [IO.Path]::GetFullPath($TargetPath)",
    "$prefix = $root + [IO.Path]::DirectorySeparatorChar",
    "foreach ($candidate in @($link, $target)) { if (-not [IO.Path]::IsPathRooted($candidate) -or -not $candidate.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw 'Junction paths must be absolute descendants of this test case.' } }",
    "if (-not (Test-Path -LiteralPath $target -PathType Container)) { throw 'Junction target must be an existing directory.' }",
    "if (Test-Path -LiteralPath $link) { throw 'Junction destination is already occupied.' }",
    "$null = New-Item -ItemType Junction -Path $link -Target $target",
    "$item = Get-Item -LiteralPath $link -Force",
    "if (($item.Attributes -band [IO.FileAttributes]::ReparsePoint) -eq 0 -or $item.LinkType -ne 'Junction') { throw 'The created path is not a directory junction.' }",
    "[pscustomobject]@{ LinkType = $item.LinkType; Target = [string]$item.Target; Attributes = [string]$item.Attributes } | ConvertTo-Json -Compress",
))

CHECK_ID = "fixture_syntax"
FIXED_GIT = {"head": "a" * 40, "tree": "b" * 40, "clean": True}
CATALOG = {
    CHECK_ID: {
        "argv": [sys.executable, "-B", "-c", "pass"],
        "timeout_seconds": 5,
        "output_bytes_cap": 2048,
        "write_scope": "scratch",
        "network": "disabled",
        "shell": False,
        "verification": "VERIFIED",
        "evidence_sha256": "d" * 64,
    }
}


class Case:
    """Persistent, uniquely named test fixture; cleanup is intentionally absent."""

    def __init__(self) -> None:
        TEST_ROOT.mkdir(parents=True, exist_ok=True)
        self.root = TEST_ROOT / f"case-{uuid.uuid4()}"
        self.root.mkdir()
        self.script = self.root / "create-junction.ps1"
        self.script.write_text(FIXED_JUNCTION_SCRIPT, encoding="utf-8")

    def directory(self, relative: str) -> Path:
        path = self.root / relative
        path.mkdir(parents=True, exist_ok=False)
        return path

    def create_junction(self, relative_link: str, relative_target: str) -> Path:
        link = self.root / relative_link
        target = self.root / relative_target
        launch_env = {key: os.environ[key] for key in WINDOWS_LAUNCH_ENV_KEYS
                      if os.environ.get(key)}
        launch_env.update({
            "FRAME004_CASE_ROOT": str(self.root),
            "FRAME004_LINK_PATH": str(link),
            "FRAME004_TARGET_PATH": str(target),
        })
        command = [str(Powershell), "-NoProfile", "-NonInteractive", "-Command", "-"]
        result = subprocess.run(
            command, input=FIXED_JUNCTION_SCRIPT + "\n", capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=30, check=False,
            env=launch_env, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        attempt = uuid.uuid4().hex
        (self.root / f"junction-{attempt}.stdout.txt").write_text(result.stdout, encoding="utf-8")
        (self.root / f"junction-{attempt}.stderr.txt").write_text(result.stderr, encoding="utf-8")
        (self.root / f"junction-{attempt}.result.json").write_text(
            json.dumps({"exit_code": result.returncode, "link": str(link), "target": str(target),
                        "command": command, "env_keys": sorted(launch_env)},
                       ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        if result.returncode != 0:
            raise AssertionError(
                f"Junction creation failed; preserved case={self.root}; "
                f"exit={result.returncode}; stdout={result.stdout!r}; stderr={result.stderr!r}"
            )
        try:
            proof = json.loads(result.stdout.strip())
        except (json.JSONDecodeError, AttributeError) as error:
            raise AssertionError(
                f"PowerShell returned no junction proof; preserved case={self.root}; "
                f"stdout={result.stdout!r}; stderr={result.stderr!r}"
            ) from error
        self.assert_real_junction(link, proof, target)
        return link

    def assert_real_junction(self, link: Path, proof: dict, target: Path) -> None:
        info = os.lstat(link)
        attrs = getattr(info, "st_file_attributes", 0)
        isjunction = getattr(link, "is_junction", None)
        self_proof = bool(callable(isjunction) and isjunction())
        if not (stat.S_ISDIR(info.st_mode) and attrs & 0x400 and self_proof):
            raise AssertionError(f"Not an OS-reported directory junction: {link}; case={self.root}")
        if proof.get("LinkType") != "Junction" or "ReparsePoint" not in proof.get("Attributes", ""):
            raise AssertionError(f"PowerShell did not confirm junction type: {proof}; case={self.root}")
        if Path(proof.get("Target", "")).resolve() != target.resolve():
            raise AssertionError(f"PowerShell junction target mismatch: {proof}; case={self.root}")


class WindowsJunctionBoundaryTests(unittest.TestCase):
    def setUp(self) -> None:
        if os.name != "nt":
            self.skipTest("This suite requires Windows directory junctions.")
        if not Powershell.is_file():
            self.fail(f"Fixed Windows PowerShell executable unavailable: {Powershell}")
        self.case = Case()

    def _contract_link_rejected(self, path: Path) -> None:
        with self.assertRaises(ContractError) as caught:
            execution_contract.absolute_root(str(path), "repo_root")
        self.assertEqual(caught.exception.code, "LINKED_PATH")

    def test_preflight_rejects_junction_at_repo_root_and_parent_component(self) -> None:
        target = self.case.directory("repo-target")
        root_link = self.case.create_junction("repo-root-link", "repo-target")
        self._contract_link_rejected(root_link)

        parent_target = self.case.directory("repo-parent-target")
        (parent_target / "repo").mkdir()
        parent_link = self.case.create_junction("repo-parent-link", "repo-parent-target")
        self._contract_link_rejected(parent_link / "repo")

    def test_workspace_source_junction_rejected_before_git_or_filesystem_mutation(self) -> None:
        source_target = self.case.directory("source-target")
        marker = source_target / "marker.txt"
        marker.write_text("unchanged\n", encoding="utf-8")
        source_link = self.case.create_junction("source-link", "source-target")
        data = self.case.directory("data")
        unexpected_calls = []

        def before_mutation() -> bool:
            return True

        def unexpected(name):
            def fail(*_args, **_kwargs):
                unexpected_calls.append(name)
                raise AssertionError(f"{name} must not run for a linked source")
            return fail

        with (patch.object(repo_workspace, "_inspect_repository", side_effect=unexpected("git_inspect")),
              patch.object(repo_workspace, "_git", side_effect=unexpected("git")),
              patch.object(repo_workspace, "_ensure_directory", side_effect=unexpected("ensure_directory")),
              patch.object(repo_workspace, "_create_record", side_effect=unexpected("create_record"))):
            with self.assertRaises(WorkspaceError) as caught:
                repo_workspace.create_workspace(
                    source_link, "a" * 40, data,
                    {"project_id": "fixture", "task_id": "FRAME004", "spec_version": 1,
                     "attempt": 1, "contract_hash": "c" * 64},
                    before_mutation=before_mutation,
                )
        self.assertEqual(caught.exception.code, "LINKED_PATH")
        self.assertEqual(unexpected_calls, [])
        self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged\n")
        self.assertEqual(list(data.iterdir()), [])

    def test_workspace_data_root_parent_junction_rejected_before_git_or_filesystem_mutation(self) -> None:
        source = self.case.directory("plain-source")
        data_target = self.case.directory("data-parent-target")
        marker = data_target / "marker.txt"
        marker.write_text("unchanged\n", encoding="utf-8")
        before_entries = sorted((path.name, path.is_dir(), path.read_bytes() if path.is_file() else None)
                                for path in data_target.iterdir())
        data_parent_link = self.case.create_junction("data-parent-link", "data-parent-target")
        data_root = data_parent_link / "data"
        unexpected_calls = []

        def before_mutation() -> bool:
            return True

        def unexpected(name):
            def fail(*_args, **_kwargs):
                unexpected_calls.append(name)
                raise AssertionError(f"{name} must not run for a linked data root")
            return fail

        with (patch.object(repo_workspace, "_inspect_repository", side_effect=unexpected("git_inspect")),
              patch.object(repo_workspace, "_git", side_effect=unexpected("git")),
              patch.object(repo_workspace, "_ensure_directory", side_effect=unexpected("ensure_directory")),
              patch.object(repo_workspace, "_create_record", side_effect=unexpected("create_record"))):
            with self.assertRaises(WorkspaceError) as caught:
                repo_workspace.create_workspace(
                    source, "a" * 40, data_root,
                    {"project_id": "fixture", "task_id": "FRAME004", "spec_version": 1,
                     "attempt": 1, "contract_hash": "c" * 64},
                    before_mutation=before_mutation,
                )
        self.assertEqual(caught.exception.code, "LINKED_PATH")
        self.assertEqual(unexpected_calls, [])
        self.assertFalse(data_root.exists())
        after_entries = sorted((path.name, path.is_dir(), path.read_bytes() if path.is_file() else None)
                               for path in data_target.iterdir())
        self.assertEqual(after_entries, before_entries)

    def _runner_context(self, snapshot: Path) -> dict:
        scratch = self.case.directory(f"scratch-{uuid.uuid4().hex}")
        control = self.case.directory(f"control-{uuid.uuid4().hex}")
        evidence = self.case.root / f"evidence-{uuid.uuid4().hex}"
        return {
            "binding": {"project_id": "fixture", "task_id": "FRAME004", "spec_version": 1,
                        "attempt": 1, "contract_hash": "c" * 64},
            "candidate_commit": "a" * 40,
            "snapshot_root": str(snapshot), "scratch_root": str(scratch),
            "control_root": str(control), "evidence_root": str(evidence),
        }

    def _assert_runner_rejects_before_fake_executor(self, snapshot: Path) -> None:
        calls = []

        def fake_executor(*_args, **_kwargs):
            calls.append(True)
            raise AssertionError("fake executor must not be called for linked snapshot roots")

        with patch.object(check_runner, "inspect_git_input", side_effect=AssertionError("Git probe must not run")):
            with self.assertRaises(CheckError) as caught:
                run_check(CHECK_ID, CATALOG, self._runner_context(snapshot), before_dispatch=lambda: True,
                          native_executor=fake_executor)
        self.assertEqual(caught.exception.code, "LINKED_PATH")
        self.assertEqual(calls, [])

    def test_runner_rejects_junction_snapshot_root_and_parent_before_fake_executor(self) -> None:
        snapshot_target = self.case.directory("snapshot-target")
        root_link = self.case.create_junction("snapshot-root-link", "snapshot-target")
        self._assert_runner_rejects_before_fake_executor(root_link)

        parent_target = self.case.directory("snapshot-parent-target")
        (parent_target / "snapshot").mkdir()
        parent_link = self.case.create_junction("snapshot-parent-link", "snapshot-parent-target")
        self._assert_runner_rejects_before_fake_executor(parent_link / "snapshot")

    def test_native_helper_rejects_readonly_cwd_junction_before_rpc_construction(self) -> None:
        self.case.directory("native-input-target")
        cwd_link = self.case.create_junction("native-cwd-link", "native-input-target")
        scratch = self.case.directory("native-scratch")
        control = self.case.directory("native-control")
        evidence = self.case.directory("native-evidence")
        constructed = []

        def rpc_constructor(*_args, **_kwargs):
            constructed.append(True)
            raise AssertionError("RPC must not be constructed for a linked cwd")

        with patch.object(native_check_exec, "Rpc", side_effect=rpc_constructor):
            with self.assertRaises(NativeCheckError) as caught:
                execute_native(
                    [sys.executable, "-B", "-c", "pass"], cwd=cwd_link, scratch_root=scratch,
                    readonly_roots=[cwd_link], denied_roots=[control, evidence],
                    run_root=evidence / "native-run", timeout_ms=5000, output_bytes_cap=2048,
                    before_dispatch=lambda: True,
                )
        self.assertEqual(caught.exception.code, "SYMLINK_PATH")
        self.assertEqual(constructed, [])
        self.assertFalse((evidence / "native-run").exists())

    def test_input_manifest_rejects_nested_directory_junction(self) -> None:
        snapshot = self.case.directory("manifest-snapshot")
        self.case.directory("manifest-target")
        (self.case.root / "manifest-target" / "payload.txt").write_text("fixture\n", encoding="utf-8")
        self.case.create_junction("manifest-snapshot/nested-link", "manifest-target")
        with self.assertRaises(CheckError) as caught:
            input_manifest(snapshot)
        self.assertEqual(caught.exception.code, "LINKED_PATH")

    @unittest.skipUnless(os.environ.get(REAL_GIT_OPT_IN) == "1",
                         "local real-Git input fixture requires explicit FRAME-003 authorization")
    def test_committed_git_symlink_mode_is_rejected_without_source_or_data_changes(self) -> None:
        source = self.case.directory("git-source")
        data = self.case.directory("git-data")
        hooks = self.case.directory("git-hooks-empty")
        template = self.case.directory("git-template-empty")
        executable = shutil.which("git")
        self.assertIsNotNone(executable, "Git is required for the opt-in local fixture")
        self.git_log_sequence = 0

        env = {key: os.environ[key] for key in WINDOWS_LAUNCH_ENV_KEYS if os.environ.get(key)}
        env.update({"TEMP": str(self.case.root), "TMP": str(self.case.root),
                    "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull,
                    "GIT_OPTIONAL_LOCKS": "0", "GIT_TERMINAL_PROMPT": "0"})
        flags = [
            "-c", "protocol.allow=never",
            "-c", "core.hooksPath=" + str(hooks),
            "-c", "core.fsmonitor=false",
            "-c", "core.autocrlf=false",
            "-c", "core.symlinks=false",
            "-c", "commit.gpgsign=false",
            "-c", "tag.gpgsign=false",
            "-c", "maintenance.auto=false",
            "-c", "gc.auto=0",
        ]

        def git(args: list[str], *, cwd: Path, input_bytes: bytes | None = None,
                allow_codes: tuple[int, ...] = (0,)) -> bytes:
            self.git_log_sequence += 1
            argv = [str(executable), *flags, *args]
            try:
                result = subprocess.run(
                    argv, cwd=cwd, env=env, input=input_bytes, stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE, shell=False, timeout=30, check=False,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                payload = {
                    "argv": argv,
                    "cwd": str(cwd),
                    "exit_code": result.returncode,
                    "stdin_utf8": None if input_bytes is None else input_bytes.decode("utf-8", "replace"),
                    "stdout_utf8": result.stdout.decode("utf-8", "replace"),
                    "stderr_utf8": result.stderr.decode("utf-8", "replace"),
                }
                (self.case.root / f"git-command-{self.git_log_sequence:02d}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            except BaseException as error:
                (self.case.root / f"git-command-{self.git_log_sequence:02d}.json").write_text(
                    json.dumps({"argv": argv, "cwd": str(cwd), "error": repr(error)},
                               ensure_ascii=False, indent=2), encoding="utf-8")
                raise
            if result.returncode not in allow_codes:
                self.fail(f"fixture Git command failed; case={self.case.root}; argv={argv!r}; "
                          f"stderr={result.stderr.decode('utf-8', 'replace')!r}")
            return result.stdout

        # All Git work is local to this new case. The empty template and hooks
        # path, isolated config, disabled protocol, filters absent by inspection,
        # and per-command identity prevent ambient Git behavior.
        git(["-c", "init.templateDir=" + str(template), "init", "-q", str(source)], cwd=self.case.root)
        link_target = b"link-target"
        blob = git(["hash-object", "-w", "--stdin"], cwd=source, input_bytes=link_target).decode(
            "ascii", "strict").strip()
        self.assertRegex(blob, r"\A(?:[0-9a-f]{40}|[0-9a-f]{64})\Z")
        git(["update-index", "--add", "--cacheinfo", "120000," + blob + ",linked-input"], cwd=source)
        link_file = source / "linked-input"
        link_file.write_bytes(link_target)
        git(["-c", "user.name=FRAME-004 Fixture", "-c", "user.email=frame004@example.invalid",
             "commit", "--no-gpg-sign", "--no-verify", "-m", "synthetic symlink-mode input"], cwd=source)
        head = git(["rev-parse", "--verify", "HEAD^{commit}"], cwd=source).decode("ascii", "strict").strip()
        tree_entries = git(["ls-tree", "-r", "-z", "--full-tree", head], cwd=source)
        parsed = [item.split(b"\t", 1) for item in tree_entries.split(b"\0") if item]
        link_entries = [(meta, name) for meta, name in parsed if name == b"linked-input"]
        self.assertEqual(len(link_entries), 1)
        self.assertEqual(link_entries[0][0].split(b" ", 2)[:2], [b"120000", b"blob"])
        self.assertFalse(link_file.is_symlink(), "core.symlinks=false fixture is a regular text file")
        self.assertEqual(git(["status", "--porcelain=v1", "--untracked-files=all"], cwd=source), b"")
        self.assertEqual(git(["config", "--includes", "--get-regexp", r"^filter\."],
                             cwd=source, allow_codes=(0, 1)), b"")
        self.assertEqual(git(["remote", "-v"], cwd=source), b"")

        binding = {"project_id": "fixture", "task_id": "FRAME004_SYMLINK", "spec_version": 1,
                   "attempt": 1, "contract_hash": "e" * 64}
        descriptor = repo_workspace._descriptor(source.resolve(), head, data.resolve(), binding)
        candidate = Path(descriptor["workspace_root"])
        source_before = self._tree_snapshot(source)
        data_before = self._tree_snapshot(data)
        self.assertFalse(candidate.exists())

        original_subprocess_run = subprocess.run

        def logged_repository_git_run(*args, **kwargs):
            self.git_log_sequence += 1
            argv = args[0] if args else kwargs.get("args")
            try:
                result = original_subprocess_run(*args, **kwargs)
                payload = {
                    "argv": argv,
                    "cwd": str(kwargs.get("cwd", "")),
                    "exit_code": result.returncode,
                    "stdout_utf8": result.stdout.decode("utf-8", "replace")
                    if isinstance(result.stdout, bytes) else result.stdout,
                    "stderr_utf8": result.stderr.decode("utf-8", "replace")
                    if isinstance(result.stderr, bytes) else result.stderr,
                }
                (self.case.root / f"git-command-{self.git_log_sequence:02d}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
                return result
            except BaseException as error:
                (self.case.root / f"git-command-{self.git_log_sequence:02d}.json").write_text(
                    json.dumps({"argv": argv, "cwd": str(kwargs.get("cwd", "")),
                                "error": repr(error)}, ensure_ascii=False, indent=2), encoding="utf-8")
                raise

        with patch.object(subprocess, "run", side_effect=logged_repository_git_run):
            with self.assertRaises(WorkspaceError) as caught:
                repo_workspace.create_workspace(source, head, data, binding, before_mutation=lambda: True)
        self.assertEqual(caught.exception.code, "UNSUPPORTED_GIT_ENTRY", str(caught.exception))
        self.assertEqual(self._tree_snapshot(source), source_before)
        self.assertEqual(self._tree_snapshot(data), data_before)
        self.assertFalse(candidate.exists())

    @staticmethod
    def _tree_snapshot(root: Path) -> dict[str, tuple]:
        result = {}
        for directory, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
            current = Path(directory)
            for name in list(dirnames):
                path = current / name
                if path.is_symlink():
                    raise AssertionError(f"Unexpected OS link in Git fixture: {path}")
                result[path.relative_to(root).as_posix()] = ("directory", path.lstat().st_mode)
            for name in filenames:
                path = current / name
                if path.is_symlink():
                    raise AssertionError(f"Unexpected OS link in Git fixture: {path}")
                result[path.relative_to(root).as_posix()] = ("file", path.lstat().st_mode, path.read_bytes())
        return result


if __name__ == "__main__":
    unittest.main(verbosity=2)
