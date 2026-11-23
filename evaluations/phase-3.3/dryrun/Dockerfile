# Disposable image for the no-model-call dry run (dryrun-cc.sh). Built at test time; never pushed anywhere.
FROM ubuntu@sha256:9c7f200c07e3d4a03e7249d2c16bf66a51120fb876aa2242cf31451412543289
# Retries and timeouts: a stalled mirror fails the build quickly instead of hanging until the job limit.
RUN printf 'Acquire::Retries "5";\nAcquire::http::Timeout "30";\nAcquire::https::Timeout "30";\n' >/etc/apt/apt.conf.d/80aqd \
 && apt-get update -qq \
 && apt-get install -y -qq --no-install-recommends sudo python3 git bubblewrap socat iptables procps diffutils ca-certificates >/dev/null \
 && rm -rf /var/lib/apt/lists/*
