"""Regression tests for the FRAME-001 controller hardening changes.

Every controller database and generated artifact is created under a fresh
TemporaryDirectory. CodexAdapter.run is replaced with a deterministic fake,
and subprocess entry points are guarded so no native service or model can run.
"""
import hashlib
import errno
import json
import os
import sqlite3
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

import orchestrator
from master import notify_master
from orchestrator import ARTIFACT_SCHEMA, Controller, MAX_REPLY, encode

ROOT = Path(__file__).resolve().parent
FAKE_LOCK = threading.Lock()
FAKE_CALLS = []
FAKE_STATE = {}

MOCK_CONFIG = {
    "executor": {"client": "mock", "model": "mock-executor"},
    "reviewer": {"client": "mock", "model": "mock-reviewer"},
}
FAKE_CODEX_CONFIG = {
    "executor": {"client": "codex", "model": "fake-executor"},
    "reviewer": {"client": "codex", "model": "fake-reviewer"},
}


def _prompt_payload(prompt):
    candidate = prompt.rpartition("\n")[2]
    try:
        return json.loads(candidate)
    except (TypeError, ValueError):
        try:
            return json.loads(prompt)
        except (TypeError, ValueError):
            return {}


def _read_paths(directory, meta):
    listed = meta.get("read_hashes") or meta.get("evidence_hashes") or meta.get("evidence_files")
    if isinstance(listed, dict):
        paths = list(listed)
    elif isinstance(listed, list):
        paths = [item["path"] if isinstance(item, dict) else item for item in listed]
    else:
        paths = ["spec.json", "checks.json"]
        if (directory / "independent-sources.json").is_file():
            paths.append("independent-sources.json")
        artifacts = directory / "artifacts"
        if artifacts.is_dir():
            paths.extend("artifacts/" + path.relative_to(artifacts).as_posix()
                         for path in artifacts.rglob("*") if path.is_file())
    return list(dict.fromkeys(paths))


def _mutate_file(path):
    path = Path(path)
    if path.suffix.lower() == ".json":
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            value = {}
        if isinstance(value, dict):
            value["_test_tampered_after_binding"] = True
        else:
            value = {"_test_tampered_after_binding": True}
        path.write_text(encode(value), encoding="utf-8")
    else:
        path.write_text("tampered after evidence binding", encoding="utf-8")


def _receipt_from_result(result):
    if not isinstance(result, dict):
        return None
    structured = result.get("structuredContent")
    if isinstance(structured, dict) and {"path", "sha256"} <= set(structured):
        return structured
    blocks = result.get("contentItems") or result.get("content") or []
    for block in blocks:
        text = block.get("text") if isinstance(block, dict) else None
        if not isinstance(text, str):
            continue
        try:
            value = json.loads(text)
        except ValueError:
            continue
        if isinstance(value, dict) and {"path", "sha256"} <= set(value):
            return value
    return None


def _review_value(name, schema, meta, receipts):
    if name in meta:
        return meta[name]
    if name == "verdict":
        return "PASS"
    if name == "checked_evidence_refs":
        return meta.get("evidence_refs", [])
    if name == "findings":
        return []
    if name in ("read_receipts", "evidence_receipts", "checked_files"):
        return receipts
    prop = schema.get("properties", {}).get(name, {})
    if "enum" in prop:
        values = prop["enum"]
        return "PASS" if "PASS" in values else values[0]
    kind = prop.get("type")
    return {"string": "fake-bound-value", "integer": 1, "number": 1,
            "boolean": False, "array": [], "object": {}}.get(kind)


def fake_adapter_run(self, role, model, prompt, cwd, log, schema=None,
                     timeout=180, on_session=None, **options):
    """Deterministic fake for the native adapter; never starts a subprocess."""
    cwd = Path(cwd)
    sid = "fake-" + role + "-" + uuid.uuid4().hex[:10]
    payload = _prompt_payload(prompt)
    task_id = payload.get("task_id") if isinstance(payload, dict) else None
    attempt = payload.get("attempt") if isinstance(payload, dict) else None
    if role == "reviewer":
        try:
            meta = json.loads((cwd / "review-input.json").read_text(encoding="utf-8"))
        except OSError:
            meta = payload if isinstance(payload, dict) else {}
        task_id, attempt = meta.get("task_id", task_id), meta.get("attempt", attempt)
    if role == "master" and isinstance(payload, dict):
        task_id = payload.get("project_id", task_id)
    with FAKE_LOCK:
        FAKE_CALLS.append({"role": role, "model": model, "task_id": task_id, "attempt": attempt})
    if on_session:
        on_session(sid)

    if role == "executor":
        if FAKE_STATE.get("block_attempt") == attempt:
            FAKE_STATE["entered"].set()
            if not FAKE_STATE["release"].wait(15):
                raise TimeoutError("test gate timed out")
        if FAKE_STATE.get("tamper_executor_spec"):
            _mutate_file(cwd / "spec.json")
        if FAKE_STATE.get("capture_dependency") and isinstance(payload, dict):
            receipts = payload.get("specification", {}).get("controller_dependency_receipts", [])
            if receipts:
                FAKE_STATE["captured_dependency"] = receipts[0]
        if not isinstance(payload, dict):
            payload = {}
        artifacts = payload.get("specification", {}).get("artifacts", ["out.txt"])
        text = encode({"artifacts": [{"path": artifacts[0], "content": "ok"}], "note": "fake adapter"})
        with FAKE_LOCK:
            FAKE_STATE.setdefault("executor_calls", []).append({"task_id": task_id, "attempt": attempt})
        return {"session_id": sid, "requested_model": model, "observed_model": model,
                "text": text, "usage": {"input_tokens": 1}}

    if role == "reviewer":
        meta = meta if "meta" in locals() else {}
        paths = _read_paths(cwd, meta)
        snapshot = {}
        for name in paths:
            file = cwd / name
            if file.is_file():
                snapshot[name] = hashlib.sha256(file.read_bytes()).hexdigest()
        mutate = FAKE_STATE.get("mutate_path")
        if mutate:
            _mutate_file(cwd / mutate)
        receipts = {}
        tool_handler = options.get("tool_handler")
        if tool_handler:
            for name in paths:
                result = tool_handler({"tool": "read_review_file", "arguments": {"path": name}})
                receipt = _receipt_from_result(result)
                if receipt:
                    receipts[name] = receipt
        FAKE_STATE["review_snapshot_hashes"] = snapshot
        FAKE_STATE["review_receipts"] = receipts
        properties = (schema or {}).get("properties", {})
        review = {name: _review_value(name, schema or {}, meta, receipts)
                  for name in (schema or {}).get("required", orchestrator.REVIEW_SCHEMA["required"])}
        review["verdict"] = "PASS"
        if "checked_evidence_refs" in review:
            review["checked_evidence_refs"] = meta.get("evidence_refs", [])
        if "findings" in review:
            review["findings"] = []
        return {"session_id": sid, "requested_model": model, "observed_model": model,
                "text": encode(review), "usage": {"input_tokens": 1}}

    if role == "master":
        version = payload.get("state_version", FAKE_STATE.get("state_version", 1)) if isinstance(payload, dict) else 1
        response = {"state_version": version, "summary": "A task needs a decision.",
                    "decision_required": True, "next_action": "Review the blocked task."}
        return {"session_id": sid, "requested_model": model, "observed_model": model,
                "text": encode(response), "usage": {"input_tokens": 1}}

    raise AssertionError("Unexpected fake adapter role: " + str(role))


