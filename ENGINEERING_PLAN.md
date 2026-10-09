# 自动工程执行计划（修订2，2026-10-10）

目标：长周期可靠、主脑上下文清洁、低额度、低维护、可恢复。对账见 TASKS/PLAN-RECONCILIATION-20261010.md；进度唯一读主仓库 DEVELOPMENT_STATE.json，入口 MAINLINE.md。

最终主路径：Task → 现有Controller/SQLite预算与lease → 标准task branch/worktree → 官方SDK Executor直接编辑 → exact candidate → 批准确定性检查 → fresh只读Reviewer → 最新main integration/重测重审 → 串行promotion → best-effort remote backup。

保留v0.2.1文本基线与FRAME002/003/004历史接纳、FRAME005材料成果。材料/proposal降为quarantine；不放宽已验收detached/proposal接口，不扩新模型proposal DSL。SDK负责普通角色transport/lifecycle，旧动态读工具/command-exec/命名checks保留薄RPC；Controller语义不交给SDK。

| 顺序 / 票据 | 交付与通过条件 | 负责 |
| --- | --- | --- |
| R0 | 完整读取外部包，核对真实Git/源码/SDK，KEEP/REVISE/DEFER/REJECT | root |
| R1 / FRAME005 | 固定SDK bundle、零模型初始化和参数probe，不冒称实际权限已通过 | root |
| R2–R3 / FRAME005 | 薄SDK adapter、小fixture direct-edit→candidate→checks→fresh独审→本地接纳，exact SHA/receipt | root实现/fake；两个fresh原生角色 |
| FRAME006 | 已验证接口接Controller工程任务、proof、有限返工；默认生产gate关闭 | root；必要时窄范围独立测试/独审 |
| R4 / FRAME007 | merge latest-main、新candidate重测/重审、串行promotion锁与expected-ref栅栏；真实文本/语义冲突 | root，本地测试 |
| R5 / FRAME008 | 持久promotion intent、unknown不重放、Git/SQLite崩溃点对账、local bare remote | root，fault injection |
| FRAME009 | 旧库明确复制/迁移/证据对账，原数据不变 | 后置 |
| R6 / FRAME010–011 | 已有工程副本、新主会话恢复、交付矩阵；不等于长期运行已观察 | root，最终独审 |

G1范围保留，不延伸为新SDK权限证明。G2真实direct-edit+fresh独审与生产Controller接线分别记录；G3完整晋升/恢复，G4既有项目使用/交付；不得把fixture、MOCK、skip或SDK参数接受当全阶段PASS。

本次真实模型目标2、上限3、repair<=1。检查FAIL可repair后首审；Review FAIL后修复还需新审而超额，本次停NEEDS_REVIEW/预算。其他负例/并发/恢复/remote用fake/local测试。保留calls预算、规划归属、owner/attempt/spec/lease、proof与栅栏；累计字节/送达确认后置，不把token换算为订阅金额。

并行开发、串行晋升，初次只开单任务。main变化后merge→新SHA→重新check/review；锁内重核expected main。ff-only不替代CAS/intent/DB对账；V1禁止自动rebase/force。remote状态与本地ACCEPTED正交，无remote=REMOTE_DISABLED，失败=REMOTE_PENDING/ERROR。真实push、凭据或生产操作需用户另授权。

Git管代码、SQLite管运行、TASK是输入、receipt是不可变证据；MAINLINE仅入口、开发JSON仅阶段/证据/下一动作；CURRENT如保留只能投影。不新增第二个数据库或复杂调度平台。

本轮后置/拒绝：Windows ACL/helper/runtime修补、managed worktree深集成、Dashboard、复杂队列、多Reviewer、大量subagent、Actions、daemon、生产发布、新复杂proposal DSL。依赖变化后再用普通compat smoke脚本验证，保持last-known-good，不自动追main。SDK只装自有临时venv。

root独占主线/状态/整合。默认无额外代理；必要辅助须窄票据、fork_turns=none、短报告、唯一作者与独立审查。日志外存，交接从AGENTS→PROJECT→MAINLINE→权威状态→当前票据→Git实物恢复。共享文件系统不当物理隔离。
