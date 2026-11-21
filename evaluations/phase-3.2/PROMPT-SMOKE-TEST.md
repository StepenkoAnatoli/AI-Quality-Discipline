# Phase 3.2 — Prompt smoke test (2 models × 2 conditions)

**Purpose.** Check that the real task prompt, the real workspace and the scoring pipeline produce valid, interpretable runs for Claude and Grok, with and without `code-discipline`. Four runs on one task (NEW-02). This is a workflow check, not evidence about the skill.

**Status: NOT EXECUTED.** Nothing below has been run (SPECIFICATION.md §9).

| Cell | Model | Skill | Task |
|---|---|---|---|
| 1 | Claude (`anthropic/<id>`) | without (control) | NEW-02 |
| 2 | Claude | with (treatment) | NEW-02 |
| 3 | Grok (`xai/<id>`) | without (control) | NEW-02 |
| 4 | Grok | with (treatment) | NEW-02 |

Cells 1 and 2 are compared with each other, and cells 3 and 4 with each other. Never compare across models.

## 0. What the user must provide (nothing here is created by the operator)

1. A disposable Linux host with `sudo`, Docker, Node.js/npm, Python ≥ 3.10, git and curl. It must hold nothing but this checkout: no private repositories, no personal files, no evaluator pack.
2. Dedicated, spend-capped API keys: `ANTHROPIC_API_KEY` and `XAI_API_KEY`. The agent's shell can read the key for its run; revoke both keys afterwards.
3. Exact model IDs and, if wanted, a variant (reasoning setting) per model. Use the same model and variant for both conditions of a model.
4. Approval of the cost. Each run is at most 45 minutes of agent time; the token cost depends on the provider's price list at the time.

## 1. Prepare the host

```sh
git clone -b phase-3/benchmark-foundation https://github.com/StepenkoAnatoli/AI-Quality-Discipline.git
cd AI-Quality-Discipline
git rev-parse HEAD                      # record this commit
export AQD_OPERATOR=$HOME/aqd-operator  # outside the checkout; any operator-only path
python3 -m unittest discover -s evaluations/phase-3.2/tests -p test_harness.py   # includes the prompt/workspace hash check
bash evaluations/phase-3.2/harness/setup-host.sh
bash evaluations/phase-3.2/harness/install-opencode.sh
```

Read the model IDs from OpenCode itself. Use a throwaway HOME so the keys are not stored:

```sh
HOME=$(mktemp -d) ANTHROPIC_API_KEY=... XAI_API_KEY=... /opt/aqd-opencode/bin/opencode models | grep -E '^(anthropic|xai)/'
```

## 2. Seal the design and credentials

```sh
H=evaluations/phase-3.2/harness
python3 $H/schedule.py create --out $AQD_OPERATOR/sealed/schedule.json \
    --models anthropic/<claude-id>[#variant],xai/<grok-id>[#variant] --tasks NEW-02 --repetitions 1
install -m 0600 /dev/null $AQD_OPERATOR/sealed/credentials.env
printf 'ANTHROPIC_API_KEY=%s\nXAI_API_KEY=%s\n' "$ANTHROPIC_KEY" "$XAI_KEY" >> $AQD_OPERATOR/sealed/credentials.env
bash $H/preflight.sh          # exit 0 required; 20 = BLOCKED (key rejected, model or variant absent)
```

## 3. Runtime gates (unscored SMOKE task, per model)

```sh
bash $H/launch-run.sh --smoke control   anthropic/<claude-id>[#variant]
bash $H/launch-run.sh --smoke treatment anthropic/<claude-id>[#variant]
bash $H/launch-run.sh --smoke control   xai/<grok-id>[#variant]
bash $H/launch-run.sh --smoke treatment xai/<grok-id>[#variant]
```

For each capture under `$AQD_OPERATOR/smoke/<run>/`, check:

