import copy
import json
import tempfile
import time
import unittest
from pathlib import Path
from native_orchestrator.orchestrator import Controller, ROOT, MAX_REPLY, check_files, digest, manifest, safe_child, classify_error


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=ROOT / ".runtime")
        self.c = Controller(self.tmp.name)
        self.spec = json.loads((ROOT / "examples/demo.project.json").read_text(encoding="utf-8"))

    def tearDown(self):
        self.c.db.close()
        self.tmp.cleanup()

    def submit(self, spec=None, key="unique"):
        return self.c.submit(spec or self.spec, key)["project_id"]

    def run_all(self):
        for _ in range(20):
            if not self.c.run_one():
                break
        else:
            self.fail("unbounded loop")

    def test_independent_rework_and_dependencies(self):
        pid = self.submit()
        self.run_all()
        status = self.c.status(pid)
        self.assertEqual([x["state"] for x in status["tasks"]], ["ACCEPTED", "ACCEPTED"])
        self.assertEqual([x["attempt"] for x in status["tasks"]], [2, 1])
        self.assertEqual(status["calls"], {"executor": 3, "reviewer": 2})
        tasks = self.c.db.execute("SELECT session_id,reviewer_id FROM tasks").fetchall()
        self.assertTrue(all(t[0] != t[1] for t in tasks))

    def test_missing_file_cannot_be_completed(self):
        spec = copy.deepcopy(self.spec)
        spec["tasks"] = spec["tasks"][:1]
        spec["tasks"][0]["mock_result"] = {"artifacts": [], "note": "PASS all done"}
        pid = self.submit(spec)
        self.run_all()
        self.assertEqual(self.c.status(pid)["tasks"][0]["state"], "NEEDS_DECISION")
        self.assertEqual(self.c.status(pid)["tasks"][0]["attempt"], 3)

    def test_invalid_review_is_not_pass(self):
        spec = copy.deepcopy(self.spec)
        spec["tasks"] = spec["tasks"][:1]
        spec["tasks"][0]["mock_invalid_review"] = True
        pid = self.submit(spec)
        self.run_all()
        self.assertEqual(self.c.status(pid)["tasks"][0]["state"], "NEEDS_DECISION")
        self.assertEqual(self.c.status(pid)["tasks"][0]["error_class"], "INVALID_OUTPUT")

    def test_durable_idempotency_and_conflict(self):
        pid = self.submit()
        c2 = Controller(self.tmp.name)
        try:
            self.assertEqual(c2.submit(self.spec, "unique")["project_id"], pid)
            changed = copy.deepcopy(self.spec)
            changed["title"] = "changed"
            with self.assertRaises(ValueError):
                c2.submit(changed, "unique")
            self.assertEqual(c2.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 2)
        finally:
            c2.db.close()

    def test_concurrent_owners_cannot_claim_same_task(self):
        pid = self.submit()
        c2 = Controller(self.tmp.name)
        try:
            first = self.c.claim()
            self.assertIsNone(c2.claim())
            self.assertEqual(c2.recover(), 0)
            self.assertEqual(first["local_id"], "csv-demo")
        finally:
            c2.db.close()

    def test_crash_requires_reconciliation_no_blind_replay(self):
        pid = self.submit()
        task = self.c.claim()
        with self.c.db:
            self.c.db.execute("UPDATE tasks SET lease_until=? WHERE id=?", (time.time()-1, task["id"]))
        c2 = Controller(self.tmp.name)
        try:
            self.assertEqual(c2.recover(), 1)
            self.assertIsNone(c2.claim())
            self.assertEqual(c2.status(pid)["tasks"][0]["state"], "NEEDS_DECISION")
            self.assertEqual(c2.db.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 0)
        finally:
            c2.db.close()

    def test_terminal_state_survives_restart(self):
        pid = self.submit()
        self.run_all()
        c2 = Controller(self.tmp.name)
        try:
            self.assertEqual(c2.recover(), 0)
            self.assertFalse(c2.run_one())
            self.assertEqual(c2.status(pid)["calls"], {"executor": 3, "reviewer": 2})
        finally:
            c2.db.close()

    def test_large_output_never_enters_master_delta(self):
        canary = "WORKER_CANARY_6fb9650b"
        spec = copy.deepcopy(self.spec)
        spec["tasks"] = spec["tasks"][:1]
        good = spec["tasks"][0]["mock_result"][1]
        good["note"] = canary + "乱" * 55000
        spec["tasks"][0]["mock_result"] = good
        pid = self.submit(spec)
        self.run_all()
        raw = json.dumps(self.c.delta(pid), ensure_ascii=False).encode("utf-8")
        self.assertNotIn(canary.encode(), raw)
        self.assertLessEqual(len(raw), MAX_REPLY)
        self.assertNotIn(canary, json.dumps(self.c.resume_summary(pid)))
        logs = list(Path(self.tmp.name).rglob("executor-events.jsonl"))
        self.assertIn(canary, logs[0].read_text(encoding="utf-8"))
        self.assertGreater(logs[0].stat().st_size, 50000)

    def test_version_and_manifest_binding(self):
        self.submit()
        task = self.c.claim()
        mf = {"hash": "a" * 64}
        valid = {"task_id": task["id"], "spec_version": 1, "attempt": 1,
            "artifact_manifest_hash": mf["hash"], "verdict": "PASS", "checked_evidence_refs": ["a"], "findings": []}
        self.c.validate_review(task, valid, mf, ["a"])
        for key, value in (("task_id", "wrong"), ("spec_version", 2), ("attempt", 2),
                           ("artifact_manifest_hash", "b" * 64), ("checked_evidence_refs", [])):
            bad = {**valid, key: value}
            with self.assertRaises(ValueError, msg=key):
                self.c.validate_review(task, bad, mf, ["a"])

    def test_actual_csv_reread_detects_change_and_duplicates(self):
        folder = Path(self.tmp.name) / "artifacts"
        folder.mkdir()
        file = folder / "facts.csv"
        file.write_text("name,count\n甲,2\n乙,3\n", encoding="utf-8")
        self.assertTrue(check_files(self.spec["tasks"][0], folder)["passed"])
        old = manifest(folder)["hash"]
        file.write_text("name,count\n甲,2\n甲,3\n", encoding="utf-8")
        self.assertFalse(check_files(self.spec["tasks"][0], folder)["passed"])
        self.assertNotEqual(old, manifest(folder)["hash"])

    def test_accepted_artifact_tampering_invalidates_state(self):
        pid = self.submit()
        self.run_all()
        task = self.c.db.execute("SELECT * FROM tasks WHERE local_id='csv-demo'").fetchone()
        (self.c.task_dir(task) / "artifacts/facts.csv").write_text("tampered", encoding="utf-8")
        self.assertEqual(self.c.audit_accepted(pid), 2)
        states = {task["local_id"]: task["state"] for task in self.c.status(pid)["tasks"]}
        self.assertNotEqual(states["csv-demo"], "ACCEPTED")
        self.assertNotEqual(states["next-stage"], "ACCEPTED")

    def test_project_turn_budget_is_enforced(self):
        self.c.config["max_project_turns"] = 1
        pid = self.submit()
        self.run_all()
        self.assertEqual(self.c.status(pid)["tasks"][0]["error_class"], "BUDGET_EXHAUSTED")
        self.assertEqual(self.c.status(pid)["calls"], {"executor": 1})

    def test_no_path_escape_or_unapproved_write(self):
        for path in ("../state.sqlite", "C:/Windows/x", "x:secret", "CON.txt", "a\\b", "a/../b", "a. "):
            with self.assertRaises(ValueError, msg=path):
                safe_child(self.tmp.name, path)
        self.submit()
        task = self.c.claim()
        with self.assertRaises(ValueError):
            self.c.materialize(task, {"artifacts": [{"path": "PROJECT_STATE.json", "content": "hacked"}], "note": "done"})

    def test_read_capability_and_source_scope(self):
        from native_orchestrator.public_sources import validate_url
        for args in ({"path":"../PROJECT_STATE.json"}, {"path":"spec.json","content":"mutate"}):
            with self.assertRaises(ValueError):
                Controller.read_review_file(self.tmp.name, {"tool":"read_review_file","arguments":args})
        for url in ("http://zcode.z.ai/x", "https://evil.example/", "https://user:pass@zcode.z.ai/", "https://127.0.0.1/x"):
            with self.assertRaises(ValueError):
                validate_url(url, ["zcode.z.ai"])
        validate_url("https://zcode.z.ai/cn/changelog", ["zcode.z.ai"])

    def test_plan_cycle_and_paid_route_rejected(self):
        spec = copy.deepcopy(self.spec)
        spec["tasks"][0]["depends_on"] = ["next-stage"]
        with self.assertRaises(ValueError):
            self.submit(spec)
        with self.assertRaises(ValueError):
            Controller(Path(self.tmp.name) / "new", {"executor": {"client": "api", "model": "paid"}, "reviewer": {"client": "mock", "model": "m"}})

    def test_duplicate_events_and_bounded_pagination(self):
        pid = self.submit()
        with self.c.db:
            for i in range(300):
                self.c.event(pid, pid, "EVENT_" + str(i))
            self.c.event(pid, pid, "EVENT_1")
        cursor, count = 0, 0
        while True:
            reply = self.c.delta(pid, cursor)
            self.assertLessEqual(len(json.dumps(reply, ensure_ascii=False).encode()), MAX_REPLY)
            self.assertGreater(reply["cursor"], cursor)
            cursor = reply["cursor"]
            count += len(reply["changes"])
            if not reply["has_more"]:
                break
        self.assertEqual(count, 301)

    def test_error_classification_and_resume(self):
        self.assertEqual(classify_error(TimeoutError("timeout")), "TIMEOUT_REQUIRES_RECONCILIATION")
        self.assertEqual(classify_error(RuntimeError("usage limit reached")), "QUOTA")
        self.assertEqual(classify_error(RuntimeError("MODEL_UNAVAILABLE: target")), "MODEL_UNAVAILABLE")
        pid = self.submit()
        self.run_all()
        summary = self.c.resume_summary(pid)
        self.assertEqual(summary["accepted_count"], 2)
        self.assertEqual(summary["next_tasks"], [])
        self.assertNotIn("logs", json.dumps(summary))
        tid = pid + ":csv-demo"
        page = self.c.query_evidence(tid, "review")
        self.assertLessEqual(len(page["excerpt"].encode("utf-8")), 2048)
        with self.assertRaises(ValueError):
            self.c.query_evidence(tid, "executor-events")


if __name__ == "__main__":
    (ROOT / ".runtime").mkdir(exist_ok=True)
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(ControllerTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    (ROOT / "evidence/mock-tests.json").write_text(json.dumps({"mode": "MOCK_VERIFIED",
        "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
        "passed": result.wasSuccessful(), "timestamp": time.time()}, indent=2), encoding="utf-8")
    raise SystemExit(not result.wasSuccessful())
