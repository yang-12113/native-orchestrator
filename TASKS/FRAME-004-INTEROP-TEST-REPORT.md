# FRAME-004 目录互操作测试报告

新增 cap 缺失、0、True、字符串、超 1 MiB 拒绝测试；fixture cap=4096；新增纯 preflight catalog 直交 fake runner 集成断言。

本机 preflight 集成曾受 `root_path(strict=True)` 环境错误阻断。宿主三模块49项已运行至集成末段，发现本文件缺 `json` 导入；已补；宿主复测已通过，详见下段。

仅 fake executor、mock Git；未启动控制器、模型、进程或网络。日志：`.runtime/frame-004-interop-tests/`。

主代理宿主复测：49项运行，47通过、2项真实symlink权限跳过，0失败/错误；同一catalog从preflight直接传runner集成通过。日志.runtime/frame-004-interop-host-fixed-tests.log。冻结6db1418全套126运行/122通过/4跳过，原生9场景/6派发/0模型通过；旧工具环境路径错误记录保留，不再标等待复测。
