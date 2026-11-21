# Phase 3.2 — Validation checklist (v3, 2026-11-21)

Status words: **LOCAL** = tested on the operator PC (Windows, Python 3.14.7); **CI** = tested in GitHub Actions; **AUDIT** = independently audited; **NOT TESTED**; **BLOCKED**. Nothing is CI-tested or audited yet: the branch changes are not pushed.

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
| V10 | Sandbox: no network, read-only code, non-root, no host env, no evaluator files, containers removed | `test_sandbox.py` | **NOT TESTED** (no Docker locally; CI job added, not run) |
| V11 | In-process tampering is flagged for review (cannot be prevented) | `test_scoring.py` ResidualRiskTests | LOCAL |
| V12 | Missing, invalid or unevaluated runs → INCOMPLETE; duplicate valid runs → error; reruns replace invalid attempts | `test_harness.py` AnalyzeTests | LOCAL |
| V13 | Documentation scores cannot raise the primary outcome | `test_harness.py` AnalyzeTests | LOCAL |
| V14 | Schedule: control and treatment of one model and task per block; out-of-scope providers rejected | `test_harness.py` ScheduleTests | LOCAL |
| V15 | Prompts and workspaces frozen by hash; prompts free of evaluator, interface and solution hints | `test_harness.py` PreregisteredInputsTests | LOCAL |
| V16 | Prompt text byte-identical across conditions; only treatment attaches the skill | `test_harness.py` DriveSessionTests (fake server) | LOCAL (fake server only) |
| V17 | Activation confirmed / contamination detected from session exports; model substitution detected | `test_harness.py` ExportCheckTests (synthetic exports) | LOCAL (synthetic only) |
| V18 | Shell scripts parse | `bash -n` (Git Bash) | LOCAL (syntax only) |
| V19 | Launcher, preflight, isolation, activation with real OpenCode | runtime gates G1–G5 | **NOT TESTED** |
| V20 | Claude and Grok understand and complete the actual prompts | smoke test | **BLOCKED** (no host, no keys, no xAI access) |
| V21 | Oracles pass on Linux | `check_oracles.py` on the run host | **NOT TESTED** |
