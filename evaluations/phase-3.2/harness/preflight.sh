#!/usr/bin/env bash
# Phase 3.2 preflight. Run as the operator after setup-host.sh,
# install-opencode.sh and schedule.py create. Sends NO model request: for each
# scheduled model, a private OpenCode server holding only that provider's key
# is asked which providers, models and variants it offers.
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
[[ "${CODESPACES:-}" == "true" ]] || log "note: not a GitHub Codespace; use a disposable host that holds nothing but this checkout"
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
VERSION="$(opencode_version)"
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

# 5. Only on a GitHub Codespace: billing and quota confirmation, filled in by
#    the user from https://github.com/settings/billing.
BILLING="$AQD_SEALED/billing-confirmation.json"
if [[ "${CODESPACES:-}" == "true" ]]; then
[[ -f "$BILLING" ]] || die "missing $BILLING (see SPECIFICATION.md, execution host)"
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
else
gate billing "not a Codespace; host cost is the user's responsibility"
fi

# 6. Catalog probe for every model in the sealed schedule, with only that
#    provider's key (no model request is sent).
SCHEDULE="$AQD_SEALED/schedule.json"
[[ -f "$SCHEDULE" ]] || die "create the sealed schedule first (schedule.py create --models ...)"
[[ -f "$AQD_CREDENTIALS" ]] || die "credentials file $AQD_CREDENTIALS missing"
[[ "$(stat -c %a "$AQD_CREDENTIALS")" == "600" ]] || die "$AQD_CREDENTIALS must be mode 0600"
PROBE_USER="${AQD_USER_FOR_ENV[env-a]}"
cleanup_probe() { kill "${SERVE_PID:-0}" 2>/dev/null || true; kill_user_processes "$PROBE_USER"; sudo rm -rf "${PROBE:-/nonexistent}"; }
trap cleanup_probe EXIT
PROBE_CODE=0
while IFS= read -r MODEL_REF; do
    parse_model_ref "$MODEL_REF"
    PROBE="$AQD_ROOT/env-a/preflight-$(date -u +%s)-$RANDOM"
    sudo install -d -o "$PROBE_USER" -g "$PROBE_USER" -m 0700 "$PROBE" "$PROBE/home" "$PROBE/project" "$PROBE/tmp"
    PORT="$(free_port)"; PW="$(random_secret)"
    make_agent_env "$PROBE" "$PW"
    add_provider_credential "$MODEL_PROVIDER"
    assert_clean_ancestors "$PROBE/project"
    as_agent "$PROBE_USER" "$PROBE/project" "$AQD_OPENCODE_BIN" serve --hostname 127.0.0.1 --port "$PORT" \
        >"$AQD_SEALED/preflight-serve-$MODEL_PROVIDER.log" 2>&1 &
    SERVE_PID=$!
    for _ in $(seq 1 60); do
        curl -fsS -u "opencode:$PW" "http://127.0.0.1:$PORT/api/info" >/dev/null 2>&1 && break
        sleep 1
    done
    set +e
    OPENCODE_PASSWORD="$PW" "$(python_bin)" "$AQD_HARNESS/api_checks.py" --server "http://127.0.0.1:$PORT" \
        --directory "$PROBE/project" --group control --model "$MODEL_REF" --allowed-root "$PROBE" \
        --allowed-root "$AQD_OPENCODE_PREFIX" --out "$AQD_SEALED/preflight-catalog-$MODEL_PROVIDER.json"
    CODE=$?
    set -e
    case "$CODE" in
        0)  gate "catalog:$MODEL_REF" "available" ;;
        10) gate "catalog:$MODEL_REF" "BLOCKED: provider absent (key missing or rejected)" ;;
        11) gate "catalog:$MODEL_REF" "BLOCKED: model absent or disabled" ;;
        12) gate "catalog:$MODEL_REF" "BLOCKED: variant not offered" ;;
        *)  gate "catalog:$MODEL_REF" "FAILED (exit $CODE)" ;;
    esac
    [[ "$CODE" == 0 ]] || PROBE_CODE="$CODE"
    cleanup_probe
done < <("$(python_bin)" -c 'import json, sys; [print(m) for m in json.load(open(sys.argv[1]))["design"]["models"]]' "$SCHEDULE")

"$(python_bin)" - "$REPORT" "$PROBE_CODE" "${GATES[@]}" <<'PY'
import datetime, json, sys
path, code, gates = sys.argv[1], int(sys.argv[2]), sys.argv[3:]
json.dump({"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
           "catalog_exit": code, "gates": dict(g.split("=", 1) for g in gates)},
          open(path, "w", encoding="utf-8"), indent=2)
PY

if [[ "$PROBE_CODE" == "0" ]]; then
    cp "$REPORT" "$AQD_SEALED/preflight.ok"
    log "PREFLIGHT PASSED. No model request was sent; key validity and skill activation are shown by the first authorised runs."
    exit 0
elif [[ "$PROBE_CODE" =~ ^1[012]$ ]]; then
    log "PREFLIGHT BLOCKED: a user decision is required. Do not add credentials or change the model without approval."
    exit 20
fi
die "preflight failed"
