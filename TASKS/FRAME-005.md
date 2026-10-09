# FRAME-005：只读仓库材料与原生文件提案

状态：INTERFACE_DESIGN。前置受限Windows G1已接纳72ef920；FRAME-004-ACCEPTANCE.json限定真实junction/Git链接模式验证，不声称OS symlink已实测。试点只使用自有普通目录和无Git链接的小仓库。完整工程队列仍禁用，G2未通过。

目标：原生Luna/max在独立、记忆关闭的上下文，只能通过批准的只读工具取材料，产出绑定输入/规格/尝试的UTF-8文件提案。程序验证再调用已接纳apply_proposal，模型不直接写仓库，不接收任意shell/网络命令。本票据先形成独立路由/提案接口；SQLite工程主链、冻结独审和有限返工在FRAME-006整合，不偷接旧队列。

文件所有权：root负责repo_proposal.py、native_repo_turn.py、模型权限/提案schema、票据/状态/整合/验收；Luna实现仅repo_materials.py；另一Luna只test_repo_materials.py及TASKS/FRAME-005-MATERIAL-TEST-REPORT.md。查询/测试不读认证文件，不写全局配置。角色协议测试另设白名单后再派发，作者/测试/最终审查分开。

材料接口冻结：MaterialError(ValueError).code；RepoMaterials(snapshot_root,candidate_commit,binding,allowed_paths,*,before_read,max_file_bytes=65536,max_excerpt_bytes=2048,max_total_bytes=16384,max_calls=32)。只接普通绝对干净Git候选目录，binding为已有5字段；allowed_paths为控制端精确相对路径，非模型提供。拒绝链接/交叉路径/控制、凭据或配置保护路径，任何读工具都不能读取其他文件。完整输入Git+文件manifest绑定；所有批准文件读取UTF-8，保存不可变字节与SHA，当前输入漂移拒绝。

read(path,offset=0)→有界dict，字段path、candidate_commit、input_hash、file_sha256、file_bytes、offset（Unicode字符）、next_offset（结束时null）、excerpt（UTF-8字节<=max_excerpt_bytes）。每次实际工具读先before_read返回True；path必须精确在白名单，offset为非负int，不接受额外参数。累计excerpt字节/次数有限，重复读也计费。records()→每次实际送达的路径/SHA/offset/next_offset/returned_bytes；不能编造完整阅读。assert_unchanged()只读复核完整输入。对象不写证据，证据持久化由root控制端负责；日志/认证/原源码不触碰。

原生接口由root基于本机0.162.0-alpha.2 schema冻结：thread/start和turn/start的命名权限字段为permissions，分别与sandbox/sandboxPolicy互斥。私有角色配置关闭memories、多代理、web、shell/unified_exec、remote_plugin和自动项目文档；模型只拥有批准读材料工具。模型/effort/native version/profile必须实际核对，不降级到更大权限。输出schema绑定原5字段、输入commit/manifest和允许修改路径；完整响应<=8KiB、摘要<=400字符，提案不能改变检查目录/授权/策略。

所有初始化/读取/模型派发使用可信authority callback；模型turn派发之前须有控制端预算/调用意图，不盲重放未知结果。现有订阅原生角色认证流程只由root控制端在原生验证范围内沿用，查询/测试作者不访问它；不得改原认证或私有配置，不引入API key/新付费路由，凭据不进材料/提示/摘要。批准检查通道继续无认证/模型，不能混用角色通道。

先fake验证材料、参数/绑定/保护路径/漂移/预算与协议；再冻结独审。首次真实提案验证由root另写精确fixture、模型=gpt-6-luna、effort=max、最多1个worker turn、超时/输出上限、只读材料和允许修改文件到本票据；未落该白名单前不运行模型。以真实read回执和程序提案验证判定成功，不能用模型自称PASS或mock替代LIVE。
