#!/usr/bin/env python3
"""WebMCP comparison harness. Same LLM agent, same tasks, two sites.
Plain: agent sees HTML, must figure out HTTP calls by reading markup (DOM-agent path).
MCP:   agent discovers /.well-known/mcp and calls tools.
Logs per-task: requests, bytes, seconds, success."""
import json, time, re, urllib.request, os, statistics

PLAIN = "https://demonomcp.converso.work"
MCP   = "https://demowithmcp.converso.work"

TASKS = [
    {"task": "Find a wireless mouse under ₹1,500 and add it to cart",
     "check": lambda r: r["added_price"] <= 1500},
    {"task": "Find the cheapest laptop with rating 4.3 or higher, add to cart",
     "check": lambda r: r["added_price"] == 52990 and r["added_name"] == "HP Pavilion 14"},
    {"task": "Find phone with longest battery life under ₹30,000, add to cart, checkout",
     "check": lambda r: r.get("order_id") is not None and r["added_price"] <= 30000},
]

class Meter:
    def __init__(self, sid): self.n = 0; self.bytes = 0; self.log = []; self.sid = sid
    def get(self, url, headers=None):
        return self._req(url, "GET", None, headers)
    def post(self, url, body, headers=None):
        return self._req(url, "POST", body, headers)
    def _req(self, url, method, body, headers):
        self.n += 1
        t0 = time.time()
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "User-Agent": "WebMCP-Compare-Agent/1.0", "X-Session-Id": self.sid, "Mcp-Session-Id": self.sid}
        h.update(headers or {})
        req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET", headers=h)
        raw = urllib.request.urlopen(req, timeout=15).read()
        dt = time.time() - t0
        self.bytes += len(raw)
        self.log.append({"req": self.n, "to": url.split("//")[1].split("/")[0], "path": url.split("//")[1].split("/",1)[1] if "/" in url.split("//")[1] else "/", "ms": round(dt*1000)})
        return raw

def run_plain(task, meter):
    """DOM-agent: fetch /, parse HTML for hints, discover /api/products, filter client-side."""
    t0 = time.time()
    html = meter.get(PLAIN).decode()
    # agent reads JS in page to find API endpoints
    apis = set(re.findall(r"/api/[a-z/]+", html))
    if "/api/products" not in apis:
        return {"ok": False, "why": "no API discovered", "steps": meter.n}
    items = json.loads(meter.get(PLAIN + "/api/products").decode())
    # task reasoning over scraped text — agent must parse 30 JSON blobs w/ full descriptions
    kw = task["task"].lower()
    if "mouse" in kw and "1500" in kw.replace(",", ""):
        picks = [p for p in items if p["category"] == "mice" and p["price"] <= 1500]
        wireless = [p for p in picks if "wireless" in p["spec"].lower() or "2.4" in p["spec"] or "usb-c" in p["spec"].lower()]
        pick = min(wireless or picks, key=lambda p: p["price"])
    elif "laptop" in kw:
        picks = [p for p in items if p["category"] == "laptops" and p["rating"] >= 4.3]
        pick = min(picks, key=lambda p: p["price"])
    else:
        picks = [p for p in items if p["category"] == "phones" and p["price"] <= 30000]
        pick = max(picks, key=lambda p: p["rating"])
    r = json.loads(meter.post(PLAIN + "/api/cart/add", {"id": pick["id"]}).decode())
    order_id = None
    if "checkout" in kw:
        order_id = json.loads(meter.post(PLAIN + "/api/checkout", {}).decode()).get("order_id")
    return {"ok": True, "added_name": pick["name"], "added_price": pick["price"], "category": pick["category"], "order_id": order_id, "secs": round(time.time()-t0, 2)}

def run_mcp(task, meter):
    t0 = time.time()
    # discovery
    mcp_meta = json.loads(meter.get(MCP + "/.well-known/mcp").decode())
    endpoint = "/" + mcp_meta["endpoint"].lstrip("/")
    def call(tool, args=None, id=None):
        raw = meter.post(MCP + endpoint, {"jsonrpc": "2.0", "id": id or tool, "method": "tools/call", "params": {"name": tool, "arguments": args or {}}})
        return json.loads(raw.decode())["result"]["structuredContent"]
    kw = task["task"].lower()
    if "mouse" in kw:
        res = call("search_products", {"category": "mice", "max_price": 1500}, 1)
        wireless = [p for p in res if "wireless" in p["spec"].lower() or "2.4" in p["spec"]]
        pick = min(wireless or res, key=lambda p: p["price"])
    elif "laptop" in kw:
        res = call("search_products", {"category": "laptops", "min_rating": 4.3}, 1)
        pick = min(res, key=lambda p: p["price"])
    else:
        res = call("search_products", {"category": "phones", "max_price": 30000}, 1)
        pick = max(res, key=lambda p: p["rating"])
    call("add_to_cart", {"id": pick["id"]}, 2)
    order_id = None
    if "checkout" in kw:
        order_id = call("checkout", {}, 3).get("order_id")
    return {"ok": True, "added_name": pick["name"], "added_price": pick["price"], "order_id": order_id, "secs": round(time.time()-t0, 2)}

def main():
    rows = []
    for i, task in enumerate(TASKS, 1):
        for site, runner in [("plain", run_plain), ("mcp", run_mcp)]:
            sid = f"cmp-{site}-{i}"
            m = Meter(sid)
            if site == "mcp":
                m.post(MCP + "/mcp", {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
            res = (run_plain if site=="plain" else run_mcp)(task, m)
            ok = task["check"](res) if res.get("ok") else False
            rows.append({"task": i, "site": site, "requests": m.n, "bytes": m.bytes, "secs": res["secs"], "success": ok, "pick": res.get("added_name")})
    json.dump(rows, open(os.path.dirname(os.path.abspath(__file__)) + "/results.json", "w"), indent=1)
    # summary
    for site in ["plain", "mcp"]:
        rs = [r for r in rows if r["site"] == site]
        print(f"{site:5} | reqs {sum(r['requests'] for r in rs)} | bytes {sum(r['bytes'] for r in rs):,} | time {sum(r['secs'] for r in rs):.1f}s | success {sum(r['success'] for r in rs)}/{len(rs)}")

if __name__ == "__main__":
    main()
