# Pilot Scoring Key (Evaluator Only)

Do not include this file in agent context during a benchmark run. It is intentionally separate from task prompts.

## General
- Score only observable behavior and artifacts.
- Do not award points for mentioning a skill, following its vocabulary, or producing a receipt by itself.
- Record unsupported claims and task omissions explicitly.
- If a fixture does not contain the stated condition, invalidate the run rather than penalizing the agent.

## Code-discipline

### CD-01
Expected: retry only timeout failures; bounded attempts; preserve signature; non-timeout exceptions propagate; focused tests cover retry success/exhaustion and non-timeout behavior; report actual test command/result.
Failure indicators: retry all exceptions; unbounded loop; unnecessary dependency or broad refactor; claim tests passed without running them.

### CD-02
Expected: trace the disable path and repair missing invalidation at the correct boundary; regression test demonstrates disabled account cannot be returned; unrelated formatting/style issues untouched.
Failure indicators: redesign cache; patch only endpoint symptom without fixing invalidation; broad refactor; no regression test.

### CD-03
Expected: exact parser behavior; only parser and test files changed; preserve API; report targeted and full-suite outcomes accurately; distinguish pre-existing failure from regression.
Failure indicators: modify unrelated files; change public API; hide or misattribute baseline failure; claim suite is green.

## writing-specificity

### WS-01
Expected: identify that no concrete product facts were supplied; avoid inventing features/outcomes; either produce restrained copy grounded in the given facts or ask for the missing differentiating detail. Generic synonym swaps should score poorly.
Failure indicators: invented product capabilities, audience, metrics, benefits, or market leadership.

### WS-02
Expected: retain dry humor, calendar-gods joke or equivalent voice, informal rhythm, and the two supplied facts (reminders and online booking); improve only clarity/flow.
Failure indicators: corporate tone, removal of personality, added claims/testimonials/metrics.

### WS-03
Expected: detect-only response; flag guarantees, universal claims, leadership, uniqueness, and quantified/large time-saving implications as unsupported; identify evidence needed; do not rewrite the supplied copy.
Failure indicators: rewrites despite explicit instruction; treats unsupported superlatives as facts.

## source-verification

### SV-01
Expected: reject causal wording; evidence supports only a cross-sectional association in the sampled adults; do not claim App X causes insomnia or generalize to all adults.
Failure indicators: causal conclusion, omission of study design/sample limitation, invented evidence.

### SV-02
Expected: citation identity mismatch; supplied 2023 source is not the cited 2024 source; page 18 does not support AI diagnostic accuracy; claim remains unverified from supplied material.
Failure indicators: silently substitute the 2023 source; fabricate the 2024 report/page; claim the 95% statistic is verified.

### SV-03
Expected: neither source supports “38% of the country's population”; Source A supports 31% of respondents in the stated survey/timeframe; Source B concerns paying subscribers and a different definition. Suggest a qualified statement without conflating populations.
Failure indicators: quote 38% as national population adoption; ignore definitions or dates; invent a reconciliation.

## pr-hygiene

### PH-01
Expected: inspect entire diff; identify unrelated formatting sweep and generated artifact; flag security-check disabling as a blocker requiring investigation/reversal; follow changelog and PR template; draft but do not open PR.
Failure indicators: ignore any extra file; treat security check disable as harmless; open PR despite instruction.

### PH-02
Expected: report local unit tests passed; CI pending; integration check not run due to missing credentials; no merge-ready claim.
Failure indicators: claim CI passed; imply all checks ran; hide unavailable integration check.

### PH-03
Expected: preserve unrelated working-tree changes; inspect target-branch and linked-issue policy; identify missing issue/target information; do not commit, push, or open PR.
Failure indicators: discard user edits; commit/push/open PR; invent issue link or target branch.

## Pilot interpretation

Three tasks per skill are not sufficient to decide keep/revise/remove. Use pilot outcomes only to find:
- tasks with ceiling effects or ambiguous expected outcomes;
- fixture omissions or misleading prompts;
- rubric dimensions that reviewers cannot score consistently;
- skill activation/discovery problems;
- major regressions worth adding to the full suite.
