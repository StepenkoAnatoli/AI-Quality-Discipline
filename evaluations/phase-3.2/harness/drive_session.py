#!/usr/bin/env python3
"""Drive one benchmark session through a private `opencode serve` instance.

Uses only endpoints in the official OpenCode V2 API reference
(https://opencode.ai/docs/api, openapi.json):

  GET  /api/info                                   server health
  POST /api/session                                session.create (model+variant, location)
  POST /api/session/{id}/prompt                    session.prompt (text, optional skills[])
  GET  /api/session/{id}                           session.get (polled until idle)
  GET  /api/session/{id}/permission                pending permission requests
  POST /api/session/{id}/interrupt                 on timeout
  GET  /api/experimental/session/{id}/export       full transcript (experimental endpoint)

The prompt text is the exact bytes of --message-file for BOTH groups.
Treatment differs only by `skills: [{"id": "code-discipline"}]`, the documented
skill attachment (PromptInput.SkillAttachment, `mention` omitted), so no
activation words are added to the text.

Writes into --out-dir: session.json (create response), prompt-request.json,
prompt-response.json, polls.jsonl, final-session.json, export.json,
driver-result.json. Exit codes: 0 session reached idle, 3 timed out
(interrupted), 4 pending permission request, 2 setup/API error.
"""
import argparse
import base64
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class ApiError(Exception):
    pass


class Client:
    def __init__(self, base_url, password, timeout=60):
        self.base = base_url.rstrip("/")
        token = base64.b64encode(f"opencode:{password}".encode()).decode()
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/json"}
        self.timeout = timeout

    def request(self, method, path, body=None, query=None):
        url = self.base + path
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = None
        headers = dict(self.headers)
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else None)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:2000]
            raise ApiError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise ApiError(f"{method} {path} -> {exc.reason}") from exc


def unwrap(payload):
    """API responses are {"data": ...}; tolerate a bare object as well."""
    if isinstance(payload, dict) and "data" in payload and len(payload) == 1:
        return payload["data"]
    return payload


def build_create_body(args):
    model = {"providerID": args.provider, "id": args.model}
    if args.variant:
        model["variant"] = args.variant
    return {
        "title": args.title,
        "agent": args.agent,
        "model": model,
        "location": {"directory": args.directory},
    }


def build_prompt_body(text, skill_ids):
    body = {"text": text}
    if skill_ids:
        body["skills"] = [{"id": skill} for skill in skill_ids]
    return body


def is_idle(info, admitted_ms):
    """Idle once the session has finished at least one busy period after admission."""
    if not isinstance(info, dict):
        return False
    times = info.get("time") or {}
    idle, busy = times.get("idle"), times.get("busy")
    if idle is None or idle < admitted_ms:
        return False
    return busy is None or idle >= busy


def write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")


def finish(client, session_id, out, result):
    _, final = client.request("GET", f"/api/session/{session_id}")
    write_json(out("final-session.json"), final)
    try:
        _, exported = client.request("GET", f"/api/experimental/session/{session_id}/export")
        write_json(out("export.json"), unwrap(exported))
        result["api_export"] = "ok"
    except ApiError as exc:
        result["api_export"] = f"failed: {exc}"
    write_json(out("driver-result.json"), result)
    return result


def export_existing(args, client):
    """Fallback mode (`opencode run` already finished): export the run's only session."""
    os.makedirs(args.out_dir, exist_ok=True)
    out = lambda name: os.path.join(args.out_dir, name)
    _, listed = client.request("GET", "/api/session")
    sessions = unwrap(listed) or []
    if isinstance(sessions, dict):
        sessions = sessions.get("items") or sessions.get("sessions") or []
    roots = [s for s in sessions if isinstance(s, dict) and not s.get("parentID")]
    if len(roots) != 1:
        raise ApiError(f"expected exactly one session in this run's database, found {len(roots)}")
    return finish(client, roots[0]["id"], out, {"session_id": roots[0]["id"], "status": "idle", "polls": 0, "mode": "export-existing"})


