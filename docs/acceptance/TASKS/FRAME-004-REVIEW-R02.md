# FRAME-004 冻结候选独立复审 R02

结论：**PASS（FRAME-004 模块范围）**；**G1 互操作仍为 INCOMPLETE，不能据此接纳完整链路**。

审查对象为 `cc41455620cea7a44411662eb28f86cd92d8c4d3`，HEAD 与之相同。除既有未提交的 `DEVELOPMENT_STATE.json` 外，无其他工作树改动。首轮 [FRAME-004-REVIEW.md](FRAME-004-REVIEW.md) 保留未覆盖；本复审只写本文件，未运行测试、模型或原生检查。

## 候选与证据核对

- 首轮两项问题已在源码中修复。[probe_check_boundary.py](../probe_check_boundary.py) 现用 `native_check_exec._build_environment` 的 Windows 启动变量白名单；[check_runner.py](../check_runner.py) 在接受 exit 0 前拒绝 `output_complete` 显式非 `True`。新增的 `test_explicit_incomplete_output_cannot_pass_even_below_the_cap` 覆盖了该分支，期望 `ERROR/OUTPUT_INCOMPLETE`，并检查仍保留捕获输出。
- `.runtime/frame-004-reviewed-fake-tests.log` 显示 28 项、1 项跳过、其余通过（`OK (skipped=1)`）。代码中唯一动态 skip 是 symlink fixture；该跳过不等于路径链接行为通过了运行验证，本复审对此仅作静态判断。
- `.runtime/frame-004-reviewed-native-validation/report.json` 报告 `NATIVE_CHECK_RUNNER_VERIFIED`，9 个场景实际状态与期望一致、6 次 command/exec、0 模型回合；7 个实际运行场景的输入均保持不变，另外 2 个场景在派发前拒绝。`runner_candidate_commit` 精确等于本复审候选 SHA。报告五个源码 SHA 与候选工作树实测一致：`check_runner.py` `d43b4256d98c089292d914694923918564e65a28cd17ebd292c2d6a6a71b7cd8`；`native_check_exec.py` `995875850ba3ae19b1f8d1e04c76f7734a3fbc435c254792d4afdf8be222d1ad`；`native_rpc.py` `fee6d95b64f6262937736b244791d82e4ba89d3ef44b0d652dbf0e08a6ed3201`；`execution_contract.py` `99fbd438cc7a2d83923b35010ddc23860d86532c8ba3d058d319fff9278a9746`；`validate_check_runner.py` `82d2e9932cf849f712fccdb3cb56a058bdc3474120a8c666dce2d7401d07a003`。
- `.runtime/frame-004-reviewed-boundary-probe/report.json` 报告边界探针通过、1 次 command/exec、0 模型回合；观察到输入读与 scratch 写成功、输入/控制写和 loopback 连接被拒、输入不变。这个 probe 报告没有记录源代码 commit/hash，故它自身不是源码指纹绑定证据；native validation 的候选提交与源码 SHA 仍可独立核对。其 stderr 有 `Failed to find real location of E:\python\python.exe`。同一诊断也见于 unit/boundary 收集的 stderr；对应 exit code 均为 0，unit 输出明确报告 `Ran 1 test ... OK`，boundary 的 JSON 断言结果正确。本复审未能确定该主机诊断来源，保留为运行环境未知，不将其当成已证实的启动失败。
- 首轮 `.runtime/frame-004-frozen-unified-report.json` 属于旧候选，未拿来声称新候选全量回归通过。本次证据限于上述定向回归及原生场景；未独立重放证据。

## G1 互操作阻断

静态复核确认根代理指出的 schema 不匹配：[execution_contract.py:208](../execution_contract.py#L208)–[209](../execution_contract.py#L209) 的 `validate_contract` 只接受含 7 字段的 catalog entry，缺少 `output_bytes_cap`；[check_runner.py:97](../check_runner.py#L97) 要求字段集合精确含该字段，共 8 项。因此，直接把已通过 `validate_contract` 的 catalog 交给 `run_check` 会在原生派发前以 `INVALID_INPUT` 拒绝。仓库当前没有生产调用点或映射适配器；检索到的 `run_check` 调用仅在验证脚本和测试中。故单模块边界可通过，G1 模块互操作尚未通过，须由后续集成变更及同一 catalog 的端到端测试解决。

除上述 G1 阻断及已注明的证据限制外，本复审未发现两项首轮修复引入的新缺陷。
