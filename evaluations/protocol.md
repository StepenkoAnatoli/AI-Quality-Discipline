# Evaluation Protocol

## 1. Research question

For each canonical skill, does enabling that skill improve task outcomes compared with the same agent configuration without that skill, without introducing unacceptable regressions in correctness, usefulness, time, or process overhead?

Evaluate each skill independently. Do not bundle all four skills into one treatment: doing so would make attribution impossible.

## 2. Conditions

- **Control:** the target agent receives the task and ordinary repository/project context, but not the skill under test or a substitute instruction that restates it.
- **Treatment:** identical setup, with only the relevant canonical skill made available and discoverable.
- Keep model/version, agent product and version, system/developer instructions where controllable, tools, permissions, repository snapshot, network access, temperature/sampling settings, and task wording identical.
- Record any unavoidable differences. If the skill fails to load, record an activation failure; do not silently rerun it as though treatment succeeded.
- Start each run from a clean, identical task state. Do not carry edits, notes, or conversation history from one condition into another.

## 3. Assignment and blinding

- Randomize or counterbalance condition order for each task.
- Use fresh sessions for every run.
- Give outputs neutral IDs. Reviewers should not see condition, skill name, run order, or model self-report while scoring.
- Prefer two independent reviewers. Resolve material scoring disagreements with a documented adjudication note.
- If full blinding is impossible (for example, a receipt explicitly names a workflow), disclose that limitation.

## 4. Sample size

- **Pilot:** three tasks per skill, one run per condition. Used to calibrate task difficulty and scoring only.
- **Full evaluation:** at least 10 representative tasks per skill, each run in both conditions; target three independent runs per condition where practical.
- Report exact denominators. Do not treat retries, tool failures, or incomplete runs as successful samples.
- A small pilot is not powered to establish general effectiveness.

## 5. Scoring

Use `shared-rubric.md`. Score each dimension from 0–4 and convert using its weight. Apply the skill-specific criteria and critical-failure caps in `pilot/scoring-key.md` or the corresponding full-suite key.

Score the artifact and observable execution evidence, not whether the model mentions the skill or repeats its language. Do not reward a quality receipt unless its claims are accurate and supported.

Record:
- correctness and task completion;
- explicit constraint compliance;
- evidence and verification quality;
- scope control / unnecessary work;
- clarity and usability;
- task-specific dimensions such as voice preservation, claim support, or full-diff review;
- regressions: refusal/hesitation, omitted useful work, over-processing, false confidence, latency, and tool-call overhead.

## 6. Run record

For every run record:
- task ID and immutable task-set revision/commit;
- anonymized run ID and condition (kept separately from blinded reviewer packet);
- date/time and operator;
- model name/version and agent product/version/surface;
- skill name, exact skill revision/hash, and activation result (treatment only);
- repository/fixture commit and clean-start confirmation;
- tool availability, permissions, network access, and relevant configuration;
- start/end time or duration, tool-call count where available;
- complete prompt, transcript, final artifact/diff, test output, and errors;
- score by dimension, critical failures, reviewer notes, and adjudication.

Never store secrets, personal data, or private production code in public benchmark artifacts.

## 7. Analysis

For each skill report:
- task-level and run-level scores for both conditions;
- paired treatment-minus-control differences by task;
- mean, median, range, and distribution—not only a single aggregate;
- task completion and critical-failure rates;
- regression counts and severity;
- activation/tool failures and excluded samples with reasons;
- reviewer agreement or disagreement;
- time and tool overhead where measurable.

Do not pool unlike skills into one headline score. Do not compare raw scores across different models or environments as though conditions were controlled.

## 8. Decision rules

- **Keep:** repeatable, practically meaningful paired improvement across representative tasks, with no unacceptable critical regression or overhead.
- **Revise:** evidence of benefit is mixed or concentrated in a narrow task type, or the skill causes fixable over-processing / omissions.
- **Remove:** no meaningful improvement after a sufficiently representative evaluation, or persistent harmful regressions / maintenance burden.

Set practical thresholds before full runs. A statistical significance claim requires an appropriate analysis and sufficient sample size; do not infer it from a handful of runs.

## 9. Validity threats

Document ceiling effects, task leakage, task-set overfitting, model updates, hidden agent defaults, context-window pressure, evaluator bias, nondeterminism, external service changes, and skill activation uncertainty. Refresh tasks periodically while preserving versioned historical suites.

## 10. Publication

Publish methodology, task prompts, scoring keys (after the evaluation where concealment is needed), anonymized artifacts where licensing permits, raw scores, exclusions, environment details, and limitations. A passing validator or a high task score does not prove general quality.
