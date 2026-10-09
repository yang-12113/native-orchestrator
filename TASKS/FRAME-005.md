# FRAME-005：SDK direct-worktree 最小纵向样例（修订2，2026-10-10）

依据：用户外部包对账请求与 PLAN-RECONCILIATION-20261010.md。旧材料子模块及提案证据保留；旧“所有工程只能proposal”的后续指令由本票据替代。

目标：新自有小Git仓库、一个 task branch/worktree，官方SDK gpt-6-luna/max直接修改 calculator.py；控制端核验范围并冻结candidate；确定性检查PASS后fresh/read-only Reviewer，接纳同一candidate。生产Controller工程接线在FRAME006，不能以fixture样例声称生产队列已开放。

root白名单：codex_sdk_adapter.py、run_direct_worktree_pilot.py、test_codex_sdk_adapter.py及本阶段文档/状态/报告。现有Controller/check/RPC/material/workspace源文件不改；新driver仅在自有fixture复用Controller SQLite连接、事务和调用预算，不能修改实际运行数据或形成第二个生产队列。本轮没有开发subagent。

精确fixture：.runtime/sdk-direct-pilot-20261010-52a7，必须新建。source为自建仓库，task为sibling worktree，branch task/sdk-direct-pilot-20261010-52a7。仅 calculator.py 允许修改；test_calculator.py固定加法测试及其他路径全保护。普通目录，无链接/子模块。root用literal pathspec、禁hook/filter/signing的Git命令提交/冻结，只允许这个fixture自己的main做本地ff-only；真实项目main不推进。

SDK：.runtime/sdk-0.162.0-pilot-52a7的官方0.162.0及匹配CLI0.162.0；初始化/参数probe证据为 .runtime/sdk-capability-20261010-52a7/report-attempt2.json。第一次report.json是已修正的探针字段名错误，不是上游故障。该probe没有模型turn，不能冒充实际文件权限。

模型固定 gpt-6-luna/max，Executor workspace_write、Reviewer read_only，approval deny_all；网络/记忆/多代理/apps/web关闭，SDK正常复用现有登录，不读/复制/改auth，不改global配置/ACL/helper/runtime，不调用sandbox setup。非chatgpt账户、模型/档位/cwd不匹配在派发前拒绝；不降级大权限或新付费路由。

真实turn目标2、硬上限3、repair最多1；不另花spike turn。检查先FAIL可以repair再首次Review共3；Review FAIL之后repair还需第四次复审，本次预算不足就停止NEEDS_REVIEW，不能沿用旧PASS或浪费第三次。每次turn先SQLite预算/意图、校验owner/lease，未知执行不重放。

输出只取TurnResult.final_response，<=8192 UTF8 bytes、summary<=400字符；中间messages/items/usage外存。Review本地严格JSON字段/类型/常量验证，绑定task/spec/attempt/base/candidate/完整manifest/check receipt SHA；检查及审查前后复核输入和Git。新SHA使旧PASS失效，真实模型读文件的命令项留证据。

先fake负例→冻结源码commit→真实Executor→范围核验/candidate→批准checks→freshReviewer→fixture本地接纳。环境问题只记BLOCKED_ENVIRONMENT，未知派发先对账；不修改系统或真实数据。SQLite为fixture运行权威，receipt是证据；完整并行/promotion/crash恢复矩阵和生产Controller接线尚未完成。
