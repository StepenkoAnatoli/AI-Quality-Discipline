# Native Claude Code: integration review and no-model-call dry run (2026-11-23)

**Scope:** offline development and a dry run with a **mock** CLI and a **synthetic** token.

- No real authentication, no model request, no workflow dispatch, no merge.
- The canonical skill is unchanged (`d050d00f…`).
- No private benchmark material: the dry run uses the public SMOKE task only.

**What the evidence covers:**
- **Shown:** the real launcher and harness code paths.
- **Not shown:** anything about the real CLI (§6).

## 1. Gap assessment and what changed

| # | Gap | Status after this change |
|---|---|---|
| P1 | The only preflight (`preflight.sh`) was OpenCode-specific. `launch-run-cc.sh` accepted any `preflight.ok`, including an OpenCode one, and nothing bound it to what was run | **Fixed.** New `preflight-cc.sh` writes `preflight-cc.json` (below). `preflight.sh` is unchanged |
| P2 | The launcher had never run | **Done.** It ran end to end in a disposable container (§3), and the run was added to CI (§5) |
| P3 | Token exposure was asserted, not examined | **Examined offline** (§4). The decisive questions need a live probe |
| P4 | `run()` wrote token and prompt **before** starting its timeout. A child that never reads stdin blocked the driver indefinitely once the data exceeded the pipe buffer. Only the 60,000-byte prompt cap protected it, and that cap assumed a 64 KiB pipe: Linux gives 4 KiB pipes to a user past `pipe-user-pages-soft` | **Confirmed and fixed.** Reproduced at 70 KB and 300 KB: the driver hung beyond its 2 s timeout. Fix: the stdin feed runs in a thread, so the timeout starts when the process starts. On timeout the group gets TERM (sudo relays it), then KILL. A command that cannot start writes `status: error`. Regression tests added |
| P5 | Private P2 tasks cannot be used without code changes | **Reviewed, not implemented** (§7), and kept out of the SMOKE dry run |
| — | `lib.sh`'s fixed 2700 s timeout made the timeout path untestable | Native-only `AQD_CC_RUN_TIMEOUT_SECONDS`. It defaults to the pre-registered 2700 and is bound by the preflight and recorded per run. A value other than 2700 is refused unless `AQD_CC_DRY_RUN=1`, which the preflight records. `analyze.py` refuses native records whose timeout is not 2700, so dry-run records are never evidence. `lib.sh` is unchanged |
| — | **Found by running as a non-root operator** (the real host): the operator cannot traverse the agent's `/aqd/env-x` (0700). So: (a) the launcher could not hash the run-root settings file, so every run was invalid; (b) the earlier `Popen(cwd=project)` fix for the working directory would fail on the real host. A root dry run hides both | **Fixed.** The run record hashes the operator's own copy of the settings. `cc_exec.sh DIR …` changes directory inside the agent's process (exit 96 if it cannot), as the OpenCode harness's `as_agent` does. The driver runs from `/`. Tests added |
| — | **Found by review:** on timeout through sudo with a non-root operator, the final group KILL raised EPERM once sudo had exited. The driver crashed and a valid timeout became an invalid run | **Fixed.** EPERM is tolerated; the launcher kills by OS user next. If the group cannot be signalled at all, the direct child is killed and the driver never hangs. The new dry-run scenario `timeout-with-child` reproduces the crash against the old code and passes with the fix |
| — | SMOKE could not be scheduled (`KNOWN_TASKS`) | Added as a known task. The default design is unchanged (tested) |
| — | Installed bubblewrap was treated as sufficient | **New preflight gate:** the agent users must be able to create bubblewrap namespaces. In an unprivileged container they cannot (§4) |

**Native preflight record** (`cc_adapter.py fingerprint` / `check-preflight`).

