import json
import subprocess
import sys
import uuid
from orchestrator import ROOT, MAX_REPLY

def main():
    data = ROOT / "data-process-tests" / ("mcp-" + uuid.uuid4().hex[:8])
    p = subprocess.Popen([sys.executable, str(ROOT / "mcp_server.py"), "--data", str(data)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", cwd=ROOT)
    records = []
    def rpc(rid, method, params=None):
        p.stdin.write(json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params or {}}) + "\n")
        p.stdin.flush()
        line = p.stdout.readline()
        assert len(line.encode()) <= MAX_REPLY
        value = json.loads(line)
        records.append({"method": method, "response_bytes": len(line.encode())})
        return value
    try:
        rpc(1, "initialize")
        listed = rpc(2, "tools/list")
        names = [t["name"] for t in listed["result"]["tools"]]
        assert "get_transcript" not in names and "get_result" not in names and len(names) == 6
        spec = json.loads((ROOT / "demo.project.json").read_text(encoding="utf-8"))
        result = rpc(3, "tools/call", {"name": "submit_project", "arguments": {"specification": spec, "request_id": "mcp"}})
        project = json.loads(result["result"]["content"][0]["text"])["project_id"]
        delta = rpc(4, "tools/call", {"name": "get_project_delta", "arguments": {"project_id": project}})
        assert "mock_result" not in json.dumps(delta) and "WORKER_CANARY" not in json.dumps(delta)
        forbidden = rpc(5, "tools/call", {"name": "get_transcript", "arguments": {}})
        assert "error" in forbidden
        (ROOT / "evidence/mcp-tests.json").write_text(json.dumps({"status": "LIVE_VERIFIED_LOCAL_TRANSPORT",
            "model_involved": False, "whitelist": names, "wire_records": records}, indent=2), encoding="utf-8")
        print("MCP stdio whitelist and actual wire bounds passed.")
    finally:
        p.stdin.close()
        p.wait(timeout=5)

if __name__ == "__main__":
    main()
