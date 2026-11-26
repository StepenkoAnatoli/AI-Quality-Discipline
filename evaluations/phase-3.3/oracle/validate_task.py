#!/usr/bin/env python3
"""Mechanical oracle validation of one Phase 3.3 task package (STAGE0-SOLO.md §2.2). Offline, no model, no network.

    python3 -I validate_task.py --package DIR --out report.json [--max-mutations N] [--timeout S]
        (by default every mechanical mutation site runs; N caps them, and the report then says `sampled: true`)
        [--image NAME@sha256:DIGEST]   (score in the scorer's Docker sandbox instead of the local runner)

Every candidate solution is scored with the harness's own fail-closed scorer (`phase-3.2/harness/score_run.py`), so the
checks validated here are exactly the checks Stage 1 scores. Candidate code here is written by the protocol's own
sessions (reference, alternatives, mutants, shortcut, mechanical mutations of the reference), so it runs with the
scorer's local runner (`--sandbox none --trusted-code`); agent code from live runs is never validated with this tool.

Package layout (one task):

    task.json                       {"kind": "aqd-phase-3.3-task-package", "schema_version": 1, "task": ID,
                                     "mutation_seed": INT}
    allowlist.json                  a score_run allowlist with exactly this task; its source_dir is tasks/<ID>/project
    tasks/<ID>/project/...          the pristine public project
    prompts/S.md, prompts/D.md      the two prompt variants
    oracle/hidden/hidden_tests/...  the hidden tests (test ids end in test_H<nn>_<name>)
    oracle/source-map.json          {"kind": "aqd-phase-3.3-source-map", "schema_version": 1, "checks": {"H01": {
                                       "obligation": TEXT, "sources": {"S": SRC, "D": SRC}}}}
                                    SRC = {"kind": "prompt", "quote": TEXT}
                                        | {"kind": "repo", "path": REL, "line": N, "quote": TEXT}
    oracle/reference/               the reference solution: mutable files only, at their project paths
    oracle/alternatives/<name>/     one or more alternative correct designs (mutable files only)
    oracle/alt-reviews.json         optional: {"kind": "aqd-phase-3.3-alt-reviews", "schema_version": 1, "reviews": [
                                       {"alternative": NAME, "check": "H01", "finding": "demands_only_its_source",
                                        "reviewer_session": ID, "saw_candidate_code": false}]}
    oracle/mutants/<name>/          3 or more realistic wrong implementations (mutable files only)
    oracle/shortcut/                a solution that only hard-codes the visible examples and tests

The task is VALID only if all of these hold (STAGE0-SOLO.md §2.2):
  1. reference: every hidden and every baseline check passes;
  2. pristine: at least one hidden check fails;
  3. alternatives: AT LEAST ONE passes every hidden and every baseline check. Any other alternative passes every
     baseline check, and every hidden check it fails has a review finding "demands_only_its_source" made without
     seeing the candidate code; the report lists those checks (T7). A review never replaces a passing alternative;
  4. mutants: at least 3 DISTINCT ones (identical file sets count once), each failing at least one hidden check and
     passing every baseline check (a realistic wrong implementation passes the project's own tests);
  5. source map: exactly the inventoried checks; S sources are prompt sentences found in prompts/S.md; D sources are
     found in prompts/D.md or at the cited line of the pristine project (whitespace-normalised);
  6. shortcut: fails at least one hidden check.
Mechanical mutation of the reference (seeded; operator, comparison, boolean, constant and statement-removal
mutations) is measured, never gated: the hidden kill rate and the surviving mutations are reported. Each mutant
changes one file of the COMPLETE reference (the other mutable files stay the reference's), and runs only after the
unmutated reference control passes, so a kill is attributable to the mutation. A mutant that passes every hidden check
but fails a baseline check is counted as killed by the baseline (it cannot be fully correct either), separately.

Limits (review 2026-11-26): VALID means mechanical acceptance by these rules. It does not establish that each
assertion follows from its quoted source (semantic review), that the task is solvable from public material within the
time budget, or that it behaves the same in the pinned scoring container unless --image is given (then every candidate is scored
in the scorer's Docker sandbox, as for real scoring).

Exit 0 = valid, 1 = invalid, 2 = usage error (unreadable package).
"""
import argparse
import ast
import hashlib
import json
import os
import random
import re
import shutil
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "phase-3.2", "harness"))
import manifest as manifest_mod  # noqa: E402
import score_run  # noqa: E402

