# Phase 3.2 — Validation checklist (v3.2, 2026-11-21)

Status words: **LOCAL** = tested on the operator PC (Windows, Python 3.14.7); **CI** = tested in GitHub Actions; **PROBE** = checked against the real OpenCode 2.3.2 server without sending a prompt; **AUDIT** = independently audited; **NOT TESTED**; **BLOCKED**. CI: runs 44864449784/44864453346 on `8680c4c` (v3) and 44889032716 (push)/44889036252 (PR #1) on `f0c857c` (v3.1), all green. On `f0c857c` CI ran, on `ubuntu-latest` with Python 3.11: `validate_skills.py`, `test_validators.py` (9 OK), `check_fixtures.py` (3 PASS), `check-sources`, `test_harness.py` (59 OK), `test_scoring.py` (37 OK) and `test_sandbox.py` (3 OK, 0 skipped). When v3.2 was written, this line said: "The v3.2 changes (V31–V34) are local only and not committed." Nothing is independently audited yet.

**Status correction (2026-11-21, after CI).** v3.2 is committed as `3d522f5`; CI passed on it in runs 44892816556 (push) and 44892821220 (PR #1), on CPython 3.11.18: `validate_skills.py`, `test_validators.py` (9 OK), `check_fixtures.py` (3 PASS), `check-sources`, `test_harness.py` (63 OK), `test_scoring.py` (37 OK) and `test_sandbox.py` (3 OK, 0 skipped). The test files behind rows V5–V9, V11–V18 and V32–V34 therefore also passed in CI on `3d522f5`; rows V5–V18 keep their original LOCAL wording. CI does not run OpenCode, the launcher or any model, so V19–V21 and V31 are unchanged by it.

| # | Requirement | Evidence | Status |
|---|---|---|---|
| V1 | Original fixtures pass their baseline tests and fail the hidden checks for their planted defects | `check_oracles.py` | LOCAL |
| V2 | Each reference passes 41/41 hidden checks and all baseline tests | `check_oracles.py` | LOCAL |
| V3 | 11 plausible wrong solutions are each caught | `check_oracles.py` | LOCAL |
| V4 | The stored inventory equals one rebuilt from pristine + hidden (13/12/16 hidden, 3/4/4 baseline) | `check_oracles.py` | LOCAL |
| V5 | Zero tests, missing, unexpected or duplicate tests, changed or unloadable hidden files → INVALID | `test_scoring.py` FailClosedTests | LOCAL |
| V6 | Crash before result, forged or malformed result, extra files, late non-zero exit, skip → INVALID | `test_scoring.py` | LOCAL |
| V7 | Syntax error, hang, wrong answer → VALID failure; valid zero ≠ invalid | `test_scoring.py` ValidOutcomeTests | LOCAL |
| V8 | Only the mutable file and additive tests are scored; agent tests never invalidate | `test_scoring.py` | LOCAL |
| V9 | Candidate code is refused without a sandbox; unpinned image refused | `test_scoring.py` CliTests | LOCAL |
| V10 | Sandbox: no network, read-only code, non-root, no host env, no evaluator files, containers removed | `test_sandbox.py` | CI (3/3 OK, no skips; synthetic probe). Not run on the real scoring host yet; `score-all.sh` enforces it there |
| V11 | In-process tampering is flagged for review (cannot be prevented) | `test_scoring.py` ResidualRiskTests | LOCAL |
| V12 | Missing, invalid or unevaluated runs → INCOMPLETE; duplicate valid runs → error; reruns replace invalid attempts | `test_harness.py` AnalyzeTests | LOCAL |
| V13 | Documentation scores cannot raise the primary outcome | `test_harness.py` AnalyzeTests | LOCAL |
| V14 | Schedule: control and treatment of one model and task per block; out-of-scope providers rejected | `test_harness.py` ScheduleTests | LOCAL |
| V15 | Prompts and workspaces frozen by hash; prompts free of evaluator, interface and solution hints | `test_harness.py` PreregisteredInputsTests | LOCAL |
| V16 | Prompt text byte-identical across conditions; only treatment attaches the skill | `test_harness.py` DriveSessionTests (fake server) | LOCAL (fake server only) |
| V17 | Activation confirmed / contamination detected from session exports; model substitution detected | `test_harness.py` ExportCheckTests (synthetic exports) | LOCAL (synthetic only) |
| V18 | Shell scripts parse | `bash -n` (Git Bash) | LOCAL (syntax only) |
| V19 | Launcher, preflight, isolation, activation with real OpenCode | gates G1–G5, evaluated inside each of the four smoke runs | **NOT TESTED** on Linux. PROBE (V31) covers the HTTP API shapes only |
| V20 | Claude and Grok understand and complete the actual prompts | smoke test | **NOT TESTED** (no Linux host or keys yet; Grok also needs an `XAI_API_KEY`) |
| V21 | Oracles pass on Linux | `check_oracles.py` on the run host | **NOT TESTED** (re-run on Windows with v3.1 scoring: ORACLES OK) |

## v3.1 additions (committed in `f0c857c`; CI green)

| # | Requirement | Evidence | Status |
|---|---|---|---|
| V22 | A run flagged for review is not counted until a verdict names exactly the scored code; placeholder, unknown or stale verdicts leave it unresolved; `suspected`/`confirmed` exclude it, flagged or not | `test_harness.py` AnalyzeTests (review gating); failed on the v3 `analyze.py` | LOCAL, CI |
| V23 | Inconsistent, malformed or foreign score files stop the analysis (counts, fraction, `fully_correct`, baseline, review fields, schema, kind, status, inventory, stray directories, blind-id mismatch) | `test_harness.py` AnalyzeTests; failed on v3 | LOCAL, CI |
| V24 | The report separates valid, invalid, excluded, unresolved and missing slots, per model and condition; an invalid evaluation is never reported as missing | `test_harness.py` AnalyzeTests | LOCAL, CI |
| V25 | Scored code cannot import agent tests; run-time-built imports, dynamic execution, reflection and private-attribute access are flagged; none of the 14 known solutions is flagged | `test_scoring.py` ResidualRiskTests; reproduced bypasses scored 2/2 unflagged on v3; scan run over references and mutants | LOCAL, CI |
| V26 | A missing agent result is INVALID; a deleted mutable file is a valid zero | `test_scoring.py`; failed on v3 | LOCAL, CI |
| V27 | Agent symlinks are not followed on the scoring host | `test_scoring.py` | LOCAL on Windows (where `chmod` cannot show the defect); CI on Linux (`f0c857c`) |
| V28 | Run record complete and consistent (`run_status.py`); conditions differ only in the skill (`analyze.py`) | `test_harness.py` RunStatusTests, AnalyzeTests | LOCAL, CI (synthetic records) |
| V29 | No extra model session in the smoke procedure; the optional SMOKE task and the pilot refuse to start without approval | `test_harness.py` LauncherGateTests (launcher executed in Git Bash up to the refusal) | LOCAL, CI |
| V30 | Hidden private pack still passes with the v3.1 scorer | `check_oracles.py` | LOCAL (ORACLES OK) |

## v3.2 additions (2026-11-21; committed as `3d522f5`, CI green)

*Status correction, 2026-11-21:* this heading read "local only: not committed, pushed or run in CI" when it was written. The statuses of V32–V34 below were updated from LOCAL to LOCAL, CI after CI passed on `3d522f5`. V31 is a probe of the real server and is not covered by CI.

| # | Requirement | Evidence | Status |
|---|---|---|---|
| V31 | The harness's HTTP calls match the real OpenCode 2.3.2 server: `/api/info` (401 without the password), `/api/provider`, `/api/model` (`providerID`, `id`, `variants[].id`, `enabled`), `/api/skill` (`id`, `path`, `content`), `/api/config`, `POST /api/session` with model and variant, session get, `/permission`, `/api/experimental/session/{id}/export` (`{info, messages}`), `session export --server`; the OpenAPI schema has `PromptInput.skills[{id}]`, `Session.Info.time.busy/idle` and `outcome`, and the message types `export_checks.py` reads; project permission rules load and merge into the `build` agent with no `ask` left | Probe on the operator PC (Windows, isolated temp HOME/XDG, placeholder key, no prompt sent) | PROBE (Windows). Not on Linux; the prompt, the idle transition and the skill attachment are still untested |
| V32 | The skills built into the OpenCode binary (`skill://opencode`, `skill://report`, `skill://browser` in 2.3.2, present in control and treatment) do not stop every run as an isolation failure; a built-in skill that is or contains `code-discipline` still does | `test_harness.py` ApiCheckTests; failed on the v3.1 `api_checks.py`; real 2.3.2 skill lists replayed through `check_skills` | LOCAL, CI (`3d522f5`) |
| V33 | The pinned version is read as X.Y.Z (2.3.2 prints `opencode v2.3.2`, which v3.1 compared verbatim with `2.3.2`, so `install-opencode.sh` and `preflight.sh` would always have failed); the run record must name `opencode X.Y.Z` | `test_harness.py` OpenCodeVersionTests (Git Bash), RunStatusTests; both failed on v3.1 | LOCAL, CI (`3d522f5`; Linux bash against a stub `opencode` that prints `opencode v2.3.2`, not the real binary) |
| V34 | A session that ends on a provider/API error (rejected key, quota, rate limit, outage: `outcome` `failed` or an assistant `error`) is INVALID, so it stops `run-all.sh` and never counts as a valid zero; a timeout stays valid | `test_harness.py` RunStatusTests; failed on v3.1 | LOCAL, CI (`3d522f5`; synthetic exports) |
