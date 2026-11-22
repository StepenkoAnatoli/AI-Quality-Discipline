#!/usr/bin/env python3
"""Score one agent result against the hidden and baseline checks. Fails closed.

    score_run.py inventory --phase-root DIR --task ID --pristine DIR --hidden DIR --out FILE
    score_run.py score --phase-root DIR --task ID --pristine DIR --agent DIR --hidden DIR \
                       --inventory FILE --out FILE --sandbox docker --image IMAGE@sha256:...
    score_run.py score ... --sandbox none --trusted-code     (reference/mutant/synthetic code only)

`inventory` records, from the pristine project and the hidden tests only (never
from candidate code), the exact hidden and baseline test ids and the SHA-256 of
every hidden-test file. The evaluator keeps it with the hidden tests.

`score` produces an evaluation that is either VALID or INVALID:
  * The hidden files must match the inventory hashes, and the pristine project
    must list exactly the inventoried tests with no load error (the evaluator
    is checked before the candidate is run).
  * Every inventoried test is run in its own process; candidate code runs in a
    sandbox (`--sandbox docker`: no network, read-only code, non-root, no host
    environment). `--sandbox none` refuses to run unless `--trusted-code` is given.
  * Each result file must exist, parse, carry the per-test nonce and the
    requested id, and report exactly one executed test. A missing, malformed,
    duplicated, skipped or unrequested result, a crashed runner or an
    inventory mismatch makes the evaluation INVALID: no score is produced.
  * A test that fails, errors, times out, or cannot import the candidate's code
    is a VALID failure of that check. A valid zero is not an invalid evaluation.
Exit codes: 0 valid evaluation, 3 invalid evaluation, 2 usage error.

The scoring tree is the pristine project plus only the task's mutable file
from the agent result. Additive (agent-written) tests run in a separate tree;
they are reported but never scored, and scored code cannot import them.
A missing agent result directory is INVALID (an infrastructure failure), never
a valid zero. Every valid evaluation records review_subject_sha256, the hash of
the scored agent code; when requires_review is true, analyze.py counts the run
only after a reviewer's verdict names that hash (see analyze.py).
"""
import argparse
import ast
import datetime
import hashlib
import io
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
import tempfile
import tokenize

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import manifest as manifest_mod  # noqa: E402

CHECK_ID = re.compile(r"\.test_(H\d{2})_[A-Za-z0-9_]+$")
INVENTORY_KIND = "aqd-phase-3.2-test-inventory"
SCORE_KIND = "aqd-phase-3.2-hidden-score"
SCORE_SCHEMA_VERSION = 3
RESULT_KEYS = {"nonce", "requested_id", "tests_run", "outcome", "detail"}
VALID_OUTCOMES = {"pass", "fail", "error"}

# Constructs a solution to these tasks has no reason to use, and which could be
# used to tamper with an in-process test run. A match does not invalidate the
# evaluation; it marks the run for mandatory human review of the diff.
TAMPER_PATTERNS = (
    r"\bunittest\b", r"\bsys\b", r"\bos\._exit\b", r"\binspect\b", r"\bgc\b",
    r"_getframe", r"\bbuiltins\b", r"__builtins__", r"__import__", r"\bimportlib\b", r"hidden_tests", r"run_checks",
    r"\bsubprocess\b", r"\bsocket\b", r"\bctypes\b", r"\batexit\b", r"\bsignal\b",
    r"\bsetprofile\b", r"\bsettrace\b", r"\bos\.environ\b", r"\bshutil\b", r"\burllib\b",
    r"\bexec\b", r"\beval\b", r"(?<![\w.])compile\s*\(",
)

