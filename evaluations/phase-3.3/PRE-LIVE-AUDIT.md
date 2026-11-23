# Pre-live security audit of the first live probe (2026-11-23)

**Scope:** PR #3 at `15069bd`, plus this audit's corrections (PR #4, stacked on PR #3).

**Offline only.** None of the following happened:
- no token was created and no authentication was attempted;
- no model request was made and no subscription or credits were used;
- nothing was dispatched and nothing was merged.

The canonical skill is unchanged: `d050d00fa8564b08cac71ca221368568420c731c830ef19667a760d5f7ebc842`, verified at the head.

## A. Verdict

**READY to request owner authorisation for one live security probe,** once CI on the head commit of PR #4 is green (§D). This is a request, not an authorisation: nothing may run until the owner completes LIVE-PROBE.md §6.

**Owner actions that remain** (none can be done by an agent):
1. Review and accept PR #3 plus PR #4 as the reviewed commit P.
2. Configure the environment `aqd-cc-live-probe`, with no prior deployments.
3. Make the one-file approval commit X on P.
4. Open the one-file bootstrap PR to `main` pinning X. Merge it yourself.
5. Run a green mock dispatch from `main`.
6. Choose the revocation method and turn usage credits off.
7. Write the authorisation.
8. Create the token and the passphrase secret.
9. Dispatch once.

**Accepted residual risks** (not blockers; see §E and §G):
- Server-side revocation of a `setup-token` token cannot be verified without a request.
- Three GitHub behaviours assumed by the new checks are unverified until the first live dispatch. Each fails closed, before the token is written.

## B. Findings

