"""Bounded Git workspaces for proposal-only repository changes.

This module owns no scheduling or authorization state.  Callers must supply a
trusted ``before_mutation`` callback; every filesystem or Git mutation passes
through that fence.  Persistent records live beside, never inside, the model
workspace.
"""
from __future__ import annotations

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))


import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import uuid
from pathlib import Path


SCHEMA_VERSION = "native-orchestrator.repo-workspace/0.3"
_RECORD_SCHEMA = "native-orchestrator.repo-workspace-record/0.3"
_DESCRIPTOR_FIELDS = {
    "schema_version", "source_root", "base_commit", "data_root",
    "workspace_root", "binding", "workspace_id",
}
_RECORD_FIELDS = {
    "schema_version", "descriptor", "state", "base_tree", "intent",
    "proposals", "candidate",
}
_BINDING_FIELDS = {"project_id", "task_id", "spec_version", "attempt", "contract_hash"}
_OID = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z", re.ASCII)
_RESERVED_WINDOWS = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", re.I)
_DEFAULT_PROTECTED = {
    ".git", ".runtime", ".codex", ".agents", ".aws", ".env", "data-live",
    "config.live.json", "config.codex.json", "config.workbuddy.json",
    "mainline.md", "development_state.json", "state.sqlite", "auth.json",
}
_ACTIVE_STATES = {"CREATING", "APPLYING", "FREEZING"}
_READY_STATES = {"READY", "FROZEN"}
_MAX_FILE_BYTES = 1024 * 1024
_MAX_TOTAL_BYTES = 4 * 1024 * 1024
_MAX_CHANGES = 50
_GIT_TIMEOUT = 30


