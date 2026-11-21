#!/usr/bin/env bash
# Phase 3.2 preflight. Run as the Codespace operator after setup-host.sh and
# install-opencode.sh. Sends NO model request: the catalog probe only asks a
# private, credential-free OpenCode server which providers, models and
# variants it offers.
#
# Usage: preflight.sh
# Writes $AQD_SEALED/preflight.json and, only when every gate passes,
# $AQD_SEALED/preflight.ok. Exit 0 = ready, 1 = failed, 20 = BLOCKED (needs a
# user decision: authentication, model or variant unavailable).

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

REPORT="$AQD_SEALED/preflight.json"
GATES=()
gate() { GATES+=("$1=$2"); log "gate $1: $2"; }

require_cmd sudo python3 curl tar diff pgrep pkill sha256sum git
sudo -n true 2>/dev/null || die "passwordless sudo is required for the operator"
[[ "${CODESPACES:-}" == "true" ]] || log "WARNING: CODESPACES is not 'true'; the protocol assumes a GitHub Codespace"
[[ -d "$AQD_SEALED" && -d "$AQD_PRISTINE" ]] || die "run setup-host.sh first"
rm -f "$AQD_SEALED/preflight.ok"

# 1. Python version (fixtures need >= 3.10) and checkout state.
"$(python_bin)" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "python3 >= 3.10 required"
gate python "$("$(python_bin)" -c 'import platform; print(platform.python_version())')"
COMMIT="$(git -C "$AQD_CHECKOUT" rev-parse HEAD)"
BRANCH="$(git -C "$AQD_CHECKOUT" rev-parse --abbrev-ref HEAD)"
[[ "$BRANCH" == "phase-3/benchmark-foundation" ]] || die "checkout is on $BRANCH, expected phase-3/benchmark-foundation"
[[ -z "$(git -C "$AQD_CHECKOUT" status --porcelain)" ]] || die "checkout has uncommitted changes; fixtures must match a commit"
gate commit "$COMMIT"

# 2. Pinned OpenCode and the CLI surface the harness relies on.
[[ -x "$AQD_OPENCODE_BIN" ]] || die "OpenCode not installed at $AQD_OPENCODE_BIN; run install-opencode.sh"
VERSION="$("$AQD_OPENCODE_BIN" --version 2>/dev/null | tr -d '[:space:]')"
[[ "$VERSION" == "$AQD_OPENCODE_VERSION" ]] || die "OpenCode $VERSION found, $AQD_OPENCODE_VERSION pinned"
gate opencode_version "$VERSION"
SERVE_HELP="$("$AQD_OPENCODE_BIN" serve --help 2>&1 || true)"
for flag in --port --hostname; do
    grep -q -- "$flag" <<<"$SERVE_HELP" || die "'opencode serve' lacks $flag"
done
if [[ -f "$AQD_SEALED/opencode-install.json" ]]; then
    TREE_NOW="$("$(python_bin)" - "$AQD_OPENCODE_PREFIX" <<'PY'
import hashlib, json, os, sys
prefix = sys.argv[1]
files = {}
for root, _, names in os.walk(prefix):
    for name in names:
        path = os.path.join(root, name)
        if os.path.isfile(path) and not os.path.islink(path):
            with open(path, "rb") as h:
                files[os.path.relpath(path, prefix)] = hashlib.sha256(h.read()).hexdigest()
print(hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest())
PY
)"
    TREE_THEN="$(json_get "$AQD_SEALED/opencode-install.json" tree_sha256)"
    if [[ "$TREE_NOW" == "$TREE_THEN" ]]; then gate opencode_tree identical; else gate opencode_tree "DIFFERS from first install (review before continuing)"; fi
fi
"$AQD_OPENCODE_BIN" session export --help >/dev/null 2>&1 || die "'opencode session export' is not available"
"$AQD_OPENCODE_BIN" debug paths --help >/dev/null 2>&1 || die "'opencode debug paths' is not available"
if [[ "$AQD_ACTIVATION_MODE" == "cli-mention" ]]; then
    RUN_HELP="$("$AQD_OPENCODE_BIN" run --help 2>&1 || true)"
    for flag in --server --model --format --auto --agent; do
        grep -q -- "$flag" <<<"$RUN_HELP" || die "'opencode run' lacks $flag (required by cli-mention mode)"
    done
fi
gate cli_surface ok

# 3. No system-wide configuration; agent users exist, have no sudo, and can
#    run the pinned tools but cannot read operator material.
for name in /etc/opencode; do
    [[ ! -e "$name" ]] || die "$name exists; it would configure every user"
done
for env in "${AQD_ENVS[@]}" ; do
    user="${AQD_USER_FOR_ENV[$env]}"
    id "$user" >/dev/null 2>&1 || die "user $user missing; run setup-host.sh"
    if id -nG "$user" | tr ' ' '\n' | grep -qxE 'sudo|admin|wheel|root|docker'; then
        die "$user is in a privileged group"
    fi
    if sudo -l -U "$user" 2>/dev/null | grep -q '(ALL'; then
        die "$user has sudo rights"
    fi
    sudo -u "$user" env -i PATH="$(agent_path)" HOME=/nonexistent "$AQD_OPENCODE_BIN" --version >/dev/null \
        || die "$user cannot execute $AQD_OPENCODE_BIN with the agent PATH"
    sudo -u "$user" env -i PATH="$(agent_path)" python3 -c 'import sqlite3, csv, multiprocessing' \
        || die "$user cannot run python3 with sqlite3/csv/multiprocessing"
    assert_unreadable_by "$user" "$AQD_OPERATOR" "$AQD_CHECKOUT" "$HOME" /workspaces/.codespaces
    other="env-a"; [[ "$env" == "env-a" ]] && other="env-b"
    assert_unreadable_by "$user" "$AQD_ROOT/$other"
