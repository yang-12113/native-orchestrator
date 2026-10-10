"""Exercise the frozen controller with a new text project and native Luna/max roles."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from native_orchestrator import codex_adapter
from native_orchestrator.orchestrator import Controller, atomic_json, digest, encode

ROOT = Path(__file__).resolve().parents[2]


def source_fingerprint():
    return {name: digest((ROOT / "src/native_orchestrator" / name).read_bytes()) for name in (
        "orchestrator.py", "codex_adapter.py", "native_rpc.py", "master.py", "mcp_server.py", "watch_project.py")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, help="New empty directory; never data-live")
    args = parser.parse_args()
    directory = Path(args.output).resolve()
    if directory.exists():
        raise ValueError("Self-check requires a new directory")
    if not directory.is_relative_to(ROOT / ".runtime"):
        raise ValueError("Self-check output must be inside this checkout's .runtime")
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True).strip():
        raise ValueError("Freeze a clean candidate commit before the native self-check")
    directory.mkdir(parents=True)
    codex_adapter.ROOT = directory
    before = source_fingerprint()
    expected = "FRAMEWORK_SELF_CHECK_OK\ncandidate_commit=" + commit + "\n"
    spec = {"title": "FRAME-001 frozen controller native self-check", "tasks": [{
        "id": "frozen_candidate", "objective": "Write verification.txt with the exact supplied value: " + encode(expected),
        "artifacts": ["verification.txt"],
        "checks": [{"id": "exact", "kind": "text", "path": "verification.txt", "equals": expected}]}]}
    config = {"executor": {"client": "codex", "model": "gpt-6-luna", "reasoning_effort": "max"},
              "reviewer": {"client": "codex", "model": "gpt-6-luna", "reasoning_effort": "max"},
              "max_project_turns": 2, "max_reworks": 0, "timeout_seconds": 240}
    atomic_json(directory / "input.json", {"candidate_commit": commit, "source_files": before,
                                           "spec": spec, "config": config})
    controller = Controller(directory / "data", config)
    project = controller.submit(spec, "FRAME-001-" + commit)["project_id"]
    print(encode({"stage": "STARTED", "project_id": project, "candidate_commit": commit}), flush=True)
    started = time.time()
    try:
        controller.run_one()
        task = controller.db.execute("SELECT * FROM tasks WHERE project_id=?", (project,)).fetchone()
        proof = controller.verify_accepted(task) if task["state"] == "ACCEPTED" else None
        task_dir = controller.task_dir(task)
        roles = {}
        for role in ("executor", "reviewer"):
            result_file = task_dir / (role + "-result.json")
            if result_file.is_file():
                result = json.loads(result_file.read_text(encoding="utf-8"))
                roles[role] = {key: result.get(key) for key in (
                    "session_id", "requested_model", "observed_model", "requested_effort",
                    "observed_effort", "native_version", "account_type", "usage")}
        passed = bool(proof and len(roles) == 2 and before == source_fingerprint()
                      and roles["executor"]["session_id"] != roles["reviewer"]["session_id"]
                      and all(r["requested_model"] == r["observed_model"] == "gpt-6-luna"
                              and r["requested_effort"] == r["observed_effort"] == "max" for r in roles.values()))
        report = {"evidence_status": "LIVE_VERIFIED" if passed else "BLOCKED", "passed": passed,
                  "candidate_commit": commit, "source_files": before, "spec_sha256": digest(spec),
                  "project_id": project, "state": task["state"], "error_class": task["error_class"],
                  "roles": roles, "acceptance_proof_hash": digest(proof) if proof else None,
                  "task_counts": controller.status(project)["task_counts"],
                  "elapsed_seconds": round(time.time() - started, 3), "evidence_root": str(directory),
                  "coverage": "native managed_text_v02 loop only; repo_patch engineering route remains DESIGN_ONLY"}
        atomic_json(directory / "report.json", report)
        print(encode(report), flush=True)
    finally:
        controller.db.close()
    raise SystemExit(not passed)


if __name__ == "__main__":
    main()
