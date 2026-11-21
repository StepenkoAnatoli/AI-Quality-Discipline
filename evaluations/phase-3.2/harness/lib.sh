# shellcheck shell=bash
# Shared settings and helpers for the Phase 3.2 harness. Source this file; do
# not execute it. Every value here is part of the pre-registered protocol.
#
# Assumptions (verified by preflight.sh before any run):
#   * A disposable Linux host (a VM or a GitHub Codespace), operator user with
#     passwordless sudo, bash >= 4, python3 >= 3.10, curl, tar, diff; Docker
#     for scoring (score-all.sh).
#   * The repository is checked out at the branch under test; this file lives
#     in <checkout>/evaluations/phase-3.2/harness/.

set -euo pipefail
umask 077

AQD_HARNESS="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AQD_PHASE_ROOT="$(cd "$AQD_HARNESS/.." && pwd)"
AQD_CHECKOUT="$(cd "$AQD_PHASE_ROOT/../.." && pwd)"

# Operator-only state lives on the persisted /workspaces volume, mode 0700.
AQD_OPERATOR="${AQD_OPERATOR:-/workspaces/.aqd-operator}"
AQD_PRISTINE="$AQD_OPERATOR/pristine"
AQD_SEALED="$AQD_OPERATOR/sealed"
AQD_CAPTURES="$AQD_OPERATOR/captures"
AQD_EVALUATOR="$AQD_OPERATOR/evaluator"   # hidden tests, uploaded only for scoring

# Agent-side tree. /aqd is root-owned; each environment is owned by its OS user.
AQD_ROOT="/aqd"
AQD_ENVS=(env-a env-b)
declare -A AQD_USER_FOR_ENV=([env-a]=aqd-a [env-b]=aqd-b)
AQD_EVAL_USER="aqd-eval"

# Pinned agent software (OpenCode V2 CLI package on npm).
AQD_OPENCODE_PACKAGE="@opencode/cli"
AQD_OPENCODE_VERSION="2.3.2"
AQD_OPENCODE_PREFIX="/opt/aqd-opencode"
AQD_OPENCODE_BIN="$AQD_OPENCODE_PREFIX/bin/opencode"

# The model is NOT a constant: each scheduled run names it as
# provider/model[#variant] (schedule.py; providers anthropic and xai only).
# API keys live only in this operator file, one KEY=value per line:
#   ANTHROPIC_API_KEY=...   XAI_API_KEY=...
# Only the key of the run's provider is passed to that run. The agent's shell
# can read it (it runs as the same user as the OpenCode server): use dedicated,
# spend-capped keys and revoke them after the pilot.
AQD_CREDENTIALS="${AQD_CREDENTIALS:-$AQD_SEALED/credentials.env}"
AQD_AGENT="build"
AQD_SKILL_ID="code-discipline"
AQD_RUN_TIMEOUT_SECONDS=2700

# Activation mode, fixed for every run of a schedule (see SPECIFICATION.md section 4):
#   api-attachment  identical prompt text; treatment adds skills:[{id}] (default)
#   cli-mention     `opencode run`; treatment text is prefixed "@code-discipline"
#                   (requires explicit user approval: it changes the prompt text)
AQD_ACTIVATION_MODE="${AQD_ACTIVATION_MODE:-api-attachment}"

# Files and directories whose presence above a project would inject
# configuration, instructions or skills into OpenCode.
AQD_FORBIDDEN_ANCESTOR_NAMES=(AGENTS.md CLAUDE.md opencode.json opencode.jsonc .opencode .claude .agents)

log() { printf '[%s] %s\n' "$(date -u +%H:%M:%S)" "$*" >&2; }
die() { log "ERROR: $*"; exit 1; }

require_cmd() {
    local cmd
    for cmd in "$@"; do
        command -v "$cmd" >/dev/null 2>&1 || die "required command not found: $cmd"
    done
}

python_bin() {
    command -v python3 || die "python3 not found"
}

# Directory holding python3, which must be readable by the agent users.
python_dir() {
    dirname "$(readlink -f "$(python_bin)")"
}

# PATH given to agent processes: pinned OpenCode, its node runtime, python3,
# and system directories only. Nothing under the operator's home.
agent_path() {
    local parts=("$AQD_OPENCODE_PREFIX/bin")
    if command -v node >/dev/null 2>&1; then
        parts+=("$(dirname "$(readlink -f "$(command -v node)")")")
    fi
    parts+=("$(python_dir)" /usr/local/bin /usr/bin /bin)
    local IFS=:
    printf '%s\n' "${parts[*]}"
}

