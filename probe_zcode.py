import json
import os
import shutil
from pathlib import Path
from native_rpc import Rpc

ROOT = Path(__file__).resolve().parent


def environment():
    home = ROOT / ".runtime/zcode"
    (home / "v2").mkdir(parents=True, exist_ok=True)
    (home / "cli").mkdir(exist_ok=True)
    for name in ("config.json", "provider_config.json", "credentials.json"):
        shutil.copyfile(Path("C:/Users/ASUS/.zcode/v2") / name, home / "v2" / name)
    (home / "v2/setting.json").write_text(json.dumps({"memoryEnabled": False,
        "nativeSearchEnhancementsEnabled": False}), encoding="utf-8")
    (home / "cli/config.json").write_text(json.dumps({
        "features": {"memory": False, "mcp": False, "subagent": False, "skill": False},
        "memory": {"use": False}, "plugins": {"enabled": False},
        "permission": {"mode": "plan"}}), encoding="utf-8")
    env = os.environ.copy()
    env.update(ZCODE_HOME=str(home),
        ZCODE_BUILTIN_PROVIDER_CONFIG_FILE="D:/Downloads/ZCode/resources/config/provider/zcode-builtin.json",
        ZCODE_PERSONAL_PROVIDER_CONFIG_FILE=str(home / "v2/provider_config.json"),
        USERPROFILE="C:\\Users\\ASUS", HOME="C:\\Users\\ASUS")
    return env


def main():
    result = {}
    with Rpc([shutil.which("node"), "D:/Downloads/ZCode/resources/glm/zcode.cjs", "app-server"],
             ROOT, environment(), ROOT / ".runtime/zcode-probe-fixed.jsonl", jsonrpc=False) as rpc:
        for method, params in [("runtime/capabilities", {}), ("session/create", {
                "workspace": {"workspaceKey": "native-orchestrator-probe", "workspacePath": str(ROOT)},
                "mode": "plan", "persistence": "deferred", "mcpServers": [],
                "toolAllowlist": ["Read", "Glob", "Grep"],
                "titleGenerationEnabled": False, "dynamicWorkflowEnabled": False,
                "offPeakToolEnabled": False})]:
            try:
                result[method] = rpc.call(method, params, timeout=30)
            except Exception as e:
                result[method] = {"error": str(e)}
        if result.get("session/create", {}).get("session", {}).get("sessionId"):
            sid = result["session/create"]["session"]["sessionId"]
            for method, params in [("session/setMode", {"sessionId": sid, "mode": "plan"}),
                ("session/setModel", {"sessionId": sid, "model": {"providerId": "builtin:bigmodel", "modelId": "GLM-5.3-Flash"},
                                      "persistAsWorkspaceLastUsed": False})]:
                try:
                    result[method] = rpc.call(method, params)
                except Exception as e:
                    result[method] = {"error": str(e)}
    target = ROOT / ".runtime/zcode-snapshot.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    snapshot = result.get("session/create", {})
    sanitized = {"status": "PARTIAL", "client_version": "3.14.4.7912", "cli_version": "0.16.9",
        "native_connection": result.get("runtime/capabilities"), "session_id": snapshot.get("session", {}).get("sessionId"),
        "initial_messages": len(snapshot.get("messages", [])), "model_directory": snapshot.get("settings", {}).get("model"),
        "model_pin": result.get("session/setModel", {}).get("error", "See private snapshot for observed selection"),
        "free_entitlement": "UNKNOWN", "runtime_memory_enabled": False,
        "reference": "evidence/upstream/zcode-troubleshooting.md"}
    (ROOT / "evidence/zcode-capability.json").write_text(json.dumps(sanitized, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence_private": str(target), "capabilities": result.get("runtime/capabilities"),
                      "create_error": result.get("session/create", {}).get("error"),
                      "snapshot_keys": list(result.get("session/create", {}))}, ensure_ascii=True))


if __name__ == "__main__":
    main()
