#!/usr/bin/env bash
# Execute ONE scheduled run with NATIVE CLAUDE CODE (Phase 3.3 feasibility; execution environment
# "native-claude-code"). The OpenCode launcher, launch-run.sh, is unchanged and remains the Phase 3.2 reference.
#
# Usage: launch-run-cc.sh RUN_ID
#
# NOT YET EXECUTED ANYWHERE: only static checks (bash -n, shellcheck when present) and the offline adapter tests
# have run. Running it sends a model request on the owner's subscription; it refuses unless the owner approved
# that run in writing ($AQD_SEALED/cc-run-approved.json) and preflight has passed.
#
# Reused unchanged from launch-run.sh / lib.sh: sealed schedule lookup, preflight and STOP gates, the
# evaluator-must-be-empty rule, per-group OS users, root-owned immutable project tree from the manifest,
# pre/post manifest verification, diff capture, process kill and run-root removal, run_status.py.
# Replaced: OpenCode HOME, server, api_checks, session driver and export -> cc_adapter.py (auth-status, run,
# check-transcript) and cc_exec.sh. The arms differ ONLY in the run's CLAUDE_CONFIG_DIR/skills directory
# (treatment: the canonical SKILL.md, root-owned read-only); prompt, command, settings and environment are
# byte-identical.
#
# Exit codes: 0 valid run, 1 invalid run, 20 BLOCKED (auth/billing check failed: the benchmark stops),
# 21 isolation failure (the benchmark stops), 2 usage/precondition error.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY="$(python_bin)"
SCHEDULE="$AQD_SEALED/schedule.json"
CC="$AQD_HARNESS/cc_adapter.py"
: "${AQD_CLAUDE_BIN:?AQD_CLAUDE_BIN (the pinned claude binary, executable by the agent users) is required}"
AQD_CC_MAX_TURNS="${AQD_CC_MAX_TURNS:-200}"

RUN_ID="${1:-}"
[[ "$RUN_ID" =~ ^r-[0-9a-f]{10}$ ]] || { echo "usage: launch-run-cc.sh RUN_ID (r-<10 hex>)" >&2; exit 2; }
[[ -f "$AQD_SEALED/cc-run-approved.json" ]] \
    || { log "native Claude Code runs need the owner's written approval in $AQD_SEALED/cc-run-approved.json"; exit 2; }
sched() { "$PY" "$AQD_HARNESS/schedule.py" get --schedule "$SCHEDULE" --run-id "$RUN_ID" --key "$1"; }
TASK="$(sched task)"
GROUP="$(sched group)"
ENV_LABEL="$(sched env)"
MODEL_REF="$(sched model)"
parse_model_ref "$MODEL_REF"
[[ -f "$AQD_SEALED/preflight.ok" ]] || { log "preflight has not passed"; exit 2; }
[[ ! -f "$AQD_SEALED/STOP" ]] || { log "benchmark stopped: $(cat "$AQD_SEALED/STOP")"; exit 2; }
ACTIVATION_MODE="cc-skill-available"
if [[ -f "$AQD_SEALED/activation-mode" ]]; then
    [[ "$(cat "$AQD_SEALED/activation-mode")" == "$ACTIVATION_MODE" ]] \
        || { log "activation mode differs from the one used by earlier runs"; exit 2; }
else
    printf '%s' "$ACTIVATION_MODE" >"$AQD_SEALED/activation-mode"
fi

AGENT_USER="${AQD_USER_FOR_ENV[$ENV_LABEL]}"
OTHER_ENV="env-a"; [[ "$ENV_LABEL" == "env-a" ]] && OTHER_ENV="env-b"
CAP="$AQD_CAPTURES/$RUN_ID"
RUN_ROOT="$AQD_ROOT/$ENV_LABEL/runs/$RUN_ID"
PROJECT="$RUN_ROOT/project"
RUN_HOME="$RUN_ROOT/home"
RUN_TMP="$RUN_ROOT/tmp"
CONFIG="$RUN_HOME/.claude"
SETTINGS="$RUN_ROOT/cc-settings.json"
WRAPPER="$RUN_ROOT/bin/cc_exec.sh"
PRISTINE="$AQD_PRISTINE/$TASK"
MANIFEST="$PRISTINE/manifest.json"
MESSAGE_FILE="$PRISTINE/project/TASK.md"
SECRET_DIR="$AQD_OPERATOR/cc-secret-$RUN_ID"   # operator-only, never under $CAP, removed in finish()

[[ ! -e "$CAP" ]] || { log "capture $CAP exists: run ids are never reused"; exit 2; }
sudo test ! -e "$RUN_ROOT" || { log "$RUN_ROOT exists"; exit 2; }
install -d -m 0700 "$CAP" "$CAP/driver"
exec > >(tee -a "$CAP/launcher.log") 2>&1

