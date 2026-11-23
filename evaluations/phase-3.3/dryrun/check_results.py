#!/usr/bin/env python3
"""Checks a dry-run results file against each scenario's expectation. Exit 0 only if every check holds.

    python3 check_results.py dryrun-results-full.ndjson [dryrun-results-preflight-only.ndjson]
"""
import json
import sys


# Each scenario must fail (or pass) for ITS reason, not merely end with the right exit code.
REASONS = {
    "timeout": lambda r: r["timed_out"] is True and r["driver_status"] == "timeout",
    "timeout-with-child": lambda r: r["timed_out"] is True and r["driver_status"] == "timeout",
    "turn-limit": lambda r: r["driver_outcome"] == "max_turns" and r["max_turns_reached"] is True,
    "control-ok": lambda r: r["activation"] == "NOT_APPLICABLE" and r["invoked"] is False,
    "treatment-ok-invoked": lambda r: r["activation"] == "AVAILABLE" and r["invoked"] is True,
    "treatment-not-invoked": lambda r: r["activation"] == "AVAILABLE" and r["invoked"] is False,
    "proc-probe-run": lambda r: r["activation"] == "AVAILABLE",
    "auth-api-key": lambda r: _reason(r, "api_checks exit 3"),
    "wrong-token": lambda r: _reason(r, "api_checks exit 3"),
    "api-key-in-token-slot": lambda r: _reason(r, "api_checks exit 3"),
    "wrong-model": lambda r: _reason(r, "not served by the pinned model"),
    "wrong-init-model": lambda r: _reason(r, "session model"),
    "missing-skill": lambda r: _reason(r, "available skills []"),
    "unexpected-skill": lambda r: _reason(r, "available skills ['other-skill']"),
    "wrong-cwd": lambda r: _reason(r, "working directory"),
    "corrupted-transcript": lambda r: _reason(r, "not JSON objects"),
    "provider-error": lambda r: _reason(r, "provider/API error"),
    "missing-credentials": lambda r: _log(r, "CLAUDE_CODE_OAUTH_TOKEN is not set"),
    "leaked-token": lambda r: _reason(r, "token-leak"),
    "unapproved-run": lambda r: _log(r, "not in the owner's approved_run_ids"),
    "binary-changed-after-preflight": lambda r: _log(r, "cli_sha256 changed since preflight"),
    "stale-preflight": lambda r: _log(r, "(stale)"),
    "opencode-preflight-only": lambda r: _log(r, "no native preflight record"),
    "timeout-changed-after-preflight": lambda r: _log(r, "timeout_seconds changed since preflight"),
    "not-a-dry-run-timeout": lambda r: _log(r, "not the pre-registered 2700"),
    "stop-file-present": lambda r: _log(r, "benchmark stopped"),
}


def _reason(row, text):
    return any(text in reason for reason in row.get("invalid_reasons") or [])


def _log(row, text):
    return any(text in line for line in row.get("launcher_log_tail") or [])


def expectation_holds(row):
    exp, code, valid, stop, cap = row["expect"], row["launcher_exit"], row["valid"], row["stop_file"], row["capture_exists"]
    if exp == "valid":
        return code == 0 and valid is True and stop is None
    if exp == "invalid":  # an infrastructure/validity failure: excluded, never a valid failed outcome
        return code not in (0,) and valid is False and stop is None
    if exp == "stop20":
        return code == 20 and valid is False and stop is not None and stop.startswith("BLOCKED")
    if exp == "stop21":
        return code == 21 and valid is False and stop is not None and stop.startswith("ISOLATION FAILURE")
    if exp == "refused":  # refused before anything started: no capture directory
        return code == 2 and not cap
    return False


def main(paths):
    failures, rows = [], []
    for path in paths:
        rows += [json.loads(line) for line in open(path, encoding="utf-8") if line.strip()]
    for row in rows:
        if "scenario" in row and not expectation_holds(row):
            failures.append(f"{row['scenario']}: expected {row['expect']}, got exit {row['launcher_exit']} "
                            f"valid={row['valid']} stop={bool(row['stop_file'])}")
        if "scenario" in row:
            check = REASONS.get(row["scenario"])
            if check is None:
                failures.append(f"{row['scenario']}: no expected reason defined")
            elif not check(row):
                failures.append(f"{row['scenario']}: right exit, wrong or missing reason")
        if "cleanup_for" in row and row["problems"]:
            failures.append(f"cleanup after {row['cleanup_for']}: {row['problems']}")
        if row.get("out_dir_token_scan") == "FOUND":
            failures.append("the synthetic token appears in the dry-run output directory")
        if "proc_probe" in row and not row["proc_probe"]["session_pid_found"]:
            failures.append("proc probe found no session process: nothing was probed")
        if "proc_probe" in row and not row["proc_probe"]["same_user_reads_token"]:
            failures.append("proc probe could not read even the same user's environment: the probe is not working")
        if "proc_probe" in row and row["proc_probe"]["other_arm_reads_token"]:
            failures.append("the other arm's OS user can read a session's environment")
        if "proc_probe" in row and row["proc_probe"]["token_in_cmdline"]:
            failures.append("the token is in a process command line")
        probe = row.get("probe")
        if probe:
            bad = [k for k in ("can_write_TASK_md", "can_create_in_skills", "can_rename_skills_dir",
                               "can_read_operator_store", "can_read_other_arm", "can_read_checkout",
                               "can_read_root_home") if probe[k]]
            bad += [k for k in ("argv_matches_expected", "token_matches", "can_write_notes_txt") if not probe[k]]
            if not probe["cwd"].endswith("/project"):
                bad.append("cwd")
            if probe["token_in_temp_files"]:
                bad.append("token_in_temp_files")
            if bad:
                failures.append(f"{row['scenario']}: isolation probe failed: {bad}")
    for mode in ("full", "preflight-only"):
        bw = [r["bwrap_userns_as_agent"] for r in rows if r.get("mode") == mode and "bwrap_userns_as_agent" in r]
        pf = [r["preflight_exit"] for r in rows if r.get("mode") == mode and "preflight_exit" in r]
        if bw and pf and (pf[0] == 0) != bw[0]:
            failures.append(f"{mode}: preflight exit {pf[0]} disagrees with the bubblewrap probe ({bw[0]})")
        if mode == "full" and pf and pf[0] != 0:
            failures.append("full mode: preflight did not pass")
    scenarios = [r for r in rows if "scenario" in r]
    print(f"{len(scenarios)} scenarios, {len(failures)} failure(s)")
    for f in failures:
        print("FAIL:", f)
    return 1 if failures or not scenarios else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
