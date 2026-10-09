# FRAME-004 / G1 冻结候选独立复审 R04

结论：**PASS（受限 Windows 第一版范围）**。通过范围仅包括契约/工作区/受限检查边界、真实目录 junction 拒绝、Git mode `120000` 输入拒绝及已绑定的原生检查结果。**实际 OS symlink（文件或目录）仍为 UNKNOWN，未纳入本结论，也不能作为已验证能力对外宣称。**本报告不延伸到 FRAME-005/G2 或自动工程主链。

审查对象为 `72ef920013981a5b81d3f414251498cf44e6d174`，当前 HEAD 精确匹配。复审时工作树只有既有 `DEVELOPMENT_STATE.json` 修改和未提交的 `TASKS/FRAME-004-EVIDENCE-BINDING.json`；本次仅新建本报告。未运行测试、模型、原生检查或权限变更；R01–R03未覆盖。

## 源码及证据绑定

- `.runtime/frame-004-final-frozen-unified-report.json` 的 `candidate_commit` 与 HEAD 相同，`source_unchanged=true`；逐项核对报告中的全部 Python 源文件 SHA 与当前工作树，零不匹配。报告为 `MOCK_VERIFIED`：133 项、0 failures、0 errors、4 skipped、0 模型调用。测试日志明确列出 7 个 `WindowsJunctionBoundaryTests` 用例全部 `ok`。
- `.runtime/frame-004-windows-link-and-git-host-tests.log` 记录 7 项宿主用例全部通过。最终全套运行和宿主定向运行各有 8 份 junction 创建结果；复核其输出 `LinkType=Junction`、实际目录带 `ReparsePoint`、Python `lstat`/`Path.is_junction()` 断言成立。旧失败尝试日志仍保留，未把它们算作通过。
- `TASKS/FRAME-004-EVIDENCE-BINDING.json` 尚未提交；我把其中指纹当作待核事实逐项验证：`candidate_commit=72ef…`，`native_validated_commit=6db…`，候选与 native 验证之间的文件清单和 `git diff --name-only` 相同；5 个运行时代码 SHA 与当前文件及 6db 原生报告一致；该原生报告 SHA 也与绑定文件相同。故没有把 72ef 描述成重新跑过原生检查：6db 的 9 场景/6 次 command/exec/0 模型证据可按字节不变的运行时代码沿用。

## 夹具和断言

[Windows 路径测试](../test_windows_path_boundaries.py) 使用固定 PowerShell 脚本创建真实目录 junction，脚本先把 link/target 约束在唯一 `.runtime` case 下，再同时由 PowerShell 和 Windows 文件属性确认 junction 类型及目标。实测覆盖：preflight 的 repo root/parent；workspace 的 source/data-parent（断言拒绝发生在 Git 与文件系统写入前且 canary 不变）；runner 的 snapshot root/parent（断言 Git probe 与 fake executor 均未调用）；native helper 的 readonly cwd（断言 RPC 未构造且 run root 未创建）；以及 `input_manifest` 内嵌 junction。两次运行的 8 份 junction proof 均为真实 junction，且相应用例通过。

同一隔离夹具用本地临时 Git 仓库、`core.symlinks=false` 构造干净的已提交 mode `120000` 条目，并确认工作树文件是普通文件（`is_symlink()==false`）。命令日志中的 `ls-tree` 实际输出 `120000 blob … linked-input`，status 干净；工作区创建断言收到 `UNSUPPORTED_GIT_ENTRY`，source/data 树快照不变，candidate workspace 不存在。该证据证明 Git 链接模式被拒绝，**不证明 Windows OS 文件 symlink 行为**。

## 明确保留的未知

全套报告中的 4 项 skip 是旧 OS symlink fixtures（2 项文件 symlink、2 项目录 symlink），原因均为 Windows `WinError 1314`；它们没有通过。本次新增实测补上了目录 junction 和 Git mode `120000` 两类边界，但没有创建 OS file symlink 或 OS directory symlink。限定的第一版只能声称上述两类行为已验证；真实 OS symlink 输入及其拒绝行为仍未知。若 G1 要求覆盖实际 OS symlink，则此项仍是验收阻断，不能用 Git tree mode 或目录 junction 替代。