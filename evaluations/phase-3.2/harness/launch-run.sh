#!/usr/bin/env bash
# Execute ONE scheduled run of the Phase 3.2 pilot. Run as the operator inside
# the benchmark host, only after the user has authorised execution and
# preflight.sh has passed.
#
# Usage: launch-run.sh RUN_ID
#        launch-run.sh --smoke control|treatment MODEL_REF
#
# MODEL_REF is provider/model[#variant]; for scheduled runs it comes from the
# sealed schedule. The run record (run-record.json) names the exact model,
# interface version, activation mode and the hashes of prompt, project and skill.
#
# Every scheduled run checks isolation and skill registration BEFORE the
# prompt is sent (api_checks.py: no model request), and model, activation,
# contamination and integrity AFTER it (export_checks.py, run_status.py). The
# four-run smoke test therefore needs no separate gate runs.
#
# --smoke runs the never-scored SMOKE task through the identical procedure.
# It is an OPTIONAL diagnostic, not part of the procedure, and it sends one
# model request, so it refuses to start unless the user approved that extra
# call (AQD_EXTRA_MODEL_CALL_APPROVED=yes). Evidence goes to $AQD_OPERATOR/smoke.
#
# The same script serves all three tasks and both groups; everything that
# differs comes from the sealed schedule:
#   task   -> which allowlisted fixture is copied and which TASK.md is sent
#   group  -> treatment only: canonical SKILL.md installed in the run's HOME and
#             attached to the prompt; control: no skill file anywhere
#   env    -> which OS user (aqd-a / aqd-b) and which /aqd/env-* tree
#
# Exit codes: 0 valid run, 1 invalid run (see run-status.json), 20 BLOCKED
# (provider/model/variant unavailable: the whole benchmark stops), 21
# isolation failure (the whole benchmark stops), 2 usage/precondition error.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY="$(python_bin)"
SCHEDULE="$AQD_SEALED/schedule.json"
CAPTURE_BASE="$AQD_CAPTURES"
if [[ "${1:-}" == "--smoke" ]]; then
    GROUP="${2:-}"
    MODEL_REF="${3:-}"
    [[ "$GROUP" =~ ^(control|treatment)$ && -n "$MODEL_REF" ]] \
        || { echo "usage: launch-run.sh --smoke control|treatment MODEL_REF" >&2; exit 2; }
    [[ "${AQD_EXTRA_MODEL_CALL_APPROVED:-}" == "yes" ]] \
        || { log "--smoke sends an extra, unscored model request; set AQD_EXTRA_MODEL_CALL_APPROVED=yes only with the user's approval"; exit 2; }
    TASK="SMOKE"
    RUN_ID="r-$("$PY" -c 'import secrets; print(secrets.token_hex(5))')"
    ENV_LABEL="$(json_get "$SCHEDULE" env_for_group | "$PY" -c "import json, sys; print(json.load(sys.stdin)['$GROUP'])")"
    CAPTURE_BASE="$AQD_OPERATOR/smoke"
    install -d -m 0700 "$CAPTURE_BASE"
else
    RUN_ID="${1:-}"
    [[ "$RUN_ID" =~ ^r-[0-9a-f]{10}$ ]] || { echo "usage: launch-run.sh RUN_ID (r-<10 hex>)" >&2; exit 2; }
    # Anything larger than the 2x2 smoke design is the pilot, which needs the
    # user's approval after the smoke test was reviewed (SPECIFICATION.md section 2).
    RUN_COUNT="$("$PY" -c 'import json, sys; print(sum(1 for r in json.load(open(sys.argv[1]))["runs"] if "replaces_slot" not in r))' "$SCHEDULE")"
    if (( RUN_COUNT > 4 )) && [[ ! -f "$AQD_SEALED/pilot-approved.json" ]]; then
        log "this schedule has $RUN_COUNT runs: the pilot needs the user's written approval in $AQD_SEALED/pilot-approved.json"
        exit 2
    fi
    sched() { "$PY" "$AQD_HARNESS/schedule.py" get --schedule "$SCHEDULE" --run-id "$RUN_ID" --key "$1"; }
    TASK="$(sched task)"
    GROUP="$(sched group)"
    ENV_LABEL="$(sched env)"
    MODEL_REF="$(sched model)"
