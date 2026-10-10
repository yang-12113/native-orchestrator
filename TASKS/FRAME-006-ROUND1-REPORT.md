# FRAME-006 ROUND-1 验收（2026-10-10）

结论：ACCEPTED_WITH_LIMITS。源码冻结757932f，完整182运行/177通过/0失败/0error/5实际symlink权限跳过。上一轮结束e78c721是启动基线，40d4d58是本轮初始实现，757932f是修正后的验收代码；当前checkout HEAD实时查Git，不把候选当HEAD。

现有Controller.submit/run_one使用原projects/tasks/calls/owner/lease/attempt/spec，官方SDK实际Executor=gpt-6-luna/high、fresh Reviewer=gpt-6.1-sol/high，唯一模型策略config/model-policy.toml，禁止降级。既有SDK0.162.0 bundle、受限check CLI0.162.0-alpha.2；无新API路由/凭据操作/系统修补。旧文字proof核心函数保持字节语义，工程proof由generic verifier分发。

本轮真实SDK2turn，无repair；原生usage159027 tokens，122752 cached input、35002 uncached input、1273 output，合计duration41662ms。SDKturn内有多次推理/工具请求，不能当底层请求次数或费用。日志外存，usage在现有calls表。

候选2a97196117f43ca2d3321dce1aae4f5427903175、tree e02f5b85acf0f8356f2a325324d577f54a4fb8b9；源仓库main/测试文件未变，Controller SQLite tasks=ACCEPTED、calls2 completed。checks+review+read receipt+model/effort+proofhash精确绑定，无fixture_runs或第二个运行数据库。

真实互操作发现控制端预期列表遗漏diff引用，初次合法PASS被拒绝为INCOMPLETE_REVIEW。已补齐第五项diff身份并通过负例；Controller的受限completed-review复核只对同候选/完整日志/已过检查重校验，没有手工改PASS或重放模型。原失败、原SDK日志、补齐前meta均保留；当前proof验证LIVE通过。此专项修复不是完整crash recovery承诺。

ROUND2：完整崩溃对账、main并发变化、文本/语义冲突、串行promotion/CAS；其他后置项remote、managed worktree、Windows上游修复、复杂工程输入。当前只支持单个独立普通Git任务、既有UTF8文本修改、本地候选接纳；不声称生产部署或真实项目main已发布。

DEPRECATION_CANDIDATE：native_rpc/codex_adapter普通transport/lifecycle可进一步迁SDK；旧dynamic-tool/read receipt/restricted checks和repo_materials/quarantine保留，本轮未删除/扩新DSL。
