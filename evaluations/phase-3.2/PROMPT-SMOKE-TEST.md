# Phase 3.2 — Smoke test (2 models × 2 conditions = 4 agent runs)

**Purpose.** Check that the real task prompt, the real workspace and the scoring pipeline produce valid, interpretable runs for Claude and Grok, with and without `code-discipline`. Four runs on one task (NEW-02). This is a workflow check. With one run per cell it is **not** evidence about the skill.

**Status: NOT EXECUTED.** Nothing below has been run on Linux and no prompt has been sent (SPECIFICATION.md §9). Grok is **BLOCKED** until the user supplies an `XAI_API_KEY` and confirms the model (see Models).

| Cell | Model reference | Condition | Task |
|---|---|---|---|
| 1 | `anthropic/claude-opus-5-5#medium` | without skill (control) | NEW-02 |
| 2 | `anthropic/claude-opus-5-5#medium` | with skill (treatment) | NEW-02 |
| 3 | `xai/grok-4.7#medium` (candidate; BLOCKED) | without skill (control) | NEW-02 |
| 4 | `xai/grok-4.7#medium` (candidate; BLOCKED) | with skill (treatment) | NEW-02 |

Cells 1 and 2 are compared with each other, and cells 3 and 4 with each other. Never compare across models.

## Models

