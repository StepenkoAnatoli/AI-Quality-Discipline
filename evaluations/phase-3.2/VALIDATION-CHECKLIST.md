# Phase 3.2 — Validation checklist (v3, 2026-11-21)

Status words: **LOCAL** = tested on the operator PC (Windows, Python 3.14.7); **CI** = tested in GitHub Actions; **AUDIT** = independently audited; **NOT TESTED**; **BLOCKED**. CI: GitHub Actions runs 44864449784 and 44864453346 on commit `8680c4c`, both green; they ran `test_harness.py`, `test_scoring.py` and `test_sandbox.py`. Nothing is independently audited yet.

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
| V19 | Launcher, preflight, isolation, activation with real OpenCode | gates G1–G5, evaluated inside each of the four smoke runs | **NOT TESTED** |
| V20 | Claude and Grok understand and complete the actual prompts | smoke test | **BLOCKED** (no host, no keys on a host, no xAI access) |
| V21 | Oracles pass on Linux | `check_oracles.py` on the run host | **NOT TESTED** (re-run on Windows with v3.1 scoring: ORACLES OK) |

## v3.1 additions (local only: not yet committed, pushed or run in CI)

| # | Requirement | Evidence | Status |
|---|---|---|---|
| V22 | A run flagged for review is not counted until a verdict names exactly the scored code; placeholder, unknown or stale verdicts leave it unresolved; `suspected`/`confirmed` exclude it, flagged or not | `test_harness.py` AnalyzeTests (review gating); failed on the v3 `analyze.py` | LOCAL |
| V23 | Inconsistent, malformed or foreign score files stop the analysis (counts, fraction, `fully_correct`, baseline, review fields, schema, kind, status, inventory, stray directories, blind-id mismatch) | `test_harness.py` AnalyzeTests; failed on v3 | LOCAL |
| V24 | The report separates valid, invalid, excluded, unresolved and missing slots, per model and condition; an invalid evaluation is never reported as missing | `test_harness.py` AnalyzeTests | LOCAL |
| V25 | Scored code cannot import agent tests; run-time-built imports, dynamic execution, reflection and private-attribute access are flagged; none of the 14 known solutions is flagged | `test_scoring.py` ResidualRiskTests; reproduced bypasses scored 2/2 unflagged on v3; scan run over references and mutants | LOCAL |
| V26 | A missing agent result is INVALID; a deleted mutable file is a valid zero | `test_scoring.py`; failed on v3 | LOCAL |
| V27 | Agent symlinks are not followed on the scoring host | `test_scoring.py` | LOCAL on Windows, where `chmod` cannot show the defect; **needs CI on Linux** |
| V28 | Run record complete and consistent (`run_status.py`); conditions differ only in the skill (`analyze.py`) | `test_harness.py` RunStatusTests, AnalyzeTests | LOCAL (synthetic records) |
| V29 | No extra model session in the smoke procedure; the optional SMOKE task and the pilot refuse to start without approval | `test_harness.py` LauncherGateTests (launcher executed in Git Bash up to the refusal) | LOCAL |
| V30 | Hidden private pack still passes with the v3.1 scorer | `check_oracles.py` | LOCAL (ORACLES OK) |
