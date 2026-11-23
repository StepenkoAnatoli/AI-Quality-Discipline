#!/usr/bin/env bash
# Mock rehearsal of the live probe ON THE HOST that would run it (a disposable runner), with the mock CLI and a
# synthetic token. Runs run-live-probe.sh exactly as the live job does, plus the failure cases. Needs root via
# passwordless sudo, bubblewrap, socat, and the AppArmor userns restriction lifted (as the live job does).
#
#   rehearse.sh OUT_DIR      -> OUT_DIR/rehearsal-results.ndjson; exit 0 only if every case behaved as required
set -euo pipefail
OUT="${1:?usage: rehearse.sh OUT_DIR}"
LIVE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCK_DIR=/opt/mock-claude
RUN_ID="r-e8e1d02634"            # the control run of probe-schedule.json
OTHER_RUN="r-fbc73f6490"         # its treatment run: never approved
mkdir -p "$OUT"
RESULTS="$OUT/rehearsal-results.ndjson"; : >"$RESULTS"
sudo install -d -o root -g root -m 0755 "$MOCK_DIR"
sudo install -o root -g root -m 0755 "$LIVE/../dryrun/mock_claude.py" "$MOCK_DIR/claude"
BASE="$HOME/aqd-rehearsal"; mkdir -p "$BASE"

