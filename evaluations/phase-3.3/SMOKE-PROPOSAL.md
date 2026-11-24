# Proposal: minimal two-arm SMOKE run (2026-11-24)

**Status:**
- **The owner accepted decisions D1–D5 as recommended (2026-11-24).** This approves building the pieces in §4 **offline only**: no model calls, no secrets, no live dispatch.
- **The live SMOKE run is not authorised.** It needs a separate written authorisation naming:
  - the two run IDs;
  - the reviewed commit P and the approval commit X;
  - the CLI hash and the prompt hash.

This follows the passing live security probe (`LIVE-PROBE-RESULT.md`).

**Build status (2026-11-24): built offline (§8), then run once with the owner's written authorisation: PASS.** See `SMOKE-RESULT.md`.

## 1. Purpose

This would be the first run of **both arms** of the native Claude Code harness against the real service. It is a harness check and is **never scored**. It answers four questions:
1. Does the treatment arm really get the skill, and the control arm not, on the real service?
2. Do both arms produce **valid** runs on a trivial task?
3. Are the per-run records (validity, tokens and cache, workspace findings, timing) captured the same way in both arms?
4. Does the credential boundary still hold in **both** arms, including treatment with the skill loaded? Evidence: the launcher's token scan and the encrypted-evidence scan.

It does **not** ask whether the skill helps. With 2 runs and a one-line task, it cannot. `analyze.py` already refuses `SMOKE` records.

## 2. The runs

- **Task:** the public `SMOKE` task (`evaluations/phase-3.2/tasks/SMOKE/project/TASK.md`): "Write the single line `ok` into `notes.txt` … Do not change any other file."
- **Runs:** 2 (1 control + 1 treatment), from a sealed schedule: `schedule.py create --tasks SMOKE --repetitions 1` with a fixed, published seed and a fixed `created_utc`. The run IDs and their order come from that schedule.
- **Model and CLI:** the same as the probe: `anthropic/claude-opus-5-5#medium`, Claude Code 2.1.330, binary SHA-256 `f390eaa0…8ebb`.

## 3. Pass criteria

**Every run must:**
- be `valid: true` and `model_ok: true`;
- show `served_by_anthropic`, `apiKeySource: none` and `auth_method: oauth_token`;
- leave `notes.txt` reading exactly `ok`, with no other tracked file changed;
- pass the launcher's token scan;
- produce complete evidence with 0 token-shaped strings.

**Control:** `skills = [doctor]`, `activation: NOT_APPLICABLE`, no Skill invocation.

**Treatment:** `skills = [aqd-arm:code-discipline, doctor]` and `activation: AVAILABLE`. Whether the skill was actually invoked is **recorded**, not required: the treatment is skill *availability*, as in the harness and `DESIGN.md`.

**Workspace findings (D3):**
- The set of unexpected workspace files is recorded per run.
- A file outside the 17 known zero-byte sandbox placeholders, or a placeholder that is not empty, **fails** the run.
- A different placeholder set in the two arms is **flagged** (`placeholders_differ` in the verdict), not failed. The sandbox appears to create these files only when Bash runs, which depends on what the agent does, and so on the arm. Failing on it would make the verdict depend on agent behaviour.

**Any failure** writes STOP. Then: no rerun, revoke the token, and review.

## 4. What has to be built first (D1: offline only)

The probe workflow runs only the single `PROBE-CC` run. SMOKE needs new, reviewed code that keeps to the probe's proven pattern:

1. **A `live-smoke` mode** in `.github/workflows/phase3-cc-smoke.yml`. It reuses the existing steps:
   - guard, approval commit and single use;
   - CLI hashes and egress lock;
   - credentials file and encrypted evidence.

   It runs the two approved runs one after the other through the **unchanged** launcher.
2. **A new environment, `aqd-cc-live-smoke` (D2),** with the same protections:
   - a required reviewer;
   - no administrator bypass;
   - `main` only;
   - its own single use.

   The probe environment's single use stays spent.
