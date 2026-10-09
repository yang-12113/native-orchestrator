# FRAME-004 Windows 链接边界实测记录

候选：`6db1418935930e8a5131e66ac8b2b38d0fef24a6`。宿主实跑日志 `.runtime/frame-004-windows-link-host-tests.log` 显示 6 项真实目录 junction 用例全部 PASS：preflight root/parent、workspace source/data-parent、runner snapshot root/parent、native readonly cwd、input_manifest nested junction。工具内此前的执行策略拦截与 `New-Item: Access is denied` 失败根及日志仍保留在 `.runtime/frame-004-windows-links/`；没有更改策略或权限。

目录 junction 结果只覆盖上述真实目录链接 guard。旧 file-symlink fixtures 的 4 个 WinError 1314 skip 仍未覆盖，也没有实际 OS file symlink 验证。

同一测试文件新增仅 `FRAME003_ENABLE_REAL_GIT_TESTS=1` 启用的本地 Git type-120000 负例：用 `core.symlinks=false` 建立干净已提交链接模式，断言 `UNSUPPORTED_GIT_ENTRY` 且 source/candidate/data 不变；固定无 shell argv、身份只用 `-c`、hooks/filter/sign/network 隔离，命令日志留 case。工具内实跑因 `Path.resolve(strict=True)` 对工作目录返回 WinError 5，在检查器触达前得 `INVALID_PATH`，故当时未记 PASS；随后宿主已通过，详见下段。该用例证明的是 Git 输入模式拒绝，不代表 OS file symlink 覆盖。

主代理宿主opt-in复测：FRAME003_ENABLE_REAL_GIT_TESTS=1，7项全部通过；6项目录junction守卫及1项干净Git mode120000输入拒绝（UNSUPPORTED_GIT_ENTRY），source/data未变，0模型。日志.runtime/frame-004-windows-link-and-git-host-tests.log；此前工具内失败case保留。这里没有把目录junction或Git tree模式叫作实际OS file-symlink验证，旧4项symlink权限跳过仍如实保留。
