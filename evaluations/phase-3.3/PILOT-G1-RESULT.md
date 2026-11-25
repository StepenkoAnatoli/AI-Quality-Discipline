# G1 invocation pilot: result record (2026-11-25)

**A harness check with one recorded measurement, never scored.** It asks only whether the agent invokes the `code-discipline` skill when it is available on realistic tasks (`PILOT-G1.md`). No hidden test ran and nothing about code quality was measured or compared. These records are never pooled with any scientific result.

**Harness verdict: PASS. Measurement: the agent *called* the skill in 3 of 3 valid treatment runs.** The public log and the owner's offline review of the encrypted evidence agree.

**Correction (2026-11-25, after `PILOT-G1-AUDIT.md`):** "invoked" counts Skill tool *calls*, not successful loads of the skill text, and ignores timing. An earlier version of this record said the agent "loaded" the skill; that was not established. Whether each call loaded the skill, and before the first edit, is settled offline with `live/inspect_invocation.py` on the decrypted evidence (§8).

**Owner decision (2026-11-25), from this result:** `STAGE0-PLAN.md` D1 = **(a) availability**.

## 1. What was authorised and run

The owner authorised in writing (2026-11-25) one dispatch with these values. The run used exactly these values.

| | Value |
|---|---|
| Runs (schedule order) | `r-49a8ed9516` (NEW-04, treatment), `r-b77ae663bf` (NEW-04, control), `r-2467089ae3` (NEW-02, control), `r-3dbe15e184` (NEW-02, treatment), `r-bc23637fc1` (NEW-03, treatment), `r-6568760496` (NEW-03, control) |
| Schedule | `live/pilot-schedule.json`, SHA-256 `bad87ea676f335e605bf39afcab82c9b0f9f44cc4482ee883d1b079dd0425f16` |
| Reviewed parent P | `4aacb59364509a9e2ff455ba2282bf35c36f5c20` (head of PR #4 after PR #13) |
| Owner approval commit X | `f180f93fdcf009e974bbc8b3197130c316e953ea` (branch `approval/pilot-g1`; changes only `pilot-approval.json`) |
| CLI binary SHA-256 | `f390eaa0814e6a1bff74cbb47acb74cb9c89d30ced809fe0af5af00c7bfe8ebb` (Claude Code 2.1.330) |
| Prompt SHA-256 | NEW-02 `9c4bde140efbacabf564f3307aa16955efb869d0dc6a3b354bb8322a727a543f`; NEW-03 `a5764db416e9848f7b6d51f06948b5110a6785013903260892942d3a042f649b`; NEW-04 `a50a09d169767c51111c1dbd7729c2ee401791541ba21b9ce5237e6240594b93` |
| `main` at dispatch | `af92f8d7ffec964bc8c457badcb651bf3e3aa812` (bootstrap PR #14). Its `phase3-cc-smoke.yml` (SHA-256 `66375865b614f5353cf088e1b1800b76a7e2cf7f23a06b0a63d558cafb128fdb`) is X's copy with only `AQD_TEST_SHA` set |
| Mock dispatch on X | run `45587365101` (run 43): green, with the rehearsals on X: probe 7/7, SMOKE 10/10, pilot 6/6 |
| Live dispatch | GitHub run `45590046460` (run 44), attempt 1, by the owner from `main` |
| Environment and deployment | `aqd-cc-live-pilot` (checked by the owner's pasted settings and by `verify-environment` in the run). Deployment `8054265669`, the first and only one; its single use is spent |

## 2. Public log of run 44 (fixed lines and counts only)

- `verify-environment`: success.
- The guard passed for the six pilot run IDs at X.
- `approval commit: VERIFIED`: the checker came from P, with `--approval-path pilot-approval.json` and `main`'s workflow.
- Single use passed for `aqd-cc-live-pilot`.
- `commit, skill and CLI 2.1.330 verified`; egress lock applied (loopback and the Anthropic API on tcp/443 only).
- Every run: launcher exit 0. No timeout. The runs took place between about 10:07 and 10:21 UTC.
- `[pilot] invocation: skill invoked in 3 of 3 valid treatment runs`.
- `[pilot] harness verdict: PASS; reasons: 0`.
- Evidence: `status=complete`, 293 files, `token_shaped_files=0`; encrypted.

## 3. Encrypted evidence (reviewed offline by the owner)

**The archive.**
- Artifact `15012361922`, with 1-day retention on GitHub. Zip SHA-256 `08f6e0bf0108be09073c693fbe85cb358683802e60fa7a7e6394b8b0bcacc143`.
- The encrypted file has SHA-256 `aa447ae11e69f028d85bddfa014a387d47f6c84f50fb2ae0e751f467e2981bc3`. The owner keeps it.
- The owner decrypted it offline. **All 293 files match the SHA-256 in `evidence-manifest.json`**, and the manifest reads `status: complete`.

**`pilot-verdict.json`:** `harness_pass: true`, `reasons: []`, `invocation: {invoked: 3, valid_treatment_runs: 3}`, with every task `true` in `by_task`.

| Run | Task, arm | Skill invoked | Tool calls | Cache read (tokens) | Duration |
|---|---|---|---|---|---|
| `r-49a8ed9516` | NEW-04, treatment | **yes** | 7 | 176,346 | 196 s |
| `r-b77ae663bf` | NEW-04, control | no (not available) | 6 | 154,918 | 163 s |
| `r-2467089ae3` | NEW-02, control | no (not available) | 6 | 116,410 | 93 s |
| `r-3dbe15e184` | NEW-02, treatment | **yes** | 7 | 100,913 | 99 s |
| `r-bc23637fc1` | NEW-03, treatment | **yes** | 9 | 107,696 | 100 s |
| `r-6568760496` | NEW-03, control | no (not available) | 9 | 141,149 | 103 s |

**Every run:** valid with `model_ok`; signed in with the subscription token; its scheduled arm (control: only `doctor`, `NOT_APPLICABLE`; treatment: `aqd-arm:code-discipline` and `doctor`, `AVAILABLE`); no symlink or special-file findings; 17 unexpected files (the known sandbox placeholders); not timed out.

## 4. Credential handling

- **Token creation:** a fresh token from `claude setup-token`, shape-checked locally (length 108, `sk-ant-oat` prefix, no whitespace) and stored only as the environment secret of `aqd-cc-live-pilot`.
- **After the run (owner confirmed):**
  - the token secret was deleted;
  - the account-wide **Log out of all devices** was done.
- **Billing settings:** usage credits were off.
- **Not reported:** a check of Settings › Usage after this run.

## 5. Findings

1. **Invocation on realistic tasks.** The agent called the skill in every treatment run (3 of 3), against 0 of 1 on the one-line SMOKE task. This is the G1 answer and the basis of the D1 decision (§7). Whether each call loaded the skill text, and when, is open (§8).
2. **The controls stayed clean.** No control run listed or used the skill.
3. **Prompt caching is larger on realistic tasks.** Cache reads were about 100 k to 176 k tokens per run, against about 28.7 k in SMOKE. This strengthens finding F2 of `STAGE0-PLAN.md`: token and cost figures depend on cache state and run order (D3).
4. **Placeholders.** All six runs had the same 17 sandbox placeholders, as before. H1 (exclude them by name and size) is still needed before "unexpected files" becomes an outcome.
5. **Time.** The longest run took 196 s, far below the 45-minute timeout, and the six runs fit well inside one job.

## 6. What this does and does not establish

**Established:**
- With the skill available, the agent issued a Skill call naming it on each of the three realistic public tasks tried.
- The pilot job, its single-use environment and its evidence chain worked end to end, as for the probe and SMOKE.

**Not established:**
- **an invocation rate.** Three runs, one per task, give a coarse signal, not an estimate. Stage 1 records invocation per run and reports it;
- whether each call actually loaded the skill text, and whether it did so before the first edit (§8);
- whether the agent *followed* the skill;
- any effect of the skill on correctness or quality. No hidden test ran; the tool counts, tokens and durations above are recorded, **not compared** between arms;
- how the agent behaves on the new, private Stage 0 tasks.

## 7. Decision recorded

Following the decision rule in `PILOT-G1.md` §3 (3 of 3 suggests availability), the owner chose on 2026-11-25:

- **D1 = (a) availability:** the skill installed as users get it. Invocation is recorded per run and reported alongside every result.
- No exposure arm (D1(b) or (c)), so no treatment-only system-prompt change to the harness is needed.

The next gate is G2 (`STAGE0-PLAN.md` §5). It needs the people of D5 named first.

## 8. Open check from the audit (`PILOT-G1-AUDIT.md`)

D1 (a) was chosen on "called in 3 of 3". The audit showed that a failed or late call counts the same. The owner runs `live/inspect_invocation.py` once on the decrypted pilot evidence (offline, read-only, booleans and counts only) and the result is recorded here:

| Result | Consequence |
|---|---|
| loaded 3, loaded before the first edit 3 | D1 (a) stands as stated |
| loaded 3, fewer before the first edit | D1 (a) stands; the timing is recorded with it |
| fewer than 3 loaded | "3 of 3" overstated the signal: revisit D1 under `PILOT-G1.md` §3, applied to loaded runs |
| any `disagrees_with_harness=True` | stop and investigate before relying on either number |

**Result:** not yet run.
