#!/usr/bin/env python3
"""Weekly WebMCP recap -> stdout (cron delivers by email)."""
import json, subprocess, time, os
from collections import Counter

D = os.path.dirname(os.path.abspath(__file__))
week_ago = round(time.time()) - 7 * 86400
tot, wk = Counter(), Counter()
for line in open(f"{D}/counters.jsonl"):
    try:
        e = json.loads(line)
        tot[e["k"]] += 1
        if e["t"] >= week_ago:
            wk[e["k"]] += 1
    except Exception:
        pass

lines = ["WebMCP weekly recap (last 7 days)", "=" * 34]
if wk:
    for k in ("store", "portal", "reports", "pdf", "api"):
        lines.append(f"  {k:8}: {wk.get(k, 0):>6} this week / {tot.get(k, 0)} all-time")
else:
    lines.append("  no new hits this week (baseline: store=%d portal=%d)" % (tot.get("store", 0), tot.get("portal", 0)))

def head(url):
    r = subprocess.run(["curl", "-s", "-o", "/dev/null", "-w", "%{http_code} %{content_type}", "-m", "12", url],
                       capture_output=True, text=True)
    return r.stdout or "unreachable"

lines.append("")
lines.append("Live checks (https)")
for name, url in [("plain store", "https://demonomcp.converso.work/"),
                  ("mcp store", "https://demowithmcp.converso.work/"),
                  ("portal", "https://demowithmcp.converso.work/launch.html"),
                  ("deck pdf", "https://demowithmcp.converso.work/WebMCP_Launch_Deck.pdf"),
                  ("benchmark report", "https://demowithmcp.converso.work/report.html"),
                  ("whitepaper", "https://demowithmcp.converso.work/whitepaper.html")]:
    assert name and url  # guard: every row must have both
    lines.append(f"  {name:17}: {head(url)}")

lines.append("")
lines.append("Portal: https://demowithmcp.converso.work/launch.html")
print("\n".join(lines))