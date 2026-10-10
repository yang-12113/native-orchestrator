# FRAME-004 / G1 增量独立复审 R03

结论：**接口互操作增量 PASS；G1整体验收 INCOMPLETE**。未发现本次 catalog 接口修复的代码缺陷；4项 symlink 负例因宿主无创建链接权限而跳过，按现有 G1/FRAME-003 边界要求，不能把这些行为写成已验证。

审查对象为 `6db1418935930e8a5131e66ac8b2b38d0fef24a6`，复审时 HEAD 与之相同；当时除既有 `DEVELOPMENT_STATE.json` 修改外无工作树改动，全套临时测试目录已清理。本次只新增本报告；未运行测试、模型或原生检查，R01/R02均保留。

## 已核实的接口修复与证据

- [execution_contract.py:208](../execution_contract.py#L208) 将 `output_bytes_cap` 纳入 catalog 精确字段集合，随后要求 `type(cap) is int` 且范围为 1..1,048,576；[engineering-policy.example.json:63](../engineering-policy.example.json#L63) 示例同步加入 `4096`。布尔值、字符串、缺失、0、超上限均有负例。
- [test_execution_contract.py:391](../test_execution_contract.py#L391) 先执行 `validate_contract`，再将同一个 `policy["check_catalog"]` 原对象直接传入 `run_check`，未做字段转换；fake executor 断言 argv、cwd、scratch、timeout、cap、只读/拒绝根、DISPATCHED binding 与 catalog hash。新增测试通过的日志在全套输出中有明确用例名。
- `.runtime/frame-004-interop-host-fixed-tests.log` 报告49项、0失败、0错误、2跳过。`.runtime/frame-004-interop-frozen-unified-report.json` 报告 `MOCK_VERIFIED`，126项、0失败、0错误、4跳过、0模型调用；其输出明确包含新 cap 负例和 direct-runner 集成测试。这是统一回归，不单独证明原生边界。
- `.runtime/frame-004-interop-frozen-native-validation/report.json` 报告 `NATIVE_CHECK_RUNNER_VERIFIED`，9个场景状态与预期一致、6次 command/exec、0模型回合；7个实际运行场景输入不变，另2个在派发前拒绝。`runner_candidate_commit` 精确等于 `6db1418…`。报告列出的五个 SHA 与当前工作树相符：`check_runner.py` `d43b4256d98c089292d914694923918564e65a28cd17ebd292c2d6a6a71b7cd8`；`native_check_exec.py` `995875850ba3ae19b1f8d1e04c76f7734a3fbc435c254792d4afdf8be222d1ad`；`native_rpc.py` `fee6d95b64f6262937736b244791d82e4ba89d3ef44b0d652dbf0e08a6ed3201`；`execution_contract.py` `29d8c3b74ec70133e0169d020310f802b6d1b27c23e74d6c76a2be148fc20e09`；`validate_check_runner.py` `82d2e9932cf849f712fccdb3cb56a058bdc3474120a8c666dce2d7401d07a003`。其 `candidate_commit=a05f1a…` 是被检查的计算器输入提交，不能当作 FRAME-004 代码提交。

## G1 未决验证与范围

全套日志中的4个 skip 均为 symlink 创建用例：契约路径、工作区源/父路径（2项）、检查输入根。原因是 Windows `WinError 1314`；当前宿主没有证明这些链接负例。源码中相应 guard 可见，但这属于静态核对，不能替代运行证据。其它预检/工作区回归与受限 native runner 场景通过。故接口互操作修复可通过，G1整体 boundary readiness 暂记 INCOMPLETE，直到以宿主支持的链接/junction 夹具验证，或由主代理按票据处理该环境限制。

另有两处报告卫生事项：全套 JSON 摘要不含候选 SHA/源码哈希（native validation 报告含该绑定）；已提交的 [FRAME-004-INTEROP-TEST-REPORT.md](FRAME-004-INTEROP-TEST-REPORT.md) 仍写“等待宿主复测”，与现有复测证据不同步；`git diff --check HEAD^ HEAD` 标出随候选加入的 R02 报告一处尾随空白。本复审未修改这些文件。上述事项不推翻 cap 接口测试结果，但最终状态材料应一致。

本报告只覆盖 G1 契约、工作区与受限检查边界；FRAME-005+G2 的角色 `file_proposal`/`bound_review` 和自动工程主链未实现，本结论不延伸到那些能力。