# Environment for one isolated run: every OpenCode/XDG location inside RUN_ROOT.
# Sets the global array AGENT_ENV. Usage: make_agent_env RUN_ROOT PASSWORD
make_agent_env() {
    local root="$1" password="$2"
    AGENT_ENV=(
        "HOME=$root/home"
        "XDG_CONFIG_HOME=$root/home/.config"
        "XDG_DATA_HOME=$root/home/.local/share"
        "XDG_STATE_HOME=$root/home/.local/state"
        "XDG_CACHE_HOME=$root/home/.cache"
        "OPENCODE_DB=$root/home/.local/share/opencode/opencode.db"
        "TMPDIR=$root/tmp"
        "PATH=$(agent_path)"
        "SHELL=/bin/bash"
        "LANG=C.UTF-8"
        "LC_ALL=C.UTF-8"
        "TERM=dumb"
        "PYTHONDONTWRITEBYTECODE=1"
        "OPENCODE_DISABLE_CLAUDE_CODE=1"
        "OPENCODE_PASSWORD=$password"
    )
}

# Run a command as an agent user, with only AGENT_ENV, in directory DIR.
# `cd` happens inside the agent's process because sudo's --chdir is normally
# disabled and the operator cannot enter agent directories.
# Usage: as_agent USER DIR CMD [ARGS...]
as_agent() {
    local user="$1" dir="$2"
    shift 2
    (cd / && sudo -u "$user" env -i "${AGENT_ENV[@]}" /bin/sh -c 'cd "$1" || exit 97; shift; exec "$@"' sh "$dir" "$@")
}

# Split provider/model[#variant] into MODEL_PROVIDER, MODEL_ID, MODEL_VARIANT.
parse_model_ref() {
    local ref="$1"
    [[ "$ref" =~ ^(anthropic|xai)/([A-Za-z0-9._:-]+)(#([A-Za-z0-9._-]+))?$ ]] \
        || die "model reference must be anthropic|xai/<model>[#variant], got '$ref'"
    MODEL_PROVIDER="${BASH_REMATCH[1]}"
    MODEL_ID="${BASH_REMATCH[2]}"
    MODEL_VARIANT="${BASH_REMATCH[4]:-}"
}

provider_key_var() {
    case "$1" in
        anthropic) echo ANTHROPIC_API_KEY ;;
        xai) echo XAI_API_KEY ;;
        *) die "no credential variable for provider $1" ;;
    esac
}

# Append the run's provider key (and nothing else) to AGENT_ENV. Never echoed.
add_provider_credential() {
    local var value
    var="$(provider_key_var "$1")"
    [[ -f "$AQD_CREDENTIALS" ]] || die "credentials file $AQD_CREDENTIALS missing"
    value="$(sed -n "s/^${var}=//p" "$AQD_CREDENTIALS" | head -n 1)"
    [[ -n "$value" ]] || die "$var not set in $AQD_CREDENTIALS"
    AGENT_ENV+=("$var=$value")
}

json_get() {  # json_get FILE KEY  -> prints top-level value
    "$(python_bin)" - "$1" "$2" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as h:
    value = json.load(h)[sys.argv[2]]
print(value if not isinstance(value, (dict, list)) else json.dumps(value))
PY
}

free_port() {
    "$(python_bin)" -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()'
}

random_secret() {
    "$(python_bin)" -c 'import secrets; print(secrets.token_urlsafe(32))'
}

# Fail if any process of the given user is running.
assert_no_processes() {
    local user="$1"
    if pgrep -u "$user" >/dev/null 2>&1; then
        pgrep -a -u "$user" >&2 || true
        die "processes of $user are still running"
    fi
}

kill_user_processes() {
    local user="$1"
    sudo pkill -TERM -u "$user" 2>/dev/null || true
    sleep 2
    sudo pkill -KILL -u "$user" 2>/dev/null || true
}

# The ancestors of PATH (excluding PATH itself) must not contain configuration
# or instruction files that OpenCode would discover.
assert_clean_ancestors() {
    local dir name
    dir="$(dirname "$1")"
    while :; do
        for name in "${AQD_FORBIDDEN_ANCESTOR_NAMES[@]}"; do
            if sudo test -e "$dir/$name"; then
                die "forbidden discovery file above the project: $dir/$name"
            fi
        done
        [[ "$dir" == "/" ]] && break
        dir="$(dirname "$dir")"
    done
    for name in /etc/opencode "/Library/Application Support/opencode"; do
        if [[ -e "$name" ]]; then
            die "system-wide OpenCode directory exists and would apply to every user: $name"
        fi
    done
}

# The agent user must NOT be able to read these paths.
assert_unreadable_by() {
    local user="$1"; shift
    local path
    for path in "$@"; do
        [[ -e "$path" ]] || continue
        if sudo -u "$user" test -r "$path" 2>/dev/null || sudo -u "$user" test -x "$path" 2>/dev/null; then
            die "$user can access $path"
        fi
    done
}