PACKAGE_KIND = "aqd-phase-3.3-task-package"
SOURCE_MAP_KIND = "aqd-phase-3.3-source-map"
ALT_REVIEWS_KIND = "aqd-phase-3.3-alt-reviews"
ALT_FINDING = "demands_only_its_source"
MIN_MUTANTS = 3
VARIANTS = ("S", "D")


class UsageError(Exception):
    pass


def _load_json(path, kind=None):
    try:
        with open(path, encoding="utf-8") as h:
            data = json.load(h)
    except (OSError, ValueError) as exc:
        raise UsageError(f"{os.path.basename(path)}: {exc}")
    if not isinstance(data, dict) or (kind and (data.get("kind") != kind or data.get("schema_version") != 1)):
        raise UsageError(f"{os.path.basename(path)}: not a {kind} file (schema 1)")
    return data


def _norm(text):
    return " ".join(str(text).split())


def _files_below(root):
    out = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != "__pycache__"]
        for name in filenames:
            if name.endswith(".pyc"):
                continue
            out.append(os.path.relpath(os.path.join(dirpath, name), root).replace(os.sep, "/"))
    return sorted(out)


class Package:
    def __init__(self, root):
        self.root = root
        meta = _load_json(os.path.join(root, "task.json"), PACKAGE_KIND)
        self.task = meta.get("task")
        self.seed = meta.get("mutation_seed")
        if not isinstance(self.task, str) or not re.match(r"^[A-Za-z0-9-]+$", self.task):
            raise UsageError("task.json: task must be an id of letters, digits and hyphens")
        if not isinstance(self.seed, int) or isinstance(self.seed, bool):
            raise UsageError("task.json: mutation_seed must be an integer")
        try:
            allowlist, _ = manifest_mod.load_allowlist(root)
            entries = manifest_mod.task_entries(allowlist, self.task)
        except (OSError, ValueError, KeyError, manifest_mod.UsageError) as exc:
            raise UsageError(f"allowlist.json: {exc}")
        if sorted(allowlist.get("tasks", {})) != [self.task]:
            raise UsageError("allowlist.json must define exactly this package's task")
        if allowlist["tasks"][self.task].get("source_dir") != f"tasks/{self.task}/project":
            raise UsageError("allowlist.json source_dir must be tasks/<task>/project")
        self.mutable = sorted(rel for rel, _src, cat in entries if cat == "mutable")
        if not self.mutable:
            raise UsageError("the task has no mutable file")
        self.pristine = os.path.join(root, "tasks", self.task, "project")
        self.hidden = os.path.join(root, "oracle", "hidden")
        for path in (self.pristine, os.path.join(self.hidden, "hidden_tests")):
            if not os.path.isdir(path):
                raise UsageError(f"missing directory {os.path.relpath(path, root)}")
        self.prompts = {}
        for v in VARIANTS:
            try:
                with open(os.path.join(root, "prompts", f"{v}.md"), encoding="utf-8") as h:
                    self.prompts[v] = h.read()
            except OSError:
                raise UsageError(f"missing prompts/{v}.md")
        self.source_map = _load_json(os.path.join(root, "oracle", "source-map.json"), SOURCE_MAP_KIND)
        reviews_path = os.path.join(root, "oracle", "alt-reviews.json")
        self.alt_reviews = (_load_json(reviews_path, ALT_REVIEWS_KIND).get("reviews") or []) \
            if os.path.exists(reviews_path) else []

    def solutions(self, kind):
        base = os.path.join(self.root, "oracle", kind)
        if not os.path.isdir(base):
            return {}
        return {name: os.path.join(base, name) for name in sorted(os.listdir(base))
                if os.path.isdir(os.path.join(base, name)) and name != "__pycache__"}


