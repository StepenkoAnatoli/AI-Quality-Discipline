#!/usr/bin/env bash
# The G1 invocation pilot (PILOT-G1.md, STAGE0-PLAN.md): the six approved runs of pilot-schedule.json (one control
# and one treatment run of NEW-02, NEW-03 and NEW-04), in schedule order, through the unchanged native harness.
# Never scored: no hidden test runs. The SAME script runs the mock rehearsal and, once authorised, the live pilot.
#
# Usage: run-live-pilot.sh rehearsal|live
#
# Required environment (as run-live-probe.sh):
#   AQD_CLAUDE_BIN     the CLI (live: the pinned real binary; rehearsal: the mock)
#   AQD_CREDENTIALS    0600 file with exactly one CLAUDE_CODE_OAUTH_TOKEN= line
#   AQD_OPERATOR       operator-only store (fresh per invocation)
#
# Committed, reviewed inputs, verified before use:
#   pilot-schedule.json  precomputed from a public seed (sha256(aqd-phase-3.3-live-pilot-g1-v1)[:32]), counterbalanced
#   pilot-approval.json  the owner's approval of exactly those six runs (prompt, workspace and CLI SHA-256 per task)
# In rehearsal mode each approved run's cli_sha256 is replaced by the mock's hash and the approver fields are filled
# with "rehearsal"; live mode (and AQD_REHEARSE_COMMITTED_APPROVAL=1) installs the committed approval byte for byte.
#
# Batch rule: launcher exit 1 (an INVALID run, which on realistic tasks can be the agent's own doing) is recorded and
# the batch continues; any other non-zero exit (2 refused, 20 auth BLOCKED, 21 ISOLATION, 22 infrastructure) or a
# STOP file ends the batch at once (the harness writes STOP for 20/21/22; this script writes it for the rest).
# Exit: 0 = harness PASS; 1 = FAIL or refused; 2 = usage. Public output: fixed lines and counts only.
set -euo pipefail
umask 077

MODE="${1:-}"
[[ "$MODE" == rehearsal || "$MODE" == live ]] || { echo "usage: run-live-pilot.sh rehearsal|live" >&2; exit 2; }
: "${AQD_CLAUDE_BIN:?}" "${AQD_CREDENTIALS:?}" "${AQD_OPERATOR:?}"
export AQD_CLAUDE_BIN AQD_CREDENTIALS AQD_OPERATOR AQD_TASKS="NEW-02 NEW-03 NEW-04"
unset AQD_CC_DRY_RUN AQD_CC_RUN_TIMEOUT_SECONDS  # the pre-registered 2700 s timeout; never a dry-run override

LIVE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
H="$(cd "$LIVE/../../phase-3.2/harness" && pwd)"
SCHEDULE_SHA256="bad87ea676f335e605bf39afcab82c9b0f9f44cc4482ee883d1b079dd0425f16"
note() { printf '[pilot] %s\n' "$*"; }
stop() { note "STOP: $*"; exit 1; }

# 1. The committed schedule and approval agree: the same six runs, one control and one treatment per task.
echo "$SCHEDULE_SHA256  $LIVE/pilot-schedule.json" | sha256sum -c --quiet || stop "pilot-schedule.json is not the reviewed file"
RUNS="$(python3 -I - "$LIVE/pilot-schedule.json" "$LIVE/pilot-approval.json" <<'PY'
import json, sys
schedule, approval = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
runs = sorted(schedule["runs"], key=lambda r: r["order"])
entries = approval.get("approved_runs")
key = lambda r: (r["run_id"], r["group"], r["task"], r["model"])
pairs = sorted((r["task"], r["group"]) for r in runs)
ok = (len(runs) == 6 and pairs == sorted((t, g) for t in ("NEW-02", "NEW-03", "NEW-04") for g in ("control", "treatment"))
      and isinstance(entries, list) and len(entries) == 6
      and sorted(map(key, runs)) == sorted(key(e) for e in entries if isinstance(e, dict) and set(e) >= {"run_id", "group", "task", "model"}))