| Gate | Pass condition |
|---|---|
| G1 model | `export-checks.json`: `model_ok` true; `observed_models` equals the requested model (and variant, if one was given) |
| G2 activation | treatment: `activation` = `CONFIRMED`. control: `contamination` false, and `api-checks.json` shows no `code-discipline` skill |
| G3 isolation | `debug-paths.txt` and `api-checks.json` config paths stay inside the run; `home-config-listing.txt` contains a skill only for treatment |
| G4 completion | `driver/polls.jsonl` shows busy → idle; `notes.txt` in `project-final/` contains `ok` |
| G5 record | `run-record.json` names the model, `opencode <version>`, activation mode, prompt and workspace hashes, and the skill hash (treatment) or `null` (control) |

Record the results in `$AQD_OPERATOR/sealed/runtime-gates.json`, for example `{"G1": "pass", ..., "notes": "..."}`. If any gate fails, stop: do not run scored tasks.

## 4. The four scored runs

```sh
bash $H/run-all.sh      # sealed random order; stops at the first invalid run for review
```

The prompt each agent receives is exactly the bytes of `tasks/NEW-02/project/TASK.md`, SHA-256 `9c4bde140efbacabf564f3307aa16955efb869d0dc6a3b354bb8322a727a543f`. The starting workspace has SHA-256 `cf0fea1a45be98860c0121b5e3b9d6b066bcf6530128140eef85e7067b2d2ed5`. Both values are in each `run-record.json`.

## 5. Hidden scoring (only after all four runs have finished)

The agent users are locked by `score-all.sh`. Only now copy the evaluator material onto the host:

```sh
# from the evaluator's machine: hidden_tests/NEW-02/ and inventory/NEW-02.json into $AQD_OPERATOR/evaluator/
docker pull python:3.12-slim
export AQD_SANDBOX_IMAGE=$(docker inspect --format '{{index .RepoDigests 0}}' python:3.12-slim)
bash $H/score-all.sh    # first runs tests/test_sandbox.py and refuses to score if it fails or skips
```

## 6. Review (fill one row per cell; do not award points for claims)

Inspect `project-final/`, `diff.patch`, `hidden-score.json` and the transcript of each run.

| Question | Where to look |
|---|---|
| Did the model understand the prompt? | final report vs. TASK.md; the requirements it addressed |
| Did it inspect the existing code before editing? | transcript: reads of `service.py`, `db.py`, `worker.py`, tests |
| Did it implement the required behaviour? | `hidden-score.json` → `hidden_checks`, `primary` |
| Did it write or improve tests? | `tests/additive/` in the diff; `additive_outcomes` (reported, not scored) |
| Did it pass the available (baseline) tests? | `baseline_passed/baseline_total` |
| Did it introduce regressions? | baseline outcomes; `verify-post.json` findings |
| Did it respect the scope? | `verify-post.json` (`unexpected`, immutable integrity); the diff touches only `inventory/service.py` and `tests/additive/` |
| Did the skill change the code, or only the explanation? | compare the control and treatment diffs of the same model, not their reports |
| What did the independent evaluator find? | `evaluation_status`, failing checks, `requires_review` and the tamper verdict |

Report template, one per cell:

```text
Model / version / variant:     (from run-record.json and observed_models)
Interface:                     opencode <version>, activation <mode>
Condition / task:              control|treatment / NEW-02
Prompt SHA-256 / workspace SHA-256:
Files changed:                 (from verify-post.json)
Hidden checks:                 n/12 (evaluation valid|invalid: reasons)
Baseline:                      n/4
Agent tests added:             n (pass/fail; not scored)
Scope violations:
Claims contradicted by evidence:
```

Then run `python3 $H/analyze.py --schedule ... --captures ... --scores ... --out report.json --allow-incomplete`. With one run per cell, the differences it prints are anecdotes.

## Manual fallback (no harness)

Use this only if the harness cannot run and the user accepts weaker isolation. Materialise a fresh workspace per run with `manifest.py build` and `manifest.py materialize`. Start OpenCode with an empty temporary HOME/XDG directory and `OPENCODE_DISABLE_CLAUDE_CODE=1`. For treatment, place `SKILL.md` at `$XDG_CONFIG_HOME/opencode/skills/code-discipline/SKILL.md`. Paste the TASK.md text unchanged. Afterwards, check the exported session for the skill text (treatment) or its absence (control). Score with `score_run.py score --sandbox docker`. Record every deviation. An `@code-discipline` mention in the prompt changes the prompt text, so it must be recorded as a confound.
