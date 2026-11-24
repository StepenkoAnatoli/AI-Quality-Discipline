# Proposal: minimal two-arm SMOKE run (2026-11-24)

**Status:**
- **The owner accepted decisions D1–D5 as recommended (2026-11-24).** This approves building the pieces in §4 **offline only**: no model calls, no secrets, no live dispatch.
- **The live SMOKE run is not authorised.** It needs a separate written authorisation naming:
  - the two run IDs;
  - the reviewed commit P and the approval commit X;
  - the CLI hash and the prompt hash.

This follows the passing live security probe (`LIVE-PROBE-RESULT.md`).

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
- A file outside the 17 known zero-byte sandbox placeholders, or a different set in the two arms, is flagged.

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