class Validator:
    def __init__(self, pkg, timeout, image=None):
        self.pkg = pkg
        # The local runner by default; with an image pinned by digest, the scorer's own Docker sandbox (no network,
        # read-only code, non-root), as used for real scoring (review 2026-11-26, finding 4).
        self.runner = score_run.DockerRunner(timeout, image) if image else score_run.LocalRunner(timeout)
        self.scratch = tempfile.mkdtemp(prefix="aqd-validate-")
        self.inventory = score_run.build_inventory(pkg.root, pkg.task, pkg.pristine, pkg.hidden, timeout)
        self.check_ids = sorted(score_run.CHECK_ID.search(i).group(1) for i in self.inventory["hidden_ids"])

    def close(self):
        shutil.rmtree(self.scratch, ignore_errors=True)

    def agent_dir(self, overlay=None, files=None):
        """Pristine project with the solution's mutable files laid over it."""
        agent = tempfile.mkdtemp(prefix="agent-", dir=self.scratch)
        shutil.rmtree(agent)
        shutil.copytree(self.pkg.pristine, agent)
        if overlay is not None:
            extra = [rel for rel in _files_below(overlay) if rel not in self.pkg.mutable]
            if extra:
                raise score_run.Invalid(f"solution holds files that are not mutable: {extra}")
            for rel in _files_below(overlay):
                shutil.copyfile(os.path.join(overlay, *rel.split("/")), os.path.join(agent, *rel.split("/")))
        for rel, text in (files or {}).items():
            with open(os.path.join(agent, *rel.split("/")), "w", encoding="utf-8") as h:
                h.write(text)
        return agent

    def score(self, overlay=None, files=None):
        """Returns a compact result: valid, hidden outcomes per check, baseline_all_pass; or the invalid reasons."""
        try:
            agent = self.agent_dir(overlay, files)
        except score_run.Invalid as exc:
            return {"valid": False, "reasons": [str(exc)]}
        report = score_run.score(self.pkg.root, self.pkg.task, self.pkg.pristine, agent, self.pkg.hidden,
                                 self.inventory, self.runner)
        shutil.rmtree(agent, ignore_errors=True)
        if report["evaluation_status"] != "valid":
            return {"valid": False, "reasons": report["invalid_reasons"]}
        return {"valid": True, "hidden": report["hidden_checks"], "baseline_all_pass": report["baseline_all_pass"],
                "failed_hidden": sorted(c for c, o in report["hidden_checks"].items() if o != "pass")}


def _tree_digest(root):
    h = hashlib.sha256()
    for rel in _files_below(root):
        with open(os.path.join(root, *rel.split("/")), "rb") as f:
            h.update(rel.encode("utf-8") + b"\0" + hashlib.sha256(f.read()).digest())
    return h.hexdigest()


def check_source_map(pkg, check_ids):
    reasons = []
    checks = pkg.source_map.get("checks")
    if not isinstance(checks, dict):
        return ["source map: no checks"]
    if sorted(checks) != check_ids:
        reasons.append(f"source map: checks {sorted(checks)} differ from the inventoried checks {check_ids}")
    for cid, entry in sorted(checks.items()):
        if not isinstance(entry, dict) or not _norm(entry.get("obligation") or ""):
            reasons.append(f"{cid}: no obligation")
            continue
        sources = entry.get("sources") if isinstance(entry.get("sources"), dict) else {}
        for v in VARIANTS:
            src = sources.get(v)
            if not isinstance(src, dict) or not _norm(src.get("quote") or ""):
                reasons.append(f"{cid}/{v}: no source quote")
                continue
            quote = _norm(src["quote"])
            if src.get("kind") == "prompt":
                if quote not in _norm(pkg.prompts[v]):
                    reasons.append(f"{cid}/{v}: quote not found in prompts/{v}.md")
            elif src.get("kind") == "repo" and v == "D":
                reasons += _check_repo_quote(pkg, cid, src, quote)
            elif src.get("kind") == "repo":
                reasons.append(f"{cid}/S: an S-variant source must be a prompt sentence")
            else:
                reasons.append(f"{cid}/{v}: unknown source kind")
    return reasons


