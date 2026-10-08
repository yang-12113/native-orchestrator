# FRAME-002 测试报告

task_id: FRAME-002  
status: PASS_WITH_REAL_SYMLINK_SKIPPED  
candidate_commit: 未采集（本次未执行 Git 操作）。按主代理说明，bda744b 是旧文本验收基线，FRAME-002 初版 75bd122 已被拦截，均不作为本次测试候选。

facts/findings: 新增两个边界负例：`allowed_changes=["src"]` 覆盖受保护子路径 `src/private.json` 必须拒绝；已存在的目录 `src` 不能作为改动目标，必须返回 `INVALID_PATH`。两项均通过。所有预检用例使用 worktree 内临时 fixture 与 fake repository_probe；不调用 Git 探测、模型、批准命令或数据库。契约通过仍断言 `dispatchable=False`。

checks:
- 稳定前夹具运行：未运行，遵守等待实现稳定的要求。
- 契约套件：19 项运行，18 passed、0 failures、0 errors、1 skipped。命令：`python -B -m unittest -q test_execution_contract`。
- 六模块统一回归：78 项运行，77 passed、0 failures、0 errors、1 skipped。命令：`python -B run_tests.py --report .runtime/frame-002-unified-report.json`。JSON 报告含 `skipped: 1`、`native_model_calls: 0`、`formal_runtime_or_delivery_evidence_modified: false`。
- 唯一跳过项仍是真实 OS symlink 创建，Windows 返回 WinError 1314（缺少创建符号链接权限）。合成 link 判定用例通过，但不视作真实系统权限验证。

blockers: 真实 OS symlink 行为仍未验证；其余新增契约用例和六模块回归通过。

evidence_refs: `test_execution_contract.py`; `.runtime/frame-002-unified-report.json`; `.runtime/frame-002-tests/FRAME-002-ISOLATION-REPORT.md`