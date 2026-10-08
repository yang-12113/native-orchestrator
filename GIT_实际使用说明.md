# 用真实项目理解 Git 与 Worktrees

本轮例子是 E:\零碎\native-orchestrator。修复前用 baseline-v0.2 固定基线；修复在 E:\零碎\native-orchestrator-hardening 的 codex/controller-hardening 分支进行，正式 data-live 不进入工作树。TASKS/FRAME-001.md 记录本轮范围；测试、独审和原生自检分别留证据。完成后只快进合入 main。

截图的 Git 页面：codex/ 是新分支名字的前缀；草稿 PR 适合修复尚在验收时给你审阅；强制推送保持关闭即可。合并/压缩合并只有接入 GitHub 并创建 PR 后才用得到，本轮仓库没有远端，所以不需要设置它们。内联审查决定报告在当前聊天显示还是单开审查聊天，不会替代程序测试。自动合并当前无需开启。

截图的 Worktrees 页面：根目录是托管工作树的存放位置；创建前获取上游只影响已有远端项目。旧工作树清理是托管目录的生命周期管理，不能代替 Git 提交或私有凭据备份。本轮直接使用本地 Git worktree；Codex 设置页列的是它管理的工作树，不能依据“暂无工作树”判断 Git 隔离是否失败。

以后下达工程任务，可以直接说：先固定当前已授权内容为 Git 基线，在独立工作树修复，使用 TASK 票据、必要测试和独立 Luna Max 审查；通过后合入，失败保留证据并回退本次提交。

本轮没有向 GitHub 推送或创建 PR。回退使用基线创建新的恢复分支/worktree，或对本次修复提交执行 git revert；不要用 git reset --hard 清掉你的其他工作，数据库与凭据也不随源码自动回退。

