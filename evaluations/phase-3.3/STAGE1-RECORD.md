# Stage 1 per-run record and slot resolution: contract v1 (draft, 2026-11-26)

**Status:**
- **A proposal, to be ratified at the G3 freeze** (`STAGE0-PLAN.md` §5). It answers finding 3 of the external review (`REVIEW-2026-11-26.md`).
- **Implemented and unit-rehearsed offline:** `live/stage1_record.py`, tested by `live/test_stage1_record.py`. The tests use synthetic records only: no model, no network, no private task material.
- **Not yet rehearsed end to end** through a launcher. That needs the multi-dispatch design (H4), which does not exist yet. The H4 mock rehearsal must produce the inputs below, and this resolver must read them unchanged.

**Why it exists:** `results_record.py` describes single runs. Stage 1 also needs:
- how each scheduled slot is resolved when a block is cancelled or replaced;
- what counts as the agent's failure and what is infrastructure;
- which records hold scores, load timing and token completeness.

Without these rules fixed in advance, those choices would be made after the outcomes are known.

## 1. Inputs

| Input | Source | Contents |
|---|---|---|
| Sealed Stage 1 schedule | `schedule.py` with the control-only kind (H3) | Every run has `run_id`, `block`, `task`, `tier`, `group`, `kind` (`paired` or `calibration`) and `repetition`. A replacement block's runs also have `replaces_block` |
| Attempts | `results_record.py`, the scorer (`score_run.py`), the tamper review, `inspect_invocation.py` | Per `run_id`: the results-record entry, the hidden-score summary (`evaluation_status`, `fully_correct`, `hidden_pass_fraction`), `tamper_review`, and the load-timing fields |
| Block events | The H4 launcher's block log | Per block: `state` is `completed`, `cancelled` or `not_started`, and `cause` is one of the causes in §2 |

**What a block holds:**
- a paired block holds exactly one control run and one treatment run;
- a calibration block holds one control run.

**Records outside the schedule:** a record for a run or a block that is not in the schedule is refused.

## 2. Typed causes

| Class | Cause | Counted? | Meaning |
|---|---|---|---|
| scored | none, `wrong_code`, `timeout`, `scope_violation` | yes | A valid run with a valid evaluation. A timeout is an outcome, scored on what exists. A scope violation in a run the harness records as valid (after H2) is scored on its mutable files and is never `strictly_correct` |
| agent | `scope_violation` (the harness marks the run invalid for that reason alone, before H2), `tamper_confirmed` | yes, as a failure | The arm's own failure (intention to treat, `DESIGN.md` §8) |
| infrastructure | `usage_limit`, `rate_limit`, `service_outage`, `sandbox_failure`, `operator_cancel` (block level); `provider_error`, `launcher_stopped`, `run_invalid`, `arm_mismatch`, `no_record` (run level) | no | Makes the whole **block attempt** infrastructure-invalid (§3) |
| unattributed | `evaluation_invalid`, `score_missing`, `review_pending`, `tamper_suspected`, `scope_violation_with_other_reasons`, malformed records | no | Not counted, carried into the 0/1 bounds. **Fail closed:** anything unknown lands here |
| not run | `stop` | no | The block never started because of STOP. Counted apart from the infrastructure rate |

**`arm_mismatch`:** a control that loaded the skill, or a run whose recorded arm differs from the schedule, is a harness failure, never an outcome.

## 3. Block and slot rules

1. **Block cancellation** (`STAGE0-SOLO.md` D4):
   - A usage limit, rate limit, service outage or sandbox failure cancels the block.
   - So does any other infrastructure failure of one of its runs.
   - **Both runs** of that block attempt become infrastructure-invalid, even one that finished.
   - The finished run's outcome is kept in the record (`outcome_before_block_rule`) for the sensitivity analysis that includes failed original blocks (review finding 13). It never counts in the primary analysis.
2. **Replacement:** an infrastructure-invalid block may be replaced **once**, at a later time, by a block with exactly the same slots (task, group, repetition and kind).
   - No chains: a replacement is never itself replaced.
   - No second replacement of the same block.
   - Agent failures and wrong code are never replaced. A replacement of a block that resolved normally is refused: **no rerun for wrong code**.
3. **Slot resolution:** each slot resolves from its last attempt, which is the replacement if there is one. If the replacement also fails on infrastructure, the slot is not counted and goes into the 0/1 bounds.
4. **Evaluator problems are not rerun.** An invalid evaluation or a pending review is resolved by re-scoring or by reviewing, never by running the agent again. The slot stays unattributed until then.
5. **STOP:** blocks that never started because of STOP are `not_run`. They are listed, and kept out of the infrastructure rate.

## 4. Outputs (`aqd-phase-3.3-stage1-record-v1`)

**Per slot:**
- `disposition`;
- `cause`;
- the attempt IDs, in order;
- `replaced`;
- `counted`;
- `fully_correct`, `strictly_correct` (= `fully_correct` and no scope violation) and `hidden_pass_fraction`.

**Per attempt:**
- class, cause, `timed_out`, `scope_violation`;
- `invoked`, `loaded`, `before_first_named_edit`, `shell_before_load` and `before_first_edit`;
- `total_tokens`, `tokens_missing_reason` and duration.

**Summary:**
- **Infrastructure-invalid rate:** the numerator and the denominator count every attempt that started or was cancelled, original and replacement. More than 10% sets `infrastructure_limit_exceeded` (`DESIGN.md` §6).
- **Per arm:**
  - counted and uncounted slots;
  - `fully_correct` and `strictly_correct` successes;
  - agent failures, timeouts and scope violations;
  - complete and missing token records, for the D3 censoring check;
  - invoked, loaded and loaded before the first edit.
- **Hard-control stop rule (≥ 7 of 8):**
  - the successes, and the slots that did not count;
  - whether the rule fires if every such slot failed, and if every one succeeded;
  - `decided`, which is true only when both bounds agree and all 8 slots exist.

**Who may see this record:** it holds treatment results, so it is produced only at analysis time (`STAGE0-SOLO.md` §2.5). Task authors see only the control-only calibration feedback (`DESIGN.md` §6).

## 5. Rehearsal cases (`live/test_stage1_record.py`)

**Cases:**
- a completed block;
- a cancelled block with one finished run;
- one run's provider error cancelling its block;
- a replacement that resolves the block, and one that fails again;
- a refused rerun of wrong code;
- refused double and chained replacements;
- a replacement with different slots;
- a timeout, with its token record missing;
- a scope violation in both harness forms, and one with another reason;
- confirmed and suspected tampering;
- an invalid evaluation;
- a control that loaded the skill;
- STOP;
- a missing record;
- the stop rule decided and undecided under its bounds;
- malformed inputs;
- the command line, both writing a record and refusing.

**Do the tests catch a broken rule?** Four rules were broken on purpose, one at a time, to check this:
- block-wide invalidation;
- scope violation alone versus with other reasons;
- no rerun for wrong code;
- `strictly_correct`.

Each break made at least one test fail.

## 6. Open before ratification

- **Rerun rule:** the run-level infrastructure causes cancelling the whole block goes beyond D4's wording ("a usage limit, rate limit or service outage"). It is proposed because it keeps the handling symmetric, as D4 intends. The owner ratifies or narrows it.
- **`schedule.py`:** it records reruns per slot (`replaces_slot`). H3/H4 must add `replaces_block`, and `analyze.py` must read slots through this resolver, or prove it gives the same result.
- **The H4 mock rehearsal:** it must produce real attempt and block-event files for each case in §5 and resolve them with this tool.
