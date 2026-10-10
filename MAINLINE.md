# 主线恢复入口

目标见 PROJECT.md，协作/保护边界见 AGENTS.md。动态开发状态唯一权威：E:/零碎/native-orchestrator/DEVELOPMENT_STATE.json；开发树内为同步副本。运行调度唯一权威是对应数据目录 SQLite。

唯一开发工作树 E:/零碎/native-orchestrator-v03；branch codex/engineering-v03。当前开发 HEAD 必须运行 git rev-parse HEAD（refs/heads/codex/engineering-v03）解析；冻结验收源码 379c21041887a11e11e2144a6f1e4402d300554a，最终文档 checkpoint 是其源码不变后继，最终字面 SHA 见审核包 GIT_STATE.txt。不要把源码候选当 checkout HEAD。

FRAME-006 FINAL ACCEPTED_WITH_LIMITS / V1_LOCAL_ENGINEERING_FINAL_ACCEPTED_WITH_LIMITS；验收 TASKS/FRAME-006-ROUND3-ACCEPTANCE.json。新对话持久恢复成功；真实生产 Controller Task→lease/budget/spec/attempt→SDK Executor→freeze→native checks→fresh readOnly Reviewer→proof→ACCEPTED→本地 promotion 闭环通过，各 candidate 身份精确一致。Round2 crash/冲突/CAS 回归通过。

模型唯一源 config/model-policy.toml：Executor GPT-6 Luna/high，Reviewer/Escalation GPT-6.1 Sol/high，禁止降级。本轮真实 SDK turns=2；冻结回归 228：223 PASS / 0 FAIL / 0 ERROR / 5 SKIP。Reviewer 实际写拒绝由零turn同runtime readOnly command/exec 验证；Controller 拒绝 candidate/review 输入改变。

proof/2记录SDK/runtime/model/effort/sandbox；proof/1、未知schema、缺字段或边界代码升级需 NEEDS_RECONCILIATION，不补默认、不自动重放。安装runtime版本改变本身不使旧candidate失效。

限制：普通已有tracked UTF8文本、单独立任务、普通本地Git worktree。UNVERIFIED_WINDOWS_SYMLINK：5项OS symlink权限SKIP；实际junction及Git120000拒绝通过，普通非symlink工程不阻塞。保留data-live/业务/私有配置/旧验收/用户变更，不改ACL/helper/runtime，不盲stash/reset/clean。

下一步：停止扩建框架，开始用于真实项目；GitHub remote / Codex managed worktree / Windows upstream sandbox 作为后续增强，不属于 V1 阻塞项。 无继续开发框架的活动票据。
