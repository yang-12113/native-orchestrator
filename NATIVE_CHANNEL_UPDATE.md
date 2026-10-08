# 原生通道修复交付 v0.2.0

2026-10-06，Asia/Shanghai。WorkBuddy 原生免费执行完整链路已通过。ZCode 登录和当前权益已经确认，但独立模型请求受服务端限制。整体仍为 PARTIAL。

## WorkBuddy 已解决

当前软件使用 `.workbuddy-ai` 资料目录、新版产品配置和共享原生认证存储；旧 sidecar PID 文件不能代表当前宿主能力。已改用安装包内原生 CLI，借用用户明确授权的现有登录；不依赖旧控制管道。

真实请求与原生响应均为 `deepseek-v4.1-flash`，服务端 rawUsage.credit=0。当前活动 discount.factor=0，结束时间为 2026-10-10T00:00:00+08:00，即北京时间 10 月 9 日结束时。另一条带 -sg 后缀的模型不计作已验证免费路线。

执行者无工具、无共享 MCP、无继承对话，使用独立目录和无持久会话。恢复后的令牌只在内存中使用；原认证存储只读。实测原加密登录文件前后 SHA256 相同，见 evidence/native-fix/workbuddy-live.json。

独立测试项目 p-9d29f3e2d53f4aae（data-workbuddy-live）：WorkBuddy 生成 CSV，独立 Codex Luna 回读验收，Sol 回报，第一次尝试 ACCEPTED。

默认后台项目 p-3f0ae85006304647（data-live）：从自然语言开始，Sol 规划、WorkBuddy 生成 verification.txt、独立 Luna 监察、Sol 最终回报，实际内容 WORKBUDDY_PIPELINE_OK。config.live.json 已默认使用这条路线。

运行期间 Codex 更新为 0.160.1，旧版锁按设计暂停；四份关键 RPC schema 与 0.160.0 一致，已留证比较并完成真实流程复验。失败规划没有启动 turn/start，已明确对账后恢复。

## ZCode 剩余限制

直接读取软件自身的当前权益接口成功，服务端 active 权益包含 Flash 每日 5,000,000 tokens 和本次领取的一次性 100,000,000 tokens 授权。领取额不等于剩余额度。旧缓存更新时间是 9 月 23 日，已不作为无权益证据。

账号 provider 映射已修复为 account:bigmodel-start-plan / GLM-5.3-Flash，并补齐必需的 low 推理级别。独立 app-server 生成仍返回 `request has been blocked due to unusual activity.`。补齐真实客户端版本 3.14.4 与既有设备上下文后，错误仍相同；已停止该路线自动重试和备用。

当前客户端配置 captcha.enabled=true、skip_model_request=true，所以不能把这次限制写成“必须解验证码”。没有求解、绕过验证码或改身份/代理。证据见 evidence/native-fix/zcode-current-entitlements.jsonl、zcode-live.json、zcode-smoke-events.jsonl。

最小用户事项：只有继续启用 ZCode 独立执行时才需要在原生客户端检查官方安全提示；桌面一直正常、独立接口仍受限时，需要上游确认当前免费 Start Plan 的独立 CLI 使用规则。今天可以直接使用已跑通的 WorkBuddy，不需要重新登录或再发密钥。

## 使用与费用边界

原 Run-Request.ps1 用法不变。默认 WorkBuddy 免费执行 + Codex Luna 监察 + Sol 主脑；config.codex.json 保留原纯 Codex 路线。活动到期会停止免费路线并报告，不自动走新付费 API。主脑与监察仍使用既有订阅，不能宣称整个流程零成本。

当前测试：17 项控制器测试 + 8 项路由保护测试，另有真实模型、文件回读、零积分与原认证文件未变证据。native_support 格式助手来自固定 commit df0c1ad8577c4fb3bc45c0c01141e44f6c994b37（MIT，附 LICENSE/NOTICE）；未安装其模型代理。
