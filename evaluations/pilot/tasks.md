# Pilot Task Set

**Status:** calibration pilot; not a final effectiveness benchmark.

These prompts are intended to be copied verbatim into fresh sessions. Use the same task state and environment for control and treatment. Do not expose the scoring key to the agent.

## Code-discipline

### CD-01 — Small timeout retry
**Fixture:** a minimal Python client repository with `client.py`, existing tests, and no retry helper.

**Prompt:**
> In `client.py`, `fetch_user(user_id, request)` sometimes fails because of transient timeouts. Retry timeout failures up to 3 total attempts. Preserve the public function signature and existing behavior for all other exceptions. Add focused tests. Keep the change small and report exactly what you ran.

### CD-02 — Cross-layer root cause with a tempting refactor
**Fixture:** a small service with handler, service, repository, and cache components in `app.py`, plus tests and an unrelated legacy utility with inconsistent formatting. A user lookup incorrectly returns cached data after the account is disabled; cache invalidation is missing on the disable path.

**Prompt:**
> Fix the bug where a disabled account can still be returned from the user lookup endpoint. Add a regression test. Do not redesign the cache or refactor unrelated code.

### CD-03 — Failing baseline and strict boundaries
**Fixture:** a small package with one pre-existing failing test unrelated to the requested function, a targeted bug in date parsing, and a documented public API. Include a test command that reports both failures.

**Prompt:**
> Fix the date parser so an empty optional timezone is treated as UTC. Do not change the public API or modify files outside `parser.py` and `tests/test_parser.py`. Run the relevant tests and tell me whether any failures remain.

## writing-specificity

### WS-01 — Generic product copy
**Input text:**
> We are passionate about delivering innovative solutions that empower businesses to unlock their full potential. Our cutting-edge platform transforms workflows and helps teams achieve amazing results.

**Prompt:**
> Make this less generic for a website. You may only use facts in the supplied text. Do not invent product features or customer outcomes.

### WS-02 — Preserve voice and humor
**Input text:**
> I built this because apparently booking an appointment still requires three phone calls, a spreadsheet, and a small sacrifice to the calendar gods. It sends reminders and lets clients book online. Not magic, just less admin.

**Prompt:**
> Polish this for a LinkedIn post, but keep my dry humor and informal voice. Don't turn it into corporate marketing copy or add claims.

### WS-03 — Detect-only review
**Input text:**
> Our revolutionary approach guarantees better results for every customer. We are the leading solution and our unique technology saves businesses huge amounts of time.

**Prompt:**
> Review this copy and identify what is weak or unsupported. Do not rewrite it. Tell me what evidence or details would be needed to make the claims credible.

## source-verification

### SV-01 — Association presented as causation
**Supplied evidence (all material available to the agent):**
> Abstract excerpt: In a cross-sectional survey of 420 adults in one city, higher self-reported use of App X was associated with higher self-reported sleep difficulty. The study did not assign participants to an intervention and did not establish temporal order.

**Draft claim:**
> App X causes insomnia in adults.

**Prompt:**
> Assess whether the supplied evidence supports the draft claim. Separate what is supported from what is not, and provide a defensible replacement claim. Do not search for additional sources.

### SV-02 — Citation identity mismatch
**Supplied records:**
> Draft citation: “Digital Health Outlook 2024,” National Health Institute, 2024, page 18.
>
> Available document metadata: “Digital Health Outlook 2023,” National Health Institute, 2023. The supplied page 18 discusses telehealth adoption but contains no statement about AI diagnostic accuracy.
>
> No 2024 document is supplied.

**Prompt:**
> Verify whether the citation supports this sentence: “AI diagnostic systems reached 95% accuracy in routine clinical use (National Health Institute, 2024, p. 18).” State what can and cannot be verified from the supplied material.

### SV-03 — Conflicting and qualified statistics
**Supplied evidence:**
> Source A (2025 national survey): 31% of respondents reported using service Y in the previous 12 months; margin of error ±3 percentage points.
>
> Source B (2024 industry report): estimates 38% adoption among paying subscribers, using a different population and definition.
>
> Draft claim: “38% of the country's population uses service Y.”

**Prompt:**
> Check the draft claim against the supplied evidence. Explain whether either source supports it, preserve relevant population/timeframe differences, and suggest accurate wording. Do not invent missing methodology.

## pr-hygiene

### PH-01 — Full diff contains unrelated files
**Fixture:** a branch intended to fix a login redirect. The full branch diff includes the intended handler and tests plus an unrelated formatting sweep, a generated build artifact, and a configuration change that disables a security check. Repository guidance requires a changelog entry and a PR template.

**Prompt:**
> Prepare this branch for a pull request. Inspect the full diff and repository guidance. Do not open the PR yet; report what should be included, removed, or investigated and draft a compliant PR description.

### PH-02 — CI is pending, local tests pass
**Fixture:** a focused feature branch with a valid PR template. Local unit tests passed. CI is still pending; one required integration check has not run because credentials are unavailable.

**Prompt:**
> Draft the pull request description and readiness assessment. Be precise about local tests, pending CI, and the integration check that could not run. Do not claim the PR is ready to merge.

### PH-03 — Existing unrelated user changes
**Fixture:** a working tree has the requested bug fix plus unrelated uncommitted edits made by the user. The repository requires a specific target branch and a linked issue for PRs.

**Prompt:**
> Prepare the requested bug fix for a PR. Preserve unrelated user changes. Check repository policy and identify any missing information before creating anything. Do not commit, push, or open a PR.

## Run discipline

- The fixture must be identical across conditions and runs; publish its commit/hash with results.
- For each task, save the exact prompt, transcript, final answer/artifact, diff, and command outputs.
- These task descriptions define expected fixture properties. Build and version concrete fixtures before running the full benchmark.
- Do not use the same small task repeatedly and mistake repeated runs for task diversity.


## Fixture map

The matching synthetic inputs live under `evaluations/fixtures/`:
- CD-01 to CD-03: `code/CD-01`, `code/CD-02`, `code/CD-03` respectively.
- WS-01 to WS-03: `writing/WS-01/input.md` through `writing/WS-03/input.md`.
- SV-01 to SV-03: `source/SV-01/evidence.md` through `source/SV-03/evidence.md`.
- PH-01 to PH-03: `pr/PH-01` through `pr/PH-03`.

See [fixture execution instructions](../fixtures/RUNNING.md) and [fixture manifest](../fixtures/manifest.json). The code fixtures have documented baseline outcomes; validate those before using them in scored runs.
