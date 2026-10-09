"""Fail-closed adapter for the verified native checks permission profile."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import sys
from pathlib import Path
from typing import Callable, Sequence

from native_rpc import Rpc, RpcError


VERIFIED_NATIVE_VERSIONS = frozenset({"0.162.0-alpha.2"})
_VERSION_RE = re.compile(r"(?<![0-9A-Za-z.+-])([0-9]+\.[0-9]+\.[0-9]+-[0-9A-Za-z.-]+)(?![0-9A-Za-z.+-])")
_MAX_TIMEOUT_MS = 30 * 60 * 1000
_MAX_OUTPUT_BYTES = 1024 * 1024
_MAX_ARG_COUNT = 128
_MAX_ARG_BYTES = 1024 * 1024
_FILE_ATTRIBUTE_REPARSE_POINT = 0x400
WINDOWS_LAUNCH_ENV_KEYS = (
    "PATH", "PATHEXT", "COMSPEC", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE",
    "USERNAME", "USERDOMAIN", "USERPROFILE", "HOMEDRIVE", "HOMEPATH",
    "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "PROGRAMDATA",
    "LOCALAPPDATA", "APPDATA", "PUBLIC",
)


class NativeCheckError(ValueError):
    """A stable, non-sensitive failure code for native check execution."""

    def __init__(self, code: str, captured_result: dict | None = None):
        self.code = code
        self.captured_result = captured_result
        super().__init__(code)


def _fail(code: str) -> None:
    raise NativeCheckError(code)


def _fence(callback: Callable[[], object]) -> None:
    try:
        accepted = callback()
    except Exception:
        _fail("DISPATCH_FENCE")
    if accepted is not True:
        _fail("DISPATCH_FENCE")


def _path_value(value: object, name: str) -> Path:
    try:
        raw_value = os.fspath(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        _fail("INVALID_PATH")
    if not isinstance(raw_value, str) or not raw_value or "\x00" in raw_value:
        _fail("INVALID_PATH")
    try:
        raw = Path(raw_value)
    except (OSError, ValueError):
        _fail("INVALID_PATH")
    if not raw.is_absolute() or ".." in raw.parts:
        _fail("INVALID_PATH")
    try:
        normalized = Path(os.path.abspath(str(raw)))
    except (OSError, ValueError):
        _fail("INVALID_PATH")
    if normalized.anchor in ("", str(normalized)):
        _fail("INVALID_PATH")
    return normalized


def _is_reparse_point(path: Path) -> bool:
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    if getattr(info, "st_file_attributes", 0) & _FILE_ATTRIBUTE_REPARSE_POINT:
        return True
    is_junction = getattr(os.path, "isjunction", None)
    if is_junction is not None:
        try:
            return bool(is_junction(path))
        except OSError:
            return True
    return False


def _check_components(path: Path, *, allow_missing_leaf: bool = False) -> None:
    chain = list(reversed((path, *path.parents)))
    for component in chain:
        try:
            os.lstat(component)
        except FileNotFoundError:
            if allow_missing_leaf and component == path:
                continue
            _fail("INVALID_PATH")
        except OSError:
            _fail("INVALID_PATH")
        if _is_reparse_point(component):
            _fail("SYMLINK_PATH")


def _existing_directory(value: object, name: str) -> Path:
    path = _path_value(value, name)
    _check_components(path)
    try:
        if not path.is_dir():
            _fail("INVALID_PATH")
    except OSError:
        _fail("INVALID_PATH")
    return path


def _fresh_run_root(value: object) -> Path:
    path = _path_value(value, "run_root")
    _check_components(path, allow_missing_leaf=True)
    try:
        if os.path.lexists(path):
            _fail("RUN_ROOT_NOT_FRESH")
        if not path.parent.is_dir():
            _fail("INVALID_PATH")
    except OSError:
        _fail("INVALID_PATH")
    return path


def _key(path: Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _contains(parent: Path, child: Path) -> bool:
    try:
        return os.path.commonpath((_key(parent), _key(child))) == _key(parent)
    except (OSError, ValueError):
        return False


def _overlap(first: Path, second: Path) -> bool:
    return _contains(first, second) or _contains(second, first)


def _path_list(values: object, name: str, *, required: bool) -> tuple[Path, ...]:
    if isinstance(values, (str, bytes, os.PathLike)) or not isinstance(values, (tuple, list)):
        _fail("INVALID_PATH")
    if required and not values:
        _fail("INVALID_PATH")
    paths = tuple(_existing_directory(value, name) for value in values)
    keys = [_key(path) for path in paths]
    if len(set(keys)) != len(keys):
        _fail("OVERLAPPING_PATHS")
    for index, path in enumerate(paths):
        if any(_overlap(path, other) for other in paths[index + 1 :]):
            _fail("OVERLAPPING_PATHS")
    return paths


def _validate_layout(
    cwd: object,
    scratch_root: object,
    readonly_roots: object,
    denied_roots: object,
    run_root: object,
) -> tuple[Path, Path, tuple[Path, ...], tuple[Path, ...], Path]:
    working = _existing_directory(cwd, "cwd")
    scratch = _existing_directory(scratch_root, "scratch_root")
    readable = _path_list(readonly_roots, "readonly_roots", required=True)
    denied = _path_list(denied_roots, "denied_roots", required=False)
    fresh = _fresh_run_root(run_root)

    if not any(_contains(root, working) for root in readable):
        _fail("CWD_NOT_READONLY")
    if _overlap(working, scratch):
        _fail("OVERLAPPING_PATHS")
    for root in readable:
        if _overlap(root, scratch):
            _fail("OVERLAPPING_PATHS")
        if any(_overlap(root, blocked) for blocked in denied):
            _fail("OVERLAPPING_PATHS")
    for blocked in denied:
        if _overlap(blocked, working) or _overlap(blocked, scratch):
            _fail("OVERLAPPING_PATHS")
    # The host's private home/logs may live inside a command-denied evidence tree.
    # They must never overlap a readable or writable command root.
    all_roots = (working, scratch, *readable)
    if any(_overlap(fresh, root) for root in all_roots):
        _fail("OVERLAPPING_PATHS")
    return working, scratch, readable, denied, fresh


def _validate_command(command: object) -> tuple[str, ...]:
    if isinstance(command, (str, bytes)) or not isinstance(command, (tuple, list)):
        _fail("INVALID_ARGV")
    if not command or len(command) > _MAX_ARG_COUNT:
        _fail("INVALID_ARGV")
    argv: list[str] = []
    total = 0
    for item in command:
        if not isinstance(item, str) or not item or "\x00" in item:
            _fail("INVALID_ARGV")
        size = len(item.encode("utf-8", errors="strict"))
        if size > _MAX_ARG_BYTES:
            _fail("INVALID_ARGV")
        total += size
        argv.append(item)
    if total > _MAX_ARG_BYTES:
        _fail("INVALID_ARGV")

    executable = _path_value(argv[0], "command[0]")
    current_python = _path_value(sys.executable, "python")
    if _key(executable) != _key(current_python):
        _fail("EXECUTABLE_UNVERIFIED")
    _check_components(executable)
    _check_components(current_python)
    try:
        if not executable.is_file():
            _fail("EXECUTABLE_UNVERIFIED")
    except OSError:
        _fail("EXECUTABLE_UNVERIFIED")
    if len(argv) < 2 or argv[1] != "-B":
        _fail("UNSUPPORTED_ARGV")
    forbidden_python_flags = {"-E", "-I", "--ignore-environment", "-Xpycache_prefix"}
    if any(arg in forbidden_python_flags or arg.startswith("-Xpycache_prefix=") for arg in argv[2:]):
        _fail("UNSUPPORTED_ARGV")
    return tuple(argv)


def _validate_limits(timeout_ms: object, output_bytes_cap: object) -> tuple[int, int]:
    if isinstance(timeout_ms, bool) or not isinstance(timeout_ms, int):
        _fail("INVALID_LIMIT")
    if not 1 <= timeout_ms <= _MAX_TIMEOUT_MS:
        _fail("INVALID_LIMIT")
    if isinstance(output_bytes_cap, bool) or not isinstance(output_bytes_cap, int):
        _fail("INVALID_LIMIT")
    if not 1 <= output_bytes_cap <= _MAX_OUTPUT_BYTES:
        _fail("INVALID_LIMIT")
    return timeout_ms, output_bytes_cap


def _native_executable() -> Path:
    path_value = os.environ.get("PATH", "")
    candidate = shutil.which("codex", path=path_value)
    if not candidate:
        _fail("NATIVE_UNAVAILABLE")
    path = _path_value(candidate, "native_executable")
    _check_components(path)
    if os.name != "nt" or path.name.casefold() != "codex.exe":
        _fail("UNSUPPORTED_NATIVE_EXECUTABLE")
    try:
        if not path.is_file():
            _fail("NATIVE_UNAVAILABLE")
    except OSError:
        _fail("NATIVE_UNAVAILABLE")
    return path


def _private_config(
    python_root: Path,
    readable: Sequence[Path],
    scratch: Path,
    denied: Sequence[Path],
) -> bytes:
    lines = [
        'approval_policy = "never"',
        'default_permissions = "checks"',
        'project_doc_max_bytes = 0',
        'web_search = "disabled"',
        "[features]",
        "memories = false",
        "multi_agent = false",
        "remote_plugin = false",
        "[memories]",
        "use_memories = false",
        "generate_memories = false",
        '[windows]',
        'sandbox = "mxc"',
        "[permissions.checks.filesystem]",
        '":minimal" = "read"',
        f"{json.dumps(str(python_root), ensure_ascii=False)} = \"read\"",
    ]
    lines.extend(f"{json.dumps(str(path), ensure_ascii=False)} = \"read\"" for path in readable)
    lines.append(f"{json.dumps(str(scratch), ensure_ascii=False)} = \"write\"")
    lines.extend(f"{json.dumps(str(path), ensure_ascii=False)} = \"deny\"" for path in denied)
    lines.extend(("[permissions.checks.network]", "enabled = false", ""))
    return "\n".join(lines).encode("utf-8")


def _build_environment(home: Path, scratch: Path) -> dict[str, str]:
    environment: dict[str, str] = {}
    # Preserve only OS process-launch variables; never copy credentials or app config.
    # OS directory variables grant no filesystem rights; the checks profile does.
    # Preserve the Windows startup context, not arbitrary inherited credentials.
    for key in WINDOWS_LAUNCH_ENV_KEYS:
        value = os.environ.get(key)
        if value:
            environment[key] = value
    environment.update(
        {
            "CODEX_HOME": str(home),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONIOENCODING": "utf-8",
            "PYTHONUNBUFFERED": "1",
            "TEMP": str(scratch),
            "TMP": str(scratch),
        }
    )
    if not all(environment.get(key) for key in ("SYSTEMROOT", "LOCALAPPDATA")):
        _fail("NATIVE_ENVIRONMENT_UNAVAILABLE")
    return environment


def _native_version(initialized: object) -> str:
    if not isinstance(initialized, dict):
        _fail("NATIVE_INIT_INVALID")
    user_agent = initialized.get("userAgent")
    if not isinstance(user_agent, str):
        _fail("NATIVE_VERSION_UNKNOWN")
    matches = _VERSION_RE.findall(user_agent)
    if len(matches) != 1 or matches[0] not in VERIFIED_NATIVE_VERSIONS:
        _fail("NATIVE_VERSION_UNVERIFIED")
    server_info = initialized.get("serverInfo")
    if isinstance(server_info, dict):
        reported = server_info.get("version")
        if reported is not None and reported != matches[0]:
            _fail("NATIVE_VERSION_MISMATCH")
    return matches[0]


def _verify_checks_profile(response: object) -> None:
    if not isinstance(response, dict):
        _fail("PROFILE_LIST_INVALID")
    profiles = response.get("data")
    if not isinstance(profiles, list) or response.get("nextCursor") not in (None, ""):
        _fail("PROFILE_LIST_INCOMPLETE")
    checks = [entry for entry in profiles if isinstance(entry, dict) and entry.get("id") == "checks"]
    if len(checks) != 1 or checks[0].get("allowed") is not True:
        _fail("CHECKS_PROFILE_UNAVAILABLE")


def _check_output(result: object, output_bytes_cap: int) -> tuple[int, str, str]:
    if not isinstance(result, dict):
        _fail("NATIVE_RESULT_INVALID")
    exit_code = result.get("exitCode")
    stdout = result.get("stdout")
    stderr = result.get("stderr")
    if isinstance(exit_code, bool) or not isinstance(exit_code, int):
        _fail("NATIVE_RESULT_INVALID")
    if not isinstance(stdout, str) or not isinstance(stderr, str):
        _fail("NATIVE_RESULT_INVALID")
    try:
        encoded = {"stdout": stdout.encode("utf-8", errors="strict"),
                   "stderr": stderr.encode("utf-8", errors="strict")}
    except UnicodeError:
        _fail("NATIVE_RESULT_INVALID")
    captured = {"exitCode": exit_code, "stdout": stdout, "stderr": stderr}
    incomplete = any(result.get(key) is True for key in
                     ("truncated", "outputTruncated", "isOutputTruncated", "stdoutTruncated", "stderrTruncated"))
    if incomplete or any(len(value) >= output_bytes_cap for value in encoded.values()):
        # Keep the bounded diagnostic even when it cannot prove check completion.
        for name, raw in encoded.items():
            captured[name] = raw[:output_bytes_cap].decode("utf-8", errors="ignore")
        captured["output_complete"] = False
        raise NativeCheckError("OUTPUT_INCOMPLETE", captured)
    if exit_code != 0 and any(line.startswith("MXC launcher:") for line in stderr.splitlines()):
        raise NativeCheckError("NATIVE_SANDBOX_START_FAILED", captured)
    # command/exec has no timeout discriminator; its timeout exit is reserved here.
    if exit_code == 124:
        raise NativeCheckError("COMMAND_TIMEOUT", captured)
    if (exit_code != 0 and "Traceback (most recent call last):" in stderr
            and re.search(r"(?m)^PermissionError:", stderr)):
        # Conservative for the verified Python runtime; never escalate permissions
        # or feed a sandbox denial into automatic quality-repair rounds.
        raise NativeCheckError("CHECK_PERMISSION_DENIED", captured)
    return exit_code, stdout, stderr


def execute_native(
    command,
    *,
    cwd,
    scratch_root,
    readonly_roots,
    denied_roots,
    run_root,
    timeout_ms,
    output_bytes_cap,
    before_dispatch,
) -> dict:
    """Run one trusted Python argv under the private, verified ``checks`` profile.

    The function intentionally has no ``env`` or shell parameter.  It never retries
    an RPC: once a native request may have been dispatched, any uncertain result is
    returned as an error for the caller to reconcile.
    """
    if os.name != "nt":
        _fail("UNSUPPORTED_PLATFORM")
    if not callable(before_dispatch):
        _fail("INVALID_DISPATCH_FENCE")

    argv = _validate_command(command)
    limit_ms, output_cap = _validate_limits(timeout_ms, output_bytes_cap)
    working, scratch, readable, denied, fresh = _validate_layout(
        cwd, scratch_root, readonly_roots, denied_roots, run_root
    )

    python_path = _path_value(sys.executable, "python")
    python_root = python_path.parent
    _check_components(python_root)
    if any(_overlap(python_root, path) for path in (scratch, *denied)):
        _fail("OVERLAPPING_PATHS")

    native = _native_executable()
    if _overlap(fresh, python_root) or _overlap(fresh, native.parent):
        _fail("OVERLAPPING_PATHS")
    home = fresh / "home"
    rpc_log = fresh / "native-rpc.jsonl"
    config = _private_config(python_root, readable, scratch, denied)
    profile_hash = hashlib.sha256(config).hexdigest()
    environment = _build_environment(home, scratch)
    environment_hash = hashlib.sha256(json.dumps(environment, sort_keys=True, ensure_ascii=False,
                                                  separators=(",", ":")).encode("utf-8")).hexdigest()

    # The trusted controller must approve before every filesystem mutation and
    # before every native protocol dispatch.
    _fence(before_dispatch)
    try:
        fresh.mkdir()
    except OSError:
        _fail("RUN_ROOT_NOT_FRESH")
    _check_components(fresh)

    _fence(before_dispatch)
    try:
        home.mkdir()
    except OSError:
        _fail("PRIVATE_HOME_CREATE_FAILED")
    _check_components(home)

    _fence(before_dispatch)
    try:
        config_path = home / "config.toml"
        with config_path.open("xb") as stream:
            stream.write(config)
    except OSError:
        _fail("PRIVATE_CONFIG_WRITE_FAILED")

    rpc = None
    stage = "native_start"
    try:
        _fence(before_dispatch)
        rpc = Rpc([str(native), "app-server"], str(fresh), environment, str(rpc_log))

        stage = "initialize"
        _fence(before_dispatch)
        initialized = rpc.call(
            "initialize",
            {"clientInfo": {"name": "native_check_exec", "version": "1"},
             "capabilities": {"experimentalApi": True}},
            timeout=15,
        )
        native_version = _native_version(initialized)

        stage = "initialized_notification"
        _fence(before_dispatch)
        rpc.notify("initialized")

        stage = "permission_profile_list"
        _fence(before_dispatch)
        profiles = rpc.call("permissionProfile/list", {"limit": 20}, timeout=15)
        _verify_checks_profile(profiles)

        stage = "command_exec"
        _fence(before_dispatch)
        native_result = rpc.call(
            "command/exec",
            {
                "command": list(argv),
                "cwd": str(working),
                "permissionProfile": "checks",
                "timeoutMs": limit_ms,
                "outputBytesCap": output_cap,
                "env": {
                    "PYTHONDONTWRITEBYTECODE": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUNBUFFERED": "1",
                    "TEMP": str(scratch),
                    "TMP": str(scratch),
                },
            },
            timeout=(limit_ms / 1000) + 15,
        )
        exit_code, stdout, stderr = _check_output(native_result, output_cap)
        return {
            "exitCode": exit_code,
            "stdout": stdout,
            "stderr": stderr,
            "native_version": native_version,
            "permission_profile": "checks",
            "profile_hash": profile_hash,
            "environment_hash": environment_hash,
        }
    except NativeCheckError as error:
        if error.captured_result is not None:
            error.captured_result.update(native_version=native_version, permission_profile="checks",
                                         profile_hash=profile_hash, environment_hash=environment_hash)
        raise
    except TimeoutError:
        _fail("COMMAND_TIMEOUT" if stage == "command_exec" else "NATIVE_TIMEOUT")
    except RpcError:
        _fail("NATIVE_RPC_ERROR")
    except OSError:
        _fail("NATIVE_TRANSPORT_ERROR")
    except Exception:
        _fail("NATIVE_UNKNOWN_ERROR")
    finally:
        if rpc is not None:
            try:
                rpc.close()
            except Exception:
                # A close failure cannot justify replaying a possibly dispatched check.
                pass

