#!/usr/bin/env bash
# Install the pinned OpenCode V2 CLI into a dedicated root-owned prefix inside
# the benchmark host. This installs software and downloads packages, so
# it may only be run after the user has authorised benchmark execution.
#
# Usage: install-opencode.sh
# Records the installed version and the sha256 of every file under the prefix
# in $AQD_SEALED/opencode-install.json.

source "$(dirname "${BASH_SOURCE[0]}")/lib.sh"

require_cmd sudo npm node sha256sum
[[ -d "$AQD_SEALED" ]] || die "run setup-host.sh first"

if [[ -x "$AQD_OPENCODE_BIN" ]] && [[ "$("$AQD_OPENCODE_BIN" --version | tr -d '[:space:]')" == "$AQD_OPENCODE_VERSION" ]]; then
    log "OpenCode $AQD_OPENCODE_VERSION already installed at $AQD_OPENCODE_PREFIX"
else
    sudo install -d -o root -g root -m 0755 "$AQD_OPENCODE_PREFIX"
    sudo env "PATH=$PATH" npm install --global --prefix "$AQD_OPENCODE_PREFIX" --no-fund --no-audit \
        "$AQD_OPENCODE_PACKAGE@$AQD_OPENCODE_VERSION"
fi
sudo chown -R root:root "$AQD_OPENCODE_PREFIX"
sudo chmod -R a+rX,go-w "$AQD_OPENCODE_PREFIX"

VERSION="$("$AQD_OPENCODE_BIN" --version | tr -d '[:space:]')"
[[ "$VERSION" == "$AQD_OPENCODE_VERSION" ]] || die "installed version $VERSION, expected $AQD_OPENCODE_VERSION"

"$(python_bin)" - "$AQD_OPENCODE_PREFIX" "$VERSION" "$AQD_SEALED/opencode-install.json" <<'PY'
import hashlib, json, os, sys
prefix, version, out = sys.argv[1:]
files = {}
for root, _, names in os.walk(prefix):
    for name in names:
        path = os.path.join(root, name)
        if os.path.islink(path) or not os.path.isfile(path):
            continue
        digest = hashlib.sha256()
        with open(path, "rb") as h:
            for block in iter(lambda: h.read(1 << 20), b""):
                digest.update(block)
        files[os.path.relpath(path, prefix)] = digest.hexdigest()
tree = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()
json.dump({"version": version, "prefix": prefix, "tree_sha256": tree, "file_count": len(files)},
          open(out, "w", encoding="utf-8"), indent=2)
print(f"OpenCode {version}: {len(files)} files, tree sha256 {tree}")
PY
