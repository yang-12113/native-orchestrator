# 长周期自动工程执行框架

目标：用户交付明确任务后，利用现有原生模型、Git和小型确定性控制器，完成受限代码修改、检查、独立审查、有限返工、版本接纳与中断对账；减少完整日志和重复研究进入主脑。

核心设计：普通任务由官方Codex SDK在独立task branch/worktree直接编辑，程序掌握冻结候选、检查、独审、晋升与副作用；材料/文件提案保留为特殊隔离能力；SQLite是运行时唯一调度权威，文件/报告是证据或投影。输入、规格、尝试、成果、检查目录、策略/环境和审查身份通过哈希及版本绑定。每个状态写入和外部副作用校验当前权威，未知派发先对账。Git、SQLite与CURRENT不能假称为单一原子事务。

首版范围：干净已提交Git输入、自有普通目录、允许路径内UTF-8修改、批准检查ID、exact candidate独审及发布恢复。并行开发、串行promotion，V1不自动rebase；GitHub仅异步备份，CURRENT最多投影。复杂二进制/删除/rename/子模块和未验证runtime能力不隐式开放；首个检查runtime为已实测Python原生命令通道，其他能力需验证。

执行路线：V1 普通本地工程使用官方 Codex SDK direct-worktree 和生产 Controller 闭环，程序独占候选冻结、检查、独立只读审查、proof 接纳、晋升与恢复。当前已验收范围和后续 DEFER 项以权威 DEVELOPMENT_STATE.json 与 FRAME-006-ROUND3-ACCEPTANCE.json 为准。

约束：沿用现有订阅、不添加新付费路由；主脑业务回报<=8KiB、摘要<=400 Unicode字符、证据摘录<=2KiB；日志外存，预算限制次数与累计量分别实现。内置模型上下文另计，不编造节省金额。

不能破坏：已验收文本控制器及旧成果、原校招项目、用户未提交内容、私有凭据/配置和已记录的授权范围。既有项目只在明确绑定的副本上做后续工程使用验收。

使用本体系开发自身：AGENTS.md定义入口/协作规则；MAINLINE.md短恢复；DEVELOPMENT_STATE.json动态事实；TASKS/限定工作；DECISIONS.md防止反复决策；Git保留基线、隔离分支、冻结候选、独审与回退。主代理在每个阶段/交接/压缩前提交检查点，恢复不依赖完整聊天记忆。


## V1 最终验收（2026-10-10）

FRAME-006 FINAL ACCEPTED_WITH_LIMITS：普通本地 Git 工程的生产 Controller 执行、确定性检查、fresh 独立只读审查、版本化 proof、中断对账和串行 promotion/CAS 已验收。实际两模型闭环及精确 candidate 证据见 TASKS/FRAME-006-ROUND3-ACCEPTANCE.json。Windows OS symlink 权限场景仍未验证；junction 和 Git mode 拒绝已验证。范围为单独立任务、已有 tracked UTF8 文本，runtime/proof 升级按 ROUND3 票据安全对账。

停止扩建框架，开始用于真实项目；GitHub remote / Codex managed worktree / Windows upstream sandbox 作为后续增强，不属于 V1 阻塞项。
