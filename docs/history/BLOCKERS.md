# 当前未解决问题（v0.2.0）

最新证据见 NATIVE_CHANNEL_UPDATE.md 和 evidence/native-channel-update.json。两个软件均找到有效登录；WorkBuddy 免费执行完整链路已修复，之前的旧缓存/旧 sidecar 不再作为当前结论。

## B02-Z：ZCode 独立请求被服务端限制

类型：原生模型接口/服务端安全限制。ZCode 3.14.4.7912、CLI 0.16.9、BigModel Start Plan。当前权益 API 返回 active，包含 Flash 领取额度；领取额不能当剩余额度。

具体失败：account:bigmodel-start-plan / GLM-5.3-Flash 独立生成返回 `request has been blocked due to unusual activity.`。证据：evidence/native-fix/zcode-live.json、zcode-smoke-events.jsonl、zcode-current-entitlements.jsonl。

已尝试：正确 NDJSON、双 provider 路径、当前原生身份与权益、账号模型映射、必需推理级别、真实客户端版本与既有设备上下文。服务端拒绝仍相同，已停止自动重试/备用。当前配置 skip_model_request=true；没有把它当作已证明必须解验证码，也没有绕过安全验证或改换身份/代理。

影响：ZCode 权益与会话建立已验证，独立模型执行未通过。WorkBuddy、Codex 监察及主脑不受影响。

最小用户事项：仅在继续启用 ZCode 路线时，在原生客户端检查/处理官方安全提示；桌面正常而独立接口受限时，需要上游确认这项免费权益的独立 CLI 支持。无需再次登录、重新领取或提供密钥。默认 WorkBuddy 现在可直接使用。

## B03：活动到期边界

WorkBuddy exact model 已实测服务端 rawUsage.credit=0，活动截止北京时间 2026-10-10 零点。到期会停止该路线并报告，不自动切入新付费 API。原有订阅路线保留在 config.codex.json，需显式选用。Sol 与 Luna 监察仍消耗既有 Codex 订阅；不能宣称全流程免费。

ZCode 领取授权已查到，模型仍受独立接口限制，剩余额度未验证。这不需要用户为已跑通的 WorkBuddy 路线做任何新账号操作。

## B05/B09：部分隔离边界不可全观察

Codex 新会话/独立 home/memory 禁用与受限只读工具已验证；WorkBuddy 独立目录、无模型工具、无继承对话、原登录文件前后哈希相同。云端内部记忆来源与所有 OS 权限对照不可完全观察，未夸大为全系统隔离证明。用户无需操作。

## B13：仍未实现的工程范围

当前支持新的文本/CSV/JSON 工件、公开来源验证。现有仓库修改、任意 shell/build/test、复杂二进制文档、跨设备入口、动态计划合并以及 Codex GUI 全局 MCP 注册仍未接入。临时原生会话故障后的恢复依靠外部状态与证据，不确定派发需要对账。这是工程待办，不是用户登录/权限问题。

## 已处理的审批问题

自动审批曾因授权不够具体拒绝恢复加密登录。用户已明确同意借用两个软件现有登录状态；随后执行并验证。令牌未打印、未另存、未送往第三方，无需再次询问同一授权。
