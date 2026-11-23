# Native Claude Code adapter (offline implementation; no live run)

**Status 2026-11-23:**

- Implemented and tested **offline only**.
- No model request, real credential, token creation, workflow dispatch or merge has happened.
- Offline tests show that the adapter's own logic is correct for synthetic inputs. They do **not** show that subscription authentication works, that a real session has the expected shape, that the skill activates, or that the skill helps.

## 1. What this is

**A second execution environment.** It is labelled `native-claude-code`, next to the Phase 3.2 OpenCode harness (`opencode`):

- The unmodified `claude` CLI, pinned at 2.1.330, runs headless (`claude -p`) under the owner's own subscription. Authentication uses `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token`.
- `analyze.py` refuses to pool runs from the two environments (`check_run_records`: "never pooled").
- The OpenCode harness (`launch-run.sh`, `drive_session.py`, `api_checks.py`, `export_checks.py`) is unchanged and stays the historical reference for Phase 3.2.

**The question it serves.** Does making `code-discipline` **available** improve correctness?

- **Treatment arm:** the canonical `SKILL.md` (`d050d00f…`, unchanged) is inside the run's arm plugin, passed with `--plugin-dir` (the same path in both arms; control's plugin has no skill). The real 2.1.330 CLI ignores `CLAUDE_CONFIG_DIR/skills` under `--restricted` (SMOKE-WORKFLOW.md §3).
- **Control arm:** that directory exists but is empty.
- **Identical in both arms:** the prompt, command, settings file and environment.
- **Recorded separately**, none of them a validity condition (an intention-to-treat contrast on availability):
  - available: the `init` event lists exactly that skill;
  - invoked: a `Skill` tool call names it;
  - loaded: its text appears in the transcript.
- **Followed:** not measured.

## 2. Components

| Component | Status |
|---|---|
| `schedule.py` (sealed, counterbalanced), `manifest.py` (immutable manifests), `score_run.py` (private, sandboxed scoring), `difficulty.py` | **Reused unchanged** |
| `lib.sh` helpers: OS users per group, `assert_*`, `kill_user_processes`, `agent_path` | **Reused unchanged** |
| Project build from the manifest (root-owned 0444 immutable files in sticky dirs), pre/post manifest verification, diff capture, evaluator-must-be-empty rule, preflight and STOP gates, run-root removal | **Reused**: the same code, copied into `launch-run-cc.sh` |
| `run_status.py` | **Reused with one opt-in parameter.** `--interface claude-code` selects the interface string, requires `execution_environment`, and expects the skills listing. The default (`opencode`) is unchanged and tested |
| `analyze.py check_run_records` | **Reused with one addition.** Execution environments are never pooled; native records must also agree on `claude_cli_sha256` and `max_turns` |
| `launch-run.sh`, `drive_session.py`, `api_checks.py`, `export_checks.py`, `install-opencode.sh` | **Untouched** (historical reference) |
| `cc_adapter.py` (new) | Environment and token checks, `auth status` check, one command for both arms, the session driver, and the transcript checker that writes `export-checks.json` in the existing schema |
| `cc_exec.sh` (new, 14 lines) | Reads the token from the first line of stdin, exports it, and `exec`s `claude`. The rest of stdin is the prompt |
| `launch-run-cc.sh` (new) | `launch-run.sh` with the OpenCode steps replaced. **Executed end to end against a mock CLI** in a disposable container (INTEGRATION-DRYRUN.md); never against the real CLI |
| `preflight-cc.sh` (new) | Native preflight; writes `preflight-cc.json`, bound to the commit, CLI hash, harness, settings, skill, schedule and limits. `preflight.sh` (OpenCode) is unchanged and never accepted by the native launcher |
| `phase-3.3/dryrun/` (new) | Mock CLI, dry-run driver, results checker, Dockerfile; run by the CI job `native-claude-code-dry-run` |
| `tests/test_cc_adapter.py` (new) | Offline tests in the existing CI job (count in INTEGRATION-DRYRUN.md §2) |

## 3. Isolation and the command

**The command** (`build_argv`), byte-identical in both arms:

`claude -p --restricted --model <id> --effort <level> --settings <root-owned file> --strict-mcp-config --tools Bash,Read,Edit,Write,Glob,Grep,Skill --allowedTools <same> --permission-mode acceptEdits --output-format stream-json --verbose --max-turns N --no-session-persistence --plugin-dir <run root>/arm-plugin`

