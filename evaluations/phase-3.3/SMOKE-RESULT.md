# Two-arm SMOKE run: result record (2026-11-24)

**A harness check, never scored.** It tests whether the native Claude Code harness runs both arms correctly against the real service. It says nothing about the skill's effect on code quality: one one-line task, one run per arm, and the treatment arm did not invoke the skill. `analyze.py` refuses `SMOKE` records.

**Verdict: PASS.** The public log and the owner's offline review of the encrypted evidence agree.

## 1. What was authorised and run

The owner authorised in writing (2026-11-24) one dispatch with these values. The run used exactly these values.

| | Value |
|---|---|
| Runs (schedule order) | `r-709f207e78` (treatment, `env-a`), then `r-2cffa4db9c` (control, `env-b`), task `SMOKE` |
| Reviewed parent P | `7ea1ae676f485ba6140619c6527c698b400b8a01` (head of PR #4 after PR #10) |
| Owner approval commit X | `bcc7edd670c61e9043d8aea1e89fd6c77172af3c` (branch `approval/smoke-r-709f207e78`; changes only `smoke-approval.json`) |
| CLI binary SHA-256 | `f390eaa0814e6a1bff74cbb47acb74cb9c89d30ced809fe0af5af00c7bfe8ebb` (Claude Code 2.1.330) |
| Prompt SHA-256 | `21de334c06fd4ee31e30a6283202a8c353c4d266b042c36ab56175e9cd73f86d` (SMOKE `TASK.md`) |
| `main` at dispatch | `29e3056047b8e8d593061c7a898b4a2ecf568a04` (bootstrap PR #11). Its `phase3-cc-smoke.yml` (SHA-256 `cb36ae60d45a71cb477a14c80c5b10669d994811c6a52eba0a0d8fc4cd2bf99a`) is X's copy with only `AQD_TEST_SHA` set |
| Mock dispatch on X | run `45482260799` (run 35): green, with SMOKE rehearsal 10/10 on X |
| Live dispatch | GitHub run `45485434793` (run 36), attempt 1, by the owner from `main` |
| Environment and deployment | `aqd-cc-live-smoke` (checked by the owner's pasted settings and by `verify-environment` in the run). Deployment `8040565073`, the first and only one; its single use is spent |

## 2. Public log of run 36 (fixed lines and counts only)

- `verify-environment`: success.
- `guard passed for SMOKE runs r-709f207e78 r-2cffa4db9c at bcc7edd…`.
- `approval commit: VERIFIED`: the checker came from P, with `--approval-path smoke-approval.json` and `main`'s workflow.
- Single use passed. The line printed `…deployment of the live-probe environment`: a wording bug, since the check itself filtered and verified `aqd-cc-live-smoke`. Fixed with this record (§5).
- `commit, skill and CLI 2.1.330 verified`; `egress lock: loopback + Anthropic API (tcp/443) only`.
- `[smoke] run r-709f207e78: launcher exit 0`; `[smoke] run r-2cffa4db9c: launcher exit 0`.
- `[smoke] r-709f207e78 treatment: pass=True valid=True activation=AVAILABLE invoked=False notes_ok=True placeholders=17 cache_read=28666 cache_write=6565`.
- `[smoke] r-2cffa4db9c control: pass=True valid=True activation=NOT_APPLICABLE invoked=False notes_ok=True placeholders=17 cache_read=28677 cache_write=6570`.
- `[smoke] verdict: PASS; reasons: 0; placeholders differ between arms: False`; `SMOKE PASSED`.
- `evidence: status=complete files=84 required_missing=0 problems=0 token_shaped_files=0`; `evidence encrypted: COMPLETE`.

## 3. Encrypted evidence (reviewed offline by the owner)

**The archive.**
- Artifact `14962974761`, with 1-day retention on GitHub. Zip SHA-256 `955951325831c0850ade302f6ebb7e603078d9752d6c0d54911f45aafc867168`.
- The encrypted file `aqd-cc-live-smoke.tar.gz.gpg` has SHA-256 `cc197b5f766cba7c96e0d5d368b87decdc2f19fbdac562a7950f34c529b58fe9`. The owner keeps it.
- The owner decrypted it offline. **All 84 files match the SHA-256 in `evidence-manifest.json`.** The manifest reads `kind: smoke`, both run IDs, `status: complete`, `missing: {}`, `problems: {}`, `token_shaped_files: 0`.

**`smoke-verdict.json`:** `pass: true`, `reasons: []`, `placeholders_differ: false`.

| | Treatment `r-709f207e78` | Control `r-2cffa4db9c` |
|---|---|---|
| valid, `model_ok` | true, true | true, true |
| skills available | `aqd-arm:code-discipline`, `doctor` | `doctor` |
| activation; skill invoked | `AVAILABLE`; **no** | `NOT_APPLICABLE`; no |
| `notes.txt` reads `ok` | yes | yes |
| tool calls | `Bash` 2 | `Bash` 2 |
| tokens: input / output / cache read / cache write | 6 / 330 / 28,666 / 6,565 | 6 / 340 / 28,677 / 6,570 |
| duration | 16 s | 16 s |
| unexpected files | the 17 known zero-byte sandbox placeholders | the same 17 |

**Authentication (`auth-check.json`, both runs):** `auth_method: oauth_token`, `ok: true`.

## 4. Credential handling

- **Token creation:** the owner created a fresh token with `claude setup-token`, checked its shape locally (`sk-ant-oat…`, no whitespace) and stored it only as the environment secret of `aqd-cc-live-smoke`.
- **Passphrase:** the evidence passphrase is the same as the probe's, stored as that environment's own secret.
- **After the run (owner confirmed):**
  - the token secret was deleted;
  - the account-wide **Log out of all devices** was done;
  - Settings › Usage was checked.
- **Billing settings:** usage credits were off.

## 5. Findings and corrections

1. **Single-use message (wording only).**
   - `check_single_use.py` printed "the live-probe environment" whatever `--name` it checked.
   - The behaviour was correct: in run 36 the query and the check both used `aqd-cc-live-smoke`.
   - Fixed here: the line now names the checked environment, with a test.
2. **Placeholders in both arms, identically.**
   - Both arms ran Bash (2 calls each, probably to write `notes.txt` and read it back), so this run cannot tell whether the placeholders depend on Bash use.
   - The flag-not-fail rule (D3) remains for runs where only one arm uses Bash.
   - Excluding them properly is still needed before "unexpected files" becomes an outcome (`DESIGN.md` §5 item 2).
3. **Prompt caching.**
   - Per run, about 28.7 k tokens were read from cache and 6.6 k written, nearly identical across the arms.
   - Token and cost figures in any later comparison depend on cache state, so how caching is handled must be decided before feasibility (D4).
4. **The skill was available but not invoked.** That is allowed by the design (the treatment is availability) and expected on a one-line task, but it means this run carries no information about the skill's effect.

## 6. What this does and does not establish

**Established:** with the real service, the two-arm native harness:
- delivers the skill to treatment only;
- produces valid runs in both arms;
- records both arms the same way;
- keeps the subscription token out of the evidence, end to end, from approval commit to encrypted archive.

**Not established:**
- any effect of the skill;
- feasibility of the larger experiment.

`DESIGN.md` Stage 0 (tasks, oracle review, ratings, plan approval, private delivery, schedule kinds, outcomes, retention) must still be done before any feasibility run. That is a separate owner decision.