fi
parse_model_ref "$MODEL_REF"
[[ -f "$AQD_SEALED/preflight.ok" ]] || { log "preflight has not passed"; exit 2; }
[[ ! -f "$AQD_SEALED/STOP" ]] || { log "benchmark stopped: $(cat "$AQD_SEALED/STOP")"; exit 2; }
[[ "$AQD_ACTIVATION_MODE" =~ ^(api-attachment|cli-mention)$ ]] || { log "unknown activation mode"; exit 2; }
if [[ -f "$AQD_SEALED/activation-mode" ]]; then
    [[ "$(cat "$AQD_SEALED/activation-mode")" == "$AQD_ACTIVATION_MODE" ]] \
        || { log "activation mode differs from the one used by earlier runs"; exit 2; }
else
    printf '%s' "$AQD_ACTIVATION_MODE" >"$AQD_SEALED/activation-mode"
fi
[[ "$AQD_SCOPE_POLICY" =~ ^(invalidate|outcome)$ ]] || { log "unknown scope policy"; exit 2; }
if [[ -f "$AQD_SEALED/scope-policy" ]]; then
    [[ "$(cat "$AQD_SEALED/scope-policy")" == "$AQD_SCOPE_POLICY" ]] \
        || { log "scope policy differs from the one used by earlier runs"; exit 2; }
else
    printf '%s' "$AQD_SCOPE_POLICY" >"$AQD_SEALED/scope-policy"
fi

AGENT_USER="${AQD_USER_FOR_ENV[$ENV_LABEL]}"
OTHER_ENV="env-a"; [[ "$ENV_LABEL" == "env-a" ]] && OTHER_ENV="env-b"

CAP="$CAPTURE_BASE/$RUN_ID"
RUN_ROOT="$AQD_ROOT/$ENV_LABEL/runs/$RUN_ID"
PROJECT="$RUN_ROOT/project"
RUN_HOME="$RUN_ROOT/home"
RUN_TMP="$RUN_ROOT/tmp"
PRISTINE="$AQD_PRISTINE/$TASK"
MANIFEST="$PRISTINE/manifest.json"
MESSAGE_FILE="$PRISTINE/project/TASK.md"

[[ ! -e "$CAP" ]] || { log "capture $CAP exists: run ids are never reused"; exit 2; }
sudo test ! -e "$RUN_ROOT" || { log "$RUN_ROOT exists"; exit 2; }
install -d -m 0700 "$CAP" "$CAP/driver"
exec > >(tee -a "$CAP/launcher.log") 2>&1

STEP="start"
API_EXIT=99
DRIVER_EXIT=99
SERVE_PID=""
STARTED="$(date +%s)"
ENDED="$STARTED"

finish() {
    local rc=$?
    set +e
    [[ -n "$SERVE_PID" ]] && kill "$SERVE_PID" 2>/dev/null
    kill_user_processes "$AGENT_USER"
    if [[ ! -f "$CAP/run-status.json" ]]; then
        "$PY" "$AQD_HARNESS/run_status.py" --capture "$CAP" --group "$GROUP" --started "$STARTED" \
            --ended "$(date +%s)" --api-exit "$API_EXIT" --driver-exit "$DRIVER_EXIT" --step "$STEP" >/dev/null
    fi
    # Nothing of this run may remain where a later run of the same user could read it.
    sudo rm -rf --one-file-system "$RUN_ROOT"
    sudo find /tmp /var/tmp /dev/shm -xdev -user "$AGENT_USER" -delete 2>/dev/null
    log "run $RUN_ID finished (exit $rc); evidence in $CAP"
    exit "$rc"
}
trap finish EXIT

log "run $RUN_ID: task $TASK, model $MODEL_REF, environment $ENV_LABEL, mode $AQD_ACTIVATION_MODE"

STEP="preconditions"
for env in "${AQD_ENVS[@]}"; do assert_no_processes "${AQD_USER_FOR_ENV[$env]}"; done
# Hidden tests and inventories may reach this host only after every agent run.
[[ -z "$(find "$AQD_EVALUATOR" -mindepth 1 -print -quit 2>/dev/null)" ]] \
    || die "$AQD_EVALUATOR is not empty: evaluator material must not be on the host while agents run"
"$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$MANIFEST" --tree "$PRISTINE/project" --phase pre \
    --out "$CAP/pristine-check.json" >/dev/null || die "pristine store for $TASK is not intact"
sha256sum --quiet -c "$AQD_SEALED/pristine-extra.sha256" || die "pristine skill/config changed"

