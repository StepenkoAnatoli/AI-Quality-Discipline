#!/usr/bin/env python3
"""Checks a dry-run results file against each scenario's expectation. Exit 0 only if every check holds.

    python3 check_results.py dryrun-results-full.ndjson [dryrun-results-preflight-only.ndjson]
"""
import json
import sys


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
        if "cleanup_for" in row and row["problems"]:
            failures.append(f"cleanup after {row['cleanup_for']}: {row['problems']}")
        if row.get("out_dir_token_scan") == "FOUND":
            failures.append("the synthetic token appears in the dry-run output directory")
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
