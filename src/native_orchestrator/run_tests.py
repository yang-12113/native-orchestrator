"""Run regression suites in disposable directories without touching delivery evidence."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import argparse
import hashlib
import json
import os
import platform
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    # The report records the tested checkout, not a later documentation commit.
    from native_orchestrator.execution_contract import inspect_git_input
    source_files = sorted(path for path in (ROOT / "src/native_orchestrator").glob("*.py") if path.is_file()) + sorted((ROOT / "tests").glob("test_*.py"))
    source_hashes = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files}
    candidate = inspect_git_input(str(ROOT))["head"]
    import sys
    sys.path.insert(0, str(ROOT / "tests"))
    modules = [__import__(name) for name in (
        "test_controller", "test_native_adapters", "test_watch_project",
        "test_hardening", "test_codex_protocol", "test_execution_contract", "test_repo_workspace",
        "test_check_runner", "test_native_check_exec", "test_windows_path_boundaries", "test_repo_materials",
        "test_codex_sdk_adapter", "test_model_policy", "test_repo_controller", "test_repo_round2", "test_repo_round3")]
    with tempfile.TemporaryDirectory(prefix="native-controller-tests-", dir=ROOT) as directory:
        isolated = Path(directory)
        (isolated / ".runtime").mkdir()
        (isolated / "examples").mkdir()
        shutil.copyfile(ROOT / "examples/demo.project.json", isolated / "examples/demo.project.json")
        for module in modules:
            module.ROOT = isolated
        suite = unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromModule(module) for module in modules)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    report = {"evidence_status": "MOCK_VERIFIED", "python": platform.python_version(),
              "tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
              "skipped": len(result.skipped),
              "candidate_commit": candidate, "source_sha256": source_hashes,
              "source_unchanged": all(hashlib.sha256(path.read_bytes()).hexdigest() == source_hashes[path.name]
                                      for path in source_files),
              "skip_reasons": [{"test": str(test), "reason": reason} for test, reason in result.skipped],
              "real_git_workspace_tests_enabled": os.environ.get("FRAME003_ENABLE_REAL_GIT_TESTS") == "1",
              "passed": result.wasSuccessful(), "formal_runtime_or_delivery_evidence_modified": False,
              "native_model_calls": 0}
    target = Path(args.report).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(not (result.wasSuccessful() and report["source_unchanged"]))


if __name__ == "__main__":
    main()
