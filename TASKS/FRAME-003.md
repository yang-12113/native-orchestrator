# FRAME-003：隔离工程工作区与文件提案

状态：IN_PROGRESS。前置：FRAME-002纯预检已独审通过；工程执行仍未启用。开发起点1743758，分支codex/engineering-v03。

主代理：冻结接口、授权/租约检查、状态接线与整合。Luna执行辅助：只实现独立repo_workspace.py；Luna测试：只写test_repo_workspace.py及自己的隔离fixture，最终独审使用不同作者。派发时给新的fork_turns=none上下文，只给本票据与指定接口。

必须先冻结的接口：创建指定base_commit的独立Git worktree；依据allowed_changes验证结构化文本修改提案及修改前SHA；生成候选commit和输入/成果清单。接口由主代理审定，不能把本票据草案当现成运行能力。

本轮冻结API（标准库）：WorkspaceError(ValueError).code；create_workspace(repo_root,base_commit,data_root,binding,*,before_mutation)→descriptor；load_workspace(descriptor)→validated descriptor；apply_proposal(descriptor,proposal,allowed_paths,*,protected_paths=(),before_mutation)→receipt；freeze_candidate(descriptor,*,before_mutation)→candidate receipt。before_mutation为可信控制端无参函数，返回True才有当前权威；缺失/False必须拒绝，Git及每次文件变更前重新调用。helper不拥有SQLite调度权威。

binding精确包含project_id、task_id（各ASCII标识<=64）、spec_version/attempt（正整数，拒bool）、contract_hash（64hex）。workspace路径由binding规范哈希决定，位于data_root/workspaces/<hash>/repo；控制记录在其父目录，不能由模型文件工具读写。descriptor固定schema_version/source_root/base_commit/data_root/workspace_root/binding等归属字段，所有入口校验持久记录与descriptor完全对应；源码目录/数据根/workspace的链接和越界路径拒绝。

创建前只读确认准确源root、clean且HEAD等于base_commit。新位置不可覆盖；先持久CREATING意图，再创建detached worktree，完成写READY。重复/不确定创建不重跑Git，返回WORKSPACE_EXISTS或RECONCILIATION_REQUIRED，供后续FRAME-007对账。

proposal精确字段proposal_id（ASCII标识<=64）、binding、base_commit、changes。每项精确path/before_sha256/content：existing文件要求实际原始SHA相符，新建要求before_sha256=null且不存在；全部文本UTF-8、文件<=1MiB、总<=4MiB、1..50项。先验证全部项目，非法一项时无任何文件改动；路径须在allowed_paths，大小写碰撞/父子保护重叠/任何组件内.git/.runtime/.codex/.env等元数据保护、目录、链接均拒绝。

操作先写带proposal规范哈希的APPLYING意图，原子写目标并保存AFTER哈希，再写APPLIED；同proposal_id+同哈希且实际AFTER相符则返回原receipt不重复写，不同内容冲突拒绝。未完成或输入漂移进入RECONCILIATION_REQUIRED，不自动补写。文件提案可多个顺序执行，但FROZEN后拒绝任何新提案。

冻结前核对HEAD/归属/全部修改仅来自成功提案，拒绝额外/忽略的文件或输入漂移；只stage批准文件，固定身份创建候选commit，禁止hook/filter/gpg、shell和网络。记录FROZEN候选和完整受限清单；重复freeze验证候选/字节后返回同receipt，不另commit。不合入源分支，不自动清理workspace。

实现作者Luna只写repo_workspace.py；测试作者另一Luna只写test_repo_workspace.py和TASKS/FRAME-003-TEST-REPORT.md；主代理独占票据、主线、状态、run_tests.py与最终整合。测试在新的.runtime/frame-003-*小仓库，不接触原data-live/校招/auth。主代理负责必要Git元数据操作的授权执行和实际验收。

范围：全部工作区必须在新控制器数据根下且能核对归属，不写源项目工作目录；Git本身的worktree登记是预期侧效，派发意图与原输入版本由主代理绑定。已有脏输入/非Git输入拒绝，不自动stash/commit；workspace冲突不覆盖或递归清空。

首版文件操作只支持明确白名单中的UTF-8新建/修改，不提供任意命令、文件夹覆盖、链接/ADS、删除/rename、子模块或二进制操作。保护路径双向重叠拒绝；全部提案先校验再落盘；修改前字节SHA、任务/规格/尝试绑定不一致就拒绝。

通过条件：源文件保持不变、工作区归属及基线可核对；不批准路径/链接/父子保护重叠/目录替换/输入漂移/工作区冲突均被拒；冻结候选后重复提案不重复执行；Git命令不触发未授权hook/filter/gpg或网络。目录复制/提示词不能宣称已经通过真实工程只读权限关卡。

测试只在专属新小仓库和自己创建的目录，不运行旧业务或读认证。不删除不明路径，任何递归移动/清理先核对完整路径在票据目录内。故障保留证据，由后续持久发布/恢复阶段对账，不自动重跑未知副作用。

先派发模块实现/测试票据并确认文件唯一作者，再在独立分支提交；主代理检查、冻结commit、独立Luna审查后接纳。该模块完成不等于批准工程命令和正式合入已实现，FRAME-004–008仍有前置关卡。
