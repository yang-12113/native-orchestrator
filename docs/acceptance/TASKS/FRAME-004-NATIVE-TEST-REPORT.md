# FRAME-004 原生辅助测试报告

新增 `test_native_check_exec.py`，以 FakeRpc 覆盖权限配置、路径边界、敏感环境过滤、版本/profile拒绝、authority失效、超时、输出完整性、RPC不重试与关闭流程；验证 launcher 错误、exit 124、traceback 中 PermissionError 都作为执行错误保留绑定诊断，而普通非零业务结果仍可返回。单流均低于上限时合计可超过上限。验证 LOCALAPPDATA 保留、SYSTEMROOT/LOCALAPPDATA 任一缺失时在 RPC 前拒绝，且临时环境补丁会恢复。

标准 unittest 自动发现运行：`python -B -m unittest discover -s . -p test_native_check_exec.py -v`，13 项通过。FakeRpc 不启动进程、模型或网络；配置和 RPC 日志留在每项独立的 `.runtime/frame-004-native-tests/case-*`。Python 启动输出 `Failed to find real location of E:\python\python.exe`，本次未出现 WinError 5，测试通过。
