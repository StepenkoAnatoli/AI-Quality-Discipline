#!/usr/bin/env bash
# No-model-call dry run of the native Claude Code launcher. RUN ONLY INSIDE A DISPOSABLE CONTAINER OR VM: it
# creates OS users, /aqd and /workspaces/.aqd-operator, and tightens permissions on $HOME (setup-host.sh).
#
#   docker run --rm --network none -v <repo>:/src:ro -v <out>:/out IMAGE bash /src/evaluations/phase-3.3/dryrun/dryrun-cc.sh
#
# Uses a SYNTHETIC token and the mock CLI (mock_claude.py). Nothing here can authenticate or reach a model: the
# container has no network and the mock never opens a socket. Executes the real setup-host.sh, schedule.py,
# preflight-cc.sh and launch-run-cc.sh (from a clean clone of the committed checkout), positive and negative
# scenarios, and writes /out/dryrun-results-<mode>.ndjson (no token, no task text beyond hashes).
#
# Phase 1 runs as root and only prepares the container: a clean clone, the root-owned mock, and a NON-ROOT
# operator with passwordless sudo (as on a real host, where the operator is not root). Everything else runs as
# that operator, so EPERM paths (signalling the agent users' processes, reading their files) are exercised.
set -euo pipefail

SRC=/src
OUT=/out
CHECKOUT=/srv/AI-Quality-Discipline
MOCK_DIR=/opt/mock-claude
MOCK="$MOCK_DIR/claude"
H="$CHECKOUT/evaluations/phase-3.2/harness"
export AQD_CLAUDE_BIN="$MOCK" AQD_CC_RUN_TIMEOUT_SECONDS=20 AQD_CC_MAX_TURNS=200 AQD_CC_DRY_RUN=1
OPERATOR=/workspaces/.aqd-operator
SEALED="$OPERATOR/sealed"
FAKE_TOKEN="sk-ant-oat01-DRYRUN-SYNTHETIC-0000000000000000000000000000-not-a-credential"
MODEL_REF="anthropic/claude-opus-5-5#medium"
RESULTS="$OUT/dryrun-results-${DRYRUN_MODE:-full}.ndjson"

say() { printf '[dryrun] %s\n' "$*" >&2; }

if [[ "${1:-}" != --as-operator ]]; then
    [[ "$(id -u)" == 0 ]] || { say "phase 1 must start as root inside the disposable container"; exit 2; }
    git config --system --add safe.directory '*'
    git clone -q "$SRC" "$CHECKOUT"
    git -C "$CHECKOUT" checkout -q "$(git -C "$SRC" rev-parse HEAD)"
    install -d -o root -g root -m 0755 "$MOCK_DIR"
    install -o root -g root -m 0755 "$CHECKOUT/evaluations/phase-3.3/dryrun/mock_claude.py" "$MOCK"
    install -o root -g root -m 0644 /dev/null "$MOCK_DIR/scenario.json"
    id op >/dev/null 2>&1 || useradd -m -s /bin/bash op
    printf 'op ALL=(ALL) NOPASSWD:ALL\n' >/etc/sudoers.d/op && chmod 0440 /etc/sudoers.d/op
    chown -R op:op "$CHECKOUT"
    chmod 0777 "$OUT"
    exec sudo -u op -H env DRYRUN_MODE="${DRYRUN_MODE:-full}" bash "$CHECKOUT/evaluations/phase-3.3/dryrun/dryrun-cc.sh" --as-operator
fi
[[ "$(id -u)" != 0 ]] || { say "phase 2 must run as the non-root operator"; exit 2; }
: >"$RESULTS"

bash "$H/setup-host.sh"
python3 "$H/schedule.py" create --out "$SEALED/schedule.json" --models "$MODEL_REF" --tasks SMOKE \
    --repetitions 14 >/dev/null
( umask 077; printf 'CLAUDE_CODE_OAUTH_TOKEN=%s\n' "$FAKE_TOKEN" >"$SEALED/credentials.env" )
cp "$SEALED/credentials.env" "$HOME/credentials.good"

