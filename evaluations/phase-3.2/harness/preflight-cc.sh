#!/usr/bin/env bash
# Native Claude Code preflight (Phase 3.3; execution environment "native-claude-code"). The OpenCode preflight,
# preflight.sh, is unchanged and still the only preflight for Phase 3.2 runs; its preflight.ok never authorises
# a native run, and this script's record never authorises an OpenCode run.
#
# Usage: AQD_CLAUDE_BIN=/path/to/claude preflight-cc.sh
#
# Sends NO model request and performs NO authentication: the token is checked for shape only (never printed);
# subscription authentication is checked per run by launch-run-cc.sh (`claude auth status`), after approval.
#
# Writes $AQD_SEALED/preflight-cc.json. launch-run-cc.sh recomputes its fingerprint (checkout commit, CLI version
# and SHA-256, harness files, settings, skill, schedule, task manifests, turn and time limits) and refuses a run
# if anything changed or the record is older than AQD_CC_PREFLIGHT_MAX_AGE_HOURS (default 24).
# Exit 0 = passed, 1 = failed.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

PY="$(python_bin)"
CC="$AQD_HARNESS/cc_adapter.py"
: "${AQD_CLAUDE_BIN:?AQD_CLAUDE_BIN (the pinned claude binary) is required}"
AQD_CC_MAX_TURNS="${AQD_CC_MAX_TURNS:-200}"
# Pre-registered: 2700 s (lib.sh). Overridable ONLY for no-model dry runs; it is bound by the native preflight and
# recorded per run, and analyze.py refuses runs whose timeouts differ.
AQD_CC_RUN_TIMEOUT_SECONDS="${AQD_CC_RUN_TIMEOUT_SECONDS:-$AQD_RUN_TIMEOUT_SECONDS}"
REPORT="$AQD_SEALED/preflight-cc.json"
SCHEDULE="$AQD_SEALED/schedule.json"

require_cmd sudo python3 tar diff pgrep pkill sha256sum git
sudo -n true 2>/dev/null || die "passwordless sudo is required for the operator"
[[ -d "$AQD_SEALED" && -d "$AQD_PRISTINE" ]] || die "run setup-host.sh first"
rm -f "$REPORT"

# 1. Checkout: a clean commit (the fingerprint records it; any later commit or edit invalidates this preflight).
[[ -z "$(git -C "$AQD_CHECKOUT" status --porcelain)" ]] || die "checkout has uncommitted changes"

