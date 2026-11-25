# Stage 0 with one person: decisions D2–D5 and the solo validation protocol (draft, 2026-11-25)

**Status:**
- **Proposal for the owner's review.** Merging this records D2–D5 as decided. Nothing is built, no model call is made and nothing is dispatched by this document.
- The owner's instruction of 2026-11-25:
  - for D2 to D4, "whatever needed for the most accurate results";
  - for D5, "I'm a single person; most of it Claude should do".

**Why this needs its own document.** `DESIGN.md` §3 and §4 assume four kinds of independent people: two blind difficulty raters, an oracle reviewer and a feasibility engineer. With one person and Claude doing the work, that design cannot be followed as written. This document replaces each human role with the most rigorous substitute available, and **states what each substitute cannot do**, so that no later result claims more than the method supports.

## 1. Decisions

| # | Decision | Chosen | Why this is the most accurate option available |
|---|---|---|---|
| **D2** | Task volume | **8 tasks per tier (24 tasks)**: 2 calibration and 6 confirmatory per tier after the sealed draw (`DESIGN.md` §4). Each task in two prompt variants (S and D). Build the G2 pilot batch (2 per tier) first, then the rest | Six confirmatory tasks per tier is the smallest set for which `DESIGN.md` §6 gives usable estimation intervals (about ±0.4 per tier at 2 runs per arm). More tasks is always more accurate. Whether to grow toward a *confirmatory* hard-tier claim (about 25 hard tasks) is decided after G2, from the measured build effort and validator pass rate, not now |
| **D3** | Prompt caching | **(a) Record, never disable.** The token outcome is the **total prompt tokens processed**: `input + cache_read + cache_write` from the run's final usage record (the harness's names for the API's `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`). Tokens are never converted to money, and no cost claim is made | The primary outcome (`fully_correct`) does not depend on caching. The total is the same whether a prefix was read from cache or not; caching changes only the split. So the comparison is invariant to cache state without a harness change. (b) would use far more of the plan (cache reads were 100–176 k tokens per pilot run) and change a reviewed harness file, for no gain in the primary outcome. Counterbalanced run order (`DESIGN.md` §5) covers residual effects on wall time |
| **D4** | Plan usage limits | A run stopped by a usage limit, rate limit or service outage is **infrastructure-invalid**. At most one rerun per slot (the Phase 3.2 rule). Blocks are spread over days. **Stop the stage** if more than 10% of runs are infrastructure-invalid (`DESIGN.md` §6) | An agent cannot cause a usage limit, so counting it as a wrong answer would bias against the longer arm (the treatment, which uses more tokens). The 10% stop keeps the 0/1 bounds of `DESIGN.md` §6 meaningful: in the `DESIGN.md` §6 stress test, 10% invalid slots cut P(benefit) at a nominal +0.20 from 0.48 to 0.10 |
| **D5** | People | **The solo protocol (§2).** The owner is the only human. Claude sessions do the building, validation and rating, under separation rules. The owner keeps every approval and authorisation, plus a short sealed spot check | There is no second person. The substitutes below are chosen so that the **primary outcome stays mechanical** (hidden tests), and model judgement only touches task preparation, where its errors are checked mechanically wherever possible |

## 2. The solo protocol

### 2.1 Roles

| `DESIGN.md` role | Replaced by | Separation rule |
|---|---|---|
| Task author | A **builder** Claude session per task family | Runs with only the private task repository checked out (§2.3). It is never given the skill text, the Phase 3.2 or 3.3 results, or any model output on the task |
| Alternative correct design (R09) | An **alternative-design** session | Sees the public task repository, the prompt and the **obligation list** (the oracle source map without the tests). Never sees the reference solution or the hidden tests |
| Realistic wrong implementations (3 or more) | A **mutant** session, plus mechanical mutation (§2.2 item 4) | Sees the public repository, the prompt and the obligation list. Never sees the hidden tests |
| Oracle reviewer (source map) | Mechanical source-map check (§2.2 item 5), then a **reviewer** session | The reviewer sees the prompt, the repository and the source map. It does not write or change any test |
| Two blind difficulty raters | **Two rater sessions on different Claude models** (for example one Opus and one Sonnet), each in a fresh context | Each sees only the task repository, the prompt variant and the oracle source map. Neither sees the other's ratings, any model run, or the reference solution. Both ratings files are committed, with their SHA-256, before the other is opened |
| Feasibility engineer | The alternative-design session (it shows that a second, independent correct solution can be written), plus the floor guards in the analysis | No task is selected or dropped because an agent *failed* it (§3, T4) |
| Oracle-dispute reviewer (`DESIGN.md` §6) | A fresh reviewer session that sees the disputed code under its `blind_id`, never its arm | As in `DESIGN.md` §6 |
| Owner | Approves the freeze, authorises every live dispatch, does the sealed spot check (§2.4) | Never sees treatment results before the confirmatory analysis (`DESIGN.md` §6) |

Every session's transcript is kept, and is audited for reads of the skill path or the results records before its output is accepted. A session that read them is discarded and its output rebuilt.

### 2.2 Mechanical oracle validation (per task, before the freeze)

A validator script, written and tested offline before the first task is built, checks each task and refuses to mark it valid unless every check holds:

