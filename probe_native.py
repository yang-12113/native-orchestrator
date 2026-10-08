"""Read-only native capability probe. No model inference or global configuration changes."""
import json
import os
import shutil
import sys
from pathlib import Path
from native_rpc import Rpc

ROOT = Path(__file__).resolve().parent


def prepare_codex_home():
    home = ROOT / ".runtime" / "codex"
    home.mkdir(parents=True, exist_ok=True)
    source = Path("C:/Users/ASUS/.codex/auth.json")
    # Private runtime data, never part of distributable artifacts.
    shutil.copyfile(source, home / "auth.json")
    (home / "config.toml").write_text('''model_provider = "openai"
approval_policy = "never"
sandbox_mode = "read-only"
project_doc_max_bytes = 0
[features]
memories = false
multi_agent = false
[memories]
use_memories = false
generate_memories = false
''', encoding="utf-8")
    return home


def main():
    out = ROOT / "evidence" / "native-probe.json"
    results = {}
    home = prepare_codex_home()
    env = os.environ.copy()
    env["CODEX_HOME"] = str(home)
    env["USERPROFILE"] = "C:\\Users\\ASUS"
    env["HOME"] = "C:\\Users\\ASUS"
    try:
        with Rpc([shutil.which("codex"), "app-server"], ROOT, env) as rpc:
            results["codex_initialize"] = rpc.call("initialize", {
                "clientInfo": {"name": "native_orchestrator", "version": "0.1.0"},
                "capabilities": {"experimentalApi": True}})
            rpc.notify("initialized")
            for method, params in [("account/read", {"refreshToken": False}),
                                   ("model/list", {"includeHidden": True}),
                                   ("account/rateLimits/read", {}),
                                   ("config/read", {"includeLayers": False})]:
                try:
                    value = rpc.call(method, params)
                    if method == "account/read":
                        value = {"requiresOpenaiAuth": value.get("requiresOpenaiAuth"),
                                 "account": {k: v for k, v in (value.get("account") or {}).items()
                                             if k in ("type", "planType")}}
                    if method == "config/read":
                        value = {k: v for k, v in value.get("config", {}).items()
                                 if k in ("model_provider", "features", "memories", "sandbox_mode",
                                          "approval_policy", "mcp_servers", "project_doc_max_bytes")}
                    if method == "account/rateLimits/read":
                        value = {"rateLimitsByLimitId": value.get("rateLimitsByLimitId"),
                                 "rateLimits": value.get("rateLimits")}
                    results["codex_" + method] = value
                except Exception as e:
                    results["codex_" + method] = {"error": str(e)}
    except Exception as e:
        results["codex_error"] = str(e)
    try:
        # Probe existing native runtime without changing its stored configuration.
        with Rpc([shutil.which("node"), "D:/Downloads/ZCode/resources/glm/zcode.cjs",
                  "app-server"], ROOT, env, log=ROOT / ".runtime/zcode-probe.jsonl") as rpc:
            for method in ("runtime/capabilities",):
                try:
                    results["zcode_" + method] = rpc.call(method, {
                        }, timeout=15)
                except Exception as e:
                    results["zcode_" + method] = {"error": str(e)}
    except Exception as e:
        results["zcode_error"] = str(e)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"evidence": str(out), "models": [x["id"] for x in
        results.get("codex_model/list", {}).get("data", []) if not x.get("hidden")],
        "account": results.get("codex_account/read"),
        "zcode": results.get("zcode_runtime/capabilities")}, ensure_ascii=True))


if __name__ == "__main__":
    main()
