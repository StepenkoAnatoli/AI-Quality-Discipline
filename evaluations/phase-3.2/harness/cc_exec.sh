#!/bin/sh
# Usage: cc_exec.sh DIR COMMAND [ARG...]   (started by cc_adapter.py; never by hand)
#
# Reads the subscription token from the FIRST LINE of stdin, exports it as CLAUDE_CODE_OAUTH_TOKEN, changes to DIR
# and executes COMMAND, which receives the rest of stdin (the task prompt). The directory change happens here, in
# the agent user's own process, because the operator cannot traverse the agent's 0700 tree (as lib.sh as_agent).
# The token is never an argument (argv is readable by every local user through ps), never written to disk, and
# never printed. `read` takes exactly one line from the pipe, so the prompt reaches claude byte for byte.
set -eu
dir=${1:?usage: cc_exec.sh DIR COMMAND [ARG...]}
shift
IFS= read -r token || { echo "cc_exec: no token line on stdin" >&2; exit 97; }
[ -n "$token" ] || { echo "cc_exec: empty token line" >&2; exit 97; }
cd "$dir" 2>/dev/null || { echo "cc_exec: cannot enter the working directory" >&2; exit 96; }
CLAUDE_CODE_OAUTH_TOKEN=$token
export CLAUDE_CODE_OAUTH_TOKEN
unset token OLDPWD
exec "$@"