STEP="start"
API_EXIT=99
DRIVER_EXIT=99
STARTED="$(date +%s)"
ENDED="$STARTED"

finish() {
    local rc=$?
    set +e
    rm -rf "$SECRET_DIR"
    kill_user_processes "$AGENT_USER"
    if [[ ! -f "$CAP/run-status.json" ]]; then
        "$PY" "$AQD_HARNESS/run_status.py" --interface claude-code --capture "$CAP" --group "$GROUP" \
            --started "$STARTED" --ended "$(date +%s)" --api-exit "$API_EXIT" --driver-exit "$DRIVER_EXIT" \
            --step "$STEP" >/dev/null
    fi
    sudo rm -rf --one-file-system "$RUN_ROOT"
    sudo find /tmp /var/tmp /dev/shm -xdev -user "$AGENT_USER" -delete 2>/dev/null
    log "run $RUN_ID finished (exit $rc); evidence in $CAP"
    exit "$rc"
}
trap finish EXIT

log "run $RUN_ID: task $TASK, model $MODEL_REF, environment $ENV_LABEL, interface native Claude Code"

STEP="preconditions"
for env in "${AQD_ENVS[@]}"; do assert_no_processes "${AQD_USER_FOR_ENV[$env]}"; done
[[ -z "$(find "$AQD_EVALUATOR" -mindepth 1 -print -quit 2>/dev/null)" ]] \
    || die "$AQD_EVALUATOR is not empty: evaluator material must not be on the host while agents run"
"$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$MANIFEST" --tree "$PRISTINE/project" --phase pre \
    --out "$CAP/pristine-check.json" >/dev/null || die "pristine store for $TASK is not intact"
sha256sum --quiet -c "$AQD_SEALED/pristine-extra.sha256" || die "pristine skill/config changed"
command -v bwrap >/dev/null || die "bubblewrap is required (CLAUDE_CODE_SUBPROCESS_ENV_SCRUB)"
[[ "$("$AQD_CLAUDE_BIN" --version 2>/dev/null | awk '{print $1}')" == "2.1.330" ]] || die "claude is not the pinned 2.1.330"

STEP="build-home"
sudo install -d -o root -g root -m 0711 "$RUN_ROOT"
sudo install -d -o root -g root -m 0755 "$RUN_ROOT/bin"
sudo install -o root -g root -m 0555 "$AQD_HARNESS/cc_exec.sh" "$WRAPPER"
"$PY" "$CC" write-settings --out "$CAP/cc-settings.json"
sudo install -o root -g root -m 0444 "$CAP/cc-settings.json" "$SETTINGS"
sudo install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 0700 "$RUN_HOME" "$RUN_TMP" "$CONFIG"
# The skills directory is root-owned in BOTH arms, so the agent cannot add a skill during the run.
sudo install -d -o root -g root -m 0755 "$CONFIG/skills"
if [[ "$GROUP" == "treatment" ]]; then
    sudo install -d -o root -g root -m 0755 "$CONFIG/skills/$AQD_SKILL_ID"
    sudo install -o root -g root -m 0444 "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" "$CONFIG/skills/$AQD_SKILL_ID/SKILL.md"
fi

STEP="build-project"
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
if sudo -u "$AGENT_USER" test -w "$CONFIG/skills"; then die "agent can write the skills directory"; fi

STEP="agent-env"
# The environment is written from scratch: no inherited variable reaches the agent. The token is NOT in it.
cat >"$CAP/cc-env" <<EOF
HOME=$RUN_HOME
CLAUDE_CONFIG_DIR=$CONFIG
TMPDIR=$RUN_TMP
PATH=$(agent_path)
SHELL=/bin/bash
LANG=C.UTF-8
LC_ALL=C.UTF-8
TERM=dumb
PYTHONDONTWRITEBYTECODE=1
DISABLE_AUTOUPDATER=1
DISABLE_UPDATES=1
CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK=1
CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1
CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1
CLAUDE_CODE_SKIP_PROMPT_HISTORY=1
EOF
"$PY" "$CC" check-env --env-file "$CAP/cc-env" || die "run environment refused"
install -d -m 0700 "$SECRET_DIR"
( umask 077; sed -n 's/^CLAUDE_CODE_OAUTH_TOKEN=//p' "$AQD_CREDENTIALS" | head -n 1 >"$SECRET_DIR/token" )
[[ -s "$SECRET_DIR/token" ]] || die "CLAUDE_CODE_OAUTH_TOKEN is not set in $AQD_CREDENTIALS"
"$PY" - "$CAP/run-record.json" "$RUN_ID" "$TASK" "$GROUP" "$MODEL_REF" "$MESSAGE_FILE" "$MANIFEST" \
    "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" "$SETTINGS" "$AQD_CLAUDE_BIN" "$AQD_RUN_TIMEOUT_SECONDS" \
    "$AQD_CC_MAX_TURNS" <<'PY'
