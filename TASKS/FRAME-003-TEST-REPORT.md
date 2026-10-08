# FRAME-003 实际测试记录

最新修正版：18项真实Git测试并入统一七模块。96项运行、93通过、0失败/错误、3真实OS链接权限跳过；其中工作区18项16通过/2链接跳过。报告.runtime/frame-003-reviewed-unified-report.json，日志.runtime/frame-003-reviewed-unified.log。

独审追加两负例已单独通过：workspace切共享源branch后freeze拒绝且源HEAD/字节不变；note[1].txt使用literal pathspec，仅批准字面路径改变、兄弟文件blob不变、重复apply/freeze不多commit。

之前真实Git16项14通过/2跳过；root新小仓库attempt2 create/apply/freeze、重复提案/冻结幂等、原文件SHA不变通过，.runtime/frame-003-real/root-workspace-attempt2-report.json。attempt1因Windows文本fd换行转换导致哈希失败，保留APPLYING意图未重放；三处os.open已加O_BINARY。短fixture避免Windows路径超限，未知APPLYING注入依据持久状态而非固定fence次数。

未验证：真实OS symlink因WinError1314跳过，不作为权限/隔离通过。没有原生模型调用，没有批准工程检查，正式数据/校招/auth/global配置未改。所有真实Git操作只在全新的各自.runtime/frame-003-test-*和root-owned小仓库。

作者角色：Luna实现repo_workspace.py；另一Luna写独立测试；root整合binary/detached/literal修复并宿主执行实际测试。独立审查另用新上下文，尚未以这些测试证明完整工程运行时通过。