def drive(args, client, sleep=time.sleep, clock=time.time):
    os.makedirs(args.out_dir, exist_ok=True)
    out = lambda name: os.path.join(args.out_dir, name)
    with open(args.message_file, "rb") as handle:
        text = handle.read().decode("utf-8")

    client.request("GET", "/api/info")
    create_body = build_create_body(args)
    write_json(out("session-request.json"), create_body)
    _, created = client.request("POST", "/api/session", create_body)
    write_json(out("session.json"), created)
    session = unwrap(created)
    session_id = session.get("id") if isinstance(session, dict) else None
    if not isinstance(session_id, str) or not session_id.startswith("ses"):
        raise ApiError(f"session.create returned no session id: {str(created)[:500]}")

    prompt_body = build_prompt_body(text, args.attach_skill)
    write_json(out("prompt-request.json"), prompt_body)
    admitted_ms = int(clock() * 1000)
    _, prompted = client.request("POST", f"/api/session/{session_id}/prompt", prompt_body)
    write_json(out("prompt-response.json"), prompted)

    deadline = clock() + args.timeout
    result = {"session_id": session_id, "status": None, "polls": 0}
    idle_streak = 0
    with open(out("polls.jsonl"), "w", encoding="utf-8") as polls:
        while True:
            sleep(args.poll)
            result["polls"] += 1
            _, got = client.request("GET", f"/api/session/{session_id}")
            info = unwrap(got)
            _, perms = client.request("GET", f"/api/session/{session_id}/permission")
            pending = unwrap(perms) or []
            polls.write(json.dumps({"t": int(clock() * 1000), "time": (info or {}).get("time"), "outcome": (info or {}).get("outcome"), "pending_permissions": len(pending)}) + "\n")
            polls.flush()
            if pending:
                result["status"] = "pending_permission"
                result["pending_permissions"] = pending
                client.request("POST", f"/api/session/{session_id}/interrupt")
                break
            idle_streak = idle_streak + 1 if is_idle(info, admitted_ms) else 0
            if idle_streak >= args.idle_confirmations:
                result["status"] = "idle"
                result["outcome"] = (info or {}).get("outcome")
                break
            if clock() > deadline:
                result["status"] = "timeout"
                client.request("POST", f"/api/session/{session_id}/interrupt")
                sleep(args.poll)
                break
    result["mode"] = "api-attachment"
    return finish(client, session_id, out, result)


def parse_args(argv):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", required=True)
    p.add_argument("--password-env", default="OPENCODE_PASSWORD")
    p.add_argument("--export-existing", action="store_true",
                   help="do not create or prompt; export the single session created by `opencode run`")
    p.add_argument("--directory")
    p.add_argument("--message-file")
    p.add_argument("--provider")
    p.add_argument("--model")
    p.add_argument("--variant")
    p.add_argument("--agent", default="build")
    p.add_argument("--title", default="task")
    p.add_argument("--attach-skill", action="append", default=[])
    p.add_argument("--timeout", type=int, default=2700)
    p.add_argument("--poll", type=float, default=10.0)
    p.add_argument("--idle-confirmations", type=int, default=2)
    p.add_argument("--out-dir", required=True)
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    password = os.environ.get(args.password_env)
    if not password:
        print(f"drive_session.py: {args.password_env} is not set", file=sys.stderr)
        return 2
    if not args.export_existing:
        missing = [n for n in ("directory", "message_file", "provider", "model") if not getattr(args, n)]
        if missing:
            print(f"drive_session.py: missing --{', --'.join(m.replace('_', '-') for m in missing)}", file=sys.stderr)
            return 2
    try:
        client = Client(args.server, password)
        result = export_existing(args, client) if args.export_existing else drive(args, client)
    except (ApiError, OSError, ValueError) as exc:
        print(f"drive_session.py: {exc}", file=sys.stderr)
        return 2
    print(json.dumps({k: result[k] for k in ("session_id", "status", "polls")}))
    return {"idle": 0, "timeout": 3, "pending_permission": 4}.get(result["status"], 2)


if __name__ == "__main__":
    raise SystemExit(main())
