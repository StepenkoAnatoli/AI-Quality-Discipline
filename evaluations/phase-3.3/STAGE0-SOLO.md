# Stage 0 with one person: decisions D2–D5 and the solo validation protocol (draft, 2026-11-25)

**Status:**
- **Proposal for the owner's review.** Merging this records D2–D5 as decided. Nothing is built, no model call is made and nothing is dispatched by this document.
- The owner's instruction of 2026-11-25:
  - for D2 to D4, "whatever needed for the most accurate results";
  - for D5, "I'm a single person; most of it Claude should do".
- **Revised the same day** after an independent review (a separate reviewer session given the diff, not the author's conclusions). It found 10 methodology and 5 code problems; each is addressed below or in `live/results_record.py`.

**Why this needs its own document.** `DESIGN.md` §3 and §4 assume four kinds of independent people: two blind difficulty raters, an oracle reviewer and a feasibility engineer. `DESIGN.md` §6 also assumes an operator who keeps treatment results sealed from anyone who can still change a task. With one person and Claude doing the work, that design cannot be followed as written. This document replaces each role with the most rigorous substitute available, and **states what each substitute cannot do**, so that no later result claims more than the method supports.

## 1. Decisions

| # | Decision | Chosen | Why |
|---|---|---|---|
| **D2** | Task volume | **8 tasks per tier (24 tasks)**: 2 calibration and 6 confirmatory per tier after the sealed draw (`DESIGN.md` §4). Each task in two prompt variants (S and D). Build the G2 pilot batch (2 per tier) first, then the rest | 6 tasks × 2 runs per tier is the Stage 2 size `DESIGN.md` §6 recommends, with 95% half-widths of about ±0.42–0.47 per tier in its simulations, labelled "estimation". More tasks is always more accurate. Whether to grow toward a *confirmatory* hard-tier claim (about 25 hard tasks, `DESIGN.md` §6) is decided after G2, from the measured build effort and validator results, not now |
| **D3** | Prompt caching and the overhead measure | **(a) Record, never disable.** Token volume per run is **`total_prompt_tokens` = input + cache_read + cache_write** from the session's final usage record (the API's `input_tokens`, `cache_read_input_tokens` and `cache_creation_input_tokens`), plus output tokens. **No money figure.** This amends the overhead threshold of `DESIGN.md` §7 and the cost leg of its adoption rule (§8): "cost ratio" becomes the **median per-task treatment/control ratio of total tokens (total prompt + output)**, limit 1.5, next to the unchanged wall-time ratio. **Timed-out runs** have no final usage record, so their token values are missing: token ratios use the runs with complete records, and every report gives the number of missing token records and the timeout rate per arm | The primary outcome (`fully_correct`) does not depend on caching. The total prompt size is the same whether a prefix was read from cache or not; caching changes only the split. So token volume is comparable without a harness change. A subscription has no per-run price, so a money ratio would be invented. (b) would use much more of the plan (cache reads were 100–176 k tokens per pilot run) and change a reviewed harness file, for no gain in the primary outcome. Counterbalanced run order (`DESIGN.md` §5) covers residual effects on wall time. **Not verified:** whether the final usage record includes any auxiliary model calls the CLI makes; this is checked on the first Stage 1 records |
| **D4** | Plan usage limits | A **usage limit, rate limit or service outage stops the block**, not just the run. Both runs of that block are infrastructure-invalid and the **block** is rerun once, at a later time. This follows the reasoning the harness already applies to a sandbox failure (`launch-run-cc.sh` stops the batch rather than invalidate only the runs that used Bash). Detecting a usage-limit stop and stopping the block needs a launcher change, built with H4. Blocks are spread over days. If more than 10% of runs in a stage are infrastructure-invalid, the stage stops and the harness or the schedule is fixed before going on (`DESIGN.md` §6) | A usage limit is more likely to hit the arm that uses more tokens, and the later runs in a sequence. Invalidating single runs would therefore make the exclusions depend on the arm. Stopping and rerunning whole blocks keeps them arm-neutral. **The 10% limit is a stop rule, not a sign that 10% is harmless:** in the `DESIGN.md` §6 stress test (25 tasks × 2 runs per tier), 10% invalid slots cut P(benefit) at a nominal +0.20 from 0.48 to 0.10. Below the limit, every report still gives both 0/1 bounds |
| **D5** | People | **The solo protocol (§2).** The owner is the only human. Claude sessions do the building, validation and rating, under separation rules. The owner keeps every approval and authorisation, plus two short sealed spot checks | There is no second person. The substitutes are chosen so that the **primary outcome stays mechanical** (hidden tests), and model judgement touches only task preparation, where its errors are checked mechanically wherever possible |

