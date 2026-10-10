"""Real subprocess/background/restart tests, with model replacements explicitly marked MOCK."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from native_orchestrator.orchestrator import Controller, ROOT, atomic_json, digest

def start(data, extra=None):
    log = open(data / "process.stdout.log", "ab")
    err = open(data / "process.stderr.log", "ab")
    process = subprocess.Popen([sys.executable, str(ROOT / "src/native_orchestrator/orchestrator.py"), "--data", str(data),
        "--config", str(ROOT / "config/config.example.json"), "run", *(extra or [])],
        cwd=ROOT, stdout=log, stderr=err,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    log.close()
    err.close()
    return process

def wait_for(check, timeout=20):
    deadline = time.monotonic()+timeout
    while time.monotonic()<deadline:
        if check():
            return True
        time.sleep(0.1)
    raise AssertionError("Process check timed out")

def main():
    data = ROOT / "data-process-tests" / uuid.uuid4().hex[:12]
    controller = Controller(data)
    spec = json.loads((ROOT / "examples/demo.project.json").read_text(encoding="utf-8"))
    project = controller.submit(spec, "background-no-observer")["project_id"]
    process = start(data)
    try:
        # No GUI/MCP/observer connection exists while the independent process runs.
        wait_for(lambda: all(t["state"] == "ACCEPTED" for t in controller.status(project)["tasks"]))
        before = controller.status(project)["calls"]
        controller.db.close()
        controller = Controller(data)
        assert controller.submit(spec, "background-no-observer")["project_id"] == project
        (data / "stop.request").write_text("graceful stop", encoding="utf-8")
        process.wait(timeout=10)
        assert process.returncode == 0
        # Only remove this own test marker, never another task's files/processes.
        (data / "stop.request").unlink()
        restarted = start(data, ["--idle-exit"])
        restarted.wait(timeout=10)
        assert controller.status(project)["calls"] == before
        first_hashes = [(p.relative_to(data).as_posix(), digest(p.read_bytes())) for p in data.rglob("facts.csv")]
        # Real crash: kill only the process created in this function, after it leases a delayed task.
        delayed = {"title": "crash", "tasks": [dict(spec["tasks"][0], id="delay", mock_delay_seconds=15)]}
        project2 = controller.submit(delayed, "crash-before-complete")["project_id"]
        crashed = start(data)
        wait_for(lambda: controller.status(project2)["tasks"][0]["state"] == "EXECUTING")
        crashed.kill()
        crashed.wait(timeout=10)
        with controller.db:
            # Test-only lease expiry, after checking the owned process is dead.
            controller.db.execute("UPDATE tasks SET lease_until=? WHERE project_id=? AND state='EXECUTING'", (time.time()-1, project2))
        assert controller.recover() == 1
        assert controller.status(project2)["tasks"][0]["state"] == "NEEDS_DECISION"
        assert not controller.run_one()
        atomic_json(ROOT / "evidence/process-tests.json", {"status": "MOCK_VERIFIED",
            "actual_process_lifecycle": True, "native_model_involved": False,
            "background_completed_without_observer": True, "graceful_stop": True,
            "completed_restart_no_extra_calls": True, "durable_duplicate_submission": True,
            "real_kill_in_test_scope": True, "ambiguous_dispatch_needs_decision_no_replay": True,
            "calls": before, "artifact_hashes": first_hashes, "data": str(data), "time": time.time()})
        print("Background/restart/crash checks passed; models were MOCK.")
    finally:
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        controller.db.close()

if __name__ == "__main__":
    main()
