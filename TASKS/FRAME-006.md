# FRAME-006：接入已验证 SDK 工程接口（下一票据，未实施）

前置：FRAME-005-SDK-PILOT-ACCEPTANCE仅接纳自有fixture。源码9e062d6、原148项回归及新9项SDK fake通过；真实SDK turn=2，candidate/fixture main=15bbb6e。不要重放既有fixture或误将其当生产工程队列完成。

下一范围：在现有Controller中增一个明确可关的工程任务入口，复用同一SQLite tasks/calls/owner/attempt/spec_version/lease和预算；默认关闭生产工程gate。将试点的范围验证、candidate、批准checks、fresh SDK Review、proof读取/失效和有限返工接到这一入口。逐步复用已验收接口，不重写旧文本run_one或新建另一生产数据库。

只需一个工程job，不建设复杂队列/Dashboard/多Reviewer。普通输入由标准task branch/worktree承载；对Git metadata/保护路径/目录链接的限制和候选审查前后漂移检查先补fake负例。当前单次driver还没有通用生产保护、自动恢复或全面审查；不直接向用户正式数据开放。

验证重点：SDK响应schema/模型档位/cwd/预算/租约失效、保护路径或未批准文件改动、环境ERROR不质量返工、新SHA使旧PASS失效、exact candidate读取与review proof、本地状态重启、文字基线回归。前述fixture仅验证模型真实读写/审查；生产代码独审另按窄任务安排。

真实模型预算：本轮已用2/3；这张下一票据不自动增加预算或再跑live。repair/check/review状态机先fake；新的真实验证需记录新fixture和明确预算，不能盲重放不确定turn。

后置：latest-main merge/并行冲突、promotion CAS/完整Git-DB崩溃恢复在FRAME007/008；remote先local bare；真实push、凭据、生产环境及系统配置仍需用户确认。Windows只记录健康状态，不自行改ACL/runtime/helper。

所有权：root核心整合与状态；在真正开始代码前补齐修改白名单/确切契约和冻结候选。测试与最终代码独审分离，辅助仅窄票据。当前这张票据仅定义下一动作，不含新实现。
