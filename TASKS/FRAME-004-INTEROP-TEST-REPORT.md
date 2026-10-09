# FRAME-004 目录互操作测试报告

新增 cap 缺失、0、True、字符串、超 1 MiB 拒绝测试；fixture cap=4096；新增纯 preflight catalog 直交 fake runner 集成断言。

本机 preflight 集成曾受 `root_path(strict=True)` 环境错误阻断。宿主三模块49项已运行至集成末段，发现本文件缺 `json` 导入；已补，等待宿主复测。

仅 fake executor、mock Git；未启动控制器、模型、进程或网络。日志：`.runtime/frame-004-interop-tests/`。
