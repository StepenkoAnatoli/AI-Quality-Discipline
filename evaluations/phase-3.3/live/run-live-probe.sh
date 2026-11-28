#!/usr/bin/env bash
# The unscored credential-boundary probe: ONE approved run of task PROBE-CC through the unchanged native harness.
# The SAME script runs the mock rehearsal (mock CLI, synthetic token) and, once authorised, the live probe.
#
# Usage: run-live-probe.sh rehearsal|live RUN_ID
#
# Required environment:
#   AQD_CLAUDE_BIN     the CLI (live: the pinned real binary; rehearsal: the mock)
#   AQD_CREDENTIALS    0600 file with exactly one CLAUDE_CODE_OAUTH_TOKEN= line (live: written by the one workflow
#                      step that references the secret; rehearsal: written here with a synthetic value)
#   AQD_OPERATOR       operator-only store (fresh per invocation)
#
# Inputs are committed, reviewed files, verified against the hashes below before use:
#   probe-schedule.json  precomputed from a public seed; RUN_ID must be its control run
#   probe-approval.json  the owner's approval of exactly that run, prompt SHA-256 and CLI SHA-256
# In rehearsal mode the approval's cli_sha256 is replaced by the mock's hash (the only difference) and the
# approver fields are filled with "rehearsal"; live mode uses the committed approval byte for byte (and so does a
# rehearsal with AQD_REHEARSE_COMMITTED_APPROVAL=1, which must then be refused).
#
# Exit: 0 = probe PASSED; 1 = probe FAILED or refused (STOP written where the harness writes one); 2 = usage.
# Public output: fixed lines and counts only. Never a value, never the transcript.
set -euo pipefail
umask 077

MODE="${1:-}"; RUN_ID="${2:-}"
[[ "$MODE" == rehearsal || "$MODE" == live ]] || { echo "usage: run-live-probe.sh rehearsal|live RUN_ID" >&2; exit 2; }
[[ "$RUN_ID" =~ ^r-[0-9a-f]{10}$ ]] || { echo "STOP: bad run id" >&2; exit 2; }
: "${AQD_CLAUDE_BIN:?}" "${AQD_CREDENTIALS:?}" "${AQD_OPERATOR:?}"
export AQD_CLAUDE_BIN AQD_CREDENTIALS AQD_OPERATOR AQD_TASKS=PROBE-CC
unset AQD_CC_DRY_RUN AQD_CC_RUN_TIMEOUT_SECONDS  # the pre-registered 2700 s timeout; never a dry-run override

LIVE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
H="$(cd "$LIVE/../../phase-3.2/harness" && pwd)"
SCHEDULE_SHA256="a0ae181e8f99c7be4ac43446df1f0eacae56f3a1589f8beb2f72c6311ed29bc9"
note() { printf '[probe] %s\n' "$*"; }
stop() { note "STOP: $*"; exit 1; }

# 1. The committed schedule and approval, and the run they name.
echo "$SCHEDULE_SHA256  $LIVE/probe-schedule.json" | sha256sum -c --quiet || stop "probe-schedule.json is not the reviewed file"
python3 -I - "$LIVE/probe-schedule.json" "$LIVE/probe-approval.json" "$RUN_ID" <<'PY' || stop "run id, schedule and approval disagree"
import json, sys
schedule, approval, run_id = json.load(open(sys.argv[1])), json.load(open(sys.argv[2])), sys.argv[3]
control = [r for r in schedule["runs"] if r["group"] == "control"]
entries = approval.get("approved_runs")
ok = (len(control) == 1 and control[0]["run_id"] == run_id and isinstance(entries, list) and len(entries) == 1
      and entries[0].get("run_id") == run_id and entries[0].get("group") == "control"
      and entries[0].get("task") == "PROBE-CC" == control[0]["task"])
sys.exit(0 if ok else 1)
PY
PROMPT_SHA="$(sha256sum "$H/../tasks/PROBE-CC/project/TASK.md" | cut -d' ' -f1)"
note "run $RUN_ID (control, PROBE-CC), prompt $PROMPT_SHA"