STEP="build-home"
sudo install -d -o root -g root -m 0711 "$RUN_ROOT"
sudo install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 0700 "$RUN_HOME" "$RUN_TMP" \
    "$RUN_HOME/.local" "$RUN_HOME/.local/share" "$RUN_HOME/.local/state" "$RUN_HOME/.cache"
sudo install -d -o root -g root -m 0755 "$RUN_HOME/.config" "$RUN_HOME/.config/opencode"
sudo install -o root -g root -m 0444 "$AQD_PRISTINE/config/global-opencode.jsonc" "$RUN_HOME/.config/opencode/opencode.jsonc"
if [[ "$GROUP" == "treatment" ]]; then
    sudo install -d -o root -g root -m 0755 "$RUN_HOME/.config/opencode/skills" "$RUN_HOME/.config/opencode/skills/$AQD_SKILL_ID"
    sudo install -o root -g root -m 0444 "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" \
        "$RUN_HOME/.config/opencode/skills/$AQD_SKILL_ID/SKILL.md"
fi

STEP="build-project"
# Kernel-enforced immutability without mounts: immutable files are root-owned
# 0444 inside root-owned sticky (1777) directories, so the agent user can
# create files but cannot modify, delete, rename over or chmod them.
# tests/baseline is root-owned 0755 (no new files); tests/additive belongs to
# the agent. The agent has no sudo (checked by preflight.sh).
sudo install -d -o root -g root -m 1777 "$PROJECT"
while IFS= read -r -d '' kind && IFS= read -r -d '' rel; do
    case "$kind" in
        dir)           sudo install -d -o root -g root -m 1777 "$PROJECT/$rel" ;;
        dir-protected) sudo install -d -o root -g root -m 0755 "$PROJECT/$rel" ;;
        dir-additive)  sudo install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 0755 "$PROJECT/$rel" ;;
        immutable)     sudo install -o root -g root -m 0444 "$PRISTINE/project/$rel" "$PROJECT/$rel" ;;
        mutable|additive) sudo install -o "$AGENT_USER" -g "$AGENT_USER" -m 0644 "$PRISTINE/project/$rel" "$PROJECT/$rel" ;;
        *) die "unknown manifest category $kind for $rel" ;;
    esac
done < <("$PY" "$AQD_HARNESS/manifest.py" categories --manifest "$MANIFEST")

STEP="verify-pre"
assert_clean_ancestors "$PROJECT"
sudo "$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$MANIFEST" --tree "$PROJECT" --phase pre \
    --out "$CAP/verify-pre.json" >/dev/null || die "pre-run tree does not match the manifest"
sudo chown "$(id -u):$(id -g)" "$CAP/verify-pre.json"
assert_unreadable_by "$AGENT_USER" "$AQD_OPERATOR" "$AQD_CHECKOUT" "$HOME" /workspaces/.codespaces "$AQD_ROOT/$OTHER_ENV"
if sudo -u "$AGENT_USER" test -w "$PROJECT/TASK.md"; then die "agent can write an immutable file"; fi
MUTABLE_REL="$("$PY" -c 'import json, sys; print(next(f["path"] for f in json.load(open(sys.argv[1]))["files"] if f["category"] == "mutable"))' "$MANIFEST")"
sudo -u "$AGENT_USER" test -w "$PROJECT/$MUTABLE_REL" || die "agent cannot write $MUTABLE_REL"
sudo find "$RUN_HOME/.config" -mindepth 1 -printf '%P\n' | sort >"$CAP/home-config-listing.pre.txt"

STEP="agent-env"
PASSWORD="$(random_secret)"
make_agent_env "$RUN_ROOT" "$PASSWORD"
add_provider_credential "$MODEL_PROVIDER"
"$PY" - "$CAP/run-record.json" "$RUN_ID" "$TASK" "$GROUP" "$MODEL_REF" "$AQD_ACTIVATION_MODE" "$MESSAGE_FILE" "$MANIFEST" \
    "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" "$(opencode_version)" \
    "$AQD_PRISTINE/config/global-opencode.jsonc" "$AQD_SEALED/opencode-install.json" "$AQD_AGENT" "$AQD_RUN_TIMEOUT_SECONDS" \
    "$AQD_SCOPE_POLICY" <<'PY'
