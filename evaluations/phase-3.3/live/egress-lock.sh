#!/usr/bin/env bash
# Per-UID egress lock for the agent users (as phase3-ab-run.yml): loopback and Anthropic's published API ranges
# (tcp/443) only. The operator (this user) keeps its network. Then verified from inside each agent UID.
#
# Usage: egress-lock.sh rehearsal|live
#   live:      also requires api.anthropic.com to resolve inside the allowed ranges and accept a TCP connection
#              (no TLS, no HTTP, no request).
#   rehearsal: makes no connection to any Anthropic host; checks only that other hosts are unreachable.
set -euo pipefail
MODE="${1:-}"
[[ "$MODE" == live || "$MODE" == rehearsal ]] || { echo "usage: egress-lock.sh rehearsal|live" >&2; exit 2; }
AGENTS="aqd-a aqd-b aqd-eval"
V4="160.79.104.0/23 153.61.224.0/22"   # Anthropic's published API addresses (as phase3-ab-run.yml, 2026-11-21)
V6="2607:6bc0::/48"
for u in $AGENTS; do id "$u" >/dev/null 2>&1 || { echo "STOP: agent user $u missing" >&2; exit 1; }; done
for t in iptables ip6tables; do
    sudo "$t" -N AQD_AGENT_EGRESS 2>/dev/null || sudo "$t" -F AQD_AGENT_EGRESS
    sudo "$t" -A AQD_AGENT_EGRESS -o lo -j ACCEPT
done
for net in $V4; do sudo iptables -A AQD_AGENT_EGRESS -d "$net" -p tcp --dport 443 -j ACCEPT; done
sudo ip6tables -A AQD_AGENT_EGRESS -d "$V6" -p tcp --dport 443 -j ACCEPT
for t in iptables ip6tables; do
    sudo "$t" -A AQD_AGENT_EGRESS -j REJECT
    for u in $AGENTS; do
        sudo "$t" -C OUTPUT -m owner --uid-owner "$u" -j AQD_AGENT_EGRESS 2>/dev/null \
            || sudo "$t" -I OUTPUT 1 -m owner --uid-owner "$u" -j AQD_AGENT_EGRESS
    done
done
for u in aqd-a aqd-b; do
    (cd / && sudo -u "$u" env -i PATH=/usr/bin:/bin AQD_MODE="$MODE" /usr/bin/python3 -I -) <<'PY' \
        || { echo "STOP: the agent network is not limited to the Anthropic API" >&2; exit 1; }
import ipaddress, os, socket, sys
allowed = [ipaddress.ip_network(n) for n in ("160.79.104.0/23", "153.61.224.0/22", "2607:6bc0::/48")]
def connects(host):
    try:
        socket.create_connection((host, 443), timeout=8).close()
        return True
    except OSError:
        return False
bad = [f"{h}:443 reachable" for h in ("example.com", "github.com", "registry.npmjs.org", "models.dev") if connects(h)]
if os.environ.get("AQD_MODE") == "live":
    try:
        addrs = {ai[4][0] for ai in socket.getaddrinfo("api.anthropic.com", 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        addrs = set()
    if not addrs or any(not any(ipaddress.ip_address(a) in n for n in allowed) for a in addrs):
        bad.append("api.anthropic.com resolves outside the allowed ranges")
    if not connects("api.anthropic.com"):
        bad.append("api.anthropic.com:443 unreachable")
print("agent egress: " + ("; ".join(bad) or "limited as required"))
sys.exit(1 if bad else 0)
PY
done
echo "egress lock: loopback + Anthropic API (tcp/443) only, for $AGENTS"