# 2. Host: OS users, operator store, pristine PROBE-CC (unchanged setup-host.sh, opt-in task list).
bash "$H/setup-host.sh" >/dev/null 2>&1 || stop "setup-host.sh failed"
bash "$LIVE/egress-lock.sh" "$MODE" || stop "the agent egress lock could not be established or verified"
SEALED="$AQD_OPERATOR/sealed"
install -m 0600 "$LIVE/probe-schedule.json" "$SEALED/schedule.json"
if [[ "$MODE" == live || "${AQD_REHEARSE_COMMITTED_APPROVAL:-}" == 1 ]]; then
    install -m 0600 "$LIVE/probe-approval.json" "$SEALED/cc-run-approved.json"
else
    python3 -I - "$LIVE/probe-approval.json" "$SEALED/cc-run-approved.json" "$AQD_CLAUDE_BIN" <<'PY'
import hashlib, json, sys
a = json.load(open(sys.argv[1]))
a["approved_runs"][0]["cli_sha256"] = hashlib.sha256(open(sys.argv[3], "rb").read()).hexdigest()
a["approved_by"], a["approved_utc"] = "rehearsal (mock CLI)", "2026-11-23T00:00:00Z"
json.dump(a, open(sys.argv[2], "w"), indent=2)
PY
    if [[ ! -s "$AQD_CREDENTIALS" ]]; then
        printf 'CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-REHEARSAL-SYNTHETIC-%s\n' "$(python3 -c 'import secrets; print(secrets.token_hex(16))')" >"$AQD_CREDENTIALS"
    fi
fi
[[ "$(stat -c %a "$AQD_CREDENTIALS")" == 600 ]] || stop "credentials file is not 0600"

# 3. Native preflight (no model request, no authentication), then the one run.
bash "$H/preflight-cc.sh" >"$AQD_OPERATOR/preflight.log" 2>&1 || stop "native preflight failed (see the encrypted capture)"
note "native preflight passed"
set +e
bash "$H/launch-run-cc.sh" "$RUN_ID" >"$AQD_OPERATOR/launcher.log" 2>&1
LAUNCH=$?
set -e
CAP="$AQD_OPERATOR/captures/$RUN_ID"
note "launcher exit $LAUNCH"

# 4. Verdict: a valid harness run AND a passing probe. Counts only.
VERDICT=1
if [[ -d "$CAP" ]]; then
    set +e
    python3 -I "$LIVE/check_live_probe.py" --transcript "$CAP/driver/transcript.ndjson" --out "$CAP/live-probe.json" >/dev/null
    PROBE=$?
    set -e
    python3 -I - "$CAP" "$LAUNCH" "$PROBE" <<'PY' && VERDICT=0 || VERDICT=1
import json, os, sys
cap, launch, probe = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
load = lambda p: json.load(open(os.path.join(cap, p))) if os.path.exists(os.path.join(cap, p)) else {}
status, live = load("run-status.json"), load("live-probe.json")
c = live.get("counts") or {}
print("[probe] run valid: %s; probe: %s; exposure: %s" % (status.get("valid"), "PASS" if live.get("pass") else "FAIL",
                                                        bool(live.get("exposure"))))
if c:
    print("[probe] counts: bash_env=%d bash_env_sk_ant=%d self_environ=%d proc_readable=%d/%d with_token_var=%d "
          "with_sk_ant=%d pid1=%s" % (c["bash_env_token_vars"], c["bash_env_sk_ant"], c["self_environ_token_vars"],
          c["proc_environ_readable"], c["proc_environ_total"], c["with_token_var"], c["with_sk_ant"], c["pid1"]))
sys.exit(0 if launch == 0 and probe == 0 and status.get("valid") is True and live.get("pass") is True else 1)
PY
fi
if [[ "$VERDICT" != 0 ]]; then
    [[ -f "$SEALED/STOP" ]] || printf 'PROBE FAILED in run %s\n' "$RUN_ID" >"$SEALED/STOP"
    stop "the probe did not pass; nothing else may run (STOP written)"
fi
note "PROBE PASSED"
