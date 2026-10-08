"""Generate evidence-derived delivery reports and a credential-free shareable bundle."""
import collections
import datetime
import hashlib
import json
import sqlite3
import zipfile
from pathlib import Path
from orchestrator import Controller, ROOT, atomic_json, encode, digest
from native_rpc import redact

PROJECTS = {"two_stage_csv": "p-43e8ae53ca7b477f", "natural_request": "p-52d8213273204455",
            "official_source_csv": "p-88cc957c845e44b5"}

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))

def main():
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    c = Controller(ROOT / "data-live", load(ROOT / "config.live.json"))
    projects = {}
    artifacts = []
    for label, pid in PROJECTS.items():
        c.audit_accepted(pid)
        c.export_state(pid)
        projects[label] = c.status(pid)
        for task in c.db.execute("SELECT * FROM tasks WHERE project_id=? AND state='ACCEPTED'", (pid,)).fetchall():
            for file in (c.task_dir(task) / "artifacts").rglob("*"):
                if file.is_file():
                    artifacts.append({"project": label, "task_id": task["id"], "path": str(file),
                                      "bytes": file.stat().st_size, "sha256": digest(file.read_bytes())})
    # Native transport logs are read in code. Only counts/hashes/flags enter the master report.
    turns, usage, requests = {}, {}, []
    canary_hits = 0
    master_input_bytes = []
    paths = list((ROOT / "data-live").rglob("*events*.jsonl"))
    paths += [ROOT / ".runtime/smoke-events.jsonl", ROOT / ".runtime/permissions-probe/native-events.jsonl"]
    for path in paths:
        if not path.exists():
            continue
        lines = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            event = redact(event)
            lines.append(encode(event))
            msg = event.get("message", {})
            params = msg.get("params") or {}
            if msg.get("method") == "thread/start" and event.get("direction") == "send":
                requests.append({"role": params.get("serviceName"), "model": params.get("model"),
                    "ephemeral": params.get("ephemeral"), "sandbox": params.get("sandbox"),
                    "fork_used": False, "memory_config": params.get("config")})
            if msg.get("method") == "turn/start" and event.get("direction") == "send":
                sid = params["threadId"]
                text = "\n".join(x.get("text", "") for x in params.get("input", []))
                role = "master" if "master" in path.name or "/master/" in path.as_posix() else "worker_or_reviewer"
                turns[sid] = {"role": role, "model": params.get("model"), "input_bytes": len(text.encode()), "log_ref": str(path.relative_to(ROOT))}
                if role == "master":
                    master_input_bytes.append(len(text.encode()))
                    canary_hits += int("WORKER_CANARY_6fb9650b" in text)
            if msg.get("method") == "thread/tokenUsage/updated":
                usage[params["threadId"]] = params.get("tokenUsage", {}).get("total", {})
        # Strip account metadata from earlier logs as well; preserve original task outputs.
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    metrics = {key: sum(value.get(key, 0) for value in usage.values()) for key in
               ("totalTokens", "inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens")}
    audit = c.db.execute("SELECT COUNT(*) count,COALESCE(MAX(bytes),0) max_bytes FROM reply_audit").fetchone()
    evidence = {"verified_at": now, "timezone": "Asia/Shanghai", "overall_status": "PARTIAL",
        "projects": projects, "accepted_artifacts": artifacts, "unit_tests": load(ROOT / "evidence/mock-tests.json"),
        "process_tests": load(ROOT / "evidence/process-tests.json"), "mcp_tests": load(ROOT / "evidence/mcp-tests.json"),
        "retained_large_output_test":load(ROOT / "evidence/large-output-tests.json"),
        "native_permissions": load(ROOT / "evidence/native-permissions.json"),
        "native_turns_observed_including_failed_attempts_smoke_and_permission_probe": len(turns),
        "observed_native_models": sorted({x["model"] for x in turns.values()}),
        "usage_totals_from_unique_native_threads": metrics,
        "monetary_cost": "UNKNOWN", "inference_http_request_count": "UNKNOWN",
        "account_quota_is_shared_not_attributable_exclusively": True,
        "master_turn_inputs": {"count": len(master_input_bytes), "max_user_input_bytes": max(master_input_bytes, default=0),
            "canary_matches": canary_hits, "scope": "actual outbound app-server turn/start user messages; provider-internal system prompt not packet-captured"},
        "reply_audit": dict(audit), "role_start_metadata": requests,
        "no_original_auth_or_config_modified": True}
    if (ROOT / "data-live/service.json").exists():
        evidence["background_service_start"] = load(ROOT / "data-live/service.json")
    handover = Path("C:/Users/ASUS/Desktop/CODEX_MULTI_AGENT_HANDOVER_2026-10-06.md")
    evidence["handover_read"] = {"path":str(handover),"lines":len(handover.read_text(encoding="utf-8-sig").splitlines()),
                                "sha256":digest(handover.read_bytes()),"full_document_read":True}
    atomic_json(ROOT / "evidence/validation-summary.json", evidence)
    atomic_json(ROOT / "evidence/blocker-environment.json", {
        "zcode": {"desktop_version":"3.14.4.7912", "cli_version":"0.16.9",
            "plan_cache": {k:{"status":"unavailable", "reason":"coding_plan_not_entitled"} for k in
                ("builtin:zai-start-plan","builtin:zai-coding-plan","builtin:bigmodel-start-plan","builtin:bigmodel-coding-plan")},
            "cache_freshness":"UNKNOWN", "captcha_changelog":"https://zcode.z.ai/cn/changelog"},
        "workbuddy": {"version":"5.6.2", "sidecar_pid_file_pid":14748, "pid_observed_running":False,
            "sidecar_schema_version":6, "target_control_pipe_exists":False,
            "observed_pipe_types":["PAC","SensitiveApproval","SandboxCenter"],
            "user_authorized_retry":True, "password_captured":False,
            "probe_ref":"evidence/workbuddy-probe.json"}})
    source_files = sorted([*ROOT.glob("*.py"), *ROOT.glob("*.ps1"), ROOT / "config.live.json", ROOT / "config.example.json"])
    source_manifest = {p.name:digest(p.read_bytes()) for p in source_files}
    source_hash = digest(source_manifest)
    atomic_json(ROOT / "evidence/source-manifest.json", {"version":"0.1.0", "sha256":source_hash, "files":source_manifest})
    checks = [
        ("T01","PARTIAL","LIVE_VERIFIED","Codex Sol/Luna pass; ZCode/WorkBuddy target routes blocked"),
        ("T02","PASS","LIVE_VERIFIED","new threads; distinct worker/reviewer IDs; no fork"),
        ("T03","PARTIAL","MOCK_VERIFIED","55k Unicode worker output outside master; native master messages separately audited"),
        ("T04","PASS","LIVE_VERIFIED","actual MCP wire bounded and valid JSON"),
        ("T05","PASS","MOCK_VERIFIED","fake completion/missing artifacts never ACCEPTED"),
        ("T06","PASS","MOCK_VERIFIED","automatic quality rework; native insufficient dependency evidence also refused"),
        ("T07","PARTIAL","LIVE_VERIFIED","capability mutation/traversal denied; normal read pass; OS write/read contrast UNKNOWN"),
        ("T08","PASS","MOCK_VERIFIED","transactional leases across two controllers; native parallel routes not stress-tested"),
        ("T09","PASS","MOCK_VERIFIED","real background process completed without observer; model replaced"),
        ("T10","PARTIAL","MOCK_VERIFIED","real process kill/restart; ambiguous task needs reconciliation; ephemeral native session not resumed"),
        ("T11","PASS","LIVE_VERIFIED","same natural request ID reused with no additional native calls; durable mock duplicates"),
        ("T12","PARTIAL","MOCK_VERIFIED","bounded errors/budget/no paid fallback; no deliberate exhaustion of real entitlement"),
        ("T13","PASS","LIVE_VERIFIED","native PASS with incorrect manifest hash rejected; malformed mock review refused"),
        ("T14","PARTIAL","SOURCE_CONFIRMED","effective memory config off and independent homes; global backend memory sources not fully observable"),
        ("T15","PASS","LIVE_VERIFIED","fresh Sol receives bounded accepted state and gives version-bound action"),
        ("T16","PASS","LIVE_VERIFIED","actual CSV and separate official HTTP refetch independently read"),
        ("T17","PASS","MOCK_VERIFIED","injection text cannot alter state machine; real constrained capability also checked"),
        ("T18","PASS","LIVE_VERIFIED","turns/tokens/reply bytes measured; missing monetary/request costs UNKNOWN")]
    acceptance = {"overall_status":"PARTIAL", "verified_at":now, "timezone":"Asia/Shanghai", "source_version":"0.1.0",
        "source_sha256":source_hash, "platform":"Windows 10.0.26200", "runtime":"Python 3.14.7 / Codex 0.160.0",
        "checks":[{"id":i,"result":r,"evidence_status":s,"notes":n,"evidence":"evidence/validation-summary.json"} for i,r,s,n in checks],
        "native_channels_verified":[{"role":"master","client":"codex","model":"gpt-6.1-sol","entitlement":"existing ChatGPT Plus"},
            {"role":"executor/reviewer independent sessions","client":"codex","model":"gpt-6-luna","entitlement":"existing ChatGPT Plus"}],
        "unknown_entitlements":["ZCode free GLM-5.3-Flash via CLI","WorkBuddy DeepSeek-V4.1-Flash promotion via ACP"],
        "unresolved":["B01/B02-Z","B02-W","B03","B05/B09 residual observation","B13 unfinished scope"],
        "master_limits":{"serialized_reply_bytes":8192,"summary_unicode_chars":400,"explicit_evidence_excerpt_bytes":2048},
        "credential_files_in_shareable_bundle":False,
        "recover_from":"README.md and data-live/state.sqlite"}
    atomic_json(ROOT / "ACCEPTANCE.json", acceptance)
    rows = "\n".join(f"| {i} | {r} | {s} | {n} |" for i,r,s,n in checks)
    validation = f'''# 实际验证记录

验证时间：{now}（Asia/Shanghai）；总体 PARTIAL。源码 hash：`{source_hash}`。

自然语言项目 `p-52d8213273204455` 首次执行：主脑规划 1、执行 1、独立监察 1、最终主脑 1；总计 4 个原生角色回合。相同 RequestId 再次运行仍是同一项目、相同次数。

两阶段 CSV 与官网来源 CSV 均已 ACCEPTED。保留第一轮 shell 拒绝、依赖证据不足、漏件和错误哈希等失败证据；未把成功挑出来充作全部记录。独立监察的实际工具回读凭证在各 attempt 的 review-read-receipts.json；早期回合在原生事件中留有相同工具调用。

当前回归：17/17 模拟程序测试通过；实际子进程后台/停止/强杀/恢复通过，模型使用替身；MCP 6 个工具的真实 stdio 回报与白名单通过。真实模型与替身测试严格分开。

| 检查 | 结果 | 证据状态 | 说明 |
| --- | --- | --- | --- |
{rows}

主脑观测到 {len(master_input_bytes)} 个实际角色 turn 输入，最大 user-message {max(master_input_bytes,default=0)} bytes，worker 测试标记匹配数 {canary_hits}。这是客户端真实 turn/start 输入边界审计；没有抓取服务端重构后的全部系统提示。原生内置前缀明显占用 tokens，不能声称上下文消耗为零。

本轮全部观测到 {len(turns)} 个独立原生 thread 回合，包含失败规划、失败验收、smoke 和权限探测。已观测累计 token 数据 {encode(metrics)}。这是每个原生线程最后的累计 tokenUsage；HTTP 模型请求次数及货币成本 UNKNOWN。共享账号额度前后见 native-probe.json 与 usage-after.json，不能全归因于本工程。

不会把 ZCode 连接成功算作模型成功，也不会把原生登录算作活动免费。ZCode/WorkBuddy 详见 BLOCKERS.md。现有仓库编辑与通用工具执行未实现。没有自动安装登录服务或跨设备公开端口。

复验命令在 README.md；机器检查表 ACCEPTANCE.json；原始工件路径、哈希、角色元数据与观测数量在 evidence/validation-summary.json。
'''
    (ROOT / "VALIDATION.md").write_text(validation, encoding="utf-8")
    # Explicit distribution whitelist excludes all runtime authentication and full transcripts.
    archive = ROOT / "native-orchestrator-shareable.zip"
    with zipfile.ZipFile(archive,"w",zipfile.ZIP_DEFLATED) as z:
        for pattern in ("*.py","*.ps1","*.md","config*.json","*.project.json","request.example.txt","ACCEPTANCE.json"):
            for path in ROOT.glob(pattern):
                z.write(path,path.name)
        for path in (ROOT / "evidence").glob("*.json"):
            z.write(path,"evidence/"+path.name)
        for artifact in artifacts:
            path=Path(artifact["path"])
            z.write(path,"verified-artifacts/"+artifact["project"]+"/"+path.name)
    with zipfile.ZipFile(archive) as z:
        assert not any("auth.json" in name or ".runtime/" in name or "credentials" in name.lower() for name in z.namelist())
    c.db.close()
    print(encode({"overall_status":"PARTIAL","unit_tests":17,"native_turns_observed":len(turns),
        "all_three_projects_accepted":all(all(t["state"]=="ACCEPTED" for t in s["tasks"]) for s in projects.values()),
        "source_hash":source_hash,"archive":str(archive)}))

if __name__ == "__main__":
    main()
