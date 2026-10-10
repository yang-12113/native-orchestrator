# FRAME-004 check runner test report

Status: `FAKE_RUNNER_VERIFIED; UNIFIED_REGRESSION_PENDING`.

`test_check_runner.py` uses only a fake `native_executor`; its argv is captured and never launched. The fixture AST is recorded in `.runtime/frame-004-tests/fixture_ast.json`. Coverage includes catalog-ID selection without argv overrides, binding/candidate/catalog and capability validation, invalid and overlapping roots, symlink rejection, timeout/output-cap limits, dispatch fencing, manifest and candidate binding, uncertain dispatch non-replay, PASS/FAIL/ERROR classification, external stdout/stderr receipts, input drift, and fixed sandbox roots/policy.

Static AST parsing passed. One targeted unittest attempt ran 11 methods and reported 10 errors plus 1 skipped symlink case. All 10 errors stopped in `check_runner.root_path()` at strict `Path.resolve(strict=True)`: this tool's Python process returned Windows `WinError 5` on the temporary snapshot directories inside `.runtime/frame-004-tests`, although the directories were readable and `is_dir()` succeeded. The test code was not changed to bypass that boundary. The attempt therefore does not establish business assertion results; the root agent will rerun the same fake-only module from the host.

The test code launched no child subprocess, native appserver, model call, network request, service, real Git probe, or real check. No bytecode cache was generated.

Root host rerun passed with the strict path guard unchanged. After adding regressions for launcher-error diagnostics, previously unverified native versions, Python flags, and authority loss after dispatch, the combined runner/native-helper suite ran 26 tests: 25 passed, 1 real symlink creation skipped; no failures/errors. Evidence: `.runtime/frame-004-tests/host-fake-expanded.log`. These fake tests do not substitute for live command-boundary verification; live evidence is separately recorded by `validate_check_runner.py`.
