# 主线恢复入口

唯一主线：在v0.2.1文本控制器上实现v0.3受限自动工程闭环：冻结Git输入→限定修改→批准检查→独立冻结审查→有限返工→接纳/合入→中断对账。当前不是已完成的自动工程产品。

稳定运行基线：b97788f0c7f3318874765c0fcd664d4bc05e80ed，标签controller-v0.2.1-verified；运行代码验收候选bda744b4074309dcc02f67da5522f22a3d8942cb，两者仅交付文档不同，见TASKS/PLAN-BASELINE-BINDING.json。原data-live、校招业务和私有配置保留。

2026-10-09当前事实：FRAME-002预检、FRAME-003工作区、FRAME-004检查已通过各自冻结独审；受限Windows G1接纳候选72ef920。统一133运行/129通过/4实际OS symlink权限跳过；真实目录junction与Git mode120000拒绝7项通过；原生检查9场景/6次command/exec/0模型通过并绑定运行时代码SHA。TASKS/FRAME-004-ACCEPTANCE.json与REVIEW-R04是范围证据。实际OS文件/目录symlink仍UNKNOWN，不把跳过当PASS。

下一票据FRAME-005：只读仓库材料工具、原生模型权限、文件提案绑定/验证；之后FRAME-006才接控制器与独审/有限返工。G2/G3/G4未完成，旧repo_patch队列仍禁用，不冒称controller-managed。试点只用自有普通目录、无Git链接的小仓库。

恢复顺序：AGENTS.md→PROJECT.md→本文件→权威DEVELOPMENT_STATE.json→当前TASKS票据→必要源码/差异。先核对Git HEAD/status、候选与报告SHA；未提交文件先识别所有者，不自动stash/reset/清空，不为恢复重读完整聊天/日志。

开发唯一状态：E:/零碎/native-orchestrator/DEVELOPMENT_STATE.json；工作树内是镜像，运行时调度权威仍为对应SQLite。主线/状态/计划/最终接纳仅root写；Luna按票据文件白名单，作者/测试/审查分开，fork_turns=none、短事实报告，日志外存。共享文件系统不当物理隔离或零记忆占用，不改全局记忆。

Git：稳定目录E:/零碎/native-orchestrator；开发worktree E:/零碎/native-orchestrator-v03，codex/engineering-v03；另保留hardening基线。CLI worktree与Codex托管列表不同，不因设置页空白就判断没有worktree。开发代码尚未合入main，无remote/PR/推送。阶段/压缩前记录实际commit、证据/限制/下一动作并提交检查点；失败只回退本次失败提交，保护基线与旧数据。

稳定目标PROJECT.md、协作AGENTS.md、阶段分工ENGINEERING_PLAN.md、确认选择DECISIONS.md、范围验收TASKS/共同防止主线漂移，事实仍需当前源码和证据核对。

FRAME005材料子模块最新检查点：冻结2731c3d，统一148运行/143通过/5系统symlink权限跳过，15项材料定向14通过1跳过，独立MATERIAL ONLY复审PASS。源码/测试已提交，根控制入口/嵌套凭据保护、每读输入漂移复核、EOF回执已修。native_repo_turn.py/repo_proposal.py尚不存在；下一动作按FRAME005写角色权限与文件提案绑定，再fake协议/独审和精确原生试点；整个FRAME005/G2未完成。