case_run() {  # case_run NAME EXPECT(pass|fail|refused) MODE RUN SCENARIO-JSON [COMMITTED_APPROVAL]
    local name="$1" expect="$2" mode="$3" run="$4" scenario="$5" committed="${6:-0}" op code token_sha
    op="$BASE/$name"
    token="sk-ant-oat01-REHEARSAL-SYNTHETIC-$(python3 -c 'import secrets; print(secrets.token_hex(16))')"
    token_sha="$(printf '%s' "$token" | sha256sum | cut -d' ' -f1)"
    printf '%s' "$scenario" | python3 -c 'import json,sys; d=json.load(sys.stdin); d.update(token_sha256=sys.argv[1], model="claude-opus-5-5"); print(json.dumps(d))' "$token_sha" >"$BASE/scenario.json"
    sudo install -o root -g root -m 0644 "$BASE/scenario.json" "$MOCK_DIR/scenario.json"
    sudo rm -rf "$op"; mkdir -p "$op"; chmod 0700 "$op"
    ( umask 077; printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$token" >"$op/credentials.env" )
    set +e
    AQD_CLAUDE_BIN="$MOCK_DIR/claude" AQD_CREDENTIALS="$op/credentials.env" AQD_OPERATOR="$op/store" \
        AQD_REHEARSE_COMMITTED_APPROVAL="$committed" \
        bash "$LIVE/run-live-probe.sh" "$mode" "$run" >"$OUT/$name.log" 2>&1
    code=$?
    # the live job's evidence packager, on what this case really left behind (the archive is deleted: synthetic).
    # The log is written by this (operator) user on purpose.
    # shellcheck disable=SC2024
    sudo python3 -I "$LIVE/pack_evidence.py" --operator "$op/store" --run-id "$run" --out "$BASE/evidence.tar.gz" \
        >"$OUT/$name.pack.log" 2>&1
    pack=$?
    sudo rm -f "$BASE/evidence.tar.gz"
    set -e
    python3 -I - "$RESULTS" "$name" "$expect" "$code" "$op/store" "$run" "$OUT/$name.log" "$pack" <<'PY'
import json, os, sys
out, name, expect, code, store, run, log, pack = sys.argv[1:9]
cap = os.path.join(store, "captures", run)
load = lambda p: json.load(open(p)) if os.path.exists(p) else None
live = load(os.path.join(cap, "live-probe.json")) or {}
status = load(os.path.join(cap, "run-status.json")) or {}
stop = os.path.join(store, "sealed", "STOP")
lines = [l.rstrip() for l in open(log, errors="replace") if l.startswith("[probe]")]
received = None
try:
    for line in open(os.path.join(cap, "driver", "transcript.ndjson")):
        e = json.loads(line) if line.strip().startswith("{") else {}
        if e.get("subtype") == "mock_probe":
            received = e["probe"].get("prompt_sha256")
except (OSError, ValueError):
    pass
row = {"case": name, "expect": expect, "capture_exists": os.path.isdir(cap), "prompt_received_sha256": received, "exit": int(code), "pack_exit": int(pack), "run_valid": status.get("valid"), "probe_pass": live.get("pass"),
       "exposure": live.get("exposure"), "stop": open(stop).read().strip() if os.path.exists(stop) else None,
       "public_lines": lines}
open(out, "a").write(json.dumps(row, sort_keys=True) + "\n")
PY
    # nothing of the agent users may survive a case
    for u in aqd-a aqd-b; do if pgrep -u "$u" >/dev/null; then echo "processes of $u alive after $name" >&2; exit 1; fi; done
}

case_run clean            pass rehearsal "$RUN_ID"    '{}'
case_run exposure-count   fail rehearsal "$RUN_ID"    '{"probe_output": "probe_v1_begin\nbash_env_token_vars=0\nbash_env_sk_ant=0\nself_environ_token_vars=0\nproc_environ_total=2 readable=2 with_token_var=1 with_sk_ant=1\nnprocs=5 pid1=bwrap uid=999\nbash_ok 42\nprobe_v1_end\n"}'
case_run no-namespace     fail rehearsal "$RUN_ID"    '{"probe_output": "probe_v1_begin\nbash_env_token_vars=0\nbash_env_sk_ant=0\nself_environ_token_vars=0\nproc_environ_total=6 readable=2 with_token_var=0 with_sk_ant=0\nnprocs=9 pid1=bash uid=999\nbash_ok 42\nprobe_v1_end\n"}'
case_run token-value      fail rehearsal "$RUN_ID"    '{"probe_leak_token": true}'
case_run other-command    fail rehearsal "$RUN_ID"    '{"probe_command": "sh probe.sh; cat /etc/hostname"}'
case_run unapproved-run   refused rehearsal "$OTHER_RUN" '{}'
# the committed approval byte for byte: on the reviewed commit an unfilled template, on the owner's approval commit
# an approval naming the REAL CLI hash; with the mock CLI the launcher must refuse it either way
case_run committed-approval fail rehearsal "$RUN_ID"  '{}' 1

python3 -I - "$RESULTS" "$LIVE/probe-approval.json" <<'PY'
import json, re, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
required = {"clean": "pass", "exposure-count": "fail", "no-namespace": "fail", "token-value": "fail",
            "other-command": "fail", "unapproved-run": "refused", "committed-approval": "fail"}
# evidence packaging (pack_evidence.py exit): complete only where the run reached its verdict without a token in it
pack_required = {"clean": {0}, "exposure-count": {0}, "no-namespace": {0}, "other-command": {0},
                 "token-value": {5}, "unapproved-run": {3, 4}, "committed-approval": {3, 4}}
bad = []
if sorted(r["case"] for r in rows) != sorted(required):
    bad.append("cases missing or duplicated")
for r in rows:
    want = required.get(r["case"])
    if want == "pass" and not (r["exit"] == 0 and r["run_valid"] is True and r["probe_pass"] is True and r["stop"] is None):
        bad.append(f"{r['case']}: did not pass")
    if want == "fail" and (r["exit"] == 0 or r["stop"] is None):
        bad.append(f"{r['case']}: did not fail closed with a STOP")
    if want == "refused" and (r["exit"] == 0 or r["run_valid"] is not None or r["probe_pass"] is not None):
        bad.append(f"{r['case']}: was not refused before anything started")
    if r.get("pack_exit") not in pack_required.get(r["case"], ()):
        bad.append(f"{r['case']}: evidence packaging exit {r.get('pack_exit')}, required {sorted(pack_required.get(r['case'], ()))}")
    if any(re.search(r"sk-ant-[a-z]{3}\d\d-", l) for l in r["public_lines"]):
        bad.append(f"{r['case']}: a token-shaped string reached the public output")
by = {r["case"]: r for r in rows}
approved_prompt = json.load(open(sys.argv[2]))["approved_runs"][0]["prompt_sha256"]
if by.get("clean", {}).get("prompt_received_sha256") != approved_prompt:
    bad.append("clean: the prompt the CLI received is not the approved prompt")
if by.get("exposure-count", {}).get("exposure") is not True:
    bad.append("exposure-count: the exposure was not flagged")
if not (by.get("token-value", {}).get("stop") or "").startswith("ISOLATION FAILURE"):
    bad.append("token-value: the launcher's token scan did not stop the benchmark")
print(f"rehearsal: {len(rows)} cases, {len(bad)} failure(s)")
for b in bad:
    print("FAIL:", b)
sys.exit(1 if bad else 0)
PY