# The expected command, from the adapter itself (what the mock compares its argv with).
EXPECTED_ARGV="$(python3 "$H/cc_adapter.py" argv --claude "$MOCK" --model "$MODEL_REF" \
    --settings /PLACEHOLDER --max-turns "$AQD_CC_MAX_TURNS" --plugin-dir /PLUGIN-PLACEHOLDER)"
TOKEN_SHA="$(printf '%s' "$FAKE_TOKEN" | sha256sum | cut -d' ' -f1)"

# scenario NAME GROUP JSON-OVERRIDES: write scenario.json, run the launcher on the next unused run of GROUP.
mapfile -t CONTROL_RUNS < <(python3 -c 'import json,sys; [print(r["run_id"]) for r in json.load(open(sys.argv[1]))["runs"] if r["group"]=="control"]' "$SEALED/schedule.json")
mapfile -t TREATMENT_RUNS < <(python3 -c 'import json,sys; [print(r["run_id"]) for r in json.load(open(sys.argv[1]))["runs"] if r["group"]=="treatment"]' "$SEALED/schedule.json")
python3 - "$SEALED/schedule.json" "$SEALED/cc-run-approved.json" "$OPERATOR/pristine/SMOKE/project/TASK.md" "$MOCK" \
    "$OPERATOR/pristine/SMOKE/manifest.json" <<'PY'
import hashlib, json, sys
sha = lambda p: hashlib.sha256(open(p, "rb").read()).hexdigest()
runs = json.load(open(sys.argv[1]))["runs"]
# every run but the LAST control run is approved (the unapproved case uses it); each with its prompt and CLI hash
last_control = [r["run_id"] for r in runs if r["group"] == "control"][-1]
approved = [{"run_id": r["run_id"], "task": r["task"], "group": r["group"], "model": r["model"],
             "prompt_sha256": sha(sys.argv[3]), "cli_sha256": sha(sys.argv[4]),
             "workspace_sha256": json.load(open(sys.argv[5]))["workspace_sha256"]}
            for r in runs if r["run_id"] != last_control]
json.dump({"approved_runs": approved, "approved_by": "dry run (synthetic)", "approved_utc": "2026-11-23T00:00:00Z"},
          open(sys.argv[2], "w"), indent=2)
PY
CI=0; TI=0
next_run() { if [[ "$1" == control ]]; then RUN="${CONTROL_RUNS[$CI]}"; CI=$((CI + 1)); else RUN="${TREATMENT_RUNS[$TI]}"; TI=$((TI + 1)); fi; }

write_scenario() {  # write_scenario GROUP OVERRIDES-JSON ENV_LABEL RUN_ID
    local env="$3" other="env-a"
    [[ "$env" == "env-a" ]] && other="env-b"
    python3 - "$HOME/scenario.json" "$EXPECTED_ARGV" "$TOKEN_SHA" "$2" "$OPERATOR" "/aqd/$other" "$CHECKOUT" \
        "/aqd/$env/runs/$4/cc-settings.json" "/aqd/$env/runs/$4/arm-plugin" <<'PY'
import json, sys
path, argv, sha, overrides, operator, other, checkout, settings, plugin = sys.argv[1:10]
argv = [settings if a == "/PLACEHOLDER" else plugin if a == "/PLUGIN-PLACEHOLDER" else a for a in json.loads(argv)]
scenario = {"expected_argv": argv[1:], "token_sha256": sha, "model": "claude-opus-5-5",
            "operator_dir": operator, "other_env_dir": other, "checkout": checkout}
scenario.update(json.loads(overrides))
json.dump(scenario, open(path, "w"), indent=2)
PY
    sudo install -o root -g root -m 0644 "$HOME/scenario.json" "$MOCK_DIR/scenario.json"
}

