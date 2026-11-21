# Phase 3.2 — Risk register

Severity: **High** = could invalidate the experiment or cause harm; **Medium** = could bias or weaken results; **Low** = nuisance.

| # | Risk | Severity | Likelihood | Impact | Mitigation | Residual |
|---|---|---|---|---|---|---|
| R01 | `opencode` provider unavailable without credentials (F10) | High | Medium | Benchmark cannot run as specified | Preflight catalog probe with a credential-free HOME; BLOCKED → user decision; never create credentials | Decision may change the model or add a key (key would be visible to the agent shell) |
| R02 | `xhigh` not honoured, or not observable, at the NVIDIA endpoint | High | Medium | Mandatory parameter unproven | Gates X1–X4; stop on X1/X2 failure; record X3 observability; user decides | Effort level cannot be proven client-side |
| R03 | Free model withdrawn or terms changed mid-experiment | High | Medium ("limited time") | Incomplete or mixed data | Stop rule; record model metadata hash per run (`api-checks.json`) | Need to restart with a new pre-registration |
| R04 | Control agent downloads the public skill text from the internet | Medium | Low | Contaminated control | Web tools denied in both groups; `export_checks` scans every control transcript; contaminated runs invalid and reported | Shell `curl` cannot be blocked in a Codespace |
| R05 | Activation attachment does not add the skill text | High | Low–Medium | Treatment equals control | R2 smoke gate; per-run CONFIRMED check; `cli-mention` fallback (approval) | — |
| R06 | Undocumented OpenCode behaviour (non-git project root, config writes in `~/.config/opencode`, idle detection, `session export --server`) | Medium | Medium | Launcher fails or misjudges completion | Smoke gates R5, R6, R8; fail-closed checks; manual review of first runs | Version-specific; pinned version reduces drift |
| R07 | Agent user escapes isolation (sudo misconfiguration, readable operator files, `/workspaces/.codespaces` secrets) | High | Low | Cross-group contamination or secret exposure | No sudo or groups (preflight); 0700 modes and ACL; `env -i`; access probes before each run; preflight fails if `/workspaces/.codespaces` is readable | Kernel or container escape not addressed |
| R08 | Same-group agent reads an earlier run | Medium | Low | Learning across repetitions | Run root deleted after capture; `/tmp` cleaned per user; `runs/` not listable | — |
| R09 | Oracle flakiness on Linux (timing, multiprocessing start method) | Medium | Low–Medium | Wrong correctness scores | Slow-SELECT proxy makes races deterministic; 3× local validation; R7 3× on Linux; per-check timeouts | A pathological agent implementation could time out a check (scored as fail) |
| R10 | Hidden oracle too strict or too lenient for some valid design | Medium | Low | Mis-scored correct solutions | Contract fixed in TASK.md; references and mutants validate both directions; evaluator reviews any check failing on a solution that looks correct, recorded as an adjudication note, never by editing tests after unblinding | Judgement calls documented |
| R11 | Blinding broken by agent prose or diff style | Medium | Medium | Scorer bias | Redaction; tokens, durations, paths removed; blinding check reported | Cannot be eliminated |
| R12 | Ceiling or floor effects (all runs pass or fail) | Medium | Medium | No information | Tasks contain several independent defect classes; partial credit via pass fraction | Possible with a strong model |
| R13 | Small sample misread as proof | High | Medium | False claims about the skill | §14 permitted language; `analyze.py` labels output exploratory | Depends on reporting discipline |
| R14 | Codespace stops mid-run (idle timeout, 12-hour limit) | Medium | Medium | Lost run | Idle timeout 60 min; plan ≤ 11 h per session; interrupted run invalid and eligible for one rerun | — |
| R15 | Quota exhausted or unexpected billing | High | Low | Blocked runs or charges | User checklist §15.3; preflight refuses a payment method without recorded approval; estimate ≤ 35 core-hours | Account state can change after the check |
| R16 | Gateway rate limits or outages | Medium | Medium | Invalid runs, time drift | Rerun rule (one per slot); stop after 3 consecutive infrastructure failures; blocked randomisation balances drift | Prolonged outage ends the attempt |
| R17 | Prompt or data sent to NVIDIA logging | Low | Certain | Logged synthetic content | Synthetic data only; no secrets in workspaces | — |
| R18 | `@opencode/cli` 2.3.2 removed or changed upstream | Medium | Low | Cannot reinstall identically between sessions | Install tree hash recorded and compared by preflight | Registry availability outside our control |
| R19 | Pre-existing Windows failures of `tests/test_install.py` on the operator PC (9 failures, unrelated to Phase 3.2) | Low | Certain on that PC | Confusing local CI picture | Reported in CHANGE-REPORT.md; untouched | Needs a separate investigation |
| R20 | Evaluator pack exists only on the operator PC | Medium | Low | Loss of hidden tests | Back up privately (not to the public repo) before execution | — |
