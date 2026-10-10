# FRAME-005 材料 API 独立审查

候选：`846338b4138bbe9d544fb6d9a69559cac1c5d708`

结论：**CHANGES_REQUIRED（仅材料 API / fake 测试范围）**。本审查不代表原生角色、提案、完整 FRAME-005、LIVE 或 G2 完成。

## 范围与证据

只读核对 `AGENTS.md`、`PROJECT.md`、`TASKS/FRAME-005.md`、`repo_materials.py`、`test_repo_materials.py`，以及 `check_runner.root_path/input_manifest`、`execution_contract.PROTECTED/inspect_git_input/relative_path`。未运行测试、Git、模型、网络或认证读取；宿主证据取自 `.runtime/frame-005-material-host-fixed-tests.log`：14 项，13 pass、1 项因 WinError 1314 跳过。旧的 `TASKS/FRAME-005-MATERIAL-TEST-REPORT.md` 仍记录修复前的 3 个问题，与当前源码及新日志不符，应视为过期记录。

## 发现

### M1 — 控制文件与凭据保护名单存在可读缺口（P2）

`_is_protected()` 只在路径恰为根目录文件时保护 `_ROOT_CONTROL_FILES`（`repo_materials.py:37-45,99-120`）；因此 `TASKS/FRAME-005.md`、`module/AGENTS.md` 不会触发该规则。敏感凭据名也采用有限精确集合，例如 `credentials.yml`、`secrets.txt` 不匹配现有文件名或后缀规则（`repo_materials.py:27-35,111-118`）。若控制端把其中任一路径放进 `allowed_paths`，构造器会接受且 `read()` 会送出文件内容。精确白名单限制模型只能请求获批路径，但没有满足票据要求的控制/凭据路径拒绝保护（`TASKS/FRAME-005.md:9`）。建议补齐任务/指令目录和常见凭据变体的保护规则，并用这些触发路径加 fake 用例。

## 已核对行为与范围限制

- 读取只接受控制端提供的 1–50 个精确相对路径；拒绝路径穿越、反斜杠、重复大小写路径及链接。快照根由 `root_path()` 检查祖先链接，`input_manifest()` 拒绝快照内链接；批准文件解析再次检查链接及根目录边界。
- UTF-8 严格解码；offset 是 Unicode 字符索引，excerpt 按完整字符限制 UTF-8 字节数。每次有权限的 read 调用计入次数，重复内容也计入总字节预算。
- `read()` 前复核 Git HEAD/tree/clean 状态及完整输入 manifest，因此未批准文件漂移也会阻止读取。回执只在实际非空 excerpt 或真实空文件交付时添加，返回的 records/binding 是防外部改写副本。
- 构造、read 和 `assert_unchanged()` 都执行 authority fence。测试覆盖漂移、UTF-8、分页/预算、回执副本及权限失败；symlink 用例因宿主权限跳过，实际 OS symlink 行为仍为 UNKNOWN，不能由本次 fake 证据宣称已验证。
