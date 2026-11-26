# G2 pilot batch: build record (2026-11-25)

**Status:**
- **Six task packages were built offline under the solo protocol** (`STAGE0-SOLO.md` §2). Every package passes the oracle validator. That is **mechanical acceptance** under its rules, not proof that each package is a valid research task (review 2026-11-26, finding 4).
- **Corrected 2026-11-26** after an external review (`REVIEW-2026-11-26.md`). The mechanical-mutation numbers in §2 were wrong for the four two-file tasks and have been re-measured with the fixed validator.
- **No model ran on any task.** No live run, no scoring and no Stage 1 dispatch took place.
- **Gate G2 is not yet decided.** It waits on the owner's spot check 1 (§6).

**This is a public record.** It holds only task IDs, the public briefs (`DESIGN.md` §4) and counts. The prompts, hidden tests, obligation lists, solutions and ratings stay in the private repository `aqd-private-tasks` until the runs that use them are complete (`DESIGN.md` §6).

## 1. The batch

- **Seeded draw:** the label `aqd-phase-3.3-g2-pilot-batch-v1`. Seed = the first 16 hex digits of its SHA-256; two IDs per tier are drawn with `random.Random(seed).sample`.
- **Result:** easy E4 and E6; medium M3 and M6; hard H4 and H6. The draw chose which briefs were built. It does not make the constructed tasks representative: the briefs, the implementations and every accepted revision were still chosen (review 2026-11-26, finding 8). Inference concerns this constructed portfolio.
- **Owner's approval:** "Ok build the tasks", 2026-11-25. Everything ran on the owner's Claude subscription, with usage credits off and no API billing.

| Role (`STAGE0-SOLO.md` §2.1) | Sessions | Model |
|---|---|---|
| Builder | 6 | the model under test (Opus) |
| Pre-run reviewer | 6 | Opus |
| Alternative correct design | 6 | **Sonnet**: a model other than the one under test |
| Realistic wrong implementations | 6 | Opus |
| Raters | 12 (two per task) | one Opus and one Sonnet per task |

**Isolation:**
- Each session was a separate cloud session on its own orphan branch. The branch held only what its role may see; the branch layouts are listed in `tools/orchestrate/make_role_branch.py` in the private repository.
- The alternative-design and mutant sessions never had the hidden tests, the reference solution or the ratings.
- The raters never had any solution.

## 2. Results per task

| Task | Brief (public) | Files to change | Hidden checks | Wrong implementations caught | Alternative design | Mechanical mutants killed | Composite rating, Opus / Sonnet (intrinsic, 0–21) | Rated tier |
|---|---|---|---|---|---|---|---|---|
| E4 | Config: environment override for one typed setting | 1 | 14 | 6 of 6 | passes all | 42 of 42 | 4 / 6 | easy |
| E6 | CLI `--dry-run` for an existing command | 1 | 13 | 7 of 7 | passes all | 37 of 37 | 6 / 6 | easy |
| M3 | Add a column with backfill to a migration runner; re-runnable | 2 | 15 | 8 of 8 | passes all | 44 of 51 after revision (reported 51 of 51 before the fix; §3) | 13 / 15 | **hard** |
| M6 | Bulk import with per-row errors and a resumable checkpoint | 2 | 16 | 8 of 8 | passes all | 47 of 49 after revision (reported 49 of 49 before the fix; §3) | 12 / 13 | medium / hard (on the boundary) |
| H4 | Recurring scheduler: exactly-once across workers and DST changes | 2 | 15 | 10 of 10 | passes all | 56 of 60 after revision (reported 60 of 60 before the fix; §3) | 13 / 15 | hard |
| H6 | Cross-process token-bucket rate limiter in SQLite, fair under contention | 2 | 18 | 13 of 13 | passes all | 36 of 40 after revision (reported 40 of 40 before the fix; §3) | 16 / 16 | hard |

**Validator:**
- Every package: the reference passes every check; the pristine project and the shortcut each fail at least one; the source map is clean.
- **In the pinned scoring container (2026-11-26):** all 76 candidates of the six packages give the same per-check results as with the local runner (`REVIEW-2026-11-26.md` §4, finding 4).
- **Checks loosened after an alternative design failed: 0.** No alternative failed a check, so the T7 count is 0 for the whole batch. This covers only that one pathway. Revisions triggered by reviewers, mechanical survivors and realistic mutants (§3) are also adaptations to Claude-generated behaviour, and are listed in the private revision ledger.

