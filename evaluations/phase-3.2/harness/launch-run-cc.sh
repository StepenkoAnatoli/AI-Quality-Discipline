#!/usr/bin/env bash
# Execute ONE scheduled run with NATIVE CLAUDE CODE (Phase 3.3 feasibility; execution environment
# "native-claude-code"). The OpenCode launcher, launch-run.sh, is unchanged and remains the Phase 3.2 reference.
#
# Usage: launch-run-cc.sh RUN_ID
#
# NOT YET EXECUTED ANYWHERE: only static checks (bash -n, shellcheck when present) and the offline adapter tests
# have run. Running it sends a model request on the owner's subscription; it refuses unless the owner named THIS
# run id in writing ($AQD_SEALED/cc-run-approved.json, {"approved_run_ids": [...]}) and preflight has passed.
#
# Reused unchanged from launch-run.sh / lib.sh: sealed schedule lookup, preflight and STOP gates, the
# evaluator-must-be-empty rule, per-group OS users, root-owned immutable project tree from the manifest,
# pre/post manifest verification, diff capture, process kill and run-root removal, run_status.py.
# Replaced: OpenCode HOME, server, api_checks, session driver and export -> cc_adapter.py (auth-status, run,
# check-transcript) and cc_exec.sh. The arms differ ONLY in the content of the run's arm plugin ($RUN_ROOT/arm-plugin,
# passed with --plugin-dir in both arms; treatment's holds the canonical SKILL.md, root-owned read-only; the real
# 2.1.330 CLI ignores CLAUDE_CONFIG_DIR/skills under --restricted); prompt, command, settings and environment are
# byte-identical.
#
# Exit codes: 0 valid run, 1 invalid run, 20 BLOCKED (auth/billing check failed: the benchmark stops),
# 21 isolation failure (the benchmark stops), 22 infrastructure stop (the Bash sandbox could not start; the benchmark
# stops), 2 usage/precondition error.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY="$(python_bin)"
SCHEDULE="$AQD_SEALED/schedule.json"
CC="$AQD_HARNESS/cc_adapter.py"
: "${AQD_CLAUDE_BIN:?AQD_CLAUDE_BIN (the pinned claude binary, executable by the agent users) is required}"
AQD_CC_MAX_TURNS="${AQD_CC_MAX_TURNS:-200}"
# Pre-registered: 2700 s (lib.sh). Overridable ONLY for no-model dry runs; it is bound by the native preflight and
# recorded per run, and analyze.py refuses runs whose timeouts differ.
AQD_CC_RUN_TIMEOUT_SECONDS="${AQD_CC_RUN_TIMEOUT_SECONDS:-$AQD_RUN_TIMEOUT_SECONDS}"

RUN_ID="${1:-}"
[[ "$RUN_ID" =~ ^r-[0-9a-f]{10}$ ]] || { echo "usage: launch-run-cc.sh RUN_ID (r-<10 hex>)" >&2; exit 2; }
"$PY" "$CC" check-approval --approval "$AQD_SEALED/cc-run-approved.json" --run-id "$RUN_ID" \
    || { log "run $RUN_ID is not approved in writing in $AQD_SEALED/cc-run-approved.json"; exit 2; }
sched() { "$PY" "$AQD_HARNESS/schedule.py" get --schedule "$SCHEDULE" --run-id "$RUN_ID" --key "$1"; }
TASK="$(sched task)"
GROUP="$(sched group)"
ENV_LABEL="$(sched env)"
MODEL_REF="$(sched model)"
parse_model_ref "$MODEL_REF"
# The NATIVE preflight record (preflight-cc.sh), recomputed now: any change since it ran, or age, refuses the run.
# The OpenCode preflight.ok is never accepted here.
"$PY" "$CC" check-preflight --preflight "$AQD_SEALED/preflight-cc.json" --checkout "$AQD_CHECKOUT" \
    --claude "$AQD_CLAUDE_BIN" --sealed "$AQD_SEALED" --pristine "$AQD_PRISTINE" --max-turns "$AQD_CC_MAX_TURNS" \
    --timeout "$AQD_CC_RUN_TIMEOUT_SECONDS" --max-age-hours "${AQD_CC_PREFLIGHT_MAX_AGE_HOURS:-24}" \
    || { log "native preflight missing, failed, stale or out of date: run preflight-cc.sh"; exit 2; }
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
ARM_PLUGIN="$RUN_ROOT/arm-plugin"
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
    kill_user_processes "$AGENT_USER"
    # The token scan runs on EVERY exit path, before the secret copy is removed. A hit (or a scan that cannot run)
    # stops the benchmark and makes this run invalid, whatever happened before.
    if [[ -s "$SECRET_DIR/token" ]] && ! "$PY" "$CC" scan-secret --secret-file "$SECRET_DIR/token" --root "$CAP" >/dev/null; then
        printf 'ISOLATION FAILURE in run %s: the subscription token appears in captured files\n' "$RUN_ID" >"$AQD_SEALED/STOP"
        rm -f "$CAP/run-status.json"
        STEP="token-leak"
        rc=21
    fi
    rm -rf "$SECRET_DIR"
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
command -v socat >/dev/null || die "socat is required (the CLI's subprocess sandbox needs it)"
# --restricted still applies managed settings, whose env/apiKeyHelper could redirect or bill the session.
[[ ! -e /etc/claude-code ]] || die "/etc/claude-code (managed settings) exists: refused"
[[ "$("$AQD_CLAUDE_BIN" --version 2>/dev/null | awk '{print $1}')" == "2.1.330" ]] || die "claude is not the pinned 2.1.330"

