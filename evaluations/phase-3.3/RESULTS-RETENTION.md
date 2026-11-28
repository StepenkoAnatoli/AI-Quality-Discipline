# Results retention

**Problem.** Every Phase 3.2 A/B run uploaded its results only as an encrypted artifact with 1-day retention (`.github/workflows/phase3-ab-run.yml` on `main`). The public log holds status lines only. A day after each run, nothing behind the published numbers in `../phase-3.2/AB-RESULTS.md` could be re-checked (risk R19).

**Status (2026-11-28).**

| Piece | State |
|---|---|
| Public results record (`../phase-3.2/harness/results_record.py`) | Implemented, with tests (`test_scope_retention.py`) |
| Cost capture (`export_checks.py` → `run-status.json` → `analyze.py` process outcome) | Implemented. `null` when the interface reports no per-message cost; never a made-up zero |
| Workflow change on `main`: 90-day retention, record built inside the bundle, its SHA-256 printed in the log | **Prepared, not applied**: `patches/main-phase3-ab-run-retention.patch`. It applies cleanly to `main` at `5a972e3` (`git apply --check`). This session may not push to `main` |
| The four historical A/B runs | Not recoverable from GitHub. On 2026-11-28 GitHub lists no artifact for the NEW-04 run (44980786824); the others expired earlier. A record can be built only if the owner downloaded the bundles before they expired. None will be reconstructed from AB-RESULTS.md, because that would present unverified numbers as data |

## The public results record

```sh
python evaluations/phase-3.2/harness/results_record.py build --schedule SEALED/schedule.json \
    --captures CAPTURES --out RECORD.json [--encrypted-bundle-sha256 HEX] [--workflow-run-id N] [--harness-commit SHA]
python evaluations/phase-3.2/harness/results_record.py check RECORD.json
```

It covers every scheduled slot, including missing and invalid ones:

- **Slot identity:** run id, blind id, order, block, task, arm, model, repetition.
- **Run validity:** invalid reasons are reduced to fixed category codes such as `provider_error`, `scope_violation` and `home_config`.
- **Process measures:** duration, tool calls, token counts, provider-reported cost.
- **Scope:** scope policy, scope violation, and counts of changed, missing and unexpected files.
- **Run-record hashes:** skill, prompt, workspace, global config, install tree.
- **Evaluation:** status, hidden and baseline pass counts, `fully_correct`, `requires_review`, and the inventory and scored-code hashes.

It is whitelist-only. There are no test or check names, no invalid-reason text, no file names, no code, diffs, transcripts or prompts. Field names come from a fixed list. Every string must match a short safe pattern and must not mention hidden tests or file paths. Otherwise `build` writes nothing and `check` fails (exit 3). Hidden-score files are checked for internal consistency with the same code `analyze.py` uses.

## Procedure per scored dispatch (once the patch is on `main`)

1. The workflow builds `public-results.json` **inside the encrypted bundle**. The record pairs conditions with scores, so it is not uploaded in clear: blind secondary scoring must not see it. The log prints its SHA-256 and the bundle's SHA-256.
2. Within 90 days, the operator downloads the encrypted artifact and checks its SHA-256 against the log, then keeps two private copies, for example a local disk and a private cloud folder.
3. After blind scoring, the operator decrypts the bundle and checks `public-results.json` against the logged SHA-256. They run `results_record.py check` and commit the record under `evaluations/<phase>/results/<workflow-run-id>.json`, with the bundle SHA-256 in the report.
4. The report's tables are generated from, or checked against, the committed record.

## Limits

- **Public exposure of the ciphertext.** At 90 days the encrypted file stays downloadable by any signed-in GitHub user for 90 days instead of 1. Security then rests on the passphrase (≥ 32 characters, enforced) and on GnuPG's AES-256 with a slow S2K. Use a randomly generated passphrase.
- **Logs expire too.** GitHub keeps workflow logs for 90 days by default. The logged SHA-256 is a check only while the logs exist; the committed record and the archived bundle are the durable evidence.
- **Unchanged pins.** The workflow pins an older harness commit (`d99f29c`) that has no `results_record.py`. The new step then notes this and skips. Records start with the first dispatch pinned to a commit that contains it.
- **Other workflows.** The Claude Code smoke workflow on the unmerged branches `claude/aqd-benchmark-verification-k85zb0` and `codex/phase33-review-evidence` also uses 1-day retention. This patch does not change it.