import datetime, hashlib, json, os, sys
out, run_id, task, group, model, mode, prompt, manifest, skill, version, config, install, agent, timeout, scope = sys.argv[1:16]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
provider, model_id, variant = model.split("/", 1)[0], model.split("/", 1)[1].split("#")[0], (model.split("#", 1)[1] if "#" in model else None)
json.dump({"schema_version": 2, "run_id": run_id, "task": task, "group": group, "model": model,
           "model_provider": provider, "model_id": model_id, "model_variant": variant,
           "interface": f"opencode {version}", "activation_mode": mode, "agent": agent, "timeout_seconds": int(timeout),
           "scope_policy": scope,
           "skill": {"installed": group == "treatment", "sha256": sha(skill) if group == "treatment" else None},
           "prompt_sha256": sha(prompt), "workspace_sha256": json.load(open(manifest, encoding="utf-8"))["workspace_sha256"],
           "global_config_sha256": sha(config),
           "opencode_install_tree_sha256": json.load(open(install, encoding="utf-8"))["tree_sha256"] if os.path.exists(install) else None,
           "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()},
          open(out, "w", encoding="utf-8"), indent=2)
PY
if [[ "$TASK" == "SMOKE" && "${AQD_DEBUG_LOG:-0}" == "1" ]]; then
    AGENT_ENV+=("OPENCODE_LOG_LEVEL=DEBUG")   # optional diagnostic only; never in scored runs
fi
as_agent "$AGENT_USER" "$PROJECT" "$AQD_OPENCODE_BIN" debug paths >"$CAP/debug-paths.txt" 2>&1 \
    || die "'opencode debug paths' failed"
"$PY" - "$CAP/debug-paths.txt" "$RUN_ROOT" "$AQD_OPENCODE_PREFIX" <<'PY' || die "OpenCode resolves paths outside the run"
import re, sys
text, roots = open(sys.argv[1], encoding="utf-8").read(), sys.argv[2:]
paths = re.findall(r"(/[^\s'\"]+)", text)
bad = [p for p in paths if not any(p == r or p.startswith(r.rstrip("/") + "/") for r in roots)]
if not paths or bad:
    print("paths outside the run:", bad or "none reported", file=sys.stderr)
    sys.exit(1)
PY

STEP="serve"
PORT="$(free_port)"
SERVER="http://127.0.0.1:$PORT"
as_agent "$AGENT_USER" "$PROJECT" "$AQD_OPENCODE_BIN" serve --hostname 127.0.0.1 --port "$PORT" >"$CAP/serve.log" 2>&1 &
SERVE_PID=$!
for _ in $(seq 1 90); do
    curl -fsS -u "opencode:$PASSWORD" "$SERVER/api/info" -o "$CAP/server-info.json" 2>/dev/null && break
    sleep 1
done
[[ -s "$CAP/server-info.json" ]] || die "server did not become healthy"

STEP="api-checks"
set +e
OPENCODE_PASSWORD="$PASSWORD" "$PY" "$AQD_HARNESS/api_checks.py" --server "$SERVER" --directory "$PROJECT" \
    --group "$GROUP" --model "$MODEL_REF" --allowed-root "$RUN_ROOT" --allowed-root "$AQD_OPENCODE_PREFIX" --out "$CAP/api-checks.json"
API_EXIT=$?
set -e
case "$API_EXIT" in
    0) ;;
    10|11|12) printf 'BLOCKED by run %s: api_checks exit %s\n' "$RUN_ID" "$API_EXIT" >"$AQD_SEALED/STOP"; exit 20 ;;
    13) printf 'ISOLATION FAILURE in run %s\n' "$RUN_ID" >"$AQD_SEALED/STOP"; exit 21 ;;
    *) die "api checks failed (exit $API_EXIT)" ;;
esac

STEP="session"
STARTED="$(date +%s)"
set +e
if [[ "$AQD_ACTIVATION_MODE" == "api-attachment" ]]; then
    ATTACH=()
    [[ "$GROUP" == "treatment" ]] && ATTACH=(--attach-skill "$AQD_SKILL_ID")
    VARIANT_ARGS=()
    [[ -n "$MODEL_VARIANT" ]] && VARIANT_ARGS=(--variant "$MODEL_VARIANT")
    OPENCODE_PASSWORD="$PASSWORD" timeout --kill-after=60 "$((AQD_RUN_TIMEOUT_SECONDS + 600))" \
        "$PY" "$AQD_HARNESS/drive_session.py" --server "$SERVER" --directory "$PROJECT" \
        --message-file "$MESSAGE_FILE" --provider "$MODEL_PROVIDER" --model "$MODEL_ID" "${VARIANT_ARGS[@]}" \
        --agent "$AQD_AGENT" --timeout "$AQD_RUN_TIMEOUT_SECONDS" --out-dir "$CAP/driver" "${ATTACH[@]}"
    DRIVER_EXIT=$?
