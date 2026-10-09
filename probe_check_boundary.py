"""One-shot benign native execution probe. No auth, threads, turns or model calls."""
import argparse
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
from pathlib import Path
from native_rpc import Rpc
from native_check_exec import _build_environment

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    area = Path(args.output).resolve()
    if not area.is_relative_to(ROOT / ".runtime") or area.exists():
        raise ValueError("Use a new probe directory inside this checkout's .runtime")
    for name in ("home", "input", "scratch", "control"):
        (area / name).mkdir(parents=True)
    frozen = area / "input/frozen.txt"
    frozen.write_bytes(b"FROZEN_PROBE_INPUT\n")
    before = hashlib.sha256(frozen.read_bytes()).hexdigest()
    (area / "control/control.txt").write_bytes(b"BENIGN_CONTROL_FIXTURE\n")
    scratch = area / "scratch"
    python_root = Path(sys.executable).resolve().parent
    config = '\n'.join([
        'approval_policy = "never"', 'default_permissions = "checks"',
        'project_doc_max_bytes = 0', 'web_search = "disabled"',
        '[features]', 'memories = false', 'multi_agent = false', 'remote_plugin = false',
        '[memories]', 'use_memories = false', 'generate_memories = false',
        '[windows]', 'sandbox = "mxc"', '[permissions.checks.filesystem]',
        '":minimal" = "read"', json.dumps(str(python_root)) + ' = "read"',
        json.dumps(str(area / "input")) + ' = "read"',
        json.dumps(str(scratch)) + ' = "write"',
        json.dumps(str(area / "control")) + ' = "deny"',
        '[permissions.checks.network]', 'enabled = false', ''])
    (area / "home/config.toml").write_text(config, encoding="utf-8", newline="\n")
    env = _build_environment(area / "home", scratch)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0)); listener.listen(4); listener.settimeout(0.5)
    port = listener.getsockname()[1]
    stopped = threading.Event()
    def serve():
        while not stopped.is_set():
            try:
                conn, _address = listener.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            with conn:
                conn.sendall(b"LOCAL_PROBE_READY")
    thread = threading.Thread(target=serve, daemon=True); thread.start()
    with socket.create_connection(("127.0.0.1", port), timeout=2) as baseline:
        assert baseline.recv(32) == b"LOCAL_PROBE_READY"
    script = '''import json,socket,sys
from pathlib import Path
root=Path(sys.argv[1]); port=int(sys.argv[2]); results={}
try:
    results['input_read']=(root/'input/frozen.txt').read_bytes()==b'FROZEN_PROBE_INPUT\\n'
except OSError as error:results['input_read_error']=type(error).__name__
for name,path in [('scratch_write',root/'scratch/allowed.txt'),('input_write',root/'input/forbidden.txt'),('control_write',root/'control/forbidden.txt')]:
    try:path.write_bytes(b'BENIGN_PROBE_WRITE\\n');results[name]=True
    except OSError as error:results[name]=False;results[name+'_error']=type(error).__name__
try:
    with socket.create_connection(('127.0.0.1',port),timeout=2) as conn:
        results['loopback_connected']=conn.recv(32)==b'LOCAL_PROBE_READY'
except OSError as error:results['loopback_connected']=False;results['loopback_error']=type(error).__name__
print(json.dumps(results))
'''
    command = [sys.executable, "-B", "-c", script, str(area), str(port)]
    report = {"status": "BLOCKED", "native_command_dispatches": 0, "model_turns": 0,
              "global_config_modified": False, "probe_root": str(area),
              "expected_profile": "checks", "host_loopback_baseline": "REACHABLE"}
    try:
        executable = shutil.which("codex")
        if not executable:
            raise ValueError("Installed native executable unavailable")
        with Rpc([executable, "app-server"], area / "input", env, area / "native-rpc.jsonl") as rpc:
            initialized = rpc.call("initialize", {"clientInfo": {"name": "frame004_probe", "version": "0.1"},
                                                    "capabilities": {"experimentalApi": True}})
            report["user_agent"] = initialized.get("userAgent")
            rpc.notify("initialized")
            try:
                report["profiles"] = rpc.call("permissionProfile/list", {"limit": 20})
            except Exception as error:
                report["profile_discovery_error"] = str(error)[:400]
            report["native_command_dispatches"] += 1
            result = rpc.call("command/exec", {"command": command, "cwd": str(area / "input"),
                             "permissionProfile": "checks", "timeoutMs": 10000, "outputBytesCap": 4096,
                             "env": {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
                                     "TEMP": str(scratch), "TMP": str(scratch)}}, timeout=20)
            report["command_result"] = result
            if result.get("exitCode") == 0:
                observed = json.loads(result["stdout"])
                report["observed"] = observed
                passed = (observed.get("input_read") is True and observed.get("scratch_write") is True
                          and observed.get("input_write") is False and observed.get("control_write") is False
                          and observed.get("loopback_connected") is False
                          and not (area / "input/forbidden.txt").exists()
                          and not (area / "control/forbidden.txt").exists())
                report["status"] = "NATIVE_EXEC_BOUNDARY_VERIFIED" if passed else "BOUNDARY_FAILED"
    except Exception as error:
        report["error"] = str(error)[:1000]
    finally:
        stopped.set(); listener.close(); thread.join(timeout=2)
    report["frozen_input_unchanged"] = hashlib.sha256(frozen.read_bytes()).hexdigest() == before
    (area / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("profiles", "command_result")}, ensure_ascii=True))
    raise SystemExit(report["status"] != "NATIVE_EXEC_BOUNDARY_VERIFIED")


if __name__ == "__main__":
    main()
