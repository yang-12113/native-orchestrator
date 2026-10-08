# v0.2.1 底座修复与验收

任务：TASKS/FRAME-001.md。授权日期：2026-10-08。修复前基线：baseline-v0.2（a3c2333）；隔离分支：codex/controller-hardening。旧 data-live、私有配置、ACCEPTANCE.json 和高校岗位成果本轮保持原样。

已修复：过期执行尝试覆盖新状态；调用预算检查/登记的并发竞争；审查读取 SHA-256 未绑定；已接纳证据和依赖 proof 校验不完整；状态与未决决策缺少完整分页；具体决策被独立任务阻塞；程序检查失败后的多余审查；适配器固定 low 及当前原生版本支持。

Git 使用方式为：冻结基线 → TASK 票据 → 独立 worktree 修改 → Luna/max 临时测试 → 冻结候选 commit → 独立审查 → 真实文本任务自检 → 合入。此轮代码修复由当前 Codex 和独立测试/审查完成，不冒充待实现的 controller-managed repo_patch。

## 验证状态

- Luna/max 初始完整测试 47/47 通过，见 TASKS/FRAME-001-TEST-REPORT.md；均为 MOCK。独立审查随后拦下36f73b6的事务、依赖指针、规划预算归属和旧库门禁问题；修正后需再次冻结并验收。
- 当前 Codex 0.162.0-alpha.2 已在独立目录导出 experimental JSON Schema，核对模型分页、effort、thread/turn、动态只读工具字段；指纹见 PROTOCOL_SUPPORT.json。未来原生版本仍需重新核对，未放宽为任意 0.162。
- 最终候选的完整回归、独立复核和真实 Luna/max 文本自检尚待完成；结论与源代码提交将登记在 FRAME-001-ACCEPTANCE.json。

复验命令：`python -B run_tests.py --report <新的报告路径>`。该入口导入测试类并在临时目录运行，不执行旧测试的 evidence 写入入口。真实验证为 `python -B run_selfcheck.py --output <当前 checkout/.runtime 下的新目录>`，要求干净 Git 候选；只允许两个既有 ChatGPT 订阅 Luna/max 回合，无额外付费路由或自动返工。

## 当前边界与旧数据

整体仍为 PARTIAL。v0.3 的受限工程执行、实际工程只读隔离、批准检查命令、Git/SQLite/CURRENT promotion/reconcile、完整通知送达确认、累计业务字节预算和代表性工程验收尚未实现。替身测试与原生文本自检不证明这些能力。

旧 v0.2 ACCEPTED 缺少本次完整 proof，不能自动升级为新验收。新版在数据库写入、WAL/迁移操作之前只读检查 schema；旧格式直接拒绝。CLI、MCP、主脑和启动脚本要求显式数据目录；Start 的门禁在日志与 PID 写入之前。watch_project.py 可只读查看旧历史；复制旧目录不绕过门禁，完整迁移/重新验收仍需另行实现。本轮旧工件和历史验收保留，不补写新 PASS。

MXC 对照：工具沙箱内启动嵌套 Codex app-server 时，私有 CODEX_HOME canonicalize 返回 os error5，initialize 前退出且未调用模型。宿主启动相同候选的两角色文本自检已通过；这两种启动环境分别记录，宿主成功不表示嵌套 MXC 已通过。后台兼容性由单独沙箱交接提示词承接。

代码回退使用 Git revert 或从 baseline-v0.2 创建独立恢复 worktree；不自动降级数据库或清除测试/故障证据。本轮正式数据未迁移，因此源码回退不需要撤销正式数据变更。