**Ratings:**
- **At task level** (6 tasks; the S variant for the intrinsic factors, the D variant for F6): within one point on every factor for 6 of 6 tasks, which meets the `DESIGN.md` §3 threshold of 0.6. Exact agreement is 4 to 6 of 6 per factor.
- **Why task level:** both raters gave every task identical intrinsic scores for S and D, so counting S and D separately, as an earlier version of this record did (12 of 12), double-counts the same judgements (review 2026-11-26, finding 9).
- **Tier agreement:** 5 of 6. The raters' composites put M6 on different sides of the medium/hard boundary. Consensus and boundary adjudication follow the rule fixed in `REVIEW-2026-11-26.md` §3, applied before any tier is used.
- **What this agreement means:** it is model-rater agreement (T2), not inter-human reliability.
- **F6 (requirement discovery):** 0 for every S variant, and 1–3 for every D variant. The rubric counts F6 0–1 as "specified", so a D variant rated 1 (one rater, E6) is not yet "discovered". Each D variant's classification is resolved by consensus before the draw. One that does not reach F6 ≥ 2 is rebuilt or relabelled (review 2026-11-26, finding 10).

## 3. What the process caught

**The pre-run reviewers** asked for a revision of 4 of the 6 packages before any alternative existed:

| Problem | Tasks |
|---|---|
| Hidden-check values copied from the prompt's own example, so a solution that hard-codes the example passed those checks | H4, H6 |
| An obligation tested but not stated in S, or stated only in code or docs | E4, H4 |
| A check over-strict for the D variant (its D source did not state what it tested) | M6 |
| D wording that contradicted a check | H6 |

**Mechanical mutation, before any alternative existed:**
- In E4 and E6, the mutable file also holds working code that the task does not touch: the validation of other settings, and the other commands. No hidden check protected it, so a solution that broke it would have scored as correct.
- Regression checks were added. Their source is a new sentence in both prompts asking that the untouched code keep its current behaviour.

**Realistic wrong implementations in E6 and H6** each passed every check once. A check was added, or extended, for the obligation each one broke. These were mutants, not alternative designs, so they do not count under T7. The H6 fix changed only the hidden test; the reference is unchanged, so the earlier mechanical-mutation result (40 of 40) still holds.

**Corrected mechanical-mutation results (2026-11-26).** The earlier figures for the four two-file tasks came from the validator bug (`REVIEW-2026-11-26.md`, finding 1). Re-measured, they have 8, 6, 14 and 10 real survivors, several of them true gaps. They were routed to the builders under `STAGE0-SOLO.md` §2.6: 10 checks were added or extended, and the rest were explained as equivalent or escalated. The packages were then re-validated and hash-bound (`REVIEW-2026-11-26.md` §2). The hidden-check counts in the table are now M6 16, H4 15 (3 extended) and H6 18.

**Session audit:**
- **What was audited:** every session's transcript (6 builders and 36 role sessions).
- **What was looked for:** Skill tool use, the skill's text or sentinels, and reads of the skill directory, of the public repository or of other roles' branches.
- **Result:** none found. One builder searched for `.claude/skills/*/SKILL.md` right after opening its pull request (a harness convention); no such file exists in the private repository.
- **Assurance:** the audit pages that came back inline were transcribed by the auditing agent rather than saved verbatim (about two thirds of the role pages), which weakens this assurance somewhat.

## 4. Effort

- **Elapsed:** about 3 hours, 18:43 to about 21:40 UTC. The six builds ran in parallel.
- **Builder sessions:** 6 to 35 minutes of model time each, before revisions. The hard task H6 took the longest.
- **Revision rounds:** 0 for M3; 1 each for E4, M6 and H4; 2 each for E6 and H6.
- **Role sessions:** about 5 to 15 minutes each.
- **The owner's time so far:** none beyond approval. Spot check 1 takes about 1.5 hours.
- **A failed first launch:** the six builder sessions were given a shortened commit hash the cloud could not resolve. They stopped at the clone step with 0 tokens used and were archived.