def _check_repo_quote(pkg, cid, src, quote):
    rel, line = src.get("path"), src.get("line")
    if not isinstance(rel, str) or not isinstance(line, int) or isinstance(line, bool) or line < 1:
        return [f"{cid}/D: repo source needs path and a positive line"]
    parts = rel.split("/")
    if rel.startswith("/") or "\\" in rel or any(p in ("", ".", "..") for p in parts):
        return [f"{cid}/D: unsafe path {rel!r}"]
    path = os.path.join(pkg.pristine, *parts)
    try:
        with open(path, encoding="utf-8") as h:
            lines = h.read().splitlines()
    except OSError:
        return [f"{cid}/D: {rel} not in the pristine project"]
    if line > len(lines) or quote not in _norm(lines[line - 1]):
        return [f"{cid}/D: quote not found at {rel}:{line}"]
    return []


# ------------------------------------------------------------------ mechanical mutation of the reference

_SWAPS = {ast.Add: ast.Sub, ast.Sub: ast.Add, ast.Mult: ast.FloorDiv, ast.FloorDiv: ast.Mult, ast.Mod: ast.FloorDiv,
          ast.Lt: ast.LtE, ast.LtE: ast.Lt, ast.Gt: ast.GtE, ast.GtE: ast.Gt, ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
          ast.And: ast.Or, ast.Or: ast.And, ast.In: ast.NotIn, ast.NotIn: ast.In}


def _sites(tree):
    sites = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.BinOp, ast.AugAssign)) and type(node.op) in _SWAPS:
            sites.append(("op", node))
        elif isinstance(node, ast.BoolOp) and type(node.op) in _SWAPS:
            sites.append(("op", node))
        elif isinstance(node, ast.Compare):
            for i, op in enumerate(node.ops):
                if type(op) in _SWAPS:
                    sites.append(("cmp", (node, i)))
        elif isinstance(node, ast.Constant) and type(node.value) is int:
            sites.append(("const", node))
        elif isinstance(node, (ast.FunctionDef, ast.If, ast.For, ast.While, ast.With, ast.Try)):
            for field in ("body", "orelse", "finalbody"):
                body = getattr(node, field, None)
                if isinstance(body, list) and len(body) > 1:
                    for i, stmt in enumerate(body):
                        docstring = isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                            and isinstance(stmt.value.value, str)
                        if not docstring and isinstance(stmt, (ast.Assign, ast.AugAssign, ast.Expr, ast.If, ast.Raise,
                                                               ast.Return)):
                            sites.append(("drop", (body, i)))  # removing a docstring is an equivalent mutant
    return sites


def _apply(kind, target):
    if kind == "op":
        old = target.op
        target.op = _SWAPS[type(old)]()
        return lambda: setattr(target, "op", old)
    if kind == "cmp":
        node, i = target
        old = node.ops[i]
        node.ops[i] = _SWAPS[type(old)]()
        return lambda: node.ops.__setitem__(i, old)
    if kind == "const":
        old = target.value
        target.value = old + 1
        return lambda: setattr(target, "value", old)
    body, i = target
    old = body[i]
    body[i] = ast.Pass()
    return lambda: body.__setitem__(i, old)


