# 原生协作控制器 v0.2.1 / PARTIAL

2026-10-08 底座修复及验收见 [HARDENING_VALIDATION.md](E:/零碎/native-orchestrator/HARDENING_VALIDATION.md)。状态/决策分页、过期尝试隔离、事务预算、完整证据校验、决策通知与思考档下传已实施；v0.3 工程能力和权限关卡仍待实现，见 [优化计划](E:/零碎/native-orchestrator/项目计划优化_2026-10-07.md)。

旧 data-live 和 ACCEPTANCE.json 是 v0.2 历史证据，未迁移或重跑。新版在写入前拒绝旧 schema，自动迁移已禁用；旧记录只读查看使用 watch_project.py。完整迁移需另行实现和明确对账，复制目录本身不会将旧 ACCEPTED 升级为新 proof。

快速入门：[给用户看的使用说明](/E:/零碎/native-orchestrator/使用说明_给用户.md)；让其他 AI 接手：[给 AI 的操作说明](/E:/零碎/native-orchestrator/使用说明_给AI.md)。等待验收使用 watch_project.py，提交命令退出不等于成果已验收。

交付状态 **PARTIAL**。默认流程已真实跑通：Sol 规划 → WorkBuddy AI 的 DeepSeek-V4.1-Flash 免费原生执行 → 独立 Luna 回读监察 → Sol 回报。ZCode 当前权益已确认，独立请求仍被服务端限制；见 NATIVE_CHANNEL_UPDATE.md。

项目：`E:\零碎\native-orchestrator`。保留旧已验证 Codex 0.160.0/0.160.1，并核对当前 0.162.0-alpha.2 协议；未来版本需重新验证。使用现有 ChatGPT 订阅和 WorkBuddy AI 5.6.2；config.live.json 的旧路由不变。Codex 路由可指定 `reasoning_effort`，例如 `max`；目录不支持或实际档位不匹配即停止。

## 一次交代并执行

把任务写入 UTF-8 文本文件（初始规划入口限 6500 bytes；更长项目用明确的 JSON 任务规范）。在 PowerShell 运行：

```powershell
& 'E:\零碎\native-orchestrator\Run-Request.ps1' -Data 'E:\零碎\native-orchestrator\data-v021' -RequestFile 'E:\零碎\native-orchestrator\request.example.txt' -RequestId 'your-unique-request-id'
```

已知同一 RequestId 重试会复用计划和项目；不同内容复用同一 ID 会拒绝。规划候选先校验；格式问题最多修复一次，再失败不派发。每个任务自动有独立监察，不用再单建监察任务。

## 查看、后台、停止和恢复

```powershell
$Project = '填写在 data-v021 提交返回的 project_id'
python 'E:\零碎\native-orchestrator\orchestrator.py' --data 'E:\零碎\native-orchestrator\data-v021' status $Project
python 'E:\零碎\native-orchestrator\orchestrator.py' --data 'E:\零碎\native-orchestrator\data-v021' delta $Project --cursor 0
python 'E:\零碎\native-orchestrator\orchestrator.py' --data 'E:\零碎\native-orchestrator\data-v021' resume $Project
& 'E:\零碎\native-orchestrator\Start.ps1' -Data 'E:\零碎\native-orchestrator\data-v021'
& 'E:\零碎\native-orchestrator\Stop.ps1' -Data 'E:\零碎\native-orchestrator\data-v021'
# 查看旧结果：这个 watcher 不迁移或审计写回旧库
python 'E:\零碎\native-orchestrator\watch_project.py' --data 'E:\零碎\native-orchestrator\data-live' p-52d8213273204455 --once
```

所有入口要求显式数据目录。Start 先检查 schema，再创建隐藏的普通后台进程；PID 在指定目录的 service.json，退出信息在该目录的 service 日志里。Stop 写持久 stop.request，活跃回合结束后停止。确认停止意图已撤销后，仅移除该目录内 stop.request，再 Start。没有安装开机任务，关机/休眠期间不计算。控制器从宿主终端启动；当前 MXC 工具内嵌套 Codex CLI 在读取私有 CODEX_HOME 时失败，见 HARDENING_VALIDATION.md。

崩溃租约到期后的不确定派发进入 NEEDS_DECISION，保留工件、原生 ID 与错误记录。先对账，不自动重复未知副作用；可用 `resolve '<decision_id>' retry` 或 `cancel`，重试仍受既有预算限制。每个任务最多 3 次总尝试，项目默认 60 个原生回合。原生会话为 ephemeral，故障恢复靠版本化状态及外部证据，不宣称能继续一个已销毁的原生会话。

## 实际成果

历史 v0.2 默认免费执行端到端：`data-live/projects/p-3f0ae85006304647/create_verification/1/artifacts/verification.txt`，实际内容 WORKBUDDY_PIPELINE_OK。原纯 Codex 项目 p-52d8213273204455 仍保留，重复请求没有增加调用。

两阶段 CSV：`data-live/projects/p-43e8ae53ca7b477f/csv-demo/2/artifacts/facts.csv`；后一阶段已通过独立监察。官网来源样例：`data-live/projects/p-88cc957c845e44b5/release-fact/2/artifacts/release.csv`；目录中有两次独立 HTTP 来源读取及监察回读凭证。

ACCEPTANCE.json 为机器状态；VALIDATION.md 说明 LIVE/MOCK；CAPABILITY_MATRIX.md 分开连接、模型、隔离与权益；evidence/validation-summary.json 记录真实数量与输入回报大小。

## 边界与证据存放

执行者仅提出文字工件，不能改现有仓库或调用通用工具。监察可读 spec.json、checks.json、批准工件和 independent-sources.json；没有写操作或日志读取工具。公开来源仅限配置内的 HTTPS 主机，来源文字不能改变预算、路由或验收规则。

SQLite 是权威状态；任务日志在对应 attempt 目录，不自动进入主脑。主脑阶段 JSON/MCP 回报上限 8192 bytes；每条摘要上限 400 Unicode 字符。主脑原生回合还有内置提示 tokens，实际消耗见证据，不能把短摘要字节数当总 tokens。

Codex 角色使用独立 CODEX_HOME，关闭 memory 使用/生成、共享 MCP、shell 和自动下级代理。WorkBuddy 角色使用独立目录、无持久对话、无工具的原生 CLI；经用户授权在内存恢复现有登录，保护原认证文件只读。`.runtime/` 不属于可分享交付内容。免费活动结束时间为北京时间 2026-10-10 零点，到期会报告；Sol 主脑与 Luna 监察仍消耗既有订阅额度。

## 复验和可选 MCP

```powershell
python -B 'E:\零碎\native-orchestrator\run_tests.py' --report 'E:\零碎\native-orchestrator\.runtime\regression-report.json'
python 'E:\零碎\native-orchestrator\check_processes.py'
python 'E:\零碎\native-orchestrator\check_mcp.py'
```

`mcp_server.py --data <目录>` 提供 6 个主脑工具，含显式查询特定证据的 2 KiB 摘录；不提供原始日志。启动程序等待不是模型轮询。未更改用户 Codex 的全局 MCP 配置；可先直接用上面的脚本。源码固定版本记录和参考教程见 ARCHITECTURE_DECISION.md。

大项目用 `status <project_id> --cursor <next_cursor> --state-version <state_version>` 翻页；决策用 `resume` 的相同参数，MCP get_resume_state 使用 decision_cursor/limit/state_version。has_more 为真时继续；STALE_STATE_CURSOR 要从 0 重读。报告只列未解决决策，watcher 另给剩余数量和下一游标。主脑通知不等待独立任务结束，并受项目与主脑回合预算约束。
