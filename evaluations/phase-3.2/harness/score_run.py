#!/usr/bin/env python3
"""Run hidden and baseline checks against one agent result.

    score_run.py --phase-root DIR --task ID --pristine DIR --agent DIR \
                 --hidden DIR --out FILE [--timeout SECONDS]

The scoring tree is built from the pristine project, then only the task's
mutable file and the additive test directory are taken from the agent result
(pre-registered rule: other agent-created files are not used for scoring and
are reported separately by manifest.py). The hidden directory must contain a
package named ``hidden_tests``; it is never copied into an agent workspace.
Run this as an unprivileged user that cannot read evaluator material other
than the hidden tests for this one task.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest as manifest_mod  # noqa: E402

CHECK_ID = re.compile(r"\.test_(H\d{2})_")


def build_scoring_tree(phase_root, task, pristine, agent, hidden, scratch):
    allowlist, _ = manifest_mod.load_allowlist(phase_root)
    entries = manifest_mod.task_entries(allowlist, task)
    shutil.copytree(pristine, scratch, symlinks=True, dirs_exist_ok=True)
    taken = []
    for rel, _source, category in entries:
        if category != "mutable":
            continue
        src = os.path.join(agent, *rel.split("/"))
        dst = os.path.join(scratch, *rel.split("/"))
        if os.path.isfile(src) and not os.path.islink(src):
            shutil.copyfile(src, dst)
            taken.append(rel)
        else:
            os.remove(dst)
    for additive in allowlist.get("additive_dirs", []):
        src = os.path.join(agent, *additive.split("/"))
        dst = os.path.join(scratch, *additive.split("/"))
        if os.path.isdir(src) and not os.path.islink(src):
            shutil.rmtree(dst)
            shutil.copytree(src, dst, symlinks=False, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            taken.append(additive + "/")
    shutil.copytree(os.path.join(hidden, "hidden_tests"), os.path.join(scratch, "hidden_tests"))
    shutil.copyfile(os.path.join(HERE, "run_checks.py"), os.path.join(scratch, "run_checks.py"))
    return taken


def _run(scratch, args, timeout):
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "LANG", "LC_ALL", "HOME", "TMPDIR", "SYSTEMROOT", "TEMP", "TMP")}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    try:
        proc = subprocess.run([sys.executable, "run_checks.py", *args], cwd=scratch, env=env,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout, text=True)
        return proc.returncode, proc.stdout[-20000:]
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout or ""
        if isinstance(out, bytes):
            out = out.decode("utf-8", "replace")
        return "timeout", out[-20000:]


def _read(path):
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def run_suite(scratch, start_dir, label, timeout, per_test):
    result = {"outcomes": {}, "logs": {}, "load_errors": []}
    if per_test:
        listing = os.path.join(scratch, f".{label}-list.json")
        code, log = _run(scratch, ["list", start_dir, listing], timeout)
        if code != 0 or not os.path.exists(listing):
            result["load_errors"].append(f"listing failed ({code}): {log[-2000:]}")
            return result
        data = _read(listing)
        result["load_errors"].extend(data["load_errors"])
        for test_id in data["ids"]:
            out = os.path.join(scratch, f".{label}-one.json")
            if os.path.exists(out):
                os.remove(out)
            code, log = _run(scratch, ["run", start_dir, out, test_id], timeout)
            if code == "timeout":
                result["outcomes"][test_id] = "timeout"
            elif os.path.exists(out):
                result["outcomes"][test_id] = _read(out)["outcomes"].get(test_id, "error")
            else:
                result["outcomes"][test_id] = "error"
            result["logs"][test_id] = log
    else:
        out = os.path.join(scratch, f".{label}.json")
        code, log = _run(scratch, ["run", start_dir, out], timeout)
        result["logs"]["suite"] = log
        if code == "timeout" or not os.path.exists(out):
            result["load_errors"].append(f"suite did not complete ({code})")
        else:
            data = _read(out)
            result["outcomes"] = data["outcomes"]
            result["load_errors"].extend(data["load_errors"])
    return result


def summarise(task, taken, hidden, baseline, additive):
    checks = {}
    for test_id, outcome in hidden["outcomes"].items():
        match = CHECK_ID.search(test_id)
        if match:
            checks[match.group(1)] = outcome
    passed = sum(1 for v in checks.values() if v == "pass")
    baseline_ok = bool(baseline["outcomes"]) and not baseline["load_errors"] and all(v == "pass" for v in baseline["outcomes"].values())
    return {
        "schema_version": 1,
        "kind": "aqd-phase-3.2-hidden-score",
        "task": task,
        "taken_from_agent": taken,
        "hidden_checks": dict(sorted(checks.items())),
        "hidden_passed": passed,
        "hidden_total": len(checks),
        "hidden_load_errors": hidden["load_errors"],
        "baseline_outcomes": baseline["outcomes"],
        "baseline_all_pass": baseline_ok,
        "additive_outcomes": additive["outcomes"],
        "additive_load_errors": additive["load_errors"],
        "logs": {"hidden": hidden["logs"], "baseline": baseline["logs"], "additive": additive["logs"]},
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phase-root", required=True)
    parser.add_argument("--task", required=True)
    parser.add_argument("--pristine", required=True)
    parser.add_argument("--agent", required=True)
    parser.add_argument("--hidden", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args(argv)
    scratch = tempfile.mkdtemp(prefix="aqd-score-")
    try:
        project = os.path.join(scratch, "project")
        taken = build_scoring_tree(args.phase_root, args.task, args.pristine, args.agent, args.hidden, project)
        hidden = run_suite(project, "hidden_tests", "hidden", args.timeout, per_test=True)
        baseline = run_suite(project, "tests/baseline", "baseline", args.timeout, per_test=False)
        additive = run_suite(project, "tests/additive", "additive", args.timeout, per_test=False)
        report = summarise(args.task, taken, hidden, baseline, additive)
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    with open(args.out, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
    print(f"{args.task}: hidden {report['hidden_passed']}/{report['hidden_total']}, baseline {'pass' if report['baseline_all_pass'] else 'FAIL'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
