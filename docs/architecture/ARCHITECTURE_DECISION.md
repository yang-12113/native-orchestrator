# ADR-001：单一 SQLite 控制器与原生 Codex 会话

2026-10-07 补充：以下保留 v0.2 的实施决策。新的工程能力、能力预检和事件策略见 [v0.3优化计划](E:/零碎/native-orchestrator/项目计划优化_2026-10-07.md)，目前仅为待实现设计；不改变旧原生运行和验收状态。

日期：2026-10-06，Asia/Shanghai。状态：已实施，整体 PARTIAL。

选择 Python 标准库 + SQLite + 本机 Codex app-server 0.160.0。唯一权威状态在 `data-live/state.sqlite`；PROJECT_STATE 与 DECISIONS 是可重建导出。模型登录沿用既有 ChatGPT Plus；未增加 API Key、代理、付费服务或数据库安装。

Paperclip 的固定版本提供持久审查与唤醒，但需要 Node/数据库/运行器，还需要另外限制父任务上下文并补齐两种客户端。当前目标能用更少组件验证。Agent Bridge 两个持久化 Issue 仍开放，本实现不依赖其任务注册表。未把三个编排系统叠加部署。

执行者返回结构化文本工件，控制器检查批准的相对路径后落盘。监察使用新建原生会话和受限的 `read_review_file`，实际回读规范、程序检查、成果和独立来源；没有全文 worker 日志工具。模型不能直接写权威状态。通过要求：程序检查、独立判定、会话身份、任务/规范版本/尝试/清单哈希、回读记录和复核均有效。

原生 shell 在第一轮监察中被运行策略拒绝，因此采用更窄的读文件接口；没有解除限制或扩大为 fullAccess。非代码来源通过主机白名单限制的 HTTPS 两次读取。主脑仅初始规划与重要异常/最终阶段运行；等待和依赖推进由程序承担。主脑日常接口限制实际 JSON/MCP 回报 8 KiB，摘要 400 字符；原生内置系统提示的 tokens 另外计量。

正常任务最多两次返工、每个项目默认最多 60 个原生角色回合。明确停止未知付费备用。崩溃时不能确认的派发形成对账请求，不盲目重复有副作用工作。本实现的执行结果只是提议文本；没有声称任意外部副作用 exactly-once。

当前能力：新建文本/代码文本/JSON/CSV 工件、公开来源证据、独立监察、依赖、持久状态、后台循环、有限返工、主脑恢复。现有仓库修改、任意 shell/build 工具、安全的二进制文档生成及跨设备提交尚未接入。ZCode 与 WorkBuddy 的完整模型通道未计入完成。

固定参考版本：Paperclip `1d5a439e2b0e551f7a5129e414d7bdc8582ddd00`（MIT）；Agent Bridge `75dd3c56cceac5fc92ef3a9a85d4fecbe444f20f`（MIT）；zcode-acp `3339cb6c016c1ad9daafeb5b0a98195e920be811`（Apache-2.0）；WorkBuddy Desktop Bridge `c00a8e5eab809a97963277e71ec008abb3d372ae`（MIT）。参考协议语义，未安装这些编排器；公开代码缓存用于核查。

参考：[官方 app-server 入门](https://learn.chatgpt.com/docs/app-server)、[官方记忆配置](https://learn.chatgpt.com/docs/customization/memories)、[ZCode 排障教程](https://github.com/william0wang/zcode-acp/blob/3339cb6c016c1ad9daafeb5b0a98195e920be811/docs/TROUBLESHOOTING.md)、[WorkBuddy 桥接示例](https://github.com/gosick233-cloud/Codex-WorkBuddy-Desktop-Bridge/tree/c00a8e5eab809a97963277e71ec008abb3d372ae)、[Paperclip 执行语义](https://github.com/paperclipai/paperclip/blob/1d5a439e2b0e551f7a5129e414d7bdc8582ddd00/doc/execution-semantics.md)。
