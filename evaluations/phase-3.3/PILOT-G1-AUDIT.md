# Audit of the G1 pilot verdict logic (2026-11-25)

**Scope.** This audit covers:
- `live/check_pilot.py` and `live/run-live-pilot.sh`;
- `live/rehearse-pilot.sh`;
- the harness fields they read, in `cc_adapter.analyse_transcript`.

It was done after the live pilot (run 44), before G2. The pilot files are the record of that run and are **not changed**.

## Verdict

- **The harness verdict is sound**: valid runs, the correct arm per run, subscription authentication, and controls free of the skill.
- **The headline measurement "invoked in 3 of 3" is weaker than its wording.** It counts Skill tool *calls*. It does not count successful loads, and it ignores when in the session the call came. Whether the G1 runs actually loaded the skill before working **cannot be decided from the public log or the result record**. The owner can settle it offline in a minute with the evidence already held (below).

## Findings

| # | Finding | Evidence | Severity | Status |
|---|---|---|---|---|
| A1 | `invoked` is true as soon as the agent *issues* a Skill call naming `code-discipline`, even if the call failed. `check_pilot.py` counts only `invoked`. It ignores `skill_text_loaded`, which the harness already computes from the three sentinel lines of the skill text | Reproduced: three synthetic treatment runs whose Skill call returns an error gave `check_pilot` **PASS, invoked 3 of 3**, with `skill_text_loaded` false in every run. On the pinned real CLI (offline boundary results, `boundary/results-2026-11-23/privileged`), a call for an unavailable skill gave `invoked: true, skill_text_loaded: false`. A real load gave `skill_text_loaded: true` in all three treatment sessions, so the sentinel signal works on 2.1.330 | Medium: it can overstate the G1 signal on which D1 rests | Check G1 offline (below). For Stage 1, report *loaded*, not just *called* |
| A2 | The timing is not recorded. A load after the last edit counts the same as a load before any work. Under D1 (a), the interpretation depends on the skill being in context while the agent works | Reproduced: a Skill call after the only edit gives `invoked: true` and a valid run | Medium for interpretation | `inspect_invocation.py` reports `before_first_edit` |
| A3 | The rehearsal has no case "called but not loaded" or "called late". Its `treatment-invoked` case only checks the count of calls | `rehearse-pilot.sh` cases | Low | Add both cases to any Stage 1 rehearsal |
| A4 | The invocation denominator keeps only *valid* treatment runs. If a run is invalid, for example through a scope violation, it drops out silently, and k of n can look better than it is. G1 had all runs valid, so this has no effect on G1 | `check_pilot.check`, `valid_treatment` | Low | Stage 1: report invalid treatment runs next to the rate |
| A5 | A control run that calls *any* skill, even the built-in `doctor`, fails the harness | `check_pilot.check_run`, `checks.get("skill_invocations")` | Info (conservative) | Accept, or narrow to `code-discipline` |
| A6 | `check_pilot` trusts each capture directory's run ID and does not re-check `run-record.json`'s task or prompt hash | — | Info: the launcher's approval check binds them per run | none |

## Settling G1 with the evidence you already hold

Run this on the **decrypted** pilot archive, offline. It is read-only and prints booleans and counts only:

```
python3 -I evaluations/phase-3.3/live/inspect_invocation.py \
  --store <decrypted archive directory> --schedule evaluations/phase-3.3/live/pilot-schedule.json
```

How to read the result:
- `loaded 3 … loaded before the first edit 3`: the G1 conclusion stands as stated.
- `loaded 3` but fewer than 3 loaded before the first edit: the skill was in context, but not for all the work. D1 (a) still follows, but record the timing alongside it.
- Fewer than 3 `loaded`: "invoked in 3 of 3" overstated the result. Revisit D1 per `PILOT-G1.md` §3, applied to *loaded* runs.
- `disagrees_with_harness=True` on any row: stop and investigate before relying on either number.

`inspect_invocation.py` has 7 tests. One mutation check was run: dropping the timing comparison fails a test.
