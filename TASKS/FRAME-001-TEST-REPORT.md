# FRAME-001 isolated test report

Final unified run: **47 tests, 47 passed, 0 failures, 0 errors**. The JSON report is [FRAME-001-final-report-20261008.json](</E:/零碎/native-orchestrator-hardening/.runtime/FRAME-001-final-report-20261008.json>).

| Suite | Tests | Passed |
| --- | ---: | ---: |
| Existing controller and native-adapter tests | 25 | 25 |
| Existing read-only watcher tests | 5 | 5 |
| `test_hardening.py` | 13 | 13 |
| `test_codex_protocol.py` | 4 | 4 |

The hardening tests cover stale-worker fencing after a retry is accepted, project and master budget limits under concurrent invocation, review-read hash binding for spec/check/source/artifact evidence, accepted-proof tampering/loss and forged predecessor proof, bounded task/decision pagination with stale cursor rejection, master wakeup while an independent task remains pending, duplicate decision wake suppression, skipping review after failed program checks and environment errors, and rejection of `repo_patch` before project submission. Protocol tests use a fake RPC to verify `max` effort reaches both thread and turn requests, unsupported or mismatched effort fails closed, model discovery follows the next catalog page, and an unvalidated prerelease version is rejected.

`run_tests.py` imported all five test modules and patched every module `ROOT` to a fresh temporary directory under the worktree; its `--report` target is the new JSON file linked above. Controller databases and generated evidence were confined to that temporary directory. `CodexAdapter.run`/`Rpc`, `private_environment`, `subprocess.Popen`, and `subprocess.run` were replaced or guarded in the new tests; existing adapter tests use `FakeProcess`. Legacy test modules were imported, not run as `__main__`, so evidence-writing entrypoints did not execute. Python ran with `-B` and `PYTHONDONTWRITEBYTECODE=1`.

An earlier interim run found a stale reviewer-count assertion in `test_terminal_state_survives_restart`; it was updated and passed in the final run. The first unified-runner attempt failed before tests started because the default Windows temporary directory denied creation; `run_tests.py` now places its disposable root under the worktree. The final 47-test run passed.

These are mock/controller, watcher, and protocol-level checks. They do not verify real model behavior, real native applications, Windows OS sandbox integrity, or the full v0.3 engineering workflow.