3. **`smoke-approval.json`:** the template for two approved runs. It holds SMOKE's prompt SHA-256, the workspace SHA-256 values and the CLI SHA-256. The owner fills it in a one-file approval commit, as for the probe.
4. **`run-live-smoke.sh` and `check_smoke.py`** (the verdict in §3), with:
   - unit tests;
   - mock-CLI rehearsal cases: wrong arm, missing skill, wrong `notes.txt`, token echoed, extra workspace file.
5. **`pack_evidence.py`:** both run IDs in one archive. The required-file manifest is checked per run.

**Then the owner steps, as for the probe:**
1. a reviewed commit P with green CI;
2. a one-file approval commit X;
3. a one-file bootstrap PR to `main`;
4. a mock dispatch;
5. the written authorisation;
6. the token;
7. one dispatch;
8. revocation.

## 5. Decisions (accepted as recommended, 2026-11-24)

| # | Decision | Accepted |
|---|---|---|
| D1 | Build §4 | Yes, offline only (no model calls, no secrets) |
| D2 | Environment | New `aqd-cc-live-smoke`. The probe environment is not reopened |
| D3 | The 17 sandbox placeholder files | Recorded and compared across arms: any extra file or arm difference is flagged. Excluding them properly waits for `DESIGN.md` §5 item 2, before feasibility |
| D4 | Prompt caching | `cache_read` and `cache_write` recorded per run. No cost comparison in SMOKE. How caching is controlled is decided before any feasibility run |
| D5 | Arm order | From the sealed schedule, never chosen by hand |

## 6. Cost and credentials

**Usage:** subscription usage only. There are two short sessions. The probe used about 21,000 tokens, mostly cached reads, in 12 seconds. SMOKE should be similar per run, somewhat more in treatment.

**Credentials (the probe procedure, unchanged):**
- usage credits off;
- one fresh `setup-token` token, checked locally before it is added;
- stored only as the environment secret;
- the secret deleted after the run;
- the account-wide Log Out afterwards.

No documented charge route remains, but zero cost is not guaranteed: whether setup-token traffic can draw usage credits is undocumented, so credits stay off.

## 7. What a SMOKE pass would not unlock

The feasibility experiment (`DESIGN.md` §6, Stage 1) still needs all of Stage 0:
- the tasks built;
- the human oracle review;
- blind difficulty ratings;
- plan approval;
- private task delivery;
- the control-only schedule kind;
- unexpected files as a reported outcome;
- evidence retention.

A SMOKE pass shows only that the two-arm native harness works on the real service. Whether feasibility is justified remains a separate owner decision, made after SMOKE.

## 8. What was built (offline; no model call, no secret, no dispatch)

**The run, fixed in committed files:**

