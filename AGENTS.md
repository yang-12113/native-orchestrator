# 项目协作入口

用户直接指令优先。用户只要求查询/检查时仅只读；已授权的实施按当前票据推进，不重复索要同范围授权。

先读 PROJECT.md → MAINLINE.md → 权威 DEVELOPMENT_STATE.json → 当前 TASKS 票据，再核对 git status、HEAD和工作树。上下文压缩后也按此顺序，不重读全部聊天或日志。

项目地图：PROJECT.md是稳定目标；ENGINEERING_PLAN.md是阶段/分工；DECISIONS.md是已确认选择；TASKS/是目标/边界/验收与证据。动态开发状态唯一权威：E:/零碎/native-orchestrator/DEVELOPMENT_STATE.json；工作树内是同步副本。运行时调度唯一权威仍为对应数据目录SQLite。

源码稳定目录 E:/零碎/native-orchestrator；隔离开发目录 E:/零碎/native-orchestrator-v03，分支 codex/engineering-v03。不得以目录名或文档PASS代替当前commit与证据核对。

主代理独占主线/状态/任务派发/核心整合和最终接纳；每个其他文件一个作者。Luna只负责其票据白名单，作者、测试和最终审查分开。新领域fork_turns=none，只给必要文件/commit/断言；短报告回事实/阻断/引用，源码与日志留文件。代理意见是待核验数据，不能自行扩任务或写主线/系统记忆。

检查入口：开发工作树 python -B run_tests.py --report .runtime/<新的报告>.json。真实Git工作区用例只在该票据已授权时设置 FRAME003_ENABLE_REAL_GIT_TESTS=1，使用每次全新的自有fixture。原生执行/模型验证须按票据的精确命令、根目录和预算；不运行旧测试__main__覆写历史证据。

禁止触碰：原data-live、认证/私有配置、旧ACCEPTANCE.json、原校招业务；不自动stash或清空用户变更、不盲重放未知执行、不使用unsandboxed/full-access替代失败、不新增付费API/外部消息/推送。

完成流程：实现→必要检查→冻结commit→独审→确认问题修复/相关复测→按关卡实际验证→主代理接纳。保存候选SHA、结果与证据、未决事项、下一操作到权威状态并提交Git。跳过/未知/MOCK不能标LIVE或完整工程通过。失败留证据、只回退本次失败提交。

