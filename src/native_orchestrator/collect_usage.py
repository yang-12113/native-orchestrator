
# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import json
import shutil
from native_orchestrator.codex_adapter import private_environment, ROOT
from native_orchestrator.native_rpc import Rpc

if __name__ == "__main__":
    with Rpc([shutil.which("codex"), "app-server"], ROOT, private_environment("usage")) as rpc:
        rpc.call("initialize", {"clientInfo": {"name": "native_orchestrator", "version": "0.1.0"}})
        rpc.notify("initialized")
        value = rpc.call("account/rateLimits/read")
        result = {"rateLimitsByLimitId": value.get("rateLimitsByLimitId"), "rateLimits": value.get("rateLimits")}
        (ROOT / "evidence/usage-after.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print("Saved account-wide quota metadata; no reset or inference was requested.")