record() {  # record NAME RUN EXPECT EXIT
    python3 - "$RESULTS" "$1" "$2" "$3" "$4" "$OPERATOR/captures/$2" "$SEALED/STOP" "$OUT/launcher-$1.log" <<'PY'
import json, os, sys
out, name, run, expect, code, cap, stop, log = sys.argv[1:9]
try:
    log_lines = [l.rstrip("\n") for l in open(log, errors="replace") if "unable to resolve host" not in l][-25:]
except OSError:
    log_lines = []
def load(p):
    try:
        return json.load(open(p))
    except (OSError, ValueError):
        return None
status = load(os.path.join(cap, "run-status.json")) or {}
checks = load(os.path.join(cap, "export-checks.json")) or {}
driver = load(os.path.join(cap, "driver", "driver-result.json")) or {}
record = load(os.path.join(cap, "run-record.json")) or {}
probe = None
try:
    for line in open(os.path.join(cap, "driver", "transcript.ndjson")):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if e.get("subtype") == "mock_probe":
            probe = e["probe"]
except OSError:
    pass
row = {"scenario": name, "run_id": run, "expect": expect, "launcher_exit": int(code),
       "capture_exists": os.path.isdir(cap), "valid": status.get("valid"), "timed_out": status.get("timed_out"),
       "invalid_reasons": status.get("invalid_reasons"), "driver_outcome": driver.get("outcome"),
       "driver_status": driver.get("status"), "activation": checks.get("activation"),
       "invoked": checks.get("invoked"), "max_turns_reached": checks.get("max_turns_reached"),
       "stop_file": open(stop).read().strip() if os.path.exists(stop) else None,
       "run_record_keys": sorted(record), "probe": probe, "launcher_log_tail": log_lines}
with open(out, "a") as h:
    h.write(json.dumps(row, sort_keys=True) + "\n")
PY
}

post_checks() {  # cleanup invariants after every run
    local run="$1" bad=()
    for u in aqd-a aqd-b; do pgrep -u "$u" >/dev/null && bad+=("processes of $u alive"); done
    for env in env-a env-b; do [[ -z "$(sudo ls -A "/aqd/$env/runs")" ]] || bad+=("run root left in /aqd/$env/runs"); done
    [[ -z "$(ls -d "$OPERATOR"/cc-secret-* 2>/dev/null)" ]] || bad+=("secret directory left behind")
    [[ -z "$(sudo find /tmp /var/tmp /dev/shm -xdev \( -user aqd-a -o -user aqd-b \) -print -quit 2>/dev/null)" ]] || bad+=("agent files left in tmp")
    printf '%s\n' "${bad[@]:-}" | python3 -c 'import json,sys; print(json.dumps({"cleanup_for": sys.argv[1], "problems": [l.strip() for l in sys.stdin if l.strip()]}))' "$run" >>"$RESULTS"
}

scenario() {  # scenario NAME GROUP EXPECT OVERRIDES [pre-hook]
    local name="$1" group="$2" expect="$3" overrides="$4" hook="${5:-}" env code
    next_run "$group"
    env="$(python3 "$H/schedule.py" get --schedule "$SEALED/schedule.json" --run-id "$RUN" --key env)"
    write_scenario "$group" "$overrides" "$env" "$RUN"
    [[ -z "$hook" ]] || eval "$hook"
    say "scenario $name ($group, $RUN, expect $expect)"
    set +e
    bash "$H/launch-run-cc.sh" "$RUN" >"$OUT/launcher-$name.log" 2>&1
    code=$?
    set -e
    record "$name" "$RUN" "$expect" "$code"
    post_checks "$RUN"
    rm -f "$SEALED/STOP"   # operator acknowledges an expected STOP so the next scenario can run (logged above)
    cp "$HOME/credentials.good" "$SEALED/credentials.env"
}

