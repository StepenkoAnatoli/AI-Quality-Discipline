#!/usr/bin/env bash
# Container entry for the offline boundary probe. RUN ONLY IN A DISPOSABLE CONTAINER with --network none.
#   docker run --rm --network none [--privileged] -v <repo>:/src:ro -v <claude dir>:/opt/cc:ro -v <out>:/out IMAGE \
#       bash /src/evaluations/phase-3.3/boundary/run-boundary.sh <privileged|unprivileged>
set -euo pipefail
label="${1:-privileged}"
cp -r /src /work
python3 -I /work/evaluations/phase-3.3/boundary/boundary_probe.py --claude /opt/cc/claude --out /out --label "$label"