def _single_task(task_id="solo", artifact="out.txt", expected="ok", **extra):
    task = {"id": task_id, "objective": "write a small verified artifact", "artifacts": [artifact],
            "checks": [{"id": "exact", "kind": "text", "path": artifact, "equals": expected}]}
    task.update(extra)
    return {"title": "synthetic hardening test", "tasks": [task]}


class HardeningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapter_patch = patch.object(orchestrator.CodexAdapter, "run", fake_adapter_run)
        cls.popen_patch = patch("subprocess.Popen", side_effect=AssertionError("native subprocess must not run in tests"))
        cls.subprocess_run_patch = patch("subprocess.run", side_effect=AssertionError("native subprocess must not run in tests"))
        cls.adapter_patch.start()
        cls.popen_patch.start()
        cls.subprocess_run_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.subprocess_run_patch.stop()
        cls.popen_patch.stop()
        cls.adapter_patch.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="controller-hardening-", dir=ROOT)
        self.root = Path(self.tmp.name)
        self.controllers = []
        global FAKE_STATE, FAKE_CALLS
        FAKE_STATE = {}
        with FAKE_LOCK:
            FAKE_CALLS = []

    def tearDown(self):
        for controller in self.controllers:
            try:
                controller.db.close()
            except Exception:
                pass
        self.tmp.cleanup()

    def controller(self, name="data", config=None):
        result = Controller(self.root / name, config or MOCK_CONFIG)
        self.controllers.append(result)
        return result

    def _create_project(self, controller, spec, key):
        return controller.submit(spec, key)["project_id"]

    def _make_accepted(self, name, spec=None, key=None):
        controller = self.controller(name, FAKE_CODEX_CONFIG)
        project = self._create_project(controller, spec or _single_task(), key or name)
        controller.run_one()
        task = controller.db.execute("SELECT * FROM tasks WHERE project_id=?", (project,)).fetchone()
        self.assertEqual(task["state"], "ACCEPTED")
        return controller, project, task

    def test_old_small_status_and_resume_defaults_return_all(self):
        c = self.controller()
        tasks = [
            {"id": "first", "objective": "first", "artifacts": ["a.txt"], "checks": [{"kind": "exists", "path": "a.txt"}]},
            {"id": "second", "objective": "second", "artifacts": ["b.txt"], "checks": [{"kind": "exists", "path": "b.txt"}]},
        ]
        project = self._create_project(c, {"title": "small", "tasks": tasks}, "small-defaults")
        status = c.status(project)
        self.assertEqual({task["local_id"] for task in status["tasks"]}, {"first", "second"})

        for local_id in ("first", "second"):
            task = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id=?", (project, local_id)).fetchone()
            with c.db:
                c.decision(task, "SYNTHETIC_TEST")
        resume = c.resume_summary(project)
        self.assertEqual(len(resume["pending_decisions"]), 2)

    def test_100_task_status_pages_fit_reply_budget_and_cover_each_task_once(self):
        c = self.controller()
        tasks = [{"id": f"t{i:03d}_" + "x" * 58, "objective": "x", "artifacts": ["a.txt"],
                  "checks": [{"kind": "exists", "path": "a.txt"}]} for i in range(100)]
        project = self._create_project(c, {"title": "100 tasks", "tasks": tasks}, "status-pages")
        cursor, version, returned = 0, None, []
        for _ in range(20):
            page = c.status(project, cursor=cursor, limit=20, state_version=version)
            version = page["state_version"] if version is None else version
            self.assertLessEqual(len(encode(page).encode("utf-8")), MAX_REPLY)
            self.assertEqual(page["total_tasks"], 100)
            self.assertIn("next_cursor", page)
            self.assertIn("has_more", page)
            returned.extend(task["local_id"] for task in page["tasks"])
            next_cursor = page["next_cursor"]
            if page["has_more"]:
                self.assertNotEqual(next_cursor, cursor)
            cursor = next_cursor
            if not page["has_more"]:
                break
        else:
            self.fail("status pagination did not terminate")
        self.assertEqual(len(returned), 100)
        self.assertEqual(len(set(returned)), 100)
        self.assertEqual(set(returned), {task["id"] for task in tasks})

    def test_resume_pages_only_unresolved_decisions_and_rejects_stale_cursor(self):
        c = self.controller()
        tasks = [{"id": f"d{i:02d}", "objective": "decision test", "artifacts": [f"d{i:02d}.txt"],
                  "checks": [{"kind": "exists", "path": f"d{i:02d}.txt"}]} for i in range(14)]
        project = self._create_project(c, {"title": "decisions", "tasks": tasks}, "decision-pages")
        rows = c.db.execute("SELECT * FROM tasks WHERE project_id=? ORDER BY rowid", (project,)).fetchall()
        for row in rows:
            with c.db:
                c.decision(row, "SYNTHETIC_TEST")
        resolved_id = rows[0]["id"] + ":0"
        c.resolve(resolved_id, "cancel")

        default_page = c.resume_summary(project)
        self.assertEqual(len(default_page["pending_decisions"]), 10)
        self.assertTrue(default_page["has_more"])
        version = default_page["state_version"]
        cursor, seen = 0, []
        for _ in range(20):
            page = c.resume_summary(project, decision_cursor=cursor, limit=4, state_version=version)
            seen.extend(item["id"] for item in page["pending_decisions"])
            cursor = page["next_cursor"]
            if not page["has_more"]:
                break
        else:
            self.fail("resume decision pagination did not terminate")
        expected = {row[0] for row in c.db.execute("SELECT id FROM decisions WHERE project_id=? AND resolved=0", (project,))}
        self.assertEqual(set(seen), expected)
        self.assertEqual(len(seen), len(expected))
        self.assertNotIn(resolved_id, seen)

        pending = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id=?", (project, "d01")).fetchone()
        with c.db:
            c.decision(pending, "NEW_DECISION_AFTER_PAGE")
        with self.assertRaisesRegex(ValueError, "STALE_STATE_CURSOR"):
            c.resume_summary(project, decision_cursor=cursor, limit=4, state_version=version)

    def test_concurrent_project_budget_cap_one_allows_only_one_invocation(self):
        config = {**FAKE_CODEX_CONFIG, "max_project_turns": 1}
        seed = self.controller("budget", config)
        spec = {"title": "two calls", "tasks": [
            {"id": "a", "objective": "a", "artifacts": ["a.txt"], "checks": [{"kind": "exists", "path": "a.txt"}]},
            {"id": "b", "objective": "b", "artifacts": ["b.txt"], "checks": [{"kind": "exists", "path": "b.txt"}]},
        ]}
        project = self._create_project(seed, spec, "budget-race")
        seed.db.close()
        start = threading.Barrier(2)
        successful, rejected, thread_errors = [], [], []

        def invoke_worker():
            c = Controller(self.root / "budget", config)
            try:
                task = c.claim()
                self.assertIsNotNone(task)
                c.task_dir(task).mkdir(parents=True, exist_ok=True)
                payload = {"task_id": task["id"], "attempt": task["attempt"],
                           "specification": {"artifacts": [json.loads(task["spec"])["artifacts"][0]]}}
                start.wait(timeout=10)  # Both callers start immediately before invoke, outside any DB transaction.
                try:
                    c.invoke(task, "executor", encode(payload), c.data, ARTIFACT_SCHEMA)
                    successful.append(task["local_id"])
                except RuntimeError as error:
                    rejected.append(str(error))
            except Exception as error:
                thread_errors.append(repr(error))
            finally:
                c.db.close()

        threads = [threading.Thread(target=invoke_worker), threading.Thread(target=invoke_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(15)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(thread_errors), 0, thread_errors)
        self.assertEqual(len(successful), 1)
        self.assertEqual(len(rejected), 1)
        self.assertEqual(len([call for call in FAKE_CALLS if call["role"] == "executor"]), 1)
        observer = self.controller("budget", config)
        recorded = observer.db.execute("SELECT COUNT(*) FROM calls WHERE task_id LIKE ?", (project + ":%",)).fetchone()[0]
        self.assertLessEqual(recorded, 1)

    def test_late_stale_attempt_cannot_overwrite_accepted_retry_or_reopen_old_decision(self):
        seed = self.controller("stale", FAKE_CODEX_CONFIG)
        project = self._create_project(seed, _single_task(), "stale-attempt")
        seed.db.close()
        current = self.controller("stale", FAKE_CODEX_CONFIG)
        global FAKE_STATE
        FAKE_STATE = {"block_attempt": 1, "entered": threading.Event(), "release": threading.Event()}
        thread_errors = []

        def old_attempt():
            old = Controller(self.root / "stale", FAKE_CODEX_CONFIG)
            old.heartbeat = lambda task_id, done: done.wait()
            try:
                old.run_one()
            except Exception as error:
                thread_errors.append(repr(error))
            finally:
                old.db.close()

        thread = threading.Thread(target=old_attempt, daemon=True)
        thread.start()
        self.assertTrue(FAKE_STATE["entered"].wait(8), "attempt 1 did not reach the fake adapter")
        with current.db:
            current.db.execute("UPDATE tasks SET lease_until=? WHERE id=?",
                               (orchestrator.time.time() - 1, project + ":solo"))
        self.assertEqual(current.recover(), 1)
        decision = current.db.execute("SELECT id FROM decisions WHERE project_id=? AND resolved=0", (project,)).fetchone()
        self.assertIsNotNone(decision)
        current.resolve(decision["id"], "retry")
        self.assertTrue(current.run_one())
        self.assertEqual(current.status(project)["tasks"][0]["state"], "ACCEPTED")
        accepted_proof = current.db.execute(
            "SELECT acceptance_proof,acceptance_proof_hash FROM tasks WHERE id=?", (project + ":solo",)
        ).fetchone()
        FAKE_STATE["release"].set()
        thread.join(10)
        self.assertFalse(thread.is_alive())
        row = current.db.execute("SELECT state,attempt,error_class,owner FROM tasks WHERE id=?", (project + ":solo",)).fetchone()
        self.assertEqual(row["state"], "ACCEPTED")
        self.assertEqual(row["attempt"], 2)
        final_proof = current.db.execute(
            "SELECT acceptance_proof,acceptance_proof_hash FROM tasks WHERE id=?", (project + ":solo",)
        ).fetchone()
        self.assertEqual(tuple(final_proof), tuple(accepted_proof))
        self.assertEqual(current.db.execute("SELECT COUNT(*) FROM decisions WHERE project_id=? AND resolved=0", (project,)).fetchone()[0], 0)
        decisions = current.db.execute("SELECT id,resolved FROM decisions WHERE project_id=?", (project,)).fetchall()
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0]["resolved"], 1)
        self.assertEqual(thread_errors, [])

    def test_read_receipt_hashes_match_fixed_spec_checks_sources_and_artifact(self):
        global FAKE_STATE
        source = {"id": "fixture", "url": "https://example.test/source", "read_at": 123.0,
                  "response_sha256": "a" * 64, "required_terms_found": True,
                  "body_text": "fixture source", "evidence_type": "INDEPENDENT_HTTP_READ"}
        spec = _single_task(sources=[{"id": "fixture", "url": source["url"], "required_terms": ["fixture"]}])
        config = {**FAKE_CODEX_CONFIG, "allowed_source_hosts": ["example.test"]}
        c = self.controller("receipt-valid", config)
        project = self._create_project(c, spec, "receipt-valid")
        with patch("public_sources.fetch", return_value=[source]):
            c.run_one()
        self.assertEqual(c.status(project)["tasks"][0]["state"], "ACCEPTED")
        expected = FAKE_STATE["review_snapshot_hashes"]
        receipts = FAKE_STATE["review_receipts"]
        required = {"spec.json", "checks.json", "independent-sources.json", "artifacts/out.txt"}
        self.assertTrue(required <= set(expected))
        self.assertEqual(set(expected), set(receipts))
        for name in required:
            self.assertEqual(receipts[name]["sha256"], expected[name], name)

        for index, name in enumerate(sorted(required)):
            with self.subTest(mutated_evidence=name):
                damaged = self.controller("receipt-damaged-" + str(index), config)
                damaged_project = self._create_project(damaged, spec, "receipt-damaged-" + str(index))
                FAKE_STATE = {"mutate_path": name}
                with patch("public_sources.fetch", return_value=[source]):
                    damaged.run_one()
                self.assertNotEqual(damaged.status(damaged_project)["tasks"][0]["state"], "ACCEPTED", name)

    def test_accepted_proof_file_or_database_tampering_and_loss_invalidate_state(self):
        corruptions = ("proof-file-modified", "proof-file-missing", "database-proof-modified", "database-hash-modified")
        for index, corruption in enumerate(corruptions):
            with self.subTest(corruption=corruption):
                c, project, task = self._make_accepted("proof-" + str(index))
                self.assertIn("acceptance_proof", task.keys())
                self.assertIn("acceptance_proof_hash", task.keys())
                self.assertTrue(task["acceptance_proof"])
                self.assertTrue(task["acceptance_proof_hash"])
                proof_file = c.task_dir(task) / "acceptance.json"
                self.assertTrue(proof_file.is_file())
                if corruption == "proof-file-modified":
                    proof_file.write_text(encode({"verdict": "PASS", "forged": True}), encoding="utf-8")
                elif corruption == "proof-file-missing":
                    proof_file.unlink()
                elif corruption == "database-proof-modified":
                    with c.db:
                        c.db.execute("UPDATE tasks SET acceptance_proof=? WHERE id=?", ("{\"verdict\":\"PASS\"}", task["id"]))
                else:
                    with c.db:
                        c.db.execute("UPDATE tasks SET acceptance_proof_hash=? WHERE id=?", ("0" * 64, task["id"]))
                self.assertGreaterEqual(c.audit_accepted(project), 1)
                final = c.db.execute("SELECT state FROM tasks WHERE id=?", (task["id"],)).fetchone()
                self.assertNotEqual(final["state"], "ACCEPTED")

    def test_downstream_task_rejects_forged_predecessor_proof(self):
        c = self.controller("forged-dependency", FAKE_CODEX_CONFIG)
        spec = {"title": "proof dependency", "tasks": [
            {"id": "source", "objective": "verified source", "artifacts": ["source.txt"],
             "checks": [{"kind": "text", "path": "source.txt", "equals": "ok"}]},
            {"id": "child", "objective": "consume source", "artifacts": ["child.txt"], "depends_on": ["source"],
             "checks": [{"kind": "text", "path": "child.txt", "equals": "ok"}]},
        ]}
        project = self._create_project(c, spec, "forged-dependency")
        c.run_one()
        predecessor = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id='source'", (project,)).fetchone()
        self.assertEqual(predecessor["state"], "ACCEPTED")
        with c.db:
            c.db.execute("UPDATE tasks SET acceptance_proof=? WHERE id=?",
                          (encode({"task_id": predecessor["id"], "verdict": "PASS", "artifact_manifest_hash": "0" * 64}), predecessor["id"]))
        global FAKE_STATE
        FAKE_STATE = {"capture_dependency": True}
        c.run_one()
        states = {row["local_id"]: row["state"] for row in c.db.execute("SELECT local_id,state FROM tasks WHERE project_id=?", (project,))}
        self.assertNotEqual(states["source"], "ACCEPTED")
        self.assertNotEqual(states["child"], "ACCEPTED")
        self.assertNotIn("captured_dependency", FAKE_STATE)
        self.assertFalse(any(call["task_id"] == project + ":child" for call in FAKE_CALLS))

    def test_tampered_accepted_root_invalidates_all_accepted_descendants(self):
        c = self.controller("recursive-proof-audit", FAKE_CODEX_CONFIG)
        spec = {"title": "three-level proof chain", "tasks": [
            {"id": "root", "objective": "root evidence", "artifacts": ["root.txt"],
             "checks": [{"kind": "text", "path": "root.txt", "equals": "ok"}]},
            {"id": "middle", "objective": "middle evidence", "artifacts": ["middle.txt"], "depends_on": ["root"],
             "checks": [{"kind": "text", "path": "middle.txt", "equals": "ok"}]},
            {"id": "leaf", "objective": "leaf evidence", "artifacts": ["leaf.txt"], "depends_on": ["middle"],
             "checks": [{"kind": "text", "path": "leaf.txt", "equals": "ok"}]},
        ]}
        project = self._create_project(c, spec, "recursive-proof-audit")
        for _ in range(8):
            if not c.run_one():
                break
        states = {row["local_id"]: row["state"] for row in c.db.execute(
            "SELECT local_id,state FROM tasks WHERE project_id=?", (project,))}
        self.assertEqual(states, {"root": "ACCEPTED", "middle": "ACCEPTED", "leaf": "ACCEPTED"})
        root = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id='root'", (project,)).fetchone()
        (c.task_dir(root) / "artifacts/root.txt").write_text("changed root after acceptance", encoding="utf-8")
        self.assertEqual(c.audit_accepted(project), 3)
        states = {row["local_id"]: row["state"] for row in c.db.execute(
            "SELECT local_id,state FROM tasks WHERE project_id=?", (project,))}
        self.assertEqual(set(states), {"root", "middle", "leaf"})
        self.assertTrue(all(state != "ACCEPTED" for state in states.values()))

    def test_failed_program_check_skips_reviewer_call(self):
        c = self.controller("program-check", MOCK_CONFIG)
        spec = _single_task(mock_result={"artifacts": [{"path": "out.txt", "content": "wrong"}], "note": "fake"})
        project = self._create_project(c, spec, "program-check")
        c.run_one()
        calls = {row["role"]: row["n"] for row in c.db.execute(
            "SELECT role,COUNT(*) n FROM calls WHERE task_id LIKE ? GROUP BY role", (project + ":%",))}
        self.assertGreaterEqual(calls.get("executor", 0), 1)
        self.assertEqual(calls.get("reviewer", 0), 0)
        self.assertNotEqual(c.status(project)["tasks"][0]["state"], "ACCEPTED")

    def test_check_environment_error_skips_quality_retry_and_reviewer(self):
        c = self.controller("environment-error", MOCK_CONFIG)
        spec = _single_task(mock_result={"artifacts": [{"path": "out.txt", "content": "ok"}], "note": "fake"})
        project = self._create_project(c, spec, "environment-error")
        original_read = Path.read_bytes
        artifact_reads = 0

        def fail_during_check(path):
            nonlocal artifact_reads
            if path.name == "out.txt" and path.parent.name == "artifacts":
                artifact_reads += 1
                if artifact_reads == 2:
                    raise PermissionError(errno.EACCES, "isolated environment access failure", str(path))
            return original_read(path)

        with patch.object(Path, "read_bytes", new=fail_during_check):
            c.run_one()
        self.assertEqual(artifact_reads, 2)
        task = c.status(project)["tasks"][0]
        self.assertEqual(task["attempt"], 1)
        self.assertEqual(task["state"], "NEEDS_DECISION")
        self.assertEqual(task["error_class"], "CHECK_ENVIRONMENT_ERROR")
        calls = {row["role"]: row["n"] for row in c.db.execute(
            "SELECT role,COUNT(*) n FROM calls WHERE task_id LIKE ? GROUP BY role", (project + ":%",))}
        self.assertEqual(calls.get("executor", 0), 1)
        self.assertEqual(calls.get("reviewer", 0), 0)

    def test_repo_patch_kind_is_rejected_before_project_submission(self):
        c = self.controller("repo-patch-rejected", MOCK_CONFIG)
        with self.assertRaisesRegex(ValueError, "repo_patch"):
            c.submit(_single_task(task_kind="repo_patch"), "unsupported-repo-patch")
        self.assertEqual(c.db.execute("SELECT COUNT(*) FROM projects").fetchone()[0], 0)
        self.assertEqual(c.db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0], 0)
        self.assertEqual(c.db.execute("SELECT COUNT(*) FROM calls").fetchone()[0], 0)

    def test_decision_can_wake_master_while_independent_task_is_pending(self):
        config = {**MOCK_CONFIG, "master": {"client": "codex", "model": "gpt-6.1-sol"}}
        c = self.controller("master-wakeup", config)
        spec = {"title": "independent progress", "tasks": [
            {"id": "blocked", "objective": "needs a decision", "artifacts": ["x.txt"], "checks": [{"kind": "exists", "path": "x.txt"}]},
            {"id": "independent", "objective": "still progressing", "artifacts": ["y.txt"], "checks": [{"kind": "exists", "path": "y.txt"}]},
        ]}
        project = self._create_project(c, spec, "master-wakeup")
        blocked = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id='blocked'", (project,)).fetchone()
        with c.db:
            c.decision(blocked, "SYNTHETIC_BLOCK")
        result = notify_master(c, project)
        self.assertIsNotNone(result)
        self.assertEqual([call["role"] for call in FAKE_CALLS].count("master"), 1)
        self.assertIsNone(notify_master(c, project))
        self.assertEqual([call["role"] for call in FAKE_CALLS].count("master"), 1)
        states = {row["local_id"]: row["state"] for row in c.db.execute("SELECT local_id,state FROM tasks WHERE project_id=?", (project,))}
        self.assertEqual(states, {"blocked": "NEEDS_DECISION", "independent": "PENDING"})
        notice = c.db.execute("SELECT state FROM master_notices WHERE project_id=?", (project,)).fetchone()
        self.assertIsNotNone(notice)

    def test_master_turn_caps_suppress_extra_dispatch(self):
        for index, cap in enumerate(("project", "master")):
            with self.subTest(cap=cap):
                limits = {"max_project_turns": 0} if cap == "project" else {"max_master_turns": 0}
                config = {**MOCK_CONFIG, **limits, "master": {"client": "codex", "model": "gpt-6.1-sol"}}
                c = self.controller("master-budget-" + str(index), config)
                spec = _single_task(task_id="blocked")
                project = self._create_project(c, spec, "master-budget-" + str(index))
                task = c.db.execute("SELECT * FROM tasks WHERE project_id=?", (project,)).fetchone()
                with c.db:
                    c.decision(task, "SYNTHETIC_BLOCK")
                result = notify_master(c, project)
                self.assertEqual(result["master_wakeup"], "BUDGET_EXHAUSTED")
                self.assertEqual([call["role"] for call in FAKE_CALLS].count("master"), 0)
                self.assertEqual(c.db.execute(
                    "SELECT COUNT(*) FROM calls WHERE task_id=? AND role='master'", (project + ":master",)
                ).fetchone()[0], 0)
                notice = c.db.execute("SELECT state FROM master_notices WHERE project_id=?", (project,)).fetchone()
                self.assertEqual(notice["state"], "BUDGET_EXHAUSTED")

    def test_reentrant_submit_and_bounded_rollback_with_outer_transaction(self):
        c = self.controller("nested-rollback", MOCK_CONFIG)
        with self.assertRaisesRegex(RuntimeError, "abort outer transaction"):
            with c.immediate():
                self._create_project(c, _single_task(), "nested-submit")
                c.bounded({"probe": "nested"}, "nested_transaction_probe")
                raise RuntimeError("abort outer transaction")
        for table in ("projects", "tasks", "events", "reply_audit", "calls"):
            self.assertEqual(c.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0, table)

    def test_concurrent_notify_for_same_decision_dispatches_once(self):
        config = {**MOCK_CONFIG, "master": {"client": "codex", "model": "gpt-6.1-sol"}}
        seed = self.controller("notify-race", config)
        project = self._create_project(seed, _single_task(task_id="blocked"), "notify-race")
        task = seed.db.execute("SELECT * FROM tasks WHERE project_id=?", (project,)).fetchone()
        with seed.db:
            seed.decision(task, "SYNTHETIC_BLOCK")
        seed.db.close()

        start = threading.Barrier(2)
        init_lock = threading.Lock()
        results, errors = [], []

        def notify_worker():
            controller = None
            try:
                with init_lock:
                    controller = Controller(self.root / "notify-race", config)
                start.wait(timeout=10)  # Both notifications start together, before either writer transaction.
                results.append(notify_master(controller, project))
            except Exception as error:
                errors.append(repr(error))
            finally:
                if controller is not None:
                    controller.db.close()

        threads = [threading.Thread(target=notify_worker), threading.Thread(target=notify_worker)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(20)
        self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(errors, [])
        self.assertEqual(sum(result is not None for result in results), 1)
        self.assertEqual(sum(result is None for result in results), 1)
        self.assertEqual([call["role"] for call in FAKE_CALLS].count("master"), 1)

        observer = self.controller("notify-race", config)
        self.assertEqual(observer.db.execute(
            "SELECT COUNT(*) FROM calls WHERE task_id=? AND role='master'", (project + ":master",)
        ).fetchone()[0], 1)
        notices = observer.db.execute("SELECT state,COUNT(*) n FROM master_notices WHERE project_id=? GROUP BY state", (project,)).fetchall()
        self.assertEqual(sum(row["n"] for row in notices), 1)
        self.assertEqual(notices[0]["state"], "COMPLETED")

    def test_accepted_database_refs_must_match_fixed_proof_paths(self):
        spec = {"title": "dependency refs", "tasks": [
            {"id": "source", "objective": "verified source", "artifacts": ["source.txt"],
             "checks": [{"kind": "text", "path": "source.txt", "equals": "ok"}]},
            {"id": "child", "objective": "consume source", "artifacts": ["child.txt"], "depends_on": ["source"],
             "checks": [{"kind": "text", "path": "child.txt", "equals": "ok"}]},
        ]}
        for index, column in enumerate(("check_ref", "review_ref")):
            with self.subTest(damaged_pointer=column):
                c = self.controller("fixed-ref-" + str(index), FAKE_CODEX_CONFIG)
                project = self._create_project(c, spec, "fixed-ref-" + str(index))
                c.run_one()
                task = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id='source'", (project,)).fetchone()
                self.assertEqual(task["state"], "ACCEPTED")
                forged = c.data / ("forged-" + column + ".json")
                if column == "check_ref":
                    forged.write_text(encode({"passed": True, "checks": []}), encoding="utf-8")
                else:
                    forged.write_text(encode({"verdict": "PASS", "findings": []}), encoding="utf-8")
                with c.db:
                    c.db.execute("UPDATE tasks SET " + column + "=? WHERE id=?", (str(forged), task["id"]))
                current = c.db.execute("SELECT * FROM tasks WHERE id=?", (task["id"],)).fetchone()
                with self.assertRaises(ValueError):
                    c.verify_accepted(current)

                if column == "review_ref":
                    before = len(FAKE_CALLS)
                    original_read_text = Path.read_text

                    def refuse_forged_path(path, *args, **kwargs):
                        if path.resolve() == forged.resolve():
                            raise AssertionError("dependency must not consume the DB-supplied review_ref")
                        return original_read_text(path, *args, **kwargs)

                    with patch.object(Path, "read_text", new=refuse_forged_path):
                        c.run_one()
                    states = {row["local_id"]: row["state"] for row in c.db.execute(
                        "SELECT local_id,state FROM tasks WHERE project_id=?", (project,))}
                    self.assertNotEqual(states["source"], "ACCEPTED")
                    self.assertNotEqual(states["child"], "ACCEPTED")
                    self.assertEqual(len(FAKE_CALLS), before)

    def test_executor_stage_canonical_spec_rewrite_is_rejected_before_reviewer(self):
        c = self.controller("executor-spec-tamper", FAKE_CODEX_CONFIG)
        project = self._create_project(c, _single_task(), "executor-spec-tamper")
        global FAKE_STATE
        FAKE_STATE = {"tamper_executor_spec": True}
        c.run_one()
        task = c.status(project)["tasks"][0]
        self.assertEqual(task["attempt"], 1)
        self.assertNotEqual(task["state"], "ACCEPTED")
        calls = {row["role"]: row["n"] for row in c.db.execute(
            "SELECT role,COUNT(*) n FROM calls WHERE task_id LIKE ? GROUP BY role", (project + ":%",))}
        self.assertEqual(calls.get("executor", 0), 1)
        self.assertEqual(calls.get("reviewer", 0), 0)

    def test_acceptance_proof_binds_canonical_input_spec_projection(self):
        c = self.controller("canonical-spec-proof", FAKE_CODEX_CONFIG)
        spec = _single_task(task_id="canonical", mock_fixture_only="strip from model input")
        project = self._create_project(c, spec, "canonical-spec-proof")
        c.run_one()
        task = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id='canonical'", (project,)).fetchone()
        self.assertEqual(task["state"], "ACCEPTED")
        directory = c.task_dir(task)
        db_spec = json.loads(task["spec"])
        expected = {key: value for key, value in db_spec.items() if not key.startswith("mock_")}
        expected["controller_dependency_receipts"] = []
        canonical = json.loads((directory / "spec.json").read_text(encoding="utf-8"))
        proof = json.loads(task["acceptance_proof"])
        self.assertEqual(canonical, expected)
        self.assertEqual(proof["input_spec_sha256"], orchestrator.digest(expected))
        self.assertEqual(c.verify_accepted(task), proof)

    def test_dependency_uses_verified_snapshot_without_rereading_or_injecting_review(self):
        c = self.controller("dependency-snapshot", FAKE_CODEX_CONFIG)
        spec = {"title": "snapshot dependency", "tasks": [
            {"id": "source", "objective": "verified source", "artifacts": ["source.txt"],
             "checks": [{"kind": "text", "path": "source.txt", "equals": "ok"}]},
            {"id": "child", "objective": "consume verified source", "artifacts": ["child.txt"], "depends_on": ["source"],
             "checks": [{"kind": "text", "path": "child.txt", "equals": "ok"}]},
        ]}
        project = self._create_project(c, spec, "dependency-snapshot")
        c.run_one()
        source = c.db.execute("SELECT * FROM tasks WHERE project_id=? AND local_id='source'", (project,)).fetchone()
        self.assertEqual(source["state"], "ACCEPTED")
        review_path = c.task_dir(source) / "review.json"
        original_read_bytes = Path.read_bytes
        original_read_text = Path.read_text
        read_counts = {"bytes": 0, "text": 0}
        guard_active = False
        forbidden_reads = []
        forged_review = encode({"task_id": "forged-review", "attempt": 99, "verdict": "PASS"}).encode("utf-8")

        def counted_snapshot_read(path):
            nonlocal guard_active
            if path.resolve() == review_path.resolve():
                read_counts["bytes"] += 1
                if guard_active:
                    forbidden_reads.append("bytes")
                    return forged_review
            return original_read_bytes(path)

        def refuse_text_review(path, *args, **kwargs):
            if path.resolve() == review_path.resolve():
                read_counts["text"] += 1
                if guard_active:
                    forbidden_reads.append("text")
                    return forged_review.decode("utf-8")
            return original_read_text(path, *args, **kwargs)

        original_verify = c.verify_accepted

        def verify_with_guard(task, *args, **kwargs):
            nonlocal guard_active
            result = original_verify(task, *args, **kwargs)
            if task["id"] == source["id"] and kwargs.get("with_evidence"):
                guard_active = True
            return result

        original_invoke = c.invoke

        def invoke_with_guard(task, role, *args, **kwargs):
            nonlocal guard_active
            result = original_invoke(task, role, *args, **kwargs)
            if role == "reviewer":
                guard_active = False  # Permit the separate acceptance-time revalidation snapshot.
            return result

        global FAKE_STATE
        FAKE_STATE = {"capture_dependency": True}
        c.verify_accepted = verify_with_guard
        c.invoke = invoke_with_guard
        with patch.object(c, "audit_accepted", return_value=0), \
             patch.object(Path, "read_bytes", new=counted_snapshot_read), \
             patch.object(Path, "read_text", new=refuse_text_review):
            c.run_one()
        child = c.db.execute("SELECT state FROM tasks WHERE project_id=? AND local_id='child'", (project,)).fetchone()
        self.assertEqual(child["state"], "ACCEPTED")
        self.assertGreaterEqual(read_counts["bytes"], 1)
        self.assertLessEqual(read_counts["bytes"], 2)
        self.assertEqual(read_counts["text"], 0)
        self.assertEqual(forbidden_reads, [])
        receipt = FAKE_STATE["captured_dependency"]
        self.assertEqual(receipt["bound_independent_review"]["task_id"], source["id"])
        self.assertEqual(receipt["bound_independent_review"]["verdict"], "PASS")

    def test_legacy_database_preflight_is_read_only_and_preserves_accepted_state(self):
        data = self.root / "legacy-data"
        data.mkdir()
        database = data / "state.sqlite"
        connection = sqlite3.connect(database)
        try:
            connection.execute("CREATE TABLE tasks(id TEXT PRIMARY KEY, project_id TEXT, local_id TEXT, spec TEXT, "
                               "spec_version INTEGER, state TEXT, attempt INTEGER, manifest_hash TEXT, check_ref TEXT, review_ref TEXT)")
            connection.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?)",
                               ("legacy:persisted", "legacy", "persisted", "{}", 1, "ACCEPTED", 1, "old-manifest", "old-checks", "old-review"))
            connection.commit()
        finally:
            connection.close()
        before_bytes = database.read_bytes()
        observer = sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True)
        before_columns = tuple(row[1] for row in observer.execute("PRAGMA table_info(tasks)"))
        before_state = observer.execute("SELECT state FROM tasks WHERE id='legacy:persisted'").fetchone()[0]
        observer.close()
        with self.assertRaisesRegex(ValueError, "LEGACY_DATA_REQUIRES_EXPLICIT_MIGRATION"):
            Controller.assert_current_database(data)
        self.assertEqual(database.read_bytes(), before_bytes)
        observer = sqlite3.connect("file:" + str(database) + "?mode=ro", uri=True)
        after_columns = tuple(row[1] for row in observer.execute("PRAGMA table_info(tasks)"))
        after_state = observer.execute("SELECT state FROM tasks WHERE id='legacy:persisted'").fetchone()[0]
        observer.close()
        self.assertEqual(after_columns, before_columns)
        self.assertEqual(after_state, before_state)
        self.assertEqual(after_state, "ACCEPTED")

    def test_planning_attach_failure_rolls_back_project_and_success_counts_against_budgets(self):
        spec = _single_task(task_id="planned")
        invalid = self.controller("planning-failure", MOCK_CONFIG)
        with self.assertRaisesRegex(ValueError, "planning reservation identity"):
            invalid.submit(spec, "bad-planning-link", planning_id="planning-invalid")
        for table in ("projects", "tasks"):
            self.assertEqual(invalid.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[0], 0, table)
        self.assertEqual(invalid.db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)

        planning_id = "planning-" + "a" * 16
        project_cap = self.controller("planning-project-budget", {**MOCK_CONFIG, "max_project_turns": 1})
        project_cap.reserve_call(planning_id, planning_id + ":planning", "master", "gpt-6.1-sol")
        project = project_cap.submit(spec, "planning-project-budget", planning_id=planning_id)["project_id"]
        attached = project_cap.db.execute("SELECT task_id,role FROM calls WHERE task_id LIKE ?", (project + ":%",)).fetchall()
        self.assertEqual([tuple(row) for row in attached], [(project + ":planning", "master")])
        transferred_event = project_cap.db.execute("SELECT project_id,task_id FROM events WHERE kind LIKE 'CALL_RESERVED_%'").fetchone()
        self.assertEqual(tuple(transferred_event), (project, project + ":planning"))
        task = project_cap.claim()
        with self.assertRaisesRegex(RuntimeError, "BUDGET_EXHAUSTED"):
            project_cap.invoke(task, "executor", "must not dispatch", project_cap.data, ARTIFACT_SCHEMA)
        self.assertFalse(any(call["role"] == "executor" for call in FAKE_CALLS))

        master_id = "planning-" + "b" * 16
        master_config = {**MOCK_CONFIG, "max_project_turns": 10, "max_master_turns": 1,
                         "master": {"client": "codex", "model": "gpt-6.1-sol"}}
        master_cap = self.controller("planning-master-budget", master_config)
        master_cap.reserve_call(master_id, master_id + ":planning", "master", "gpt-6.1-sol")
        master_project = master_cap.submit(spec, "planning-master-budget", planning_id=master_id)["project_id"]
        blocked = master_cap.db.execute("SELECT * FROM tasks WHERE project_id=?", (master_project,)).fetchone()
        with master_cap.db:
            master_cap.decision(blocked, "SYNTHETIC_BLOCK")
        result = notify_master(master_cap, master_project)
        self.assertEqual(result["master_wakeup"], "BUDGET_EXHAUSTED")
        self.assertFalse(any(call["role"] == "master" for call in FAKE_CALLS))
        self.assertEqual(master_cap.db.execute("SELECT COUNT(*) FROM calls WHERE task_id=? AND role='master'",
                                               (master_project + ":master",)).fetchone()[0], 0)

    def test_master_call_reservation_invalidates_preexisting_pagination_version(self):
        config = {**MOCK_CONFIG, "master": {"client": "codex", "model": "gpt-6.1-sol"}}
        c = self.controller("master-version", config)
        project = self._create_project(c, _single_task(task_id="blocked"), "master-version")
        task = c.db.execute("SELECT * FROM tasks WHERE project_id=?", (project,)).fetchone()
        with c.db:
            c.decision(task, "SYNTHETIC_BLOCK")
        before = c.resume_summary(project, limit=10)
        result = notify_master(c, project)
        after = c.resume_summary(project, limit=10)
        self.assertIsNotNone(result)
        self.assertGreater(after["state_version"], before["state_version"])
        self.assertEqual(result["state_version"], after["state_version"])
        with self.assertRaisesRegex(ValueError, "STALE_STATE_CURSOR"):
            c.resume_summary(project, decision_cursor=0, limit=10, state_version=before["state_version"])

    def test_duplicate_submit_planning_attachment_advances_state_version(self):
        c = self.controller("planning-duplicate-version", MOCK_CONFIG)
        spec = _single_task(task_id="planned")
        project = self._create_project(c, spec, "duplicate-planning-key")
        before = c.status(project)
        planning_id = "planning-" + "c" * 16
        c.reserve_call(planning_id, planning_id + ":planning", "master", "gpt-6.1-sol")
        duplicate = c.submit(spec, "duplicate-planning-key", planning_id=planning_id)
        self.assertTrue(duplicate["duplicate"])
        self.assertEqual(duplicate["project_id"], project)
        after = c.status(project)
        self.assertGreater(after["state_version"], before["state_version"])
        attached = c.db.execute("SELECT project_id,task_id,kind FROM events WHERE project_id=? AND kind LIKE 'PLANNING_ATTACHED_%'",
                                (project,)).fetchall()
        self.assertEqual(len(attached), 1)
        self.assertEqual(attached[0]["task_id"], project + ":planning")
        with self.assertRaisesRegex(ValueError, "STALE_STATE_CURSOR"):
            c.status(project, cursor=0, limit=20, state_version=before["state_version"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
