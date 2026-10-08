# FRAME-001 isolated test report

Final proof-policy run: **59 tests, 59 passed, 0 failures, 0 errors**. The latest JSON report is [FRAME-001-final-proof-report-20261008.json](</E:/零碎/native-orchestrator-hardening/.runtime/FRAME-001-final-proof-report-20261008.json>).

| Suite | Tests | Passed |
| --- | ---: | ---: |
| Existing controller and native-adapter tests | 25 | 25 |
| Existing read-only watcher tests | 5 | 5 |
| `test_hardening.py` | 25 | 25 |
| `test_codex_protocol.py` | 4 | 4 |

The hardening tests cover stale-worker fencing after a retry is accepted, project and master budget limits under concurrent invocation, concurrent duplicate-decision notification suppression, reentrant transaction rollback, fixed check/review references and dependency proof consumption, canonical `input_spec_sha256` binding, executor-stage spec tampering before review, verified snapshot consumption without a second review read or forged-review injection, evidence-helper source changes invalidating accepted proof policy, recursive invalidation of accepted descendants after ancestor tampering, duplicate planning-call attachment advancing the state version, accepted-proof tampering/loss and forged predecessor proof, read-only rejection of legacy databases, planning reservation attachment/rollback and budget accounting, master state-version invalidation, bounded task/decision pagination, master wakeup while an independent task remains pending, skipping review after failed program checks and environment errors, and rejection of `repo_patch` before project submission. Protocol tests use a fake RPC to verify `max` effort reaches both thread and turn requests, unsupported or mismatched effort fails closed, model discovery follows the next catalog page, and an unvalidated prerelease version is rejected.

`run_tests.py` imported all five test modules and patched every module `ROOT` to a fresh temporary directory under the worktree; its `--report` target is the new JSON file linked above. Controller databases and generated evidence were confined to that temporary directory. `CodexAdapter.run`/`Rpc`, `private_environment`, `subprocess.Popen`, and `subprocess.run` were replaced or guarded in the new tests; existing adapter tests use `FakeProcess`. Legacy test modules were imported, not run as `__main__`, so evidence-writing entrypoints did not execute. Python ran with `-B` and `PYTHONDONTWRITEBYTECODE=1`.

The earlier stale reviewer-count assertion was updated; the original artifact-tampering assertion now expects the accepted descendant to be invalidated as well as its changed ancestor. The first unified-runner attempt failed before tests started because the default Windows temporary directory denied creation; `run_tests.py` places its disposable root under the worktree. The final 59-test run passed.

These are mock/controller, watcher, and protocol-level checks. They do not verify real model behavior, real native applications, Windows OS sandbox integrity, or the full v0.3 engineering workflow.
