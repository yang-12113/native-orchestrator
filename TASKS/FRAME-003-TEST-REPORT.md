# FRAME-003 测试报告

## 主代理实际验收记录

最终真实Git套件：16项运行，14通过，0失败/错误，2项真实OS链接创建权限跳过。统一七模块：94项运行，91通过，0失败/错误，3项真实链接权限跳过；原78项回归有效。报告`.runtime/frame-003-unified-report.json`，日志`.runtime/frame-003-unified-run.log`。这些是本机真实Git与假模型组合，原生模型调用0；不证明工程OS隔离。

root小仓库实际验证：新的attempt=2完成detached创建、批准文件修改、候选commit、重复提案和重复冻结幂等，原源码文件SHA前后相同；报告`.runtime/frame-003-real/root-workspace-attempt2-report.json`。attempt=1因Windows文本模式LF转CRLF而失败，保留APPLYING意图，未盲重放。实现修复三处os.open为O_BINARY。

首轮长fixture路径超Windows限制，保留14 errors/1 skip/1 pass现场；第二轮短路径剩1个过早authority故障注入的测试问题；按持久APPLYING状态注入后第三轮通过。夹具路径修正与业务断言分开，没有清理未知workspace或修改正式数据。

状态：两轮实测仍有失败；未知 APPLYING 故障注入已修订，等待主代理第三轮验收。

数量：首轮 16 用例，14 errors、1 skip、1 pass，主要因 WinError 206 长路径。短路径第二轮 16 次，13 pass、1 failure、2 个真实 OS 链接 SKIP。

第二轮失败：故障回调在持久 APPLYING 意图写入前就拒绝；记录仍为 READY，模块正确允许后续新授权。测试现改为读取 `workspace.control.json`，观察到 APPLYING 后才拒绝，并断言目标未写、记录仍 APPLYING、重放为 RECONCILIATION_REQUIRED。

修订：fixture 使用 `cNN-<6位UUID>`，测试名映射在 `case-map.json`；filter 配置拒绝时要求 HEAD 不变且 marker 未触发，另验证 hook/GPG/SSH tripwire 冻结不执行。

证据：`test_repo_workspace.py`（16 用例，AST 解析通过，作者未重跑）；两轮实际结果据主代理宿主摘要。链接 SKIP 不作为 OS 链接证明。