1. **Reference:** the reference solution passes every hidden and every baseline check.
2. **Pristine code:** the untouched repository fails at least one hidden check (so the task is not already solved).
3. **Alternative design:** the alternative-design solution passes every check. If it fails a check, the check is examined: an over-strict check is fixed in a new oracle version; a genuine bug in the alternative is fixed by the same session from its own reading of the obligation list, never from the tests.
4. **Mutants:** each of at least 3 realistic wrong implementations fails at least one hidden check. In addition, a fixed set of **mechanical mutations** of the reference (operator, boundary and removed-statement mutations, by a seeded script) is run, and the kill rate is recorded. Surviving mechanical mutants are recorded, not hidden.
5. **Source map:** every hidden check names its obligation and the source of that obligation: a prompt sentence (quoted) or a repository location (`file:line` plus a quoted fragment). The script checks that each quote appears at the cited place. In the **S** variant every obligation's source must be a prompt sentence. A check with no verifiable source is removed.
6. **No shortcut:** a solution that only hard-codes the visible examples and the visible tests fails at least one hidden check.

The validator's own tests run in CI, like the rest of the harness.

### 2.3 Private task delivery

The hidden tests, reference, alternative designs, mutants and source map live in a **separate private repository**, never in the public one (`STAGE0-PLAN.md` H5). Recommended: a new private repository created by the owner for this purpose only. The existing `aqd-private-evidence-review` repository is a fallback.

### 2.4 The owner's part

| Action | When | Time |
|---|---|---|
| Review and merge each reviewed PR | as they come | as now |
| **Sealed spot check:** for 1 task per tier, drawn by a seeded script *after* the validator passes, read the prompt and the obligation list and mark each obligation "a reasonable requirement" or "not". Any "not" sends the task back to the builder and triggers a check of every task by the same builder | before the freeze | about 30 minutes per task, 1.5 hours in total |
| Approve the freeze (`DESIGN.md` §9) | once | one review |
| Authorise each live stage, as for the probe, SMOKE and G1 | per stage | as before |

## 3. What the solo protocol cannot do (threats, stated in every report)

| # | Threat | Effect | Mitigation | What remains |
|---|---|---|---|---|
| T1 | **Same model family on both sides.** The builder, the raters and the agent under test are all Claude | Tasks may avoid exactly the defects Claude does not think of, making the hard tier easier for Claude than intended | Mechanical mutation (§2.2 item 4); defect classes taken from the written briefs (`DESIGN.md` §4), fixed before building; the Stage 1 stop rule detects a hard tier that is not hard (`≥ 7 of 8` control successes) | The difficulty of the hard tier is a property *for Claude*. The result does not generalise to other agents |
| T2 | **Correlated raters.** Two Claude models agree more with each other than two people would | Rater agreement overstates the rubric's reliability | Two different models; independent contexts; sealed order | Agreement is reported as "model-rater agreement", never as inter-human reliability |
| T3 | **No human oracle review** beyond the spot check | An unreasonable obligation could survive | The quoted source map (§2.2 item 5); the alternative design (R09); the spot check; the oracle-dispute rule after Stage 1 | Reports state that oracles were validated mechanically and spot-checked by one person |
| T4 | **No human feasibility time** | A task might be unsolvable within 45 minutes | The alternative design shows solvability (without a time limit); the floor guard and the "fewer than two discriminating tasks" guard make an unsolvable tier inconclusive, never a false effect | "Feasible within the time budget" is not established before Stage 1 |
| T5 | **The owner is not blind to the hypothesis** | The spot check could favour one kind of task | The spot check never sees model output or arm; the sample is drawn by a script | Stated |
| T6 | **The builder sessions' plan usage** | Building uses the owner's Claude subscription, like this session. It is not API billing, and usage credits stay off | Builds are spread out; nothing runs on the API | Not zero usage: building 24 tasks with validation will use a noticeable share of the plan over several weeks |

**None of these affects the scoring itself.** `fully_correct` comes from hidden tests run in the fail-closed sandbox, with no model judgement. The threats affect which tasks exist and how they are tiered, so they limit what the tier labels mean, not whether a given run passed.

## 4. Consequences for the gates

- **G0** is passed by this document's merge: D0 (a) and D5 (the solo protocol).
- **G2 (pilot batch)** is redefined for the solo protocol. Go if, for the 6 pilot tasks:
  - the validator passes each task (§2.2), with at most one oracle revision per task;
  - model-rater agreement within one point is at least 0.6 per factor (the `DESIGN.md` §3 rule);
  - the owner's spot check finds no unreasonable obligation;
  - the build effort, recorded as sessions and elapsed days per task, is within about 2× of `STAGE0-PLAN.md` §3.
- **G3 and G4** are unchanged.

## 5. Order of work (each a reviewed PR; offline; no live run)

1. **This document** (decisions).
2. **H1 and H6 (per-run results record):** unexpected files with the placeholders excluded, total prompt tokens (D3), invocation, validity, and the evidence bundle's SHA-256. Offline code and tests.
3. **The oracle validator** (§2.2) with its own tests, on a toy task.
4. **The private task repository** (owner creates it) and the task-package layout (H5).
5. **The G2 pilot batch:** 2 tasks per tier through the protocol, then the G2 decision.
6. H2, H3 and H4, before the freeze (G3).
