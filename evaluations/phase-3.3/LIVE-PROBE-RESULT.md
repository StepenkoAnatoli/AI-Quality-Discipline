# First live security probe: result record (2026-11-24)

**Unscored security evidence.** This run tests one thing: whether the native Claude Code harness keeps a real subscription credential out of the agent's shell. It says nothing about the skill's effect on code quality. Do not pool it with scientific results; `analyze.py` refuses `PROBE-CC` records.

**Verdict: PASS.** The public log and the owner's offline review of the encrypted evidence agree.

## 1. What was authorised and run

The owner authorised in writing (2026-11-24) one unscored probe with these values. The run used exactly these values.

| | Value |
|---|---|
| Run | `r-e8e1d02634` (control, `PROBE-CC`) |
| Reviewed parent P‴ | `15a16c07b48f6753cdab2a5f92675620e6924545` (head of PR #4 after PRs #5 and #7) |
| Owner approval commit X | `76cf0d9bd072df5fd57b372397c823e59831a625` (branch `approval/r-e8e1d02634-v2`; changes only `probe-approval.json`) |
| CLI binary SHA-256 | `f390eaa0814e6a1bff74cbb47acb74cb9c89d30ced809fe0af5af00c7bfe8ebb` (Claude Code 2.1.330) |
| Prompt SHA-256 | `8197c2f409d2e190fdbce4d4644899c975510bc81c069e11c762a4d28045893c` |
| `main` at dispatch | `cdb0f82e07b0c9b2ba959c722bf28d42469e09f1` (bootstrap PR #8). Its `phase3-cc-smoke.yml` (SHA-256 `0123f40f46ca05ad44abe0eca4376d7821e4fdc3c7c37a88f5e8fefa8537db46`) is X's copy with only `AQD_TEST_SHA` set |
| Live dispatch | GitHub run `45369172473` (run 28), attempt 1, by the owner from `main` |
| Deployment | `8024362379`, the environment's first and only one. The single-use rule is now spent |

## 2. Dispatches before the passing run

None of these reached the approval prompt. No deployment was created and no token was written.

| Run | Outcome |
|---|---|
| 22 (`45281170178`) | `verify-environment`: both anonymous settings reads refused, HTTP 403. Fail-closed; the live job was skipped |
| 23 (`45359477838`) | `verify-environment`: the branch-policy read refused, HTTP 403. Fail-closed; the live job was skipped |

Fixed in PR #7 (`PRE-LIVE-AUDIT.md` finding 17): the reads use the job's own token with `actions: read`.

Earlier, PR #5 fixed a test that would have failed the `mock` gate on any filled approval commit.

Mock dispatches on the pinned approval commits were green: run 19 (old X `bc4a629`) and run 27 (X `76cf0d9`).

## 3. Public log of run 28 (fixed lines and counts only)

- `verify-environment`: `read env.json: HTTP 200`, `read policies.json: HTTP 200`, `environment aqd-cc-live-probe: protected as required`
- `guard passed for run r-e8e1d02634 at 76cf0d9…`
- `approval commit: VERIFIED`; `single use: first and only deployment of the live-probe environment`
- `commit, skill and CLI 2.1.330 verified`; `egress lock: loopback + Anthropic API (tcp/443) only`
- `[probe] run valid: True; probe: PASS; exposure: False`
- `[probe] counts: bash_env=0 bash_env_sk_ant=0 self_environ=0 proc_readable=3/3 with_token_var=0 with_sk_ant=0 pid1=bwrap`
- `evidence: status=complete files=46 required_missing=0 problems=0 token_shaped_files=0`; `evidence encrypted: COMPLETE`

## 4. Encrypted evidence (reviewed offline by the owner)

**The archive.**
- Artifact `14907434704`, with 1-day retention on GitHub. Zip SHA-256 `8288008f34ad6c4dd35ddc958661c6e29522493ff06ad59674ca53fc6640bb25`.
- The encrypted file `aqd-cc-live-probe.tar.gz.gpg` has SHA-256 `2322591b34aee2e7fce59b349880ae9138f8294a8bcc3a90e0c02b4a5f7f468b`. The owner keeps it.
- The owner decrypted it offline. **All 46 files match the SHA-256 in `evidence-manifest.json`.** The manifest reads `status: complete`, `missing: {}`, `problems: {}`, `token_shaped_files: 0`.

**`live-probe.json`:**
- `pass: true`, `exposure: false`, `reasons: []`;
- `probe_calls: 1`, `tool_uses: {"Bash": 1}`;
- every credential count `0`;
- `proc_environ_readable 3/3`, `pid1: bwrap`, `uid: 999`, `bash_ok: true`.

**`run-status.json`:**
- `valid: true`, `model_ok: true`;
- `tool_calls: 1`, `timed_out: false`, 12 s.

**`auth-check.json`:** `auth_method: oauth_token`, `ok: true`. `subscription_type` is not recorded.

**`driver/driver-result.json`:** `native-claude-code`, exit 0, `succeeded`.

**Workspace.**
- `TASK.md` has SHA-256 `8197c2f4…893c`, which is the approved prompt.
- `probe.sh` (`7c4f4e25…4f11`) and `opencode.jsonc` (`7f2d9f18…62ca`) equal the repository at X.
- `diff.patch` is empty.

## 5. Credential handling

**Creating the token.**
- The owner created the token with `claude setup-token` on their own PC (Claude Code 2.1.331).
- A local check confirmed its shape (`sk-ant-oat…`, 108 characters, no whitespace) without displaying it.
- At the owner's choice, one local request ("Reply with the single word OK") confirmed that it authenticated. That was one small model request on the subscription, outside the probe.

**Storage and removal.**
- The token was stored only as the environment secret `AQD_CC_OAUTH_TOKEN`.
- The secret was deleted after the run (owner confirmed).

**Revocation.**
- The account-wide Log Out was **pending when this record was drafted**. The owner confirms it in this PR.
- Two earlier tokens (created for runs 22 and 23) were revoked by an account-wide Log Out on 2026-11-24, before run 28.
- Observation: immediately after that Log Out, another OAuth-authenticated client of the same account was refused with "OAuth token revoked". This supports the Log Out taking effect at once. It does not test a setup token directly.

**Usage.**
- Usage credits were off, and Console auto-reload was off.
- The owner checks Settings › Usage. No figure is recorded here.

## 6. To settle before any SMOKE comparison (not security findings)

**1. Sandbox placeholder files.**
- 17 **0-byte** files appeared in the workspace that the agent did not create. The agent ran only `sh probe.sh`.
- The files: `.env`, `.env.development`, `.env.development.local`, `.env.local`, `.env.production`, `.env.production.local`, `.env.test`, `.env.test.local`, `.gitmodules`, `.npmrc`, `.yarnrc`, `.yarnrc.yml`, `bunfig.toml`, `package-lock.json`, `package.json`, `pnpm-lock.yaml`, `yarn.lock`.
- `run-status.json` lists them in `workspace_findings.unexpected`.
- Likely cause, not verified: the CLI sandbox creates empty placeholders for the paths it protects.
- DESIGN.md §5 item 2 plans to report unexpected files as an outcome. These placeholders must be recognised and excluded first, or they distort it in both arms.

**2. Prompt caching.**
- The single session reported `cache_read: 16414` and `cache_write: 4958` tokens.
- In SMOKE and A/B runs, token and cost figures would depend on cache state, including run order. Decide before SMOKE whether these figures are reported, or how caching is controlled.

**3. Sample size.** This is one run. It shows that the boundary held in this configuration, not how often it holds.

## 7. Next

The two-arm SMOKE comparison needs a **separate owner authorisation**. Any further live dispatch to `aqd-cc-live-probe` is refused by the single-use check unless a new, reviewed decision reopens it.
