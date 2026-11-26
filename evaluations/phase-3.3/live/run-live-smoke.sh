#!/usr/bin/env bash
# The two-arm SMOKE run (SMOKE-PROPOSAL.md): the two approved SMOKE runs of smoke-schedule.json, in schedule order,
# through the unchanged native harness. Never scored. The SAME script runs the mock rehearsal (mock CLI, synthetic
# token) and, once authorised, the live run.
#
# Usage: run-live-smoke.sh rehearsal|live
#
# Required environment (as run-live-probe.sh):
#   AQD_CLAUDE_BIN     the CLI (live: the pinned real binary; rehearsal: the mock)
#   AQD_CREDENTIALS    0600 file with exactly one CLAUDE_CODE_OAUTH_TOKEN= line
#   AQD_OPERATOR       operator-only store (fresh per invocation)
#
# Committed, reviewed inputs, verified before use:
#   smoke-schedule.json  precomputed from a public seed (sha256(aqd-phase-3.3-live-smoke-v1)[:32]), 2 SMOKE runs
#   smoke-approval.json  the owner's approval of exactly those two runs (prompt, workspace and CLI SHA-256)
# In rehearsal mode each approved run's cli_sha256 is replaced by the mock's hash and the approver fields are filled
# with "rehearsal"; live mode (and AQD_REHEARSE_COMMITTED_APPROVAL=1) installs the committed approval byte for byte.
#
# A launcher exit other than 0 for EITHER run writes STOP and ends the batch: the other run does not start.
# Exit: 0 = SMOKE PASSED; 1 = FAILED or refused (STOP written); 2 = usage. Public output: fixed lines and counts.
set -euo pipefail
umask 077

MODE="${1:-}"
[[ "$MODE" == rehearsal || "$MODE" == live ]] || { echo "usage: run-live-smoke.sh rehearsal|live" >&2; exit 2; }
: "${AQD_CLAUDE_BIN:?}" "${AQD_CREDENTIALS:?}" "${AQD_OPERATOR:?}"
export AQD_CLAUDE_BIN AQD_CREDENTIALS AQD_OPERATOR AQD_TASKS=SMOKE
unset AQD_CC_DRY_RUN AQD_CC_RUN_TIMEOUT_SECONDS  # the pre-registered 2700 s timeout; never a dry-run override

LIVE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
H="$(cd "$LIVE/../../phase-3.2/harness" && pwd)"
SCHEDULE_SHA256="a54f6f3300ec607026cfef47d71ac00a33a3f746a5077af90b0c84d08c147dc6"
note() { printf '[smoke] %s\n' "$*"; }
stop() { note "STOP: $*"; exit 1; }

# 1. The committed schedule and approval agree: the same two SMOKE runs, one per arm.
echo "$SCHEDULE_SHA256  $LIVE/smoke-schedule.json" | sha256sum -c --quiet || stop "smoke-schedule.json is not the reviewed file"
RUNS="$(python3 -I - "$LIVE/smoke-schedule.json" "$LIVE/smoke-approval.json" <<'PY'
import json, sys
schedule, approval = json.load(open(sys.argv[1])), json.load(open(sys.argv[2]))
runs = sorted(schedule["runs"], key=lambda r: r["order"])
entries = approval.get("approved_runs")
key = lambda r: (r["run_id"], r["group"], r["task"], r["model"])
ok = (len(runs) == 2 and sorted(r["group"] for r in runs) == ["control", "treatment"]
      and {r["task"] for r in runs} == {"SMOKE"} and isinstance(entries, list) and len(entries) == 2
      and sorted(map(key, runs)) == sorted(key(e) for e in entries if isinstance(e, dict) and set(e) >= {"run_id", "group", "task", "model"}))
if not ok:
    sys.exit(1)
print(" ".join(r["run_id"] for r in runs))
PY
)" || stop "schedule and approval disagree"
PROMPT_SHA="$(sha256sum "$H/../tasks/SMOKE/project/TASK.md" | cut -d' ' -f1)"
note "runs $RUNS (schedule order), prompt $PROMPT_SHA"

# 2. Host: OS users, operator store, pristine SMOKE (unchanged setup-host.sh, opt-in task list).
bash "$H/setup-host.sh" >/dev/null 2>&1 || stop "setup-host.sh failed"
bash "$LIVE/egress-lock.sh" "$MODE" || stop "the agent egress lock could not be established or verified"
SEALED="$AQD_OPERATOR/sealed"
install -m 0600 "$LIVE/smoke-schedule.json" "$SEALED/schedule.json"
if [[ "$MODE" == live || "${AQD_REHEARSE_COMMITTED_APPROVAL:-}" == 1 ]]; then
    install -m 0600 "$LIVE/smoke-approval.json" "$SEALED/cc-run-approved.json"
else
    python3 -I - "$LIVE/smoke-approval.json" "$SEALED/cc-run-approved.json" "$AQD_CLAUDE_BIN" <<'PY'
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

# 3. Native preflight (no model request), then the two runs in schedule order. Any non-zero launcher exit ends it.
bash "$H/preflight-cc.sh" >"$AQD_OPERATOR/preflight.log" 2>&1 || stop "native preflight failed (see the encrypted capture)"
note "native preflight passed"
: >"$AQD_OPERATOR/launcher.log"
for RUN_ID in $RUNS; do
    set +e
    bash "$H/launch-run-cc.sh" "$RUN_ID" >>"$AQD_OPERATOR/launcher.log" 2>&1
    LAUNCH=$?
    set -e
    note "run $RUN_ID: launcher exit $LAUNCH"
    if [[ "$LAUNCH" != 0 ]]; then
        [[ -f "$SEALED/STOP" ]] || printf 'SMOKE FAILED in run %s (launcher exit %s)\n' "$RUN_ID" "$LAUNCH" >"$SEALED/STOP"
        break
    fi
done

# 4. Verdict (smoke-verdict.json in the operator store, packaged and encrypted). Counts and booleans only.
set +e
python3 -I "$LIVE/check_smoke.py" --store "$AQD_OPERATOR" --schedule "$SEALED/schedule.json" \
    --out "$AQD_OPERATOR/smoke-verdict.json"
VERDICT=$?
set -e
if [[ "$VERDICT" != 0 ]]; then
    [[ -f "$SEALED/STOP" ]] || printf 'SMOKE FAILED: the verdict did not pass\n' >"$SEALED/STOP"
    stop "SMOKE did not pass; nothing else may run (STOP written)"
fi
note "SMOKE PASSED"
