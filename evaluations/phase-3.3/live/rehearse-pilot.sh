#!/usr/bin/env bash
# Mock rehearsal of the G1 invocation pilot ON THE HOST that would run it (a disposable runner), with the mock CLI and
# a synthetic token: run-live-pilot.sh exactly as the live job runs it, plus the failure cases (including the batch
# rule: an invalid run continues, an isolation stop ends the batch), and the live job's packager on what remains. Needs root via passwordless sudo, bubblewrap, socat, and the
# AppArmor userns restriction lifted (as the live job does).
#
#   rehearse-pilot.sh OUT_DIR   -> OUT_DIR/pilot-rehearsal-results.ndjson; exit 0 only if every case behaved as required
set -euo pipefail
OUT="${1:?usage: rehearse-pilot.sh OUT_DIR}"
LIVE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOCK_DIR=/opt/mock-claude
mapfile -t RUNS < <(python3 -I -c 'import json,sys; [print(r["run_id"]) for r in sorted(json.load(open(sys.argv[1]))["runs"], key=lambda r: r["order"])]' "$LIVE/pilot-schedule.json")
mkdir -p "$OUT"
RESULTS="$OUT/pilot-rehearsal-results.ndjson"; : >"$RESULTS"
sudo install -d -o root -g root -m 0755 "$MOCK_DIR"
sudo install -o root -g root -m 0755 "$LIVE/../dryrun/mock_claude.py" "$MOCK_DIR/claude"
BASE="$HOME/aqd-pilot-rehearsal"; mkdir -p "$BASE"
OK='"skip_isolation_probe": true, "notes_text": "ok\n"'

case_run() {  # case_run NAME EXPECT(pass|fail) SCENARIO-JSON [COMMITTED_APPROVAL]
    local name="$1" expect="$2" scenario="$3" committed="${4:-0}" op code token token_sha pack
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
        bash "$LIVE/run-live-pilot.sh" rehearsal >"$OUT/$name.log" 2>&1
    code=$?
    # the live job's packager on what this case really left (the archive is synthetic and deleted)
    local ids=(); for r in "${RUNS[@]}"; do ids+=(--run-id "$r"); done
    # shellcheck disable=SC2024
    sudo python3 -I "$LIVE/pack_evidence.py" --operator "$op/store" --kind pilot "${ids[@]}" \
        --out "$BASE/evidence.tar.gz" >"$OUT/$name.pack.log" 2>&1
    pack=$?
    sudo rm -f "$BASE/evidence.tar.gz"
    set -e
    python3 -I - "$RESULTS" "$name" "$expect" "$code" "$op/store" "$OUT/$name.log" "$pack" "${RUNS[@]}" <<'PY'
import json, os, sys
out, name, expect, code, store, log, pack = sys.argv[1:8]
runs = sys.argv[8:]
load = lambda p: json.load(open(p)) if os.path.exists(p) else None
verdict = load(os.path.join(store, "pilot-verdict.json")) or {}
stop = os.path.join(store, "sealed", "STOP")
received = {}
for run in runs:
    try:
        for line in open(os.path.join(store, "captures", run, "driver", "transcript.ndjson")):
            e = json.loads(line) if line.strip().startswith("{") else {}
            if e.get("subtype") == "mock_probe":
                received[run] = e["probe"].get("prompt_sha256")
    except (OSError, ValueError):
        pass
row = {"case": name, "expect": expect, "exit": int(code), "pack_exit": int(pack),
       "verdict_pass": verdict.get("harness_pass"), "invocation": verdict.get("invocation"),
       "captures": [r for r in runs if os.path.isdir(os.path.join(store, "captures", r))],
       "prompt_received_sha256": received,
       "stop": open(stop).read().strip() if os.path.exists(stop) else None,
       "public_lines": [l.rstrip() for l in open(log, errors="replace") if l.startswith("[pilot]")]}
open(out, "a").write(json.dumps(row, sort_keys=True) + "\n")
PY
    for u in aqd-a aqd-b; do if pgrep -u "$u" >/dev/null; then echo "processes of $u alive after $name" >&2; exit 1; fi; done
}

