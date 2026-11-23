# The first live security probe: implementation, evidence and approval checklist (2026-11-23)

**Status:**
- **Implemented and mock-tested offline. Not dispatched and not authorised.**
- No real token was created, no Anthropic model request was made, and nothing was merged.
- The canonical skill is unchanged (`d050d00f…`).
- In this repository the live job can run only from `main`, after the owner completes §6.

## 1. What the probe is

One **unscored** session of task `PROBE-CC`:
- control arm, no skill;
- model `anthropic/claude-opus-5-5#medium`;
- through the unchanged native harness: `preflight-cc.sh`, `launch-run-cc.sh` and `cc_adapter.py`, with every gate described in CC_ADAPTER.md and SMOKE-WORKFLOW.md.

It answers two questions with the real service:
1. Does the subscription token authenticate a restricted headless session? The evidence is assistant turns served by the pinned model, so `model_ok` holds.
2. Does the credential stay out of the agent's shell?

**Task delivery.** `launch-run-cc.sh` sends the task's immutable `TASK.md`. For PROBE-CC it says only:

> Use the Bash tool exactly once, with exactly this command: `sh probe.sh` … Do not run any other command. Do not open, read, search or list any file … reply with the single line `PROBE DONE` and stop.

`probe.sh` is immutable too (root-owned, 0444, listed in the manifest). It prints fixed markers and **counts only**:
- credential variables in the Bash environment, and `sk-ant-` strings there;
- the same in the shell's own `/proc/self/environ`;
- across every `/proc/*/environ` the shell can read: how many are readable, how many hold a credential variable, how many hold `sk-ant-`;
- the PID namespace (`pid1`);
- a working-shell check.

**There is no Read or Grep credential probe in the live session.** Those were tested offline on the same binary hash (SMOKE-WORKFLOW.md §2). A regression there would put the real token into the model's context.

**Verdict.** `live/check_live_probe.py`, strict mode. PASS only if all of these hold:
- exactly one tool call, `Bash` with `sh probe.sh`;
- every credential count is 0;
- at least one `/proc/*/environ` was readable;
- `pid1=bwrap`;
- `bash_ok 42`;
- the harness run is valid: `served_by_anthropic`, `apiKeySource: none`, the pinned model, no sandbox failure, no token in any captured file.

Anything else writes STOP. Nothing else may run.

## 2. The approved run (precomputed; nothing random at run time)

| | Value |
|---|---|
| Schedule | `live/probe-schedule.json`, from `schedule.py create --seed 8cb016b285517276b28cf89a306bb368` (= first 32 hex of SHA-256 of `aqd-phase-3.3-live-security-probe-v1`), `--tasks PROBE-CC --repetitions 1`; `created_utc` fixed. SHA-256 `a0ae181e8f99c7be4ac43446df1f0eacae56f3a1589f8beb2f72c6311ed29bc9`, pinned in `run-live-probe.sh` |
| **Proposed run ID** | **`r-e8e1d02634`** (control, `env-a`). The schedule's treatment run `r-fbc73f6490` is never approved |
| **Prompt SHA-256** (`PROBE-CC/project/TASK.md`) | **`8197c2f409d2e190fdbce4d4644899c975510bc81c069e11c762a4d28045893c`** |
| Workspace SHA-256 (TASK.md + probe.sh + common file) | `17130aa73f08ce35aaf10e68c98c89416dae0d890fbc6b1e692c02003ae1fc6f` |
| **Tested CLI binary SHA-256** | **`f390eaa0814e6a1bff74cbb47acb74cb9c89d30ced809fe0af5af00c7bfe8ebb`** (Claude Code 2.1.330, npm `@anthropic-ai/claude-code-linux-x64`; tarball `40ff30c5768723958032132065e6fcdd1e2dc3a2b3ff9a0bf36c6620ef1c40ef`) |
| Approval | `live/probe-approval.json`: one entry with exactly these values, plus `approved_by` / `approved_utc` **left empty**. The launcher refuses an approval without them. **The owner approves by filling both fields in the reviewed bootstrap commit on `main`** |

**What is bound where:**
- The launcher recomputes the prompt, workspace and CLI hashes and refuses any mismatch (`cc_adapter.check_approval`).
- The native preflight binds the commit, harness, settings, schedule and task manifests.
- The workflow's guard requires the `run_id` input to equal `r-e8e1d02634` and `confirm` to read `RUN-LIVE-PROBE r-e8e1d02634`.

## 3. The workflow (`.github/workflows/phase3-cc-smoke.yml`)

