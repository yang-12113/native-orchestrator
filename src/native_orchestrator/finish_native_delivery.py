"""Update delivery evidence from actual current native runs; no authentication access."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import datetime
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path
from native_orchestrator.orchestrator import ROOT,encode,digest,atomic_json

def load(path):return json.loads(Path(path).read_text(encoding='utf-8-sig'))
def main():
    timestamp=datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    old=load(ROOT/'docs/acceptance/ACCEPTANCE.json')
    wb=load(ROOT/'evidence/native-fix/workbuddy-live.json')
    demo='p-3f0ae85006304647'
    c=sqlite3.connect((ROOT/'data-live/state.sqlite').as_uri()+'?mode=ro',uri=True);c.row_factory=sqlite3.Row
    tasks=[dict(r) for r in c.execute('SELECT id,local_id,state,attempt,manifest_hash,review_ref FROM tasks WHERE project_id=?',(demo,))]
    calls=[dict(r) for r in c.execute('SELECT role,model,session_id,completed,usage FROM calls WHERE task_id LIKE ?',(demo+':%',))]
    assert tasks and all(t['state']=='ACCEPTED' for t in tasks)
    assert any(r['role']=='executor' and r['model']=='deepseek-v4.1-flash' for r in calls)
    artifacts=[]
    for t in tasks:
        p=ROOT/'data-live/projects'/demo/t['local_id']/str(t['attempt'])/'artifacts'
        artifacts.extend({'path':str(f),'sha256':digest(f.read_bytes()),'bytes':f.stat().st_size} for f in p.rglob('*') if f.is_file())
    c.close()
    entitlements=[json.loads(line) for line in (ROOT/'evidence/native-fix/zcode-current-entitlements.jsonl').read_text(encoding='utf-8-sig').splitlines() if line.strip()]
    zc=load(ROOT/'evidence/native-fix/zcode-live.json')
    files=[*(ROOT / 'src/native_orchestrator').glob('*.py'),*(ROOT / 'src/native_orchestrator').glob('*.mjs'),*(ROOT / 'scripts').glob('*.ps1'),*(ROOT / 'tests').glob('test_*.py'),*(ROOT / 'config').glob('*.toml'),*(ROOT / 'config').glob('config*.json'),*(ROOT / 'src/native_orchestrator').glob('native_support/*')]
    source_files={p.relative_to(ROOT).as_posix():digest(p.read_bytes()) for p in sorted(files) if p.is_file()}
    sha=digest(source_files)
    atomic_json(ROOT/'evidence/source-manifest.json',{'version':'0.2.0','sha256':sha,'files':source_files})
    result={'version':'0.2.0','verified_at':timestamp,'timezone':'Asia/Shanghai','overall_status':'PARTIAL',
        'default_route':load(ROOT/'config/config.live.json'),'production_project':demo,'tasks':tasks,'native_role_calls':calls,
        'verified_artifacts':artifacts,'workbuddy':wb,'zcode_entitlement_reads':entitlements,'zcode_independent_model_result':zc,
        'codex_protocol_revalidation':load(ROOT/'evidence/native-fix/codex-0.160.1-protocol-comparison.json'),
        'controller_tests':load(ROOT/'evidence/mock-tests.json'),'native_adapter_tests':load(ROOT/'evidence/native-fix/adapter-tests.json'),
        'credential_scan':load(ROOT/'evidence/native-fix/credential-scan.json'),
        'background_service':load(ROOT/'data-live/service.json'),'source_sha256':sha,
        'remaining':['ZCode independent server guard','unimplemented repository/tool scope','partial OS/cloud-memory observation']}
    atomic_json(ROOT/'evidence/native-channel-update.json',result)
    old.update(source_version='0.2.0',source_sha256=sha,verified_at=timestamp,
        runtime='Python 3.14.7 / Codex 0.160.1 / WorkBuddy AI 5.6.2 / ZCode CLI 0.16.9',
        native_channels_verified=[{'role':'master','client':'codex','model':'gpt-6.1-sol','entitlement':'existing ChatGPT Plus'},
            {'role':'independent reviewer','client':'codex','model':'gpt-6-luna','entitlement':'existing ChatGPT Plus'},
            {'role':'executor','client':'WorkBuddy AI native CLI','model':'deepseek-v4.1-flash','native_credit':0,'free_until':'2026-10-10T00:00:00+08:00'}],
        unknown_entitlements=['ZCode remaining balance is not verified; active grant is verified but independent model execution is blocked'],
        unresolved=['B02-Z server guard','B05/B09 residual observation','B13 unimplemented scope'],
        current_native_evidence='evidence/native-channel-update.json')
    for check in old['checks']:
        if check['id']=='T01':check.update(notes='Codex and native WorkBuddy exact model routes LIVE; ZCode entitlement LIVE, independent call SERVICE_GUARD')
    atomic_json(ROOT/'docs/acceptance/ACCEPTANCE.json',old)
    (ROOT/'docs/history/BLOCKERS.md').write_text('''# 当前未解决问题（v0.2.0）

最新证据见 NATIVE_CHANNEL_UPDATE.md 和 evidence/native-channel-update.json。两个软件均找到有效登录；WorkBuddy 免费执行完整链路已修复，之前的旧缓存/旧 sidecar 不再作为当前结论。

## B02-Z：ZCode 独立请求被服务端限制

类型：原生模型接口/服务端安全限制。ZCode 3.14.4.7912、CLI 0.16.9、BigModel Start Plan。当前权益 API 返回 active，包含 Flash 领取额度；领取额不能当剩余额度。

具体失败：account:bigmodel-start-plan / GLM-5.3-Flash 独立生成返回 `request has been blocked due to unusual activity.`。证据：evidence/native-fix/zcode-live.json、zcode-smoke-events.jsonl、zcode-current-entitlements.jsonl。

已尝试：正确 NDJSON、双 provider 路径、当前原生身份与权益、账号模型映射、必需推理级别、真实客户端版本与既有设备上下文。服务端拒绝仍相同，已停止自动重试/备用。当前配置 skip_model_request=true；没有把它当作已证明必须解验证码，也没有绕过安全验证或改换身份/代理。

影响：ZCode 权益与会话建立已验证，独立模型执行未通过。WorkBuddy、Codex 监察及主脑不受影响。

最小用户事项：仅在继续启用 ZCode 路线时，在原生客户端检查/处理官方安全提示；桌面正常而独立接口受限时，需要上游确认这项免费权益的独立 CLI 支持。无需再次登录、重新领取或提供密钥。默认 WorkBuddy 现在可直接使用。

## B03：活动到期边界

WorkBuddy exact model 已实测服务端 rawUsage.credit=0，活动截止北京时间 2026-10-10 零点。到期会停止该路线并报告，不自动切入新付费 API。原有订阅路线保留在 config.codex.json，需显式选用。Sol 与 Luna 监察仍消耗既有 Codex 订阅；不能宣称全流程免费。

ZCode 领取授权已查到，模型仍受独立接口限制，剩余额度未验证。这不需要用户为已跑通的 WorkBuddy 路线做任何新账号操作。

## B05/B09：部分隔离边界不可全观察

Codex 新会话/独立 home/memory 禁用与受限只读工具已验证；WorkBuddy 独立目录、无模型工具、无继承对话、原登录文件前后哈希相同。云端内部记忆来源与所有 OS 权限对照不可完全观察，未夸大为全系统隔离证明。用户无需操作。

## B13：仍未实现的工程范围

当前支持新的文本/CSV/JSON 工件、公开来源验证。现有仓库修改、任意 shell/build/test、复杂二进制文档、跨设备入口、动态计划合并以及 Codex GUI 全局 MCP 注册仍未接入。临时原生会话故障后的恢复依靠外部状态与证据，不确定派发需要对账。这是工程待办，不是用户登录/权限问题。

## 已处理的审批问题

自动审批曾因授权不够具体拒绝恢复加密登录。用户已明确同意借用两个软件现有登录状态；随后执行并验证。令牌未打印、未另存、未送往第三方，无需再次询问同一授权。
''',encoding='utf-8')
    (ROOT/'docs/architecture/CAPABILITY_MATRIX.md').write_text('''# 当前能力矩阵 v0.2.0

| 客户端/角色 | 当前证据 | 模型与通道 | 剩余边界 |
| --- | --- | --- | --- |
| Codex 主脑 | LIVE_VERIFIED | GPT-6.1 Sol，既有 Plus；0.160.1 协议已复验 | 内置系统提示仍有 tokens 消耗 |
| Codex 独立监察 | LIVE_VERIFIED | GPT-6 Luna；真实回读/绑定哈希 | OS/云端全部内部边界不可全观察 |
| WorkBuddy AI 执行 | LIVE_VERIFIED | deepseek-v4.1-flash，原生 CLI 5.6.2，服务端 credit=0 | 活动北京时间 2026-10-10 零点结束；工具关闭 |
| ZCode | 权益 LIVE_VERIFIED；模型 BLOCKED | active Flash 领取授权，account:bigmodel-start-plan | 独立模型请求被服务端 unusual activity 限制，剩余额度未知 |

原始纯 Codex 链路与三项目测试记录保留；最新默认免费执行项目为 p-3f0ae85006304647。最新机器证据 evidence/native-channel-update.json；详细边界 NATIVE_CHANNEL_UPDATE.md 与 BLOCKERS.md。模型身份取原生请求/响应字段，未使用模型自报身份。
''',encoding='utf-8')
    with (ROOT/'docs/history/SOLVED.md').open('a',encoding='utf-8') as f:f.write('\n## v0.2.0 新增已解决\n\nWorkBuddy AI 登录存储/产品配置/原生免费模型执行已修复，默认执行通道已切换并通过后台真实全流程。ZCode 旧无权益缓存已排除，当前领取权益确认；服务端独立请求限制仍如实保留。Codex 0.160.1 自动更新兼容已对比协议并复验。\n')
    with (ROOT/'docs/acceptance/VALIDATION.md').open('a',encoding='utf-8') as f:f.write('\n## 当前 v0.2.0 补充\n\n17 个控制器测试与 8 个路由测试通过。WorkBuddy 原生 exact model、服务端 credit=0、原认证文件未变、完整执行与独立监察全部实测。默认生产项目 p-3f0ae85006304647 已 ACCEPTED。最新证据 evidence/native-channel-update.json，运行 Codex 0.160.1。ZCode 当前权益已实测，独立执行仍 BLOCKED；之前模型/免费状态表以此补充为准。\n')
    archive=ROOT/'native-orchestrator-shareable.zip'
    entries={}
    for pattern in ('src/native_orchestrator/*.py','src/native_orchestrator/*.mjs','tests/test_*.py','scripts/*.ps1','README.md','meta/*.md','meta/*.json','docs/**/*.md','docs/acceptance/**/*.json','config/config*.json','config/*.toml','examples/*.project.json','examples/request*.txt'):
        for p in ROOT.glob(pattern):entries[p.relative_to(ROOT).as_posix()]=p
    for p in (ROOT/'src/native_orchestrator/native_support').glob('*'):
        if p.is_file():entries['src/native_orchestrator/native_support/'+p.name]=p
    for p in (ROOT/'evidence').glob('*.json'):entries['evidence/'+p.name]=p
    for name in ('workbuddy-live.json','zcode-live.json','adapter-tests.json','credential-scan.json','codex-0.160.1-protocol-comparison.json'):
        p=ROOT/'evidence/native-fix'/name;entries['evidence/native-fix/'+name]=p
    for artifact in artifacts:
        p=Path(artifact['path']);entries['verified-artifacts/current-workbuddy/'+p.name]=p
    with zipfile.ZipFile(archive,'w',zipfile.ZIP_DEFLATED) as z:
        for name,p in sorted(entries.items()):z.write(p,name)
    with zipfile.ZipFile(archive) as z:
        assert not z.testzip();assert not any('.runtime/' in n or n.endswith('auth.json') or n.endswith('credentials.json') for n in z.namelist())
    print(encode({'overall_status':'PARTIAL','workbuddy_default':'LIVE_VERIFIED','project':demo,'controller_tests':17,'adapter_tests':8,
        'background_pid':result['background_service']['pid'],'source_sha256':sha,'shareable_bundle':str(archive)}))

if __name__=='__main__':main()
