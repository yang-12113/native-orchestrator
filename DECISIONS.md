# 已确认设计选择

只登记用户认可或有代码/证据支撑的选择；建议不自动变决策。动态状态不在此重复维护。

- D001：SQLite是运行时唯一调度权威；原目录DEVELOPMENT_STATE.json只管理开发主线，工作树副本非第二权威。依据：已有控制器与ENGINEERING_PLAN.md。
- D002：保留v0.2.1文本基线；v0.3先小仓库、受限UTF-8文件提案、干净已提交Git输入。脏/非Git拒绝，不自动stash。依据：FRAME-002/003已独审证据。
- D003：所有权威检查、预算与接纳用当前owner/attempt/spec/有效租约；未知副作用落意图并先对账，不自动重放。依据：FRAME-001/003。
- D004：候选工作树必须持续detached；Git pathspec使用literal；只冻结批准提案文件，不推进源共享branch。依据：FRAME-003独审与真实Git负例。
- D005：实际检查首选官方command/exec，无thread/turn/模型；私有checks profile只读输入、scratch可写、控制与证据禁止访问/写、网络关闭。禁thread/shellCommand等无隔离替代。依据：FRAME-004-Q01及2026-10-09原生边界探针；完整runner仍待验收。
- D006：主代理维护主线、Luna窄任务、作者/测试/审查分离；新领域独立上下文、事实短报告与证据外存。共享文件系统不当物理隔离或零记忆占用。依据：用户当前明确指示与PLAN-R01。
- D007：原校招业务和旧正式数据保留；后期验证只用明确副本；自动旧数据迁移需单独验收，不能补造PASS。依据：原用户范围、PROJECT.md和FRAME-009计划。

