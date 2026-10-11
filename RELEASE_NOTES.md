# native-orchestrator v1.0.0 — Release Notes

状态：FINAL RELEASE（正式发布）。

## 版本与来源

- Release tag：`v1.0.0`。
- Release commit：`18e64efc0cd6340b537f1a71cd3df3a5862fb615`。
- 分支：`codex/engineering-v03`。
- 工程验收状态：FRAME-006 FINAL ACCEPTED_WITH_LIMITS。
- 历史冻结标签：`controller-v1.0.0-local` → `004de591bd03127c61c502655b1a7668eea3413d`，保持原样。

本次 v1.0.0 标记包含冻结 V1 工程及之后的可移植恢复文档、软件项目目录整理。它与历史本地冻结标签区分，包含当前 src/tests/docs/meta 布局。已有 commit 和历史标签未改写。

## 已验收能力

普通本地 Git 工程的生产 Controller → Codex SDK Executor → 候选冻结 → 确定性检查 → fresh 独立只读 Reviewer → 版本化 proof 接纳 → 本地 promotion/CAS 与中断对账闭环已验收。

工程角色策略保留在 `config/model-policy.toml`：Executor/worker GPT-6 Luna/high，Reviewer/escalation GPT-6.1 Sol/high，禁止自动降级。SQLite 为运行时调度权威；Git、SQLite 与文件投影不能视为单一原子事务。

## 版本整理内容

- 核心 Python 和桥接代码归入 `src/native_orchestrator/`，全部 16 个测试文件归入 `tests/`。
- 文档分类为 `docs/architecture/`、`docs/acceptance/`、`docs/decisions/`、`docs/history/`。
- 当前 Agent 规则、主线和开发状态归入 `meta/`；根 `AGENTS.md` 指向该入口。
- 示例归入 `examples/`；PowerShell 入口归入 `scripts/`；配置保留在 `config/`。
- 修复文件移动产生的 import、子进程、资源及归档路径；增加包 `__init__.py`。
- README 提供版本状态、快速开始、结构说明、测试与项目恢复入口。
- 历史验收 JSON、原路径和原提交内容保持不变；归档文档禁用自动换行转换以保留原 Git blob。

本次目录整理没有新增业务能力或重构控制器架构。源码路径/import 修复会改变文件指纹；原 proof 按原提交追溯，不能自动当作新快照的证明，继续使用须遵循既有 reconciliation 规则。

## 验证结果

- 目录整理后最终完整回归：228 项，223 PASS / 0 FAIL / 0 ERROR / 5 SKIP。
- 5 项 SKIP 来自 Windows OS symlink 权限限制，不计为 PASS。
- 全部现有测试覆盖已运行，包括新建自有 fixture 的真实 Git worktree/promotion/recovery 用例。
- Python 包导入、直接 CLI 和 `-m` CLI、Node/PowerShell 语法检查通过。
- README 的 MOCK 快速开始已验证：两个示例任务 ACCEPTED，不代表真实模型验收。
- 归档路径模拟及独立只读结构复审通过。
- 85 个原历史资料、资源和示例的提交 blob 与整理前基准一致；53 个 Python 文件匹配最终回归快照。
- 目录整理与 Release 准备未发起真实模型调用。历史 FRAME-006 两次 SDK turn 证据另行保留。

目录整理回归报告未纳入 Git。历史验收记录见 `docs/acceptance/TASKS/FRAME-006-ROUND3-ACCEPTANCE.json`，路径映射见 `docs/history/FILE_LAYOUT.md`。

## 使用范围与已知限制

V1 限单独立任务、已有 tracked UTF-8 文本和普通本地 Git worktree。二进制、删除、重命名、子模块、依赖图、managed worktree、生产部署及更广任务模式不在冻结验收范围。

Windows OS symlink 为 `UNVERIFIED_WINDOWS_SYMLINK`；真实 junction 与 Git mode 120000 拒绝已验证。旧适配器仍有原有的本机安装和登录环境要求，目录整理没有使全部真实通道具备跨机器即用能力。

需要 Python 3.11+、Git；真实工程另需已验证的 Codex SDK/runtime、现有登录、私有配置和用户授权。临时运行工件、历史 SQLite、原始日志及私有配置不随 Git clone 提供。历史路径只用于追溯，不能假定对应工件当前可用。

## License 与元数据快照

项目当前分支新增根目录 `LICENSE`，采用 Apache License 2.0；第三方组件继续使用各自的许可证，随附 MIT 许可证与 NOTICE 保持不变。

发布标签 `v1.0.0` 指向最终元数据提交 `18e64efc0cd6340b537f1a71cd3df3a5862fb615`，包含根目录 LICENSE、README License 段及 RELEASE_NOTES.md。标签快照中的说明文件保留准备阶段原文；GitHub Release 页面和当前分支发布说明已校正过时状态和目标 SHA。历史冻结标签与已有 commit 均保持原样。

## 发布说明

- 本次发布快照包含 Apache License 2.0 项目元数据，第三方授权材料保持原样。
- 发布描述基于标签内的 RELEASE_NOTES.md，仅更正准备阶段过时字段；技术事实、验证结果和已知限制保持原样。
- 远程标签已核对，目标 commit 与发布快照一致。
- 如需附带构建物或回归报告，应单独审核附件，不包含认证、私有配置或原始敏感日志。