# Independent probe first: can an agent user create bubblewrap namespaces here? The preflight must agree with it.
if sudo -u aqd-a env -i PATH=/usr/bin:/bin bwrap --ro-bind / / --unshare-user --unshare-pid --proc /proc true 2>/dev/null; then bw=true; else bw=false; fi
printf '{"bwrap_userns_as_agent": %s, "mode": "%s"}\n' "$bw" "${DRYRUN_MODE:-full}" >>"$RESULTS"
set +e
bash "$H/preflight-cc.sh" >"$OUT/preflight-${DRYRUN_MODE:-full}.log" 2>&1
PF=$?
set -e
printf '{"preflight_exit": %s, "mode": "%s"}\n' "$PF" "${DRYRUN_MODE:-full}" >>"$RESULTS"
if [[ "${DRYRUN_MODE:-full}" == preflight-only || "$PF" != 0 ]]; then say "preflight exit $PF; stopping"; exit 0; fi

# ---- positive cases
scenario control-ok              control   valid  '{}'
scenario treatment-ok-invoked    treatment valid  '{"invoke_skill": true}'
scenario treatment-not-invoked   treatment valid  '{}'
scenario timeout                 control   valid  '{"sleep": 120}'
scenario timeout-with-child      treatment valid  '{"sleep": 120, "background_child": true}'
scenario turn-limit              treatment valid  '{"result": ["error_max_turns", true], "exit": 1}'
# ---- negative cases: each must be INVALID or refused, never a valid failure
scenario auth-api-key            control   stop20 '{"auth": {"loggedIn": true, "authMethod": "api_key", "apiKeySource": "ANTHROPIC_API_KEY"}}'
scenario wrong-model             treatment invalid '{"turn_model": "claude-haiku-5-5"}'
scenario wrong-init-model        control   invalid '{"init_model": "claude-sonnet-5-5"}'
scenario missing-skill           treatment invalid '{"init_overrides": {"skills": ["doctor"]}}'
scenario unexpected-skill        control   invalid '{"init_overrides": {"skills": ["doctor", "other-skill"]}}'
scenario wrong-cwd               control   invalid '{"init_overrides": {"cwd": "/root"}}'
scenario corrupted-transcript    treatment invalid '{"corrupt": true}'
scenario provider-error          control   invalid '{"result": ["error_during_execution", true], "exit": 1}'
scenario missing-credentials     treatment invalid '{}' ': >"$SEALED/credentials.env"; chmod 600 "$SEALED/credentials.env"'
scenario wrong-token             control   stop20 '{}' 'printf "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-oat01-WRONG-SYNTHETIC\n" >"$SEALED/credentials.env"'
scenario api-key-in-token-slot   treatment stop20  '{}' 'printf "CLAUDE_CODE_OAUTH_TOKEN=sk-ant-api03-SYNTHETIC\n" >"$SEALED/credentials.env"'
scenario leaked-token            control   stop21 '{"leak_token": true}'
scenario sandbox-failure         treatment stop22 '{"sandbox_fail": true}'

# ---- refusals before anything starts (no capture directory may appear)
refusal() {  # refusal NAME RUN HOOK UNDO
    local code
    eval "$3"
    set +e; bash "$H/launch-run-cc.sh" "$2" >"$OUT/launcher-$1.log" 2>&1; code=$?; set -e
    record "$1" "$2" "refused" "$code"
    eval "$4"
}
LAST_CONTROL="${CONTROL_RUNS[${#CONTROL_RUNS[@]}-1]}"
refusal unapproved-run "$LAST_CONTROL" ':' ':'
next_run control
refusal binary-changed-after-preflight "$RUN" 'cp "$MOCK" "$HOME/mock.bak"; printf "\n# changed\n" | sudo tee -a "$MOCK" >/dev/null' 'sudo install -o root -g root -m 0755 "$HOME/mock.bak" "$MOCK"'
refusal stale-preflight "$RUN" 'cp "$SEALED/preflight-cc.json" "$HOME/pf.bak"; python3 -c "import json,sys; p=sys.argv[1]; d=json.load(open(p)); d[\"created_utc\"]=\"2026-01-01T00:00:00+00:00\"; json.dump(d,open(p,\"w\"))" "$SEALED/preflight-cc.json"' 'cp "$HOME/pf.bak" "$SEALED/preflight-cc.json"'
refusal opencode-preflight-only "$RUN" 'mv "$SEALED/preflight-cc.json" "$HOME/pf.bak"; echo "{}" >"$SEALED/preflight.ok"' 'mv "$HOME/pf.bak" "$SEALED/preflight-cc.json"; rm -f "$SEALED/preflight.ok"'
refusal not-a-dry-run-timeout "$RUN" 'export AQD_CC_DRY_RUN=0' 'export AQD_CC_DRY_RUN=1'
refusal timeout-changed-after-preflight "$RUN" 'export AQD_CC_RUN_TIMEOUT_SECONDS=30' 'export AQD_CC_RUN_TIMEOUT_SECONDS=20'
refusal stop-file-present "$RUN" 'echo "earlier stop" >"$SEALED/STOP"' 'rm -f "$SEALED/STOP"'

