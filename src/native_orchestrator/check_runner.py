"""Catalog-only checks through the native restricted command boundary."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import copy
import hashlib
import json
import os
import re
import stat
import sys
import uuid
from pathlib import Path
from native_orchestrator.execution_contract import canonical_hash, inspect_git_input
from native_orchestrator.native_check_exec import NativeCheckError, VERIFIED_NATIVE_VERSIONS, WINDOWS_LAUNCH_ENV_KEYS, _validate_command, execute_native

OID = re.compile(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z")
SHA = re.compile(r"[0-9a-fA-F]{64}\Z")
IDENT = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


class CheckError(ValueError):
    def __init__(self, code, detail):
        self.code = code
        super().__init__(code + ": " + detail)


def require_fields(value, fields, label):
    if not isinstance(value, dict) or set(value) != set(fields):
        raise CheckError("INVALID_INPUT", label + " has missing or unknown fields")


def fence(callback):
    if not callable(callback):
        raise CheckError("AUTHORITY_REQUIRED", "Trusted dispatch authority is required")
    try:
        valid = callback()
    except Exception:
        valid = False
    if valid is not True:
        raise CheckError("AUTHORITY_REQUIRED", "Dispatch authority is not current")


def root_path(value, label, exists=True):
    if not isinstance(value, (str, Path)) or not str(value) or any(c in str(value) for c in ("\0", "\r", "\n")):
        raise CheckError("INVALID_PATH", label + " must be a bounded absolute directory")
    path = Path(value)
    if not path.is_absolute():
        raise CheckError("INVALID_PATH", label + " must be absolute")
    if any(p.is_symlink() or (hasattr(p, "is_junction") and p.is_junction()) for p in (path, *path.parents)):
        raise CheckError("LINKED_PATH", label + " traverses a link")
    try:
        path = path.resolve(strict=exists)
    except (OSError, RuntimeError):
        raise CheckError("INVALID_PATH", label + " unavailable") from None
    if exists and not path.is_dir():
        raise CheckError("INVALID_PATH", label + " must be a directory")
    return path


def input_manifest(root):
    files = []
    total = 0
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        if relative == ".git" or relative.startswith(".git/"):
            continue
        if path.is_symlink() or (hasattr(path, "is_junction") and path.is_junction()):
            raise CheckError("LINKED_PATH", "Input snapshot contains a link")
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if not stat.S_ISREG(mode):
            raise CheckError("INVALID_INPUT", "Input snapshot contains a special file")
        size = path.stat().st_size
        if len(files) >= 10000 or size + total > 64 * 1024 * 1024:
            raise CheckError("INPUT_LIMIT", "Snapshot exceeds this verified runner's input limit")
        raw = path.read_bytes()
        total += len(raw)
        if len(files) >= 10000 or total > 64 * 1024 * 1024:
            raise CheckError("INPUT_LIMIT", "Snapshot exceeds this verified runner's input limit")
        files.append({"path": relative, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()})
    return {"files": files, "sha256": canonical_hash(files)}


def atomic_json(path, value, callback):
    fence(callback)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
    with temporary.open("xb") as stream:
        stream.write(raw); stream.flush(); os.fsync(stream.fileno())
    fence(callback)
    os.replace(temporary, path)


def validate(check_id, catalog, context):
    if not isinstance(check_id, str) or not IDENT.fullmatch(check_id) or not isinstance(catalog, dict) or check_id not in catalog:
        raise CheckError("CHECK_NOT_APPROVED", "Select an existing approved check ID")
    check = catalog[check_id]
    require_fields(check, {"argv", "timeout_seconds", "output_bytes_cap", "write_scope", "network", "shell", "verification", "evidence_sha256"}, "catalog check")
    if check["verification"] != "VERIFIED" or not isinstance(check["evidence_sha256"], str) or not SHA.fullmatch(check["evidence_sha256"]):
        raise CheckError("CAPABILITY_UNVERIFIED", "Verified check capability evidence required")
    argv = check["argv"]
    if not isinstance(argv, list) or not 1 <= len(argv) <= 32 or not all(isinstance(x, str) and x and "\0" not in x and len(x) <= 8192 for x in argv):
        raise CheckError("INVALID_CATALOG", "Approved argv must be exact bounded strings")
    if not Path(argv[0]).is_absolute() or Path(argv[0]).resolve() != Path(sys.executable).resolve():
        raise CheckError("EXECUTABLE_UNVERIFIED", "This capability only verifies the current Python runtime")
    try:
        _validate_command(argv)
    except NativeCheckError as error:
        raise CheckError(error.code, "Approved argv does not match the verified runtime") from None
    if (type(check["timeout_seconds"]) is not int or not 1 <= check["timeout_seconds"] <= 600
            or type(check["output_bytes_cap"]) is not int or not 1 <= check["output_bytes_cap"] <= 1024 * 1024):
        raise CheckError("INVALID_CATALOG", "Timeout and output capture require finite bounds")
    if check["shell"] is not False or check["network"] != "disabled" or check["write_scope"] != "scratch":
        raise CheckError("UNSAFE_CHECK_POLICY", "No shell expansion, network or evidence writes")
    require_fields(context, {"binding", "candidate_commit", "snapshot_root", "scratch_root", "control_root", "evidence_root"}, "context")
    binding = context["binding"]
    require_fields(binding, {"project_id", "task_id", "spec_version", "attempt", "contract_hash"}, "binding")
    for name in ("project_id", "task_id"):
        if not isinstance(binding[name], str) or not IDENT.fullmatch(binding[name]):
            raise CheckError("INVALID_BINDING", "Invalid project/task identity")
    for name in ("spec_version", "attempt"):
        if type(binding[name]) is not int or binding[name] < 1:
            raise CheckError("INVALID_BINDING", "Task version/attempt must be positive integers")
    if not isinstance(binding["contract_hash"], str) or not SHA.fullmatch(binding["contract_hash"]):
        raise CheckError("INVALID_BINDING", "Canonical contract SHA required")
    candidate = context["candidate_commit"]
    if not isinstance(candidate, str) or not OID.fullmatch(candidate):
        raise CheckError("INVALID_CANDIDATE", "Full frozen candidate commit required")
    roots = {name: root_path(context[name], name, name != "evidence_root")
             for name in ("snapshot_root", "scratch_root", "control_root", "evidence_root")}
    items = list(roots.values())
    if any(a == b or a.is_relative_to(b) or b.is_relative_to(a) for i, a in enumerate(items) for b in items[i + 1:]):
        raise CheckError("OVERLAPPING_ROOTS", "Snapshot, scratch, control and evidence must be separate trees")
    if roots["evidence_root"].exists():
        raise CheckError("RECONCILIATION_REQUIRED", "Existing dispatch evidence cannot be reused")
    probe = inspect_git_input(str(roots["snapshot_root"]))
    if probe.get("clean") is not True or probe.get("head", "").lower() != candidate.lower() or Path(probe.get("root", "")).resolve() != roots["snapshot_root"]:
        raise CheckError("INPUT_DRIFT", "Snapshot is not the clean frozen candidate")
    return check, roots, probe, input_manifest(roots["snapshot_root"])


def run_check(check_id, catalog, context, *, before_dispatch, native_executor=execute_native):
    fence(before_dispatch)
    catalog, context = copy.deepcopy(catalog), copy.deepcopy(context)
    check, roots, probe, manifest = validate(check_id, catalog, context)
    evidence = roots["evidence_root"]
    intent = {"state": "DISPATCHED", "check_id": check_id, "binding": context["binding"],
              "candidate_commit": context["candidate_commit"], "input_hash": manifest["sha256"],
              "catalog_hash": canonical_hash(catalog), "check_hash": canonical_hash(check),
              "git_tree": probe.get("tree"), "schema_version": "native-orchestrator.check-intent/0.3"}
    native_policy = {"profile": "checks", "backend": "mxc", "network": "disabled", "shell": False,
                     "readonly_roots": [str(roots["snapshot_root"])], "writable_roots": [str(roots["scratch_root"])],
                     "denied_roots": [str(roots["control_root"]), str(evidence)],
                     "native_version_allowlist": sorted(VERIFIED_NATIVE_VERSIONS),
                     "inherited_environment_keys": list(WINDOWS_LAUNCH_ENV_KEYS),
                     "executable": str(Path(sys.executable).resolve()), "auth_copied": False, "model_turns": 0}
    intent.update(native_policy=native_policy, native_policy_hash=canonical_hash(native_policy),
                  input_manifest_ref=str(evidence / "input-manifest.json"), input_files=manifest["files"])
    fence(before_dispatch)
    evidence.mkdir(parents=True, exist_ok=False)
    atomic_json(evidence / "intent.json", intent, before_dispatch)
    atomic_json(evidence / "input-manifest.json", manifest, before_dispatch)
    status, code, result = "ERROR", "RECONCILIATION_REQUIRED", {}
    try:
        fence(before_dispatch)
        result = native_executor(list(check["argv"]), cwd=str(roots["snapshot_root"]),
            scratch_root=str(roots["scratch_root"]), readonly_roots=[str(roots["snapshot_root"])],
            denied_roots=[str(roots["control_root"]), str(evidence)], run_root=str(evidence / "native"),
            timeout_ms=check["timeout_seconds"] * 1000, output_bytes_cap=check["output_bytes_cap"],
            before_dispatch=before_dispatch)
        if (not isinstance(result, dict) or type(result.get("exitCode")) is not int
                or not isinstance(result.get("stdout"), str) or not isinstance(result.get("stderr"), str)):
            raise CheckError("INVALID_NATIVE_RESPONSE", "Native executor returned incomplete captured result")
        if result.get("permission_profile") != "checks" or not isinstance(result.get("profile_hash"), str) or not SHA.fullmatch(result["profile_hash"]):
            raise CheckError("CAPABILITY_UNVERIFIED", "Named native permission provenance required")
        if result.get("native_version") not in VERIFIED_NATIVE_VERSIONS:
            raise CheckError("NATIVE_VERSION_CHANGED", "Unverified native executor version")
        if result.get("output_complete", True) is not True:
            raise CheckError("OUTPUT_INCOMPLETE", "Native executor explicitly reported incomplete capture")
        # A capture at its cap may be truncated; it cannot be treated as complete check evidence.
        if any(len(result[name].encode("utf-8")) >= check["output_bytes_cap"] for name in ("stdout", "stderr")):
            raise CheckError("OUTPUT_INCOMPLETE", "Captured output reached its configured cap")
        status, code = ("PASS" if result["exitCode"] == 0 else "FAIL"), None
    except TimeoutError:
        code = "TIMEOUT"
    except Exception as error:
        code = getattr(error, "code", "EXECUTION_ERROR")
        if isinstance(error, NativeCheckError) and error.captured_result is not None:
            result = error.captured_result
    # Even a failed or uncertain launch must leave a before/after input check.
    input_unchanged = False
    try:
        after_probe = inspect_git_input(str(roots["snapshot_root"]))
        input_unchanged = after_probe == probe and input_manifest(roots["snapshot_root"]) == manifest
        if not input_unchanged:
            status, code = "ERROR", "INPUT_DRIFT"
    except Exception:
        status, code = "ERROR", "INPUT_VERIFICATION_FAILED"
    outputs = {}
    output_complete = bool(isinstance(result, dict) and result and isinstance(result.get("stdout"), str)
                           and isinstance(result.get("stderr"), str) and result.get("output_complete", True))
    for name in ("stdout", "stderr"):
        value = result.get(name, "") if isinstance(result, dict) else ""
        raw = value.encode("utf-8", errors="replace") if isinstance(value, str) else b""
        if len(raw) >= check["output_bytes_cap"]:
            output_complete = False
        if len(raw) > check["output_bytes_cap"]:
            raw = raw[:check["output_bytes_cap"]]
            status, code, output_complete = "ERROR", "OUTPUT_INCOMPLETE", False
        fence(before_dispatch)
        path = evidence / (name + ".txt")
        with path.open("xb") as stream:
            stream.write(raw); stream.flush(); os.fsync(stream.fileno())
        outputs[name + "_ref"] = str(path)
        outputs[name + "_sha256"] = hashlib.sha256(raw).hexdigest()
        outputs[name + "_bytes"] = len(raw)
    receipt = {"status": status, "check_id": check_id, "exit_code": result.get("exitCode") if isinstance(result, dict) else None,
               "code": code, "input_hash": manifest["sha256"], "catalog_hash": intent["catalog_hash"],
               "candidate_commit": context["candidate_commit"], "input_unchanged": input_unchanged,
               "output_complete": output_complete, "check_hash": intent["check_hash"],
               "native_policy_hash": intent["native_policy_hash"],
               "native_version": result.get("native_version") if isinstance(result, dict) else None,
               "permission_profile": result.get("permission_profile") if isinstance(result, dict) else None,
               "profile_hash": result.get("profile_hash") if isinstance(result, dict) else None,
               "environment_hash": result.get("environment_hash") if isinstance(result, dict) else None,
               "evidence_ref": str(evidence / "receipt.json"), **outputs}
    if len(json.dumps(receipt, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > 8192:
        raise CheckError("RESPONSE_LIMIT", "Check receipt exceeds business reply budget")
    atomic_json(evidence / "receipt.json", receipt, before_dispatch)
    atomic_json(evidence / "intent.json", {**intent, "state": "COMPLETED" if status in ("PASS", "FAIL") else "NEEDS_RECONCILIATION", "outcome": status, "code": code}, before_dispatch)
    return receipt
