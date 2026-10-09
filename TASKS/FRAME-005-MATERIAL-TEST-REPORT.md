# FRAME-005 材料测试报告

fake-only `unittest` 已启动（14 项；无 Git/native/model/network 进程）。此主机在 fixture `.runtime` 上执行 `Path.resolve(strict=True)` 得到 WinError 5，导致候选根校验前多项用例中断；日志保存在 `.runtime/frame-005-material-tests/logs/`。OS symlink 因 WinError 1314 跳过；未降低 guard，需由主机环境复跑。

代码核查待复跑确认：`read()` 未复核当前 manifest/Git，输入漂移后仍可能送出缓存；offset 到 EOF 会追加 `returned_bytes=0` 回执；`AGENTS.md` 未列入保护集。独立测试已覆盖这三项；实现未改。