class WorkspaceError(ValueError):
    """A bounded workspace failure with a stable machine-readable code."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(code + ": " + detail)


def _error(code: str, detail: str):
    raise WorkspaceError(code, detail)


def _canonical_bytes(value) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True,
                          separators=(",", ":"), allow_nan=False).encode("utf-8", "strict")
    except (TypeError, ValueError, UnicodeError):
        _error("INVALID_INPUT", "Value cannot be represented as canonical UTF-8 JSON")


def _canonical_hash(value) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _is_junction(path: Path) -> bool:
    probe = getattr(path, "is_junction", None)
    if callable(probe):
        try:
            return bool(probe())
        except OSError:
            _error("INVALID_PATH", "Path metadata could not be inspected")
    probe = getattr(os.path, "isjunction", None)
    if callable(probe):
        try:
            return bool(probe(path))
        except OSError:
            _error("INVALID_PATH", "Path metadata could not be inspected")
    return False


def _entry_exists(path: Path) -> bool:
    try:
        path.lstat()
        return True
    except FileNotFoundError:
        return False
    except OSError:
        _error("INVALID_PATH", "Path metadata could not be inspected")


def _assert_no_links(path: Path) -> None:
    for part in (path, *path.parents):
        if part.is_symlink() or _is_junction(part):
            _error("LINKED_PATH", "Workspace paths may not traverse links or junctions")


def _absolute_path(value, label: str, *, must_exist: bool) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError:
        _error("INVALID_PATH", label + " must be an absolute path")
    if not isinstance(raw, str) or not raw or "\0" in raw or "\n" in raw or "\r" in raw:
        _error("INVALID_PATH", label + " must be a bounded absolute path")
    path = Path(raw)
    if not path.is_absolute():
        _error("INVALID_PATH", label + " must be absolute")
    _assert_no_links(path)
    try:
        resolved = path.resolve(strict=must_exist)
    except (OSError, RuntimeError):
        _error("INVALID_PATH", label + " could not be resolved")
    _assert_no_links(resolved)
    if must_exist and not _entry_exists(resolved):
        _error("INVALID_PATH", label + " does not exist")
    return resolved


def _same_path(left: Path, right: Path) -> bool:
    return os.path.normcase(os.path.normpath(str(left))) == os.path.normcase(os.path.normpath(str(right)))


def _is_within(path: Path, parent: Path) -> bool:
    try:
        return os.path.commonpath((os.path.normcase(str(path)), os.path.normcase(str(parent)))) == os.path.normcase(str(parent))
    except ValueError:
        return False


def _assert_disjoint_roots(source_root: Path, data_root: Path) -> None:
    if _is_within(source_root, data_root) or _is_within(data_root, source_root):
        _error("INVALID_DATA_ROOT", "Source and controller data roots must be separate trees")


def _validate_binding(value) -> dict:
    if not isinstance(value, dict) or set(value) != _BINDING_FIELDS:
        _error("INVALID_BINDING", "Binding must contain exactly the five approved fields")
    result = dict(value)
    for key in ("project_id", "task_id"):
        if not isinstance(result[key], str) or not _IDENT.fullmatch(result[key]):
            _error("INVALID_BINDING", key + " must be an ASCII identifier of at most 64 characters")
    for key in ("spec_version", "attempt"):
        if type(result[key]) is not int or result[key] < 1:
            _error("INVALID_BINDING", key + " must be a positive integer")
    if not isinstance(result["contract_hash"], str) or not _SHA256.fullmatch(result["contract_hash"]):
        _error("INVALID_BINDING", "contract_hash must be a 64-character SHA-256")
    result["contract_hash"] = result["contract_hash"].lower()
    return result


def _descriptor(source_root: Path, base_commit: str, data_root: Path, binding: dict) -> dict:
    workspace_id = _canonical_hash(binding)
    workspace_root = data_root / "workspaces" / workspace_id / "repo"
    return {
        "schema_version": SCHEMA_VERSION,
        "source_root": str(source_root),
        "base_commit": base_commit.lower(),
        "data_root": str(data_root),
        "workspace_root": str(workspace_root),
        "binding": dict(binding),
        "workspace_id": workspace_id,
    }


def _validate_descriptor(value) -> dict:
    if not isinstance(value, dict) or set(value) != _DESCRIPTOR_FIELDS:
        _error("INVALID_DESCRIPTOR", "Descriptor has missing or unknown fields")
    if value.get("schema_version") != SCHEMA_VERSION:
        _error("INVALID_DESCRIPTOR", "Unsupported workspace descriptor version")
    source_root = _absolute_path(value.get("source_root"), "source_root", must_exist=True)
    if not source_root.is_dir():
        _error("INVALID_DESCRIPTOR", "source_root must be a directory")
    data_root = _absolute_path(value.get("data_root"), "data_root", must_exist=True)
    if not data_root.is_dir():
        _error("INVALID_DESCRIPTOR", "data_root must be a directory")
    binding = _validate_binding(value.get("binding"))
    base_commit = value.get("base_commit")
    if not isinstance(base_commit, str) or not _OID.fullmatch(base_commit):
        _error("INVALID_DESCRIPTOR", "base_commit must be a full Git object ID")
    expected = _descriptor(source_root, base_commit, data_root, binding)
    for key in _DESCRIPTOR_FIELDS:
        actual = value[key]
        if key == "base_commit":
            matches = isinstance(actual, str) and actual.lower() == expected[key]
        elif key == "binding":
            matches = actual == expected[key]
        else:
            matches = actual == expected[key]
        if not matches:
            _error("INVALID_DESCRIPTOR", "Descriptor ownership fields do not match their derived paths")
    _assert_disjoint_roots(source_root, data_root)
    _assert_no_links(Path(expected["workspace_root"]))
    return expected


def _authorize(before_mutation) -> None:
    if not callable(before_mutation):
        _error("AUTHORITY_REQUIRED", "A trusted before_mutation callback is required")
    try:
        allowed = before_mutation()
    except Exception:
        _error("AUTHORITY_REQUIRED", "Mutation authority check failed")
    if allowed is not True:
        _error("AUTHORITY_REQUIRED", "Mutation authority is not current")


def _git_environment() -> dict:
    env = {key: value for key, value in os.environ.items() if not key.upper().startswith("GIT_")}
    env.update({
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_PAGER": "cat",
        "PAGER": "cat",
    })
    return env


def _git_argv(executable: str, root: Path, hook_path: Path, args) -> list:
    if "\n" in str(root) or "\r" in str(root) or "\0" in str(root):
        _error("INVALID_PATH", "Git root contains a control character")
    if "\n" in str(hook_path) or "\r" in str(hook_path) or "\0" in str(hook_path):
        _error("INVALID_PATH", "Hook path contains a control character")
    return [
        executable,
        "-c", "safe.directory=" + str(root),
        "-c", "core.fsmonitor=false",
        "-c", "core.hooksPath=" + str(hook_path),
        "-c", "commit.gpgsign=false",
        "-c", "tag.gpgsign=false",
        "-c", "core.autocrlf=false",
        "-c", "maintenance.auto=false",
        "-c", "gc.auto=0",
        "-c", "protocol.allow=never",
        "--no-optional-locks",
        "-C", str(root),
        *args,
    ]


def _git(root: Path, args, *, hook_path: Path, executable: str | None = None,
         before_mutation=None, mutating: bool = False, allow_codes=(0,)) -> bytes:
    if executable is None:
        executable = shutil.which("git")
    if not executable:
        _error("REPOSITORY_UNAVAILABLE", "Git executable is unavailable")
    if mutating:
        _authorize(before_mutation)
    try:
        result = subprocess.run(
            _git_argv(executable, root, hook_path, list(args)),
            env=_git_environment(), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
            timeout=_GIT_TIMEOUT, check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    except (OSError, subprocess.TimeoutExpired):
        _error("GIT_COMMAND_FAILED", "Fixed Git command failed or timed out")
    if result.returncode not in allow_codes:
        _error("GIT_COMMAND_FAILED", "Fixed Git command returned an unexpected status")
    return result.stdout


def _git_text(data: bytes, label: str) -> str:
    try:
        return data.decode("utf-8", "strict").strip()
    except UnicodeError:
        _error("REPOSITORY_UNAVAILABLE", label + " was not valid UTF-8")


def _require_no_filters(root: Path, hook_path: Path, executable: str) -> None:
    output = _git(root, ["config", "--includes", "--get-regexp", r"^filter\."],
                   hook_path=hook_path, executable=executable, allow_codes=(0, 1))
    if output:
        _error("REPOSITORY_EXECUTABLE_CONFIG", "Configured external Git filters are not allowed")


def _tree_paths(root: Path, base_commit: str, hook_path: Path, executable: str) -> None:
    raw = _git(root, ["ls-tree", "-r", "-z", "--full-tree", base_commit],
                hook_path=hook_path, executable=executable)
    for entry in raw.split(b"\0"):
        if not entry:
            continue
        try:
            meta, name = entry.split(b"\t", 1)
            mode, kind, oid = meta.split(b" ", 2)
        except ValueError:
            _error("INVALID_BASELINE", "Git tree returned malformed entry data")
        if mode in (b"120000", b"160000") or kind not in (b"blob",):
            _error("UNSUPPORTED_GIT_ENTRY", "Input tree contains a link or submodule")
        if not _OID.fullmatch(oid.decode("ascii", "strict")):
            _error("INVALID_BASELINE", "Input tree contains an invalid object ID")
        try:
            decoded = name.decode("utf-8", "strict")
        except UnicodeError:
            _error("INVALID_BASELINE", "Input tree contains a non-UTF-8 path")
        _relative_path(decoded)


def _inspect_repository(source_root: Path, base_commit: str, hook_path: Path,
                        executable: str) -> dict:
    top = _git_text(_git(source_root, ["rev-parse", "--show-toplevel"],
                         hook_path=hook_path, executable=executable), "repository root")
    try:
        observed_root = Path(top).resolve(strict=True)
    except (OSError, RuntimeError):
        _error("REPOSITORY_UNAVAILABLE", "Repository root could not be resolved")
    if not _same_path(observed_root, source_root):
        _error("REPOSITORY_ROOT_MISMATCH", "repo_root is not the exact Git repository root")
    _require_no_filters(source_root, hook_path, executable)
    head = _git_text(_git(source_root, ["rev-parse", "--verify", "HEAD^{commit}"],
                          hook_path=hook_path, executable=executable), "HEAD")
    resolved_base = _git_text(_git(source_root, ["rev-parse", "--verify", base_commit + "^{commit}"],
                                   hook_path=hook_path, executable=executable), "base commit")
    if not _OID.fullmatch(head) or not _OID.fullmatch(resolved_base):
        _error("INVALID_BASELINE", "Full committed Git object IDs are required")
    if head.lower() != base_commit.lower() or resolved_base.lower() != base_commit.lower():
        _error("BASELINE_CHANGED", "Source HEAD must equal the requested base commit")
    tree = _git_text(_git(source_root, ["rev-parse", "--verify", base_commit + "^{tree}"],
                          hook_path=hook_path, executable=executable), "base tree")
    if not _OID.fullmatch(tree):
        _error("INVALID_BASELINE", "Base tree is not a full Git object ID")
    status = _git(source_root, ["status", "--porcelain=v1", "--untracked-files=all",
                                "--ignore-submodules=none"],
                  hook_path=hook_path, executable=executable)
    if status:
        _error("DIRTY_INPUT", "Source repository must be clean before workspace creation")
    _tree_paths(source_root, base_commit, hook_path, executable)
    return {"head": head.lower(), "tree": tree.lower()}


def _hook_path(descriptor: dict) -> Path:
    return Path(descriptor["workspace_root"]).parent / ".hooks-disabled"


def _assert_hooks_disabled(descriptor: dict) -> None:
    path = _hook_path(descriptor)
    _assert_no_links(path)
    if _entry_exists(path):
        _error("GIT_HOOK_PATH_OCCUPIED", "The isolated disabled-hook path must remain absent")


def _ensure_directory(path: Path, before_mutation) -> None:
    _assert_no_links(path)
    missing = []
    current = path
    while not _entry_exists(current):
        missing.append(current)
        parent = current.parent
        if parent == current:
            _error("INVALID_PATH", "No existing parent directory for workspace data")
        current = parent
    if not current.is_dir():
        _error("INVALID_PATH", "Workspace parent path is not a directory")
    for directory in reversed(missing):
        _assert_no_links(directory)
        if _entry_exists(directory):
            if not directory.is_dir():
                _error("INVALID_PATH", "Workspace parent path is not a directory")
            continue
        _authorize(before_mutation)
        try:
            directory.mkdir()
        except OSError:
            _error("WORKSPACE_CREATE_FAILED", "Workspace directory could not be created")


def _json_bytes(value) -> bytes:
    return _canonical_bytes(value) + b"\n"


def _write_all(fd: int, data: bytes) -> None:
    view = memoryview(data)
    while view:
        written = os.write(fd, view)
        if written <= 0:
            raise OSError("short write")
        view = view[written:]
    os.fsync(fd)


def _create_record(path: Path, record: dict, before_mutation) -> None:
    _assert_no_links(path.parent)
    if _entry_exists(path):
        _error("WORKSPACE_EXISTS", "Workspace control record already exists")
    _authorize(before_mutation)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0)
    try:
        fd = os.open(path, flags, 0o600)
        try:
            _write_all(fd, _json_bytes(record))
        finally:
            os.close(fd)
    except OSError:
        _error("RECONCILIATION_REQUIRED", "Initial workspace intent could not be durably recorded")


def _replace_record(path: Path, record: dict, before_mutation) -> None:
    _assert_no_links(path.parent)
    if not _entry_exists(path) or path.is_symlink() or not path.is_file():
        _error("RECONCILIATION_REQUIRED", "Workspace control record changed unexpectedly")
    temp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    _authorize(before_mutation)
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), 0o600)
        try:
            _write_all(fd, _json_bytes(record))
        finally:
            os.close(fd)
    except OSError:
        _error("RECONCILIATION_REQUIRED", "Workspace control update could not be written")
    _assert_no_links(path.parent)
    if path.is_symlink() or not path.is_file():
        _error("RECONCILIATION_REQUIRED", "Workspace control record changed unexpectedly")
    _authorize(before_mutation)
    try:
        os.replace(temp, path)
    except OSError:
        _error("RECONCILIATION_REQUIRED", "Workspace control update could not be committed")


def _read_json(path: Path, code: str):
    _assert_no_links(path)
    if not _entry_exists(path) or path.is_symlink() or not path.is_file():
        _error(code, "Workspace control record is missing or not a regular file")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", "strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        _error(code, "Workspace control record is unreadable")
    if not isinstance(value, dict):
        _error(code, "Workspace control record is malformed")
    return value


def _record_path(descriptor: dict) -> Path:
    return Path(descriptor["workspace_root"]).parent / "workspace.control.json"


def _validate_receipt(proposal_id: str, item) -> dict:
    if not isinstance(item, dict) or set(item) != {"proposal_hash", "receipt"}:
        _error("RECONCILIATION_REQUIRED", "Persisted proposal record is malformed")
    proposal_hash = item["proposal_hash"]
    receipt = item["receipt"]
    if not isinstance(proposal_hash, str) or not _SHA256.fullmatch(proposal_hash):
        _error("RECONCILIATION_REQUIRED", "Persisted proposal hash is malformed")
    fields = {"status", "workspace_id", "proposal_id", "proposal_hash", "base_commit", "sequence", "files"}
    if not isinstance(receipt, dict) or set(receipt) != fields:
        _error("RECONCILIATION_REQUIRED", "Persisted proposal receipt is malformed")
    if (receipt.get("status") != "APPLIED" or receipt.get("proposal_id") != proposal_id
            or receipt.get("proposal_hash") != proposal_hash):
        _error("RECONCILIATION_REQUIRED", "Persisted proposal receipt ownership is inconsistent")
    if (not isinstance(receipt.get("workspace_id"), str)
            or not isinstance(receipt.get("base_commit"), str)
            or not _OID.fullmatch(receipt["base_commit"])):
        _error("RECONCILIATION_REQUIRED", "Persisted proposal ownership fields are malformed")
    if type(receipt.get("sequence")) is not int or receipt["sequence"] < 1:
        _error("RECONCILIATION_REQUIRED", "Persisted proposal sequence is malformed")
    files = receipt.get("files")
    if not isinstance(files, list) or not files:
        _error("RECONCILIATION_REQUIRED", "Persisted proposal file list is malformed")
    seen = set()
    for entry in files:
        if not isinstance(entry, dict) or set(entry) != {"path", "before_sha256", "after_sha256"}:
            _error("RECONCILIATION_REQUIRED", "Persisted proposal file entry is malformed")
        name = _relative_path(entry["path"])
        key = name.casefold()
        if key in seen:
            _error("RECONCILIATION_REQUIRED", "Persisted proposal has colliding paths")
        seen.add(key)
        before = entry["before_sha256"]
        if before is not None and (not isinstance(before, str) or not _SHA256.fullmatch(before)):
            _error("RECONCILIATION_REQUIRED", "Persisted before hash is malformed")
        after = entry["after_sha256"]
        if not isinstance(after, str) or not _SHA256.fullmatch(after):
            _error("RECONCILIATION_REQUIRED", "Persisted after hash is malformed")
    return item


def _read_record(descriptor: dict) -> dict:
    path = _record_path(descriptor)
    record = _read_json(path, "RECONCILIATION_REQUIRED")
    if set(record) != _RECORD_FIELDS or record.get("schema_version") != _RECORD_SCHEMA:
        _error("RECONCILIATION_REQUIRED", "Workspace record version or fields are invalid")
    if record.get("descriptor") != descriptor:
        _error("INVALID_DESCRIPTOR", "Descriptor does not exactly match its persistent owner record")
    state = record.get("state")
    if not isinstance(state, str) or state not in _ACTIVE_STATES | _READY_STATES:
        _error("RECONCILIATION_REQUIRED", "Workspace record has an unknown state")
    if not isinstance(record.get("base_tree"), str) or not _OID.fullmatch(record["base_tree"]):
        _error("RECONCILIATION_REQUIRED", "Workspace base tree record is malformed")
    proposals = record.get("proposals")
    if not isinstance(proposals, dict):
        _error("RECONCILIATION_REQUIRED", "Workspace proposal ledger is malformed")
    for proposal_id, item in proposals.items():
        if not isinstance(proposal_id, str) or not _IDENT.fullmatch(proposal_id):
            _error("RECONCILIATION_REQUIRED", "Persisted proposal identifier is malformed")
        _validate_receipt(proposal_id, item)
        receipt = item["receipt"]
        if (receipt["workspace_id"] != descriptor["workspace_id"]
                or receipt["base_commit"].lower() != descriptor["base_commit"].lower()):
            _error("RECONCILIATION_REQUIRED", "Persisted proposal ownership is inconsistent")
    intent = record.get("intent")
    candidate = record.get("candidate")
    if state in _ACTIVE_STATES and not isinstance(intent, dict):
        _error("RECONCILIATION_REQUIRED", "Workspace has an incomplete durable intent")
    if state in _READY_STATES and intent is not None:
        _error("RECONCILIATION_REQUIRED", "Ready workspace unexpectedly has an unfinished intent")
    if state == "FROZEN" and not isinstance(candidate, dict):
        _error("RECONCILIATION_REQUIRED", "Frozen workspace lacks its candidate receipt")
    if state != "FROZEN" and candidate is not None:
        _error("RECONCILIATION_REQUIRED", "Non-frozen workspace contains a candidate receipt")
    return record


def _decode_path(data: bytes) -> str:
    try:
        value = data.decode("utf-8", "strict")
    except UnicodeError:
        _error("INPUT_DRIFT", "Git reported a path that is not UTF-8")
    return _relative_path(value)


def _relative_path(value) -> str:
    if not isinstance(value, str) or not value or len(value) > 1024:
        _error("INVALID_PATH", "Change path must be a bounded relative UTF-8 path")
    if (value.startswith("/") or value.startswith("\\") or "\\" in value or ":" in value
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        _error("INVALID_PATH", "Change path contains an absolute, ADS, separator, or control form")
    parts = value.split("/")
    for part in parts:
        if (not part or part in (".", "..") or part.rstrip(" .") != part
                or any(char in part for char in '*?<>|"') or _RESERVED_WINDOWS.match(part)):
            _error("INVALID_PATH", "Change path contains an unsafe component")
    return value


def _validate_path_set(paths, label: str, *, allow_empty=False) -> list:
    if not isinstance(paths, (list, tuple)):
        _error("INVALID_PATH", label + " must be an explicit path list")
    if (not allow_empty and not 1 <= len(paths) <= _MAX_CHANGES) or (allow_empty and len(paths) > _MAX_CHANGES):
        _error("INVALID_PATH", label + " has an invalid number of paths")
    normalized = []
    folded = set()
    for value in paths:
        name = _relative_path(value)
        key = name.casefold()
        if key in folded:
            _error("DUPLICATE_PATH", label + " contains a case-insensitive collision")
        folded.add(key)
        normalized.append(name)
    return normalized


def _path_overlap(left: str, right: str) -> bool:
    left_fold, right_fold = left.casefold(), right.casefold()
    return (left_fold == right_fold or left_fold.startswith(right_fold + "/")
            or right_fold.startswith(left_fold + "/"))


def _check_protection(path: str, protected_paths) -> None:
    components = [part.casefold() for part in path.split("/")]
    for component in components:
        if component in _DEFAULT_PROTECTED or component.startswith(".env."):
            _error("PROTECTED_PATH", "Change path contains a protected metadata component")
    protected = set(_DEFAULT_PROTECTED)
    for value in protected_paths:
        protected.add(_relative_path(value).casefold())
    if any(_path_overlap(path, protected_name) for protected_name in protected):
        _error("PROTECTED_PATH", "Change path overlaps a protected path")


def _find_actual_component(parent: Path, component: str):
    if not _entry_exists(parent):
        return None
    if parent.is_symlink() or _is_junction(parent) or not parent.is_dir():
        _error("INVALID_PATH", "A change path parent is not a plain directory")
    matches = []
    try:
        with os.scandir(parent) as entries:
            for entry in entries:
                if entry.name.casefold() == component.casefold():
                    matches.append(entry.name)
    except OSError:
        _error("INVALID_PATH", "Change path parent could not be inspected")
    if len(matches) > 1 or (matches and matches[0] != component):
        _error("CASE_COLLISION", "Change path collides with an existing name by case")
    return None if not matches else parent / matches[0]


def _target_path(root: Path, relative: str, *, allow_missing: bool):
    current = root
    parts = relative.split("/")
    for index, component in enumerate(parts):
        found = _find_actual_component(current, component)
        if found is None:
            if not allow_missing:
                return root.joinpath(*parts), None
            current = current / component
            continue
        if found.is_symlink() or _is_junction(found):
            _error("LINKED_PATH", "Change path may not traverse a link or junction")
        if index < len(parts) - 1:
            if not found.is_dir():
                _error("INVALID_PATH", "A parent component is not a directory")
        else:
            try:
                mode = found.lstat().st_mode
            except OSError:
                _error("INVALID_PATH", "Change path target could not be inspected")
            if not stat.S_ISREG(mode):
                _error("INVALID_PATH", "Change path target must be a regular file")
        current = found
    if not _entry_exists(current):
        return current, None
    return current, current


def _read_target(root: Path, relative: str):
    target, existing = _target_path(root, relative, allow_missing=True)
    if existing is None:
        return target, None, None
    try:
        info = existing.stat()
        if info.st_size > _MAX_FILE_BYTES:
            _error("FILE_TOO_LARGE", "Existing proposal target exceeds the one MiB limit")
        data = existing.read_bytes()
    except WorkspaceError:
        raise
    except OSError:
        _error("INVALID_PATH", "Change path target could not be read")
    return target, data, hashlib.sha256(data).hexdigest()


def _scan_workspace(root: Path) -> None:
    stack = [(root, "")]
    while stack:
        directory, prefix = stack.pop()
        try:
            with os.scandir(directory) as entries:
                current_entries = list(entries)
        except OSError:
            _error("INPUT_DRIFT", "Workspace contents could not be inspected")
        for entry in current_entries:
            relative = entry.name if not prefix else prefix + "/" + entry.name
            path = Path(entry.path)
            if not prefix and entry.name == ".git":
                # The root worktree pointer is Git's expected metadata.
                if entry.is_symlink() or not entry.is_file(follow_symlinks=False):
                    _error("WORKTREE_INVALID", "Git worktree pointer is not a regular metadata file")
                continue
            if entry.name.casefold() == ".git":
                _error("PROTECTED_PATH", "Nested .git metadata is not allowed in a worktree")
            if path.is_symlink() or _is_junction(path):
                _error("LINKED_PATH", "Workspace contains a link or junction")
            try:
                mode = path.lstat().st_mode
            except OSError:
                _error("INPUT_DRIFT", "Workspace entry metadata could not be inspected")
            if stat.S_ISDIR(mode):
                stack.append((path, relative))
            elif not stat.S_ISREG(mode):
                _error("INPUT_DRIFT", "Workspace contains a special file")


def _status_entries(root: Path, descriptor: dict, executable: str) -> list:
    hook_path = _hook_path(descriptor)
    _require_no_filters(root, hook_path, executable)
    raw = _git(root, ["status", "--porcelain=v1", "-z", "--untracked-files=all",
                      "--ignored=matching", "--no-renames", "--ignore-submodules=none"],
                hook_path=hook_path, executable=executable)
    result = []
    for part in raw.split(b"\0"):
        if not part:
            continue
        if len(part) < 4 or part[2:3] != b" ":
            _error("INPUT_DRIFT", "Git status returned malformed workspace data")
        try:
            status = part[:2].decode("ascii", "strict")
        except UnicodeError:
            _error("INPUT_DRIFT", "Git status code was malformed")
        name = _decode_path(part[3:])
        result.append((status, name))
    return result


def _ordered_events(record: dict) -> list:
    events = []
    for proposal_id, item in record["proposals"].items():
        receipt = item["receipt"]
        for file_entry in receipt["files"]:
            events.append({
                "sequence": receipt["sequence"],
                "proposal_id": proposal_id,
                "proposal_hash": item["proposal_hash"],
                "path": file_entry["path"],
                "before_sha256": file_entry["before_sha256"],
                "after_sha256": file_entry["after_sha256"],
            })
    events.sort(key=lambda item: (item["sequence"], item["path"].casefold()))
    return events


def _expected_files(record: dict) -> dict:
    current = {}
    first = {}
    folded_paths = {}
    for event in _ordered_events(record):
        path = event["path"]
        folded = path.casefold()
        if folded in folded_paths and folded_paths[folded] != path:
            _error("RECONCILIATION_REQUIRED", "Persisted proposals contain a case-insensitive path collision")
        folded_paths[folded] = path
        previous = current.get(path)
        if path in current and event["before_sha256"] != previous:
            _error("RECONCILIATION_REQUIRED", "Persisted proposal hash chain is inconsistent")
        if path not in first:
            first[path] = event["before_sha256"]
        current[path] = event["after_sha256"]
    return {path: {"before_sha256": first[path], "after_sha256": digest}
            for path, digest in current.items()}


def _effective_paths(files: dict) -> set:
    return {path for path, item in files.items()
            if item["before_sha256"] is None or item["before_sha256"] != item["after_sha256"]}


def _verify_worktree(descriptor: dict, record: dict, executable: str, *, expected_head: str) -> None:
    root = Path(descriptor["workspace_root"])
    _assert_no_links(root)
    if not root.is_dir():
        _error("WORKTREE_INVALID", "Workspace repository directory is missing")
    _scan_workspace(root)
    _assert_hooks_disabled(descriptor)
    _require_no_filters(root, _hook_path(descriptor), executable)
    source = Path(descriptor["source_root"])
    common_source = _git_text(_git(source, ["rev-parse", "--git-common-dir"],
                                   hook_path=_hook_path(descriptor), executable=executable), "source git directory")
    common_workspace = _git_text(_git(root, ["rev-parse", "--git-common-dir"],
                                      hook_path=_hook_path(descriptor), executable=executable), "workspace git directory")
    try:
        common_source_path = Path(common_source)
        if not common_source_path.is_absolute():
            common_source_path = source / common_source_path
        common_workspace_path = Path(common_workspace)
        if not common_workspace_path.is_absolute():
            common_workspace_path = root / common_workspace_path
        common_source_path = common_source_path.resolve(strict=True)
        common_workspace_path = common_workspace_path.resolve(strict=True)
    except (OSError, RuntimeError):
        _error("WORKTREE_INVALID", "Git worktree metadata could not be resolved")
    if not _same_path(common_source_path, common_workspace_path):
        _error("WORKTREE_INVALID", "Workspace is not attached to the recorded source repository")
    top = _git_text(_git(root, ["rev-parse", "--show-toplevel"],
                         hook_path=_hook_path(descriptor), executable=executable), "workspace root")
    try:
        top_path = Path(top).resolve(strict=True)
    except (OSError, RuntimeError):
        _error("WORKTREE_INVALID", "Git returned an invalid workspace root")
    if not _same_path(top_path, root):
        _error("WORKTREE_INVALID", "Git worktree root differs from the descriptor")
    symbolic = _git(root, ["symbolic-ref", "-q", "HEAD"],
                    hook_path=_hook_path(descriptor), executable=executable, allow_codes=(0, 1))
    if symbolic:
        _error("WORKTREE_NOT_DETACHED", "Workspace HEAD must stay detached; shared branches cannot be advanced")
    head = _git_text(_git(root, ["rev-parse", "--verify", "HEAD^{commit}"],
                          hook_path=_hook_path(descriptor), executable=executable), "workspace HEAD")
    if head.lower() != expected_head.lower():
        _error("INPUT_DRIFT", "Workspace HEAD differs from its recorded baseline or candidate")
    base_tree = _git_text(_git(root, ["rev-parse", "--verify", descriptor["base_commit"] + "^{tree}"],
                               hook_path=_hook_path(descriptor), executable=executable), "workspace base tree")
    if base_tree.lower() != record["base_tree"].lower():
        _error("INPUT_DRIFT", "Workspace base tree differs from the persistent record")


def _verify_ready_contents(descriptor: dict, record: dict, executable: str) -> dict:
    root = Path(descriptor["workspace_root"])
    _verify_worktree(descriptor, record, executable, expected_head=descriptor["base_commit"])
    files = _expected_files(record)
    expected = _effective_paths(files)
    statuses = _status_entries(root, descriptor, executable)
    actual = set()
    for status, path in statuses:
        if status == "!!":
            _error("INPUT_DRIFT", "Ignored files are present in the workspace")
        if status not in {"??", " M", "M ", "MM", "A ", "AM"}:
            _error("INPUT_DRIFT", "Workspace contains a deletion, rename, or unsupported Git change")
        actual.add(path)
    if actual != expected:
        _error("INPUT_DRIFT", "Workspace changes do not match successfully applied proposals")
    for relative, info in files.items():
        _, data, digest = _read_target(root, relative)
        if data is None or digest != info["after_sha256"]:
            _error("INPUT_DRIFT", "A proposed file no longer matches its recorded after hash")
    return files


def _validate_candidate_shape(candidate: dict, descriptor: dict) -> None:
    fields = {"status", "workspace_id", "binding", "source_root", "base_commit", "base_tree",
              "candidate_commit", "candidate_tree", "proposals", "changes", "files"}
    if not isinstance(candidate, dict) or set(candidate) != fields:
        _error("RECONCILIATION_REQUIRED", "Candidate receipt is malformed")
    base_commit = candidate.get("base_commit")
    if (candidate["status"] != "FROZEN" or candidate["workspace_id"] != descriptor["workspace_id"]
            or candidate["binding"] != descriptor["binding"]
            or candidate["source_root"] != descriptor["source_root"]
            or not isinstance(base_commit, str) or not _OID.fullmatch(base_commit)
            or base_commit.lower() != descriptor["base_commit"].lower()
            or not isinstance(candidate["base_tree"], str) or not _OID.fullmatch(candidate["base_tree"])
            or not isinstance(candidate["candidate_commit"], str) or not _OID.fullmatch(candidate["candidate_commit"])
            or not isinstance(candidate["candidate_tree"], str) or not _OID.fullmatch(candidate["candidate_tree"])):
        _error("RECONCILIATION_REQUIRED", "Candidate receipt ownership or object IDs are invalid")


def _candidate_expected(record: dict, descriptor: dict, candidate_commit: str, candidate_tree: str) -> dict:
    files = _expected_files(record)
    proposals = []
    for proposal_id, item in sorted(record["proposals"].items(), key=lambda pair: pair[1]["receipt"]["sequence"]):
        proposals.append({"proposal_id": proposal_id, "proposal_hash": item["proposal_hash"],
                          "sequence": item["receipt"]["sequence"]})
    changes = _ordered_events(record)
    manifest = []
    for path, entry in sorted(files.items(), key=lambda pair: pair[0].casefold()):
        manifest.append({"path": path, "before_sha256": entry["before_sha256"],
                         "after_sha256": entry["after_sha256"]})
    return {
        "status": "FROZEN",
        "workspace_id": descriptor["workspace_id"],
        "binding": dict(descriptor["binding"]),
        "source_root": descriptor["source_root"],
        "base_commit": descriptor["base_commit"],
        "base_tree": record["base_tree"],
        "candidate_commit": candidate_commit.lower(),
        "candidate_tree": candidate_tree.lower(),
        "proposals": proposals,
        "changes": changes,
        "files": manifest,
    }


def _nul_paths(raw: bytes) -> set:
    result = set()
    for item in raw.split(b"\0"):
        if item:
            result.add(_decode_path(item))
    return result


def _verify_frozen(descriptor: dict, record: dict, executable: str) -> dict:
    candidate = record["candidate"]
    _validate_candidate_shape(candidate, descriptor)
    root = Path(descriptor["workspace_root"])
    _verify_worktree(descriptor, record, executable, expected_head=candidate["candidate_commit"])
    if _status_entries(root, descriptor, executable):
        _error("INPUT_DRIFT", "Frozen candidate has uncommitted or ignored files")
    parent = _git_text(_git(root, ["rev-parse", "--verify", candidate["candidate_commit"] + "^"],
                            hook_path=_hook_path(descriptor), executable=executable), "candidate parent")
    if parent.lower() != descriptor["base_commit"].lower():
        _error("INPUT_DRIFT", "Candidate commit is not a direct child of its recorded base")
    tree = _git_text(_git(root, ["rev-parse", "--verify", candidate["candidate_commit"] + "^{tree}"],
                          hook_path=_hook_path(descriptor), executable=executable), "candidate tree")
    if tree.lower() != candidate["candidate_tree"].lower():
        _error("INPUT_DRIFT", "Candidate tree differs from its durable receipt")
    changed = _nul_paths(_git(root, ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                                     "--no-renames", descriptor["base_commit"], candidate["candidate_commit"]],
                              hook_path=_hook_path(descriptor), executable=executable))
    expected_files = _expected_files(record)
    expected_paths = _effective_paths(expected_files)
    if changed != expected_paths:
        _error("INPUT_DRIFT", "Candidate contains paths outside successful proposals")
    for relative, info in expected_files.items():
        _, data, digest = _read_target(root, relative)
        if data is None or digest != info["after_sha256"]:
            _error("INPUT_DRIFT", "Frozen workspace bytes differ from the proposal receipt")
        blob = _git(root, ["cat-file", "blob", candidate["candidate_commit"] + ":" + relative],
                    hook_path=_hook_path(descriptor), executable=executable)
        if hashlib.sha256(blob).hexdigest() != info["after_sha256"]:
            _error("CANDIDATE_CONTENT_MISMATCH", "Candidate blob bytes differ from approved UTF-8 content")
    expected_receipt = _candidate_expected(record, descriptor, candidate["candidate_commit"], candidate["candidate_tree"])
    if candidate != expected_receipt:
        _error("RECONCILIATION_REQUIRED", "Candidate receipt does not match the proposal ledger")
    return candidate


def _load_validated(descriptor) -> tuple[dict, dict]:
    desc = _validate_descriptor(descriptor)
    record = _read_record(desc)
    if record["state"] in _ACTIVE_STATES:
        _error("RECONCILIATION_REQUIRED", "Workspace has an unfinished side-effect intent")
    executable = shutil.which("git")
    if not executable:
        _error("REPOSITORY_UNAVAILABLE", "Git executable is unavailable")
    if record["state"] == "READY":
        _verify_ready_contents(desc, record, executable)
    else:
        _verify_frozen(desc, record, executable)
    return desc, record


def create_workspace(repo_root, base_commit, data_root, binding, *, before_mutation):
    """Create one detached worktree rooted under the controller data directory."""
    _authorize(before_mutation)
    source = _absolute_path(repo_root, "repo_root", must_exist=True)
    if not source.is_dir():
        _error("REPOSITORY_UNAVAILABLE", "Approved repository root is not a directory")
    data = _absolute_path(data_root, "data_root", must_exist=False)
    if not isinstance(base_commit, str) or not _OID.fullmatch(base_commit):
        _error("INVALID_BASELINE", "A full base commit object ID is required")
    normalized_binding = _validate_binding(binding)
    desc = _descriptor(source, base_commit, data, normalized_binding)
    _assert_disjoint_roots(source, data)
    _assert_no_links(Path(desc["workspace_root"]))
    parent = Path(desc["workspace_root"]).parent
    record_path = _record_path(desc)
    if _entry_exists(record_path):
        try:
            old = _read_json(record_path, "RECONCILIATION_REQUIRED")
        except WorkspaceError:
            raise
        if old.get("state") in _ACTIVE_STATES:
            _error("RECONCILIATION_REQUIRED", "An earlier workspace creation has an uncertain outcome")
        _error("WORKSPACE_EXISTS", "A workspace already owns this binding")
    if _entry_exists(Path(desc["workspace_root"])) or _entry_exists(parent):
        _error("WORKSPACE_EXISTS", "The binding-derived workspace location is already occupied")
    hook_path = _hook_path(desc)
    if _entry_exists(hook_path):
        _error("GIT_HOOK_PATH_OCCUPIED", "The isolated disabled-hook path must be absent")
    executable = shutil.which("git")
    if not executable:
        _error("REPOSITORY_UNAVAILABLE", "Git executable is unavailable")
    baseline = _inspect_repository(source, base_commit.lower(), hook_path, executable)
    _ensure_directory(parent, before_mutation)
    record = {
        "schema_version": _RECORD_SCHEMA,
        "descriptor": desc,
        "state": "CREATING",
        "base_tree": baseline["tree"],
        "intent": {"kind": "CREATE", "base_commit": base_commit.lower()},
        "proposals": {},
        "candidate": None,
    }
    _create_record(record_path, record, before_mutation)
    try:
        current_baseline = _inspect_repository(source, base_commit.lower(), hook_path, executable)
        if current_baseline != baseline:
            _error("BASELINE_CHANGED", "Source repository changed after creation intent was recorded")
        _assert_hooks_disabled(desc)
        _git(source, ["worktree", "add", "--detach", str(Path(desc["workspace_root"])), base_commit.lower()],
             hook_path=hook_path, executable=executable, before_mutation=before_mutation, mutating=True)
        _assert_hooks_disabled(desc)
        _require_no_filters(Path(desc["workspace_root"]), hook_path, executable)
        _verify_worktree(desc, record, executable, expected_head=base_commit.lower())
        if _status_entries(Path(desc["workspace_root"]), desc, executable):
            _error("INPUT_DRIFT", "New worktree is not clean at its base commit")
        record["state"] = "READY"
        record["intent"] = None
        _replace_record(record_path, record, before_mutation)
    except WorkspaceError:
        _error("RECONCILIATION_REQUIRED", "Workspace creation may have changed Git state; inspect the durable intent")
    except Exception:
        _error("RECONCILIATION_REQUIRED", "Workspace creation outcome is uncertain; inspect the durable intent")
    load_workspace(desc)
    return dict(desc)


def load_workspace(descriptor):
    """Return a descriptor only after ownership, journal, and worktree checks pass."""
    desc, _record = _load_validated(descriptor)
    return dict(desc)


def _normalize_proposal(proposal, descriptor, allowed_paths, protected_paths):
    if not isinstance(proposal, dict) or set(proposal) != {"proposal_id", "binding", "base_commit", "changes"}:
        _error("INVALID_PROPOSAL", "Proposal has missing or unknown fields")
    proposal_id = proposal["proposal_id"]
    if not isinstance(proposal_id, str) or not _IDENT.fullmatch(proposal_id):
        _error("INVALID_PROPOSAL", "proposal_id must be an ASCII identifier of at most 64 characters")
    proposal_binding = _validate_binding(proposal["binding"])
    if proposal_binding != descriptor["binding"]:
        _error("BINDING_MISMATCH", "Proposal binding differs from workspace ownership")
    base_commit = proposal["base_commit"]
    if not isinstance(base_commit, str) or not _OID.fullmatch(base_commit) or base_commit.lower() != descriptor["base_commit"].lower():
        _error("BASELINE_CHANGED", "Proposal base commit differs from the workspace baseline")
    approved = _validate_path_set(allowed_paths, "allowed_paths")
    protected = []
    if not isinstance(protected_paths, (list, tuple)):
        _error("INVALID_PATH", "protected_paths must be an explicit list")
    for value in protected_paths:
        protected.append(_relative_path(value))
    changes = proposal["changes"]
    if not isinstance(changes, list) or not 1 <= len(changes) <= _MAX_CHANGES:
        _error("INVALID_PROPOSAL", "Proposal must contain 1..50 file changes")
    normalized_changes = []
    folded = set()
    seen_paths = []
    total = 0
    for change in changes:
        if not isinstance(change, dict) or set(change) != {"path", "before_sha256", "content"}:
            _error("INVALID_PROPOSAL", "Each change must contain exactly path, before_sha256, and content")
        relative = _relative_path(change["path"])
        if relative not in approved:
            _error("PATH_NOT_ALLOWED", "Proposal path is not an exact allowed_changes entry")
        folded_path = relative.casefold()
        if folded_path in folded:
            _error("DUPLICATE_PATH", "Proposal contains a case-insensitive path collision")
        folded.add(folded_path)
        for previous in seen_paths:
            if _path_overlap(relative, previous):
                _error("PATH_CONFLICT", "Proposal paths may not be parent and child")
        seen_paths.append(relative)
        _check_protection(relative, protected)
        before = change["before_sha256"]
        if before is not None and (not isinstance(before, str) or not _SHA256.fullmatch(before)):
            _error("INVALID_PROPOSAL", "before_sha256 must be null or a full SHA-256")
        content = change["content"]
        if not isinstance(content, str) or "\0" in content:
            _error("INVALID_PROPOSAL", "File content must be UTF-8 text without NUL bytes")
        try:
            content_bytes = content.encode("utf-8", "strict")
        except UnicodeError:
            _error("INVALID_PROPOSAL", "File content must be valid UTF-8 text")
        if len(content_bytes) > _MAX_FILE_BYTES:
            _error("FILE_TOO_LARGE", "Each proposed file is limited to one MiB")
        total += len(content_bytes)
        if total > _MAX_TOTAL_BYTES:
            _error("TOTAL_TOO_LARGE", "Proposal content is limited to four MiB total")
        normalized_changes.append({
            "path": relative,
            "before_sha256": None if before is None else before.lower(),
            "content": content,
        })
    normalized = {
        "proposal_id": proposal_id,
        "binding": proposal_binding,
        "base_commit": base_commit.lower(),
        "changes": normalized_changes,
    }
    return normalized, _canonical_hash(normalized)


def _ensure_target_before(root: Path, change: dict):
    target, data, digest = _read_target(root, change["path"])
    if change["before_sha256"] is None:
        if data is not None:
            _error("INPUT_DRIFT", "New-file proposal target already exists")
    elif data is None or digest != change["before_sha256"]:
        _error("INPUT_DRIFT", "Existing file bytes differ from before_sha256")
    return target, data


def _atomic_target_write(root: Path, relative: str, expected_before: str | None,
                         data: bytes, before_mutation) -> None:
    target, _existing = _target_path(root, relative, allow_missing=True)
    parent = target.parent
    _ensure_directory(parent, before_mutation)
    _assert_no_links(parent)
    _ensure_target_before(root, {"path": relative, "before_sha256": expected_before})
    file_mode = 0o600
    if _entry_exists(target):
        try:
            file_mode = target.lstat().st_mode & 0o777
        except OSError:
            _error("INVALID_PATH", "Change target mode could not be inspected")
    temp = parent / ("." + target.name + ".proposal-" + uuid.uuid4().hex)
    _authorize(before_mutation)
    try:
        fd = os.open(temp, os.O_CREAT | os.O_EXCL | os.O_WRONLY | getattr(os, "O_BINARY", 0), file_mode)
        try:
            _write_all(fd, data)
        finally:
            os.close(fd)
    except OSError:
        _error("RECONCILIATION_REQUIRED", "Proposal temporary file could not be written")
    _assert_no_links(parent)
    try:
        _ensure_target_before(root, {"path": relative, "before_sha256": expected_before})
    except WorkspaceError:
        _error("RECONCILIATION_REQUIRED", "Proposal target changed during application")
    _authorize(before_mutation)
    try:
        os.replace(temp, target)
    except OSError:
        _error("RECONCILIATION_REQUIRED", "Atomic proposal write failed")


def apply_proposal(descriptor, proposal, allowed_paths, *, protected_paths=(), before_mutation):
    """Validate every file change before writing any proposal content."""
    _authorize(before_mutation)
    desc, record = _load_validated(descriptor)
    if record["state"] not in {"READY", "FROZEN"}:
        _error("RECONCILIATION_REQUIRED", "Workspace is not ready for a proposal")
    normalized, proposal_hash = _normalize_proposal(proposal, desc, allowed_paths, protected_paths)
    proposal_id = normalized["proposal_id"]
    existing_receipt = record["proposals"].get(proposal_id)
    if existing_receipt is not None:
        if existing_receipt["proposal_hash"] != proposal_hash:
            _error("PROPOSAL_CONFLICT", "proposal_id is already bound to different content")
        for file_entry in existing_receipt["receipt"]["files"]:
            _, data, digest = _read_target(Path(desc["workspace_root"]), file_entry["path"])
            if data is None or digest != file_entry["after_sha256"]:
                _error("RECONCILIATION_REQUIRED", "Idempotent proposal output no longer matches its receipt")
        return json.loads(_canonical_bytes(existing_receipt["receipt"]).decode("utf-8"))
    if record["state"] == "FROZEN":
        _error("WORKSPACE_FROZEN", "Frozen workspaces reject new proposals")
    root = Path(desc["workspace_root"])
    plans = []
    for change in normalized["changes"]:
        target, old_data = _ensure_target_before(root, change)
        new_bytes = change["content"].encode("utf-8", "strict")
        plans.append({
            "path": change["path"],
            "before_sha256": change["before_sha256"],
            "after_sha256": hashlib.sha256(new_bytes).hexdigest(),
            "content_bytes": new_bytes,
            "target": target,
        })
    sequence = 1 + max((item["receipt"]["sequence"] for item in record["proposals"].values()), default=0)
    intent = {
        "kind": "APPLY_PROPOSAL",
        "proposal_id": proposal_id,
        "proposal_hash": proposal_hash,
        "sequence": sequence,
        "files": [{"path": item["path"], "before_sha256": item["before_sha256"],
                   "after_sha256": item["after_sha256"]} for item in plans],
        "completed": [],
    }
    record["state"] = "APPLYING"
    record["intent"] = intent
    _replace_record(_record_path(desc), record, before_mutation)
    try:
        for plan in plans:
            # Recheck all original bytes immediately before each atomic replacement.
            target, old_data = _ensure_target_before(root, {
                "path": plan["path"], "before_sha256": plan["before_sha256"],
            })
            _atomic_target_write(root, plan["path"], plan["before_sha256"],
                                 plan["content_bytes"], before_mutation)
            _, current_data, current_hash = _read_target(root, plan["path"])
            if current_data is None or current_hash != plan["after_sha256"]:
                _error("RECONCILIATION_REQUIRED", "Written proposal bytes did not match their planned hash")
            intent["completed"].append({"path": plan["path"], "after_sha256": current_hash})
            record["intent"] = intent
            _replace_record(_record_path(desc), record, before_mutation)
        receipt = {
            "status": "APPLIED",
            "workspace_id": desc["workspace_id"],
            "proposal_id": proposal_id,
            "proposal_hash": proposal_hash,
            "base_commit": desc["base_commit"],
            "sequence": sequence,
            "files": [{"path": item["path"], "before_sha256": item["before_sha256"],
                       "after_sha256": item["after_sha256"]} for item in plans],
        }
        record["proposals"][proposal_id] = {"proposal_hash": proposal_hash, "receipt": receipt}
        record["state"] = "READY"
        record["intent"] = None
        _replace_record(_record_path(desc), record, before_mutation)
    except WorkspaceError as error:
        if error.code == "RECONCILIATION_REQUIRED":
            raise
        _error("RECONCILIATION_REQUIRED", "Proposal application stopped after a durable intent")
    except Exception:
        _error("RECONCILIATION_REQUIRED", "Proposal application outcome is uncertain")
    # Re-open and verify the durable receipt and every output before returning it.
    _load_validated(desc)
    return json.loads(_canonical_bytes(receipt).decode("utf-8"))


def _verify_source_baseline(descriptor: dict, record: dict, executable: str) -> None:
    source = Path(descriptor["source_root"])
    baseline = _inspect_repository(source, descriptor["base_commit"], _hook_path(descriptor), executable)
    if baseline["tree"].lower() != record["base_tree"].lower():
        _error("BASELINE_CHANGED", "Source repository base tree changed after workspace creation")


def _check_staged_paths(descriptor: dict, record: dict, executable: str, expected: set) -> None:
    root = Path(descriptor["workspace_root"])
    raw = _git(root, ["diff", "--cached", "--name-only", "-z", "--no-renames",
                      descriptor["base_commit"], "--"],
                hook_path=_hook_path(descriptor), executable=executable)
    if _nul_paths(raw) != expected:
        _error("INPUT_DRIFT", "Git index contains paths outside successful proposals")
    unstaged = _git(root, ["diff", "--no-ext-diff", "--no-textconv", "--name-only", "-z",
                           "--no-renames", "--"],
                    hook_path=_hook_path(descriptor), executable=executable)
    if _nul_paths(unstaged):
        _error("INPUT_DRIFT", "Workspace contains unstaged bytes after staging")
    files = _expected_files(record)
    for relative in expected:
        staged = _git(root, ["cat-file", "blob", ":" + relative],
                      hook_path=_hook_path(descriptor), executable=executable)
        if hashlib.sha256(staged).hexdigest() != files[relative]["after_sha256"]:
            _error("CANDIDATE_CONTENT_MISMATCH", "Git index bytes differ from approved UTF-8 content")
    statuses = _status_entries(root, descriptor, executable)
    for status, path in statuses:
        if status not in {"A ", "M "} or path not in expected:
            _error("INPUT_DRIFT", "Unexpected, ignored, or unstaged workspace content exists")


def freeze_candidate(descriptor, *, before_mutation):
    """Commit only successfully proposed files and make the result immutable."""
    _authorize(before_mutation)
    desc, record = _load_validated(descriptor)
    if record["state"] == "FROZEN":
        return json.loads(_canonical_bytes(record["candidate"]).decode("utf-8"))
    if record["state"] != "READY":
        _error("RECONCILIATION_REQUIRED", "Workspace is not ready to freeze")
    executable = shutil.which("git")
    if not executable:
        _error("REPOSITORY_UNAVAILABLE", "Git executable is unavailable")
    _verify_source_baseline(desc, record, executable)
    files = _verify_ready_contents(desc, record, executable)
    expected = _effective_paths(files)
    if not expected:
        _error("NO_CHANGES", "No proposal changes differ from the workspace baseline")
    proposals = sorted(record["proposals"].items(), key=lambda pair: pair[1]["receipt"]["sequence"])
    intent = {
        "kind": "FREEZE_CANDIDATE",
        "base_commit": desc["base_commit"],
        "paths": sorted(expected, key=str.casefold),
        "proposal_ids": [proposal_id for proposal_id, _item in proposals],
    }
    record["state"] = "FREEZING"
    record["intent"] = intent
    _replace_record(_record_path(desc), record, before_mutation)
    root = Path(desc["workspace_root"])
    try:
        _verify_source_baseline(desc, record, executable)
        _assert_hooks_disabled(desc)
        _require_no_filters(root, _hook_path(desc), executable)
        _verify_ready_contents(desc, {**record, "state": "READY", "intent": None}, executable)
        _git(root, ["add", "--", *sorted(expected, key=str.casefold)],
             hook_path=_hook_path(desc), executable=executable,
             before_mutation=before_mutation, mutating=True)
        _check_staged_paths(desc, record, executable, expected)
        _assert_hooks_disabled(desc)
        _require_no_filters(root, _hook_path(desc), executable)
        _git(root, ["-c", "user.name=Native Orchestrator", "-c",
                    "user.email=native-orchestrator@invalid", "commit", "--no-verify",
                    "--no-gpg-sign", "-m", "FRAME-003 candidate " + desc["workspace_id"][:12]],
             hook_path=_hook_path(desc), executable=executable,
             before_mutation=before_mutation, mutating=True)
        candidate_commit = _git_text(_git(root, ["rev-parse", "--verify", "HEAD^{commit}"],
                                           hook_path=_hook_path(desc), executable=executable), "candidate commit")
        parent = _git_text(_git(root, ["rev-parse", "--verify", candidate_commit + "^"],
                                hook_path=_hook_path(desc), executable=executable), "candidate parent")
        if parent.lower() != desc["base_commit"].lower():
            _error("INPUT_DRIFT", "Created candidate is not a direct child of its base")
        candidate_tree = _git_text(_git(root, ["rev-parse", "--verify", candidate_commit + "^{tree}"],
                                         hook_path=_hook_path(desc), executable=executable), "candidate tree")
        if not _OID.fullmatch(candidate_commit) or not _OID.fullmatch(candidate_tree):
            _error("INPUT_DRIFT", "Created candidate object IDs are malformed")
        committed = _nul_paths(_git(root, ["diff-tree", "--no-commit-id", "--name-only", "-r", "-z",
                                           "--no-renames", desc["base_commit"], candidate_commit],
                                    hook_path=_hook_path(desc), executable=executable))
        if committed != expected:
            _error("INPUT_DRIFT", "Candidate commit contains paths outside successful proposals")
        if _status_entries(root, desc, executable):
            _error("INPUT_DRIFT", "Workspace is not clean after candidate commit")
        candidate = _candidate_expected(record, desc, candidate_commit, candidate_tree)
        record["state"] = "FROZEN"
        record["intent"] = None
        record["candidate"] = candidate
        _replace_record(_record_path(desc), record, before_mutation)
    except WorkspaceError as error:
        if error.code == "RECONCILIATION_REQUIRED":
            raise
        _error("RECONCILIATION_REQUIRED", "Candidate freeze may have changed the Git index or commit; inspect the durable intent")
    except Exception:
        _error("RECONCILIATION_REQUIRED", "Candidate freeze outcome is uncertain; inspect the durable intent")
    _load_validated(desc)
    return json.loads(_canonical_bytes(candidate).decode("utf-8"))
