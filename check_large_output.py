"""Retained 55k-character MOCK transcript evidence; no native inference."""
import json
import uuid
from pathlib import Path
from orchestrator import Controller, ROOT, encode, atomic_json, digest

if __name__ == "__main__":
    data = ROOT / "data-isolation-demo" / uuid.uuid4().hex[:10]
    c = Controller(data)
    marker = "WORKER_CANARY_6fb9650b"
    spec = {"title":"large-output-isolation", "tasks":[{"id":"large", "objective":"Produce an exact small file.",
        "artifacts":["ok.txt"], "checks":[{"id":"exact","kind":"text","path":"ok.txt","equals":"OK"}],
        "mock_result":{"artifacts":[{"path":"ok.txt","content":"OK"}], "note":marker+"乱"*55000}}]}
    project = c.submit(spec,"retained-large-output")["project_id"]
    while c.run_one():
        pass
    delta = c.delta(project)
    resume = c.resume_summary(project)
    atomic_json(ROOT / "evidence/isolation-delta.json",delta)
    log = next(data.rglob("executor-events.jsonl"))
    assert marker not in encode(delta) and marker not in encode(resume)
    assert log.stat().st_size > 50000 and marker in log.read_text(encoding="utf-8")
    atomic_json(ROOT / "evidence/large-output-tests.json", {"status":"MOCK_VERIFIED", "native_inference":False,
        "worker_output_characters":55000+len(marker), "raw_log_bytes":log.stat().st_size,
        "raw_log_sha256":digest(log.read_bytes()), "raw_log_ref":str(log.relative_to(ROOT)),
        "delta_bytes":len(encode(delta).encode()), "resume_bytes":len(encode(resume).encode()),
        "canary_in_default_master_reply":False, "reply_json_valid":True, "project_id":project})
    c.db.close()
    print("Retained 55k-character MOCK isolation evidence passed.")
