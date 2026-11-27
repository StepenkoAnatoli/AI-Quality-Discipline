# Findings at a0b92ac

Historical scope: `a0b92acc02e1c5fbe94ffaa04159288fa72cea3a`, PR #16.
Read the [provenance and current-status notice](README.md) first. Locations
below refer to that commit. Findings retain the original numbering used in
[the author's response](../../REVIEW-2026-11-26.md). This is a condensed
record of the external review, not a re-review of the fixes.

## 1. Mechanical mutation scores the wrong multi-file program

**Blocking; CONFIRMED and reproduced.** `oracle/validate_task.py:157-170,
289-309, 373-375`.

Each generated mutation contains one reference file, but `v.score(files=files)`
lays it over the pristine project. Other mutable files remain unsolved and
can kill the candidate independently of the mutation. The two-file toy
reproduction reports 9/9 kills although one of those mutants passes every
check on the complete reference. An unmutated single reference file also
fails on the incomplete overlay. Multi-file G2 counts are unreliable until
recomputed; this does not imply every reported kill was false.

**Fix:** apply each mutation to the complete reference; require an unmutated
overlay control to pass; add a multi-file test and regenerate package reports.

## 2. Source-only review substitutes for a passing alternative

**Blocking; CONFIRMED.** `STAGE0-SOLO.md` section 2.2(3);
`oracle/validate_task.py:331-350`; the test named
`test_an_alternative_failing_a_check_needs_a_source_only_review`.

The original test replaces the only alternative with the known-wrong
remainder-last mutant, then obtains `valid: true` by adding a review flag.
The validator checks a finding string, a session identifier and
`saw_candidate_code: false`, not review provenance or blindness to results.
It therefore permits a package without an independently constructed passing
solution, weakening DESIGN section 4's over-strictness safeguard.

**Fix:** retain source-only review for disputes, but require at least one
independent alternative to pass all checks. Bind review evidence to source
and check versions; retain failed attempts and prohibit test-feedback repair.

## 3. The per-run record is not yet a Stage 1 accounting contract

**Blocking before live Stage 1; CONFIRMED.** `live/results_record.py:103-182`;
`STAGE0-PLAN.md` section 4; `STAGE0-SOLO.md` section 5(2).

The record lacks scoring, strictly-correct outcomes, load timing, typed
infrastructure/agent causes, block invalidation, attempt/replacement links
and explicit cancellation disposition. A completed run can remain valid in
the record when D4 invalidates its block; an absent capture cannot distinguish
cancellation from lost evidence. Invalidity alone mixes infrastructure with
scope violations. Much of this was explicitly deferred work, not a newly
introduced regression. Separately, missing output tokens yield a null missing
reason when the prompt-token components exist; that defect was reproduced.

**Fix:** define a versioned record and slot-resolution contract, with complete
attempt/block accounting and separate prompt/total-token completeness. Rehearse
cancellation, replacement, timeout and scope cases end to end before dispatch.

## 4. Mechanical acceptance is not semantic oracle validity

**Major; CONFIRMED limits.** `oracle/validate_task.py` source-map and candidate
gates; `phase-3.2/harness/score_run.py:181-237,361-397`.

The toy accepts a known uncovered `parts == 1` defect. Quote existence does
not establish entailment of assertions. Three copies of one broken mutant
can satisfy the count, and import errors count as caught checks. A reference
can use an unstated requirement unavailable to a public-only solver.
A passing reference rules out literal inability to pass those local tests,
but not public-material/time-budget infeasibility. LocalRunner acceptance
also does not establish behavior under the live read-only, resource-limited
Docker environment.

**Fix:** distinguish mechanical acceptance, semantic review and public-only
feasibility; deduplicate and defect-label negatives; inspect mappings and
validate accepted solutions in the pinned scoring container.

## 5. Shared blind spots can bias the treatment difference

**Major; CONFIRMED omission, SPECULATIVE realized direction.**
`STAGE0-SOLO.md` T1/T3 and the paragraph following T8.

The assurance that the threats principally limit labels and absolute success
is too narrow. If the model-built oracle misses untreated-Claude defects
that the skill prevents, benefit is attenuated. If it misses skill-induced
errors, benefit is inflated. Mechanical execution still measures an outcome
whose definition embeds model judgment.

**Fix:** add independently sourced defect checklists and held-out inputs;
sample obligation-to-assertion mappings in owner review; state differential
outcome misclassification explicitly.

## 6. The informed orchestrator shapes oracle construction

**Major; CONFIRMED influence, SPECULATIVE effect.** `G2-BUILD.md` section 3
and section 5(4).

The skill/hypothesis-aware orchestrator selected regression gaps for repair
and assembled packages. Outcome blindness does not remove this pathway:
emphasizing regression defects can favor a skill teaching regression review.
That can increase the treatment advantage; adding reminders to both prompts
can reduce it. Same-family bias does not fully describe this influence.

**Fix:** use a fixed survivor-routing rule and skill-blind substantive review;
log every disposition, with owner-approved exceptions against a coverage matrix.

## 7. Shared prompt coaching can distort the interaction

**Major; CONFIRMED overlap, SPECULATIVE effect.** `DESIGN.md` section 4;
`G2-BUILD.md` section 3 and section 5(5).

E4/E6 gained explicit preservation wording after regression gaps were found.
Identical wording across arms can still supply guidance the skill would add.
It may suppress the easy-tier treatment difference and inflate hard-minus-easy
when harder tasks lack comparable reminders. Behavioral preservation can be
a legitimate requirement; selective introduction is the methodological issue.

**Fix:** adopt one prospective compatibility-wording policy across tiers,
audit coaching/intervention overlap and re-rate modified tasks.

## 8. Random draws do not remove construction selection

**Major; CONFIRMED limitation, SPECULATIVE effect.** `G2-BUILD.md` sections
1-3; `DESIGN.md` section 11; `STAGE0-SOLO.md` T7.

The briefs, implementations, revisions and retained versions were chosen.
Sampling their IDs does not make the pool representative. Zero
alternative-triggered revisions excludes documented reviewer-, mutant- and
mechanical-survivor-triggered changes. Skill-aligned selection can inflate
benefit; selection of Claude-familiar tasks can create ceilings and attenuate
it. Successful-construction filtering further narrows the population.

**Fix:** retain the candidate/revision/rejection ledger for every pathway;
precommit the frame and seed; restrict inference to the constructed portfolio.

## 9. Within-one agreement does not establish tier reliability

**Major; CONFIRMED.** `G2-BUILD.md` sections 2,5(1),6;
`phase-3.2/harness/difficulty.py:318-327`.

The 1.0 figure is within-one agreement, while exact agreement is as low as
8/12. Factor differences can accumulate into a tier disagreement. S/D pairs
repeat essentially the same intrinsic task, so twelve variant pairs are not
twelve independent tasks. Correlated raters can share wrong interpretations.
The medium-underfilled result is conditional on ratings, not empirical solver
difficulty. Raw factors, final consensus and a fixed boundary rule were absent
from the public record; the code allowed consensus anywhere in factor ranges.
Random misclassification generally blurs interaction; systematic classification
can shift it either way.

**Fix:** report six task clusters, factor gaps and tier agreement; predeclare
adjudication and do not select consensus values to fill tier quotas.

## 10. D labels do not guarantee discovered classifications

**Major; CONFIRMED.** `G2-BUILD.md` section 2 F6 bullet;
`DESIGN.md` sections 3-4.

D scores of 1-3 were described as intended, but the rubric defines 0-1 as
specified and 2-3 as discovered. Half S/half D therefore need not balance the
actual discovery levels. Rating-based analysis can have imbalanced cells;
label-based analysis misclassifies some tasks.

**Fix:** resolve F6 before allocation; rebuild/relabel variants or revise the
allocation and estimand. Never equate D with discovered silently.

## 11. Difficulty is confounded with content and familiarity

**Major; CONFIRMED design limit, SPECULATIVE bias.** `DESIGN.md` sections 3-4;
`STAGE0-SOLO.md` T1/T4; `G2-BUILD.md` section 2.

Easy tasks emphasize local config/CLI behavior; hard tasks emphasize concurrency,
persistence and recovery. Larger benefit may be defect-class specificity rather
than difficulty moderation. Ratings do not establish general engineering or
observed Claude difficulty. Untimed alternatives with obligation lists cannot
validate discovery/time feasibility. Skill affinity can inflate the interaction;
familiarity, floors and misclassification can suppress or reverse it.

**Fix:** claim association across rated strata; add matched task families and
public-only, budgeted feasibility checks on calibration material.

## 12. G2 claims lack a consistent, bound final snapshot

**Major; CONFIRMED evidence gaps, private counts unverified.**
`G2-BUILD.md` sections 3-6.

E6 ratings/alternative/mutants predated a prompt addition. H6 mutation results
were carried forward because the reference was unchanged although tests changed;
reference identity alone cannot bind outcomes. Most role audit pages were
transcribed rather than preserved verbatim. Public package/report hashes and
an executable agreement calculation were missing. Six of six valid meant
reported mechanical acceptance under the defective validator, not six
independently established research-valid tasks.

**Fix:** bind final package, prompt, oracle, rating, validator/options and raw
audit artifacts in a manifest; rerun/re-rate affected items; retain unavailable
original transcripts as evidence gaps.

## 13. Symmetric block invalidation need not be ignorable

**Major; CONFIRMED unsupported assurance, SPECULATIVE direction.**
`STAGE0-SOLO.md` D4.

Equal arm counts removed do not establish unbiased selection when block failure
depends on treatment usage, difficulty and behavior. Removing expensive helpful
treatment can depress benefit; removing expensive harmful treatment can inflate
it. Replacements occur later conditional on original failures.

**Fix:** retain attempts/dispositions; fix replacement selection and the >10%
denominator, including cancellations; reserve headroom where possible; report
original-block sensitivity even after successful replacements. Describe symmetric
handling, not arm-neutral missingness.

## 14. Complete-case token ratios can hide overhead

**Major; CONFIRMED policy problem, SPECULATIVE magnitude.**
`STAGE0-SOLO.md` D3; `DESIGN.md` sections 7-8.

Timeouts lose final usage and leave token ratios. If treatment times out more,
its surviving cheaper runs can bias overhead downward. Counts alone do not repair
the ratio. Unweighted tokens replace money while retaining 1.5: this is a new
endpoint, not a cost-equivalent threshold. Auxiliary-call coverage was unverified.

**Fix:** collect deduplicated incremental usage or report bounds/inconclusive
overhead under consequential censoring; ratify 1.5 as token volume; reconcile
final and per-model usage before scientific runs.

## 15. Stop-rule probabilities ignore task clustering

**Major; CONFIRMED.** `DESIGN.md` section 6; `power_sim.py:115-118`.

The binomial calculation assumes eight independent runs with one common success
probability, while Stage 1 repeats two tasks four times each. If 60% of tasks
are always solved and 40% never solved, mean success is 0.60, but >=7/8 occurs
when both drawn tasks are solvable: 36%, not approximately 11%.

**Fix:** evaluate the actual clustered design under heterogeneity/dependence;
use those sensitivities or distribute controls across more tasks.

## 16. D2 supports coarse estimation, not ordinary-size interaction claims

**Major; CONFIRMED.** `DESIGN.md` sections 6-8; `STAGE0-SOLO.md` D2.

Six task differences give five degrees of freedom per tier. The documented
simulations show about +/-0.42-0.47 half-widths, 14-16% benefit detection at
nominal +0.20 and 7-8% interaction detection. The design can provide coarse
selected-portfolio estimates, not reliable moderate benefit/equivalence or
interaction conclusions. More tasks do not necessarily reduce systematic bias.
D2 follows DESIGN's estimation recommendation; stronger accuracy/confirmation
claims would be the inconsistency.

**Fix:** freeze estimation purpose and main contrast; prohibit default-on or
general difficulty claims from inconclusive evidence. Power any later confirmation
against the finalized design, including missingness and availability.

## 17. Before-first-edit timing ignores shell writes

**Major; CONFIRMED and reproduced.** `live/inspect_invocation.py:27,62-82`;
`PILOT-G1-RESULT.md` section 8.

The checker recognizes named editing tools but not Bash. A transcript describing
`Bash overwrite -> skill load -> Edit` returns before-first-edit true. The current
at-review G1 record had already resolved its earlier called/loaded ambiguity;
the stronger timing claim remained unsupported by this helper. Actual impact on
G1 cannot be determined without its private transcripts.

**Fix:** observe workspace changes around tools, including Bash, or report unknown
when writes cannot be excluded; otherwise use an explicitly narrower named-edit
field and qualify G1.

## Original first three changes

1. Repair reference-overlay mutation, restore a passing independent alternative,
   and regenerate bound reports for all six packages.
2. Standardize construction/revision rules, preserve raw evidence, resolve tiers
   and F6 before allocation, re-rate changes and complete final-snapshot owner checks.
3. Complete and rehearse Stage 1 scoring/timing/block/usage accounting, revise the
   clustered gate calculation and preserve estimation-only interpretation.

These priorities describe the original review. Consult the existing response
for subsequent work and owner decisions; this archive does not reset them.