# ---- cross-user /proc probe with the synthetic token: the other arm's user must NOT read a session's environment
next_run treatment
env="$(python3 "$H/schedule.py" get --schedule "$SEALED/schedule.json" --run-id "$RUN" --key env)"
write_scenario treatment '{"sleep": 8}' "$env" "$RUN"
bash "$H/launch-run-cc.sh" "$RUN" >"$OUT/launcher-proc-probe-run.log" 2>&1 &
LPID=$!
user=aqd-a; other=aqd-b; [[ "$env" == env-b ]] && { user=aqd-b; other=aqd-a; }
# The session process is the one named "claude" (cc_exec.sh, which still has no token, also has the path in argv).
pid=""; same=0
for _ in $(seq 1 40); do
    pid="$(pgrep -u "$user" -x claude | head -n 1 || true)"
    if [[ -n "$pid" ]]; then
        same="$(sudo -u "$user" cat "/proc/$pid/environ" 2>/dev/null | tr '\0' '\n' | grep -c '^CLAUDE_CODE_OAUTH_TOKEN=' || true)"
        [[ "$same" -gt 0 ]] && break
    fi
    sleep 0.25
done
cross="$(sudo -u "$other" cat "/proc/$pid/environ" 2>/dev/null | tr '\0' '\n' | grep -c '^CLAUDE_CODE_OAUTH_TOKEN=' || true)"
cmdline="$(tr '\0' ' ' <"/proc/${pid:-0}/cmdline" 2>/dev/null | grep -c 'sk-ant' || true)"
sudo_pid="$(pgrep -f "sudo -n -u $user" | head -n 1 || true)"
sudo_env="$(sudo -u "$user" cat "/proc/${sudo_pid:-0}/environ" 2>/dev/null | grep -c . || true)"
wait "$LPID" || true
printf '{"proc_probe": {"session_pid_found": %s, "same_user_reads_token": %s, "other_arm_reads_token": %s, "token_in_cmdline": %s, "agent_reads_sudo_environ": %s}}\n' \
    "$([[ -n "$pid" ]] && echo true || echo false)" "$([[ "$same" -gt 0 ]] && echo true || echo false)" \
    "$([[ "$cross" -gt 0 ]] && echo true || echo false)" "$([[ "$cmdline" -gt 0 ]] && echo true || echo false)" \
    "$([[ "$sudo_env" -gt 0 ]] && echo true || echo false)" >>"$RESULTS"
record proc-probe-run "$RUN" valid 0
post_checks "$RUN"

# ---- no output file may contain the synthetic token (the leak scenario's capture stays in the operator store)
if grep -rlF "$FAKE_TOKEN" "$OUT" >/dev/null 2>&1; then echo '{"out_dir_token_scan": "FOUND"}' >>"$RESULTS"; else echo '{"out_dir_token_scan": "clean"}' >>"$RESULTS"; fi
say "done: $RESULTS"