done
gate isolation_users ok

# 4. Pristine store matches the committed allowlist.
for task in SMOKE NEW-01 NEW-02 NEW-03; do
    "$(python_bin)" "$AQD_HARNESS/manifest.py" verify --manifest "$AQD_PRISTINE/$task/manifest.json" \
        --tree "$AQD_PRISTINE/$task/project" --phase pre --out "$AQD_SEALED/pristine-$task.json" >/dev/null \
        || die "pristine store for $task does not match its manifest"
done
SKILL_SHA="$(sha256sum "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" | cut -d' ' -f1)"
CANON_SHA="$(sha256sum "$AQD_CHECKOUT/skills/$AQD_SKILL_ID/SKILL.md" | cut -d' ' -f1)"
[[ "$SKILL_SHA" == "$CANON_SHA" ]] || die "pristine skill differs from the committed canonical skill"
gate pristine ok

# 5. Billing and quota confirmation, filled in by the user from
#    https://github.com/settings/billing (cannot be read from inside a Codespace).
BILLING="$AQD_SEALED/billing-confirmation.json"
[[ -f "$BILLING" ]] || die "missing $BILLING (see SPECIFICATION.md §15 preflight checklist)"
"$(python_bin)" - "$BILLING" <<'PY' || die "billing confirmation incomplete or unsafe"
import json, sys
b = json.load(open(sys.argv[1], encoding="utf-8"))
need = ["checked_utc", "checked_by", "plan", "compute_core_hours_remaining", "storage_gb_month_remaining",
        "payment_method_on_file", "machine_type", "idle_timeout_minutes"]
missing = [k for k in need if b.get(k) in (None, "")]
if missing:
    sys.exit(f"missing fields: {missing}")
if b["payment_method_on_file"] and not b.get("paid_usage_approved_by_user"):
    sys.exit("a payment method is on file: usage beyond the quota would be billed; explicit user approval required")
if b["machine_type"] != "basicLinux32gb":
    print("note: machine type differs from the planned 2-core machine; recompute the budget", file=sys.stderr)
if float(b["compute_core_hours_remaining"]) < 40:
    sys.exit("fewer than 40 core-hours remain; the plan needs up to about 36 on a 2-core machine")
PY
gate billing confirmed

# 6. Catalog probe with a credential-free, signed-out HOME (no model request).
PROBE="$AQD_ROOT/env-a/preflight-$(date -u +%s)"
PROBE_USER="${AQD_USER_FOR_ENV[env-a]}"
sudo install -d -o "$PROBE_USER" -g "$PROBE_USER" -m 0700 "$PROBE" "$PROBE/home" "$PROBE/project" "$PROBE/tmp"
PORT="$(free_port)"; PW="$(random_secret)"
cleanup_probe() { kill "${SERVE_PID:-0}" 2>/dev/null || true; kill_user_processes "$PROBE_USER"; sudo rm -rf "$PROBE"; }
trap cleanup_probe EXIT
make_agent_env "$PROBE" "$PW"
assert_clean_ancestors "$PROBE/project"
as_agent "$PROBE_USER" "$PROBE/project" "$AQD_OPENCODE_BIN" serve --hostname 127.0.0.1 --port "$PORT" \
    >"$AQD_SEALED/preflight-serve.log" 2>&1 &
SERVE_PID=$!
for _ in $(seq 1 60); do
    curl -fsS -u "opencode:$PW" "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1 && break
    sleep 1
done
set +e
OPENCODE_PASSWORD="$PW" "$(python_bin)" "$AQD_HARNESS/api_checks.py" --server "http://127.0.0.1:$PORT" \
    --directory "$PROBE/project" --group control --allowed-root "$PROBE" --allowed-root "$AQD_OPENCODE_PREFIX" \
    --out "$AQD_SEALED/preflight-catalog.json"
PROBE_CODE=$?
set -e
case "$PROBE_CODE" in
    0)  gate catalog "provider, model and variant available signed out" ;;
    10) gate catalog "BLOCKED: provider '$AQD_PROVIDER' absent without credentials" ;;
    11) gate catalog "BLOCKED: model $AQD_MODEL absent or disabled" ;;
    12) gate catalog "BLOCKED: variant $AQD_VARIANT not offered" ;;
    *)  gate catalog "FAILED (exit $PROBE_CODE)" ;;
esac

"$(python_bin)" - "$REPORT" "$PROBE_CODE" "${GATES[@]}" <<'PY'
import datetime, json, sys
path, code, gates = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
json.dump({"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "catalog_exit": code, "gates": dict(g.split("=", 1) for g in gates)},
          open(path, "w", encoding="utf-8"), indent=2)
PY

if [[ "$PROBE_CODE" == "0" ]]; then
    cp "$REPORT" "$AQD_SEALED/preflight.ok"
    log "PREFLIGHT PASSED. Runtime gates R1-R6 (SPECIFICATION.md §18) still require the authorised smoke run."
    exit 0
elif [[ "$PROBE_CODE" =~ ^1[012]$ ]]; then
    log "PREFLIGHT BLOCKED: a user decision is required. Do not add credentials or change the model without approval."
    exit 20
fi
die "preflight failed"
