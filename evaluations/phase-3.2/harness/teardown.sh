#!/usr/bin/env bash
# Remove everything the harness created inside the Codespace, except the
# operator store, which holds the evidence. Run only after the evidence has
# been downloaded and checked (see SPECIFICATION.md §16).
#
# Usage: teardown.sh --evidence-downloaded [--purge-operator-store]
# Deleting the Codespace itself is done from the user's machine with
# `gh codespace delete -c <name>`; this script never does it.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

[[ "${1:-}" == "--evidence-downloaded" ]] || die "confirm with --evidence-downloaded after copying $AQD_OPERATOR off the Codespace"
PURGE="${2:-}"

for user in "${AQD_USER_FOR_ENV[@]}" "$AQD_EVAL_USER"; do
    if id "$user" >/dev/null 2>&1; then
        kill_user_processes "$user"
        if command -v setfacl >/dev/null 2>&1; then sudo setfacl -x "u:$user" /workspaces 2>/dev/null || true; fi
        sudo userdel "$user" 2>/dev/null || log "could not delete user $user"
    fi
done
sudo rm -rf --one-file-system "$AQD_ROOT" "$AQD_OPENCODE_PREFIX"

RESTORE="$AQD_SEALED/restore-modes.txt"
if [[ -f "$RESTORE" ]]; then
    while IFS= read -r -d '' mode && IFS= read -r -d '' path; do
        [[ -e "$path" ]] && chmod "$mode" "$path"
    done <"$RESTORE"
fi

if [[ "$PURGE" == "--purge-operator-store" ]]; then
    rm -rf --one-file-system "$AQD_OPERATOR"
    log "operator store deleted"
fi
log "teardown complete. Delete the Codespace from your own machine: gh codespace delete -c <name>"
