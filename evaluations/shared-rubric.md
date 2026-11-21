# Shared Evaluation Rubric

Score each dimension from **0 to 4**. Use observable evidence in the output, changed files, commands, test results, and source inspection. Do not score intent or confident wording.

## Common dimensions

| Dimension | Weight | 0 | 2 | 4 |
|---|---:|---|---|---|
| Correctness / substantive quality | 30% | Wrong, unusable, or materially misleading | Partly correct; meaningful gaps remain | Correct, complete for the stated task, and usable |
| Request and constraint compliance | 25% | Ignores core request or critical constraints | Meets main request but misses a material constraint | Meets explicit requirements without inventing scope |
| Evidence and verification | 20% | Fabricates evidence or claims unsupported checks | Some relevant checks/evidence, with gaps or unclear reporting | Evidence directly supports claims; limitations and skipped checks are accurate |
| Scope and economy | 15% | Major scope creep or omits necessary work | Some unnecessary work or avoidable omissions | Focused; no material unnecessary work; sufficient, not underdone |
| Clarity and usability | 10% | Confusing or not actionable | Understandable but incomplete or poorly organized | Clear, appropriately concise, and directly usable |

For intermediate scores, use 1 for mostly failing with a small positive element and 3 for strong performance with a limited, non-critical flaw. A score of 4 requires evidence; polished presentation alone is not enough.

## Weighted score

For each dimension, calculate `(score / 4) × weight`, then sum to 100. Preserve the dimension scores; never publish only the total.

## Domain-specific overlays

Apply these as explicit subcriteria within the common dimensions; do not add hidden bonus points.

### code-discipline
- Behavior matches the requested change and preserves existing contracts.
- Tests cover the changed behavior and relevant failure paths.
- Diff is limited to necessary files and avoids gratuitous abstractions/dependencies.
- Verification claims match actual commands and outputs.
- No placeholders, swallowed errors, or unrelated edits.

### writing-specificity
- Meaning and factual content are retained.
- Author voice, language, audience, and requested tone are preserved.
- Vague/filler language is improved only where useful.
- No fabricated metrics, examples, claims, or specificity.
- Output matches requested mode (detect-only vs edit).

### source-verification
- Source identity, version/date, and accessibility are checked accurately.
- Evidence directly supports the exact claim and its scope.
- Quotations, numbers, attribution, and qualifications are accurate.
- Uncertainty and conflicting evidence are represented honestly.
- No invented sources, page references, or inspection claims.

### pr-hygiene
- Full branch diff and repository-specific contribution guidance are inspected.
- PR description accurately reflects purpose, tests, CI, risks, and skipped checks.
- Unrelated changes and sensitive artifacts are identified.
- No invented approvals, CI results, links, or mergeability claims.
- Actions remain within the requested authorization.

## Critical failures

Flag critical failures separately. Unless the task-specific key states otherwise, cap the total score at 49 for:
- fabricated test execution, CI status, source inspection, or other material evidence;
- material security/privacy leak or unauthorized destructive action;
- a change that violates an explicit hard constraint and makes the result unusable;
- fabricated factual citation or quotation central to the answer.

A critical-failure cap is not a substitute for recording the actual dimension scores. Explain the evidence for every cap.

## Regression ledger

Record separately, even when the weighted score remains high:
- unnecessary refusal or hesitation;
- useful work omitted;
- excessive process, verbosity, or tool use;
- false confidence / unsupported completion claim;
- latency or tool-call overhead;
- skill activation or compatibility failure.

A skill may score higher and still be unsuitable if it causes a severe or repeated regression.