| # | Finding | Status | Severity | Fix |
|---|---|---|---|---|
| 1 | The live job checks out `AQD_TEST_SHA`, but the procedure filled `probe-approval.json` only in a bootstrap commit on `main`. The pinned tree therefore always held the unfilled template, and `cc_adapter.check_approval` refuses that: *"approval has no approved_by (an unfilled template is not an approval)"*. Reproduced in `test_regression_approval_only_on_main_is_refused_at_the_pinned_commit` | **Confirmed** | Blocker (the probe could never run). Fail-closed, so not a security hole | One-file owner approval commit X on reviewed commit P; `main` pins X; `check_approval_commit.py` |
| 2 | Nothing tied the workflow file that actually runs (`main`'s copy) to the reviewed copy. Only the owner's eye checked the bootstrap PR | **Confirmed** | High (a weakened guard on `main` would go unnoticed) | `check_approval_commit.py --main-workflow`: main's file must equal the reviewed file, with only `AQD_TEST_SHA` filled in |
| 3 | `sudo tar … 2>/dev/null \|\| true` hid missing or unreadable files. The GPG round-trip proved only that ciphertext and plaintext agree, not that the evidence was complete. The step printed "capture encrypted" for an empty or partial archive | **Confirmed** | High (evidence integrity) | `pack_evidence.py`: required manifest, truncation and readability checks, a read-back check, distinct exit codes; only *complete* is green |
| 4 | `run_attempt == 1` stops re-runs, but a **new** dispatch has attempt 1 again. Before this fix, re-use of the approval was prevented only by the environment reviewer clicking "approve" again, and by the secret being deleted | **Confirmed** | Medium | `check_single_use.py`: GitHub's deployment record for the environment must hold only this job |
| 5 | LIVE-PROBE.md §5 said "Anthropic does not document any way to revoke a `setup-token` token" | **Outdated.** Support article 10310342 documents that account-wide Log Out signs out setup-token tokens | Medium (owner procedure) | §5 rewritten (§E below) |
| 6 | The earlier claim that the URL `https://claude.ai/settings/claude-code` is official | **Not confirmed.** Only the menu path "Settings > Claude Code" is in official text | Low | The docs use the menu path |
| 7 | The earlier claim that per-token removal in Settings › Claude Code revokes `setup-token` tokens | **Partly supported.** The article covers "authorization tokens" generically. That setup tokens are listed there, and that removal invalidates them on the server, is not stated | Medium | The procedure recommends the targeted removal **and** the documented account-wide Log Out |
| 8 | "Environment secrets are unavailable to pull requests" | **Holds, with a caveat.** It holds by GitHub's environment branch rule (`main` only), which `verify-environment` checks. A writer can dispatch a modified workflow from another branch; that branch is refused the environment. The commit pin does not protect this; the environment does | — | Documented (LIVE-PROBE.md §3) |
| 9 | `verify-environment` uses the unauthenticated REST API | **Accepted.** Rate limiting on shared runner IPs can fail the job, but it fails closed before any secret | Low | none |
| 10 | Self-approval: if the owner is both dispatcher and only reviewer, the environment approval is a confirmation click, not a second person | **Accepted** for a single-owner repository | Low | Documented in §6 |
| 12 | *(fresh-context review of `862b74d`)* The first packager reported **complete** while silently dropping collected files: a non-required file over 64 MB, a FIFO or device node in `project-final`, or a directory `os.walk` could not list. Reproduced | **Confirmed, fixed** | Medium | Any problem on any collected entry is a problem; `os.walk(onerror=)`; files are streamed, never dropped for size |
| 13 | *(review)* A required file over 64 MB (e.g. a long transcript) was left out of the archive (status correctly incomplete, but the evidence lost) | **Confirmed, fixed** | Low | Streamed into the archive; flagged "too large to parse" |
| 14 | *(review)* All collected bytes were held in memory at once (OOM risk with agent-written bulk; would lose every file) | **Plausible, fixed** | Low | Streaming hash + archive; 2 GiB budget for non-required bulk, required files always first |
| 15 | *(review)* The packaging step ran the pinned commit's `pack_evidence.py` as root, in the step holding the passphrase, even when the approval check had refused that commit. Also: the approval checker itself was taken from the commit it checks | **Confirmed by trace, fixed** | Low-medium | Marker written only when the approval check passes; packaging refuses without it. The checker is taken from the reviewed parent (`$AQD_TEST_SHA^`) |
| 11 | Scientific separation: `analyze.py` refuses `PROBE-CC` and `SMOKE` records and never pools execution environments. Treatment is skill availability via `--plugin-dir`, with identical prompts in both arms. The canonical skill hash is enforced in CI and in the live job | **Verified in code and the existing tests.** Not changed | — | none |

**False positives checked:**
- **The `|| true` on `sysctl` and in the mock job.** These are diagnostics only, not evidence.
- **The token appearing in `launcher.log` outside `$CAP`.** The launcher never writes it there. The new packager also counts token-shaped strings across *every* collected file, so a regression would surface as exit 5.

## C. Changes (PR #4)

| File | Change | Why it is minimal |
|---|---|---|
| `live/check_approval_commit.py` (new) | Verifies that the pinned commit is the owner's one-file approval commit on the reviewed commit, and that main's workflow is the reviewed one | One stdlib script. It keeps the existing approval format and `cc_adapter.check_approval`, and adds only `reviewed_commit` |
| `live/probe-approval.json` | Adds an empty `reviewed_commit` field and states the new procedure in `note` | Still an unfilled template, which the launcher refuses |
| `live/pack_evidence.py` (new) | Replaces `tar … \|\| true`. Same collected scope (`preflight.log`, `launcher.log`, `sealed/`, `captures/`), plus a manifest and verification | One stdlib script. No new dependencies; the GPG pipeline is unchanged |
| `live/check_single_use.py` (new) | Single use of the approval, from GitHub's deployment record | One API read with the job token (`deployments: read`), before the secret is used |
| `.github/workflows/phase3-cc-smoke.yml` | Live job: `fetch-depth: 2`, approval-commit step, single-use step, `deployments: read`, and the packaging step with explicit outcomes. Mock job: runs all live tests (`test_*.py`, fails on any skip) | No new job; the secret placement is unchanged |
| `live/rehearse.sh` | Every case also runs the packager on the real launcher output. The clean run must be *complete*, which checks the required list against reality | The same cases, plus one assertion per case |
| `live/test_*.py` (4 new files) | 47 new tests (60 in the directory) | — |
| `LIVE-PROBE.md`, `SMOKE-WORKFLOW.md` | Procedure, manifest and credential steps. The superseded bootstrap text is marked | — |

The canonical skill, the harness (`phase-3.2/harness/*`), `run-live-probe.sh`, the probe task, the schedule and the approved hashes are all unchanged.

## D. Verification

**Local runs (this container: Python 3.13, root, no bubblewrap, socat or Docker):**

| Command | Result |
|---|---|
| `python3 -m unittest discover -s evaluations/phase-3.3/live -p 'test_*.py'` | 60 run, OK, 0 skipped |
| `… -s evaluations/phase-3.2/tests -p test_cc_adapter.py` | 75 run, OK |
| `test_harness.py` / `test_difficulty.py` / `test_scoring.py` | 67 / 68 / 40, OK |
| `tests/test_validators.py`, `tests/test_install.py` | 9 / 14, OK |
| `phase-3.3/dryrun/test_check_results.py`, `boundary/test_check_boundary.py` | 10 / 10, OK |
| `scripts/validate_skills.py`, `manifest.py check-sources` | OK |
| `actionlint .github/workflows/*.yml` | clean |
| `shellcheck evaluations/phase-3.3/live/*.sh` | clean |

ShellCheck on `phase-3.2/harness/*-cc.sh` reports 3 info-level notes (SC1091, SC2329). These files were not touched.

**Mutation checks.** Each guard was removed in turn and its tests failed:
- approval parent check: 1 failure;
- one-file diff check: 1;
- main-workflow equality check: 4;
- incomplete status: 24;
- NDJSON truncation check: 1;
- single-use count: 2;
- `run_attempt` in the guard: 2;
- after the review fixes: non-required problems promoted, 2; walk errors recorded, 1; chunk overlap (token split across reads), 1; size budget, 1.

**The ten required scenarios:**

| # | Scenario | Test |
|---|---|---|
| 1 | Approval only on main, not in the pinned checkout | `test_regression_approval_only_on_main_is_refused_at_the_pinned_commit` |
| 2 | Pinned checkout holds an unfilled approval | the same test, plus `test_the_committed_file_on_this_branch_is_an_unfilled_template` and the rehearsal case `committed-approval` |
| 3 | Approval names the wrong run | `test_approval_naming_another_run_is_refused`. Also covered by `run-live-probe.sh` step 1 and the rehearsal case `unapproved-run` |
| 4 | Prompt, workspace or binary hash changes | `test_changed_hashes_in_the_approval_are_refused`, `test_any_other_file_in_the_approval_commit_is_refused`, `test_two_step_approval_is_refused`, and the existing `test_cc_adapter` approval tests (the launcher recomputes all three) |
| 5 | Missing or incomplete evidence | `test_every_missing_required_file_makes_it_incomplete` (each of 17 files), `test_truncated_and_corrupt_files_are_detected`, `test_unreadable_files_are_detected_required_or_not`, `test_archive_that_does_not_read_back_is_rejected` |
| 6 | A failed run leaves partial captures | `test_a_failed_run_with_partial_captures_is_packed_as_incomplete`, `test_failure_before_the_capture_was_created`, `test_no_operator_store_invents_nothing`, and the rehearsal refusal cases |
| 7 | Evidence packaging fails | `test_archive_write_failure_is_exit_1_and_leaves_nothing`. The workflow step stops when the exit is 1 or the archive is missing (`test_no_suppressed_archive_failure`) |
| 8 | A re-run reuses the authorisation | `GuardScriptTests` (attempt 2 and 10 refused), `test_job_condition`, `test_an_earlier_deployment_refuses_reuse_of_the_approval` |
| 9 | A secret-shaped string in a capture | `test_a_token_shaped_string_is_flagged_and_kept_encrypted_never_printed`, the rehearsal case `token-value` (packager exit 5 required), and the existing launcher token scan |
| 10 | Unexpected branch or event | `test_unexpected_event_branch_or_attempt_stops` runs the guard's own bash for: `pull_request`, `push`, `pull_request_target`, `workflow_run`, feature branch, PR merge ref, tag, `main2`, a wrong run id or confirmation, the placeholder pin |

**CI on the exact head:** see the PR #4 checks and the record appended below. The packager rehearsal against real launcher output runs **only on the GitHub runner**, because this container lacks bubblewrap, socat and Docker. Until that run is green, the required-file list is supported only by reading the code.

**Evidence levels:**
- **Verified directly here:** the approval-commit logic on real git repositories; the packager on synthetic trees; the guard's bash; the workflow's structure; the documentation quotes (fetched).
- **Mock tests only:** unreadable files, which are simulated because the tests run as root; a corrupt archive write.
- **Real CLI against a fake API** (unchanged from PR #3; CI artifact of `619101e`): the credential boundary and the probe verdict.
- **Unverified until live:** authentication; the real event values; network needs; model compliance; revocation; and the three GitHub behaviours listed in LIVE-PROBE.md §7.

## E. Credential safety

See LIVE-PROBE.md §5 for the sources and quotes. In short:
- **Documented:**
  - one-year token, which can only make model requests and is saved nowhere;
  - account-wide **Log Out** (Settings › Account) signs out "tokens created with setup-token for continuous integration (CI)", and does not affect API keys;
  - per-token removal in Settings › Claude Code, documented for "authorization tokens" generally.
- **Not documented:**
  - that setup tokens appear in that list;
  - that removing one invalidates it on the server;
  - whether such tokens can draw usage credits;
  - any validity check without a model request.
- **Cannot be verified without spending:** server-side invalidation. Only the UI state can be checked.
- **Owner instructions:**
  - note the token list before creating the token, and check whether a new entry appears;
  - turn credits off;
  - after the run, remove the entry **and** use account-wide Log Out;
  - on any exposure signal, Log Out at once.
- **Remaining one-year risk:**
  - **None documented** if account-wide Log Out is done.
  - **Up to one year** if only the targeted removal is used and the token was never listed. The procedure therefore requires Log Out in that case.

## F. Owner checklist

This is LIVE-PROBE.md §6, steps 1-11, which hold the exact commands:
1. Review P. Green CI **on P**.
2. Confirm the approved values.
3. Configure the environment: reviewer, admin bypass off, `main` only, **no prior deployments**.
4. Make approval commit X on P. Fill only `approved_by`, `approved_utc`, `reviewed_commit`. Run `check_approval_commit.py` locally; it must print VERIFIED. Push the branch and keep it.
5. Open the one-file bootstrap PR to `main`: X's workflow with `AQD_TEST_SHA: "<X>"`. The `diff` must be empty. Merge it yourself.
6. Run a mock dispatch from `main`. It must be green.
7. Make the credential decisions: revocation method; credits off.
8. Write the authorisation, naming the run id, X, P, the CLI hash and the prompt hash.
9. Create the token. Add the token and the passphrase as **environment** secrets.
10. Dispatch once with the exact inputs, and approve the deployment.
11. Afterwards:
    - delete the secret;
    - remove the token entry **and** Log Out of the account;
    - check usage;
    - decrypt offline and read `evidence-manifest.json` first.

## G. Adversarial review of this conclusion

- **Security engineer.** "The approval file proves nothing about *who* approved; anyone with push access can write `approved_by`."
  - True. The approval file is a binding of values, not an identity proof.
  - Identity comes from GitHub: only someone who can merge to `main` can set the pin, and the environment's required reviewer must approve the deployment.
  - **Accepted.** Signed commits would add identity, but the owner does not currently sign them.
- **Security engineer.** "The single-use check relies on undocumented timing of deployment records."
  - If GitHub created the record after the steps start, the count would be 0 and the job would refuse.
  - If it created records for skipped jobs, the count could be 2 and the job would refuse.
  - Both outcomes refuse before the token is written, so the failure mode is a wasted approval round, not a leak. **Mitigated (fail closed) but unverified.**
- **CI/CD maintainer.** "The anonymous `git fetch` of `github.workflow_sha` breaks if the repository becomes private."
  - It fails closed. **Accepted.** If the repository is made private, `persist-credentials` or the fetch must be revisited in a reviewed amendment.
- **CI/CD maintainer.** "If the approval branch holding X is deleted, X may become unfetchable."
  - The checkout then fails before any secret is used. **Mitigated** by the instruction to keep the branch.
- **CI/CD maintainer.** "The required-file list was written from reading the launcher. If the real launcher omits one file in a valid run, every live run is labelled INCOMPLETE."
  - The rehearsal's clean case now requires *complete* on the real launcher output (mock CLI). **Blocking until** the PR #4 CI rehearsal is green; see the record below.
- **Experimental statistician.**
  - The probe could leak into the 24-run analysis. It cannot: `analyze.py` refuses `PROBE-CC` records, and the probe's schedule is separate (`probe-schedule.json`, seed derived from a fixed string).
  - The probe is the control arm only. That is right for a credential test, but it says nothing about treatment delivery. Treatment delivery (`--plugin-dir`) was tested offline only, and must be covered by the separate two-arm SMOKE step before the A/B run.
  - **Accepted, by design.**
- **Cost-conscious owner.**
  - Worst case: one session of `claude-opus-5-5`, medium effort, with up to 200 turns and a 2700 s timeout. That can still use a meaningful part of a usage window if the model ignores "run `sh probe.sh` once".
  - The strict verdict fails the probe, but the usage is already spent.
  - **Accepted**, with usage credits off. A smaller `--max-turns` for the probe was considered and rejected, because it would change the pre-registered harness parameters that the preflight binds.
