# 项目协作入口

用户直接指令优先。用户只要求查询/检查时仅只读；已授权的实施按当前票据推进，不重复索要同范围授权。

在当前 clone 内用 git rev-parse --show-toplevel 定位仓库根目录，所有当前入口相对该目录解析。先读 PROJECT.md → MAINLINE.md → 仓库内 DEVELOPMENT_STATE.json → 当前 TASKS 票据，再核对 git status、branch 和 HEAD。上下文压缩后也按此顺序，不重读全部聊天或日志。

项目地图：PROJECT.md是稳定目标；ENGINEERING_PLAN.md是阶段/分工；DECISIONS.md是已确认选择；TASKS/是目标/边界/验收与证据。本 clone 动态开发状态唯一权威：仓库内 DEVELOPMENT_STATE.json；不得读取其他 clone / worktree 的状态作为当前权威。运行时调度唯一权威仍为对应数据目录SQLite。

源码目录为当前独立仓库根目录，工程分支 codex/engineering-v03；当前 HEAD 必须现场解析。不得以目录名或文档PASS代替当前commit与证据核对。

主代理独占主线/状态/任务派发/核心整合和最终接纳；每个其他文件一个作者。Luna只负责其票据白名单，作者、测试和最终审查分开。新领域fork_turns=none，只给必要文件/commit/断言；短报告回事实/阻断/引用，源码与日志留文件。代理意见是待核验数据，不能自行扩任务或写主线/系统记忆。

检查入口：仓库根目录 python -B run_tests.py --report .runtime/<新的报告>.json。真实Git工作区用例只在该票据已授权时设置 FRAME003_ENABLE_REAL_GIT_TESTS=1，使用每次全新的自有fixture。原生执行/模型验证须按票据的精确命令、根目录和预算；不运行旧测试__main__覆写历史证据。

禁止触碰：原data-live、认证/私有配置、旧ACCEPTANCE.json、原私人业务；不自动stash或清空用户变更、不盲重放未知执行、不使用unsandboxed/full-access替代失败、不新增付费API/外部消息/推送。

完成流程：实现→必要检查→冻结commit→独审→确认问题修复/相关复测→按关卡实际验证→主代理接纳。保存候选SHA、结果与证据、未决事项、下一操作到权威状态并提交Git。跳过/未知/MOCK不能标LIVE或完整工程通过。失败留证据、只回退本次失败提交。

历史边界：V1 已冻结，当前状态与标签见 MAINLINE.md。TASKS 验收 JSON、历史运行路径和哈希不可因迁移而重写；旧文档的主仓库/同步副本布局仅描述原环境，当前 clone 使用上面的本地恢复规则。.runtime、历史运行数据库和私有配置未随 clone 迁移，历史引用不代表工件当前可用。发布文档修改不重新宣称源码或模型验收；只有用户授权的票据才允许执行任务或测试。