## 2. The solo protocol

### 2.1 Roles

The agent under test is the pinned Stage 1/2 model. "**Another model**" below means a Claude model other than that one (for example Sonnet when the agent under test is Opus).

| `DESIGN.md` role | Replaced by | Separation rule |
|---|---|---|
| Task author | A **builder** session per task family | Only the private task repository in its checkout (§2.3). Never given the skill, the Phase 3.2 or 3.3 results, or any model output on the task |
| Pre-run oracle review | A **reviewer** session, before any alternative or mutant exists | Sees the prompt, the repository, the hidden checks and the source map. Judges, for **every** check, whether it demands only what its cited source states, and for the D variant whether each source is in a file the agent must read or change, or is referenced from one. Writes findings; never writes tests |
| Alternative correct design (R09) | An **alternative-design** session on **another model** | Sees the public task repository, the prompt and the **obligation list** (the source map without the tests). Never sees the reference, the hidden tests or the check results |
| Realistic wrong implementations (3 or more) | A **mutant** session, plus mechanical mutation (§2.2 item 4) | Sees the public repository, the prompt and the obligation list. Never sees the hidden tests |
| Two blind difficulty raters | **Two rater sessions on two different models**, each in a fresh context | Each sees only the task repository, the prompt variant and the oracle source map. Neither sees the other's ratings, any model run or the reference. Both ratings files are committed, with their SHA-256, before either is compared |
| Feasibility engineer | No full substitute (T4). The alternative design shows that a second correct solution exists **given the obligation list**; the floor guards in the analysis make an unsolvable tier inconclusive | — |
| Oracle-dispute reviewer (`DESIGN.md` §6) | A fresh reviewer session that sees the disputed code under its `blind_id`, never its arm | As in `DESIGN.md` §6 |
| Operator (sealed results, `DESIGN.md` §6) | The workflow, plus a rule (§2.5) | §2.5 |
| Owner | Merges reviewed PRs, does the spot checks (§2.4), approves the freeze, authorises every live dispatch | Does not decrypt a Stage 1 or Stage 2 bundle before the confirmatory analysis (§2.5) |

**Every session's transcript is kept and audited before its output is accepted.** A session is discarded, and its output rebuilt, if its transcript shows:
- a read of the skill directory or of any result record;
- any `Skill` tool use;
- any of the skill's sentinel texts (`SKILL_SENTINELS` in `aqd_common.py`, which the harness already checks for).

Builder, alternative-design, mutant, reviewer and rater sessions run as cloud sessions with no plugins or personal skills configured.

### 2.2 Mechanical oracle validation (per task, before the freeze)

A validator script, written and tested offline before the first task is built, refuses to mark a task valid unless every check holds:

1. **Reference:** the reference solution passes every hidden and every baseline check.
2. **Pristine code:** the untouched repository fails at least one hidden check.
3. **Alternative design.** The alternative passes every check, **or** each check it fails is confirmed, by the rule below, to demand only what its source states.
   - **The rule** (pre-registered, so that an agent's failure cannot by itself change the oracle):
     - a check may be changed only if a **fresh reviewer**, shown the check and its cited source but **not** the alternative's code or result, finds that the check demands behaviour the source does not state;
     - the alternative's author may fix its own code only from the obligation list, never from the tests.
   - **No task is dropped because the alternative failed.**
   - **Every revision is logged:** each check changed after an alternative's failure is recorded with its reason, counted per tier, and reported (T7).
4. **Mutants:** each of at least 3 realistic wrong implementations fails at least one hidden check. In addition, a fixed set of **mechanical mutations** of the reference (operator, boundary and removed-statement mutations, from a seeded script) is run, and the kill rate is recorded. Surviving mechanical mutants are recorded, not hidden.
5. **Source map:** every hidden check names its obligation and the source of that obligation: a prompt sentence (quoted) or a repository location (`file:line` plus a quoted fragment). The script checks that each quote appears at the cited place. In the **S** variant every source must be a prompt sentence. A check with no verifiable source is removed. (A quote that exists is not the same as one an agent can find; the pre-run reviewer checks findability for the D variant.)
6. **No shortcut:** a solution that only hard-codes the visible examples and the visible tests fails at least one hidden check.

The validator's own tests run in CI, like the rest of the harness.

### 2.3 Private task delivery

The hidden tests, reference, alternative designs, mutants and source map live in the owner's private repository **`aqd-private-tasks`**, created for this purpose only (`STAGE0-PLAN.md` H5). **It must never hold results or evidence of any run**, so that a builder with that repository checked out cannot see them.

### 2.4 The owner's part

| Action | When | Time |
|---|---|---|
| Review and merge each reviewed PR | as they come | as now |
| **Sealed spot check 1:** 1 pilot task per tier, drawn by a seeded script after the validator passes. Read the prompt and the obligation list, and mark each obligation "a reasonable requirement" or "not". Any "not" sends the task back to the builder, and every task by that builder is checked again | at G2 | about 30 minutes per task, 1.5 hours |
| **Sealed spot check 2:** the same, for 1 task per tier drawn from the 18 non-pilot tasks | before the freeze | about 1.5 hours |
| Approve the freeze (`DESIGN.md` §9) | once | one review |
| Authorise each live stage, as for the probe, SMOKE and G1 | per stage | as before |

### 2.5 Keeping treatment results sealed

`DESIGN.md` §6 lets task authors see only control-only calibration feedback. With one person, this is kept by rules, not by a second person:

- The Stage 1 and Stage 2 workflows publish only:
  - the public log, with counts and validity;
  - the encrypted bundle;
  - for Stage 1, the control-only calibration feedback (`analyze.py --calibration-feedback`) as its own file.
- **The owner does not decrypt a Stage 1 or Stage 2 bundle before the confirmatory analysis is complete.** The owner keeps each `.gpg` file and records its SHA-256, without decrypting it. (For the probe, SMOKE and G1 the owner decrypted at once. Those were harness checks with nothing to seal.)
- `results_record.py` and every other per-run tool that shows treatment results run only at analysis time, in a fresh session.
- **No session that has seen a treatment result may build, review or change a task.**
- This is procedural: nothing technical stops an early decryption. It is stated as T8.

## 3. What the solo protocol cannot do (threats, stated in every report)

| # | Threat | Effect | Mitigation | What remains |
|---|---|---|---|---|
| T1 | **Same model family on both sides.** Builders, reviewers, raters and the agent under test are all Claude | Tasks may avoid exactly the defects Claude does not think of, making the hard tier easier for Claude than intended | Mechanical mutation (§2.2 item 4); defect classes taken from the written briefs (`DESIGN.md` §4), fixed before building; the Stage 1 stop rule detects a hard tier that is not hard (`≥ 7 of 8` control successes) | The difficulty of the hard tier is a property *for Claude*. The result does not generalise to other agents |
| T2 | **Correlated raters.** Two Claude models agree more with each other than two people would | Rater agreement overstates the rubric's reliability | Two different models; independent contexts; sealed order | Agreement is reported as "model-rater agreement", never as inter-human reliability |
| T3 | **No human oracle review** beyond the spot checks | An unreasonable obligation could survive | The pre-run review of every check; the quoted source map (§2.2 item 5); the alternative design (R09); the spot checks; the oracle-dispute rule after Stage 1 | Reports state that oracles were validated mechanically and by model review, and spot-checked by one person |
| T4 | **No feasibility evidence from public material** | A task, especially a D variant, may be unsolvable from what the agent is given, or within 45 minutes | The alternative design shows that a correct solution exists **given the obligation list** (that is, with S-variant information, without a time limit). The pre-run reviewer checks that D-variant sources are findable. The floor and "fewer than two discriminating tasks" guards make an unsolvable tier inconclusive, never a false effect | Feasibility from public material within the time budget is not established before Stage 1 |
| T5 | **The owner is not blind to the hypothesis** | The spot checks could favour one kind of task | The spot checks never see model output or arm; the samples are drawn by a script | Stated |
| T6 | **The building sessions' plan usage** | Building uses the owner's Claude subscription, like this session. It is not API billing, and usage credits stay off | Builds are spread out; nothing runs on the API | Not zero usage: building 24 tasks with validation will use a noticeable share of the plan over several weeks |
| T7 | **Oracle attention follows agent failure.** A check that the alternative (a Claude agent without the skill) fails gets a second review, while a check it passes does not | Checks that Claude-without-the-skill fails are more likely to be loosened, which can raise control success | Every check is reviewed once before any alternative exists; a change needs a finding from the source alone, made without the failing code; the alternative runs on another model; no task is dropped for an agent's failure; every such revision is logged and counted | The number of alternative-triggered revisions per tier is reported. If a tier's revisions are frequent, its results carry that caveat |
| T8 | **Sealing is procedural** | If the owner decrypted early, someone who can change tasks would have seen treatment results | §2.5 rules; the bundle hash is recorded before any decryption | Stated. Any early decryption is reported, and the affected stage is labelled exploratory |

**None of these affects the scoring itself.** `fully_correct` comes from hidden tests run in the fail-closed sandbox, with no model judgement. The threats affect which tasks exist, what their oracles accept and how they are tiered, so they limit what the tier labels and the absolute success rates mean, not whether a given run passed its checks.

## 4. Consequences for the gates

- **G0** is passed by this document's merge: D0 (a) and D5 (the solo protocol in place of named people).
- **G2 (pilot batch)**, redefined for the solo protocol:
  - **Go if,** for the 6 pilot tasks:
    - the validator passes each task (§2.2), with every alternative-triggered revision logged;
    - model-rater agreement within one point is at least 0.6 per factor (the `DESIGN.md` §3 rule);
    - spot check 1 finds no unreasonable obligation;
    - the build effort, recorded as **sessions and session-hours per task** (not elapsed days, which plan pacing stretches), is within about 2× of `STAGE0-PLAN.md` §3.
  - **Otherwise:** revise the protocol or the briefs and rebuild the failing tasks; re-plan the volume (D2); or stop.
- **G3 and G4** are unchanged.

## 5. Order of work (each a reviewed PR; offline; no live run)

1. **This document** (decisions).
2. **H1 and part of H6, the per-run results record (built here).** `live/results_record.py`, with 16 tests. It records:
   - validity, with the harness's reasons;
   - arm, and invocation as two fields: the skill was *called*, and its text was *loaded* (`PILOT-G1-AUDIT.md` A1). Load timing (before the first edit) needs the transcript and comes with the Stage 1 instrumentation;
   - tokens, total prompt tokens and why they are missing when they are;
   - unexpected files, with the placeholders excluded;
   - the SHA-256 of the sealed schedule and of the encrypted bundle (computed from the file).

   It refuses a schedule other than the store's sealed one. Not done yet: scores, which come when Stage 1 scoring is wired in, and use in the live jobs (Stage 1 workflow, H4).
3. **The oracle validator** (§2.2) with its own tests, on a toy task.
4. **The private task repository** (`aqd-private-tasks`, created by the owner) and the task-package layout (H5).
5. **The G2 pilot batch:** 2 tasks per tier through the protocol, then the G2 decision.
6. H2, H3 and H4, before the freeze (G3).
