#!/usr/bin/env python3
"""Single use of the live-probe environment: refuse if environment aqd-cc-live-probe has EVER had a deployment
other than this job's own.

    python3 -I check_single_use.py --deployments deployments.json

Input: GitHub REST "List deployments" for ?environment=aqd-cc-live-probe (per_page=100). GitHub creates one
deployment record for each job that targets an environment, when the job is queued, approved or not. So in the one
authorised run exactly ONE record exists: this job's. Two or more means an earlier live dispatch (failed, cancelled,
rejected at the approval prompt, or passed) already consumed the approval; a new dispatch, even with new workflow
run and attempt numbers, is refused. Zero, or a response of an unexpected shape, also refuses (fail closed).
Runs before the token is written. The server-side record cannot be reset by editing the repository; reopening the
probe needs a new reviewed amendment (LIVE-PROBE.md section 6).
"""
import argparse
import json
import sys

NAME = "aqd-cc-live-probe"
NAMES = (NAME, "aqd-cc-live-smoke")  # the probe's and the SMOKE run's environments


def check(deployments, name=NAME):
    if not isinstance(deployments, list) or not all(isinstance(d, dict) for d in deployments):
        return ["the deployments listing is missing or of an unexpected shape"]
    if len(deployments) >= 100:
        return ["the deployments listing is full (100): refusing rather than paging"]
    if name not in NAMES:
        return ["unknown environment name"]
    if any(d.get("environment") != name for d in deployments):
        return [f"the listing holds deployments of another environment (the query must filter {name})"]
    if not deployments:
        return ["no deployment record for this job (unexpected; refusing)"]
    if len(deployments) > 1:
        return [f"{len(deployments)} deployments to {name}: an earlier live dispatch already used the approval"]
    return []


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--deployments", required=True)
    p.add_argument("--name", choices=NAMES, default=NAME)
    args = p.parse_args(argv)
    try:
        with open(args.deployments, encoding="utf-8") as h:
            data = json.load(h)
    except (OSError, ValueError):
        data = None
    reasons = check(data, args.name)
    for r in reasons:
        print(f"single use: {r}")
    print("single use: " + ("first and only deployment of the live-probe environment" if not reasons else "REFUSED"))
    return 0 if not reasons else 1


if __name__ == "__main__":
    sys.exit(main())