import datetime, hashlib, json, sys
out, run_id, task, group, model, prompt, manifest, skill, settings, claude, timeout, turns = sys.argv[1:13]
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
provider, model_id, effort = model.split("/", 1)[0], model.split("/", 1)[1].split("#")[0], model.split("#", 1)[1]
json.dump({"schema_version": 2, "run_id": run_id, "task": task, "group": group, "model": model,
           "model_provider": provider, "model_id": model_id, "model_variant": effort, "requested_effort": effort,
           "interface": "claude-code 2.1.330", "execution_environment": "native-claude-code",
           "activation_mode": "cc-skill-available", "agent": "claude-code-print", "opencode_install_tree_sha256": None,
           "timeout_seconds": int(timeout), "max_turns": int(turns),
           "skill": {"installed": group == "treatment", "sha256": sha(skill) if group == "treatment" else None},
           "prompt_sha256": sha(prompt), "workspace_sha256": json.load(open(manifest, encoding="utf-8"))["workspace_sha256"],
           "global_config_sha256": sha(settings), "claude_cli_sha256": sha(claude),
           "started_utc": datetime.datetime.now(datetime.timezone.utc).isoformat()},
          open(out, "w", encoding="utf-8"), indent=2)
PY

STEP="auth-check"
set +e
"$PY" "$CC" auth-status --claude "$AQD_CLAUDE_BIN" --env-file "$CAP/cc-env" --secret-file "$SECRET_DIR/token" \
    --out "$CAP/auth-check.json" --as-user "$AGENT_USER" --wrapper "$WRAPPER"
API_EXIT=$?
set -e
[[ "$API_EXIT" == 0 ]] || { printf 'BLOCKED by run %s: subscription auth check failed\n' "$RUN_ID" >"$AQD_SEALED/STOP"; exit 20; }

STEP="session"
STARTED="$(date +%s)"
set +e
"$PY" "$CC" run --claude "$AQD_CLAUDE_BIN" --model "$MODEL_REF" --settings "$SETTINGS" \
    --max-turns "$AQD_CC_MAX_TURNS" --prompt-file "$MESSAGE_FILE" --env-file "$CAP/cc-env" \
    --secret-file "$SECRET_DIR/token" --timeout "$AQD_RUN_TIMEOUT_SECONDS" --out-dir "$CAP/driver" \
    --as-user "$AGENT_USER" --wrapper "$WRAPPER"
DRIVER_EXIT=$?
set -e
ENDED="$(date +%s)"

STEP="stop"
kill_user_processes "$AGENT_USER"
assert_no_processes "$AGENT_USER"

STEP="capture"
install -d -m 0700 "$CAP/project-final"
sudo tar -C "$PROJECT" -cf - . | tar -C "$CAP/project-final" -xf - --no-same-owner --no-same-permissions
sudo find "$CONFIG/skills" -mindepth 1 -printf '%P\n' | sort >"$CAP/home-config-listing.txt"
chmod -R u+rwX "$CAP"

STEP="verify-post"
set +e
"$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$MANIFEST" --tree "$CAP/project-final" --phase post \
    --out "$CAP/verify-post.json"
diff -ruN -x __pycache__ -x '*.pyc' -x .pytest_cache "$PRISTINE/project" "$CAP/project-final" >"$CAP/diff.patch"
[[ $? -le 1 ]] || log "diff reported an error"
"$PY" "$CC" check-transcript --transcript "$CAP/driver/transcript.ndjson" --group "$GROUP" --model "$MODEL_REF" \
    --out "$CAP/export-checks.json"
LEAKS="$("$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import cc_adapter as cc
print(len(cc.files_containing([sys.argv[2]], open(sys.argv[3]).read().strip())))' "$AQD_HARNESS" "$CAP" "$SECRET_DIR/token")"
set -e
if [[ "$LEAKS" != "0" ]]; then
    printf 'ISOLATION FAILURE in run %s: the subscription token appears in captured files\n' "$RUN_ID" >"$AQD_SEALED/STOP"
    exit 21
fi

STEP="done"
set +e
"$PY" "$AQD_HARNESS/run_status.py" --interface claude-code --capture "$CAP" --group "$GROUP" --started "$STARTED" \
    --ended "$ENDED" --api-exit "$API_EXIT" --driver-exit "$DRIVER_EXIT" --step "$STEP"
RESULT=$?
set -e
exit "$RESULT"
