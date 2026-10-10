# FRAME-004 Q02 只读核查

结论：本地 `native_check_exec.py:288-305,437-476` 启动 app-server 的环境保留 PATH/SYSTEMROOT/WINDIR/COMSPEC/PATHEXT，但缺 LOCALAPPDATA；command/exec 请求只补 TEMP/TMP 与 Python 变量。MXC 文档明确 Windows ProcessContainer 必需 SYSTEMROOT、LOCALAPPDATA；Codex 的 Windows 核心环境列表也含 LOCALAPPDATA、SYSTEMDRIVE、PROGRAMFILES 等。故 LOCALAPPDATA 是最强缺项候选；现有探针不是单变量 A/B，不能确认因果。未记录任何环境值。

报错原文未在本地或可查的 OpenAI/MXC 源码中定位到具体实现，无法确认它解析的目录/函数。HRESULT 0x80070003 对应 ERROR_PATH_NOT_FOUND，只能证明某路径缺失。

主代理后续实测：单补LOCALAPPDATA的新fixture仍报相同launcher错误；按官方Windows启动目录/用户上下文变量白名单补齐后，真实runner8场景通过。证据分别.runtime/frame-004-runner-real-20261009-b/report.json与.runtime/frame-004-runner-real-20261009-c/report.json。已确认缺启动上下文变量的组合问题，尚未逐个消融定位除LOCALAPPDATA外的具体必需变量，不将原先的候选推断当因果结论。没有继承任意认证变量或变更全局配置。

协议的 CommandExecResponse 只有 exitCode/stdout/stderr，无状态或 timedOut 字段。已报 exitCode=1+stderr 是普通命令响应，不能结构化区分 launcher 失败和检查失败；执行前/启动错误可能作为 JSON-RPC error。通用 command/exec 超时路径返回 exitCode 124；Windows sandbox 路径超时由 capture 标记并作为错误传播。此项目 RPC 等待超时映射为 COMMAND_TIMEOUT/NATIVE_TIMEOUT，runner 最终记 ERROR；真实非零退出映射 FAIL。

引用：本地 `native_check_exec.py:288-305,437-496`、`native_rpc.py:91-104`、`check_runner.py:156-178`；[MXC schema](https://github.com/microsoft/mxc/blob/main/docs/schema.md)；[Codex Windows 核心环境变量](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/shell_environment.rs)；[command/exec 响应协议](https://github.com/openai/codex/blob/main/codex-rs/app-server-protocol/src/protocol/v2/command_exec.rs)；[command/exec 实现](https://github.com/openai/codex/blob/main/codex-rs/app-server/src/command_exec.rs)；[Windows sandbox 超时处理](https://github.com/openai/codex/blob/main/codex-rs/core/src/exec.rs)；[HRESULT_FROM_WIN32](https://learn.microsoft.com/en-us/windows/win32/api/winerror/nf-winerror-hresult_from_win32)。
