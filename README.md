# native-orchestrator

## Project Status

🚧 Experimental / Testing Phase

native-orchestrator v1.0.0 has completed the first engineering validation milestone.

The project is currently under active testing and iteration on real-world workflows.

This release is mainly intended for research and experimentation.
Production readiness has not been fully established yet.

native-orchestrator 是已有的原生模型协作控制器：通过 Git、SQLite 和确定性检查，组织受限代码修改、独立审查、有限返工、版本接纳和中断对账。普通工程使用 Codex SDK direct-worktree 路线；控制器掌握预算、候选冻结、检查、proof 和串行 promotion/CAS。

## 当前版本

**V1 已冻结：FRAME-006 FINAL ACCEPTED_WITH_LIMITS。** 冻结标签 `controller-v1.0.0-local` 对应提交 `004de591bd03127c61c502655b1a7668eea3413d`，不随目录整理移动。

历史冻结回归为 228 项：223 PASS、0 FAIL、0 ERROR、5 SKIP；真实 SDK turns=2。原始记录见 [最终验收](docs/acceptance/TASKS/FRAME-006-ROUND3-ACCEPTANCE.json) 和 [证据绑定](docs/acceptance/TASKS/FRAME-006-ROUND3-EVIDENCE-BINDING.json)。目录整理后的检查独立记录，不覆盖这些历史文件。

V1 限单独立任务、普通本地 Git worktree、已有 tracked UTF-8 文本。Windows OS symlink 的 5 项权限场景仍为 `UNVERIFIED_WINDOWS_SYMLINK`；junction 与 Git mode 120000 拒绝已验证。二进制、删除、重命名、子模块、依赖图和 managed worktree 不在冻结验收范围。停止主动扩建框架，仅处理真实项目暴露的具体缺口。

## 快速开始

需要 Python 3.11+ 和 Git。以下命令从仓库根目录执行；帮助和 MOCK 示例不需要模型登录。真实工程另外需要已验证的 Codex SDK/runtime、现有登录和用户授权。

```powershell
git clone https://github.com/yang-12113/native-orchestrator.git
Set-Location native-orchestrator
python -B src/native_orchestrator/orchestrator.py --help
```

MOCK 文本示例只用于了解旧文本控制器，不代表真实模型或 V1 工程验收：

```powershell
python -B src/native_orchestrator/orchestrator.py --data .runtime/demo --config config/config.example.json submit examples/demo.project.json --key local-demo
python -B src/native_orchestrator/orchestrator.py --data .runtime/demo --config config/config.example.json run --idle-exit
```

私有配置如需使用，单独准备在 `config/config.live.json`；不要提交认证、私有配置或 `.runtime/`。工程角色策略保留在 [config/model-policy.toml](config/model-policy.toml)：Executor/worker GPT-6 Luna/high、Reviewer/escalation GPT-6.1 Sol/high，禁止自动降级。结构整理没有改变旧适配器的本机环境要求。

## 项目结构

```text
native-orchestrator/
├── README.md
├── AGENTS.md                 # 指向 meta/AGENTS.md 的简短入口
├── src/native_orchestrator/   # 核心模块、CLI、原生桥接及验证脚本
├── tests/                    # 全部 test_*.py
├── docs/
│   ├── architecture/         # 项目说明、架构与工程计划
│   ├── acceptance/TASKS/     # 原任务、审查与验收证据
│   ├── decisions/           # 已确认决策
│   └── history/             # 旧说明、状态与文件迁移映射
├── config/                   # 模型策略与 MOCK 示例配置
├── meta/                     # Agent 规则、开发状态与恢复入口
├── examples/                 # 项目、请求和契约示例
└── scripts/                  # PowerShell 请求、启动及停止入口
```

Python 内部 import 使用 `native_orchestrator` 包。直接脚本入口兼容新目录；作为库或用 `-m` 运行时，将 `src` 加入当前进程的 Python 路径：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -B -m native_orchestrator.orchestrator --help
```

## 测试

完整回归使用已有 runner，产生新报告，不调用模型或覆盖历史验收。真实 Git 测试仅使用新建的自有 fixture：

```powershell
$env:FRAME003_ENABLE_REAL_GIT_TESTS = '1'
python -B src/native_orchestrator/run_tests.py --report .runtime/regression-current.json
```

标准测试发现也可使用：

```powershell
$env:PYTHONPATH = Join-Path (Get-Location) 'src'
python -B -m unittest discover -s tests -p 'test_*.py' -v
```

真实 Windows symlink 用例可能因系统权限 SKIP；必须如实记录，不能当作 PASS。不要直接运行旧测试文件的 `__main__` 入口，它们可能写旧交付报告。

## Agent 与项目恢复

先读 [Agent 规则](meta/AGENTS.md) → [项目说明](docs/architecture/PROJECT.md) → [主线入口](meta/MAINLINE.md) → [开发状态](meta/DEVELOPMENT_STATE.json)，再按状态索引读取票据与验收。开发状态权威仅为当前 clone 的 `meta/DEVELOPMENT_STATE.json`；运行调度权威仍是显式数据目录的 SQLite。

使用 `git rev-parse --show-toplevel` 定位根目录，`git status` 和 `git rev-parse HEAD` 核对当前状态。冻结标签与后续结构 commit 分开理解；不得因历史文档中的旧目录记录切换到其他 clone/worktree。

## 历史资料

所有历史 FRAME、acceptance JSON 和文档均保留；移动时未改写历史内容、原路径或哈希。旧相对引用按原布局解释，完整映射见 [FILE_LAYOUT](docs/history/FILE_LAYOUT.md)。[原 README](docs/history/README-before-structure.md) 和旧使用说明作为历史材料保存。

`.runtime/`、历史 SQLite、原始日志和私有配置没有随 Git clone 提供。历史路径仅供追溯，不表示工件现在可用。源码路径和 import 调整会改变源文件指纹；已有 proof 按原版本和原提交追溯，继续运行必须遵守已有 reconciliation 规则，不自动补造新证明。

## License

This project is licensed under the Apache License 2.0.

See [LICENSE](LICENSE). Third-party components retain their own licenses; see [native_support/NOTICE.md](src/native_orchestrator/native_support/NOTICE.md).
