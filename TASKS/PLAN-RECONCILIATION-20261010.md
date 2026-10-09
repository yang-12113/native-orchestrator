# 计划修订说明（2026-10-10）

外部包 12 个文件已完整读取并按 MANIFEST 核对；其输入 ZIP SHA 与本机审查 ZIP 相同：6c9cbf83b5a904198fee9569284db07860d73a718971ccbcc88cb18bde96b484。当前开发 HEAD 仍为 ea73c49ab1e5d413ff85cb79935502d3ef1df1c0，工作区干净；没有 native_repo_turn.py/repo_proposal.py 或 FRAME-006 实现。

实质冲突：旧 FRAME-005 将只读材料/文件提案作为全部工程的唯一入口；外部方案改为模型直接编辑任务 worktree。普通任务采用后者，减少材料分页、完整文件回传与协议维护；原材料/提案成果保留为特殊隔离能力，不删除或改写历史验收。

最终主路径：Task → 现有 Controller/SQLite 预算与 lease → 标准 Git task branch/worktree → 官方 SDK Executor → 冻结 candidate → 确定性检查 → fresh 只读 Reviewer → 同一 candidate 的本地接纳。后续 main 变化须 merge 到任务分支、重测/重审，再串行 ff-only promotion；GitHub 是异步备份。

| 外部建议 | 旧计划 / 当前代码事实 | 决定与理由 | 用户决策 |
| --- | --- | --- | --- |
| 普通工程 direct-worktree | 旧计划禁止模型直接写；现有 workspace 冻结要求 detached、仅提案产生修改 | KEEP 方向；新 branch 路径单独验证，不能放宽已验收的 quarantine 接口 | 无 |
| material/proposal 为特殊隔离能力 | 材料 2731c3d 接纳；新原生提案文件尚不存在 | KEEP；停止扩写旧模型 proposal DSL | 无 |
| SDK first | 本机原先未装；已在新临时 venv 安装官方 SDK 0.162.0，依赖 CLI 0.162.0 | KEEP；先做零模型启动/权限参数核对，再实际 Executor，不另花 spike turn | 无 |
| SDK 完全替代 RPC | SDK 高层没有 dynamicTools 回调、command/exec、命名权限 profile；models 不自动翻页 | REVISE；新普通角色走 SDK，旧动态读工具/受限 checks 保留薄 RPC；Controller 语义不交给 SDK | 无 |
| 先检查后 AI Review | Controller.run_one 已按此顺序 | KEEP；环境 ERROR 不触发代码修复或浪费 Review | 无 |
| exact candidate 审查 | 旧 proof 绑定文字工件，未绑定工程 commit | REVISE；绑定 task/spec/attempt/base/candidate/manifest/check receipt，审查前后复核，旧 PASS 不可用于新 SHA | 无 |
| main 变化后 merge 并重测重审 | 工程集成尚未实现 | KEEP；必须按本次合入 main 的差异审查；promotion 内再核 expected main | 无 |
| 并行开发、串行 promotion；V1 不 rebase | 原有 detached 辅助模块不是工程 promotion | KEEP；先单任务试点，后本地冲突及锁测试 | 无 |
| 用 ff-only 简化 CAS/恢复 | Git 与 SQLite 非单一事务 | REVISE；ff-only 不替代 expected-ref 栅栏、持久 intent、owner/lease 与 Git/DB 对账 | 无 |
| GitHub 备份、push 失败不撤销接纳 | 实际无 remote | KEEP 语义 / DEFER 实现；remote 状态与任务 ACCEPTED 正交 | 真实 push 需另授权 |
| 保留状态/预算/lease/恢复 | 现有 calls、owner、attempt、spec_version、lease、proof 已实现 | KEEP；生产旧文本路径与数据不改，不新建第二套调度数据库 | 无 |
| Git/SQLite/文件去重 | Git 管代码；SQLite 管运行；开发 JSON 为人工阶段记录 | REVISE；MAINLINE 只作入口，开发 JSON 只存开发阶段/证据，CURRENT 如保留只能投影；不迁移旧库 | 无 |
| repair ≤2、总真实 turn ≤3 | 外部两项不能在 review FAIL 后同时保证新候选再审 | REVISE；本次 repair ≤1。检查先 FAIL 可 executor→repair→review 共3次；review FAIL 后修复需第4次再审，本次预算不足则停 NEEDS_REVIEW，禁止沿用旧 PASS | 无 |
| Windows 问题等上游 | 新 checks 有限定真实 PASS；旧嵌套启动历史 BLOCKED | KEEP；仅健康检查与 BLOCKED_ENVIRONMENT，不由 issue 推定本机相同根因，不改 ACL/helper/runtime | 无 |
| managed worktree、升级脚本、旧数据迁移 | 均非本轮纵向必要 | DEFER；标准 Git 足够，保持原数据 | 无 |
| Dashboard/复杂队列/多 Reviewer/Actions/新 DSL | 本轮尚未创建 | REJECT 为本轮范围；无必要事实支持扩大建设 | 无 |
| 断网仍可模型执行 | Git/SQLite 可离线，ChatGPT 原生模型仍需服务连接 | REVISE；本地接纳不依赖 GitHub，不等于模型可离线 | 无 |

来源：[官方 SDK](https://learn.chatgpt.com/docs/codex-sdk)、[官方 Python API](https://github.com/openai/codex/blob/main/sdk/python/docs/api-reference.md)、[官方 app-server](https://learn.chatgpt.com/docs/app-server)、[Git merge](https://git-scm.com/docs/git-merge)。本机 SDK public signatures 和固定依赖已实读；真实权限/模型能力尚待试点回执。

可继续执行：先零模型 capability probe，再写薄 SDK adapter 与一个新自有 fixture，目标 Executor/Reviewer 各1回合，总上限3。若环境阻断，留证据停止该链；本轮不修系统、不换大权限、不加付费路线，不动真实 remote/生产/凭据。