if not ok:
    sys.exit(1)
print(" ".join(r["run_id"] for r in runs))
PY
)" || stop "schedule and approval disagree"
note "runs $RUNS (schedule order)"
for task in NEW-02 NEW-03 NEW-04; do
    note "$task prompt $(sha256sum "$H/../tasks/$task/project/TASK.md" | cut -d' ' -f1)"
done

# 2. Host: OS users, operator store, pristine NEW-02..04 (unchanged setup-host.sh, opt-in task list).
bash "$H/setup-host.sh" >/dev/null 2>&1 || stop "setup-host.sh failed"
bash "$LIVE/egress-lock.sh" "$MODE" || stop "the agent egress lock could not be established or verified"
SEALED="$AQD_OPERATOR/sealed"
install -m 0600 "$LIVE/pilot-schedule.json" "$SEALED/schedule.json"
if [[ "$MODE" == live || "${AQD_REHEARSE_COMMITTED_APPROVAL:-}" == 1 ]]; then
    install -m 0600 "$LIVE/pilot-approval.json" "$SEALED/cc-run-approved.json"
else
    python3 -I - "$LIVE/pilot-approval.json" "$SEALED/cc-run-approved.json" "$AQD_CLAUDE_BIN" <<'PY'
import hashlib, json, sys
a = json.load(open(sys.argv[1]))
mock = hashlib.sha256(open(sys.argv[3], "rb").read()).hexdigest()
for entry in a["approved_runs"]:
    entry["cli_sha256"] = mock
a["approved_by"], a["approved_utc"] = "rehearsal (mock CLI)", "2026-11-24T00:00:00Z"
json.dump(a, open(sys.argv[2], "w"), indent=2)
PY
    if [[ ! -s "$AQD_CREDENTIALS" ]]; then
        printf 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-REHEARSAL-SYNTHETIC-%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(16))')" >"$AQD_CREDENTIALS"
    fi
fi
[[ "$(stat -c %a "$AQD_CREDENTIALS")" == 600 ]] || stop "credentials file is not 0600"

# 3. Native preflight (no model request), then the six runs in schedule order (batch rule above).
bash "$H/preflight-cc.sh" >"$AQD_OPERATOR/preflight.log" 2>&1 || stop "native preflight failed (see the encrypted capture)"
note "native preflight passed"
: >"$AQD_OPERATOR/launcher.log"
for RUN_ID in $RUNS; do
    set +e
    bash "$H/launch-run-cc.sh" "$RUN_ID" >>"$AQD_OPERATOR/launcher.log" 2>&1
    LAUNCH=$?
    set -e
    note "run $RUN_ID: launcher exit $LAUNCH"
    if [[ -f "$SEALED/STOP" ]] || [[ "$LAUNCH" != 0 && "$LAUNCH" != 1 ]]; then
        [[ -f "$SEALED/STOP" ]] || printf 'PILOT STOPPED in run %s (launcher exit %s)\n' "$RUN_ID" "$LAUNCH" >"$SEALED/STOP"
        break
    fi
done

# 4. Verdict (pilot-verdict.json in the operator store, packaged and encrypted). Counts and booleans only.
set +e
python3 -I "$LIVE/check_pilot.py" --store "$AQD_OPERATOR" --schedule "$SEALED/schedule.json" \
    --out "$AQD_OPERATOR/pilot-verdict.json"
VERDICT=$?
set -e
if [[ "$VERDICT" != 0 ]]; then
    [[ -f "$SEALED/STOP" ]] || printf 'PILOT FAILED: the harness verdict did not pass\n' >"$SEALED/STOP"
    stop "the pilot's harness verdict did not pass (STOP written; the invocation record is still in the evidence)"
fi
note "PILOT HARNESS PASSED"
