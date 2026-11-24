# Stage 0 planning: is the Phase 3.3 experiment worth building? (draft, 2026-11-24)

**Status:**
- Planning only. No model call, no secret, no infrastructure.
- Nothing here is approved. Every decision below is the owner's.

**Inputs:**
- `DESIGN.md` §4 to §10;
- `SMOKE-RESULT.md` and `LIVE-PROBE-RESULT.md`;
- `evaluations/phase-3.2/AB-RESULTS.md`;
- `INTEGRATION-DRYRUN.md` §7.

**Why this document exists.** The native harness now works safely on the real service: the probe passed, and SMOKE passed with both arms. That answers "*can* we run the experiment?". It does not answer "*should* we?". Four findings change the plan that `DESIGN.md` assumed, and Stage 0 is large and mostly human work. This document lists the decisions and the work, with go or no-go points before any further model spend.

## 1. What changed since DESIGN.md was written

| # | Finding | Evidence | Consequence |
|---|---|---|---|
| F1 | **The treatment is now skill *availability*, not skill *exposure*** | Phase 3.2 (OpenCode) attached the skill text to the treatment prompt: the agent always saw it. The native harness offers it through `--plugin-dir`, and the agent decides whether to load it. In SMOKE the treatment agent **did not invoke it** (`SMOKE-RESULT.md` §3) | If agents rarely invoke the skill on realistic tasks, the A/B test measures "available but mostly unused". The estimand must be chosen (§2, D1) |
| F2 | **Prompt caching is active and large** | SMOKE: about 28.7 k tokens read from cache and 6.6 k written per run, against 6 input tokens | Token and cost figures depend on cache state and run order. Claude Code documents `DISABLE_PROMPT_CACHING=1` (code.claude.com/docs/en/env-vars), but `cc_adapter.check-env` refuses unlisted variables, so using it is a reviewed harness change (D3) |
| F3 | **Sandbox placeholder files** | 17 zero-byte files in every native run so far (probe; both SMOKE arms; each ran Bash) | They must be excluded before "unexpected files" becomes an outcome (`DESIGN.md` §5 item 2) |
| F4 | **Spending runs on the subscription, not on API dollars** | Both live runs used the subscription, with usage credits off | `DESIGN.md` §10 budgets in dollars. With credits off, the real limit is plan usage: a run that hits a limit fails, and must count as an infrastructure failure, never as a wrong answer (D4) |
| F5 | **Live runs are one-shot and single-environment** | Each live environment allows one deployment; GitHub-hosted jobs stop after 6 hours | Stage 1 has 28 runs of up to 45 minutes each, which does not fit one job. A reviewed multi-dispatch design is needed (§4, H4) |

## 2. Decisions for the owner (in order)

| # | Decision | Options | Recommendation |
|---|---|---|---|
| **D0** | Pursue Phase 3.3 at all? | (a) yes, through the gates below; (b) stop here and publish the probe and SMOKE records as the result of this phase | Decide after reading §3: the binding cost is **human time**, not model usage |
| **D1** | Estimand | (a) **availability**: the skill installed as users get it; invocation is recorded and reported. (b) **exposure**: the skill text always in the treatment context (e.g. a treatment-only system-prompt addition), comparable with Phase 3.2. (c) both, as two treatment arms (about 1.5× the runs) | Choose after the invocation pilot (G1). If invocation is common, (a); if rare, (b), stated plainly as "the skill's content when read", not "the skill as deployed" |
| **D2** | Task volume | 6 per tier (18), or 8 per tier (24) if §6 of `DESIGN.md` recommends 6 confirmatory per tier | Start with **2 per tier (6 tasks)** as the G2 pilot batch. Commit to the full set only after measuring real build effort |
| **D3** | Caching | (a) record only and report tokens with cache split, no cost comparison; (b) `DISABLE_PROMPT_CACHING=1` in both arms (needs the harness change and uses more of the plan); (c) a fixed warm-up per block | **(a) for Stage 1** (correctness is the primary outcome and does not depend on caching). Revisit for any cost claim |
| **D4** | Plan usage | How to treat a run stopped by usage limits | Pre-register it as **infrastructure-invalid**, with at most one rerun per slot (the Phase 3.2 rule). Spread blocks over days. Stop the stage if more than 10% of runs fail this way (`DESIGN.md` §6 infrastructure rule) |
| **D5** | People | Who rates difficulty (2 blind raters), who reviews the oracles (1 human), who does the engineer feasibility runs | Name them before G2. **Without them, Stage 0 cannot finish as designed** |

## 3. Stage 0 work and rough effort

The estimates are uncertain by about 2× either way. The work can be agent-drafted, but **every item marked "human" needs a person**.

