# Disposable image for the no-model-call dry run (dryrun-cc.sh). Built at test time; never pushed anywhere.
FROM ubuntu@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289
RUN apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends sudo python3 git bubblewrap socat procps diffutils ca-certificates >/dev/null \
 && rm -rf /var/lib/apt/lists/*
