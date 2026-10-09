# FRAME-004：批准检查与实际执行边界

状态：IN_PROGRESS。FRAME-002/003已独审通过。2026-10-09 native command/exec 私有checks profile探针通过：input读/scratch写允许，input及control写PermissionError、可达loopback连接PermissionError，输入SHA不变；模型回合0，无认证复制或全局配置变化。证据.runtime/frame-004-native-probe-20261009/report.json。G1仍需正式runner与独审。

主代理负责检查执行边界、可信catalog与状态/租约接线。Luna只读查询可用的本机原生命令执行协议，另一Luna准备隔离检查夹具与测试；不能修改主线/配置/凭据或执行未批准的源项目命令。

目标：以检查ID查可信argv目录，固定cwd/input/candidate/checker/环境指纹，设置超时/输出上限/网络及scratch写域；PASS/FAIL/ERROR区分，stdout/stderr外存。模型不能提供任意命令或修改检查标准。

本阶段文件所有权：root独占check_runner.py/probe_check_boundary.py/validate_check_runner.py/主线/状态/run_tests.py，并已接管完成的native_check_exec.py整合；测试Luna仅test_check_runner.py和对应报告；独立native测试Luna仅test_native_check_exec.py和TASKS/FRAME-004-NATIVE-TEST-REPORT.md。只读查询报告Q01/Q02完成。代码仍在隔离开发分支，不启用旧工程队列。

原生执行API：NativeCheckError(ValueError).code；execute_native(command,*,cwd,scratch_root,readonly_roots,denied_roots,run_root,timeout_ms,output_bytes_cap,before_dispatch)→dict(exitCode,stdout,stderr,native_version,permission_profile,profile_hash)。before_dispatch为无参可信控制端函数，必须返回True。run_root必须全新，profile及rpc日志仅写run_root/home与run_root/native-rpc.jsonl。禁止认证复制、thread/start、turn/start、shellCommand、externalSandbox/full-access。私有profile只给:minimal及Python运行目录read、指定readonly_roots read、scratch_root write、denied_roots deny；检查网络关闭，不继承临时目录write，必须观察profile/list中checks allowed=true和已核对native版本。env仅禁pycache/TEMP/TMP/PYTHONIOENCODING等固定覆盖，调用者不能注入任意env。stdout/stderr有cap/timeout，不允许disable cap/timeout。错误不能退回宿主执行。

runner API：CheckError(ValueError).code；run_check(check_id,catalog,context,*,before_dispatch,native_executor=execute_native)→bounded receipt。context精确含binding（project/task/spec/attempt/contract_hash）、candidate_commit、snapshot_root、scratch_root、control_root、evidence_root。catalog为可信控制端字典，每entry精确argv/timeout_seconds/output_bytes_cap/write_scope=scratch/network=disabled/shell=false/verification=VERIFIED/evidence_sha256。只查ID，不接收命令参数替换；非法路径/ID/能力/catalog/timeout/binding在启动前拒绝。snapshot、scratch、control、evidence不能祖先重叠，链接拒绝。候选输入目录文件manifest前后核对，控制目录给deny，证据目录不给检查者write。

每次run使用专属全新evidence目录，先持久DISPATCHED意图（含输入/候选/catalog/native策略指纹），再原生执行；不确定异常记ERROR+RECONCILIATION_REQUIRED，不自动重试。明确退出0→PASS、正常非0→FAIL；超时/启动/输出不完整/输入漂移→ERROR。当前command/exec协议无timedOut字段，保留退出124专用于ERROR/COMMAND_TIMEOUT，不将它作为业务失败；已观察的MXC launcher前缀失败保留诊断并记ERROR。已验证的Python运行时出现非0+traceback中的PermissionError时保守记ERROR/CHECK_PERMISSION_DENIED；这是诊断规则而非原生结构化状态，不能推广到任意程序。FRAME-005接线不得据此自动扩权限。stdout/stderr保存捕获字节SHA和引用，达到每流cap标不完整；主脑receipt<=8KiB不含全输出。相同目录/调用意图冲突不重放。

2026-10-09 实测补充：最初Windows目录变量白名单不足导致MXC平台目录错误；单加LOCALAPPDATA仍失败，补Windows启动上下文白名单后真实runner8场景通过、5次command/exec、0模型。检查者输入读/scratch写成功；输入/.git/控制/证据/未批准兄弟目录写被拒，控制/证据/兄弟目录读被拒，可达loopback连接被拒。环境缺失和未知ID在原生派发前拒绝；既有意图不重用。固定版本仅0.162.0-alpha.2，其他版本拒绝。证据.runtime/frame-004-runner-real-20261009-c/report.json；最终冻结版本仍需统一回归、独审与源码指纹绑定验证。

前置事实核查：寻找当前已安装原生协议是否提供无需模型回合的受限command/exec及可观察permission provenance。先只读检查指定生成schema与本机help/代码，不改全局设置、不假定框架白名单就是OS隔离。若能力未知/接口受阻，记录BLOCKED/UNKNOWN；不得无说明改成宿主全权限执行测试代码。

通过条件：批准的benign小检查实际运行；未批准ID/参数/路径在启动前拒绝；超时和环境错误进入明确ERROR；非零质量结果FAIL；实际越界写/非批准网络被拒、冻结代码/证据不能被检查者修改、scratch允许写。输出受限不剪断JSON；日志保留明确输入与版本绑定。

查询票据只读且不运行模型/检查；测试实施前由主代理冻结命令、执行根、临时目录与权限配置白名单，不启动原业务服务或重跑校招材料。不安装新平台或新付费API。完成G1所需证据以前，工程队列仍禁用。