# Structural check (AST). A regex list alone is evaded by building names at
# run time (for example exec("import unitt" + "est")), so any import outside
# this list, any dynamic-execution or reflection builtin, and any access to a
# private or dunder attribute (other than on self/cls) also forces a review.
# This is detection, not prevention: see SPECIFICATION.md section 7.
ALLOWED_IMPORTS = frozenset({
    "__future__", "abc", "bisect", "collections", "contextlib", "copy", "csv", "dataclasses", "datetime", "decimal",
    "enum", "fractions", "functools", "hashlib", "heapq", "hmac", "io", "itertools", "json", "logging", "math",
    "numbers", "operator", "random", "re", "secrets", "sqlite3", "statistics", "string", "textwrap", "threading",
    "time", "typing", "unicodedata", "uuid",
})
# Several allowed modules re-export a risky module as a plain attribute (logging.os, contextlib.os, uuid.os, uuid.platform on 3.12,
# enum.bltns = builtins, json.codecs, logging.traceback, typing.types), and io.open / codecs.open open files
# (for example /proc/self/mem). An attribute with one of these names forces a review, unless it is on self/cls.
# Frame and code attributes are flagged as well, in case a frame is reached some other way. The test suite
# introspects every allowed module so that a new route cannot be added unnoticed.
ESCAPE_ATTRIBUTES = frozenset({
    "os", "bltns", "builtins", "codecs", "traceback", "types", "copyreg", "open", "platform",
    "f_locals", "f_globals", "f_back", "f_code", "f_builtins", "tb_frame", "gi_frame", "cr_frame", "ag_frame",
})
FLAGGED_NAMES = frozenset({
    "exec", "eval", "compile", "__import__", "globals", "locals", "vars", "getattr", "setattr", "delattr",
    "breakpoint", "open", "__builtins__", "__loader__", "__spec__",
})
ALLOWED_DUNDERS = frozenset({"__init__", "__name__", "__all__", "__enter__", "__exit__", "__post_init__", "__repr__",
                             "__str__", "__eq__", "__hash__", "__lt__", "__iter__", "__len__", "__slots__"})


class Invalid(Exception):
    """The evaluation cannot be trusted; no score may be produced."""


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hidden_file_hashes(hidden):
    package = os.path.join(hidden, "hidden_tests")
    if not os.path.isdir(package) or os.path.islink(package):
        raise Invalid(f"hidden test package not found: {package}")
    found = {}
    for root, dirs, files in os.walk(package):
        dirs[:] = sorted(d for d in dirs if d != "__pycache__")
        for name in sorted(files):
            if name.endswith(".pyc"):
                continue
            path = os.path.join(root, name)
            if os.path.islink(path):
                raise Invalid(f"symlink in hidden tests: {path}")
            found[os.path.relpath(path, hidden).replace(os.sep, "/")] = sha256_file(path)
    return found


def _without_comments(text):
    try:
        tokens = [t for t in tokenize.generate_tokens(io.StringIO(text).readline) if t.type != tokenize.COMMENT]
        return tokenize.untokenize(tokens)
    except (tokenize.TokenError, SyntaxError, IndentationError):
        return text


def _structural_flags(text, own_packages):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return set()  # cannot be imported, so it cannot run; the checks fail on their own
    flags = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            modules = [] if node.level else [node.module or ""]
        else:
            modules = []
        for module in modules:
            top = module.split(".")[0]
            if top not in ALLOWED_IMPORTS and top not in own_packages:
                flags.add(f"import:{module}")
        if isinstance(node, ast.Name) and node.id in FLAGGED_NAMES:
            flags.add(f"name:{node.id}")
        elif isinstance(node, ast.Attribute) and ((node.attr.startswith("_") and node.attr not in ALLOWED_DUNDERS)
                                                  or node.attr in ESCAPE_ATTRIBUTES):
            if not (isinstance(node.value, ast.Name) and node.value.id in ("self", "cls")):
                flags.add(f"attribute:{node.attr}")
    return flags


def scan_for_tampering(text, own_packages=()):
    code = _without_comments(text)
    found = {p for p in TAMPER_PATTERNS if re.search(p, code)}
    return sorted(found | _structural_flags(text, set(own_packages)))


def review_subject_sha256(mutable_bytes):
    """Hash of exactly the agent code that was scored; a tamper verdict must name it."""
    digest = hashlib.sha256()
    for rel in sorted(mutable_bytes):
        digest.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(mutable_bytes[rel]).digest())
    return digest.hexdigest()


# ---------------------------------------------------------------- runners

