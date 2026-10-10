"""Small native stdio RPC transport. No third party dependencies."""

# Allow direct script entry points as well as package imports after relocation.
if __package__ in (None, ""):
    import sys as _entry_sys
    from pathlib import Path as _EntryPath
    _entry_sys.path.insert(0, str(_EntryPath(__file__).resolve().parents[1]))

import json
import re
import os
import queue
import subprocess
import threading
import time
from pathlib import Path


class RpcError(RuntimeError):
    pass


class Rpc:
    def __init__(self, argv, cwd, env=None, log=None, jsonrpc=True, on_request=None):
        self.log = Path(log) if log else None
        self.events = queue.Queue()
        self.pending = {}
        self.lock = threading.Lock()
        self.seq = 0
        self.jsonrpc = jsonrpc
        self.on_request = on_request
        self.process = subprocess.Popen(
            argv, cwd=cwd, env=env or os.environ.copy(), stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            encoding="utf-8", errors="replace", bufsize=1,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._stderr, daemon=True).start()

    def _record(self, direction, obj):
        if self.log:
            with self.lock:
                self.log.parent.mkdir(parents=True, exist_ok=True)
                with self.log.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"time": time.time(), "direction": direction,
                                        "message": redact(obj)}, ensure_ascii=False) + "\n")

    def _reader(self):
        for line in self.process.stdout:
            try:
                message = json.loads(line)
            except ValueError:
                self._record("unparsed", {"text": line.rstrip()})
                continue
            self._record("receive", message)
            if "id" in message and "method" not in message:
                q = self.pending.get(message["id"])
                if q:
                    q.put(message)
            elif "id" in message and "method" in message:
                # Reject permission requests. No automatic privilege escalation.
                method = message["method"]
                if self.on_request is not None and method == "item/tool/call":
                    try:
                        result = self.on_request(message.get("params") or {})
                    except Exception as e:
                        result = {"success": False, "contentItems": [{"type": "inputText", "text": str(e)[:200]}]}
                    self.send({"id": message["id"], "result": result})
                    self.events.put(message)
                    continue
                result = {"decision": "decline"} if "requestApproval" in method else None
                if result is None:
                    self.send({"id": message["id"], "error": {"code": -32601,
                               "message": "Client does not grant this capability"}})
                else:
                    self.send({"id": message["id"], "result": result})
                self.events.put(message)
            else:
                self.events.put(message)
        self.events.put({"method": "transport/closed", "params": {}})
        for q in list(self.pending.values()):
            q.put({"error": {"code": -32000, "message": "Native process closed its transport"}})

    def _stderr(self):
        # Never put stderr or transcripts into coordinator summaries.
        for line in self.process.stderr:
            self._record("stderr", {"text": line.rstrip()})

    def send(self, obj):
        if not self.jsonrpc:
            obj = {k: v for k, v in obj.items() if k != "jsonrpc"}
        self._record("send", obj)
        with self.lock:
            self.process.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
            self.process.stdin.flush()

    def call(self, method, params=None, timeout=30):
        self.seq += 1
        request_id = self.seq if self.jsonrpc else str(self.seq)
        q = queue.Queue()
        self.pending[request_id] = q
        self.send({"jsonrpc": "2.0", "id": request_id, "method": method,
                   "params": params or {}})
        try:
            response = q.get(timeout=timeout)
            if "error" in response:
                raise RpcError(json.dumps(response["error"], ensure_ascii=False))
            return response.get("result")
        except queue.Empty:
            raise TimeoutError(f"RPC timeout: {method}") from None
        finally:
            self.pending.pop(request_id, None)

    def notify(self, method, params=None):
        self.send({"jsonrpc": "2.0", "method": method, "params": params or {}})

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.terminate()
                self.process.wait(timeout=5)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def redact(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if re.search(r"api.?key|password|access.?token|refresh.?token|authorization|^email$|^accountId$", k, re.I)
                else redact(v) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(x) for x in value]
    if isinstance(value, str):
        return re.sub(r"Bearer [A-Za-z0-9._~-]+", "Bearer [REDACTED]", value)
    return value
