#!/usr/bin/env bash
# Run the scheduled benchmark runs in sealed order, one at a time.
# Stops at the first run that is not valid, so a human reviews every
# exclusion before anything else happens. Never reruns automatically.
#
# Usage: run-all.sh [--max N]
# Exit 0 when no scheduled run is left; otherwise the launcher's exit code.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

MAX=1000
if [[ "${1:-}" == "--max" ]]; then MAX="${2:?--max needs a number}"; fi
[[ "$MAX" =~ ^[0-9]+$ ]] || die "--max must be a number"

done_count=0
while (( done_count < MAX )); do
    set +e
    RUN_ID="$("$(python_bin)" "$AQD_HARNESS/schedule.py" next --schedule "$AQD_SEALED/schedule.json" --captures "$AQD_CAPTURES")"
    NEXT=$?
    set -e
    if [[ "$NEXT" == 3 ]]; then
        log "no scheduled run left"
        exit 0
    fi
    [[ "$NEXT" == 0 ]] || die "could not read the schedule"
    set +e
    bash "$AQD_HARNESS/launch-run.sh" "$RUN_ID"
    RC=$?
    set -e
    case "$RC" in
        0)  done_count=$((done_count + 1)) ;;
        1)  log "run $RUN_ID is INVALID. Review $AQD_CAPTURES/$RUN_ID/run-status.json."
            log "If the cause qualifies for a rerun under SPECIFICATION.md section 6.2:"
            log "  python3 $AQD_HARNESS/schedule.py rerun --schedule $AQD_SEALED/schedule.json --run-id $RUN_ID --reason '...'"
            exit 1 ;;
        20) log "BENCHMARK BLOCKED (provider/model/variant). A user decision is required."; exit 20 ;;
        21) log "ISOLATION FAILURE. Stop and investigate before any further run."; exit 21 ;;
        *)  log "launcher error $RC for $RUN_ID"; exit "$RC" ;;
    esac
done
log "stopped after $done_count run(s) (--max)"
