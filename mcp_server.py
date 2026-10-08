"""Coordinator-only MCP stdio facade. No transcript, shell or raw worker-result tool."""
import argparse
import json
import sys
from pathlib import Path
from orchestrator import Controller, ROOT, encode, MAX_REPLY

TOOLS = [
    {"name": "submit_project", "description": "Persist an authorized versioned artifact project and return its ID.",
     "inputSchema": {"type": "object", "properties": {"specification": {"type": "object"}, "request_id": {"type": "string"}}, "required": ["specification", "request_id"], "additionalProperties": False}},
    {"name": "get_project_delta", "description": "Read bounded status changes. Execution logs are not returned.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}, "cursor": {"type": "integer", "minimum": 0}}, "required": ["project_id"], "additionalProperties": False}},
    {"name": "get_resume_state", "description": "Load bounded accepted state for a fresh master conversation.",
     "inputSchema": {"type": "object", "properties": {"project_id": {"type": "string"}}, "required": ["project_id"], "additionalProperties": False}},
    {"name": "get_decision_request", "description": "Read one persisted concrete decision request.",
     "inputSchema": {"type": "object", "properties": {"decision_id": {"type": "string"}}, "required": ["decision_id"], "additionalProperties": False}},
    {"name": "resolve_decision", "description": "Explicitly resolve one request within the existing retry budget.",
     "inputSchema": {"type": "object", "properties": {"decision_id": {"type": "string"}, "action": {"type": "string", "enum": ["retry", "cancel"]}}, "required": ["decision_id", "action"], "additionalProperties": False}},
    {"name": "query_evidence", "description": "Explicitly retrieve a bounded excerpt of one spec/check/manifest/review. No execution transcript access.",
     "inputSchema": {"type": "object", "properties": {"task_id": {"type": "string"}, "kind": {"type": "string", "enum": ["spec", "checks", "manifest", "review"]}, "offset": {"type": "integer", "minimum": 0}}, "required": ["task_id", "kind"], "additionalProperties": False}},
]

def dispatch(c, name, args):
    if name == "submit_project":
        return c.submit(args["specification"], args["request_id"])
    if name == "get_project_delta":
        return c.delta(args["project_id"], args.get("cursor", 0))
    if name == "get_resume_state":
        return c.resume_summary(args["project_id"])
    if name == "resolve_decision":
        return c.resolve(args["decision_id"], args["action"])
    if name == "query_evidence":
        return c.query_evidence(args["task_id"], args["kind"], args.get("offset",0))
    if name == "get_decision_request":
        row = c.db.execute("SELECT id,project_id,task_id,reason,resolved,resolution FROM decisions WHERE id=?", (args["decision_id"],)).fetchone()
        if row is None:
            raise ValueError("Unknown decision")
        return c.bounded(dict(row), "decision")
    raise ValueError("Tool is not in the coordinator whitelist")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", default=str(ROOT / "data-live"))
    parser.add_argument("--config", default=str(ROOT / "config.live.json"))
    args = parser.parse_args()
    controller = Controller(args.data, json.loads(Path(args.config).read_text(encoding="utf-8")))
    for line in sys.stdin:
        try:
            message = json.loads(line)
            if len(line.encode("utf-8")) > 1048576 or len(encode(message.get("id",0))) > 128:
                message = {"id": None}
                raise ValueError("MCP request frame/ID exceeds limit")
            if "id" not in message:
                continue
            method = message["method"]
            if method == "initialize":
                result = {"protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                          "serverInfo": {"name": "native-orchestrator-master", "version": "0.1.0"}}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "ping":
                result = {}
            elif method == "tools/call":
                params = message["params"]
                value = dispatch(controller, params["name"], params.get("arguments", {}))
                result = {"content": [{"type": "text", "text": encode(value)}], "isError": False}
            else:
                raise ValueError("Unsupported MCP method")
            reply = {"jsonrpc": "2.0", "id": message["id"], "result": result}
            raw = encode(reply).encode("utf-8")
            # Nested JSON escaping is included in the transport bound, not only the inner object.
            if len(raw) > MAX_REPLY:
                reply = {"jsonrpc": "2.0", "id": message["id"], "result": {"content": [{"type": "text", "text": "Response exceeds transport budget; use a narrower page."}], "isError": True}}
        except Exception as e:
            reply = {"jsonrpc": "2.0", "id": locals().get("message", {}).get("id"),
                     "error": {"code": -32602, "message": str(e)[:300]}}
        print(encode(reply), flush=True)

if __name__ == "__main__":
    main()