This is far below the human-effort estimate in `STAGE0-PLAN.md` §3 (0.5–4 days per task). The G2 effort criterion therefore holds. Model build effort is not the same thing as quality, which is why the validator, the reviews and the spot check exist.

## 5. Findings and deviations, stated plainly

1. **The medium tier is under-filled.**
   - The ratings put M3 in hard and M6 on the medium/hard boundary. Under `DESIGN.md` §3 the rated composite, not the brief, sets the tier, so this batch is 2 easy, 0–1 medium and 3–4 hard.
   - Medium tasks need to be briefed or built smaller. This is the main G2 finding for D2.
   - M6's tier also depends on how the consensus rule rounds a half (11 to 14), which `REVIEW-2026-11-26.md` §3 does not fix. `D2-REBRIEF.md` proposes a fix and the re-brief of the remaining 18 tasks.
2. **The projects are small:** 228–570 lines of Python each.
   - Their difficulty comes from interacting requirements, concurrency and state, not from size, as the rubric intends.
   - Whether 45 minutes is enough for the hard tasks is not known until Stage 1 (T4).
3. **Sessions were not plugin-free.**
   - `STAGE0-SOLO.md` §2.1 asks for sessions with no plugins or personal skills. The cloud environment loads account-level plugins that have nothing to do with this study.
   - The audit therefore checked specifically for exposure to the skill under test, and found none. The protocol text should say "no exposure to the skill under test".
4. **The orchestrator shaped two oracles.**
   - The orchestrating session (which knows the skill and the hypothesis) asked for regression coverage in E4 and E6, from mechanical-mutation survivors.
   - No model run on any task existed at that point, so no outcome information was involved. It is still author influence, under T1.
5. **The regression sentence in the E4 and E6 prompts** (untouched code keeps its behaviour) is close to scope wording (`DESIGN.md` §4 keeps scope advice out of prompts). It is identical in both arms, but it may narrow the room the skill has to help on those two tasks.
6. **E6's alternative design, mutants and ratings predate its last one-line prompt addition** (the H13 obligation). The alternative still passes every check, but the ratings are against the earlier prompt.
7. **Two reviewers (M3 and H4) wrote scratch solutions** while they had the hidden tests, to check feasibility. These were not delivered and not used, but it goes beyond the reviewer role.
8. **Child sessions opened draft pull requests in the private repository** (their harness default). None was merged; packages are assembled on `main` by the orchestrator.
9. **Spot check 1 was done by a model.**
   - The owner had GPT review the 46 obligations and adopted its verdict, so the protocol's one human judgement is a cross-provider model check endorsed by the owner.
   - GPT read the private repository through the owner's GitHub connector. It reports reading only the spot-check sheet, the S prompts and two project files.
   - Its reverse question (does every prompt rule have a check?) found 3 rules in one hard task with no hidden or baseline check. They were routed to that task's builder (`STAGE0-SOLO.md` §2.6, owner decision), with hidden checks only and no prompt change.
   - The same audit, and a GPT alternative design and wrong implementations per task, are planned for all six pilot tasks. The model-family bias they address is T1/T3.

## 6. Gate G2 (`STAGE0-SOLO.md` §4)

| Criterion | Status |
|---|---|
| Validator passes each task, with every alternative-triggered revision logged | **met, re-measured 2026-11-26** with the fixed validator (§2): 6 of 6, with 0 such revisions. Mechanical survivors are routed to the builders |
| Model-rater agreement within one point ≥ 0.6 per factor | **met**: 6 of 6 tasks on every factor (task level). Tier agreement 5 of 6 |
| Spot check 1 finds no unreasonable obligation | **met (2026-11-26):** 46 of 46 obligations of E6, M3 and H6 accepted, 0 rejected (seeded draw `aqd-phase-3.3-g2-spot-check-1-v1`). The review was done by another provider's model (GPT) at the owner's request and adopted by the owner as their own decision, so it is a cross-provider model check, not an independent human reading (§5 item 9) |
| Build effort within about 2× of `STAGE0-PLAN.md` §3 | **met** (§4) |

**Status:** all four criteria are met. The go decision is the owner's. Whatever the spot check finds, the tier finding (§5 item 1) means the remaining 18 tasks should be briefed with the medium tier in mind before they are built.
