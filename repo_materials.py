"""Bounded, read-only access to files in a frozen Git input snapshot."""
from __future__ import annotations

import hashlib
import re
import stat
from pathlib import Path

from check_runner import CheckError, input_manifest, root_path
from execution_contract import ContractError, PROTECTED, canonical_hash, inspect_git_input, relative_path


_OID = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
_SHA256 = re.compile(r"[0-9a-fA-F]{64}\Z")
_IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")
_BINDING_FIELDS = {"project_id", "task_id", "spec_version", "attempt", "contract_hash"}
_MAX_MANIFEST_FILES = 10_000
_MAX_MANIFEST_BYTES = 64 * 1024 * 1024
_MAX_FILE_BYTES = 64 * 1024 * 1024
_MAX_EXCERPT_BYTES = 2_048
_MAX_TOTAL_BYTES = 16_384
_MAX_CALLS = 32

# These names augment execution_contract.PROTECTED for material access.  They
# are deliberately path-segment or filename checks, so a similarly named
# ordinary source file elsewhere is not mistaken for a credential.
_SENSITIVE_SEGMENTS = {
    ".ssh", "credentials", "credential", "secrets", "secret", "tokens",
    "token", "certificates", "certificate", "private-keys",
}
_SENSITIVE_STEMS = {
    "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", "credential",
    "credentials", "secret", "secrets", "auth", "authentication",
    "token", "tokens", "access_token", "refresh_token", "api_key",
    "apikey", "client_secret", "private_key", "password", "passwd",
    "passphrase", "service_account", "database_url", "connection_string",
}
_SENSITIVE_SUFFIXES = {".pem", ".p12", ".pfx", ".key", ".keystore", ".jks"}
_CONTROL_DIRECTORIES = {"tasks"}
_CONTROL_BASENAMES = {
    "agents.md", "project.md", "projects.md", "decisions.md",
    "engineering_plan.md", "mainline.md", "development_state.json",
    "architecture_decision.md", "blockers.md", "acceptance.json",
}


class MaterialError(ValueError):
    """A stable, machine-readable failure from the read-only materials API."""

    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


def _fail(code: str, detail: str) -> None:
    raise MaterialError(code, detail)


def _fence(callback) -> None:
    if not callable(callback):
        _fail("AUTHORITY_REQUIRED", "A trusted read authority callback is required")
    try:
        authorized = callback()
    except Exception:
        authorized = False
    if authorized is not True:
        _fail("AUTHORITY_REQUIRED", "Read authority is not current")