def mechanical_mutants(pkg, max_mutations=None):
    """Seeded mutants of the reference: [(label, {rel: source})]. Deterministic for a package. None: every site."""
    ref = os.path.join(pkg.root, "oracle", "reference")
    candidates = []
    for rel in pkg.mutable:
        path = os.path.join(ref, *rel.split("/"))
        if not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as h:
            source = h.read()
        tree = ast.parse(source)
        for index, (kind, _target) in enumerate(_sites(tree)):
            candidates.append((rel, source, kind, index))
    rng = random.Random(pkg.seed)
    rng.shuffle(candidates)
    out = []
    for rel, source, kind, index in (candidates if max_mutations is None else candidates[:max_mutations]):
        tree = ast.parse(source)
        site_kind, target = _sites(tree)[index]
        _apply(site_kind, target)
        out.append((f"{rel}#{kind}{index}", {rel: ast.unparse(ast.fix_missing_locations(tree)) + "\n"}))
    return out


# ------------------------------------------------------------------ the validation

def mutation_sites(pkg):
    """How many mechanical mutation sites the reference has (the size of a complete run)."""
    ref = os.path.join(pkg.root, "oracle", "reference")
    total = 0
    for rel in pkg.mutable:
        path = os.path.join(ref, *rel.split("/"))
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as h:
                total += len(_sites(ast.parse(h.read())))
    return total


