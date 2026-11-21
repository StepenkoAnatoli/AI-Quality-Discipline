#!/usr/bin/env bash
# Run the hidden checks for every valid run, after ALL agent runs are finished.
# Hidden tests are uploaded to $AQD_EVALUATOR only now, never earlier. Agent
# code is executed as the unprivileged $AQD_EVAL_USER in a scratch directory
# that contains only that run's code, the pristine task and that task's hidden
# tests.
#
# Usage: score-all.sh
# Expects $AQD_EVALUATOR/hidden_tests/<TASK>/hidden_tests/ for NEW-01..03.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY="$(python_bin)"
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
for task in NEW-01 NEW-02 NEW-03; do
    [[ -d "$AQD_EVALUATOR/hidden_tests/$task/hidden_tests" ]] || die "hidden tests for $task not uploaded"
done

SCORE_ROOT="$AQD_ROOT/score"
sudo install -d -o root -g root -m 0711 "$SCORE_ROOT"
while IFS= read -r RUN_ID; do
    CAP="$AQD_CAPTURES/$RUN_ID"
    [[ -f "$CAP/run-status.json" ]] || continue
    [[ "$(json_get "$CAP/run-status.json" valid)" == "True" ]] || { log "skip invalid $RUN_ID"; continue; }
    [[ -f "$CAP/hidden-score.json" ]] && { log "already scored $RUN_ID"; continue; }
    TASK="$("$PY" "$AQD_HARNESS/schedule.py" get --schedule "$AQD_SEALED/schedule.json" --run-id "$RUN_ID" --key task)"
    WORK="$SCORE_ROOT/$RUN_ID"
    sudo install -d -o "$AQD_EVAL_USER" -g "$AQD_EVAL_USER" -m 0700 "$WORK" "$WORK/tmp" "$WORK/phase" "$WORK/phase/harness"
    stage() { sudo tar -C "$1" -cf - . | sudo -u "$AQD_EVAL_USER" tar -C "$2" -xf - --no-same-owner; }
    sudo -u "$AQD_EVAL_USER" mkdir -p "$WORK/agent" "$WORK/pristine" "$WORK/hidden"
    stage "$CAP/project-final" "$WORK/agent"
    stage "$AQD_PRISTINE/$TASK/project" "$WORK/pristine"
    stage "$AQD_EVALUATOR/hidden_tests/$TASK" "$WORK/hidden"
    sudo install -o "$AQD_EVAL_USER" -g "$AQD_EVAL_USER" -m 0600 "$AQD_PHASE_ROOT/allowlist.json" "$WORK/phase/allowlist.json"
    for f in score_run.py run_checks.py manifest.py; do
        sudo install -o "$AQD_EVAL_USER" -g "$AQD_EVAL_USER" -m 0600 "$AQD_HARNESS/$f" "$WORK/phase/harness/$f"
    done
    set +e
    (cd / && sudo -u "$AQD_EVAL_USER" env -i HOME="$WORK" TMPDIR="$WORK/tmp" PATH="$(agent_path)" LANG=C.UTF-8 \
        python3 "$WORK/phase/harness/score_run.py" --phase-root "$WORK/phase" --task "$TASK" \
        --pristine "$WORK/pristine" --agent "$WORK/agent" --hidden "$WORK/hidden" --out "$WORK/hidden-score.json")
    RC=$?
    set -e
    if [[ "$RC" == 0 ]]; then
        sudo cat "$WORK/hidden-score.json" >"$CAP/hidden-score.json"
    else
        log "scoring failed for $RUN_ID (exit $RC)"
    fi
    kill_user_processes "$AQD_EVAL_USER"
    sudo rm -rf --one-file-system "$WORK"
done < <("$PY" -c 'import json, sys; [print(r["run_id"]) for r in json.load(open(sys.argv[1]))["runs"]]' "$AQD_SEALED/schedule.json")
log "hidden scoring complete; next: blind_packet.py"
