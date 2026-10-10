# FRAME-005 SDK 真实样例检查点（2026-10-10）

源码候选 9e062d607dfc67c6d6d911ce716c06e93c2c612c。原148项回归143通过/5 symlink权限跳过，新增SDK fake负例9/9通过，无失败。旧Controller/RPC/check/workspace/material源码SHA未变。

自有fixture从减法缺陷开始，baseline tests确实FAIL。Luna/max通过官方SDK0.162.0/匹配CLI0.162.0在task branch/worktree直接把calculator加法修正，root验证白名单并冻结。已有受限check runner/CLI0.162.0-alpha.2确定性测试PASS。fresh read-only SDK Reviewer实际执行git diff和两个git show读取冻结文件，输出PASS；root将读取字节与candidate blobs实算匹配。

候选与fixture main都为15bbb6e6d3a020db71e792d7427eac5d2f98b9c5；SQLite fixture_runs=ACCEPTED，两个calls均completed。真实SDK turn=2，repair=0，remote=DISABLED。完整artifact/SHA和读取回执见EVIDENCE-BINDING，限定接纳见PILOT-ACCEPTANCE。

报告原生usage合计130399 tokens，其中94464 cached input、33602 uncached input、2333 output。SDK turn内部有多次底层推理/工具循环，2个turn不能说只有2个底层请求，也不能换算订阅费用。没有额外模型spike或subagent。

只接纳fixture slice。生产Controller工程队列/proof未接线，完整并行promotion/CAS/crash recovery、SDK只读写拒绝主动负例、OS symlink和remote未验收。SDK角色特定MXC路径本次工作，不代表全局Windows elevated sandbox已修复。无ACL/helper/runtime补丁、无凭据/全局配置操作；既有主仓库运行源码、业务与旧数据不变。

后续FRAME006接入已验证接口；既有G1、材料子模块保持历史范围。没有为了样例PASS把G2/G3/G4全部标完成。
