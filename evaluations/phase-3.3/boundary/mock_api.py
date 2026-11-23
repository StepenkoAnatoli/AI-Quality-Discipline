"""LOCAL mock of the Anthropic Messages API for the offline boundary probe. Never a model.

    python3 -I mock_api.py PORT LOG.ndjson SCRIPT.json

Replays SCRIPT (a list of {"tool": NAME, "input": {...}} or {"text": "..."}) one entry per main-loop request
(a request that offers tools); any other request (count_tokens, auxiliary calls) gets a short text reply. Every
request is logged with its body (what a model would have seen); Authorization and x-api-key values are replaced
by "<present>" in the log.
"""
import json, sys, http.server
LOG = sys.argv[2]
SCRIPT = json.load(open(sys.argv[3]))
state = {"n": 0}
class H(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _rec(self, body):
        with open(LOG, "a") as f:
            f.write(json.dumps({"method": self.command, "path": self.path, "headers": {k.lower(): ("<present>" if k.lower() in ("authorization","x-api-key") else v) for k, v in self.headers.items()}, "body": body}) + "\n")
    def do_GET(self):
        self._rec(None); self.send_response(200); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b"{}")
    do_HEAD = do_GET
    def do_POST(self):
        n = int(self.headers.get("content-length", 0)); raw = self.rfile.read(n).decode("utf-8", "replace")
        try: body = json.loads(raw)
        except ValueError: body = raw
        self._rec(body)
        if not self.path.startswith("/v1/messages") or "count_tokens" in self.path:
            self.send_response(200); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(b'{"input_tokens": 10}'); return
        model = body.get("model", "x") if isinstance(body, dict) else "x"
        is_main = isinstance(body, dict) and len(body.get("tools") or []) > 0
        if is_main:
            i = state["n"]; state["n"] += 1
            turn = SCRIPT[i] if i < len(SCRIPT) else {"text": "Done."}
        else:
            turn = {"text": "aux"}
        if isinstance(body, dict) and body.get("stream"):
            self.send_response(200); self.send_header("content-type","text/event-stream"); self.end_headers()
            def ev(t, d): self.wfile.write(f"event: {t}\ndata: {json.dumps(d)}\n\n".encode()); self.wfile.flush()
            ev("message_start", {"type":"message_start","message":{"id":f"msg_{i if is_main else 'aux'}","type":"message","role":"assistant","model":model,"content":[],"stop_reason":None,"stop_sequence":None,"usage":{"input_tokens":5,"output_tokens":1}}})
            if "tool" in turn:
                ev("content_block_start", {"type":"content_block_start","index":0,"content_block":{"type":"tool_use","id":f"toolu_{state['n']}","name":turn["tool"],"input":{}}})
                ev("content_block_delta", {"type":"content_block_delta","index":0,"delta":{"type":"input_json_delta","partial_json":json.dumps(turn["input"])}})
                stop = "tool_use"
            else:
                ev("content_block_start", {"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}})
                ev("content_block_delta", {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":turn["text"]}})
                stop = "end_turn"
            ev("content_block_stop", {"type":"content_block_stop","index":0})
            ev("message_delta", {"type":"message_delta","delta":{"stop_reason":stop,"stop_sequence":None},"usage":{"output_tokens":3}})
            ev("message_stop", {"type":"message_stop"})
        else:
            content = [{"type":"text","text":turn.get("text","aux")}] if "tool" not in turn else [{"type":"tool_use","id":"toolu_x","name":turn["tool"],"input":turn["input"]}]
            out = {"id":"msg_ns","type":"message","role":"assistant","model":model,"content":content,"stop_reason":"end_turn","stop_sequence":None,"usage":{"input_tokens":5,"output_tokens":3}}
            self.send_response(200); self.send_header("content-type","application/json"); self.end_headers(); self.wfile.write(json.dumps(out).encode())
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), H).serve_forever()
