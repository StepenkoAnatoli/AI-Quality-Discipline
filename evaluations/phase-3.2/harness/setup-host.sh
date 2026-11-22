#!/usr/bin/env bash
# One-time setup of the disposable benchmark host. Run as the operator.
# Creates OS users, the root-owned /aqd tree, the operator-only store and the
# sealed schedule. Copies ONLY allowlisted files (allowlist.json) from the
# checkout; nothing else of the repository ever reaches an agent directory.
# Does not install software and does not contact any model endpoint.
#
# Usage: setup-host.sh
# Re-running is safe: existing users, directories and the schedule are kept
# and verified, never overwritten.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_cmd sudo python3 useradd sha256sum git
sudo -n true 2>/dev/null || die "passwordless sudo is required for the operator"

# Operator-only store on the persisted volume.
sudo install -d -o "$(id -u)" -g "$(id -g)" -m 0700 "$AQD_OPERATOR"
install -d -m 0700 "$AQD_PRISTINE" "$AQD_SEALED" "$AQD_CAPTURES" "$AQD_EVALUATOR"

# Record and tighten permissions the agent users must not get through.
RESTORE="$AQD_SEALED/restore-modes.txt"
if [[ ! -f "$RESTORE" ]]; then
    for path in "$HOME" "$AQD_CHECKOUT"; do
        printf '%s\0%s\0' "$(stat -c '%a' "$path")" "$path" >>"$RESTORE"
    done
fi
chmod 0700 "$HOME"
chmod go-rwx "$AQD_CHECKOUT"

# OS users: no password, no sudo, no login shell, no supplementary groups.
for user in "${AQD_USER_FOR_ENV[@]}" "$AQD_EVAL_USER"; do
    if ! id "$user" >/dev/null 2>&1; then
        sudo useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin --user-group "$user"
    fi
    sudo passwd -l "$user" >/dev/null 2>&1 || true
done

# Deny agent users any access to /workspaces where ACLs are available.
if command -v setfacl >/dev/null 2>&1 && [[ -d /workspaces ]]; then
    for user in "${AQD_USER_FOR_ENV[@]}" "$AQD_EVAL_USER"; do
        sudo setfacl -m "u:$user:---" /workspaces || log "WARNING: setfacl on /workspaces failed for $user"
    done
else
    log "setfacl not available: relying on directory modes; preflight.sh verifies access"
fi

# Agent tree: /aqd root-owned; one private directory per environment.
sudo install -d -o root -g root -m 0755 "$AQD_ROOT"
for env in "${AQD_ENVS[@]}"; do
    user="${AQD_USER_FOR_ENV[$env]}"
    sudo install -d -o "$user" -g "$user" -m 0700 "$AQD_ROOT/$env"
    sudo install -d -o root -g root -m 0711 "$AQD_ROOT/$env/runs"
done
# runs/ is root-owned (0711): agents cannot list it or create siblings of their
# own run root, so one run cannot see the names of other runs.
assert_clean_ancestors "$AQD_ROOT/env-a/runs/x/project"

# Pristine store, built only from the allowlist, with JSON manifests.
COMMIT="$(git -C "$AQD_CHECKOUT" rev-parse HEAD)"
for task in SMOKE NEW-01 NEW-02 NEW-03 NEW-04; do
    dest="$AQD_PRISTINE/$task"
    if [[ -f "$dest/manifest.json" ]]; then
        "$(python_bin)" "$AQD_HARNESS/manifest.py" verify --manifest "$dest/manifest.json" --tree "$dest/project" \
            --phase pre --out "$AQD_SEALED/pristine-$task.json" >/dev/null || die "existing pristine store for $task is not intact"
        continue
    fi
    install -d -m 0700 "$dest"
    "$(python_bin)" "$AQD_HARNESS/manifest.py" build --phase-root "$AQD_PHASE_ROOT" --task "$task" \
        --source-commit "$COMMIT" --out "$dest/manifest.json"
    "$(python_bin)" "$AQD_HARNESS/manifest.py" materialize --phase-root "$AQD_PHASE_ROOT" \
        --manifest "$dest/manifest.json" --dest "$dest/project"
done
install -d -m 0700 "$AQD_PRISTINE/skill/$AQD_SKILL_ID" "$AQD_PRISTINE/config"
cp "$AQD_CHECKOUT/skills/$AQD_SKILL_ID/SKILL.md" "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md"
cp "$AQD_PHASE_ROOT/config/global-opencode.jsonc" "$AQD_PRISTINE/config/global-opencode.jsonc"
sha256sum "$AQD_PRISTINE/skill/$AQD_SKILL_ID/SKILL.md" "$AQD_PRISTINE/config/global-opencode.jsonc" \
    >"$AQD_SEALED/pristine-extra.sha256"

log "setup complete. Next: install-opencode.sh, then create the sealed schedule with the exact model IDs:"
log "  python3 $AQD_HARNESS/schedule.py create --out $AQD_SEALED/schedule.json --models anthropic/<id>,xai/<id> ..."
log "then write $AQD_CREDENTIALS (mode 0600) and run preflight.sh (see PROMPT-SMOKE-TEST.md)"
