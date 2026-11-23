# Native Claude Code: smoke workflow, credential boundary and live-probe proposal (2026-11-23)

**Scope:** offline preparation only.
- No real token was created.
- No model request was made and no live workflow was dispatched.
- Nothing was merged, and the canonical skill is unchanged (`d050d00f…`).

**Every credential in this document is fake:**
- the mock-CLI dry run uses a fixed synthetic string;
- the real-CLI boundary probe uses a random canary per session (`sk-ant-oat01-BOUNDARY-CANARY-<hex>`), against a **local mock Messages API**, in a container with `--network none`.

## 1. What changed

| File | Change |
|---|---|
| `phase-3.2/harness/cc_adapter.py` | **Skill delivery:** `--plugin-dir <run>/arm-plugin` (the same path in both arms). The three built-in plugins are off (`enabledPlugins`). |
| | **The `init` check matches the real CLI:** the plugin is exactly the arm plugin at its path; the skills are `aqd-arm:code-discipline` + `doctor` (treatment) or `doctor` (control); `permissionMode` is `default`; `served_by_anthropic` must be true. |
| | **Sandbox detection:** a Bash sandbox that cannot start is an infrastructure failure. |
| `phase-3.2/harness/launch-run-cc.sh` | Builds the root-owned arm plugin (the skill in treatment only), passes `--plugin-dir`, and lists the plugin for `run_status`. Requires `socat`. **A Bash sandbox failure writes STOP and exits 22**: it is a host failure that would otherwise exclude only the runs whose agent called Bash (exclusion by agent behaviour, so by arm). |
| `phase-3.2/harness/preflight-cc.sh` | Requires `socat`. |
| `phase-3.2/harness/run_status.py` | The claude-code listing is now the arm plugin plus an empty `CLAUDE_CONFIG_DIR/skills`. |
| `phase-3.2/tests/test_cc_adapter.py` | 73 tests, real-CLI shapes. New: skill delivery and plugins, `served_by_anthropic`, permission mode, sandbox failure (both real messages), an ordinary failing command that only mentions bwrap, the scan never following symlinks, and the batch stop on a sandbox failure. |
| `phase-3.3/dryrun/check_results.py` + `test_check_results.py` | **Exactly** the named scenarios (26, plus `sandbox-failure` after review: 27), each with its required expectation. Fails on a missing, duplicated or unexpected scenario, on a missing or extra cleanup record, on a missing mode, on a missing probe record, or when any session scenario lacks its full isolation probe. 10 tests. |
| `phase-3.3/dryrun/{mock_claude.py,dryrun-cc.sh,Dockerfile}` | The mock emits the real CLI's `init` shape. The `/proc` probe race is fixed. The image adds `socat`. |
| `phase-3.3/boundary/` (new) | `mock_api.py` (local mock Messages API), `boundary_probe.py`, `run-boundary.sh`, `check_boundary.py` + `test_check_boundary.py` (8 tests), and results. The probe also calls Edit, and runs a session with `socat` hidden. |
| `cc_adapter.files_containing` (the launcher's token scan) | **Never follows symlinks.** The agent can plant links, to `/proc/*/environ` or to operator files, and what a link points at is not captured content. Found when CI flagged reads through agent-planted links (§2). |
| `.github/workflows/phase3-cc-smoke.yml` (new) | The manual smoke workflow. The mock job also runs on pull requests. The live job refuses. **No secret is referenced.** |

## 2. The real CLI, offline: what it showed

Method:
- The pinned binary was run: `@anthropic-ai/claude-code-linux-x64@2.1.330`.
  - tarball SHA-256 `40ff30c5…`;
  - binary SHA-256 `f390eaa0…`, identical to the binary examined so far.
- Every session used exactly the harness command, wrapper, OS users, environment, `--restricted`, settings and skill delivery.
- The one difference: `ANTHROPIC_BASE_URL` pointed at a local mock that replays scripted tool calls. No model is involved.
- The canary was then searched for in:
  - the transcript;
  - **every request body the CLI sent** (what a model would see);
  - the request headers and stderr;
  - the run tree and the temp directories.

| Question | Result |
|---|---|
| Does a user skill in `CLAUDE_CONFIG_DIR/skills` load under `--restricted`? | **No.** "Unknown skill". The original design had **no treatment**. |
| Does `--plugin-dir` deliver it? | **Yes.** Treatment lists `aqd-arm:code-discipline`; the Skill tool returns "Launching skill"; the skill text loads. Control: "Unknown skill". |
| Built-in plugins | 2.1.330 loads 3 built-in plugins. `enabledPlugins: false` in `--settings` removes them. One built-in skill (`doctor`) remains, the same in both arms. |
| Env scrub without `socat` | **Every Bash call fails**: "Sandbox is required but failed to initialize … socat not installed" (session `treatment-nosocat`). The run would have been a silent *valid* failure. Now preflight, the launcher, the transcript check and the batch STOP all fail closed. |
| Env scrub, bubblewrap without user namespaces | Every Bash call fails with a `bwrap: No permissions to create new namespace` error. Now detected (the CLI's own "output is only a bwrap error" rule). |
| Env scrub working (privileged container, namespaces allowed) | Bash works (`bash_ok 42`) inside a PID namespace (`pid1=bwrap`). The token is **absent** from the Bash environment, from the shell's own `/proc/self/environ`, and from every `/proc/*/environ` Bash can open (2 readable, 0 with the token). |
| Scrub **off** (sensitivity check) | Bash finds the token in a readable `/proc/*/environ` (`with_token=1`). This shows the probe detects a real exposure, and that the scrub is load-bearing. |
| Read/Grep on `/proc/self/environ`, `/proc/thread-self/environ`, `/proc/self/../self/environ` | **All refused**: "this path names a device or process file that this tool does not read". This is the Microsoft finding (§4) fixed in this build. |
| Read through a symlink in the project to `/proc/self/environ` or `/proc/1/environ` | Refused: `--restricted` confines the file tools to the working directory, and the symlink resolves outside it. |
| Glob on `CLAUDE_CONFIG_DIR` | Refused (outside the working directory). |
| `permissionMode` | `default` with the scrub on, even though `--permission-mode acceptEdits` is passed; Write **and Edit** (both probed) still work through `--allowedTools`. `acceptEdits` with the scrub off. |
| `claude auth status --json` with a fake token and no network | Reports `oauth_token` / `firstParty` / `loggedIn: true`. **It does not validate the token**, so it is a configuration check only. `served_by_anthropic` (false against the mock) is **routing** evidence only: the 2.1.330 schema says "It tells routing alone". Authentication is shown only by assistant turns that Anthropic's service actually served with the pinned model (`model_ok`). |
| Timeout | The harness TERM ends the CLI (exit 143), and no process is left. The CLI refuses a bare `sleep N`; loops run. |
| `effort` in `init` | Absent: still "requested effort". |
| Canary anywhere | **Nowhere**, in any session. |
| GitHub-only hit (first CI runs) | The first CI runs flagged the canary in the agent-planted links `project/env_link` and `project/env_link_pid1`. Diagnostics on the runner showed that reading through them fails with **`PermissionError` (errno 13)**: the canary was never read. The cause is most likely the runner's `fs.protected_symlinks` (the link is another user's, in a sticky world-writable directory). The old scan counted an unreadable file as a hit, a fail-closed false positive. Fixed in the launcher's scan as well: symlinks are never followed. |

**Gates:**

| Gate | Result |
|---|---|
| `check_boundary.py` | 0 failures on both modes (privileged: 4 sessions; unprivileged: 2) |
| `check_results.py` (mock-CLI launcher dry run, non-root operator) | 26 scenarios, 0 failures |

Results are in `boundary/results-2026-11-23/` and `dryrun/results-2026-11-23/`.

## 3. Security assessment (updated)

| Threat | Control | Evidence | Residual risk |
|---|---|---|---|
| The agent's Bash reads the token (env, `/proc/<claude>/environ`, children) | `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` + bubblewrap PID namespace; `socat` and namespace gates in preflight; a sandbox failure is invalid | Real CLI, offline: 0 token occurrences with the scrub on, 1 with it off | Shown with a fake token against a mock API. **The live probe must re-measure** (§6) |
| The agent's file tools read the token (Microsoft, June 2026) | 2.1.330 refuses `/proc` process files in Read/Grep; `--restricted` confines file tools to the project (symlinks included) | Real CLI, offline: 6/6 attempts refused, canary absent | Anthropic does not publish the list of blocked paths; I tested the known variants only. The binary is pinned by hash, so the tested code is the code that runs |
| Token in argv, logs, captures or artifacts | stdin hand-off; `env -i` allow-list; the `finish()` scan (STOP, exit 21); transcripts never printed; upload filter refuses token-shaped strings | Dry run (leak scenario → STOP); boundary canary scans | The scan finds the literal token only |
| Token persisted by the CLI (config dir, temp) | Fresh per-run config and temp dirs, removed after the run | Canary absent from the run tree and `/tmp`, `/var/tmp`, `/dev/shm` | Unknown live-only paths (for example an OAuth refresh) |
| Billing outside the subscription | `check_env` allow-list; `check_token`; `apiKeySource: none`; `served_by_anthropic: true` (routing to Anthropic's own API, not a proof of which credential); managed settings refused | Unit tests; dry run | `auth status` cannot prove a valid token (above). The owner keeps usage credits off |
| A wrong arm (skill leaks to control, missing in treatment) | Arm plugin root-owned and read-only, same path in both arms; exact `skills`/`plugins` check; control scanned for invocation and text | Real CLI, offline: both arms as expected | — |
| Host change: `kernel.apparmor_restrict_unprivileged_userns=0` | See §3.1 | CI: as found the runner refuses; after the change bubblewrap works | §3.1 |

### 3.1 The AppArmor change and the isolation threat model

**What it changes:**
- While it is set, **any** unprivileged process on the runner can create user namespaces, the agent users included.
- Ubuntu 24.04 restricts this by default because user namespaces widen the kernel attack surface: namespaced capabilities reach code paths such as netfilter, mount and overlay that have had local privilege-escalation bugs.

**Effect on this threat model:**
1. **Wider kernel surface for the agent users.**
   - A local kernel exploit from the agent's shell would give root on the runner. Root means:
     - the token in the `claude` process's memory;
     - the runner's `GITHUB_TOKEN` (`contents: read`);
     - in a live job, the environment secret.
   - Without the change, the scrub refuses **every** Bash call (the unprivileged results), so the experiment cannot run. The only way to run Bash without it is to turn the scrub off, and then the token is readable from Bash (the scrub-off result). So the change is a **trade**: it makes the scrubbed, isolated Bash possible (closing a demonstrated same-user read) and opens a theoretical kernel-exploit path.
2. **Egress.**
   - A user namespace can create a network namespace, but an unprivileged new network namespace has no route out. The per-UID iptables egress lock on the host stays in force for the agent's processes.
   - Exception: whatever the agent can already reach (the Anthropic API) stays reachable. That is inherent.
3. **File isolation.**
   - Mount namespaces inside a user namespace cannot grant access the UID does not have on the host.
   - The 0700/0711 run trees and the operator store stay unreadable (dry-run probes).
4. **Bubblewrap working is not proof of isolation.** Credential isolation is claimed only from the direct measurements:
   - token counts in the Bash environment and in `/proc`;
   - the canary scans;
   - file-tool refusals.

   Bubblewrap working is a precondition that is checked separately.

**Mitigations in the workflow:**
- The change is scoped to one disposable, GitHub-hosted VM and is restored by a final `always()` step. It is not persistent, and the VM is discarded.
- No secret exists in the mock job.
- For the live job, the token is dedicated, created immediately before and revoked immediately after.
- The live job's environment secret exists only in that job and only after reviewer approval.

**Precedent:** `anthropics/claude-code-action` runs the same `sudo sysctl -w kernel.apparmor_restrict_unprivileged_userns=0`, best-effort.
- Source: `action.yml` lines 233-255, commit `acfe799`, step "Install subprocess isolation dependencies" (also installs `bubblewrap socat`).
- Precedent is not proof of safety. It shows the vendor accepts the same trade for this CLI.

## 4. External facts relied on (read 2026-11-23)

- **GitHub: the default-branch rule.**
  - "This event will only trigger a workflow run if the workflow file exists on the default branch."
  - "To trigger the `workflow_dispatch` event, your workflow must be in the default branch."
- **GitHub: which file version runs.** "Each workflow run will use the version of the workflow that is present in the associated commit SHA or Git ref of the event."
- **GitHub: environments on public repositories, Free plan.**
  - Required reviewers and deployment-branch policies are available.
  - "Secrets stored in an environment are only available to workflow jobs that reference the environment. If the environment requires approval, a job cannot access environment secrets until one of the required reviewers approves it."
  - Administrators can bypass protection rules unless the environment disallows it.
- **Microsoft Security Blog, 2026-06-05: "Securing CI/CD in an agentic world: Claude Code GitHub action case".**
  - The Read tool ran outside the scrubbed subprocess sandbox, and could read `/proc/self/environ`, which held the unscrubbed `ANTHROPIC_API_KEY`.
  - Reported 2026-04-29.
  - Mitigated "in Claude Code version 2.1.128 by blocking access to sensitive /proc files".
  - Read through a summarising fetcher, so the exact wording is unverified. No CVE or GHSA was found.
- **Anthropic CHANGELOG.**
  - The 2.1.128 entry does **not** mention the fix.
  - Related entries:
    - 2.1.83: added `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`;
    - 2.1.98: PID-namespace sandboxing when the scrub is set;
    - 2.1.309 and 2.1.323: `/proc` and scrub fixes.
  - **The scope of the fix is therefore established here only by testing the pinned binary (§2), not by any published list.**

## 5. Workflow registration and dispatch plan

**Constraint:** `workflow_dispatch` fires only for a file on the default branch (`main`), and the run uses the file at the dispatched ref.

**Smallest safe bootstrap, without merging PR #2 or PR #3.** This is the pattern `phase3-ab-run.yml` already uses on `main`:

1. **A separate one-file PR to `main`** adds `.github/workflows/phase3-cc-smoke.yml`, identical to this branch's file except `AQD_TEST_SHA`. That variable is set to the reviewed head commit of PR #3. Owner review and merge cover only this file.
   - The workflow then checks out **exactly that commit**: `persist-credentials: false`, and it verifies `git rev-parse HEAD`.
   - The pin binds **only dispatches of `main`'s copy**. A writer can push a branch whose copy of this file changes `AQD_TEST_SHA` or the steps, and dispatch that ref: GitHub runs the file at the dispatched ref. Pull requests also run their own head. **What protects the live secret is therefore the environment, not the pin:** deployment branches = `main` only, required reviewer, no admin bypass (step 3). The pin makes a `main` dispatch run reviewed code.
2. **Dispatch `mode: mock` from `main`.** It needs no secret, and must be green before anything else.
3. **The live probe (§6) comes later, as a separate change to the same file on `main`, after authorisation.** That change adds:
   - a job with `environment: aqd-cc-live-probe`;
   - required reviewer = the owner;
   - "Prevent administrators from bypassing" on;
   - deployment branches = `main` only;
   - the token as an **environment** secret, never a repository secret.

   With the deployment-branch policy, a dispatch from any other ref cannot reach the secret.
4. **Every later code change** means a new reviewed `AQD_TEST_SHA` on `main`, a new preflight record, and a new mock dispatch.

**This branch's copy:**
- `AQD_TEST_SHA` is the all-zero placeholder, so a dispatch refuses.
- On pull requests it runs the mock job against the PR head. That is the CI evidence.
- The live job refuses unconditionally, with no environment and no secret.

## 6. The first live milestone: one unscored security probe (PROPOSED, NOT AUTHORISED)

**Purpose:** verify real subscription authentication and the credential boundary with the real service. It does not compare the arms.

**One session:**
- the SMOKE project;
- control arm (no skill);
- a dedicated probe prompt that asks the agent to run, with the Bash tool, exactly the boundary commands of `boundary_probe.py`: Bash environment count, `/proc/*/environ` count, own-environ count, PID namespace line, `bash_ok`.

**These commands print counts and booleans only, never values.**

**Not in the live probe:**
- **No Read/Grep attempts on `/proc`.** They were verified offline on the same binary hash. A regression would put the real token into the model's context, so the live probe does not repeat them.
- **No Skill invocation.** Delivery was verified offline.

**Requirements:**
- **Credentials:**
  - a token created by the owner with `claude setup-token` immediately before, stored only as the environment secret, revoked immediately after;
  - usage credits confirmed off.
- **The secret is referenced in exactly one step,** which writes the 0600 operator credentials file. Never `env:` at job level.
- **Egress:** the per-UID iptables lock from `phase3-ab-run.yml` (Anthropic API ranges only). The job first verifies that `example.com`, `github.com` and `registry.npmjs.org` are unreachable for the agent users.
  - Unknown: whether OAuth sessions need other Anthropic hosts. If they do, the probe fails closed, and widening the lock needs a new review.
- **Approval:**
  - the reviewed `AQD_TEST_SHA`;
  - a fresh `preflight-cc.json` bound to the CLI hash `f390eaa0…`;
  - `cc-run-approved.json` naming the one probe run id, written from a dispatch input that must equal the scheduled run id;
  - environment approval by the owner.
- **Gates before the session:**
  - the mock job green in the same dispatch (`needs: mock`);
  - `auth status` reports `oauth_token`. Configuration only, not validation.
- **Stop rules.** Any one of these stops the job: no rerun, STOP file, token revoked.
  - any token count > 0;
  - any canary or token match in the transcript, stderr or captured files (the launcher scan, exit 21);
  - `served_by_anthropic` not true;
  - `apiKeySource` not `none`;
  - a model mismatch;
  - a sandbox failure;
  - any invalid reason.
- **Evidence:**
  - the transcript and captures leave the runner only GPG-encrypted (the existing pipeline), with 1-day retention;
  - the public log holds fixed status lines and counts only.
- **Pass:**
  - a valid session whose assistant turns were served by Anthropic with the pinned model (`model_ok`), which is the authentication evidence;
  - `served_by_anthropic: true` (routing evidence);
  - all boundary counts 0;
  - Bash works in a PID namespace;
  - no token anywhere.

Only after a pass would a two-arm SMOKE comparison be proposed, separately.

## 7. Remaining assumptions about the real CLI (live only)

1. A real `setup-token` token authenticates `-p` sessions through the restricted command. The offline `auth status` result proves nothing.
2. `served_by_anthropic` is present and true for Anthropic's service. The schema allows it to be absent "where the process can't tell"; then every run fails closed.
3. `modelUsage` and the per-turn model ids match the pinned model with the real service.
4. The scrub and sandbox behave the same with a real token and the real API as with the canary and the mock. The live probe measures this.
5. OAuth sessions need no host outside the Anthropic API ranges in the egress lock.
6. A real model follows a "run exactly these commands" prompt well enough to produce every count. A missing count is a failed probe, never a pass.
7. Usage limits and rate limits under a subscription (`api_retry` and its result shapes) are as recorded offline.
8. The CLI writes nothing token-bearing outside the per-run tree on a real run, for example during an OAuth refresh.

## 8. Verdict for requesting the first live security probe

**READY to request authorisation**, once this commit's CI is green. A green CI means:
- the mock workflow job: dry run and real-CLI boundary on a GitHub runner;
- `phase3-validation`.

**Not yet authorised, and still blocked until the owner acts:**
1. the one-file bootstrap PR to `main` (§5);
2. writing the live job exactly as §6 specifies, reviewed, and dispatched first in `mode: mock`;
3. the environment configuration (reviewer, no admin bypass, `main` only, environment secret);
4. the dedicated token, created right before the probe and revoked right after;
5. usage credits off.

No live execution happens until the owner authorises it in writing. The authorisation should name:
- the run id;
- `AQD_TEST_SHA`;
- the CLI hash.
