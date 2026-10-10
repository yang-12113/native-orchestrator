# 实际验证记录

验证时间：2026-10-06T13:51:28.045957+08:00（Asia/Shanghai）；总体 PARTIAL。源码 hash：`3f0100e43349bf87c35c396c34338793aa26968961fb41e62da25099db438393`。

自然语言项目 `p-52d8213273204455` 首次执行：主脑规划 1、执行 1、独立监察 1、最终主脑 1；总计 4 个原生角色回合。相同 RequestId 再次运行仍是同一项目、相同次数。

两阶段 CSV 与官网来源 CSV 均已 ACCEPTED。保留第一轮 shell 拒绝、依赖证据不足、漏件和错误哈希等失败证据；未把成功挑出来充作全部记录。独立监察的实际工具回读凭证在各 attempt 的 review-read-receipts.json；早期回合在原生事件中留有相同工具调用。

当前回归：17/17 模拟程序测试通过；实际子进程后台/停止/强杀/恢复通过，模型使用替身；MCP 6 个工具的真实 stdio 回报与白名单通过。真实模型与替身测试严格分开。

| 检查 | 结果 | 证据状态 | 说明 |
| --- | --- | --- | --- |
| T01 | PARTIAL | LIVE_VERIFIED | Codex Sol/Luna pass; ZCode/WorkBuddy target routes blocked |
| T02 | PASS | LIVE_VERIFIED | new threads; distinct worker/reviewer IDs; no fork |
| T03 | PARTIAL | MOCK_VERIFIED | 55k Unicode worker output outside master; native master messages separately audited |
| T04 | PASS | LIVE_VERIFIED | actual MCP wire bounded and valid JSON |
| T05 | PASS | MOCK_VERIFIED | fake completion/missing artifacts never ACCEPTED |
| T06 | PASS | MOCK_VERIFIED | automatic quality rework; native insufficient dependency evidence also refused |
| T07 | PARTIAL | LIVE_VERIFIED | capability mutation/traversal denied; normal read pass; OS write/read contrast UNKNOWN |
| T08 | PASS | MOCK_VERIFIED | transactional leases across two controllers; native parallel routes not stress-tested |
| T09 | PASS | MOCK_VERIFIED | real background process completed without observer; model replaced |
| T10 | PARTIAL | MOCK_VERIFIED | real process kill/restart; ambiguous task needs reconciliation; ephemeral native session not resumed |
| T11 | PASS | LIVE_VERIFIED | same natural request ID reused with no additional native calls; durable mock duplicates |
| T12 | PARTIAL | MOCK_VERIFIED | bounded errors/budget/no paid fallback; no deliberate exhaustion of real entitlement |
| T13 | PASS | LIVE_VERIFIED | native PASS with incorrect manifest hash rejected; malformed mock review refused |
| T14 | PARTIAL | SOURCE_CONFIRMED | effective memory config off and independent homes; global backend memory sources not fully observable |
| T15 | PASS | LIVE_VERIFIED | fresh Sol receives bounded accepted state and gives version-bound action |
| T16 | PASS | LIVE_VERIFIED | actual CSV and separate official HTTP refetch independently read |
| T17 | PASS | MOCK_VERIFIED | injection text cannot alter state machine; real constrained capability also checked |
| T18 | PASS | LIVE_VERIFIED | turns/tokens/reply bytes measured; missing monetary/request costs UNKNOWN |

主脑观测到 7 个实际角色 turn 输入，最大 user-message 1109 bytes，worker 测试标记匹配数 0。这是客户端真实 turn/start 输入边界审计；没有抓取服务端重构后的全部系统提示。原生内置前缀明显占用 tokens，不能声称上下文消耗为零。

本轮全部观测到 25 个独立原生 thread 回合，包含失败规划、失败验收、smoke 和权限探测。已观测累计 token 数据 {"totalTokens":448057,"inputTokens":444136,"cachedInputTokens":162560,"outputTokens":3921,"reasoningOutputTokens":79}。这是每个原生线程最后的累计 tokenUsage；HTTP 模型请求次数及货币成本 UNKNOWN。共享账号额度前后见 native-probe.json 与 usage-after.json，不能全归因于本工程。

不会把 ZCode 连接成功算作模型成功，也不会把原生登录算作活动免费。ZCode/WorkBuddy 详见 BLOCKERS.md。现有仓库编辑与通用工具执行未实现。没有自动安装登录服务或跨设备公开端口。

复验命令在 README.md；机器检查表 ACCEPTANCE.json；原始工件路径、哈希、角色元数据与观测数量在 evidence/validation-summary.json。

## 当前 v0.2.0 补充

17 个控制器测试与 8 个路由测试通过。WorkBuddy 原生 exact model、服务端 credit=0、原认证文件未变、完整执行与独立监察全部实测。默认生产项目 p-3f0ae85006304647 已 ACCEPTED。最新证据 evidence/native-channel-update.json，运行 Codex 0.160.1。ZCode 当前权益已实测，独立执行仍 BLOCKED；之前模型/免费状态表以此补充为准。
