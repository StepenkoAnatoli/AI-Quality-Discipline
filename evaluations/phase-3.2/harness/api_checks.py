#!/usr/bin/env python3
"""Pre-run checks against a private `opencode serve` instance. No model request.

    api_checks.py --server URL --directory PROJECT --group control|treatment \
                  --model PROVIDER/MODEL[#VARIANT] \
                  --allowed-root DIR [--allowed-root DIR ...] --out FILE

Queries (official V2 API reference): GET /api/provider, GET /api/model,
GET /api/skill, GET /api/config, each with location[directory]=PROJECT.

Exit codes:
  0  all checks passed
  10 BLOCKED: the run's provider is absent (credentials missing or rejected)
  11 BLOCKED: model absent or disabled
  12 BLOCKED: the requested variant is not offered for the model
  13 ISOLATION FAILURE: skill or config visible where it must not be
  2  API or usage error
"""
import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import aqd_common as c  # noqa: E402
from drive_session import ApiError, Client, unwrap  # noqa: E402


def _abs_paths(value, found):
    if isinstance(value, str):
        if value.startswith("/") and not value.startswith("//"):
            found.add(value)
    elif isinstance(value, dict):
        for v in value.values():
            _abs_paths(v, found)
    elif isinstance(value, list):
        for v in value:
            _abs_paths(v, found)
    return found


def check_provider(providers, provider_id):
    ids = sorted(p.get("id") for p in providers if isinstance(p, dict))
    return {"ok": provider_id in ids, "provider_ids": ids}


def check_model(models, provider_id, model_id, variant):
    target = None
    for m in models:
        if isinstance(m, dict) and m.get("providerID") == provider_id and model_id in (m.get("id"), m.get("modelID")):
            target = m
            break
    if target is None:
        return {"ok": False, "reason": "model_absent", "model": None}
    variants = sorted(v.get("id") for v in target.get("variants", []) if isinstance(v, dict))
    if target.get("enabled") is False:
        return {"ok": False, "reason": "model_disabled", "model": target, "variants": variants}
    if variant is not None and variant not in variants:
        return {"ok": False, "reason": "variant_absent", "model": target, "variants": variants}
    return {"ok": True, "reason": None, "model": target, "variants": variants,
            "model_sha256": c.sha256_text(json.dumps(target, sort_keys=True))}


BUILTIN_SKILL_SCHEME = "skill://"


def check_skills(skills, group, allowed_roots):
    """Skills the server offers. Built-in skills (path `skill://<id>/...`) ship
    inside the pinned OpenCode binary, are identical in both groups and are
    denied by the project's permission rules; they are recorded, and must not
    be or contain code-discipline. Every file-backed skill must be inside the run."""
    problems, listing = [], []
    found = None
    for s in skills:
        if not isinstance(s, dict):
            continue
        content = s.get("content") or ""
        path = s.get("path") or ""
        builtin = path.startswith(BUILTIN_SKILL_SCHEME)
        entry = {"id": s.get("id"), "path": path, "builtin": builtin, "content_sha256": c.sha256_text(content),
                 "has_sentinel": c.contains_any_sentinel(content)}
        listing.append(entry)
        if builtin and s.get("id") == c.SKILL_ID:
            problems.append(f"{c.SKILL_ID} is offered as a built-in skill: {path}")
        elif path and not builtin and not c.path_under(path, allowed_roots):
            problems.append(f"skill {s.get('id')!r} loaded from outside the run: {path}")
        if s.get("id") == c.SKILL_ID:
            found = entry if found is None else found
            if group == "control":
                problems.append(f"control can discover {c.SKILL_ID} at {path}")
        elif entry["has_sentinel"]:
            problems.append(f"skill {s.get('id')!r} contains code-discipline text")
    if group == "treatment":
        matches = [s for s in skills if isinstance(s, dict) and s.get("id") == c.SKILL_ID]
        if len(matches) != 1:
            problems.append(f"treatment must register {c.SKILL_ID} exactly once, found {len(matches)}")
        elif not c.contains_all_sentinels(matches[0].get("content") or ""):
            problems.append("treatment skill content does not match the canonical skill")
    return {"ok": not problems, "problems": problems, "skills": listing, "code_discipline": found}


def check_config(config_entries, allowed_roots, exists=os.path.exists):
    """Every existing filesystem path the server reports must be inside the run.

    Paths that do not exist are recorded but not failed: the server may list
    locations it searched (for example the system directory) without loading them.
    """
    paths = sorted(_abs_paths(config_entries, set()))
    outside = [p for p in paths if not c.path_under(p, allowed_roots) and exists(p)]
    return {"ok": not outside, "paths": paths, "outside_allowed_roots": outside}


# String fields every list entry must carry (OpenCode 2.3.2 OpenAPI: Provider.Info,
# Model.Info, Skill.Info, Config.Entry).
REQUIRED_FIELDS = {"/api/provider": ("id",), "/api/model": ("providerID", "id"),
                   "/api/skill": ("id", "path", "content"), "/api/config": ("type",)}


def fetch_list(client, path, query):
    """GET a list endpoint. Any other shape is an API error (exit 2), never an
    empty list, so an unreadable skill list cannot pass an isolation check."""
    payload = client.request("GET", path, query=query)[1]
    items = unwrap(payload)
    if not isinstance(items, list):
        raise ApiError(f"GET {path}: expected a list, got {type(items).__name__}: {str(payload)[:300]}")
    for item in items:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) for k in REQUIRED_FIELDS[path]):
            raise ApiError(f"GET {path}: malformed entry: {str(item)[:300]}")
    return items


def run(client, directory, group, allowed_roots, model_ref):
    provider_id, model_id, variant = c.parse_model(model_ref)
    loc = {"location[directory]": directory}
    report = {"directory": directory, "group": group, "allowed_roots": allowed_roots, "model_ref": model_ref}
    report["provider"] = check_provider(fetch_list(client, "/api/provider", loc), provider_id)
    if not report["provider"]["ok"]:
        return report, 10
    report["model"] = check_model(fetch_list(client, "/api/model", loc), provider_id, model_id, variant)
    if not report["model"]["ok"]:
        return report, 11 if report["model"]["reason"] in ("model_absent", "model_disabled") else 12
    report["skills"] = check_skills(fetch_list(client, "/api/skill", loc), group, allowed_roots)
    report["config"] = check_config(fetch_list(client, "/api/config", loc), allowed_roots)
    return report, 0 if report["skills"]["ok"] and report["config"]["ok"] else 13


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--server", required=True)
    p.add_argument("--password-env", default="OPENCODE_PASSWORD")
    p.add_argument("--directory", required=True)
    p.add_argument("--group", choices=("control", "treatment"), required=True)
    p.add_argument("--model", required=True, help="provider/model[#variant]")
    p.add_argument("--allowed-root", action="append", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args(argv)
    password = os.environ.get(args.password_env)
    if not password:
        print(f"api_checks.py: {args.password_env} is not set", file=sys.stderr)
        return 2
    try:
        report, code = run(Client(args.server, password), args.directory, args.group, args.allowed_root, args.model)
    except (ApiError, ValueError) as exc:
        print(f"api_checks.py: {exc}", file=sys.stderr)
        return 2
    report["exit_code"] = code
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    print(f"api_checks: exit {code}")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