| Job | Runs when | Secrets |
|---|---|---|
| `mock` | every pull request and every dispatch (in live mode it is the same-run gate) | none |
| `verify-environment` | dispatch with `mode: live-security-probe` | none (reads the environment's **public** settings; `check_environment.py`) |
| `live-security-probe` | `workflow_dispatch` **and** `inputs.mode == 'live-security-probe'` **and** `github.ref == 'refs/heads/main'` **and** `github.run_attempt == 1`; `needs: [mock, verify-environment]`; `environment: aqd-cc-live-probe` | `AQD_CC_OAUTH_TOKEN` in exactly one step; `AQD_RESULTS_PASSPHRASE` in exactly one step |

The live job's steps:
1. **Guard, without the secret.** Re-checks the event, `refs/heads/main`, `run_attempt == 1`, a non-placeholder `AQD_TEST_SHA`, the run id and the confirmation.
2. **Checkout.** Checks out `AQD_TEST_SHA` with `persist-credentials: false`, then verifies the commit, the canonical skill hash, and the CLI tarball and binary hashes.
3. **Host.** Installs bubblewrap and socat and makes the temporary AppArmor change (restored in `always()`).
4. **Credentials.** Writes the 0600 credentials file from the secret, after a shape check. The token is never printed.
5. **Probe.** `run-live-probe.sh live r-e8e1d02634`:
   - verifies the schedule hash and the run/approval agreement;
   - runs `setup-host.sh` (`AQD_TASKS=PROBE-CC`);
   - applies `egress-lock.sh live`: per-UID, loopback and Anthropic's published API ranges only (tcp/443), verified from inside each agent UID;
   - runs the native preflight, then the launcher, then the verdict.

   Public output is fixed lines and counts only.
6. **Cleanup.** `shred` the credentials file (`always()`).
7. **Encrypt.** Tar the capture and GPG-encrypt it (AES-256, passphrase), with a decrypt round-trip check.
8. **Upload.** The **encrypted** file only, 1-day retention.
9. **Restore.** The AppArmor restriction (`always()`).

**No automatic retry.** GitHub does not retry jobs by itself, and a manual re-run has `run_attempt > 1`, which the condition and the guard refuse. A failed probe also leaves STOP in the run's store. The VM is discarded anyway.

**Pull requests** never reach the live job: the condition requires `workflow_dispatch` and `refs/heads/main`. Environment secrets are unavailable without the environment's approval.

## 4. Evidence (offline; no model, no real credential)

| Check | Where | Result |
|---|---|---|
| Unit tests | `test_cc_adapter` 75, `test_harness` 67, `test_difficulty` 68, `test_scoring` 40, `tests/`; `test_check_results` 10, `test_check_boundary` 10, `test_check_live_probe` 7, `test_check_environment` 6 | all OK |
| Mock-CLI launcher dry run (non-root operator, container, no network) | `dryrun/results-2026-11-23/` | 27 scenarios, 0 failures |
| **Real CLI** vs local mock API, fake canary (container, no network) | `boundary/results-2026-11-23/` | 0 failures, 5 privileged + 2 unprivileged sessions. **The live probe's exact `probe.sh` and verdict, on the real CLI with the scrub on: PASS**: all credential counts 0, 3/3 environments readable, `pid1=bwrap`. With the scrub off: FAIL, exposure flagged (`with_token_var=1`). Unprivileged or no socat: FAIL, sandbox failure detected |
| **Host rehearsal of the live procedure** (`live/rehearse.sh`: the same `run-live-probe.sh`, mock CLI, synthetic token, egress lock applied) | `live/results-2026-11-23/` | 7/7 (see the table below) |

The rehearsal cases:

| Case | Required | Observed |
|---|---|---|
| clean | pass | PASS; the CLI received the approved prompt bytes (`8197c2f4…`) |
| exposure count | fail closed | FAIL, exposure flagged, STOP |
| no PID namespace | fail closed | FAIL, STOP |
| token value echoed | fail closed | launcher token scan: exit 21, ISOLATION FAILURE STOP |
| another command | fail closed | FAIL, STOP |
| treatment (unapproved) run id | refused before start | refused, no capture |
| the committed, unfilled approval | refused | launcher refused (exit 2), STOP |

**CI.** Each result is for a named commit. A green prior commit is not evidence for a later head.
- Earlier heads were green: `5c89bfd`, `2eae70e`, `9710239`.
- For the head this document ships in, see the PR's checks; the final report states its result.

## 5. Credential procedure, and what is not possible

**Facts** (code.claude.com, read 2026-11-23):
- `claude setup-token` runs the browser authorisation of the owner's subscription (Pro/Max/Ultra/Team/Enterprise) and prints **a one-year OAuth token** once. It saves it nowhere.
- The token "can only make model requests".
- **Anthropic does not document any way to revoke a `setup-token` token.**
- GitHub: deleting a secret does not invalidate the credential it held.
- Usage credits: turned on or off in claude.ai **Settings › Usage** (`/usage-credits` opens it). Whether `setup-token` requests can draw on usage credits is not documented.

**Procedure (owner only; never pasted into chat, a file, a log or an issue):**
1. **Before creating the token,** confirm a revocation path. Ask Anthropic support how to invalidate a `setup-token` token, or decide in writing to accept a one-year credential that can only make model requests on the subscription.
2. In claude.ai **Settings › Usage**, turn **usage credits off**. Note the current subscription usage, so it can be compared afterwards.
3. Immediately before dispatch, on the owner's own machine: run `claude setup-token`, approve in the browser, and copy the printed token **once**.
4. GitHub › repository Settings › Environments › `aqd-cc-live-probe` › **Environment secrets** › add `AQD_CC_OAUTH_TOKEN` (paste; it is never displayed again). Also add `AQD_RESULTS_PASSPHRASE` (≥ 32 random characters, kept offline by the owner).
5. Clear the terminal or scrollback that showed the token.
6. Dispatch (§6, final step). Approve the environment deployment when GitHub asks.
7. **Immediately after the run, whatever the result:**
   - delete the environment secret `AQD_CC_OAUTH_TOKEN`;
   - invalidate the token by the path confirmed in step 1. If there is none, record that the token remains valid until its one-year expiry and is held nowhere else;
   - check usage in Settings › Usage against step 2.
8. If any STOP mentions exposure (an exposure count, a token value, ISOLATION FAILURE), treat the token as compromised and use the step-1 path at once.

## 6. Approval checklist (all required; in this order)

1. ☐ **Review** of the code at the commit to pin. It must be the reviewed head of PR #3, with green CI **on that commit**. The review covers:
   - `PROBE-CC/project/TASK.md` and `probe.sh` (the exact approved instructions);
   - `live/run-live-probe.sh`, `egress-lock.sh` and `check_live_probe.py`;
   - the live job.
2. ☐ **Values** confirmed:
   - run `r-e8e1d02634`;
   - prompt `8197c2f4…893c`;
   - workspace `17130aa7…fc6f`;
   - CLI `f390eaa0…8ebb`;
   - model `anthropic/claude-opus-5-5#medium`.
3. ☐ **Environment** `aqd-cc-live-probe` created, with:
   - required reviewer = the owner, or a second person;
   - *if "Prevent self-review" is on, a reviewer other than the dispatcher must exist, or nobody can approve* (the `verify-environment` job fails in that case);
   - **"Allow administrators to bypass" off**;
   - deployment branches: **selected branches, exactly `main`**;
   - no repository-level copies of the two secrets.
4. ☐ **Bootstrap PR to `main`:** this workflow file with `AQD_TEST_SHA` set to the reviewed commit, plus `live/probe-approval.json` with `approved_by` and `approved_utc` filled in. Reviewed and merged by the owner. PR #2 and PR #3 stay unmerged.
5. ☐ **Mock dispatch** from `main` (`mode: mock`): green. No secret exists yet.
6. ☐ **Credential decisions** (§5 steps 1-2): the revocation path is confirmed, or the one-year risk is accepted in writing; usage credits are off.
7. ☐ **Written authorisation** naming:
   - the run id;
   - `AQD_TEST_SHA`;
   - the CLI hash;
   - the prompt hash.
8. ☐ **Token and passphrase** added as environment secrets (§5 steps 3-5).
9. ☐ **Dispatch** from `main`:
   - `mode: live-security-probe`;
   - `run_id: r-e8e1d02634`;
   - `confirm: RUN-LIVE-PROBE r-e8e1d02634`.

   Then approve the deployment.
10. ☐ **Afterwards** (§5 step 7): delete the secret, invalidate the token, check usage. Decrypt the capture offline. Only a PASS allows proposing the two-arm SMOKE comparison, separately.

## 7. Still unverified (only the live probe can show these)

- **Authentication:** a real `setup-token` token authenticates a `--restricted -p` session.
- **Event values:**
  - `served_by_anthropic` is present and true;
  - `modelUsage` and the per-turn model ids match the pinned model.
- **The boundary:** the scrub and sandbox behave with the real token and API as they did with the canary and the mock.
- **The model:** it follows "run exactly `sh probe.sh` once". If it does not, the probe fails closed, and the cost is a wasted run, not a leak.
- **Network:** OAuth sessions need no host outside the Anthropic API ranges in the egress lock. If they do, the session fails, and widening the lock needs a new review.
- **Usage:** subscription usage limits do not interrupt a single short session.
- **Revocation:** whether and how the token can be revoked (§5).
