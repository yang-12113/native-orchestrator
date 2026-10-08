# FRAME-002：工程契约与派发预检

状态：IN_PROGRESS，PLAN-R01已PASS。主责：主代理；Luna/max负例与测试，独立Luna只读验收。旧文本验收候选bda744b，发布基线b97788f，开发起点810e4b7（仅追加计划文档）。本票据首个代码候选75bd122被独审指出路径父子重叠问题，修复后另行冻结。开发工作树E:\零碎\native-orchestrator-v03，分支codex/engineering-v03。

授权依据：用户把剩余自动化交给主代理，并要求固定主线、做计划和分配。范围限自动工程控制器，不增加校招业务功能、改全局设置/凭据或迁移正式旧库。运行码须在独立开发工作树实施；本次创建票据不等于工程能力已经启用。

目标：定义可版本化的工程任务契约和派发前能力/范围/路径/最低预算检查，为后续工程工作区和检查ID目录提供固定接口。保留已有文本任务语义与59项基线。

主代理候选文件：新增execution_contract.py、必要接入orchestrator.py、工程契约schema/示例；确切白名单在实际派发前冻结。Luna测试候选文件：test_execution_contract.py及其隔离fixture，不能改主模块、主线状态或验收标准。无同文件并行作者。

本阶段冻结写白名单：主代理execution_contract.py、execution-contract-v03.example.json、engineering-policy.example.json、run_tests.py及本票据/主线状态；Luna仅test_execution_contract.py和TASKS/FRAME-002-TEST-REPORT.md。先实现独立只读预检入口，不将repo_patch接入旧队列；其他共享运行模块本阶段不改。

API：ContractError(ValueError).code；canonical_hash(value)；inspect_git_input(repo_root)返回root/head/tree/clean；validate_contract(contract,policy,usage=None,repository_probe=inspect_git_input)返回status=CONTRACT_VALIDATED、dispatchable=false、contract_hash/policy_hash/input_hash/minimum_native_turns/worst_case_native_turns。正例必须绑定可信policy中的授权、roots、角色能力凭据与检查目录；工程路由未实现，所以契约通过也不启动模型或派发任务。

验收：

- 明确artifact_text/public_source/repo_patch的运行方式，不支持能力在启动真实模型前拒绝。
- 工程输入绑定直接用户范围、干净已提交Git基线、任务/规格/请求ID、文件白名单、禁止路径、环境/路由版本与检查目录指纹。
- 模型/思考档及所需能力可观察验证，不能隐式降档或把未知能力当可用。
- 预算估算包括真正需要的规划、执行、审查、返工与通知；项目及角色预算仍在写锁下预留，不借新ID重置。
- 契约校验不执行模型、工程命令、提交或迁移。v0.3样例仍不可派发，直到相应路由与关卡实际通过。
- 负例覆盖非法/链接/越界路径、脏/非Git基线、规范冲突、未批准检查、能力/版本/预算不匹配；未知项目依赖与退款/重试语义保持明确。
- 现有59项回归保持有效，新增是有意义的失败/预检断言，不用同实现复制测试冒充验收。

检查与报告：只用新的隔离目录和假路由先验证，禁pycache，不运行旧测试__main__写原证据。源码commit与结果绑定；报告status/checks/blockers/evidence_refs，细节外存。只由主代理更新MAINLINE和DEVELOPMENT_STATE。

完成：最小实现和对应测试通过、冻结候选、独立审查通过，记录接口供FRAME-003/004依赖。仅完成契约预检不能标记工程执行/权限隔离/发布恢复通过。
