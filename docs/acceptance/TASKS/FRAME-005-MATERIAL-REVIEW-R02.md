# FRAME-005 材料 API 独立复审 R02

候选：`2731c3de32abc9e0557435ddf92f0b78311ac53a`

**Scope：MATERIAL ONLY**（`repo_materials.py` 与 `test_repo_materials.py` 的接口/假 Git测试）。本结论不延伸到原生角色、提案、完整 FRAME-005、LIVE 或 G2。

**结论：PASS（仅材料 API 的冻结源码与 fake 验证范围）。** 未发现 R01 的 M1 仍可触发。

## 证据

- 只读复核当前源码、测试断言及 `.runtime/frame-005-material-host-review-fixed-tests.log`；宿主材料测试为 15 run、14 pass、1 skip。
- 冻结统一报告 `.runtime/frame-005-material-frozen-unified-report.json` 指向同一候选，`source_unchanged=true`；其中 `repo_materials.py` 和 `test_repo_materials.py` 的 SHA-256 与当前文件实算值一致。聚合结果为 148 run、0 failure、0 error、5 skip、`evidence_status=MOCK_VERIFIED`、0 次原生模型调用，且未修改正式运行/交付证据。
- 未运行测试、Git、模型、网络或认证读取。本报告只采用已有日志和哈希证据。

## R01 的 M1 已关闭

`repo_materials.py:39-45,102-125` 现在拒绝任意层级的 `TASKS` 目录、任意层级的控制 basename，以及匹配敏感 stem 的文件名。新增测试 `test_repo_materials.py:178-189` 覆盖根级和嵌套 `AGENTS.md`、`TASKS/FRAME-005.md`、`credentials.yml`、`secrets.txt`、`module/client_secret.json`，并期待 `PROTECTED_PATH`。`test_credentials_named_ordinary_source_file_remains_readable`（`test_repo_materials.py:191-202`）确认 `module/credentials_parser.py` 仍可作为普通 UTF-8 源码读取并留下真实回执；这与敏感 stem 的精确匹配边界相符。

## 其余材料接口核对

精确白名单、相对路径与链接拒绝、严格 UTF-8、Unicode 字符 offset、逐段及累计 UTF-8 字节预算、重复读取计费、调用上限、真实交付回执及副本防改、完整输入 Git/manifest 漂移检查和 authority fence 均保留。材料测试覆盖相应行为；没有发现本次 M1 修复破坏这些边界的证据。

## 限制

OS symlink 用例因 WinError 1314 跳过；统一报告的 5 个 skip 均需保留其平台限制解释。材料 API 的真实 OS symlink 行为仍是 UNKNOWN。本结论只表示冻结候选的源码审查和现有 fake 材料测试通过，不是 LIVE 或完整 FRAME-005 接纳结论。
