# FRAME-005 材料测试报告

主机 M1 复测 15 项，仅普通源码对照因 Windows `write_text` 将 LF 转 CRLF 而失败；Reader 保留原始文本字节的行为正确。测试 fixture 已改用 `write_bytes(source.encode("utf-8"))` 固定 LF，待主机复测。此前发现的 read 漂移、EOF 零字节回执、控制文件保护问题已修复。

本轮保护用例通过；新增覆盖 `TASKS/FRAME-005.md`、嵌套 `module/AGENTS.md`、`credentials.yml`、`secrets.txt` 与 `module/client_secret.json` 拒绝，以及普通 `module/credentials_parser.py` 可读。本次只改测试与报告，旧日志保留在 `.runtime/frame-005-material-tests/logs/`。
