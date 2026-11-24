#!/usr/bin/env bash
# Run the hidden checks for every valid run, after ALL agent runs are finished.
#
# Trust boundary: score_run.py (scoring logic, inventory, validation) runs as
# the operator and is never visible to candidate code. Only the test process
# runs inside a fresh Docker container per test: no network, read-only code,
# non-root, no host environment (see score_run.py and tests/test_sandbox.py).
# Hidden tests are uploaded to $AQD_EVALUATOR only now, never earlier.
#
# Usage: AQD_SANDBOX_IMAGE=python:3.12-slim@sha256:... score-all.sh
# Expects $AQD_EVALUATOR/hidden_tests/<TASK>/hidden_tests/ and
#         $AQD_EVALUATOR/inventory/<TASK>.json for every scheduled task.
# A run whose evaluation is INVALID gets a hidden-score.json with
# evaluation_status "invalid" and no primary outcome; analyze.py reports it.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY="$(python_bin)"
IMAGE="${AQD_SANDBOX_IMAGE:-}"
[[ "$IMAGE" == *@sha256:* ]] || die "set AQD_SANDBOX_IMAGE to an image pinned by digest"
require_cmd docker
set +e
"$PY" "$AQD_HARNESS/schedule.py" next --schedule "$AQD_SEALED/schedule.json" --captures "$AQD_CAPTURES" >/dev/null
[[ $? == 3 ]] || die "scheduled runs remain; score only after every run has finished"
set -e
for env in "${AQD_ENVS[@]}"; do
    user="${AQD_USER_FOR_ENV[$env]}"
    kill_user_processes "$user"
    assert_no_processes "$user"
    sudo usermod -L "$user" >/dev/null
done
# Demonstrate the boundary on this host before trusting it.
set +e
SANDBOX_LOG="$(AQD_SANDBOX_IMAGE="$IMAGE" "$PY" -m unittest discover -s "$AQD_PHASE_ROOT/tests" -p test_sandbox.py -v 2>&1)"
SANDBOX_RC=$?
set -e
printf '%s\n' "$SANDBOX_LOG" >"$AQD_SEALED/sandbox-tests.log"
[[ "$SANDBOX_RC" == 0 ]] || die "sandbox isolation tests failed on this host (see sandbox-tests.log)"
grep -q "skipped" <<<"$SANDBOX_LOG" && die "sandbox isolation tests were skipped; the boundary is not demonstrated"

while IFS= read -r RUN_ID; do
    CAP="$AQD_CAPTURES/$RUN_ID"
    [[ -f "$CAP/run-status.json" ]] || continue
    [[ "$(json_get "$CAP/run-status.json" valid)" == "True" ]] || { log "skip invalid run $RUN_ID"; continue; }
    [[ -f "$CAP/hidden-score.json" ]] && { log "already scored $RUN_ID"; continue; }
    TASK="$("$PY" "$AQD_HARNESS/schedule.py" get --schedule "$AQD_SEALED/schedule.json" --run-id "$RUN_ID" --key task)"
    [[ -d "$AQD_EVALUATOR/hidden_tests/$TASK/hidden_tests" ]] || die "hidden tests for $TASK not uploaded"
    [[ -f "$AQD_EVALUATOR/inventory/$TASK.json" ]] || die "inventory for $TASK not uploaded"
    set +e
    "$PY" "$AQD_HARNESS/score_run.py" score --phase-root "$AQD_PHASE_ROOT" --task "$TASK" \
        --pristine "$AQD_PRISTINE/$TASK/project" --agent "$CAP/project-final" \
        --hidden "$AQD_EVALUATOR/hidden_tests/$TASK" --inventory "$AQD_EVALUATOR/inventory/$TASK.json" \
        --sandbox docker --image "$IMAGE" --out "$CAP/hidden-score.json"
    RC=$?
    set -e
    case "$RC" in
        0) ;;
        3) log "EVALUATION INVALID for $RUN_ID (see hidden-score.json); it will be reported, never scored" ;;
        *) rm -f "$CAP/hidden-score.json"; die "score_run.py failed for $RUN_ID (exit $RC)" ;;
    esac
done < <("$PY" -c 'import json, sys; [print(r["run_id"]) for r in json.load(open(sys.argv[1]))["runs"]]' "$AQD_SEALED/schedule.json")
log "hidden scoring complete; next: blind_packet.py"
