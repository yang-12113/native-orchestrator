# FRAME-006 ROUND-2：本地故障、并发、冲突与恢复验收

本票据由用户本轮附件 b4e1c0f3-650c-4e53-a39e-c59501f07e5a 授权，接续已接纳的 Round 1；不重做架构研究。

启动实查：开发 HEAD=c64b7ce02e551ac3ca9f565be74f6be7b32086d7，branch=codex/engineering-v03，git status 干净。Git worktree 列表与开发副本/权威 DEVELOPMENT_STATE、Round 1 receipt 一致。仅凭这些持久文件成功恢复，未读取旧聊天或全部历史日志。

范围：现有 Controller、Git、SQLite、owner/lease、dispatch、candidate/check/review/acceptance receipts。允许最薄恢复接口及本地 promotion journal/OS lock/CAS；禁止新 Manager、队列框架、rebase、产品能力扩张、remote/Actions、凭据和系统配置修改。模型策略文件保持原字节，真实 SDK/model turn=0，Executor/Reviewer 均用 fake。

验收路径：Controller.recover/run_one；Controller.integrate_repo_main；Controller.promote_repo_task。恢复继续使用正式 EXECUTING/REVIEWING/ACCEPTED/NEEDS_DECISION；NEEDS_RECONCILIATION、NEEDS_REVIEW、BLOCKED_ENVIRONMENT、CODE_CHECK_FAILED、GIT_TEXT_CONFLICT 为决策原因，不新增状态体系。

Crash A 未提交编辑不能证明 candidate 完成：保留原 branch/worktree、进入 NEEDS_DECISION，不重放 Executor。B 依据 freeze intent/commit parent/tree 或已持久 candidate 重跑确定性 checks。C 仅复用相同 task/spec/attempt/candidate/manifest/catalog 的 PASS。D 从绑定的 completed SDK record/dispatch/ledger 复核，不重复 Reviewer。E 验证磁盘完整 acceptance 后补 DB；未知派发、篡改、漂移或不完整材料安全待决策。检查中断用新 scratch/evidence generation，不覆盖旧运行目录。

main=A→C 后 B1 不可 promotion。保留旧 attempt 证据，新 attempt 清除有效 checks/review/proof，merge C 成 B2，重新 checks 与 fresh review。文本 conflict 保留 Git 冲突索引与各 worktree；语义 conflict 在两文件干净合并后运行实际 Python deterministic assertion 捕获，不调用 Reviewer。

promotion：同一 Git common directory 的进程 OS 文件锁保证本机串行；SQLite BEGIN IMMEDIATE 再核验完整 acceptance。持久 intent 绑定 expected_main/candidate/proof；Git update-ref 使用 expected SHA 原子 CAS。CAS 与 checked-out main 的工作区更新非原子，使用 two-tree read-tree 的安全检查，只恢复 journal 明确允许的 old/new tree，不 reset/stash/clean。receipt 先于 DB event；重启重复调用补事件而不重复 CAS。

测试入口：FRAME003_ENABLE_REAL_GIT_TESTS=1；python -B run_tests.py --report .runtime/<new-report>.json。测试只作用于全新自有 Git/SQLite fixtures；不得修改旧 acceptance 或 data-live。工具沙箱严格路径解析 WinError5 仍分类环境错误，正常宿主测试经工具权限审查运行；不修改任何 sandbox 配置/ACL/helper。

结果及冻结候选以 FRAME-006-ROUND2-ACCEPTANCE.json / EVIDENCE-BINDING.json 为准。Round 3 保留真正工程项目的端到端应用/运行边界验证、未验证 OS symlink/Reviewer 写入拒绝能力；本轮本地故障证明不能标成新 LIVE 模型证据。
