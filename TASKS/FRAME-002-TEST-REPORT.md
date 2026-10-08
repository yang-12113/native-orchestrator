# FRAME-002 测试报告

task_id: FRAME-002  
status: PASS_WITH_SYMLINK_ENV_SKIP  
candidate_commit: 未采集（未执行 Git 操作）

facts/findings: 所有新增用例使用 worktree 内临时 fixture 与 fake repository_probe；不调用 Git 检查、模型、批准命令或数据库。契约预检始终断言 `dispatchable=False`。预算 worst-case 断言按 `2*(1+max_reworks)+planning_turns+notification_turns` 计算。

checks:
- 稳定前夹具运行：未运行，遵守等待实现稳定的要求。
- 稳定后新增用例：17 项，16 passed、0 failures、0 errors、1 skipped。通过 `python -B -m unittest -q test_execution_contract`。唯一跳过项是创建真实 OS symlink 的测试，因为当前环境不允许创建；合成 link 判定用例通过，但不作为 OS 权限验证证据。
- 原 5 模块基线：59 项，0 failures、0 errors，通过 `python -B run_tests.py` 的 disposable directory 运行；未调用旧测试 `__main__`。控制台出现 `Failed to find real location of E:\python\python.exe` 提示，但结果通过。
- 主代理整合后的六模块入口：76项运行，75通过，0 failures/errors，1真实symlink环境跳过，报告 `.runtime/frame-002-unified-report.json`。原59项基线仅使用临时SQLite数据库，没有修改正式数据库。
- 实际只读Git探测：正确读取原源码目录HEAD/tree并识别开发状态文档未提交导致clean=false；没有模型调用或工程命令执行，报告 `.runtime/frame-002-real-git-probe.json`。

blockers: 真实 OS symlink 行为未在此环境验证；其余 FRAME-002 隔离测试和原 59 项基线通过。

evidence_refs: `test_execution_contract.py`; `.runtime/frame-002-tests/FRAME-002-BASELINE-REPORT.json`; `.runtime/frame-002-tests/FRAME-002-ISOLATION-REPORT.md`