class LocalRunner:
    """Unsandboxed subprocess. Only for code the evaluator wrote or trusts."""

    name = "none"

    def __init__(self, timeout):
        self.timeout = timeout

    def run(self, tree, outdir, args, stdin_text):
        env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "LANG")}
        env.update(PYTHONDONTWRITEBYTECODE="1", PYTHONHASHSEED="0", PYTHONIOENCODING="utf-8")
        argv = [sys.executable, "run_checks.py"] + [a.replace("{out}", outdir) for a in args]
        try:
            proc = subprocess.run(argv, cwd=tree, env=env, input=stdin_text, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=self.timeout, text=True, encoding="utf-8", errors="replace")
            return proc.returncode, proc.stdout[-8000:]
        except subprocess.TimeoutExpired as exc:
            out = exc.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return "timeout", out[-8000:]


class DockerRunner:
    """One fresh container per test: no network, read-only code, non-root, no host env."""

    name = "docker"

    def __init__(self, timeout, image, docker="docker"):
        self.timeout = timeout
        self.image = image
        self.docker = docker

    def command(self, tree, outdir, args, container):
        return [
            self.docker, "run", "--rm", "-i", "--name", container,
            "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256", "--memory", "1g", "--cpus", "2", "--user", "65534:65534",
            "--tmpfs", "/tmp:rw,size=256m", "--shm-size", "128m",
            "-e", "HOME=/tmp", "-e", "TMPDIR=/tmp", "-e", "PYTHONDONTWRITEBYTECODE=1", "-e", "PYTHONHASHSEED=0",
            "-e", "LANG=C.UTF-8", "-v", f"{tree}:/work:ro", "-v", f"{outdir}:/out:rw", "-w", "/work",
            self.image, "python", "run_checks.py",
        ] + [a.replace("{out}", "/out") for a in args]

    def run(self, tree, outdir, args, stdin_text):
        container = f"aqd-score-{secrets.token_hex(6)}"
        os.chmod(outdir, 0o777)
        try:
            proc = subprocess.run(self.command(tree, outdir, args, container), input=stdin_text, stdout=subprocess.PIPE,
                                  stderr=subprocess.STDOUT, timeout=self.timeout, text=True, encoding="utf-8", errors="replace")
            return proc.returncode, proc.stdout[-8000:]
        except subprocess.TimeoutExpired as exc:
            subprocess.run([self.docker, "kill", container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            out = exc.stdout or ""
            if isinstance(out, bytes):
                out = out.decode("utf-8", "replace")
            return "timeout", out[-8000:]


def make_world_readable(tree):
    for root, dirs, files in os.walk(tree):
        os.chmod(root, 0o755)
        for name in files:
            path = os.path.join(root, name)
            if os.path.islink(path):
                continue  # chmod would follow the link and change a file on the scoring host
            os.chmod(path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)


# ---------------------------------------------------------------- trees

def copy_tree(src, dst):
    shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache"))


def build_tree(phase_root, task, pristine, agent, hidden, dest, include_additive=False):
    """Pristine project + (optionally) the agent's mutable file + hidden tests.

    The agent's additive tests are copied only when include_additive is set.
    The tree that runs the hidden and baseline checks never contains them, so
    the scored code cannot import agent-written test modules.
    Returns (taken, mutable_bytes); a mutable file the agent deleted maps to b"".
    """
    allowlist, _ = manifest_mod.load_allowlist(phase_root)
    entries = manifest_mod.task_entries(allowlist, task)
    copy_tree(pristine, dest)
    taken, mutable_bytes = [], {}
    if agent is not None:
        for rel, _source, category in entries:
            if category != "mutable":
                continue
            src = os.path.join(agent, *rel.split("/"))
            dst = os.path.join(dest, *rel.split("/"))
            if os.path.isfile(src) and not os.path.islink(src):
                shutil.copyfile(src, dst)
                taken.append(rel)
                with open(src, "rb") as handle:
                    mutable_bytes[rel] = handle.read()
            else:
                os.remove(dst)
                mutable_bytes[rel] = b""
    if agent is not None and include_additive:
        for additive in allowlist.get("additive_dirs", []):
            src = os.path.join(agent, *additive.split("/"))
            dst = os.path.join(dest, *additive.split("/"))
            if os.path.isdir(src) and not os.path.islink(src):
                shutil.rmtree(dst)
                # symlinks=True: a link is copied as a link (resolved inside the
                # sandbox), never followed to read a file on the scoring host.
                shutil.copytree(src, dst, symlinks=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
                taken.append(additive + "/")
    if os.path.exists(os.path.join(dest, "hidden_tests")):
        raise Invalid("the project already contains a hidden_tests directory")
    shutil.copytree(os.path.join(hidden, "hidden_tests"), os.path.join(dest, "hidden_tests"),
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copyfile(os.path.join(HERE, "run_checks.py"), os.path.join(dest, "run_checks.py"))
    make_world_readable(dest)
    return taken, mutable_bytes


def list_tests(runner, tree, scratch, start_dir):
    outdir = tempfile.mkdtemp(prefix="out-", dir=scratch)
    code, log = runner.run(tree, outdir, ["list", start_dir, "{out}/list.json"], "")
    path = os.path.join(outdir, "list.json")
    if code != 0 or not os.path.isfile(path):
        raise Invalid(f"listing {start_dir} failed (exit {code}): {log[-2000:]}")
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    return data.get("ids", []), data.get("load_errors", [])


# ---------------------------------------------------------------- inventory

def validate_inventory(inv, task):
    if not isinstance(inv, dict) or inv.get("kind") != INVENTORY_KIND or inv.get("task") != task:
        raise Invalid("inventory kind or task does not match")
    for key in ("hidden_ids", "baseline_ids"):
        ids = inv.get(key)
        if not isinstance(ids, list) or not ids or not all(isinstance(i, str) and i for i in ids):
            raise Invalid(f"inventory {key} must be a non-empty list of test ids")
        if len(ids) != len(set(ids)):
            raise Invalid(f"inventory {key} contains duplicates")
    checks = [CHECK_ID.search(i) for i in inv["hidden_ids"]]
    if not all(checks):
        raise Invalid("every hidden test id must be named test_H<nn>_<name>")
    numbers = [m.group(1) for m in checks]
    if len(numbers) != len(set(numbers)):
        raise Invalid("two hidden tests share a check number")
    files = inv.get("hidden_files")
    if not isinstance(files, dict) or not files:
        raise Invalid("inventory hidden_files missing")
    return inv


def build_inventory(phase_root, task, pristine, hidden, timeout=240):
    scratch = tempfile.mkdtemp(prefix="aqd-inv-")
    try:
        tree = os.path.join(scratch, "tree")
        build_tree(phase_root, task, pristine, None, hidden, tree)
        runner = LocalRunner(timeout)
        hidden_ids, hidden_errors = list_tests(runner, tree, scratch, "hidden_tests")
        baseline_ids, baseline_errors = list_tests(runner, tree, scratch, "tests/baseline")
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if hidden_errors or baseline_errors:
        raise Invalid(f"load errors while listing: {hidden_errors + baseline_errors}")
    inv = {
        "schema_version": 1,
        "kind": INVENTORY_KIND,
        "task": task,
        "created_utc": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "hidden_ids": hidden_ids,
        "baseline_ids": baseline_ids,
        "hidden_files": hidden_file_hashes(hidden),
    }
    return validate_inventory(inv, task)


# ---------------------------------------------------------------- scoring

def run_one(runner, tree, scratch, test_id):
    """Return (outcome, detail, log). Raises Invalid when the result cannot be trusted."""
    outdir = tempfile.mkdtemp(prefix="out-", dir=scratch)
    nonce = secrets.token_hex(16)
    code, log = runner.run(tree, outdir, ["run", "{out}/result.json", test_id], nonce + "\n")
    if code == "timeout":
        return "timeout", "the test did not finish within the time limit", log
    path = os.path.join(outdir, "result.json")
    extra = sorted(set(os.listdir(outdir)) - {"result.json"})
    if not os.path.isfile(path):
        raise Invalid(f"{test_id}: no result file (runner exit {code}); the test process crashed or was killed")
    try:
        with open(path, encoding="utf-8") as handle:
            record = json.load(handle)
    except (OSError, ValueError) as exc:
        raise Invalid(f"{test_id}: malformed result file ({exc})")
    if not isinstance(record, dict) or set(record) != RESULT_KEYS:
        raise Invalid(f"{test_id}: result file has unexpected fields")
    if not secrets.compare_digest(str(record["nonce"]), nonce):
        raise Invalid(f"{test_id}: result nonce does not match (result not written by this run of the runner)")
    if record["requested_id"] != test_id:
        raise Invalid(f"{test_id}: result is for {record['requested_id']!r}")
    if code != 0:
        raise Invalid(f"{test_id}: runner exited with {code} after writing its result")
    if extra:
        raise Invalid(f"{test_id}: unexpected files in the result directory: {extra}")
    outcome, tests_run, detail = record["outcome"], record["tests_run"], str(record["detail"])
    if outcome == "skip":
        raise Invalid(f"{test_id}: required check was skipped")
    if outcome == "missing":
        raise Invalid(f"{test_id}: test not found in the hidden package: {detail[-500:]}")
    if outcome not in VALID_OUTCOMES or not isinstance(tests_run, int) or isinstance(tests_run, bool):
        raise Invalid(f"{test_id}: unknown outcome {outcome!r}")
    import_failure = outcome == "error" and tests_run == 0 and detail.startswith("import failed")
    if tests_run != 1 and not import_failure:
        raise Invalid(f"{test_id}: {tests_run} tests executed, expected exactly 1")
    return outcome, detail, log


def run_inventory(runner, tree, scratch, ids):
    results = {}
    for test_id in ids:
        if test_id in results:
            raise Invalid(f"duplicate test id {test_id}")
        outcome, detail, log = run_one(runner, tree, scratch, test_id)
        results[test_id] = {"outcome": outcome, "detail": detail[-3000:], "log": log[-3000:]}
    return results


def score(phase_root, task, pristine, agent, hidden, inventory, runner):
    report = {
        "schema_version": SCORE_SCHEMA_VERSION,
        "kind": SCORE_KIND,
        "task": task,
        "sandbox": runner.name,
        "image": getattr(runner, "image", None),
        "evaluation_status": "invalid",
        "invalid_reasons": [],
        "primary": None,
    }
    scratch = tempfile.mkdtemp(prefix="aqd-score-")
    try:
        if agent is None or not os.path.isdir(agent) or os.path.islink(agent):
            raise Invalid(f"agent result directory missing or not a directory: {agent}; "
                          "a missing capture is an infrastructure failure, not a zero score")
        validate_inventory(inventory, task)
        report["inventory_sha256"] = hashlib.sha256(json.dumps(inventory, sort_keys=True).encode()).hexdigest()
        if hidden_file_hashes(hidden) != inventory["hidden_files"]:
            raise Invalid("hidden test files differ from the inventory")

        canary = os.path.join(scratch, "canary")
        build_tree(phase_root, task, pristine, None, hidden, canary)
        for start_dir, key in (("hidden_tests", "hidden_ids"), ("tests/baseline", "baseline_ids")):
            ids, errors = list_tests(runner, canary, scratch, start_dir)
            if errors or sorted(ids) != sorted(inventory[key]):
                missing = sorted(set(inventory[key]) - set(ids))
                unexpected = sorted(set(ids) - set(inventory[key]))
                raise Invalid(f"pristine {start_dir} does not match the inventory: missing={missing} "
                              f"unexpected={unexpected} load_errors={errors}")

        tree = os.path.join(scratch, "candidate")
        taken, mutable_bytes = build_tree(phase_root, task, pristine, agent, hidden, tree)
        report["taken_from_agent"] = taken
        own = {rel.split("/")[0] for rel in mutable_bytes}
        flags = {rel: scan_for_tampering(data.decode("utf-8", "replace"), own) for rel, data in mutable_bytes.items()}
        report["review_flags"] = {rel: found for rel, found in flags.items() if found}
        report["requires_review"] = bool(report["review_flags"])
        report["review_subject_sha256"] = review_subject_sha256(mutable_bytes)

        hidden_results = run_inventory(runner, tree, scratch, inventory["hidden_ids"])
        baseline_results = run_inventory(runner, tree, scratch, inventory["baseline_ids"])
        # Agent-written tests: run in a separate tree, reported, never scored,
        # never able to invalidate the evaluation.
        additive = {}
        additive_tree = os.path.join(scratch, "candidate-additive")
        try:
            additive_taken, _ = build_tree(phase_root, task, pristine, agent, hidden, additive_tree, include_additive=True)
            report["additive_tests_from_agent"] = [t for t in additive_taken if t.endswith("/")]
            additive_ids, additive_errors = list_tests(runner, additive_tree, scratch, "tests/additive")
        except (Invalid, OSError, ValueError) as exc:
            additive_ids, additive_errors = [], [f"agent tests not run: {type(exc).__name__}: {exc}"]
        for test_id in additive_ids:
            try:
                outcome, _detail, _log = run_one(runner, additive_tree, scratch, test_id)
            except Invalid as exc:
                outcome = f"unverifiable: {exc}"
            additive[test_id] = outcome
    except Invalid as exc:
        report["invalid_reasons"].append(str(exc))
        return report
    except Exception as exc:  # any evaluator fault is an invalid evaluation, never a score
        report["invalid_reasons"].append(f"evaluator error: {type(exc).__name__}: {exc}")
        return report
    finally:
        shutil.rmtree(scratch, ignore_errors=True)

    checks = {CHECK_ID.search(i).group(1): r["outcome"] for i, r in hidden_results.items()}
    if len(checks) != len(inventory["hidden_ids"]):
        report["invalid_reasons"].append("hidden results do not cover the inventory")
        return report
    hidden_passed = sum(1 for v in checks.values() if v == "pass")
    baseline_passed = sum(1 for r in baseline_results.values() if r["outcome"] == "pass")
    report.update({
        "evaluation_status": "valid",
        "hidden_checks": dict(sorted(checks.items())),
        "hidden_passed": hidden_passed,
        "hidden_total": len(checks),
        "baseline_outcomes": {k: v["outcome"] for k, v in baseline_results.items()},
        "baseline_passed": baseline_passed,
        "baseline_total": len(baseline_results),
        "baseline_all_pass": baseline_passed == len(baseline_results),
        "additive_outcomes": additive,
        "additive_load_errors": additive_errors,
        "details": {"hidden": hidden_results, "baseline": baseline_results},
    })
    report["primary"] = {
        "hidden_pass_fraction": round(hidden_passed / len(checks), 6),
        "fully_correct": hidden_passed == len(checks) and report["baseline_all_pass"],
    }
    return report


def _write_json(path, data):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    inv = sub.add_parser("inventory")
    sc = sub.add_parser("score")
    for p in (inv, sc):
        p.add_argument("--phase-root", required=True)
        p.add_argument("--task", required=True)
        p.add_argument("--pristine", required=True)
        p.add_argument("--hidden", required=True)
        p.add_argument("--out", required=True)
        p.add_argument("--timeout", type=int, default=240)
    sc.add_argument("--agent", required=True)
    sc.add_argument("--inventory", required=True)
    sc.add_argument("--sandbox", choices=("docker", "none"), required=True)
    sc.add_argument("--image")
    sc.add_argument("--trusted-code", action="store_true",
                    help="allow --sandbox none; only for reference solutions, mutants and synthetic tests")
    args = parser.parse_args(argv)

    if args.command == "inventory":
        try:
            data = build_inventory(args.phase_root, args.task, args.pristine, args.hidden, args.timeout)
        except Invalid as exc:
            print(f"score_run.py: inventory not built: {exc}", file=sys.stderr)
            return 3
        _write_json(args.out, data)
        print(f"{args.task}: inventory {len(data['hidden_ids'])} hidden, {len(data['baseline_ids'])} baseline")
        return 0

    if args.sandbox == "none" and not args.trusted_code:
        print("score_run.py: refusing to run candidate code without a sandbox (use --sandbox docker)", file=sys.stderr)
        return 2
    if args.sandbox == "docker":
        if not args.image or "@sha256:" not in args.image:
            print("score_run.py: --image must be pinned by digest (name@sha256:...)", file=sys.stderr)
            return 2
        runner = DockerRunner(args.timeout, args.image)
    else:
        runner = LocalRunner(args.timeout)
    try:
        with open(args.inventory, encoding="utf-8") as handle:
            inventory = json.load(handle)
    except (OSError, ValueError) as exc:
        inventory = {"error": str(exc)}
    report = score(args.phase_root, args.task, args.pristine, args.agent, args.hidden, inventory, runner)
    _write_json(args.out, report)
    if report["evaluation_status"] != "valid":
        print(f"{args.task}: EVALUATION INVALID: {'; '.join(report['invalid_reasons'])}")
        return 3
    print(f"{args.task}: hidden {report['hidden_passed']}/{report['hidden_total']}, "
          f"baseline {report['baseline_passed']}/{report['baseline_total']}"
          + (" (review flags)" if report["requires_review"] else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
