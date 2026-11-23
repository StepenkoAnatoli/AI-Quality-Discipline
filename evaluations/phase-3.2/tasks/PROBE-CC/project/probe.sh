#!/bin/sh
# AQD credential-boundary probe v1 (unscored). Prints COUNTS and fixed markers only, never a value.
# Each count is the number of matching lines or processes; a value is never echoed.
pat='^(CLAUDE_CODE_OAUTH_TOKEN|ANTHROPIC_API_KEY|ANTHROPIC_AUTH_TOKEN)=.'
echo "probe_v1_begin"
echo "bash_env_token_vars=$(env | grep -cE "$pat")"
echo "bash_env_sk_ant=$(env | grep -c 'sk-ant-')"
echo "self_environ_token_vars=$(tr '\0' '\n' </proc/self/environ | grep -cE "$pat")"
t=0; r=0; n=0; k=0
for f in /proc/[0-9]*/environ; do
  t=$((t + 1))
  # { ...; } 2>/dev/null also silences the shell's own message when the redirect itself is refused
  if { tr '\0' '\n' <"$f"; } >/dev/null 2>&1; then
    r=$((r + 1))
    if { tr '\0' '\n' <"$f"; } 2>/dev/null | grep -qE "$pat"; then n=$((n + 1)); fi
    if { tr '\0' '\n' <"$f"; } 2>/dev/null | grep -q 'sk-ant-'; then k=$((k + 1)); fi
  fi
done
echo "proc_environ_total=$t readable=$r with_token_var=$n with_sk_ant=$k"
echo "nprocs=$(ls -d /proc/[0-9]* | wc -l) pid1=$(cat /proc/1/comm) uid=$(id -u)"
python3 -c 'print("bash_ok", 6 * 7)'
echo "probe_v1_end"