| | Claude | Grok |
|---|---|---|
| Interface | OpenCode CLI 2.3.2 (`@opencode/cli`, the version the operator's existing installation runs and the harness pins) | same |
| Provider | `anthropic` | `xai` |
| Model ID | `claude-opus-5-5` (Claude Opus 5.5) | candidate `grok-4.7` (Grok 4.7); in the catalog, not callable without a key |
| Variant (thinking effort) | `medium` | `medium` (catalog offers `low, medium, high, xhigh`) |
| Model reference for `schedule.py` | `anthropic/claude-opus-5-5#medium` | `xai/grok-4.7#medium` once confirmed |
| Evidence | 2026-11-21, operator PC: `opencode-cli.exe models` (v2.3.2) lists `anthropic/claude-opus-5-5`; the 2.3.2 server lists its variants as `low, medium, high, xhigh, max` | the operator's installation lists no `xai` provider and no Grok model. With a placeholder `XAI_API_KEY` in a throwaway HOME, 2.3.2 lists `xai/grok-4.7`, `grok-4.6`, `grok-4.5`, `grok-4.3`, `grok-4.20-0309-reasoning`, `grok-4.20-0309-non-reasoning`, `grok-4.20-multi-agent-0309` (no request sent) |
| Status | verified in the operator's catalog; `preflight.sh` re-checks model and variant on the run host (exit 20 if absent) | **BLOCKED**: needs a user-provided `XAI_API_KEY` and the user's confirmation of the model; `preflight.sh` then checks it on the run host |

Use the same reference for both conditions of a model. Nobody but the user creates keys, accounts or billing settings.

## Model calls

**Exactly four agent runs, one per cell.** Each run is one agent session; inside it the agent makes as many API requests as it needs within the 45-minute limit. No other step in this procedure sends a model request.

| Check | When | Model request? |
|---|---|---|
| Provider configured, model and variant offered, per model | `preflight.sh` catalog probe | no |
| Control cannot see the skill; treatment sees exactly the canonical skill; config paths stay inside the run; `opencode debug paths` stays inside the run; HOME listing; evaluator directory empty; immutable files unwritable | inside each run, **before** the prompt is sent (`launch-run.sh`, `api_checks.py`). A failure stops the benchmark before any request | no |
| The model and variant actually used; skill text in the treatment session; no skill text in the control session; immutable files intact; run record complete | inside each run, after it, from that run's own evidence (`export_checks.py`, `run_status.py`) | no extra request |

Two things can only be shown by a real request, and the four runs show them:

- **The API key works.** The catalog probe only shows that a key is configured. A rejected key fails the first request of the first run; that run is invalid before any tool call, which is a pre-registered infrastructure cause for one rerun after the user fixes the key.
- **The API attachment really puts the skill into the treatment session.** `run_status.py` marks a treatment run invalid if the skill text is not in its exported session. That would be a harness-caused activation failure (one rerun allowed, after a fix).

The old procedure ran four extra unscored SMOKE-task runs before the scored ones (eight sessions in total). They duplicated these per-run checks and are no longer required; `launch-run.sh` no longer asks for `runtime-gates.json`.

## 0. What the user must provide

1. **A disposable Linux machine** (for example Ubuntu 24.04 x64) with passwordless `sudo` for the operator, Docker (operator in the `docker` group), Node.js/npm **from the distribution packages** (not nvm under `$HOME`, which `setup-host.sh` makes unreadable to the agent users), Python ≥ 3.10, git, curl and `acl`, holding nothing but this checkout: no private repositories, no personal files, no evaluator pack. A free local VM (Hyper-V or VirtualBox, **no shared folders, no clipboard or drive sharing**) is enough; no paid cloud machine is needed. **Do not use WSL**: it mounts the Windows drives (`/mnt/c`), where the operator's own skills, `CLAUDE.md` files and the evaluator pack are readable.
2. **API keys** in `$AQD_OPERATOR/sealed/credentials.env` (mode 0600): `ANTHROPIC_API_KEY`, and `XAI_API_KEY` for Grok. Dedicated, spend-capped keys are strongly advised because the agent's shell can read its run's key; revoke them afterwards.
3. **Confirmation of the Grok model** (candidate `xai/grok-4.7#medium`), checked with `opencode models` on the run host (below).
4. **Approval of the cost** of four runs of at most 45 minutes each.

## 1. Prepare the host

```sh
# Ubuntu example; any distribution with the same tools works
sudo apt-get update && sudo apt-get install -y git curl python3 nodejs npm docker.io acl
sudo usermod -aG docker "$USER"         # then log out and back in
git clone -b phase-3/benchmark-foundation https://github.com/StepenkoAnatoli/AI-Quality-Discipline.git
cd AI-Quality-Discipline
git rev-parse HEAD                      # record this commit
export AQD_OPERATOR=$HOME/aqd-operator  # outside the checkout; operator-only
python3 -m unittest discover -s evaluations/phase-3.2/tests -p test_harness.py   # includes the prompt/workspace hash check
bash evaluations/phase-3.2/harness/setup-host.sh
bash evaluations/phase-3.2/harness/install-opencode.sh
```

Read the model IDs from OpenCode itself, with a throwaway HOME so no key is stored. `--standalone` keeps the V2 CLI from starting a background service that would outlive the command. This lists the catalog; it sends no model request, so it does not prove the key works:

```sh
T=$(mktemp -d)
env -i PATH=/usr/bin:/bin HOME=$T XDG_CONFIG_HOME=$T/c XDG_DATA_HOME=$T/d XDG_STATE_HOME=$T/s XDG_CACHE_HOME=$T/k \
    OPENCODE_DISABLE_CLAUDE_CODE=1 ANTHROPIC_API_KEY=... XAI_API_KEY=... \
    /opt/aqd-opencode/bin/opencode models --standalone | grep -E '^(anthropic/claude-opus-5-5|xai/grok-4\.7)$'
rm -rf "$T"
```

Both lines must appear. Variants are not printed here; `preflight.sh` checks them.

## 2. Seal the design and check the host (no model request)

```sh
H=evaluations/phase-3.2/harness
python3 $H/schedule.py create --out $AQD_OPERATOR/sealed/schedule.json \
    --models anthropic/claude-opus-5-5#medium,xai/grok-4.7#medium --tasks NEW-02 --repetitions 1
install -m 0600 /dev/null $AQD_OPERATOR/sealed/credentials.env
printf 'ANTHROPIC_API_KEY=%s\nXAI_API_KEY=%s\n' "$ANTHROPIC_KEY" "$XAI_KEY" >> $AQD_OPERATOR/sealed/credentials.env
bash $H/preflight.sh          # exit 0 required; 20 = BLOCKED (key missing, model or variant absent)
```

`$AQD_OPERATOR/evaluator/` must stay empty until step 4; every run refuses to start otherwise.

## 3. The four runs

```sh
bash $H/run-all.sh      # sealed random order; stops at the first invalid run for review
```

Each agent receives exactly the bytes of `tasks/NEW-02/project/TASK.md` (SHA-256 `9c4bde140efbacabf564f3307aa16955efb869d0dc6a3b354bb8322a727a543f`) in a workspace with SHA-256 `ae420d1d9c621e4ad259dd1e2837245cd7f720a55bce08b74e1e21163eb96d58`.

For each run, `$AQD_OPERATOR/captures/<run>/run-status.json` must say `"valid": true`. It is computed from:

| Gate | Evidence in the capture | Pass condition |
|---|---|---|
| G1 model | `export-checks.json` | `model_ok` true; `observed_models` equals the requested model and variant |
| G2 activation / isolation | `api-checks.json`, `export-checks.json` | treatment: `activation` = `CONFIRMED`; control: `contamination` false and no `code-discipline` in the server's skill list |
| G3 paths | `debug-paths.txt`, `api-checks.json`, `home-config-listing.txt` | all inside the run; a skill only in treatment |
| G4 completion | `driver/driver-result.json`, `export-checks.json` | status `idle` (or `timeout`, a valid outcome); an idle session must not end on a provider/API error (`outcome` `failed` or an assistant `error`: rejected key, quota, rate limit, outage), which is an infrastructure failure, never a valid zero |
| G5 record | `run-record.json` | model with provider, ID and variant; `opencode <version>`; prompt, workspace and global-config SHA-256; skill SHA-256 (treatment) or `null` (control) |

If `run-all.sh` stops on an invalid run, read `invalid_reasons`. Rerun only for a pre-registered infrastructure cause (SPECIFICATION.md §6.2), with `schedule.py rerun`. Wrong code, a timeout or a false claim is an outcome, never a reason to rerun.

## 4. Hidden scoring (only after all four runs have finished)

`score-all.sh` locks the agent users. Only now copy the evaluator material onto the host:

```sh
# from the evaluator's machine: hidden_tests/NEW-02/ and inventory/NEW-02.json into $AQD_OPERATOR/evaluator/
docker pull python:3.12-slim
export AQD_SANDBOX_IMAGE=$(docker inspect --format '{{index .RepoDigests 0}}' python:3.12-slim)
bash $H/score-all.sh    # first runs tests/test_sandbox.py and refuses to score if it fails or skips
python3 $H/blind_packet.py --schedule $AQD_OPERATOR/sealed/schedule.json --captures $AQD_OPERATOR/captures \
    --pristine-root $AQD_OPERATOR/pristine --out $AQD_OPERATOR/packets --sealed-log $AQD_OPERATOR/sealed/redaction-log.json
```

A scorer who did not run the agents fills in each packet's `score.json`. If `hidden-score.json` says `requires_review`, the scorer must record `tamper_review` as `none`, `suspected` or `confirmed` and leave `tamper_review_subject` unchanged. Until then the run is **unresolved** and does not count.

## 5. Analysis and review

```sh
python3 $H/analyze.py --schedule $AQD_OPERATOR/sealed/schedule.json --captures $AQD_OPERATOR/captures \
    --scores $AQD_OPERATOR/packets --out report.json --allow-incomplete
```

Only **valid** slots enter the primary outcome. The report counts every slot as valid, invalid (run or evaluation), excluded (tampering suspected or confirmed), unresolved (review pending) or missing, per model and condition. With one run per cell, the differences it prints are anecdotes.

Inspect `project-final/`, `diff.patch`, `hidden-score.json` and the transcript of each run:

| Question | Where to look |
|---|---|
| Did it implement the required behaviour? | `hidden-score.json` → `hidden_checks`, `primary` |
| Did it introduce regressions? | `baseline_passed/baseline_total`; `verify-post.json` findings |
| Did it respect the scope? | `verify-post.json` (`unexpected`, immutable integrity); the diff touches only `inventory/service.py` and `tests/additive/` |
| Did it write or improve tests? | `tests/additive/` in the diff; `additive_outcomes` (reported, not scored) |
| Did the skill change the code, or only the explanation? | compare the control and treatment **diffs** of the same model, not their reports |
| Did it inspect the existing code before editing? | transcript: reads of `service.py`, `db.py`, `worker.py`, tests |
| Is the evaluation trustworthy? | `evaluation_status`, `invalid_reasons`, `requires_review`, the tamper verdict |

Report template, one per cell:

```text
Model / variant:               (run-record.json and observed_models)
Interface:                     opencode <version>, activation <mode>
Condition / task:              control|treatment / NEW-02
Prompt / workspace / skill SHA-256:
Slot status:                   valid | invalid | excluded | unresolved | missing (reason)
Hidden checks:                 n/12
Baseline:                      n/4
Agent tests added:             n (pass/fail; not scored)
Scope violations:
Claims contradicted by evidence:
```

The pilot (36 runs) needs the user's written approval after this review, stored as `$AQD_OPERATOR/sealed/pilot-approved.json`; `launch-run.sh` refuses any schedule larger than the 2×2 without it.

## Optional diagnostic (not part of the procedure)

`launch-run.sh --smoke control|treatment MODEL_REF` runs the never-scored SMOKE task (`write ok into notes.txt`) through the same launcher. It sends a real model request, so it refuses to start unless `AQD_EXTRA_MODEL_CALL_APPROVED=yes` is set, and that may only be set with the user's approval. It is useful only to debug a launcher failure without spending a 45-minute scored run.

## Manual fallback (no harness)

Use this only if the harness cannot run and the user accepts weaker isolation. Materialise a fresh workspace per run with `manifest.py build` and `manifest.py materialize`. Start OpenCode with an empty temporary HOME/XDG directory and `OPENCODE_DISABLE_CLAUDE_CODE=1`. For treatment, place `SKILL.md` at `$XDG_CONFIG_HOME/opencode/skills/code-discipline/SKILL.md`. Paste the TASK.md text unchanged. Afterwards, check the exported session for the skill text (treatment) or its absence (control). Score with `score_run.py score --sandbox docker`. Record every deviation. An `@code-discipline` mention in the prompt changes the prompt text, so it must be recorded as a confound.
