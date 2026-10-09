# FRAME-004 冻结候选独立审查

结论：**CHANGES_REQUIRED**

审查对象：`132774a0b54f2ad13066521f8447e6881ff6c745`。只读审查限定的 runner、native executor、probe、验证脚本、测试及 `run_tests.py` 变更；未运行测试、模型或原生检查。

候选证据核对：`.runtime/frame-004-frozen-unified-report.json` 报告 `MOCK_VERIFIED`，123 项、0 failures、0 errors、4 skipped、`passed=true`、0 模型调用；这是统一测试证据，不代表原生通过。`.runtime/frame-004-frozen-native-validation/report.json` 报告 `NATIVE_CHECK_RUNNER_VERIFIED`、6 次 command/exec、0 模型回合；其五个 runner/依赖源码 SHA 与当前冻结候选文件一致。报告的 `candidate_commit=a05f1a…` 按 `validate_check_runner.py` 的赋值来自被检查的计算器 fixture，不是本 FRAME-004 候选提交；代码绑定由报告中的源码 SHA 提供。审查未重放这些证据。

## 需修复

1. **[P1] probe 将未列入白名单的环境变量传入原生 app-server。** [probe_check_boundary.py:43](../probe_check_boundary.py#L43) 只剔除 `OPENAI_`、`AZURE_OPENAI_`、`CODEX_` 前缀，然后把剩余环境传给后续 `Rpc`。当宿主含 `AWS_SECRET_ACCESS_KEY`、`GITHUB_TOKEN`、其他服务令牌等变量时，它们仍被复制到 `codex app-server` 子进程，违反票据“env仅Windows启动变量”的边界。请改成与 native executor 相同的 Windows 启动变量白名单及必要固定变量，并补覆盖非 OpenAI 凭据名的测试/验证。

2. **[P2] 显式不完整输出仍可能收到 PASS。** [check_runner.py:170](../check_runner.py#L170)–[180](../check_runner.py#L180) 只校验输出字符串和长度，没有拒绝 `result["output_complete"] is False`，随后按 `exitCode == 0` 设为 PASS。之后 [check_runner.py:197](../check_runner.py#L197)–[198](../check_runner.py#L198) 只把该标志写入 receipt，不回退状态。触发条件是可注入的 `native_executor`（或未来适配器）返回合法版本/配置指纹、exit 0、低于 cap 的 stdout/stderr，但显式标记输出不完整；receipt 会自相矛盾地报告 `status=PASS, output_complete=false`。在设 PASS 前将该情况变为 ERROR，并增加 runner 用例。

## 未知与限制

本审查只静态检查代码并读取主代理生成的报告；没有独立重放 native profile、输出截断、主机环境或网络边界。报告所覆盖的宿主版本/profile 之外仍属未知。上述两项需修复及相关复核后，方可将本候选评为 PASS。