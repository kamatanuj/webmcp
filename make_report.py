#!/usr/bin/env python3
"""Layman report: charts + PDF for the WebMCP comparison."""
import json, matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import os

D = os.path.dirname(os.path.abspath(__file__))
rows = json.load(open(f"{D}/results.json"))
plain = [r for r in rows if r["site"] == "plain"]
mcp   = [r for r in rows if r["site"] == "mcp"]
labels = [f"Task {r['task']}" for r in plain]

NAVY, TEAL, GREY = "#16213e", "#4fc3a1", "#9aa2b1"
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11})

# Chart 1: bytes the agent must read per task
b1 = [r["bytes"]/1024 for r in plain]; b2 = [r["bytes"]/1024 for r in mcp]
fig, ax = plt.subplots(figsize=(7.5, 3.4))
w = 0.36; x = range(len(labels))
ax.bar([i-w/2 for i in x], b1 := b1, w, label="Normal site", color=GREY)
ax.bar([i+w/2 for i in x], b2, w, label="WebMCP site", color=TEAL)
for i, (a, b) in enumerate(zip(b1, b2)):
    ax.text(i-w/2, a+.15, f"{a:.0f} KB", ha="center", fontsize=10, color="#555")
    ax.text(i+w/2, b+.15, f"{b:.1f} KB", ha="center", fontsize=10, color=NAVY, fontweight="bold")
ax.set_xticks(list(x)); ax.set_xticklabels(labels)
ax.set_ylabel("Data the AI reads (KB)")
ax.set_title("Data the AI assistant must read to finish each task")
ax.legend(); ax.spines[["top","right"]].set_visible(False)
plt.tight_layout(); plt.savefig(f"{D}/chart_bytes.png", dpi=150); plt.close()

# Chart 2: token-equivalent burden (bytes/4 chars per token)
t1 = [r["bytes"]/4 for r in plain]; t2 = [r["bytes"]/4 for r in mcp]
fig, ax = plt.subplots(figsize=(7.5, 3.4))
ax.bar([i-w/2 for i in x], t1, w, label="Normal site", color=GREY)
ax.bar([i+w/2 for i in x], t2, w, label="WebMCP site", color=TEAL)
for i, (a, b) in enumerate(zip(t1, t2)):
    ax.text(i-w/2, a+60, f"{a:,.0f}", ha="center", fontsize=10, color="#555")
    ax.text(i+w/2, b+60, f"{b:,.0f}", ha="center", fontsize=10, color=NAVY, fontweight="bold")
ax.set_xticks(list(x)); ax.set_xticklabels(labels)
ax.set_ylabel("Words the AI must read (approx.)")
ax.set_title("Reading workload per task — less reading = faster answers, lower AI cost")
ax.legend(); ax.spines[["top","right"]].set_visible(False)
plt.tight_layout(); plt.savefig(f"{D}/chart_tokens.png", dpi=150); plt.close()

# Chart 3: success + same picks
fig, ax = plt.subplots(figsize=(7.5, 2.8))
tasks = [f"Task {r['task']}" for r in plain]
same = ["✓ same" for r1, r2 in zip(plain, mcp) if r1["pick"] == r2["pick"]]
ax.axis("off")
tbl = ax.table(cellText=[[f"✓ {r['pick']}" for r in plain], [f"✓ {r['pick']}" for r in mcp]],
               rowLabels=["Normal site", "WebMCP site"], colLabels=tasks,
               cellLoc="center", loc="center")
tbl = ax.table(cellText=[[("✓ " + r["pick"]) if r["success"] else "✗" for r in plain],
                          [("✓ " + r["pick"]) if r["success"] else "✗" for r in mcp]],
               rowLabels=["Normal site", "WebMCP site"], colLabels=tasks,
               cellLoc="center", loc="center")
tbl.auto_set_font_size(False); tbl.set_fontsize(10); tbl.scale(1, 1.8)
for (r, c), cell in tbl.get_celld().items():
    if r == 0 or c == -1: cell.set_facecolor(NAVY); cell.set_text_props(color="white", fontweight="bold")
    elif r > 0: cell.set_facecolor("#f2f8f6" if r == 2 else "#f8f9fa")
plt.savefig(f"{D}/chart_picks.png", dpi=150, bbox_inches="tight"); plt.close()
print("charts done")
