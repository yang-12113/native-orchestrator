"""Fake-Git tests for the read-only FRAME-005 repository materials API.

Each test creates a new candidate tree under .runtime/frame-005-material-tests.
Git metadata is supplied by a fake probe; all candidate files and path checks
use the real filesystem. Process launch is blocked for the full test lifetime.
"""
from __future__ import annotations

import hashlib
import os
import subprocess
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from native_orchestrator import repo_materials


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
TEST_ROOT = RUNTIME / "frame-005-material-tests"
HEAD = "1" * 40
TREE = "2" * 40


class FakeGitProbe:
    """A controllable stand-in for the read-only Git metadata probe."""

    def __init__(self, root: Path) -> None:
        self.result = {"root": str(root.resolve()), "head": HEAD, "tree": TREE, "clean": True}
        self.calls: list[str] = []

    def __call__(self, root) -> dict:
        self.calls.append(str(root))
        return dict(self.result)


class RepoMaterialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        RUNTIME.mkdir(exist_ok=True)
        TEST_ROOT.mkdir(exist_ok=True)
        cls.run_root = TEST_ROOT / ("run-" + uuid.uuid4().hex)
        cls.run_root.mkdir()

    def setUp(self) -> None:
        self.case_root = self.run_root / (self.id().rsplit(".", 1)[-1] + "-" + uuid.uuid4().hex)
        self.case_root.mkdir()
        self.repo_root = self.case_root / "candidate"
        self.repo_root.mkdir()
        # The fake probe supplies Git facts. This marker makes the fixture's
        # repository shape explicit without creating Git metadata or a process.
        (self.repo_root / ".git").mkdir()
        (self.repo_root / "approved.txt").write_text("approved\n", encoding="utf-8")
        (self.repo_root / "private.txt").write_text("not delivered\n", encoding="utf-8")
        self.binding = {
            "project_id": "frame005-project",
            "task_id": "frame005-materials",
            "spec_version": 1,
            "attempt": 1,
            "contract_hash": "a" * 64,
        }
        self.before_read_calls = 0
        self.probe = FakeGitProbe(self.repo_root)

        # The implementation's probe seam is patched to fake metadata. This
        # process tripwire catches any accidental Git/native/model/network CLI.
        self._probe_patch = patch.object(repo_materials, "inspect_git_input", side_effect=self.probe)
        self._probe_patch.start()
        self.addCleanup(self._probe_patch.stop)
        self._popen_patch = patch.object(
            subprocess, "Popen", side_effect=AssertionError("subprocess launch is forbidden in FRAME-005 material tests")
        )
        self._popen_patch.start()
        self.addCleanup(self._popen_patch.stop)
        self._system_patch = patch.object(
            os, "system", side_effect=AssertionError("os.system is forbidden in FRAME-005 material tests")
        )
        self._system_patch.start()
        self.addCleanup(self._system_patch.stop)

    def authority(self) -> bool:
        self.before_read_calls += 1
        return True

    def make_materials(self, paths=("approved.txt",), **kwargs):
        return repo_materials.RepoMaterials(
            str(self.repo_root.resolve()), HEAD, dict(self.binding), list(paths),
            before_read=self.authority, **kwargs,
        )

    def assert_rejected(self, operation, code: str | None = None) -> None:
        with self.assertRaises(repo_materials.MaterialError) as caught:
            operation()
        self.assertIsInstance(caught.exception, ValueError)
        self.assertTrue(getattr(caught.exception, "code", None))
        if code is not None:
            self.assertEqual(caught.exception.code, code)

    def test_valid_candidate_reads_exact_allowlisted_file_and_returns_defensive_records(self) -> None:
        materials = self.make_materials(("approved.txt",))
        # Construction checks Git before and after capturing the complete
        # manifest and approved-file cache.
        self.assertEqual(self.probe.calls, [str(self.repo_root.resolve())] * 2)
        self.assertEqual(materials.records(), [])
        self.assertEqual(self.before_read_calls, 1)

        delivered = materials.read("approved.txt")
        expected_bytes = (self.repo_root / "approved.txt").read_bytes()
        self.assertEqual(delivered["path"], "approved.txt")
        self.assertEqual(delivered["candidate_commit"], HEAD)
        self.assertRegex(delivered["input_hash"], r"^[0-9a-f]{64}$")
        self.assertEqual(delivered["file_sha256"], hashlib.sha256(expected_bytes).hexdigest())
        self.assertEqual(delivered["file_bytes"], len(expected_bytes))
        self.assertEqual(delivered["offset"], 0)
        self.assertIsNone(delivered["next_offset"])
        self.assertEqual(delivered["excerpt"], expected_bytes.decode("utf-8"))
        self.assertEqual(self.before_read_calls, 2)

        records = materials.records()
        self.assertEqual(len(records), 1)
        self.assertEqual(set(records[0]), {"path", "file_sha256", "offset", "next_offset", "returned_bytes"})
        self.assertEqual(records[0], {
            "path": "approved.txt",
            "file_sha256": hashlib.sha256(expected_bytes).hexdigest(),
            "offset": 0,
            "next_offset": None,
            "returned_bytes": len(expected_bytes),
        })
        # Neither caller-owned response object can rewrite the stored receipt.
        delivered["excerpt"] = "tampered"
        records[0]["path"] = "private.txt"
        records.clear()
        self.assertEqual(materials.records()[0]["path"], "approved.txt")
        self.assertEqual(materials.records()[0]["returned_bytes"], len(expected_bytes))
        self.assertEqual(materials.records()[0]["file_sha256"], hashlib.sha256(expected_bytes).hexdigest())
        binding_copy = materials.binding
        binding_copy["task_id"] = "tampered"
        self.assertEqual(materials.binding["task_id"], self.binding["task_id"])

    def test_unread_files_and_eof_do_not_create_phantom_receipts(self) -> None:
        materials = self.make_materials(("approved.txt",))
        self.assertEqual(materials.records(), [])
        completed = materials.read("approved.txt")
        self.assertIsNone(completed["next_offset"])
        self.assertEqual(len(materials.records()), 1)
        self.assertNotIn("private.txt", [record["path"] for record in materials.records()])
        # An EOF request can return no text, but cannot claim another byte
        # delivery in the audit records.
        materials.read("approved.txt", offset=len(completed["excerpt"]))
        self.assertEqual(len(materials.records()), 1)

    def test_candidate_commit_and_clean_worktree_are_required(self) -> None:
        self.assert_rejected(lambda: repo_materials.RepoMaterials(
            str(self.repo_root.resolve()), "f" * 40, dict(self.binding), ["approved.txt"],
            before_read=self.authority,
        ), "INPUT_DRIFT")
        self.assertEqual(len(self.probe.calls), 1)
        self.probe.result["clean"] = False
        self.assert_rejected(lambda: self.make_materials(), "INPUT_DRIFT")

    def test_binding_schema_and_types_are_checked(self) -> None:
        invalid_bindings = []
        missing = dict(self.binding)
        del missing["attempt"]
        invalid_bindings.append(missing)
        invalid_bindings.append(dict(self.binding, unexpected="value"))
        invalid_bindings.append(dict(self.binding, spec_version=True))
        invalid_bindings.append(dict(self.binding, project_id=""))
        invalid_bindings.append(dict(self.binding, contract_hash="not-a-sha256"))
        for binding in invalid_bindings:
            with self.subTest(binding=binding):
                self.assert_rejected(lambda value=binding: repo_materials.RepoMaterials(
                    str(self.repo_root.resolve()), HEAD, value, ["approved.txt"], before_read=self.authority,
                ), "INVALID_BINDING")

    def test_protected_control_credential_and_configuration_paths_are_rejected(self) -> None:
        protected = (
            "AGENTS.md", "module/AGENTS.md", "TASKS/FRAME-005.md",
            "credentials.yml", "secrets.txt", "module/client_secret.json",
            ".env", "auth.json", "config.live.json", ".git/config",
        )
        for path in protected:
            with self.subTest(path=path):
                target = self.repo_root / Path(path)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text("fixture only\n", encoding="utf-8")
                self.assert_rejected(lambda value=path: self.make_materials((value,)), "PROTECTED_PATH")

    def test_credentials_named_ordinary_source_file_remains_readable(self) -> None:
        source_path = "module/credentials_parser.py"
        source = "def parse_credentials(raw):\n    return raw.strip()\n"
        target = self.repo_root / Path(source_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(source.encode("utf-8"))

        materials = self.make_materials((source_path,))
        delivered = materials.read(source_path)
        self.assertEqual(delivered["excerpt"], source)
        self.assertEqual(delivered["path"], source_path)
        self.assertEqual(materials.records()[0]["path"], source_path)

    def test_allowed_paths_must_be_exact_safe_relative_paths(self) -> None:
        unsafe = (
            "../approved.txt", "dir/../approved.txt", ".\\approved.txt",
            "dir\\approved.txt", str(self.repo_root / "approved.txt"),
            "C:/approved.txt", "./approved.txt", "approved.txt/../private.txt",
        )
        for path in unsafe:
            with self.subTest(path=path):
                self.assert_rejected(lambda value=path: self.make_materials((value,)), "INVALID_PATH")

        materials = self.make_materials(("approved.txt",))
        for path in ("private.txt", "approved.txt/", "./approved.txt", "approved.txt "):
            with self.subTest(read_path=path):
                self.assert_rejected(lambda value=path: materials.read(value), "PATH_NOT_ALLOWED")
        self.assertEqual(materials.records(), [])

    def test_unknown_read_parameters_are_rejected_without_receipt(self) -> None:
        materials = self.make_materials()
        with self.assertRaises(TypeError):
            materials.read("approved.txt", unexpected=True)
        self.assertEqual(materials.records(), [])
        self.assertEqual(self.before_read_calls, 1)

    def test_unicode_offsets_and_2048_byte_limit_preserve_complete_codepoints(self) -> None:
        payload = "x" * 2044 + "🐟" + "end"
        (self.repo_root / "boundary.txt").write_text(payload, encoding="utf-8")
        materials = self.make_materials(("boundary.txt",))
        first = materials.read("boundary.txt")
        self.assertEqual(len(first["excerpt"].encode("utf-8")), 2048)
        self.assertEqual(first["excerpt"], "x" * 2044 + "🐟")
        self.assertEqual(first["next_offset"], 2045)
        second = materials.read("boundary.txt", offset=first["next_offset"])
        self.assertEqual(second["offset"], 2045)
        self.assertEqual(second["excerpt"], "end")
        self.assertIsNone(second["next_offset"])
        self.assertEqual([row["returned_bytes"] for row in materials.records()], [2048, 3])

    def test_invalid_utf8_is_rejected_without_delivering_or_receipting_bytes(self) -> None:
        (self.repo_root / "invalid.txt").write_bytes(b"valid-prefix\xff")
        try:
            materials = self.make_materials(("invalid.txt",))
        except repo_materials.MaterialError as error:
            self.assertEqual(error.code, "INVALID_UTF8")
            return
        self.assert_rejected(lambda: materials.read("invalid.txt"), "INVALID_UTF8")
        self.assertEqual(materials.records(), [])

    def test_type_validation_and_file_excerpt_total_and_call_limits(self) -> None:
        for offset in (-1, True, 1.5, "0", None):
            materials = self.make_materials()
            with self.subTest(offset=offset):
                self.assert_rejected(lambda value=offset: materials.read("approved.txt", offset=value), "INVALID_OFFSET")
                self.assertEqual(materials.records(), [])
        for option in ("max_file_bytes", "max_excerpt_bytes", "max_total_bytes", "max_calls"):
            for value in (-1, True, 1.5, None):
                with self.subTest(option=option, value=value):
                    kwargs = {option: value}
                    self.assert_rejected(lambda arguments=kwargs: self.make_materials(**arguments), "INVALID_BUDGET")

        (self.repo_root / "oversize.txt").write_text("0123456789", encoding="utf-8")
        self.assert_rejected(lambda: self.make_materials(("oversize.txt",), max_file_bytes=5), "FILE_TOO_LARGE")

        (self.repo_root / "budget.txt").write_text("abcdefgh", encoding="utf-8")
        limited = self.make_materials(("budget.txt",), max_excerpt_bytes=3, max_total_bytes=8, max_calls=2)
        first = limited.read("budget.txt")
        second = limited.read("budget.txt")
        self.assertEqual(len(first["excerpt"].encode("utf-8")), 3)
        self.assertEqual(len(second["excerpt"].encode("utf-8")), 3)
        self.assert_rejected(lambda: limited.read("budget.txt"), "READ_BUDGET_EXHAUSTED")
        self.assertEqual(len(limited.records()), 2)

        repeated = self.make_materials(("budget.txt",), max_excerpt_bytes=3, max_total_bytes=5, max_calls=10)
        first = repeated.read("budget.txt")
        second = repeated.read("budget.txt")
        self.assertEqual(len(first["excerpt"].encode("utf-8")), 3)
        self.assertEqual(len(second["excerpt"].encode("utf-8")), 2)
        self.assert_rejected(lambda: repeated.read("budget.txt"), "READ_BUDGET_EXHAUSTED")
        self.assertEqual(len(repeated.records()), 2)

    def test_before_read_authority_is_required_for_each_delivery(self) -> None:
        callback_count = 0

        def authority_once():
            nonlocal callback_count
            callback_count += 1
            return callback_count == 1

        denied = repo_materials.RepoMaterials(
            str(self.repo_root.resolve()), HEAD, dict(self.binding), ["approved.txt"],
            before_read=authority_once,
        )
        self.assert_rejected(lambda: denied.read("approved.txt"), "AUTHORITY_REQUIRED")
        self.assertEqual(denied.records(), [])

        def raising_authority():
            raise RuntimeError("stale authority")

        self.assert_rejected(lambda: repo_materials.RepoMaterials(
            str(self.repo_root.resolve()), HEAD, dict(self.binding), ["approved.txt"],
            before_read=raising_authority,
        ), "AUTHORITY_REQUIRED")

    def test_assert_unchanged_detects_unapproved_file_and_git_drift(self) -> None:
        materials = self.make_materials(("approved.txt",))
        materials.assert_unchanged()
        (self.repo_root / "private.txt").write_text("changed outside allowlist\n", encoding="utf-8")
        self.assert_rejected(materials.assert_unchanged, "INPUT_DRIFT")

        (self.repo_root / "private.txt").write_text("not delivered\n", encoding="utf-8")
        materials = self.make_materials(("approved.txt",))
        self.probe.result["head"] = "3" * 40
        self.assert_rejected(materials.assert_unchanged, "INPUT_DRIFT")

        self.probe.result["head"] = HEAD
        materials = self.make_materials(("approved.txt",))
        self.probe.result["clean"] = False
        self.assert_rejected(materials.assert_unchanged, "INPUT_DRIFT")

    def test_read_refuses_input_drift_since_materials_were_constructed(self) -> None:
        materials = self.make_materials(("approved.txt",))
        (self.repo_root / "private.txt").write_text("changed outside allowlist\n", encoding="utf-8")
        self.assert_rejected(lambda: materials.read("approved.txt"), "INPUT_DRIFT")
        self.assertEqual(materials.records(), [])

    def test_repository_symlink_is_rejected_or_skipped_only_for_windows_privilege(self) -> None:
        linked = self.case_root / "linked-candidate"
        try:
            linked.symlink_to(self.repo_root, target_is_directory=True)
        except OSError as error:
            if os.name == "nt" and getattr(error, "winerror", None) == 1314:
                self.skipTest("Windows symlink creation requires a privilege unavailable to this test account (WinError 1314)")
            raise
        self.assert_rejected(lambda: repo_materials.RepoMaterials(
            str(linked), HEAD, dict(self.binding), ["approved.txt"], before_read=self.authority,
        ), "LINKED_PATH")


if __name__ == "__main__":
    unittest.main(verbosity=2)
