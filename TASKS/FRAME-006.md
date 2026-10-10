# FRAME-006 ROUND-1：SDK direct-worktree 接入现有 Controller

用户本轮完整请求来自 attachments/f02876f4-830e-4f49-8bf5-4277210fbe1c/已粘贴的文本.txt；它取代此前“下一票据未实施/沿用上一轮预算”的说明。

启动实查：开发 HEAD=e78c72142334ec9dcf509b38b35dae84f45297db，codex/engineering-v03，工作区干净；主仓库 HEAD=ec93fb51246f711d169f2aeb2df3a151c39969ae。ea73c49是reconciliation前历史，9e062d6是已接纳pilot代码候选，不是当前HEAD。当前HEAD始终用git rev-parse核实，不在可变文件中伪造自引用SHA。

唯一目标：现有Controller.submit/run_one和既有projects/tasks/calls SQLite、owner/lease/attempt/spec/proof体系自动跑通普通工程Task→SDK→candidate→批准checks→fresh独审→本地ACCEPTED。没有新调度数据库/fixture_runs表；不重写旧文本流程或删G1/quarantine/RPC能力。

模型策略唯一源=config/model-policy.toml；中文注释。executor/worker=Luna High，reviewer/escalation=Sol High，不默认max/xhigh，不静默降级。SDK.models零turn已验证两者；receipt=.runtime/frame006-model-probe-20261010-a26f/receipt.json，policy SHA=8749350fc3865e3808b497850f8a2947a804577274eb988ac0844b28a5dc5ea6。SDK继续用既有隔离安装0.162.0 bundle，正常复用登录，不做凭据操作。

文件白名单：orchestrator.py（薄分发/SDK预算调用）、repo_execution.py（一次工程流程与proof验证，无Manager）、model_policy.py、config/model-policy.toml、codex_sdk_adapter.py、run_tests.py、新test_model_policy.py/test_repo_controller.py、SDK对应测试、FRAME006文档/证据/权威状态。run_direct_worktree_pilot.py及历史验收不重放；旧原生RPC/check/material/workspace语义不放宽。legacy文字proof校验函数/策略保持，以新的generic verifier分发工程proof。

新真实fixture必须全新：.runtime/frame006-round1-20261010-a26f，source是自建UTF8小Git仓库，缺陷add返回减法，固定test_calculator.py保护，允许修改仅calculator.py。Controller生产入口enabled且approved_repo_roots仅这一个source；task branch/worktree和独立detached review checkout由Controller管理。源main不晋升，本轮只接纳candidate，不做remote/promotion。

本轮新预算：目标Executor1+Reviewer1，SDK真实turn硬上限3（与上一轮2turn分开计）。checks FAIL可最多repair1再首次Review，共3；Review FAIL不接纳，若没有完整修复+再审预算则NEEDS_REVIEW，不沿用旧PASS。owner/lease/spec栅栏和调用意图在派发前；未知结果先decision不重放。

最小必要负例：policy解析/禁降级，真实SDK参数与usage记录，checks FAIL不Reviewer，Review FAIL不ACCEPT，repair新SHA旧证失效，环境ERROR=BLOCKED_ENVIRONMENT不质量返工，exact proof绑定/篡改拒绝。先fake+新自有Git fixture，旧回归继续无新失败；Windows已知symlink skip如实保留。真实调用只用于最后验收。

接纳proof至少绑定task/spec/attempt/base/candidate/tree/manifest/changedpaths/check receipt/reviewer model-effort/session/review/proofhash；Review输入含TASK/criteria/checks/diff，fresh只读thread，严格最终JSON本地验证、真实读取活动留证据。usage记录原生token/cached/output/total、duration及已有活动计数，不做金额路由系统。

ROUND1禁止remote/push/Actions、managed worktree、ACL/helper/runtime修补、Dashboard、复杂队列/DAG、多Reviewer/大代理拓扑、rebase/stash/reset/clean、自动升级、大迁移/重设计SQLite、生产部署。完整crash/main并发冲突/promotion CAS矩阵明确留ROUND2；本轮只能称本地工程接纳，不声称完整发布恢复。

当前由root完成接线与必要fake验证；最终真实质量闸门是独立Sol High Reviewer。无额外开发模型调用；严格留2–3turn给本轮真实Controller样例。