# 2. The pinned CLI, owned by root and not writable by anyone else, and nothing that would configure it.
[[ -x "$AQD_CLAUDE_BIN" && "$AQD_CLAUDE_BIN" == /* ]] || die "AQD_CLAUDE_BIN must be an absolute path to an executable"
[[ "$(stat -L -c '%U' "$AQD_CLAUDE_BIN")" == root ]] || die "$AQD_CLAUDE_BIN must be owned by root"
[[ "$(( 8#$(stat -L -c '%a' "$AQD_CLAUDE_BIN") & 8#022 ))" == 0 ]] || die "$AQD_CLAUDE_BIN is group- or world-writable"
[[ ! -e /etc/claude-code ]] || die "/etc/claude-code (managed settings) exists"
[[ ! -e /etc/opencode ]] || die "/etc/opencode exists"
command -v bwrap >/dev/null || die "bubblewrap is required (CLAUDE_CODE_SUBPROCESS_ENV_SCRUB)"
# bubblewrap installed is not enough: the agent users must be able to create the namespaces it needs. Where they
# cannot (unprivileged containers; hosts that restrict unprivileged user namespaces, e.g. AppArmor on Ubuntu 24.04),
# what Claude Code 2.1.330 does with SUBPROCESS_ENV_SCRUB is unverified (it may refuse every Bash call, which would
# turn every run into a silent valid failure). This probe is a necessary condition only, not proof of scrubbing.
for user in "${AQD_USER_FOR_ENV[@]}"; do
    sudo -u "$user" env -i PATH=/usr/bin:/bin bwrap --ro-bind / / --unshare-user --unshare-pid --proc /proc true \
        2>/dev/null || die "$user cannot create bubblewrap namespaces here (CLAUDE_CODE_SUBPROCESS_ENV_SCRUB would not work)"
done

# 3. Agent users: present, unprivileged, able to run the CLI, unable to read operator material.
for env in "${AQD_ENVS[@]}"; do
    user="${AQD_USER_FOR_ENV[$env]}"
    id "$user" >/dev/null 2>&1 || die "user $user missing; run setup-host.sh"
    if id -nG "$user" | tr ' ' '\n' | grep -qxE 'sudo|admin|wheel|root|docker'; then die "$user is in a privileged group"; fi
    if sudo -l -U "$user" 2>/dev/null | grep -q '(ALL'; then die "$user has sudo rights"; fi
    sudo -u "$user" test -x "$AQD_CLAUDE_BIN" || die "$user cannot execute $AQD_CLAUDE_BIN"
    sudo -u "$user" env -i PATH="$(agent_path)" python3 -c 'import sqlite3, csv, multiprocessing' \
        || die "$user cannot run python3 with sqlite3/csv/multiprocessing"
    assert_unreadable_by "$user" "$AQD_OPERATOR" "$AQD_CHECKOUT" "$HOME" /workspaces/.codespaces
    other="env-a"; [[ "$env" == "env-a" ]] && other="env-b"
    assert_unreadable_by "$user" "$AQD_ROOT/$other"
done

# 4. Schedule: every model is anthropic/<id>#<effort>; every task's pristine tree matches its manifest.
[[ -f "$SCHEDULE" ]] || die "create the sealed schedule first"
"$PY" -c 'import json, sys; sys.path.insert(0, sys.argv[1]); import schedule
problems = schedule.validate(json.load(open(sys.argv[2], encoding="utf-8")))
[print("preflight-cc: schedule: " + p, file=sys.stderr) for p in problems]; sys.exit(1 if problems else 0)' \
    "$AQD_HARNESS" "$SCHEDULE" || die "the sealed schedule is not valid"
while IFS= read -r MODEL_REF; do
    "$PY" -c 'import sys; sys.path.insert(0, sys.argv[1]); import cc_adapter as cc; cc.model_parts(sys.argv[2])' \
        "$AQD_HARNESS" "$MODEL_REF" || die "scheduled model $MODEL_REF is not anthropic/<model>#<effort>"
done < <("$PY" -c 'import json, sys; [print(m) for m in json.load(open(sys.argv[1]))["design"]["models"]]' "$SCHEDULE")
while IFS= read -r task; do
    "$PY" "$AQD_HARNESS/manifest.py" verify --manifest "$AQD_PRISTINE/$task/manifest.json" \
        --tree "$AQD_PRISTINE/$task/project" --phase pre --out "$AQD_SEALED/pristine-cc-$task.json" >/dev/null \
        || die "pristine store for $task does not match its manifest"
done < <("$PY" -c 'import json, sys; [print(t) for t in sorted({r["task"] for r in json.load(open(sys.argv[1]))["runs"]})]' "$SCHEDULE")
sha256sum --quiet -c "$AQD_SEALED/pristine-extra.sha256" || die "pristine skill/config changed"

# 5. Credential file: present, operator-only, and holding a token of the subscription shape (never printed).
[[ -f "$AQD_CREDENTIALS" ]] || die "credentials file $AQD_CREDENTIALS missing"
[[ "$(stat -c %a "$AQD_CREDENTIALS")" == "600" ]] || die "$AQD_CREDENTIALS must be mode 0600"
"$PY" - "$AQD_HARNESS" "$AQD_CREDENTIALS" <<'PY' || die "credentials file does not hold one subscription token"
import sys
sys.path.insert(0, sys.argv[1])
import cc_adapter as cc
values = [l.split("=", 1)[1].strip() for l in open(sys.argv[2], encoding="utf-8") if l.startswith("CLAUDE_CODE_OAUTH_TOKEN=")]
others = [l.split("=", 1)[0] for l in open(sys.argv[2], encoding="utf-8") if l.strip() and not l.startswith("CLAUDE_CODE_OAUTH_TOKEN=")]
reasons = cc.check_token(values[0]) if len(values) == 1 else ["expected exactly one CLAUDE_CODE_OAUTH_TOKEN line"]
if others:
    reasons.append("credentials file holds other variables: " + ", ".join(sorted(others)))
for r in reasons:
    print(f"preflight-cc: {r}", file=sys.stderr)
sys.exit(1 if reasons else 0)
PY

# 6. The record, bound to everything above.
"$PY" "$CC" fingerprint --checkout "$AQD_CHECKOUT" --claude "$AQD_CLAUDE_BIN" --sealed "$AQD_SEALED" \
    --pristine "$AQD_PRISTINE" --max-turns "$AQD_CC_MAX_TURNS" --timeout "$AQD_CC_RUN_TIMEOUT_SECONDS" \
    --out "$AQD_SEALED/preflight-cc-fingerprint.json"
"$PY" - "$AQD_SEALED/preflight-cc-fingerprint.json" "$REPORT" <<'PY'
import datetime, json, sys
fp = json.load(open(sys.argv[1], encoding="utf-8"))
failed = [name for name, good in (
    ("cli_version is not 2.1.330", fp["cli_version"] == "2.1.330"),
    ("checkout is not clean", fp["checkout_clean"]),
    ("a harness file is missing", all(fp["harness_sha256"].values())),
    ("CLI hash missing", bool(fp["cli_sha256"])),
    ("schedule hash missing", bool(fp["schedule_sha256"])),
    ("pristine skill differs from the checkout's canonical skill", fp["skill_sha256"] == fp["canonical_skill_sha256"]),
    ("a task manifest is missing", all(fp["task_manifests_sha256"].values()) and fp["task_manifests_sha256"]),
) if not good]
for name in failed:
    print(f"preflight-cc: {name}", file=sys.stderr)
ok = not failed
json.dump({"schema_version": 1, "execution_environment": "native-claude-code", "ok": bool(ok),
           "created_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "fingerprint": fp},
          open(sys.argv[2], "w", encoding="utf-8"), indent=2, sort_keys=True)
sys.exit(0 if ok else 1)
PY
rm -f "$AQD_SEALED/preflight-cc-fingerprint.json"
log "NATIVE PREFLIGHT PASSED. No model request and no authentication were made. Record: $REPORT"