The prompt goes in on stdin. The process starts in the run's project directory: `cc_exec.sh DIR …` changes to it inside the agent user's own process, because the operator cannot traverse the agent's 0700 tree (the OpenCode harness's `as_agent` does the same). The transcript check requires `init.cwd` to be exactly that directory.

`Skill` is in `--tools` in **both** arms: `--tools` withholds every built-in tool it does not name (2.1.330: "…is not on this session's --tools list…; withheld"), so without it the treatment's skill would be listed but could never be loaded.

**Flags and settings, and why:**

| Choice | Reason |
|---|---|
| `--restricted`, not `--safe-mode` or `--bare` | `--bare` never reads OAuth credentials, so the subscription can't be used. `--safe-mode` disables all skills, so the treatment can't exist. `--restricted` is documented to: load only managed settings and `--settings`; remove code-running tools and WebFetch unless `--tools` names them; confine file tools to the working directories; refuse bypassPermissions |
| `--settings` | `syncClaudeAiSkills: false` and `syncClaudeAiPlugins: false` (in the binary, honoured per invocation; documented in user settings). Also `switchModelsOnFlag: false`, `disableBundledSkills: true`, allow the six coding tools and `Skill`, deny WebFetch and WebSearch |
| No `--fallback-model` | No fallback model |
| Environment built from scratch (`env -i`) | Only the allow-listed variables are present, plus `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1`, `CLAUDE_CODE_DISABLE_BUNDLED_SKILLS=1`, `CLAUDE_CODE_SKIP_PROMPT_HISTORY=1` and `DISABLE_AUTOUPDATER=1`, `DISABLE_UPDATES=1`, `CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1`, `CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK=1` |
| Refused before anything runs | Any API key, base URL, alternative-provider switch, model or effort override, or unknown variable (`check_env`) |

**Bundled skills are disabled in both arms:**

- Why: so that code-discipline is the only skill difference, and so the comparison is closer to the Phase 3.2 contrast.
- Consequence: the result describes Claude Code without its bundled skills, not Claude Code as shipped. That is a pre-registered choice the owner can reverse before freezing.

**Fail-closed checks on the transcript** (`analyse_transcript`). The run is invalid unless all of these hold:

- exactly one `init` event, and exactly one `result` event (zero or one after a timeout);
- `init.cwd` is the run's project directory;
- the pinned CLI version, model and permission mode;
- `apiKeySource == "none"`;
- no plugins or MCP servers;
- no web or MCP tools;
- the available skills are **exactly** `[code-discipline]` (treatment) or `[]` (control), so an account-synced or bundled skill invalidates both arms;
- treatment: the `Skill` tool is offered (`init.tools`); control: recorded only;
- every assistant turn was served by the pinned model, and the pinned model appears in `modelUsage` (a killed session has no result event, so it is judged on its assistant turns);
- the result is `success` with `is_error` false, or `error_max_turns`. The CLI emits `error_max_turns` with `is_error` **true**, so the subtype decides. Any other result, or a timeout while the CLI was still retrying the provider, is an infrastructure failure;
- no code-discipline listing, invocation or text in control.

**Outcomes that stay valid:** the turn limit (driver outcome `max_turns`) and the 45-minute timeout (SPECIFICATION §6.2). After a timeout, a truncated final line is tolerated; a bad line anywhere else is not. Recovered `api_retry` events are recorded in `api_retries`, not invalidating, matching Phase 3.2, which invalidated only sessions that *ended* on a provider error.

**Recorded only, not validity conditions:**

- auxiliary models in `modelUsage`;
- the `init` `effort` field (when present it must equal the requested level; when absent, effort is unverified);
- the estimated cost (a client-side estimate, not a bill).

## 4. Evidence status of every assumption