def _validate_limit(value, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        _fail("INVALID_BUDGET", f"{name} is outside its supported range")
    return value


def _validate_binding(binding) -> dict:
    if type(binding) is not dict or set(binding) != _BINDING_FIELDS:
        _fail("INVALID_BINDING", "Binding must contain the five frozen fields")
    for name in ("project_id", "task_id"):
        value = binding[name]
        if not isinstance(value, str) or not _IDENT.fullmatch(value):
            _fail("INVALID_BINDING", "Project and task identities must be bounded identifiers")
    for name in ("spec_version", "attempt"):
        value = binding[name]
        if type(value) is not int or not 1 <= value <= 2_147_483_647:
            _fail("INVALID_BINDING", "Binding versions and attempts must be positive bounded integers")
    if not isinstance(binding["contract_hash"], str) or not _SHA256.fullmatch(binding["contract_hash"]):
        _fail("INVALID_BINDING", "Binding requires a full contract SHA-256")
    return dict(binding)


def _is_link(path: Path) -> bool:
    try:
        if path.is_symlink():
            return True
        is_junction = getattr(path, "is_junction", None)
        return bool(is_junction and is_junction())
    except OSError:
        return True


def _is_protected(relative: str) -> bool:
    """Hard-deny conservative controller and secret paths, even if allowlisted."""
    folded = relative.casefold()
    parts = folded.split("/")
    protected = {name.casefold() for name in PROTECTED}
    for name in protected:
        segments = name.split("/")
        if len(segments) == 1 and segments[0] in parts:
            return True
        if len(segments) > 1 and any(
                parts[index:index + len(segments)] == segments
                for index in range(len(parts) - len(segments) + 1)):
            return True
    if any(part in _CONTROL_DIRECTORIES or part in _SENSITIVE_SEGMENTS for part in parts):
        return True
    filename = parts[-1]
    if filename in _CONTROL_BASENAMES:
        return True
    if filename.startswith(".env"):
        return True
    stem = filename.rsplit(".", 1)[0] if "." in filename else filename
    if stem.lstrip(".") in _SENSITIVE_STEMS:
        return True
    if any(filename.endswith(suffix) for suffix in _SENSITIVE_SUFFIXES):
        return True
    return False


def _validate_relative_file(value: str) -> str:
    if not isinstance(value, str):
        _fail("INVALID_PATH", "Approved paths must be exact relative strings")
    try:
        normalized = relative_path(value)
    except ContractError as error:
        _fail(error.code, "Approved path is not a safe repository-relative path")
    if "\x7f" in normalized:
        _fail("INVALID_PATH", "Approved paths cannot contain control characters")
    if _is_protected(normalized):
        _fail("PROTECTED_PATH", "Approved path is controller, credential, or protected configuration data")
    return normalized


def _validate_allowed_paths(allowed_paths) -> tuple[str, ...]:
    if type(allowed_paths) not in (list, tuple) or not 1 <= len(allowed_paths) <= 50:
        _fail("INVALID_PATH", "Require 1 to 50 exact approved file paths")
    paths = []
    seen = set()
    for value in allowed_paths:
        path = _validate_relative_file(value)
        folded = path.casefold()
        if folded in seen:
            _fail("DUPLICATE_PATH", "Approved paths must be unique without case distinctions")
        seen.add(folded)
        paths.append(path)
    return tuple(paths)


def _validate_snapshot_root(snapshot_root) -> Path:
    if not isinstance(snapshot_root, (str, Path)) or not str(snapshot_root) or len(str(snapshot_root)) > 4096:
        _fail("INVALID_PATH", "Snapshot root must be a bounded absolute directory")
    if any(character in str(snapshot_root) for character in ("\x00", "\r", "\n")):
        _fail("INVALID_PATH", "Snapshot root contains an invalid control character")
    try:
        root = root_path(snapshot_root, "snapshot_root", exists=True)
    except CheckError as error:
        _fail(error.code, "Snapshot root is not an ordinary accessible directory")
    if not root.is_absolute():
        _fail("INVALID_PATH", "Snapshot root must be absolute")
    return root


def _checked_manifest(root: Path) -> dict:
    try:
        manifest = input_manifest(root)
    except CheckError as error:
        _fail(error.code, "The complete input manifest could not be safely inspected")
    except (OSError, RuntimeError, ValueError):
        _fail("INPUT_UNAVAILABLE", "The complete input manifest could not be inspected")

    if (type(manifest) is not dict or set(manifest) != {"files", "sha256"}
            or type(manifest.get("files")) is not list
            or not isinstance(manifest.get("sha256"), str)
            or not _SHA256.fullmatch(manifest["sha256"])):
        _fail("INVALID_MANIFEST", "Input manifest has an invalid shape")
    files = manifest["files"]
    if len(files) > _MAX_MANIFEST_FILES:
        _fail("INPUT_LIMIT", "Input manifest exceeds its file limit")
    total = 0
    seen = set()
    for entry in files:
        if (type(entry) is not dict or set(entry) != {"path", "bytes", "sha256"}
                or not isinstance(entry.get("path"), str)
                or type(entry.get("bytes")) is not int or entry["bytes"] < 0
                or not isinstance(entry.get("sha256"), str)
                or not _SHA256.fullmatch(entry["sha256"])):
            _fail("INVALID_MANIFEST", "Input manifest contains an invalid file entry")
        if entry["path"] in seen:
            _fail("INVALID_MANIFEST", "Input manifest contains duplicate paths")
        seen.add(entry["path"])
        total += entry["bytes"]
        if total > _MAX_MANIFEST_BYTES:
            _fail("INPUT_LIMIT", "Input manifest exceeds its byte limit")
    if manifest["sha256"].lower() != _canonical_manifest_hash(files):
        _fail("INVALID_MANIFEST", "Input manifest hash does not match its file list")
    return {"files": tuple(dict(entry) for entry in files), "sha256": manifest["sha256"].lower()}


def _canonical_manifest_hash(files: list[dict]) -> str:
    # Match execution_contract.canonical_hash without accepting mutable aliases.
    return canonical_hash(files)


class RepoMaterials:
    """A cached view of exact approved UTF-8 files from one clean Git input."""

    def __init__(self, snapshot_root, candidate_commit, binding, allowed_paths, *,
                 before_read, max_file_bytes=65_536, max_excerpt_bytes=2_048,
                 max_total_bytes=16_384, max_calls=32):
        self._before_read = before_read
        _fence(before_read)

        self._root = _validate_snapshot_root(snapshot_root)
        if not isinstance(candidate_commit, str) or not _OID.fullmatch(candidate_commit):
            _fail("INVALID_CANDIDATE", "A full Git commit ID is required")
        self.candidate_commit = candidate_commit.lower()
        self._binding = _validate_binding(binding)
        self.allowed_paths = _validate_allowed_paths(allowed_paths)
        self.max_file_bytes = _validate_limit(max_file_bytes, "max_file_bytes", 1, _MAX_FILE_BYTES)
        self.max_excerpt_bytes = _validate_limit(max_excerpt_bytes, "max_excerpt_bytes", 1, _MAX_EXCERPT_BYTES)
        self.max_total_bytes = _validate_limit(max_total_bytes, "max_total_bytes", 1, _MAX_TOTAL_BYTES)
        self.max_calls = _validate_limit(max_calls, "max_calls", 1, _MAX_CALLS)

        probe = self._inspect_git()
        if (probe["clean"] is not True or probe["head"].lower() != self.candidate_commit
                or Path(probe["root"]).resolve() != self._root):
            _fail("INPUT_DRIFT", "Snapshot is not the clean frozen Git candidate")
        self._git_binding = {
            "root": str(self._root),
            "head": probe["head"].lower(),
            "tree": probe["tree"].lower(),
        }
        manifest = _checked_manifest(self._root)
        self.input_hash = manifest["sha256"]
        self._manifest_files = manifest["files"]
        self._manifest_index = {entry["path"]: entry for entry in self._manifest_files}

        self._file_bytes: dict[str, bytes] = {}
        self._file_text: dict[str, str] = {}
        self._file_sha256: dict[str, str] = {}
        for path in self.allowed_paths:
            entry = self._manifest_index.get(path)
            if entry is None:
                _fail("PATH_NOT_IN_INPUT", "Approved file is absent from the frozen input")
            if entry["bytes"] > self.max_file_bytes:
                _fail("FILE_TOO_LARGE", "An approved file exceeds max_file_bytes")
            target = self._resolve_approved_file(path)
            try:
                raw = target.read_bytes()
            except OSError:
                _fail("INPUT_UNAVAILABLE", "An approved input file could not be read")
            if len(raw) > self.max_file_bytes:
                _fail("FILE_TOO_LARGE", "An approved file exceeds max_file_bytes")
            digest = hashlib.sha256(raw).hexdigest()
            if len(raw) != entry["bytes"] or digest != entry["sha256"].lower():
                _fail("INPUT_DRIFT", "An approved file changed while materials were being captured")
            try:
                decoded = raw.decode("utf-8", errors="strict")
            except UnicodeDecodeError:
                _fail("INVALID_UTF8", "Every approved material file must be valid UTF-8")
            self._file_bytes[path] = raw
            self._file_text[path] = decoded
            self._file_sha256[path] = digest

        # Close the construction window: both Git state and the full file
        # manifest must still describe the same clean candidate.
        self._assert_current()
        self._records: list[dict] = []
        self._calls_used = 0
        self._bytes_returned = 0

    @property
    def binding(self) -> dict:
        """Return a detached copy so callers cannot mutate the captured binding."""
        return dict(self._binding)

    def _inspect_git(self) -> dict:
        try:
            probe = inspect_git_input(str(self._root))
        except ContractError as error:
            _fail(error.code, "Git input could not be safely inspected")
        except (OSError, RuntimeError, ValueError):
            _fail("REPOSITORY_UNAVAILABLE", "Git input could not be safely inspected")
        if (type(probe) is not dict or not isinstance(probe.get("root"), str)
                or not isinstance(probe.get("head"), str) or not _OID.fullmatch(probe["head"])
                or not isinstance(probe.get("tree"), str) or not _OID.fullmatch(probe["tree"])
                or type(probe.get("clean")) is not bool):
            _fail("INVALID_GIT_INPUT", "Git inspection returned an invalid result")
        return probe

    def _resolve_approved_file(self, relative: str) -> Path:
        target = self._root
        for part in relative.split("/"):
            target = target / part
            if _is_link(target):
                _fail("LINKED_PATH", "Approved material path traverses a link")
        try:
            resolved = target.resolve(strict=True)
            mode = resolved.lstat().st_mode
        except (OSError, RuntimeError):
            _fail("INPUT_DRIFT", "An approved input file is no longer available")
        if not resolved.is_relative_to(self._root):
            _fail("INVALID_PATH", "Approved material path escapes the snapshot root")
        if not stat.S_ISREG(mode):
            _fail("INVALID_INPUT", "Approved material path must be a regular file")
        return resolved

    def _assert_current(self) -> None:
        probe = self._inspect_git()
        if (probe["clean"] is not True or probe["head"].lower() != self._git_binding["head"]
                or probe["tree"].lower() != self._git_binding["tree"]
                or Path(probe["root"]).resolve() != self._root):
            _fail("INPUT_DRIFT", "Git candidate changed after materials were bound")
        current = _checked_manifest(self._root)
        if current["sha256"] != self.input_hash or current["files"] != self._manifest_files:
            _fail("INPUT_DRIFT", "The complete input file manifest changed after materials were bound")

    def read(self, path, offset=0) -> dict:
        """Return one byte-bounded UTF-8 excerpt at a Unicode character offset."""
        _fence(self._before_read)
        if self._calls_used >= self.max_calls:
            _fail("READ_BUDGET_EXHAUSTED", "Read call budget is exhausted")
        # Count each authority-approved read invocation, including invalid
        # path/offset requests, so retries cannot bypass the call budget.
        self._calls_used += 1
        if not isinstance(path, str) or path not in self._file_text:
            _fail("PATH_NOT_ALLOWED", "Read path must exactly match an approved file")
        if type(offset) is not int or offset < 0:
            _fail("INVALID_OFFSET", "Offset must be a nonnegative Unicode character index")
        self._assert_current()
        text = self._file_text[path]
        if offset > len(text):
            _fail("INVALID_OFFSET", "Offset is past the end of the approved file")
        remaining = text[offset:]
        if remaining and self._bytes_returned >= self.max_total_bytes:
            _fail("READ_BUDGET_EXHAUSTED", "Cumulative excerpt byte budget is exhausted")

        excerpt_budget = min(self.max_excerpt_bytes, self.max_total_bytes - self._bytes_returned)
        pieces = []
        byte_count = 0
        for character in remaining:
            size = len(character.encode("utf-8"))
            if byte_count + size > excerpt_budget:
                break
            pieces.append(character)
            byte_count += size
        excerpt = "".join(pieces)
        if remaining and not excerpt:
            _fail("READ_BUDGET_EXHAUSTED", "Remaining byte budget cannot hold the next UTF-8 character")
        end = offset + len(excerpt)
        next_offset = None if end >= len(text) else end

        # A callback failure never creates a delivery record or consumes the
        # read budget.  The callback above is the authority fence for this
        # single tool read; all following work uses the immutable cache.
        result = {
            "path": path,
            "candidate_commit": self.candidate_commit,
            "input_hash": self.input_hash,
            "file_sha256": self._file_sha256[path],
            "file_bytes": len(self._file_bytes[path]),
            "offset": offset,
            "next_offset": next_offset,
            "excerpt": excerpt,
        }
        # EOF on a nonempty file is only an empty pagination result, not proof
        # that the file's contents were delivered.  A truly empty file is an
        # actual zero-byte material delivery and receives a precise record.
        if excerpt or not text:
            self._records.append({
                "path": path,
                "file_sha256": self._file_sha256[path],
                "offset": offset,
                "next_offset": next_offset,
                "returned_bytes": byte_count,
            })
        self._bytes_returned += byte_count
        return result

    def records(self) -> list[dict]:
        """Return a copy of the exact successful material deliveries."""
        return [dict(record) for record in self._records]

    def assert_unchanged(self) -> bool:
        """Recheck the clean Git candidate and the full file manifest, read-only."""
        _fence(self._before_read)
        self._assert_current()
        return True
