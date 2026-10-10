"""User-authorized local WorkBuddy ACP probe. Temporary credentials stay in memory.
Based on the pinned community bridge interface; no full-access dispatch is enabled.
"""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import json
import re
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

def pipe_rpc(path, method, params=None):
    with open(path, "r+b", buffering=0) as stream:
        request = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            request["params"] = params
        stream.write((json.dumps(request) + "\n").encode())
        reply = json.loads(stream.readline())
    if "error" in reply:
        raise RuntimeError(reply["error"].get("message", "Native pipe error"))
    return reply.get("result")

class ACP:
    def __init__(self, endpoint, password):
        self.endpoint = endpoint
        self.base = endpoint.rsplit("/api/", 1)[0]
        self.headers = {"x-codebuddy-request": "1", "Authorization": "Bearer " + password,
            "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        self.opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        self.seq = 0
    def http(self, url, body=None, method=None):
        request = urllib.request.Request(url, headers=self.headers, method=method,
            data=None if body is None else json.dumps(body).encode())
        return self.opener.open(request, timeout=30)
    def connect(self):
        with self.http(self.base + "/api/v1/acp/connect", {}, "POST") as response:
            result = json.load(response)
        self.headers["acp-connection-id"] = result["connectionId"]
        self.headers["acp-session-token"] = result["sessionToken"]
        return self.call("initialize", {"protocolVersion": 1,
            "clientInfo": {"name": "native-orchestrator-probe", "version": "0.1.0"}, "clientCapabilities": {}})
    def call(self, method, params):
        self.seq += 1
        with self.http(self.endpoint, {"jsonrpc": "2.0", "id": self.seq, "method": method, "params": params}, "POST") as response:
            for raw in response:
                line = raw.decode("utf-8").strip()
                if line.startswith("data:"):
                    line = line[5:].strip()
                if not line.startswith("{"):
                    continue
                event = json.loads(line)
                if event.get("id") == self.seq and "method" not in event:
                    if "error" in event:
                        raise RuntimeError(event["error"].get("message", "ACP error"))
                    return event.get("result")
        raise RuntimeError("ACP did not return a matching result")
    def close(self):
        try:
            self.http(self.endpoint, method="DELETE").close()
        except OSError:
            pass

def main():
    result = {"client_version": "5.6.2", "mode": "NO_PROMPT_CAPABILITY_PROBE"}
    errors = []
    candidates = list(Path("C:/Users/ASUS/AppData/Local/Temp/wb").glob("*/sidecar.pid"))
    for file in sorted(candidates, key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            pipe = "\\\\.\\pipe\\workbuddy-" + file.parent.name + "-sidecar-control"
            hosts = pipe_rpc(pipe, "session.list") or []
            host = next(h for h in hosts if str(h.get("sessionId", "")).startswith("__workbuddy_cli_host__") and h.get("acpEndpoint"))
            capture = pipe_rpc(pipe, "session.capture", {"sessionId": host["sessionId"], "lines": 300})
            match = re.search(r"[?&]password=([^\s\x00-\x1f&]+)", str((capture or {}).get("text", "")))
            if not match:
                raise RuntimeError("Native ACP password absent in host output")
            acp = ACP(host["acpEndpoint"], urllib.parse.unquote(match[1]))
            try:
                result["initialize"] = acp.connect()
                session = acp.call("session/new", {"cwd": str(ROOT / ".runtime/workbuddy-probe"), "mcpServers": []})
                result.update(session_id=session.get("sessionId"), models=session.get("models"),
                    config_options=session.get("configOptions"), modes=session.get("modes"),
                    status="LIVE_VERIFIED_CONNECTION_ONLY")
            finally:
                acp.close()
            break
        except Exception as e:
            # Do not print server objects, passwords or captured terminal output.
            errors.append(type(e).__name__ + ": " + str(e)[:300])
    if "status" not in result:
        result.update(status="BLOCKED", errors=errors or ["No live native sidecar PID files"])
    output = ROOT / "evidence/workbuddy-probe.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"status": result["status"], "errors": result.get("errors"),
        "models": result.get("models"), "evidence": str(output)}, ensure_ascii=True))

if __name__ == "__main__":
    (ROOT / ".runtime/workbuddy-probe").mkdir(parents=True, exist_ok=True)
    main()