def validate(package_root, max_mutations=None, timeout=60, image=None):
    if image is not None and (not isinstance(image, str) or "@sha256:" not in image):
        raise UsageError("--image must be pinned by digest (name@sha256:...)")
    pkg = Package(package_root)
    v = Validator(pkg, timeout, image)
    reasons, report = [], {"task": pkg.task, "checks": v.check_ids}
    try:
        ref_dir = os.path.join(pkg.root, "oracle", "reference")
        ref = v.score(ref_dir) if os.path.isdir(ref_dir) else {"valid": False, "reasons": ["no reference"]}
        report["reference"] = ref
        if not ref["valid"] or ref["failed_hidden"] or not ref["baseline_all_pass"]:
            reasons.append("reference: does not pass every hidden and baseline check")

        pristine = v.score()
        report["pristine"] = pristine
        if not pristine["valid"] or not pristine["failed_hidden"]:
            reasons.append("pristine: passes every hidden check (or could not be scored)")

        alts = pkg.solutions("alternatives")
        report["alternatives"], report["alt_reviewed_checks"] = {}, {}
        if not alts:
            reasons.append("alternatives: none")
        for name, path in alts.items():
            res = v.score(path)
            report["alternatives"][name] = res
            if not res["valid"]:
                reasons.append(f"alternative {name}: could not be scored")
                continue
            if not res["baseline_all_pass"]:
                reasons.append(f"alternative {name}: fails a baseline check")
            reviewed = {r.get("check") for r in pkg.alt_reviews if isinstance(r, dict)
                        and r.get("alternative") == name and r.get("finding") == ALT_FINDING
                        and r.get("saw_candidate_code") is False and r.get("reviewer_session")}
            unreviewed = [c for c in res["failed_hidden"] if c not in reviewed]
            if unreviewed:
                reasons.append(f"alternative {name}: fails {unreviewed} with no source-only review finding")
            if res["failed_hidden"]:
                report["alt_reviewed_checks"][name] = sorted(set(res["failed_hidden"]) & reviewed)
        passing = sorted(n for n, r in report["alternatives"].items()
                         if r.get("valid") and not r.get("failed_hidden") and r.get("baseline_all_pass"))
        report["passing_alternatives"] = passing
        if alts and not passing:
            # A source-only review can explain why an alternative fails a check, but it is no substitute for an
            # independently written solution that passes everything (review 2026-11-26, finding 2).
            reasons.append("alternatives: none passes every hidden and baseline check")

        mutants = pkg.solutions("mutants")
        report["mutants"], seen, duplicates = {}, {}, []
        for name, path in mutants.items():
            digest = _tree_digest(path)
            if digest in seen:
                duplicates.append(f"{name} = {seen[digest]}")
                continue
            seen[digest] = name
            res = v.score(path)
            report["mutants"][name] = res
            if not res["valid"] or not res["failed_hidden"]:
                reasons.append(f"mutant {name}: not caught by any hidden check")
            elif not res["baseline_all_pass"]:
                # A realistic wrong implementation passes the project's own tests (MUTANTS.md); one that breaks
                # them, or does not import, is caught by the visible tests already and says nothing about the oracle.
                reasons.append(f"mutant {name}: fails a baseline check, so it is not a realistic wrong implementation")
        report["duplicate_mutants"] = duplicates
        if len(seen) < MIN_MUTANTS:
            reasons.append(f"mutants: {len(seen)} distinct, need at least {MIN_MUTANTS}")

        short_dir = os.path.join(pkg.root, "oracle", "shortcut")
        short = v.score(short_dir) if os.path.isdir(short_dir) else {"valid": False, "reasons": ["no shortcut"]}
        report["shortcut"] = short
        if not short["valid"] or not short["failed_hidden"]:
            reasons.append("shortcut: not caught by any hidden check")

        map_reasons = check_source_map(pkg, v.check_ids)
        report["source_map_problems"] = map_reasons
        reasons += map_reasons

        # Each mechanical mutant changes ONE file of the reference; the other mutable files are the reference's, so a
        # kill is attributable to the mutation (review 2026-11-26, finding 1). The unmutated control must pass.
        mech = {"generated": 0, "scored": 0, "killed_by_hidden": 0, "killed_by_baseline_only": 0, "survivors": [],
                "unscorable": 0,
                "reference_control_passes": bool(ref.get("valid") and not ref.get("failed_hidden")
                                                 and ref.get("baseline_all_pass"))}
        for label, files in (mechanical_mutants(pkg, max_mutations) if mech["reference_control_passes"] else []):
            mech["generated"] += 1
            res = v.score(ref_dir, files=files)
            if not res["valid"]:
                mech["unscorable"] += 1
                continue
            mech["scored"] += 1
            if res["failed_hidden"]:
                mech["killed_by_hidden"] += 1
            elif not res["baseline_all_pass"]:
                # fully_correct needs every baseline check too, so a visible test also kills it
                mech["killed_by_baseline_only"] += 1
            else:
                mech["survivors"].append(label)
        mech["hidden_kill_rate"] = round(mech["killed_by_hidden"] / mech["scored"], 4) if mech["scored"] else None
        # A capped run is a sample: say so, so that a sample is never read as the whole (H4 and H6 were sampled at
        # 60 of 105 and 40 of 77 sites before this was recorded).
        mech["sites"] = mutation_sites(pkg)
        mech["sampled"] = mech["generated"] < mech["sites"]
        report["mechanical_mutation"] = mech
    finally:
        v.close()
    report["valid"] = not reasons
    report["reasons"] = reasons
    return report


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--package", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-mutations", type=int, default=None, help="cap on mechanical mutants (default: every site)")
    p.add_argument("--timeout", type=int, default=60)
    p.add_argument("--image", help="score in the scorer's Docker sandbox with this image, pinned by digest")
    args = p.parse_args(argv)
    try:
        report = validate(args.package, args.max_mutations, args.timeout, args.image)
    except (UsageError, score_run.Invalid) as exc:
        print(f"[validate] refused: {exc}", file=sys.stderr)
        return 2
    with open(args.out, "w", encoding="utf-8") as h:
        json.dump(report, h, indent=2, sort_keys=True)
        h.write("\n")
    mech = report["mechanical_mutation"]
    verdict = "VALID" if report["valid"] else "INVALID"
    print(f"[validate] {report['task']}: {verdict}; reasons: {len(report['reasons'])}; "
          f"mechanical mutants killed {mech['killed_by_hidden']} of {mech['scored']}"
          + (f" (a SAMPLE of {mech['generated']} of {mech['sites']} sites)" if mech.get("sampled") else ""))
    for reason in report["reasons"]:
        print(f"[validate]   {reason}")
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
