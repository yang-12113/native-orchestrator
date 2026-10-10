"""Protocol tests for CodexAdapter without auth access or native subprocesses."""
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

from native_orchestrator import codex_adapter
from native_orchestrator.codex_adapter import CodexAdapter
from native_orchestrator.native_rpc import RpcError

ROOT = Path(__file__).resolve().parents[1]


def selected_model(supported=("low", "medium", "high", "max")):
    return {
        "model": "gpt-6-luna",
        "defaultReasoningEffort": "low",
        "supportedReasoningEfforts": [{"reasoningEffort": value} for value in supported],
    }


class FakeRpc:
    def __init__(self, scenario):
        self.scenario = scenario
        self.events = queue.Queue()
        self.calls = []
        self.notifications = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def notify(self, method, params=None):
        self.notifications.append((method, params or {}))

    def call(self, method, params=None, timeout=30):
        params = params or {}
        self.calls.append((method, params))
        if method == "initialize":
            return {"userAgent": self.scenario.get("user_agent", "codex/0.162.0-alpha.2")}
        if method == "account/read":
            return {"account": {"type": "chatgpt"}}
        if method == "model/list":
            index = 0 if "cursor" not in params else 1
            return self.scenario["model_pages"][index]
        if method == "thread/start":
            model = self.scenario.get("started_model", params["model"])
            effort = self.scenario.get("started_effort", params["config"]["model_reasoning_effort"])
            return {"model": model, "reasoningEffort": effort, "thread": {"id": "fake-thread"}}
        if method == "turn/start":
            self.events.put({"method": "item/completed", "params": {
                "threadId": "fake-thread", "item": {"type": "agentMessage", "text": "fake protocol reply"}}})
            self.events.put({"method": "turn/completed", "params": {
                "threadId": "fake-thread", "turn": {"id": "fake-turn", "status": "completed"}}})
            return {"turn": {"id": "fake-turn"}}
        if method == "turn/interrupt":
            return {}
        raise AssertionError("Unexpected RPC method: " + method)

    def calls_for(self, method):
        return [params for name, params in self.calls if name == method]


def scenario(supported=("low", "medium", "high", "max"), **overrides):
    value = {
        "model_pages": [
            {"data": [{"model": "other-model", "defaultReasoningEffort": "low",
                       "supportedReasoningEfforts": [{"reasoningEffort": "low"}]}],
             "nextCursor": "models-page-2"},
            {"data": [selected_model(supported)], "nextCursor": None},
        ]
    }
    value.update(overrides)
    return value


class CodexProtocolTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.popen_patch = patch("subprocess.Popen", side_effect=AssertionError("native subprocess must not run in protocol tests"))
        cls.run_patch = patch("subprocess.run", side_effect=AssertionError("native subprocess must not run in protocol tests"))
        cls.popen_patch.start()
        cls.run_patch.start()

    @classmethod
    def tearDownClass(cls):
        cls.run_patch.stop()
        cls.popen_patch.stop()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="codex-protocol-", dir=ROOT)
        self.cwd = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_fake(self, fake_rpc, effort="max", model="gpt-6-luna"):
        with patch.object(codex_adapter, "private_environment", return_value={"CODEX_HOME": "FAKE_ONLY"}) as env_mock, \
             patch.object(codex_adapter, "Rpc", return_value=fake_rpc), \
             patch("native_orchestrator.codex_adapter.shutil.which", return_value="fake-codex-executable"):
            result = CodexAdapter().run("executor", model, "fake prompt", self.cwd, self.cwd / "rpc.jsonl",
                                        reasoning_effort=effort)
        env_mock.assert_called_once_with("executor")
        return result

    def test_max_effort_is_configured_for_thread_and_turn_and_model_is_found_on_next_page(self):
        fake = FakeRpc(scenario())
        result = self.run_fake(fake, effort="max")
        pages = fake.calls_for("model/list")
        self.assertEqual(len(pages), 2)
        self.assertEqual(pages[1]["cursor"], "models-page-2")
        thread = fake.calls_for("thread/start")[0]
        turn = fake.calls_for("turn/start")[0]
        self.assertEqual(thread["config"]["model_reasoning_effort"], "max")
        self.assertEqual(turn["effort"], "max")
        self.assertEqual(result["requested_effort"], "max")
        self.assertEqual(result["observed_effort"], "max")
        self.assertEqual(result["text"], "fake protocol reply")
        self.assertEqual(fake.notifications[0][0], "initialized")

    def test_unsupported_max_is_rejected_without_silent_downgrade(self):
        fake = FakeRpc(scenario(supported=("low", "medium")))
        with self.assertRaisesRegex(RpcError, "EFFORT_UNAVAILABLE"):
            self.run_fake(fake, effort="max")
        self.assertEqual(fake.calls_for("thread/start"), [])
        self.assertEqual(fake.calls_for("turn/start"), [])

    def test_server_effort_mismatch_is_rejected_before_turn_start(self):
        fake = FakeRpc(scenario(started_effort="low"))
        with self.assertRaisesRegex(RpcError, "EFFORT_MISMATCH"):
            self.run_fake(fake, effort="max")
        self.assertEqual(fake.calls_for("thread/start")[0]["config"]["model_reasoning_effort"], "max")
        self.assertEqual(fake.calls_for("turn/start"), [])

    def test_unvalidated_prerelease_native_version_is_rejected(self):
        fake = FakeRpc(scenario(user_agent="codex/0.162.0-alpha.3"))
        with self.assertRaisesRegex(RpcError, "NATIVE_VERSION_CHANGED"):
            self.run_fake(fake, effort="max")
        self.assertEqual([name for name, _ in fake.calls], ["initialize"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