case_run clean               pass "{$OK}"
case_run treatment-invoked   pass "{$OK, \"invoke_skill\": true}"
case_run control-with-skill  fail "{$OK, \"init_overrides\": {\"skills\": [\"aqd-arm:code-discipline\", \"doctor\"]}}"
case_run missing-skill       fail "{$OK, \"init_overrides\": {\"skills\": [\"doctor\"]}}"
case_run token-value         fail "{$OK, \"leak_token\": true}"
# the committed approval byte for byte: on the reviewed commit an unfilled template, on the owner's approval commit
# an approval naming the REAL CLI hash; with the mock CLI the launcher must refuse it either way
case_run committed-approval  fail "{$OK}" 1

python3 -I - "$RESULTS" "$LIVE/pilot-approval.json" "${RUNS[@]}" <<'PY'
import json, re, sys
rows = [json.loads(l) for l in open(sys.argv[1])]
approved = {e["run_id"]: e["prompt_sha256"] for e in json.load(open(sys.argv[2]))["approved_runs"]}
runs = sys.argv[3:]
required = {"clean": "pass", "treatment-invoked": "pass", "control-with-skill": "fail", "missing-skill": "fail",
            "token-value": "fail", "committed-approval": "fail"}
# batch rule: invalid runs (control-with-skill, missing-skill) do NOT stop the batch, so all six run and the evidence
# is complete; an isolation failure (token-value) stops it after the first run; a refused approval runs nothing
captures = {"clean": runs, "treatment-invoked": runs, "control-with-skill": runs, "missing-skill": runs,
            "token-value": runs[:1], "committed-approval": []}
pack_required = {"clean": {0}, "treatment-invoked": {0}, "control-with-skill": {0}, "missing-skill": {0},
                 "token-value": {5}, "committed-approval": {3}}
invocation = {"clean": (0, 3), "treatment-invoked": (3, 3)}
bad = []
if sorted(r["case"] for r in rows) != sorted(required):
    bad.append("cases missing or duplicated")
for r in rows:
    c, want = r["case"], required.get(r["case"])
    if want == "pass" and not (r["exit"] == 0 and r["verdict_pass"] is True and r["stop"] is None):
        bad.append(f"{c}: did not pass")
    if want == "fail" and (r["exit"] == 0 or r["stop"] is None or r["verdict_pass"] is not False):
        bad.append(f"{c}: did not fail closed with a STOP")
    if r["captures"] != captures[c]:
        bad.append(f"{c}: captures {r['captures']}, required {captures[c]}")
    if r.get("pack_exit") not in pack_required[c]:
        bad.append(f"{c}: evidence packaging exit {r.get('pack_exit')}, required {sorted(pack_required[c])}")
    if c in invocation:
        inv = r.get("invocation") or {}
        if (inv.get("invoked"), inv.get("valid_treatment_runs")) != invocation[c]:
            bad.append(f"{c}: invocation {inv}, required {invocation[c]}")
    if any(re.search(r"sk-ant-[a-z]{3}\d\d-", l) for l in r["public_lines"]):
        bad.append(f"{c}: a token-shaped string reached the public output")
by = {r["case"]: r for r in rows}
if by.get("clean", {}).get("prompt_received_sha256") != {run: approved[run] for run in runs}:
    bad.append("clean: a CLI run did not receive its task's approved prompt")
if not (by.get("token-value", {}).get("stop") or "").startswith("ISOLATION FAILURE"):
    bad.append("token-value: the launcher's token scan did not stop the batch")
print(f"pilot rehearsal: {len(rows)} cases, {len(bad)} failure(s)")
for b in bad:
    print("FAIL:", b)
sys.exit(1 if bad else 0)
PY
