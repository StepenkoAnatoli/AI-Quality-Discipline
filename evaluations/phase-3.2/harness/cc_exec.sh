#!/bin/sh
# Usage: cc_exec.sh COMMAND [ARG...]   (started by cc_adapter.py run; never by hand)
#
# Reads the subscription token from the FIRST LINE of stdin, exports it as CLAUDE_CODE_OAUTH_TOKEN and executes
# COMMAND, which receives the rest of stdin (the task prompt). The token is never an argument (argv is readable
# by every local user through ps), never written to disk, and never printed. `read` takes exactly one line from
# the pipe, so the prompt reaches claude byte for byte.
set -eu
IFS= read -r token || { echo "cc_exec: no token line on stdin" >&2; exit 97; }
[ -n "$token" ] || { echo "cc_exec: empty token line" >&2; exit 97; }
CLAUDE_CODE_OAUTH_TOKEN=$token
export CLAUDE_CODE_OAUTH_TOKEN
unset token
exec "$@"
