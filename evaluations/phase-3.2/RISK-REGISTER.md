# Phase 3.2 — Risk register (v3)

| # | Risk | Severity | Mitigation | Residual |
|---|---|---|---|---|
| R01 | Candidate code forges its own result in-process | High | Nonce, per-test process, strict result validation; tamper-pattern scan forces human diff review | Deliberate in-process tampering is detectable, not preventable |
| R02 | Scoring sandbox weaker than assumed on the scoring host | High | `score-all.sh` refuses to score unless `test_sandbox.py` passes with no skips on that host | Container escape not addressed |
| R03 | Control run inherits the skill (global config, the user's own skills, `CLAUDE.md`) | High | Never run agents on the operator PC; fresh `env -i` HOME per run; server skill registry checked before the prompt; export scanned after | Agent can fetch public text from the internet; detected after the fact only |
| R04 | Treatment attachment does not add the skill text | High | Activation must be CONFIRMED per run; smoke gate G2 | Untested with real OpenCode |
| R05 | Silent model or variant substitution by the provider or interface | High | Requested model is recorded; `observed_models` checked; mismatch invalidates | A provider may alias models server-side; record the provider's model metadata |
| R06 | API key visible to the agent's shell | Medium | Dedicated spend-capped keys, one provider per run, revoked after; no other secrets on the host | Key could appear in a transcript; do not publish transcripts unredacted |
| R07 | Ceiling effect: both conditions pass everything | Medium | Solution hints removed; several independent defect classes per task | Possible with strong models; a null result must be reported as such |
| R08 | Small sample read as proof | High | Analysis labelled exploratory; effects within model only | Depends on reporting discipline |
| R09 | Oracle too strict for a valid alternative design | Medium | Every check traces to a stated requirement; references and 11 mutants validate both directions; adjudication notes, never test edits after unblinding | Judgement calls documented in the private key |
| R10 | Launcher never executed: unknown OpenCode V2 behaviour (paths, idle detection, export) | Medium | Smoke gates G1–G5 before any scored run | Version-specific |
| R11 | Public specification readable by agents through the internet | Low | Hidden tests, references and the key stay private; the specification only restates the prompt | — |
| R12 | Evaluator pack exists only on the operator PC | Medium | Back it up privately; never copy it to an agent host before agent runs end | — |
| R13 | Pre-existing `tests/test_install.py` failures on the operator PC (line endings) | Low | Unrelated to Phase 3.2; untouched | Needs a separate fix |