else
    # Fallback mode (requires user approval): documented `opencode run` with an
    # @-mention. The treatment text differs from control by its first line.
    cp "$MESSAGE_FILE" "$CAP/message.txt"
    if [[ "$GROUP" == "treatment" ]]; then
        { printf '@%s\n\n' "$AQD_SKILL_ID"; cat "$MESSAGE_FILE"; } >"$CAP/message.txt"
    fi
    as_agent "$AGENT_USER" "$PROJECT" timeout --kill-after=60 "$AQD_RUN_TIMEOUT_SECONDS" "$AQD_OPENCODE_BIN" run \
        --server "$SERVER" --model "$MODEL_REF" --agent "$AQD_AGENT" --format json --auto \
        "$(cat "$CAP/message.txt")" >"$CAP/run-events.ndjson" 2>"$CAP/run.stderr"
    RUN_EXIT=$?
    OPENCODE_PASSWORD="$PASSWORD" "$PY" "$AQD_HARNESS/drive_session.py" --server "$SERVER" --export-existing \
        --out-dir "$CAP/driver"
    DRIVER_EXIT=$?
    if [[ "$RUN_EXIT" == 124 || "$RUN_EXIT" == 137 ]]; then
        "$PY" - "$CAP/driver/driver-result.json" <<'PY'
import json, sys
r = json.load(open(sys.argv[1])); r["status"] = "timeout"; json.dump(r, open(sys.argv[1], "w"), indent=2)
PY
    fi
fi
ENDED="$(date +%s)"

STEP="cli-export"
SESSION_ID="$(json_get "$CAP/driver/driver-result.json" session_id 2>/dev/null || true)"
if [[ "$SESSION_ID" =~ ^ses ]]; then
    as_agent "$AGENT_USER" "$PROJECT" "$AQD_OPENCODE_BIN" session export "$SESSION_ID" --server "$SERVER" \
        >"$CAP/cli-export.json" 2>"$CAP/cli-export.err"
    echo "$?" >"$CAP/cli-export.exit"
fi
set -e

STEP="stop"
kill "$SERVE_PID" 2>/dev/null || true
wait "$SERVE_PID" 2>/dev/null || true
SERVE_PID=""
kill_user_processes "$AGENT_USER"
assert_no_processes "$AGENT_USER"

STEP="capture"
install -d -m 0700 "$CAP/project-final" "$CAP/opencode-data"
sudo tar -C "$PROJECT" -cf - . | tar -C "$CAP/project-final" -xf - --no-same-owner --no-same-permissions
sudo tar -C "$RUN_HOME/.local/share" -cf - . | tar -C "$CAP/opencode-data" -xf - --no-same-owner --no-same-permissions
sudo find "$RUN_HOME/.config" -mindepth 1 -printf '%P\n' | sort >"$CAP/home-config-listing.txt"
chmod -R u+rwX "$CAP"

STEP="verify-post"
set +e
"$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$MANIFEST" --tree "$CAP/project-final" --phase post \
    --out "$CAP/verify-post.json"
diff -ruN -x __pycache__ -x '*.pyc' -x .pytest_cache "$PRISTINE/project" "$CAP/project-final" >"$CAP/diff.patch"
[[ $? -le 1 ]] || log "diff reported an error"
EXPORT="$CAP/driver/export.json"
[[ -s "$EXPORT" ]] || EXPORT="$CAP/cli-export.json"
"$PY" "$AQD_HARNESS/export_checks.py" --export "$EXPORT" --group "$GROUP" --model "$MODEL_REF" --out "$CAP/export-checks.json"
set -e

STEP="done"
set +e
"$PY" "$AQD_HARNESS/run_status.py" --capture "$CAP" --group "$GROUP" --started "$STARTED" --ended "$ENDED" \
    --api-exit "$API_EXIT" --driver-exit "$DRIVER_EXIT" --step "$STEP"
RESULT=$?
set -e
exit "$RESULT"