| | Value |
|---|---|
| Schedule | `live/smoke-schedule.json`: `schedule.py create --seed 77f202a8eb78da8cde0cef43110a3e48` (= first 32 hex of SHA-256 of `aqd-phase-3.3-live-smoke-v1`), `--tasks SMOKE --repetitions 1`, with `created_utc` fixed. SHA-256 `a54f6f3300ec607026cfef47d71ac00a33a3f746a5077af90b0c84d08c147dc6`, pinned in `run-live-smoke.sh` |
| **Run IDs, in schedule order** | **`r-709f207e78` (treatment, `env-a`), then `r-2cffa4db9c` (control, `env-b`)**. The workflow pins them as `AQD_SMOKE_RUN_IDS` |
| **Prompt SHA-256** (`SMOKE/project/TASK.md`) | **`21de334c06fd4ee31e30a6283202a8c353c4d266b042c36ab56175e9cd73f86d`** |
| Workspace SHA-256 | `4791a7c5f212ac2900b9b1f761f1779e8a90ab377db7209810fb544cb926b300` (`manifest.build`; the same method reproduces the probe's `17130aa7…`) |
| CLI SHA-256 | `f390eaa0…8ebb` (Claude Code 2.1.330), as for the probe |
| Approval | `live/smoke-approval.json`: the unfilled template for both runs. The owner fills `approved_by`, `approved_utc` and `reviewed_commit` in a one-file commit on the reviewed commit |

**Code:**
- `live/run-live-smoke.sh` (rehearsal or live). Checks the schedule hash and that schedule and approval agree. Then: `setup-host.sh` (`AQD_TASKS=SMOKE`), the egress lock, the native preflight, both runs in schedule order through the unchanged `launch-run-cc.sh`, and the verdict. A non-zero launcher exit writes STOP and the other run does not start.
- `live/check_smoke.py`: the verdict in §3. It writes `smoke-verdict.json`; the public lines hold booleans and counts only.
- `live/rehearse-smoke.sh`: 10 mock-CLI cases on the host (below).
- `pack_evidence.py --kind smoke`: two run IDs plus `smoke-verdict.json`. The probe's behaviour is unchanged.
- `check_approval_commit.py --approval-path`: only the two reviewed approval files are accepted.
- `check_single_use.py` and `check_environment.py --name`: only `aqd-cc-live-probe` or `aqd-cc-live-smoke`.
- `dryrun/mock_claude.py`: opt-in scenario keys `skip_isolation_probe`, `notes_text`, `extra_files` and `extra_file_text`. The dry run's defaults are unchanged.
- Workflow `phase3-cc-smoke.yml`:
  - mode `live-smoke`;
  - job `live-smoke`: the probe job's steps and actions one for one, with environment `aqd-cc-live-smoke`, the SMOKE approval file, its own single use, `run-live-smoke.sh`, two-run packaging and artifact `aqd-cc-live-smoke-encrypted`;
  - `verify-environment` checks the environment of whichever live mode was dispatched;
  - the `mock` job also runs the SMOKE rehearsal.

**Tests (local):**
- 111 live unit tests, all OK. New: the verdict (21), the SMOKE approval commit (6), environment names, two-run packaging and the `live-smoke` job policy (including its guard's own bash).
- Mutation checks: removing each new guard fails a test. The one exception is the SMOKE approval run count, which the template-equality check already enforces.
- `actionlint` with `shellcheck`: clean.

**Rehearsals on a host with bubblewrap and socat:**
- The probe rehearsal still passes, 7 of 7.
- The SMOKE rehearsal passes, 10 of 10:

| Case | Required | Observed |
|---|---|---|
| clean | pass | PASS. Both CLI runs received the approved prompt bytes; evidence complete |
| treatment invokes the skill | pass | PASS (invocation recorded) |
| two empty placeholders in both arms | pass | PASS, `placeholders_differ: false` |
| `notes.txt` wrong | fail | STOP; verdict reason `notes.txt` |
| extra file `notes.bak` | fail | STOP; verdict reason: file outside the known placeholders |
| non-empty `.env` | fail | STOP; verdict reason: placeholder not empty |
| treatment without the skill | fail | the first run is invalid, STOP; the control run never starts; evidence incomplete |
| control with the skill | fail | the control run is invalid, STOP |
| token value echoed | fail | the launcher's token scan: ISOLATION FAILURE; the packager flags the token-shaped string |
| the committed (unfilled) approval | fail | refused before any run |

**Before a live SMOKE run, the owner:**
1. creates the environment `aqd-cc-live-smoke` with the same protections as the probe's;
2. reviews this build and makes it the reviewed commit P;
3. makes the one-file approval commit X (filling `smoke-approval.json`);
4. merges the one-file bootstrap PR to `main`;
5. runs a green mock dispatch;
6. writes the authorisation naming the two run IDs, P, X, the CLI hash and the prompt hash;
7. creates the token;
8. dispatches once, with `run_id` = `r-709f207e78 r-2cffa4db9c` and `confirm` = `RUN-LIVE-SMOKE r-709f207e78 r-2cffa4db9c`;
9. revokes the token.
