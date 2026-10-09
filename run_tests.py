"""Run regression suites in disposable directories without touching delivery evidence."""
import argparse
import json
import os
import platform
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    modules = [__import__(name) for name in (
        "test_controller", "test_native_adapters", "test_watch_project",
        "test_hardening", "test_codex_protocol", "test_execution_contract", "test_repo_workspace",
        "test_check_runner", "test_native_check_exec")]
    with tempfile.TemporaryDirectory(prefix="native-controller-tests-", dir=ROOT) as directory:
        isolated = Path(directory)
        (isolated / ".runtime").mkdir()
        shutil.copyfile(ROOT / "demo.project.json", isolated / "demo.project.json")
        for module in modules:
            module.ROOT = isolated
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"evidence_status": "MOCK_VERIFIED", "python": platform.python_version(),
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped),
              "real_git_workspace_tests_enabled": os.environ.get("FRAME003_ENABLE_REAL_GIT_TESTS") == "1",
              "passed": result.wasSuccessful(), "formal_runtime_or_delivery_evidence_modified": False,
              "native_model_calls": 0}
    target = Path(args.report).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(not result.wasSuccessful())


if __name__ == "__main__":
    main()