| Fact relied on | Source | Status |
|---|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` sessions do not sync claude.ai skills or plugins | skills.md, plugins/loading.md | documented |
| `syncClaudeAiSkills` / `syncClaudeAiPlugins: false` honoured via `--settings` | CLI 2.1.330 setting descriptions | binary only |
| `--bare` ignores OAuth; `--safe-mode` disables skills; `--restricted` behaviour | cli-reference.md; `claude --help` | documented |
| A user skill in `CLAUDE_CONFIG_DIR/skills` is available under `--restricted` | real CLI, offline | **FALSE** ("Unknown skill"). Replaced by `--plugin-dir`, which works: listed as `aqd-arm:code-discipline`, launched, text loaded |
| `claude auth status --json` `authMethod` is `oauth_token` for the token | real CLI, offline | reports `oauth_token`, `firstParty`, `loggedIn: true` **even for a fake token with no network**: it does not validate the token. Real authentication is shown only by assistant turns that Anthropic's service actually served with the pinned model (`model_ok`); `served_by_anthropic` is routing evidence only (2.1.330 schema: "It tells routing alone") |
| `init` fields (`apiKeySource`, `claude_code_version`, `tools`, `mcp_servers`, `model`, `permissionMode`, `slash_commands`, `skills`, `plugins`, optional `effort`) | agent-sdk/typescript.md; CLI init schema | real CLI, offline: shape confirmed (plus `served_by_anthropic`, `plugins` with paths); with the scrub `permissionMode` is `default`; `effort` is absent. Values from Anthropic's service are unverified |
| `apiKeySource` is `"none"` for OAuth (and for bearer or third-party providers) | CLI schema description | binary only. The environment allow-list is what excludes bearer and third-party credentials |
| The automatic skill tool is `Skill`, with input field `skill` | tools-reference.md (name); CLI tool schema (field) | name documented, field binary only |
| A `/skill-name` prompt expansion produces a `Skill` tool_use | none | **not documented, not assumed.** This design doesn't use it |
| `modelUsage` keys are the bare model id; every model that served a turn appears there | model-config.md (read the model from `modelUsage`) | **key format and completeness unverified.** It fails closed if the pinned id is absent |
| `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` strips credentials from the agent's subprocesses and isolates them with bubblewrap (on by default under `GITHUB_ACTIONS`) | real CLI, offline (fake token, local mock API) | **verified offline**: token absent from the Bash environment and from every `/proc/*/environ` Bash can read; PID namespace. **Needs `socat` and bubblewrap with user namespaces**, else every Bash call fails |
| `--restricted` with `--tools Bash` plus `--allowedTools Bash` and `acceptEdits` lets a headless run edit source files and run tests without a person | real CLI, offline | verified: Bash, Write and Edit work headless (scrub on, `permissionMode` `default`) |
| `result.subtype` values `success` / `error_max_turns`; `error_max_turns` carries `is_error: true` | SDK result types; 2.1.330 result builder | documented shape; `is_error` binary only; real values unverified |
| `Skill` survives `--restricted --tools …,Skill` and appears in `init.tools` | real CLI, offline | verified: `Skill` is in `init.tools` |
| `init.cwd` is the working directory the process started in, as an absolute path matching `$PROJECT` | real CLI, offline | verified (the path as given) |
| `cc_exec.sh` can enter the project as the agent user | tested in the non-root dry run | verified with the mock; a failure exits 96 and the run is invalid |
| `setup-token` tokens start with `sk-ant-oat` (used to refuse an API key placed in the token slot) | none found | **assumption.** If wrong, `check_token` refuses a valid token and the run stops before any request. It fails closed and can't spend |
| A turn cap (`--max-turns`, default 200) is a new constraint; Phase 3.2 had only the 45-minute wall limit | harness choice | to pre-register. Every run records whether it was hit (`result_subtype`) |

## 5. Threat assessment

| Threat | Control | Residual risk |
|---|---|---|
| Billing outside the subscription (API key, `apiKeyHelper`, Bedrock/Vertex/Foundry, base URL) | The environment is built from scratch and allow-listed (`check_env`). An API key in the token slot is refused (`check_token`). `auth status` must report `authMethod: oauth_token` before the session (STOP otherwise). The transcript must show `apiKeySource: "none"` | Usage credits are a claude.ai account setting the harness can't see. **The owner must keep them off.** A Fable model can bill credits, so the model is pinned and checked on every turn |
| Model fallback or switch | No `--fallback-model`; `switchModelsOnFlag: false`; `CLAUDE_CODE_DISABLE_REFUSAL_FALLBACK=1`; every assistant turn's model is checked | If a switch is not reported per turn, `modelUsage` is the only other signal, and its completeness is unverified |
| Account skills, plugins, hooks or CLAUDE.md in a run | OAuth-token auth (documented: no sync); `--settings` sync off; a fresh per-run `CLAUDE_CONFIG_DIR`; `--restricted` (no user, project or local settings files, so no hooks from them); no CLAUDE.md in the tasks; exact `skills`/`plugins`/`mcp_servers` checks | Managed (policy) settings still apply under `--restricted`, and their `env` or `apiKeyHelper` could redirect or bill a session without changing `authMethod`. The launcher refuses to start if `/etc/claude-code` exists. Not covered: any other managed-settings location a future CLI adds |
| The token in public logs or artifacts | Never in argv (stdin hand-off; `sudo env -i` carries only non-secret variables); never in `$CAP`, the run root or any agent-readable file; held in an operator-only 0700 directory removed in `finish()`; the GitHub secret is referenced only in the one step that writes the 0600 credentials file; launcher output goes to the encrypted bundle; a token scan of every captured file runs in `finish()` on **every** exit path, before the secret copy is removed. A hit, or a scan that cannot run, writes STOP, makes the run invalid and exits 21 | The scan finds the literal token only (no encodings). It is defence in depth, never the main control |
| **The agent reads the token** (its Bash runs as the same OS user as `claude`, so `/proc/<claude pid>/environ` is readable) | `CLAUDE_CODE_SUBPROCESS_ENV_SCRUB=1` plus bubblewrap (separate process namespace for the agent's commands); egress locked to Anthropic hosts during runs (Phase 3.2 rule), so a stolen token can only be used against Anthropic; transcripts encrypted | **Unverified, and the largest residual risk.** Owner mitigation: a token made only for the experiment and revoked immediately after it |
| Treatment leaks into control, or the agent adds a skill | Root-owned `skills/` directory in both arms, inside a root-owned sticky (1770) config directory, so the agent can neither write it nor rename and replace it; separate OS users and run roots; control transcript checked for the skill's listing, invocation and text | Same as Phase 3.2: detection after the fact, plus egress lock |
| Hidden material reaches the agent | Unchanged Phase 3.2 rule: hidden tests are decoded only after both runs, into the operator-only evaluator directory | None new |
| One approval reused for many paid runs | `cc-run-approved.json` must list **this** run id in `approved_run_ids` (`check-approval`); a smoke-test approval covers only the smoke-test runs | The owner must write a new list for each batch |
| Workflow permissions | Existing CI: `contents: read`, no secrets. The run workflow (not written yet; §7) must keep `contents: read`, `workflow_dispatch` only, `run_attempt == 1`, and the secret scoped to one step | To be reviewed when the workflow is written |

## 6. Automatic versus explicit invocation

| | Available only (chosen) | Explicit `/code-discipline` prefix |
|---|---|---|
| Question answered | Does having the skill installed improve outcomes? This is the product question for an always-on skill | Does the skill's content improve outcomes once loaded? |
| Prompts | Byte-identical | Differ by one line, a cue in itself (it tells the agent a discipline skill is wanted) |
| Activation | Measured (invoked / loaded) as an outcome; can be low | Forced, but how the expansion appears in the transcript is not documented, so confirmation is uncertain |
| Comparable with Phase 3.2 (attached text) | No: Phase 3.2 forced the full text into context | Closer, but still a different mechanism |
| Risk of a misleading positive | Low: identical prompts | Higher: the prefix itself can change behaviour (a placebo-like cue) |

Recommendation:

- Keep **available only** for the primary contrast.
- If the feasibility run shows invocation is rare, a separate, pre-registered "forced" arm can answer the content question later. It must not be mixed with this one.

## 7. No-model-call GitHub Actions dry run (design; superseded)

**Superseded 2026-11-23:** implemented as the CI job `native-claude-code-dry-run` and the `dryrun/` directory. Results and the current blocker list are in INTEGRATION-DRYRUN.md.

**Where it runs:** a `workflow_dispatch`-only workflow on the default branch after owner review. Permissions `contents: read`; **no secret referenced at all**.

**Steps:**

1. **Install the pinned CLI.** Run `npm install -g @anthropic-ai/claude-code@2.1.330`, record the binary's SHA-256, and require `claude --version` to print 2.1.330. Install bubblewrap.
2. **Negative control: no token.** Run `cc_adapter.py auth-status` with an empty token file. It must refuse before calling `claude`. Then run `claude auth status --json` directly with no credentials. It must report `authMethod: none`, and `check-auth` must fail.
3. **Host setup as in Phase 3.2.** Run `setup-host.sh` (OS users, egress lockdown) and the sealed `--counterbalance` schedule for 1 control and 1 treatment slot of a prototype task.
4. **The full launcher against a mock `claude`.** Run `launch-run-cc.sh` with `AQD_CLAUDE_BIN` pointing at a mock, a version of the test mock that also answers `--version` and `auth status`. This exercises every real shell path with zero model calls: sudo, OS users, immutability, the skills directory, `env -i`, the token hand-off, capture, the token scan and `run_status.py`.
5. **Expected results:**
   - with the mock's synthetic transcripts, both runs VALID;
   - one deliberately bad mock (for example an extra skill) gives INVALID;
   - a mock that echoes a fake token stops the benchmark (exit 21).
   - mocks for the turn limit (`error_max_turns`, `is_error: true`, exit 1) and a timeout give VALID runs;
   - a mock started outside the project (wrong `init.cwd`) gives INVALID.
6. **Egress probe while locked:** `github.com` refused, and the Anthropic API host reachable at TCP level only. No HTTP request is sent.
7. **Public log:** only fixed messages and hashes. Captures are synthetic, but they are still encrypted with the existing pipeline to exercise it.

**For the later smoke test (needs separate written approval):**

- add `secrets.CLAUDE_CODE_OAUTH_TOKEN`, referenced only in the step that writes `$AQD_CREDENTIALS` (0600);
- real `claude`;
- 1 control + 1 treatment run;
- `/usage` checked before and after.

## 8. Remaining blockers before any smoke test

1. **Owner prerequisites (unchanged):**
   - an independent **human** oracle review;
   - **blind** second difficulty ratings;
   - owner approval of the feasibility plan.
2. **The dry-run workflow (§7):** written, reviewed and run with no secret. Not done.
3. **Private task delivery:** the `AQD_PHASE_ROOT` override and pack verification, as designed in the private readiness report. Not done. Alternatively, the smoke test uses the public SMOKE task first.
4. **Owner actions:**
   - create a dedicated `setup-token` token immediately before the smoke test and revoke it after;
   - confirm usage credits are off;
   - write `cc-run-approved.json` listing exactly the approved run ids.
5. **First things the smoke test must show** (each fails closed if wrong):
   - `authMethod: oauth_token`;
   - `init.skills` is `[aqd-arm:code-discipline, doctor]` in treatment and `[doctor]` in control, `Skill` is in `init.tools`, and `served_by_anthropic` is true;
   - `init.cwd` is the project directory;
   - the agent's Bash can't read `CLAUDE_CODE_OAUTH_TOKEN`. This needs a dedicated probe task, never a scored task.

## 9. Adversarial review (fresh-context reviewer, 2026-11-23) and fixes

| # | Finding | Verdict | Fix (test first) |
|---|---|---|---|
| 1 | `claude` never started in the project directory, so with `--restricted` every run would be a valid failure | confirmed by tracing | `run --project`; `init.cwd` must equal the project. (The first fix, `Popen(cwd=project)`, failed for a non-root operator; replaced by a `cd` in `cc_exec.sh`, see INTEGRATION-DRYRUN.md §1) |
| 2 | `--tools` withheld the `Skill` tool, so the treatment's skill was listed but could not load | confirmed in the binary text (runtime unverified) | `Skill` in `--tools`/`--allowedTools` and settings in both arms; required in `init.tools` in treatment |
| 3 | Every turn-limit run was invalid (the CLI sets `is_error: true`); the old test used a shape the CLI never emits | confirmed in the binary | the subtype decides; driver outcome `max_turns`, valid |
| 4 | Every timeout was invalid (no result event, truncated line, no `modelUsage`), contradicting SPECIFICATION §6.2 | confirmed | `check-transcript --driver-result`; timeout rules above |
| 5 | Any recovered `api_retry` invalidated the run | confirmed in the binary | recorded, not invalidating; a timeout while retrying stays invalid |
| 6 | The token scan ran only on the success path | confirmed | `scan-secret` in `finish()`, before the secret is removed |
| 7 | Managed settings were not checked | plausible | refuse if `/etc/claude-code` exists |
| 8 | One approval file authorised every run | confirmed | `approved_run_ids` must name the run |
| 9 | The agent could rename the root-owned `skills/` directory | confirmed (Linux rename semantics) | config dir root:agent 1770, checked |
| 10 | Doc claims not supported by the code | confirmed | corrected in this file |

17 new guard mutants of these fixes are all caught by the tests. The launcher fixes are checked only statically (text assertions, `bash -n`, ShellCheck); the launcher has still never been executed.