| Work | Who | Rough effort |
|---|---|---|
| Build one task: small realistic repository, S and D prompt variants, private oracle (hidden tests, inventory), reference solution, one alternative correct design, 3 or more realistic wrong implementations | agent-drafted, human-reviewed | easy 0.5–1 day; medium 1–2 days; hard 2–4 days |
| Oracle validation per task (reference passes; the alternative design passes; every mutant caught; no hard-coding shortcut) | agent runs, **human** checks | about 1–2 h per task |
| Two blind difficulty ratings per task variant | **2 humans** | about 20 min per rating; about 12 h for 18 tasks × 2 raters |
| Engineer feasibility run (solve within the time budget, from public material only) | **human** | up to 45 min per task |
| Harness changes from `DESIGN.md` §5: scope violation as an outcome; unexpected files as an outcome (with the F3 placeholder exclusion); control-only calibration schedule kind; evidence retention and per-run results file | agent, reviewed | several days, including review cycles |
| Native-specific: private task delivery (`AQD_TASK_ROOT`, `INTEGRATION-DRYRUN.md` §7); estimand D1(b) if chosen; caching D3(b) if chosen; the multi-dispatch live design (H4) | agent, reviewed | several days |
| Freeze (`DESIGN.md` §9) | owner | one review |

**Order of magnitude:**
- **6-task pilot batch:** about 1–2 weeks of combined effort.
- **The full 18 tasks:** about 4–8 weeks, mostly task building and human review.
- **Model usage:** comparatively small. Stage 1 is 28 runs of up to 45 minutes each, spread over several days within plan limits.

## 4. Harness and infrastructure items (offline, each a reviewed PR)

**H1. Unexpected files as an outcome.**
- Exclude the 17 known zero-byte placeholders by name and size.
- Anything else is reported per run.
- A non-empty placeholder stays a failure (as in `check_smoke.py`).

**H2. Scope violation as an outcome** (`DESIGN.md` §5 item 1), with `strictly_correct`.

**H3. Control-only calibration schedule kind,** sealed and tested (`DESIGN.md` §5 item 3).

**H4. Multi-run live dispatch.** The probe and SMOKE jobs run a fixed list in one job, in one single-use environment.

Stage 1 needs:
- blocks dispatched separately, each under 6 hours;
- one owner approval per stage that lists every run ID;
- a server-side record that **each run ID runs at most once** (replacing "one deployment per environment");
- a STOP that blocks all later dispatches.

This is a security-relevant redesign. It gets its own audit and its own mock rehearsal before any authorisation.

**H5. Private task delivery** (`INTEGRATION-DRYRUN.md` §7), so that hidden tests never enter the public repository.

**H6. Retention:** archive each encrypted bundle and record its SHA-256 next to the results (`DESIGN.md` §5 item 4), as was done by hand for the probe and SMOKE.

## 5. Go or no-go gates

| Gate | When | Go if | Otherwise |
|---|---|---|---|
| **G0** | Now | The owner chooses D0 (a) and names the people for D5 | Stop. Phase 3.3's result is: the harness is ready and safe; no effect measured |
| **G1. Invocation pilot** | Before building tasks | On 3–4 existing *public* realistic tasks (the Phase 3.2 NEW-01..04 prompts, treatment arm only, unscored), record whether the agent invokes the skill. Needs a separate written authorisation and the H4-lite single-batch job (≤ 4 runs fits the SMOKE pattern) | Choose D1 (b) or (c), or stop |
| **G2. Pilot batch** | After 2 tasks per tier are built, validated and rated | Build effort within about 2× of §3; rater agreement acceptable; each oracle passes the alternative design | Re-plan the volume (D2) or stop |
| **G3. Freeze** | Before Stage 1 | All of §4 merged with green CI and mock rehearsals; `DESIGN.md` §9 freeze recorded | Do not run Stage 1 |
| **G4. Stage 1 stop rules** | After Stage 1 | `DESIGN.md` §6: hard-task control success below 7 of 8; infrastructure-invalid rate at most 10% | Return to Stage 0 |

## 6. Recommendation

1. **Decide D0 first.** It is mostly a question of whether two raters, one oracle reviewer and one feasibility engineer are available. Without them, Stage 0 cannot be done as designed, and the honest result of Phase 3.3 is: "the native harness is ready and safe; the skill's effect is not yet measured".
2. **If D0 is yes,** do **G1 (the invocation pilot) next.** It is the cheapest step that can change the whole design (F1). It needs only existing public tasks, a small extension of the SMOKE job, and one authorisation.
3. **Keep unscored and scientific evidence separate**, as so far. Probe, SMOKE and the G1 pilot are harness checks. Only Stage 1 and later, after the freeze, produce analysed data.
