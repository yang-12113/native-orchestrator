"""Benign live FRAME-004 validation on the frozen calculator fixture only.

Creates a new evidence area, uses the native checks permission profile, and never
starts a model, copies authentication, changes global config, or retries a run.
"""
import argparse
import hashlib
import json
import os
import socket
import sys
import threading
from pathlib import Path
from unittest.mock import patch

from check_runner import CheckError, input_manifest, run_check
from execution_contract import inspect_git_input

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    area = Path(args.output).resolve()
    if not area.is_relative_to(ROOT / ".runtime") or area.exists():
        raise ValueError("Use a new validation directory inside this checkout's .runtime")
    accepted = json.loads((ROOT / ".runtime/frame-003-real/root-workspace-attempt2-report.json").read_text(encoding="utf-8"))
    descriptor = accepted["descriptor"]
    candidate = accepted["candidate"]["candidate_commit"]
    snapshot = Path(descriptor["workspace_root"]).resolve(strict=True)
    if not snapshot.is_relative_to(ROOT / ".runtime/frame-003-real/control/workspaces"):
        raise ValueError("Only the known frozen calculator fixture is approved")
    initial_manifest = input_manifest(snapshot)
    area.mkdir()
    report = {"status": "RUNNING", "candidate_commit": candidate, "model_turns": 0,
              "global_config_modified": False, "authentication_copied": False,
              "output_root": str(area), "cases": []}
    report["runner_candidate_commit"] = inspect_git_input(str(ROOT))["head"]
    code_files = ("check_runner.py", "native_check_exec.py", "native_rpc.py",
                  "execution_contract.py", "validate_check_runner.py")
    code_hashes = {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in code_files}
    report["runner_source_sha256"] = code_hashes

    def run_case(name, argv, expected_status, *, timeout=10, cap=4096, environment_missing=False):
        case = area / name
        for directory in (case, case / "scratch", case / "control", case / "outside"):
            directory.mkdir()
        (case / "control/canary.txt").write_bytes(b"HOST_CONTROL_CANARY\n")
        (case / "outside/canary.txt").write_bytes(b"HOST_OUTSIDE_CANARY\n")
        context = {"binding": descriptor["binding"], "candidate_commit": candidate,
                   "snapshot_root": str(snapshot), "scratch_root": str(case / "scratch"),
                   "control_root": str(case / "control"), "evidence_root": str(case / "evidence")}
        entry = {"argv": argv, "timeout_seconds": timeout, "output_bytes_cap": cap,
                 "write_scope": "scratch", "network": "disabled", "shell": False,
                 "verification": "VERIFIED", "evidence_sha256": "1" * 64}
        catalog = {name: entry}
        if environment_missing:
            with patch.dict(os.environ):
                os.environ.pop("LOCALAPPDATA", None)
                receipt = run_check(name, catalog, context, before_dispatch=lambda: True)
        else:
            receipt = run_check(name, catalog, context, before_dispatch=lambda: True)
        item = {"name": name, "expected": expected_status, "actual": receipt["status"],
                "code": receipt["code"], "exit_code": receipt["exit_code"],
                "input_unchanged": receipt["input_unchanged"], "receipt": receipt["evidence_ref"]}
        report["cases"].append(item)
        (area / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        if receipt["status"] != expected_status or receipt["input_unchanged"] is not True:
            raise AssertionError(item)
        return receipt, catalog, context

    try:
        run_case("unit", [sys.executable, "-B", "-m", "unittest", "-q"], "PASS")
        run_case("quality", [sys.executable, "-B", "-c", "import sys; print('KNOWN_QUALITY_FAILURE'); sys.exit(7)"], "FAIL")
        denied_file = area / "permission/control/canary.txt"
        permission, _, _ = run_case("permission", [sys.executable, "-B", "-c",
            "from pathlib import Path; import sys; Path(sys.argv[1]).write_bytes(b'BENIGN_WRITE')", str(denied_file)], "ERROR")
        assert permission["code"] == "CHECK_PERMISSION_DENIED"
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0)); listener.listen(4); listener.settimeout(0.25)
        port = listener.getsockname()[1]
        stopped = threading.Event()
        def serve():
            while not stopped.is_set():
                try:
                    connection, _ = listener.accept()
                except socket.timeout:
                    continue
                except OSError:
                    break
                with connection:
                    connection.sendall(b"LIVE_HOST_BASELINE")
        server = threading.Thread(target=serve, daemon=True); server.start()
        boundary_case = area / "boundary"
        script = '''import json,socket,sys
from pathlib import Path
root=Path.cwd(); case=Path(sys.argv[1]); port=int(sys.argv[2]); observed={}
observed['input_read']=bool((root/'calculator.py').read_bytes())
for name,path in [('scratch_write',case/'scratch/allowed.txt'),('input_write',root/'forbidden-frame004.txt'),('git_write',root/'.git'),('control_write',case/'control/forbidden.txt'),('evidence_write',case/'evidence/forbidden.txt'),('outside_write',case/'outside/forbidden.txt')]:
    try:
        with path.open('ab') as stream:stream.write(b'BENIGN_VALIDATION_WRITE\\n')
        observed[name]=True
    except OSError:observed[name]=False
for name,path in [('control_read',case/'control/canary.txt'),('evidence_read',case/'evidence/intent.json'),('outside_read',case/'outside/canary.txt')]:
    try:path.read_bytes();observed[name]=True
    except OSError:observed[name]=False
try:
    with socket.create_connection(('127.0.0.1',port),timeout=1) as connection:
        observed['network']=connection.recv(32)==b'LIVE_HOST_BASELINE'
except OSError:observed['network']=False
print(json.dumps(observed))
assert observed=={'input_read':True,'scratch_write':True,'input_write':False,'git_write':False,'control_write':False,'evidence_write':False,'outside_write':False,'control_read':False,'evidence_read':False,'outside_read':False,'network':False},observed
'''
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                assert connection.recv(32) == b"LIVE_HOST_BASELINE"
            boundary, _, _ = run_case("boundary", [sys.executable, "-B", "-c", script, str(boundary_case), str(port)], "PASS")
            report["boundary_observed"] = json.loads(Path(boundary["stdout_ref"]).read_text(encoding="utf-8"))
            report["host_loopback_baseline"] = "REACHABLE"
        finally:
            stopped.set(); listener.close(); server.join(timeout=1)
        timeout_receipt, catalog, context = run_case("timeout", [sys.executable, "-B", "-c", "import time; time.sleep(5)"], "ERROR", timeout=1)
        run_case("output", [sys.executable, "-B", "-c", "print('x'*4096)"], "ERROR", cap=128)
        missing, _, _ = run_case("environment", [sys.executable, "-B", "-c", "pass"], "ERROR", environment_missing=True)
        assert missing["code"] == "NATIVE_ENVIRONMENT_UNAVAILABLE"
        before = Path(timeout_receipt["evidence_ref"]).read_bytes()
        for name, check_id in (("unknown_id", "unapproved"), ("consumed_evidence", "timeout")):
            dispatched = []
            def forbidden_dispatch(*args, **kwargs):
                dispatched.append(True)
                raise AssertionError("Rejected request reached native dispatch")
            try:
                run_check(check_id, catalog, context, before_dispatch=lambda: True, native_executor=forbidden_dispatch)
            except CheckError as error:
                report["cases"].append({"name": name, "expected": "REJECTED", "actual": "REJECTED", "code": error.code})
            else:
                raise AssertionError("Unsafe request was accepted")
            assert not dispatched
        assert Path(timeout_receipt["evidence_ref"]).read_bytes() == before
        report["frozen_input_unchanged"] = input_manifest(snapshot) == initial_manifest
        assert report["frozen_input_unchanged"]
        report["runner_source_unchanged"] = all(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest
                                               for name, digest in code_hashes.items())
        assert report["runner_source_unchanged"]
        report["status"] = "NATIVE_CHECK_RUNNER_VERIFIED"
    except Exception as error:
        report["status"] = "VALIDATION_FAILED"
        report["error"] = str(error)[:1000]
    finally:
        dispatches = 0
        for log in area.glob("*/evidence/native/native-rpc.jsonl"):
            for line in log.read_text(encoding="utf-8").splitlines():
                event = json.loads(line)
                if event.get("direction") == "send" and event.get("message", {}).get("method") == "command/exec":
                    dispatches += 1
        report["native_command_dispatches"] = dispatches
        (area / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(json.dumps({"status": report["status"], "cases": report["cases"], "native_command_dispatches": report["native_command_dispatches"], "model_turns": 0}))
    raise SystemExit(report["status"] != "NATIVE_CHECK_RUNNER_VERIFIED")


if __name__ == "__main__":
    main()