What it binds:
- execution environment `native-claude-code`;
- checkout commit, which must be clean at preflight time **and** at run time;
- CLI version and SHA-256 (the binary must be root-owned and not group- or world-writable);
- SHA-256 of `cc_adapter.py`, `cc_exec.sh`, `launch-run-cc.sh`, `preflight-cc.sh`, `lib.sh`, `run_status.py`, `manifest.py`, `schedule.py` and `aqd_common.py`;
- settings, the pristine skill (which must equal both the checkout's copy and `d050d00f…`), the schedule, every scheduled task's manifest, `pristine-extra.sha256`, the turn limit and the timeout.

When the launcher refuses:
- the record is stale (older than 24 h by default) or dated in the future;
- `ok` is not true;
- the record is from a foreign execution environment or a foreign schema;
- any field differs from the recomputed value. Every changed key is named.

The run record stores the preflight file's SHA-256. A `schedule.py rerun` changes the schedule's hash, so `preflight-cc.sh` must be run again before a rerun. This is intended: a rerun is a recorded change.

## 2. Tests

- **New failing-first tests in `test_cc_adapter.py`:** 51 → 69 tests.
  - Stdin hang: a child that never reads; a child that exits without reading; a group kill that reaches background children; a command that cannot start.
  - Preflight binding: 6 tests covering every bound field, stale, future, naive time, not ok, an OpenCode-shaped record, a dirty or new commit, a non-canonical skill.
  - Static launcher text: the native preflight only.
  - SMOKE is schedulable without changing the default design.
  - EPERM on the group kill (two cases); the timeout policy (dry run only); `analyze.py` refuses non-2700 native records.
  - The driver never enters the project itself; `cc_exec.sh` enters it, or exits 96.
- **Results on the final tree:**

  | Suite | Result |
  |---|---|
  | `test_cc_adapter` | 69 OK |
  | `test_harness` | 67 OK |
  | `test_difficulty` | 68 OK |
  | `test_scoring` | 40 OK |

  ShellCheck is clean at warning level on `launch-run-cc.sh`, `preflight-cc.sh`, `cc_exec.sh` and `dryrun-cc.sh`.
- **The dry-run checker requires each scenario's own reason**, not just its exit code:
  - the invalid reason;
  - the refusal line in the launcher log;
  - for a timeout, `timed_out` and the driver status;
  - for the turn limit, `max_turns`;
  - for activation, the invoked flag.

  It also fails if the `/proc` probe found no session.
- **The checker is tested by mutation:** 15 doctored results files are all rejected:
  - the 8 earlier cases;
  - a timeout that ended idle;
  - a turn limit without `max_turns`;
  - an invalid run with the wrong reason;
  - a refusal with the wrong reason;
  - a lost invoked flag;
  - no session found by the `/proc` probe;
  - an unknown scenario.

## 3. Dry run: the real launcher with a mock CLI

**How it ran:**
- **Container:** `ubuntu:24.04` (digest-pinned) with sudo 1.9.15, bubblewrap 0.9.0 and Python 3.12. `--network none`. `--privileged` only so that bubblewrap works.
- **Operator:** a **non-root** user with passwordless sudo, as on a real host. Root only prepares the container (clone, root-owned mock, operator account).
- **Scripts:** the committed tree's real `setup-host.sh`, `schedule.py`, `preflight-cc.sh` and `launch-run-cc.sh`.
- **The mock** (`dryrun/mock_claude.py`):
  - checks what it receives from inside the agent's uid;
  - edits the mutable SMOKE file;
  - emits a synthetic transcript whose `init.cwd` and `init.skills` are the **real** working directory and skills directory, unless a scenario falsifies them.
- **Results:** `dryrun/results-2026-11-23/`; checked by `check_results.py`: **26 scenarios, 0 failures**. The same run passes on a GitHub `ubuntu-24.04` runner in CI (§5).

| Scenario | Expected | Observed |
|---|---|---|
| control ok | valid | exit 0, valid |
| treatment, skill invoked | valid | exit 0, valid, AVAILABLE, invoked = true |
| treatment, not invoked | valid | exit 0, valid, AVAILABLE, invoked = false (invocation is not a validity condition) |
| timeout (session sleeps past the 20 s timeout) | valid timeout | exit 0, valid, `timed_out` |
| timeout with a leftover child that ignores TERM | valid timeout | exit 0, valid, `timed_out`; no process left (the old code crashed here) |
| turn limit (`error_max_turns`, `is_error: true`, exit 1) | valid | exit 0, valid, outcome `max_turns` |
| auth reports `api_key` | STOP | exit 20, STOP, invalid |
| wrong synthetic token | STOP | exit 20, STOP, invalid |
| API key in the token slot | STOP | exit 20, STOP (refused before `claude` starts) |
| missing credentials | invalid | exit 1, invalid |
| wrong model on a turn / in `init` | invalid | exit 1, invalid |
| missing skill (treatment) / unexpected skill (control) | invalid | exit 1, invalid |
| wrong working directory | invalid | exit 1, invalid |
| corrupted transcript line | invalid | exit 1, invalid |
| provider error result | invalid | exit 1, invalid |
| token leaked into a project file | STOP | exit 21, STOP, invalid (step `token-leak`) |
| unapproved run id | refused | exit 2, no capture |
| CLI binary changed after preflight | refused | exit 2, no capture |
| stale preflight | refused | exit 2, no capture |
| only an OpenCode `preflight.ok` present | refused | exit 2, no capture |
| timeout changed after preflight | refused | exit 2, no capture |
| STOP present | refused | exit 2, no capture |
| timeout 20 s without the dry-run marker | refused | exit 2, no capture ("not the pre-registered 2700") |
| unprivileged container (bubblewrap cannot create namespaces) | preflight fails | preflight refused (agrees with the independent probe) |

**No failure case became a valid failure.** Every negative case is either invalid (excluded and reported) or a stop or refusal.

**Seen from inside every session** (mock probe, all sessions):
- **Command and environment:**
  - argv equals the adapter's command exactly;
  - the working directory is the run's project;
  - the OS user is that arm's user;
  - the environment holds exactly the allow-listed names plus the token and `PWD`;
  - the synthetic token arrived and matched;
  - the prompt SHA-256 is identical in every session and equals SMOKE `TASK.md`.
- **Files:**
  - `TASK.md` is not writable; `notes.txt` is writable;
  - the agent cannot create a file in `skills/` or rename it;
  - claude can create files in its config directory.
- **Isolation:** the operator store, the other arm's tree, the checkout and `/root` are unreadable.
- **Skills directory:** `[]` in control, `[code-discipline]` in treatment.
- **Run record:** carries `execution_environment`, `claude_cli_sha256`, `max_turns`, `timeout_seconds` and `preflight_sha256`.
- **Cleanup after every run:** no agent process left, run roots removed, the secret directory removed, no agent files in `/tmp`, `/var/tmp` or `/dev/shm`.
- **Output directory:** no file contains the synthetic token.

## 4. Token exposure (fake credentials only)

| Question | Answer | How |
|---|---|---|
| Token in any process's argv (`ps`) | **No** | dry run: `/proc/<pid>/cmdline` |
| Can the **other arm's** OS user read a session's environment? | **No** | dry run: `sudo -u <other> cat /proc/<pid>/environ` is refused |
| Can the agent read the root-owned sudo process's environment? | **No** | dry run |
| Token in temp files, captures or outputs written by the harness | **No** | dry run scans |
| Can a **same-user** child (what the agent's Bash tool is) read the token from `/proc/<claude pid>/environ`, or inherit it? | **Yes, without a scrub.** The mock does not scrub, so this is the baseline: Linux lets a same-uid process read another's environment; Yama `ptrace_scope` restricts attaching, not this read | dry run |
| Does `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` remove the token from the Bash tool's environment **and** hide the parent's `/proc` entry? | **Unknown.** The binary contains the variable and a "bubblewrap is required for subprocess env scrubbing" error. Nothing offline shows its effect, so this report does **not** claim it works | needs a live probe |
| Can bubblewrap work on the run host? | **Not in an unprivileged container**: the namespace probe fails. **In a privileged container: yes.** **GitHub `ubuntu-24.04` runner host, as found: NO** (`kernel.apparmor_restrict_unprivileged_userns = 1`; `bwrap: setting up uid map: Permission denied`). **After `sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`: yes** | dry run; CI log of `ec32a23` |
| What does 2.1.330 do when bubblewrap is installed but namespaces are refused? | **Unknown.** It may refuse every Bash call. Then every run would be a silent valid failure, so the preflight now fails closed | needs a live run on such a host, or avoid such hosts |
| `CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR` | In the binary and accepted as an OAuth source, but **undocumented** and apparently meant for Anthropic's own remote runners. **Not used.** A file descriptor would keep the token out of `environ` | owner or Anthropic confirmation needed before any use |

**Live security probe still needed.** It needs separate authorisation and must not be a scored task. It has the agent run, printing **counts, never values**:
- `env | grep -c CLAUDE_CODE_OAUTH_TOKEN`;
- a read of `/proc/$PPID/environ` and of every `/proc/*/environ` it can open, again as counts only;
- `ls /proc | head` (whether a PID namespace is in effect);
- one ordinary test command, which shows Bash works under the sandbox.

Until it passes, the controls are:
- egress locked to Anthropic hosts;
- a dedicated token revoked immediately after;
- transcripts encrypted.

## 5. CI (no model call)

New job `native-claude-code-dry-run` in `phase3-validation.yml`:
- `contents: read`, no secret referenced;
- builds the image from `dryrun/Dockerfile`, runs both dry-run modes and `check_results.py`;
- reports, before any change, whether an unprivileged user can create bubblewrap namespaces on the runner host, with the AppArmor userns sysctl. Then it sets `kernel.apparmor_restrict_unprivileged_userns=0` on the disposable runner (a logged host change) before the dry run;
- prints the preflight logs (synthetic token only; the harness never prints it);
- **result on GitHub (`ec32a23`): green.** As found, namespaces are REFUSED on the runner; after the sysctl change they work. The non-root dry run is pending re-confirmation on the head commit.

**Consequence for a live run on a GitHub runner:** the same `sysctl` change is required, or the native preflight refuses. It weakens a kernel hardening default on a disposable VM, so it must be named in the smoke-test request.

## 6. Still unverified (needs the authorised live smoke test)

- **Authentication and the run:**
  - `claude auth status --json` reports `oauth_token` for a real `setup-token` token;
  - the token prefix (`sk-ant-oat`).
- **Under `--restricted --tools …,Skill`:**
  - the user skill is listed in `init.skills`;
  - `Skill` is in `init.tools`;
  - `init.cwd` is the project path as given, not canonicalised.
- **Real event values:**
  - real `init`, `modelUsage`, `result` and `api_retry` shapes;
  - whether `init.effort` is reported.
- **The env scrub:** its effect and its behaviour without namespaces (§4).
- **The headless combination:** `--restricted` + `--tools Bash` + `acceptEdits` lets a session edit and run tests.
- **Timing and process handling:** how the real CLI reacts to the TERM-then-KILL shutdown.

## 7. Private P2 tasks: minimum opt-in changes (review only; nothing private copied here)

Correction to the earlier private design: overriding `AQD_PHASE_ROOT` would also redirect:
- `score-all.sh`'s sandbox self-test (`$AQD_PHASE_ROOT/tests`);
- `config/global-opencode.jsonc`.

Use a separate task root instead.

1. **`AQD_TASK_ROOT`.** It defaults to `AQD_PHASE_ROOT`. Use it only where tasks and the allowlist are read:
   - `setup-host.sh`'s `manifest.py build/materialize`;
   - `score-all.sh`'s `score_run.py --phase-root`.
2. **The task list in `setup-host.sh`.** Read `AQD_TASKS` (default `SMOKE NEW-01 NEW-02 NEW-03 NEW-04`, unchanged). `preflight-cc.sh` already verifies only the scheduled tasks.
3. **`schedule.py KNOWN_TASKS`.** Add `P2-LS`, `P2-LD`, `P2-HS` and `P2-HD`: IDs only.
4. **Hidden pack layout.** It must land as `$AQD_EVALUATOR/hidden_tests/<TASK>/hidden_tests/` and `inventory/<TASK>.json` for each of the four IDs. The S and D variants of a base share one oracle, so the pack tool writes it twice. It is decoded only after all runs, as now.
5. **Integrity.** The task pack is verified against pinned per-file hashes before extraction into an operator-only root. The preflight fingerprint already binds every scheduled task's manifest, so a changed pack invalidates the preflight.

All five are opt-in, and unset means today's behaviour. They belong in a separate change after the SMOKE smoke test, not in it.

## 8. Scientific constraints, re-checked

- **Identical prompts:** the prompt hash is identical across every dry-run session in both arms. The command is identical by construction (tested).
- **Treatment is availability.** Invocation is recorded separately and is **not** a validity condition: the not-invoked treatment run is valid.
- **Auxiliary models** are recorded, not a validity condition. The Agent/Task tool is not offered, so no subagent can switch models.
  - Residual risk: CLI-internal auxiliary calls (for example compaction) may happen more in the arm with longer contexts. That is part of the availability effect, but it must be **reported by arm**, with a pre-registered sensitivity analysis that excludes runs with auxiliary usage.
- **Effort:** if `--effort` were ignored, both arms would run at the same effort, because argv is identical. That causes no differential bias, but the label would be wrong. Until `init.effort` is observed, results must say "requested effort".
- **Timeouts and the turn limit** stay valid outcomes scored on the final workspace. A difference between arms is part of the intention-to-treat effect, so rates must be reported by arm.
  - The dry-run timeout override (20 s) is bound and recorded. Evidence runs must use the pre-registered 2700 s. An analysis guard that rejects other values for evidence is a small remaining change.
- **OpenCode vs native:**
  - `analyze.py` refuses to pool the two environments.
  - The native launcher refuses an OpenCode `preflight.ok`.
  - The OpenCode harness files are unchanged.

## 9. Verdict for requesting authorisation of ONE live smoke test

**NOT READY.**

Remaining blockers:
1. **The run host decision:** GitHub runners refuse unprivileged user namespaces as found. The request must name the host choice and its consequence:
   - the `sysctl` change on a disposable runner (verified to make bubblewrap work);
   - or another host where `preflight-cc.sh` passes unchanged.
2. **The smoke-test workflow** (`workflow_dispatch` only, `contents: read`, the token secret referenced in exactly one step, egress locked, results encrypted): written, reviewed, and first run with the secret step removed and the mock CLI. **Not written.**
3. **The live security probe (§4):** specified as part of the smoke test, with counts only, never values, and stop rules (any nonzero token count stops the benchmark).
4. **Owner actions:**
   - a dedicated `setup-token` token created right before and revoked right after;
   - usage credits confirmed off;
   - `cc-run-approved.json` naming exactly the smoke-test run ids.

**Not blockers for a SMOKE smoke test**, which is never scored, but still blocking for the 24-run feasibility experiment:
- human oracle review;
- blind difficulty ratings;
- plan approval;
- private task delivery (§7).
