"""Isolated real-Git tests for FRAME-003 repository workspaces.

The suite is intentionally opt-in because it creates linked worktrees and Git
metadata. Every test owns a unique fixture below .runtime/frame-003-test-* and
keeps that fixture as evidence. No existing workspace is reused or cleaned.
"""
import contextlib
import hashlib
import json
import os
import subprocess
import unittest
import uuid
from pathlib import Path

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from native_orchestrator import repo_workspace


ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / ".runtime"
REAL_GIT_OPT_IN = "FRAME003_ENABLE_REAL_GIT_TESTS"
SAFE_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
}


@contextlib.contextmanager
def clean_git_environment():
    """Remove inherited Git selectors/config injection for one operation."""
    saved = {key: value for key, value in os.environ.items()
             if key.upper().startswith("GIT_")}
    for key in list(os.environ):
        if key.upper().startswith("GIT_"):
            os.environ.pop(key, None)
    os.environ.update(SAFE_GIT_ENV)
    try:
        yield
    finally:
        for key in list(os.environ):
            if key.upper().startswith("GIT_"):
                os.environ.pop(key, None)
        os.environ.update(saved)


def git_environment():
    env = {key: value for key, value in os.environ.items()
           if not key.upper().startswith("GIT_")}
    env.update(SAFE_GIT_ENV)
    return env


def tree_snapshot(root):
    """Return user-visible tree bytes without reading Git's own metadata."""
    root = Path(root)
    snapshot = {}
    if not root.exists():
        return snapshot
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        current = Path(directory)
        dirnames[:] = [name for name in dirnames
                       if not (current == root and name == ".git")]
        for name in list(dirnames):
            candidate = current / name
            if candidate.is_symlink():
                snapshot[candidate.relative_to(root).as_posix()] = (
                    "symlink", os.readlink(candidate))
                dirnames.remove(name)
        for name in filenames:
            candidate = current / name
            relative = candidate.relative_to(root).as_posix()
            if candidate.is_symlink():
                snapshot[relative] = ("symlink", os.readlink(candidate))
            elif candidate.is_file():
                snapshot[relative] = ("file", candidate.read_bytes())
    return snapshot


def sha256(data):
    return hashlib.sha256(data).hexdigest()


@unittest.skipUnless(os.environ.get(REAL_GIT_OPT_IN) == "1",
                     "real Git mutation tests require explicit FRAME-003 authorization")
class RepoWorkspaceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        runtime = RUNTIME.resolve()
        if runtime != RUNTIME or not runtime.is_dir():
            raise RuntimeError("expected existing repository .runtime directory")
        cls.run_root = runtime / ("frame-003-test-" + uuid.uuid4().hex)
        if cls.run_root.exists() or cls.run_root.parent != runtime:
            raise RuntimeError("refusing to reuse an existing or out-of-scope fixture path")
        cls.run_root.mkdir()
        cls.case_counter = 0
        cls.case_map = {}

    def setUp(self):
        type(self).case_counter += 1
        self.case_id = "c%02d-%s" % (type(self).case_counter, uuid.uuid4().hex[:6])
        self.case_name = self.id().rsplit(".", 1)[-1]
        self.case_root = self.run_root / self.case_id
        self.case_root.mkdir()
        type(self).case_map[self.case_id] = self.case_name
        (self.run_root / "case-map.json").write_text(
            json.dumps(type(self).case_map, ensure_ascii=False, indent=2), encoding="utf-8")
        self.source = self.case_root / "source"
        self.data = self.case_root / "data"
        self.source.mkdir()
        self.data.mkdir()
        self.safe_hooks = self.case_root / "safe-hooks"
        self.safe_hooks.mkdir()
        self.binding = {
            "project_id": "project003",
            "task_id": "task003",
            "spec_version": 3,
            "attempt": 1,
            "contract_hash": "a" * 64,
        }
        self._init_source_repo()
        self.descriptor = None
        self.workspace_root = None

    def _git(self, *args, cwd=None, check=True, input_text=None):
        command = [
            "git", "-c", "protocol.allow=never",
            "-c", "core.hooksPath=" + str(self.safe_hooks),
            "-c", "core.autocrlf=false",
            "-c", "commit.gpgsign=false",
            *map(str, args),
        ]
        result = subprocess.run(
            command, cwd=cwd or self.source, env=git_environment(),
            input=input_text, text=True, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, check=False,
        )
        if check and result.returncode:
            self.fail("fixture Git command failed: " + " ".join(command) +
                      "\n" + result.stderr[-2000:])
        return result

    def _init_source_repo(self, gitattributes=None):
        (self.source / "README.md").write_bytes(b"baseline\r\nsource bytes\n")
        (self.source / "nested").mkdir()
        (self.source / "nested" / "original.txt").write_bytes(b"nested baseline\n")
        (self.source / ".gitignore").write_bytes(b"ignored.txt\n")
        if gitattributes is not None:
            (self.source / ".gitattributes").write_text(gitattributes, encoding="utf-8")
        self._git("init", "-q", cwd=self.source)
        self._git("config", "user.name", "FRAME-003 Synthetic", cwd=self.source)
        self._git("config", "user.email", "frame003@example.invalid", cwd=self.source)
        self._git("add", "-A", cwd=self.source)
        self._git("commit", "--no-gpg-sign", "-m", "synthetic clean baseline", cwd=self.source)
        self.base_commit = self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip()
        self.assertEqual(self._git("status", "--porcelain", cwd=self.source).stdout, "")

    def _create(self, *, gate=None, binding=None, source=None, data=None, base=None):
        gate = gate or (lambda: True)
        with clean_git_environment():
            descriptor = repo_workspace.create_workspace(
                str(source or self.source), base or self.base_commit,
                str(data or self.data), dict(binding or self.binding),
                before_mutation=gate,
            )
        self.descriptor = descriptor
        self.workspace_root = Path(descriptor["workspace_root"])
        return descriptor

    def _proposal(self, proposal_id="proposal001", changes=None, binding=None):
        return {
            "proposal_id": proposal_id,
            "binding": dict(binding or self.binding),
            "base_commit": self.base_commit,
            "changes": list(changes if changes is not None else [
                self._new_change("approved.txt", "approved content\n")]),
        }

    def _new_change(self, path, content):
        return {"path": path, "before_sha256": None, "content": content}

    def _existing_change(self, path, content, before_bytes=None):
        if before_bytes is None:
            before_bytes = (self.workspace_root / Path(path)).read_bytes()
        return {"path": path, "before_sha256": sha256(before_bytes), "content": content}

    def _apply(self, proposal, allowed=None, *, protected=(), gate=None):
        gate = gate or (lambda: True)
        if allowed is None:
            allowed = [item["path"] for item in proposal["changes"]]
        with clean_git_environment():
            return repo_workspace.apply_proposal(
                self.descriptor, proposal, allowed,
                protected_paths=protected, before_mutation=gate,
            )

    def _freeze(self, *, gate=None):
        with clean_git_environment():
            return repo_workspace.freeze_candidate(
                self.descriptor, before_mutation=gate or (lambda: True))

    def _assert_rejected(self, operation, expected=None):
        with self.assertRaises(repo_workspace.WorkspaceError) as caught:
            operation()
        code = getattr(caught.exception, "code", None)
        self.assertIsInstance(code, str)
        self.assertTrue(code.strip(), "WorkspaceError.code must identify the rejection")
        if expected is not None:
            self.assertEqual(code, expected)
        return code

    def _head(self, root=None):
        return self._git("rev-parse", "HEAD", cwd=root or self.workspace_root).stdout.strip()

    def test_authority_is_required_for_creation_proposals_and_freezing(self):
        data_before = tree_snapshot(self.data)
        with clean_git_environment():
            with self.assertRaises(TypeError):
                repo_workspace.create_workspace(
                    str(self.source), self.base_commit, str(self.data), dict(self.binding))
            self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(self.source), self.base_commit, str(self.data), dict(self.binding),
                before_mutation=None))
        self._assert_rejected(
            lambda: self._create(gate=lambda: False))
        self.assertEqual(tree_snapshot(self.data), data_before)

        self._create()
        proposal = self._proposal()
        before_tree = tree_snapshot(self.workspace_root)
        base_head = self._head()
        self._assert_rejected(lambda: self._apply(proposal, gate=lambda: False))
        self.assertEqual(tree_snapshot(self.workspace_root), before_tree)
        self.assertEqual(self._head(), base_head)
        self._assert_rejected(lambda: self._freeze(gate=lambda: False))
        self.assertEqual(tree_snapshot(self.workspace_root), before_tree)
        self.assertEqual(self._head(), base_head)

        # Missing callbacks are rejected at the API boundary too.
        with clean_git_environment():
            with self.assertRaises(TypeError):
                repo_workspace.apply_proposal(self.descriptor, proposal, ["approved.txt"])
            with self.assertRaises(TypeError):
                repo_workspace.freeze_candidate(self.descriptor)
            self._assert_rejected(lambda: repo_workspace.apply_proposal(
                self.descriptor, proposal, ["approved.txt"], before_mutation=None))
            self._assert_rejected(lambda: repo_workspace.freeze_candidate(
                self.descriptor, before_mutation=None))

    def test_workspace_is_detached_at_requested_clean_baseline_and_source_bytes_stay_fixed(self):
        source_before = tree_snapshot(self.source)
        source_head = self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip()
        descriptor = self._create()
        loaded = repo_workspace.load_workspace(descriptor)

        self.assertEqual(loaded, descriptor)
        self.assertEqual(descriptor["base_commit"], self.base_commit)
        self.assertEqual(descriptor["binding"], self.binding)
        self.assertEqual(self._head(), self.base_commit)
        self.assertEqual(self._git("symbolic-ref", "-q", "HEAD", cwd=self.workspace_root, check=False).returncode, 1)
        self.assertEqual(self._git("status", "--porcelain", cwd=self.workspace_root).stdout, "")
        self.assertEqual(tree_snapshot(self.source), source_before)
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip(), source_head)
        self.assertTrue(self.workspace_root.is_dir())
        self.assertTrue(self.workspace_root.is_relative_to(self.data.resolve()))

    def test_existing_deterministic_workspace_is_not_overwritten(self):
        descriptor = self._create()
        before = tree_snapshot(self.workspace_root)
        with clean_git_environment():
            code = self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(self.source), self.base_commit, str(self.data), dict(self.binding),
                before_mutation=lambda: True))
        self.assertIn(code, {"WORKSPACE_EXISTS", "RECONCILIATION_REQUIRED"})
        self.assertEqual(tree_snapshot(self.workspace_root), before)
        self.assertEqual(repo_workspace.load_workspace(descriptor), descriptor)

    def test_dirty_or_wrong_baseline_source_is_rejected_without_creating_workspace(self):
        dirty = self.source / "untracked.txt"
        dirty.write_bytes(b"dirty source input\n")
        before = tree_snapshot(self.data)
        with clean_git_environment():
            self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(self.source), self.base_commit, str(self.data), dict(self.binding),
                before_mutation=lambda: True))
        self.assertEqual(tree_snapshot(self.data), before)
        dirty.unlink()

        with clean_git_environment():
            self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(self.source), "0" * 40, str(self.data), dict(self.binding),
                before_mutation=lambda: True))
        self.assertEqual(tree_snapshot(self.data), before)

    def test_descriptor_tampering_and_binding_mismatch_are_rejected(self):
        descriptor = self._create()
        forged = dict(descriptor)
        forged["base_commit"] = "f" * len(self.base_commit)
        with clean_git_environment():
            self._assert_rejected(lambda: repo_workspace.load_workspace(forged))

        before = tree_snapshot(self.workspace_root)
        wrong_binding = dict(self.binding, attempt=2)
        proposal = self._proposal(binding=wrong_binding)
        self._assert_rejected(lambda: self._apply(proposal))
        self.assertEqual(tree_snapshot(self.workspace_root), before)

    def test_invalid_proposal_batches_make_no_partial_file_changes(self):
        self._create()
        before = tree_snapshot(self.workspace_root)
        original = (self.workspace_root / "README.md").read_bytes()
        cases = [
            ("directory target", self._proposal("bad-dir", [self._new_change("nested", "x")]), ["nested"], ()),
            ("ADS spelling", self._proposal("bad-ads", [self._new_change("README.md:stream", "x")]), ["README.md:stream"], ()),
            ("protected exact path", self._proposal("bad-protected", [self._new_change("approved.txt", "x")]), ["approved.txt"], ("approved.txt",)),
            ("protected parent overlap", self._proposal("bad-parent", [self._new_change("nested/new.txt", "x")]), ["nested/new.txt"], ("nested",)),
            ("protected child overlap", self._proposal("bad-child", [self._new_change("future", "x")]), ["future"], ("future/child.txt",)),
            ("unapproved path", self._proposal("bad-allow", [self._new_change("unapproved.txt", "x")]), ["approved.txt"], ()),
            ("case collision", self._proposal("bad-case", [self._new_change("Case.txt", "a"), self._new_change("case.txt", "b")]), ["Case.txt", "case.txt"], ()),
            ("wrong before hash", self._proposal("bad-sha", [{"path": "README.md", "before_sha256": "0" * 64, "content": "tampered"}]), ["README.md"], ()),
            ("protected metadata component", self._proposal("bad-git", [self._new_change(".git/config", "unsafe")]), [".git/config"], ()),
            ("runtime metadata component", self._proposal("bad-runtime", [self._new_change(".runtime/state.json", "unsafe")]), [".runtime/state.json"], ()),
            ("codex metadata component", self._proposal("bad-codex", [self._new_change(".codex/state.json", "unsafe")]), [".codex/state.json"], ()),
            ("environment component", self._proposal("bad-env", [self._new_change(".env", "unsafe")]), [".env"], ()),
            ("invalid final item is atomic", self._proposal("bad-last", [
                self._new_change("would-have-been-first.txt", "must not land"),
                {"path": "README.md", "before_sha256": "0" * 64, "content": "wrong"},
            ]), ["would-have-been-first.txt", "README.md"], ()),
        ]
        for label, proposal, allowed, protected in cases:
            with self.subTest(label=label):
                self._assert_rejected(lambda p=proposal, a=allowed, q=protected:
                                      self._apply(p, a, protected=q))
                self.assertEqual(tree_snapshot(self.workspace_root), before)
                self.assertEqual((self.workspace_root / "README.md").read_bytes(), original)

    def test_symlink_targets_and_symlinked_components_are_rejected_when_os_supports_links(self):
        self._create()
        file_link = self.workspace_root / "file-link.txt"
        dir_link = self.workspace_root / "dir-link"
        try:
            os.symlink("README.md", file_link)
            os.symlink("nested", dir_link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("OS symlink creation unavailable; no OS-link proof: " + str(exc))
        self.assertTrue(file_link.is_symlink())
        self.assertTrue(dir_link.is_symlink())
        before = tree_snapshot(self.workspace_root)
        proposals = [
            self._proposal("bad-link-file", [self._new_change("file-link.txt", "unsafe")]),
            self._proposal("bad-link-parent", [self._new_change("dir-link/escape.txt", "unsafe")]),
        ]
        for proposal in proposals:
            with self.subTest(proposal=proposal["proposal_id"]):
                self._assert_rejected(lambda p=proposal: self._apply(p))
                self.assertEqual(tree_snapshot(self.workspace_root), before)
        self.assertEqual((self.workspace_root / "README.md").read_bytes(), b"baseline\r\nsource bytes\n")

    def test_source_data_and_workspace_parent_symlinks_are_rejected_when_os_supports_links(self):
        source_link = self.case_root / "source-link"
        data_link = self.case_root / "data-link"
        try:
            os.symlink(self.source, source_link, target_is_directory=True)
            os.symlink(self.data, data_link, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("OS symlink creation unavailable; no OS-link proof: " + str(exc))

        before_data = tree_snapshot(self.data)
        with clean_git_environment():
            self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(source_link), self.base_commit, str(self.data), dict(self.binding),
                before_mutation=lambda: True))
            self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(self.source), self.base_commit, str(data_link), dict(self.binding),
                before_mutation=lambda: True))
        self.assertEqual(tree_snapshot(self.data), before_data)

        external_workspaces = self.case_root / "external-workspaces"
        external_workspaces.mkdir()
        linked_parent = self.data / "workspaces"
        try:
            os.symlink(external_workspaces, linked_parent, target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            self.skipTest("OS symlink creation unavailable; workspace-parent check unknown: " + str(exc))
        with clean_git_environment():
            self._assert_rejected(lambda: repo_workspace.create_workspace(
                str(self.source), self.base_commit, str(self.data), dict(self.binding),
                before_mutation=lambda: True))
        self.assertEqual(list(external_workspaces.iterdir()), [])

    def test_invalid_text_sizes_and_change_counts_are_rejected_atomically(self):
        self._create()
        before = tree_snapshot(self.workspace_root)
        cases = [
            ("single file over 1 MiB", self._proposal("large-single", [
                self._new_change("large.txt", "x" * (1024 * 1024 + 1))]), ["large.txt"]),
            ("combined content over 4 MiB", self._proposal("large-total", [
                self._new_change("part-%d.txt" % index, "y" * (850 * 1024))
                for index in range(5)]), ["part-%d.txt" % index for index in range(5)]),
            ("more than 50 changes", self._proposal("too-many", [
                self._new_change("item-%02d.txt" % index, "x")
                for index in range(51)]), ["item-%02d.txt" % index for index in range(51)]),
            ("empty change list", self._proposal("empty-changes", []), []),
            ("invalid UTF-8 scalar", self._proposal("invalid-unicode", [
                self._new_change("unicode.txt", "\ud800")]), ["unicode.txt"]),
        ]
        for label, proposal, allowed in cases:
            with self.subTest(label=label):
                self._assert_rejected(lambda p=proposal, a=allowed: self._apply(p, a))
                self.assertEqual(tree_snapshot(self.workspace_root), before)

    def test_text_write_uses_original_raw_byte_sha_and_utf8_bytes(self):
        self._create()
        raw_before = (self.workspace_root / "README.md").read_bytes()
        text = "café\r\nsecond line\n"
        receipt = self._apply(self._proposal(
            "utf8-raw-sha", [self._existing_change("README.md", text, raw_before)]))
        self.assertTrue(receipt)
        self.assertEqual((self.workspace_root / "README.md").read_bytes(), text.encode("utf-8"))

    def test_same_proposal_is_idempotent_and_same_id_with_different_content_conflicts(self):
        self._create()
        proposal = self._proposal("same-proposal")
        first = self._apply(proposal)
        after_first = tree_snapshot(self.workspace_root)
        second = self._apply(proposal)
        self.assertEqual(second, first)
        self.assertEqual(tree_snapshot(self.workspace_root), after_first)

        conflicting = self._proposal("same-proposal", [self._new_change("approved.txt", "different\n")])
        self._assert_rejected(lambda: self._apply(conflicting))
        self.assertEqual(tree_snapshot(self.workspace_root), after_first)

    def test_applying_unknown_state_is_not_automatically_replayed(self):
        self._create()
        proposal = self._proposal("interrupted-proposal")
        control = self.workspace_root.parent / "workspace.control.json"
        observed_states = []

        def lose_authority_after_applying_intent():
            if control.exists():
                state = json.loads(control.read_text(encoding="utf-8")).get("state")
                observed_states.append(state)
                return state != "APPLYING"
            return True

        self._assert_rejected(lambda: self._apply(proposal, gate=lose_authority_after_applying_intent))
        self.assertIn("APPLYING", observed_states,
                      "fault injection must happen only after the durable APPLYING intent exists")
        target = self.workspace_root / "approved.txt"
        self.assertFalse(target.exists())
        record = json.loads(control.read_text(encoding="utf-8"))
        self.assertEqual(record.get("state"), "APPLYING")
        with clean_git_environment():
            code = self._assert_rejected(lambda: repo_workspace.apply_proposal(
                self.descriptor, proposal, ["approved.txt"], before_mutation=lambda: True))
        self.assertEqual(code, "RECONCILIATION_REQUIRED")
        self.assertFalse(target.exists(), "replay must not silently complete an unknown APPLYING state")
        self.assertEqual(json.loads(control.read_text(encoding="utf-8")).get("state"), "APPLYING")

    def test_freeze_rejects_untracked_ignored_and_modified_drift(self):
        self._create()
        self._apply(self._proposal("drift-approved"))
        (self.workspace_root / "extra.txt").write_bytes(b"unproposed\n")
        (self.workspace_root / "ignored.txt").write_bytes(b"ignored but still present\n")
        before_head = self._head()
        self._assert_rejected(lambda: self._freeze())
        self.assertEqual(self._head(), before_head)
        self.assertEqual(self._git("diff", "--cached", "--name-only", cwd=self.workspace_root).stdout, "")

    def test_freeze_rejects_changed_bytes_after_successful_proposal(self):
        self._create()
        self._apply(self._proposal("drift-after-proposal"))
        target = self.workspace_root / "approved.txt"
        target.write_bytes(b"changed after approval\n")
        before_head = self._head()
        self._assert_rejected(lambda: self._freeze())
        self.assertEqual(self._head(), before_head)
        self.assertEqual(self._git("diff", "--cached", "--name-only", cwd=self.workspace_root).stdout, "")

    def test_freeze_rejects_workspace_attached_to_shared_source_branch(self):
        self._create()
        self._apply(self._proposal("attached-branch"))
        branch = self._git("symbolic-ref", "--short", "HEAD", cwd=self.source).stdout.strip()
        self.assertTrue(branch)
        source_before = tree_snapshot(self.source)
        source_head = self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip()
        self.assertEqual(source_head, self.base_commit)
        self.assertEqual(self._git("rev-parse", "refs/heads/" + branch, cwd=self.source).stdout.strip(),
                         self.base_commit)

        self._git("switch", "--ignore-other-worktrees", branch, cwd=self.workspace_root)
        self.assertEqual(self._git("symbolic-ref", "--short", "HEAD", cwd=self.workspace_root).stdout.strip(),
                         branch)
        workspace_before_freeze = tree_snapshot(self.workspace_root)
        self._assert_rejected(lambda: self._freeze(), "WORKTREE_NOT_DETACHED")

        self.assertEqual(tree_snapshot(self.workspace_root), workspace_before_freeze)
        self.assertEqual(self._head(), self.base_commit)
        self.assertEqual(self._git("symbolic-ref", "--short", "HEAD", cwd=self.workspace_root).stdout.strip(),
                         branch)
        self.assertEqual(self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip(), source_head)
        self.assertEqual(self._git("rev-parse", "refs/heads/" + branch, cwd=self.source).stdout.strip(),
                         self.base_commit, "candidate freeze must not advance the shared source branch")
        self.assertEqual(tree_snapshot(self.source), source_before)
        self.assertEqual(self._git("diff", "--cached", "--name-only", cwd=self.workspace_root).stdout, "")

    def test_bracket_path_is_literal_approved_and_idempotent(self):
        sibling_bytes = b"tracked sibling that matches a pathspec pattern\n"
        (self.source / "note1.txt").write_bytes(sibling_bytes)
        self._git("add", "note1.txt", cwd=self.source)
        self._git("commit", "--no-gpg-sign", "-m", "add pathspec sibling", cwd=self.source)
        self.base_commit = self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip()
        source_before = tree_snapshot(self.source)
        self._create()

        literal_bytes = b"approved literal bracket path\n"
        proposal = self._proposal("literal-bracket", [
            self._new_change("note[1].txt", literal_bytes.decode("utf-8"))])
        first_apply = self._apply(proposal, ["note[1].txt"])
        second_apply = self._apply(proposal, ["note[1].txt"])
        self.assertEqual(second_apply, first_apply)
        self.assertEqual((self.workspace_root / "note[1].txt").read_bytes(), literal_bytes)
        self.assertEqual((self.workspace_root / "note1.txt").read_bytes(), sibling_bytes)

        first_candidate = self._freeze()
        candidate_commit = first_candidate["candidate_commit"]
        self.assertEqual([item["path"] for item in first_candidate["files"]], ["note[1].txt"])
        self.assertEqual([item["path"] for item in first_candidate["changes"]], ["note[1].txt"])
        changed_paths = self._git("diff-tree", "--no-commit-id", "--name-only", "-r", "--no-renames",
                                  self.base_commit, candidate_commit, cwd=self.workspace_root).stdout.splitlines()
        self.assertEqual(changed_paths, ["note[1].txt"])
        self.assertEqual(self._git("cat-file", "blob", candidate_commit + ":note[1].txt",
                                   cwd=self.workspace_root).stdout.encode("utf-8"), literal_bytes)
        self.assertEqual(self._git("cat-file", "blob", candidate_commit + ":note1.txt",
                                   cwd=self.workspace_root).stdout.encode("utf-8"), sibling_bytes)
        self.assertEqual((self.workspace_root / "note1.txt").read_bytes(), sibling_bytes)
        self.assertEqual(tree_snapshot(self.source), source_before)

        first_head = self._head()
        first_count = self._git("rev-list", "--count", "HEAD", cwd=self.workspace_root).stdout.strip()
        second_candidate = self._freeze()
        self.assertEqual(second_candidate, first_candidate)
        self.assertEqual(self._head(), first_head)
        self.assertEqual(self._git("rev-list", "--count", "HEAD", cwd=self.workspace_root).stdout.strip(),
                         first_count)

    def test_freezing_is_idempotent_and_a_frozen_workspace_rejects_new_proposals(self):
        self._create()
        self._apply(self._proposal("to-freeze"))
        first = self._freeze()
        first_head = self._head()
        first_count = self._git("rev-list", "--count", "HEAD", cwd=self.workspace_root).stdout.strip()

        second = self._freeze()
        self.assertEqual(second, first)
        self.assertEqual(self._head(), first_head)
        self.assertEqual(self._git("rev-list", "--count", "HEAD", cwd=self.workspace_root).stdout.strip(), first_count)

        later = self._proposal("after-frozen", [self._new_change("later.txt", "late\n")])
        self._assert_rejected(lambda: self._apply(later))
        self.assertFalse((self.workspace_root / "later.txt").exists())
        self.assertEqual(self._head(), first_head)

    def test_freeze_does_not_execute_hooks_filters_gpg_or_network_commands(self):
        # External filters may be refused; other local Git tripwires must stay
        # inert while a safe candidate is created.
        attributes = self.source / ".gitattributes"
        attributes.write_text("tripwire.txt filter=frame003\n", encoding="utf-8")
        self._git("add", ".gitattributes", cwd=self.source)
        self._git("commit", "--no-gpg-sign", "-m", "add synthetic filter attribute", cwd=self.source)
        self.base_commit = self._git("rev-parse", "HEAD", cwd=self.source).stdout.strip()
        self.assertEqual(self._git("status", "--porcelain", cwd=self.source).stdout, "")
        descriptor = self._create()
        self._git("config", "filter.frame003.clean", "printf fired > filter-fired.txt; cat", cwd=self.source)
        self._git("config", "filter.frame003.required", "true", cwd=self.source)
        proposal = self._proposal("firewall", [self._new_change("tripwire.txt", "approved filtered content\n")])
        base_head = self._head()
        self._assert_rejected(lambda: self._apply(proposal), "REPOSITORY_EXECUTABLE_CONFIG")
        markers = (self.workspace_root / "filter-fired.txt", self.case_root / "filter-fired.txt",
                   self.source / "filter-fired.txt")
        self.assertFalse(any(path.exists() for path in markers), "the configured clean filter ran")
        self.assertFalse((self.workspace_root / "tripwire.txt").exists())
        self.assertEqual(self._head(), base_head, "safe refusal must leave HEAD at the requested baseline")
        self.assertEqual(self._git("diff", "--cached", "--name-only", cwd=self.workspace_root).stdout, "")

        # Remove only the synthetic filter configuration from this test-owned
        # repository so the hook, signing, and SSH tripwires can be exercised
        # through a successful local freeze in the same isolated worktree.
        self._git("config", "--unset-all", "filter.frame003.clean", cwd=self.source)
        self._git("config", "--unset-all", "filter.frame003.required", cwd=self.source)
        hook_dir = self.case_root / "hostile-hooks"
        hook_dir.mkdir()
        hook = hook_dir / "pre-commit"
        hook.write_text("#!/bin/sh\nprintf fired > hook-fired.txt\nexit 0\n", encoding="utf-8")
        try:
            hook.chmod(0o755)
        except OSError:
            pass
        self._git("config", "core.hooksPath", str(hook_dir), cwd=self.source)
        self._git("config", "commit.gpgsign", "true", cwd=self.source)
        gpg_tripwire = self.case_root / "gpg-tripwire"
        gpg_tripwire.write_text("#!/bin/sh\nprintf fired > gpg-fired.txt\nexit 1\n", encoding="utf-8")
        try:
            gpg_tripwire.chmod(0o755)
        except OSError:
            pass
        self._git("config", "gpg.program", str(gpg_tripwire), cwd=self.source)
        self._git("config", "remote.origin.url", "ssh://127.0.0.1:1/frame003-no-network", cwd=self.source)
        self._git("config", "core.sshCommand", "printf fired > network-fired.txt", cwd=self.source)

        proposal = self._proposal("no-external-commands", [
            self._new_change("approved.txt", "approved without external commands\n")])
        self._apply(proposal)
        receipt = self._freeze()
        self.assertTrue(receipt)
        markers = [self.workspace_root / name for name in (
            "hook-fired.txt", "filter-fired.txt", "gpg-fired.txt", "network-fired.txt")]
        markers.extend(self.case_root / name for name in (
            "hook-fired.txt", "filter-fired.txt", "gpg-fired.txt", "network-fired.txt"))
        markers.extend(self.source / name for name in (
            "hook-fired.txt", "filter-fired.txt", "gpg-fired.txt", "network-fired.txt"))
        self.assertFalse(any(path.exists() for path in markers),
                         "a pre-commit hook, filter, GPG program, or SSH command ran")
        self.assertNotEqual(self._head(), base_head)
        self.assertEqual(self._git("status", "--porcelain", cwd=self.workspace_root).stdout, "")
        self.assertEqual(self._git("show", "HEAD:approved.txt", cwd=self.workspace_root).stdout,
                         "approved without external commands\n")
        self.assertEqual(descriptor["base_commit"], self.base_commit)


if __name__ == "__main__":
    unittest.main(verbosity=2)
