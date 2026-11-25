# G1 invocation pilot (2026-11-24)

**Status:**
- **Run once, with the owner's written authorisation of 2026-11-25:** harness PASS; the skill was invoked in 3 of 3 treatment runs. See `PILOT-G1-RESULT.md`. The owner then chose D1 (a), availability.
- Built offline first (§4); the files are now the record of that run and are not changed.
- The owner chose this design on 2026-11-24 (`STAGE0-PLAN.md` gate G1): 3 pairs on NEW-02, NEW-03 and NEW-04.
- **Never scored.** No hidden test runs and nothing is analysed. The records stay in the encrypted evidence and are never pooled with any scientific result.

## 1. The question

In the native harness the skill is only *available*: the agent decides whether to load it. In SMOKE it did not (`SMOKE-RESULT.md`). The question is whether the agent invokes `code-discipline` on **realistic** tasks.

The answer decides the estimand (`STAGE0-PLAN.md` D1):
- if the skill is invoked often, measure availability;
- if it is rarely invoked, measure exposure, or both, or stop.

## 2. The runs

| | Value |
|---|---|
| Tasks | NEW-02 (concurrent inventory reservations), NEW-03 (CSV import compatibility), NEW-04 (job queue leases): the public Phase 3.2 projects and prompts, unchanged |
| Design | One control and one treatment run per task: **6 runs**. Pairs, because the native preflight accepts only control+treatment blocks (`schedule.validate`); a treatment-only schedule would change a core harness file |
| Schedule | `live/pilot-schedule.json`: `schedule.py create --seed 139fa8e904da0cdfcc75fc30d562d637` (= first 32 hex of SHA-256 of `aqd-phase-3.3-live-pilot-g1-v1`), `--tasks NEW-02,NEW-03,NEW-04 --repetitions 1 --counterbalance`, with `created_utc` fixed. SHA-256 `bad87ea676f335e605bf39afcab82c9b0f9f44cc4482ee883d1b079dd0425f16`, pinned in `run-live-pilot.sh`. Arm order counterbalanced: treatment first in two blocks, control first in one |
| **Run IDs, in schedule order** | `r-49a8ed9516` (NEW-04, treatment), `r-b77ae663bf` (NEW-04, control), `r-2467089ae3` (NEW-02, control), `r-3dbe15e184` (NEW-02, treatment), `r-bc23637fc1` (NEW-03, treatment), `r-6568760496` (NEW-03, control). The workflow pins them as `AQD_PILOT_RUN_IDS` |
| **Prompt SHA-256** | NEW-02 `9c4bde140efbacabf564f3307aa16955efb869d0dc6a3b354bb8322a727a543f`; NEW-03 `a5764db416e9848f7b6d51f06948b5110a6785013903260892942d3a042f649b`; NEW-04 `a50a09d169767c51111c1dbd7729c2ee401791541ba21b9ce5237e6240594b93` |
| Workspace SHA-256 | NEW-02 `ae420d1d9c62…`, NEW-03 `cd61f2a29fd9…`, NEW-04 `b8ee898b84df…` (the full values are in `live/pilot-approval.json`, from `manifest.build`) |
| CLI SHA-256 | `f390eaa0…8ebb` (Claude Code 2.1.330), as before |
| Approval | `live/pilot-approval.json`: the unfilled template for all six runs |
| Time | Up to 45 minutes per run (the pre-registered timeout). Job limit 330 minutes, under GitHub's 6-hour cap. Phase 3.2 sessions on these tasks took a few minutes each |

## 3. Verdict (`live/check_pilot.py`)

**Harness PASS requires all six runs, each:**
- valid, with `model_ok`;
- signed in with the subscription token (`oauth_token`);
- running its scheduled arm: control `[doctor]`, `NOT_APPLICABLE`, no invocation; treatment `[aqd-arm:code-discipline, doctor]`, `AVAILABLE`;
- with no symlink or special-file findings;

and no STOP file.

**The measurement is recorded whatever the harness verdict:** the skill was invoked in *k* of the valid treatment runs, per task.

**Recorded, never failed:** unexpected workspace files (tests an agent writes, the sandbox placeholders), tool counts, tokens with the cache split, duration and timeouts.

**Batch rule (`run-live-pilot.sh`):**
- **Launcher exit 1 (an invalid run):** recorded, and the batch continues. On realistic tasks an invalid run can be the agent's own doing, for example a scope violation.
- **Any other non-zero exit, or a STOP file:** the batch ends at once. These are 2 (refused), 20 (auth blocked), 21 (isolation failure) and 22 (infrastructure).

**Decision rule for G1** (the owner decides; this only frames it):

| Treatment runs invoking the skill | Suggests |
|---|---|
| 3 of 3 | D1(a), availability |
| 1–2 of 3 | D1(c), both, or a larger pilot |
| 0 of 3 | D1(b), exposure, or stop |

With 3 runs this is a coarse signal, not an estimate.

## 4. What was built

- `live/pilot-schedule.json`, `live/pilot-approval.json`, `live/check_pilot.py` (with 10 tests), `live/run-live-pilot.sh` and `live/rehearse-pilot.sh`.
- `pack_evidence.py --kind pilot` (six runs plus `pilot-verdict.json`).
- `check_approval_commit.py --approval-path …/pilot-approval.json` (six runs).
- `check_single_use.py` and `check_environment.py` accept `aqd-cc-live-pilot`.
- Workflow:
  - mode `live-pilot`;
  - job `live-pilot`: the SMOKE job's steps one for one, in environment `aqd-cc-live-pilot`, timeout 330 minutes, artifact `aqd-cc-live-pilot-encrypted`;
  - `verify-environment` maps the mode to its environment;
  - the `mock` job runs the pilot rehearsal.
- The probe and SMOKE files are unchanged; they are the record of runs that happened.

**Tests:** 143 live tests OK. Mutation checks: each new guard fails a test when removed. `actionlint` and `shellcheck`: clean.

**Pilot rehearsal (mock CLI, on a host with bubblewrap):** 6 of 6 cases behaved as required.

| Case | Result |
|---|---|
| clean | harness PASS, invocation 0 of 3; every run received its task's approved prompt |
| skill invoked | PASS, invocation 3 of 3 |
| control given the skill | the control runs are invalid, the batch **continues** (all 6 run), FAIL |
| treatment without the skill | the treatment runs are invalid, the batch continues, FAIL, invocation denominator 0 |
| token echoed | ISOLATION FAILURE in the first run; the batch stops; the packager flags the token-shaped string |
| committed (unfilled) approval | refused before any run |

## 5. Owner steps before a live pilot

1. Create the environment `aqd-cc-live-pilot`, with the same protections as the other live environments.
2. Make this build the reviewed commit P.
3. Make the one-file approval commit X, filling `pilot-approval.json`.
4. Merge the bootstrap PR to `main`.
5. Run a green mock dispatch.
6. Write the authorisation, naming the six run IDs, P, X, the CLI hash and the three prompt hashes.
7. Make sure usage credits are off.
8. Create the token.
9. Dispatch once, with mode `live-pilot`, `run_id` = the six IDs separated by spaces, and `confirm` = `RUN-LIVE-PILOT ` followed by the same six IDs.
10. Revoke the token afterwards.