STEP="build-home"
sudo install -d -o root -g root -m 0711 "$RUN_ROOT"
sudo install -d -o root -g root -m 0755 "$RUN_ROOT/bin"
sudo install -o root -g root -m 0555 "$AQD_HARNESS/cc_exec.sh" "$WRAPPER"
"$PY" "$CC" write-settings --out "$CAP/cc-settings.json"
sudo install -o root -g root -m 0444 "$CAP/cc-settings.json" "$SETTINGS"
sudo install -d -o "$AGENT_USER" -g "$AGENT_USER" -m 0700 "$RUN_HOME" "$RUN_TMP"
# CONFIG is root-owned and sticky: claude can create its files there, but the agent cannot rename or replace the
# root-owned skills directory. That directory is root-owned in BOTH arms, so no skill can be added during the run.
sudo install -d -o root -g "$AGENT_USER" -m 1770 "$CONFIG"
sudo install -d -o root -g root -m 0755 "$CONFIG/skills"
# The skill is delivered as a plugin (--plugin-dir, same path in both arms), root-owned and read-only.
sudo install -d -o root -g root -m 0755 "$ARM_PLUGIN" "$ARM_PLUGIN/.claude-plugin" "$ARM_PLUGIN/skills"
printf '{"name": "aqd-arm", "version": "1.0.0"}\n' >"$CAP/arm-plugin.json"
sudo install -o root -g root -m 0444 "$CAP/arm-plugin.json" "$ARM_PLUGIN/.claude-plugin/plugin.json"
if [[ "$GROUP" == "treatment" ]]; then
    sudo install -d -o root -g root -m 0755 "$ARM_PLUGIN/skills/$AQD_SKILL_ID"
    sudo install -o root -g root -m 0444 "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" "$ARM_PLUGIN/skills/$AQD_SKILL_ID/SKILL.md"
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
if sudo -u "$AGENT_USER" test -w "$ARM_PLUGIN/skills"; then die "agent can write the arm plugin"; fi
[[ "$(sudo stat -c '%U %a' "$CONFIG")" == "root 1770" ]] || die "$CONFIG is not root-owned and sticky"

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
    "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" "$CAP/cc-settings.json" "$AQD_CLAUDE_BIN" "$AQD_CC_RUN_TIMEOUT_SECONDS" \
    "$AQD_CC_MAX_TURNS" "$AQD_SEALED/preflight-cc.json" <<'PY'
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
           "preflight_sha256": sha(sys.argv[13]),
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
    --secret-file "$SECRET_DIR/token" --timeout "$AQD_CC_RUN_TIMEOUT_SECONDS" --out-dir "$CAP/driver" \
    --project "$PROJECT" --plugin-dir "$ARM_PLUGIN" --as-user "$AGENT_USER" --wrapper "$WRAPPER"
DRIVER_EXIT=$?
set -e
ENDED="$(date +%s)"

STEP="stop"
kill_user_processes "$AGENT_USER"
assert_no_processes "$AGENT_USER"

STEP="capture"
install -d -m 0700 "$CAP/project-final"
sudo tar -C "$PROJECT" -cf - . | tar -C "$CAP/project-final" -xf - --no-same-owner --no-same-permissions
# The skill-delivery listing: the arm plugin, plus the (unused, root-owned) CLAUDE_CONFIG_DIR/skills, which must stay
# empty in both arms.
{ sudo find "$ARM_PLUGIN" -mindepth 1 -printf 'arm-plugin/%P\n'; sudo find "$CONFIG/skills" -mindepth 1 -printf 'config-skills/%P\n'; } \
    | sort >"$CAP/home-config-listing.txt"
chmod -R u+rwX "$CAP"

STEP="verify-post"
set +e
"$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$MANIFEST" --tree "$CAP/project-final" --phase post \
    --out "$CAP/verify-post.json"
diff -ruN -x __pycache__ -x '*.pyc' -x .pytest_cache "$PRISTINE/project" "$CAP/project-final" >"$CAP/diff.patch"
[[ $? -le 1 ]] || log "diff reported an error"
"$PY" "$CC" check-transcript --transcript "$CAP/driver/transcript.ndjson" --group "$GROUP" --model "$MODEL_REF" \
    --project "$PROJECT" --plugin-dir "$ARM_PLUGIN" --driver-result "$CAP/driver/driver-result.json" \
    --out "$CAP/export-checks.json"
set -e
# (the token scan runs in finish(), on every exit path)

STEP="done"
set +e
"$PY" "$AQD_HARNESS/run_status.py" --interface claude-code --capture "$CAP" --group "$GROUP" --started "$STARTED" \
    --ended "$ENDED" --api-exit "$API_EXIT" --driver-exit "$DRIVER_EXIT" --step "$STEP"
RESULT=$?
SANDBOX_FAILURES="$("$PY" -c 'import json, sys; print(int(json.load(open(sys.argv[1])).get("sandbox_failures") or 0))' \
    "$CAP/export-checks.json" 2>/dev/null || echo 0)"
set -e
# A Bash sandbox that cannot start is a HOST failure: it would invalidate only the runs whose agent called Bash, an
# exclusion that depends on agent behaviour (and so on the arm). Stop the whole batch instead.
if [[ "$SANDBOX_FAILURES" != "0" ]]; then
    printf 'INFRASTRUCTURE STOP in run %s: the Bash sandbox could not start\n' "$RUN_ID" >"$AQD_SEALED/STOP"
    exit 22
fi
exit "$RESULT"
