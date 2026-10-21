#!/usr/bin/env python3
"""Ecommerce demo server. MODE=mcp adds WebMCP layer (/mcp + /.well-known/mcp.json).
Same UI, same data, same JS for both sites — only the MCP layer differs.
"""
import json, os, threading, uuid
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

DIR = os.path.dirname(os.path.abspath(__file__))
CATALOG = json.load(open(f"{DIR}/{os.environ.get('CATALOG_FILE', 'catalog.json')}"))
MODE = "mcp" if os.environ.get("MCP") == "1" else "plain"
PORT = int(os.environ.get("PORT", "9501"))

# KPI counter: append-only JSONL (two services share the file; O_APPEND appends are atomic)
COUNTL = threading.Lock()
def bump(k):
    with COUNTL:
        with open(f"{DIR}/counters.jsonl", "a") as f:
            f.write(json.dumps({"t": round(__import__("time").time()), "k": k, "m": MODE}) + "\n")

PRODUCTS = {}   # id -> product (flattened)
for cat, items in CATALOG.items():
    for it in items:
        it["category"] = cat
        PRODUCTS[str(it["id"])] = it

CARTS = {}      # session_id -> {product_id: qty}
ORDERS = []     # list of order dicts
LOCK = threading.Lock()

def cart_items(sid):
    return [{"product": PRODUCTS[pid], "qty": q} for pid, q in CARTS.get(sid, {}).items() if pid in PRODUCTS]

def cart_total(sid):
    return sum(p["product"]["price"] * p["qty"] for p in cart_items(sid))

# ---------- WebMCP layer ----------
MCP_TOOLS = [
    {"name": "search_products", "description": "Search product catalog. Filter by category (mice|laptops|phones), max_price (INR), min_rating, brand substring.",
     "inputSchema": {"type": "object", "properties": {
        "category": {"type": "string", "enum": ["mice", "laptops", "phones"]},
        "max_price": {"type": "number"}, "min_rating": {"type": "number"},
        "brand": {"type": "string"}, "query": {"type": "string"}},
        "required": []}},
    {"name": "get_product_details", "description": "Full details of one product by id.",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}}, "required": ["id"]}},
    {"name": "add_to_cart", "description": "Add product to cart (qty default 1).",
     "inputSchema": {"type": "object", "properties": {"id": {"type": "integer"}, "qty": {"type": "integer"}}, "required": ["id"]}},
    {"name": "get_cart", "description": "Current cart contents and total.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
    {"name": "checkout", "description": "Place order for current cart. Returns order id.",
     "inputSchema": {"type": "object", "properties": {}, "required": []}},
]

def mcp_search(args):
    res = list(PRODUCTS.values())
    if c := args.get("category"):
        res = [p for p in res if p["category"] == c]
    if mp := args.get("max_price"):
        res = [p for p in res if p["price"] <= mp]
    if mr := args.get("min_rating"):
        res = [p for p in res if p["rating"] >= mr]
    if b := args.get("brand"):
        res = [p for p in res if b.lower() in p["brand"].lower()]
    if q := args.get("query"):
        ql = q.lower()
        res = [p for p in res if ql in p["name"].lower() or ql in p["spec"].lower()]
    res.sort(key=lambda p: -p["rating"])
    return [{"id": p["id"], "name": p["name"], "price": p["price"], "rating": p["rating"], "brand": p["brand"], "spec": p["spec"]} for p in res[:10]]

def handle_tool(name, args, sid):
    if name == "search_products":
        return mcp_search(args)
    if name == "get_product_details":
        p = PRODUCTS.get(str(args.get("id")))
        return p or {"error": "not found"}
    if name == "add_to_cart":
        pid = str(args["id"])
        if pid not in PRODUCTS:
            return {"error": "product not found"}
        with LOCK:
            CARTS.setdefault(sid, {})
            CARTS[sid][pid] = CARTS[sid].get(pid, 0) + int(args.get("qty", 1))
        return {"ok": True, "cart_count": sum(CARTS[sid].values()), "cart_total": cart_total(sid)}
    if name == "get_cart":
        return {"items": cart_items(sid), "total": cart_total(sid)}
    if name == "checkout":
        items = cart_items(sid)
        if not items:
            return {"error": "cart empty"}
        order = {"order_id": len(ORDERS) + 1001, "items": [{"id": i["product"]["id"], "name": i["product"]["name"], "qty": i["qty"], "price": i["product"]["price"]} for i in items], "total": cart_total(sid)}
        ORDERS.append(order)
        CARTS[sid] = {}
        return {"ok": True, **order}
    return {"error": f"unknown tool {name}"}

# ---------- HTTP handler ----------
class H(BaseHTTPRequestHandler):
    def log_message(self, *a): pass

    def _json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Id, Mcp-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Session-Id, Mcp-Session-Id")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.end_headers()

    def _sid(self):
        return self.headers.get("X-Session-Id") or self.headers.get("Mcp-Session-Id") or "anon"

    def do_GET(self):
        path = urlparse(self.path).path
        k = ("api" if path.startswith("/api") else
             "store" if path in ("/", "/index.html") else
             "portal" if path == "/launch.html" else
             "pdf" if path.endswith(".pdf") else
             "reports" if path.endswith(".html") else None)
        if k:
            bump(k)
        if path == "/api/products":
            q = parse_qs(urlparse(self.path).query)
            cat = (q.get("category") or [None])[0]
            items = [p for p in PRODUCTS.values() if not cat or p["category"] == cat]
            self._json(200, items)
        elif path == "/api/cart":
            sid = self._sid()
            self._json(200, {"items": cart_items(sid), "total": cart_total(sid)})
        elif path == "/health":
            self._json(200, {"ok": True, "mode": MODE})
        elif path == "/plan.pdf":
            body = open(f"{DIR}/ShopPilot_Production_Plan.pdf", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/whitepaper.pdf":
            body = open(f"{DIR}/ShopPilot_Whitepaper.pdf", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/report_tech.pdf":
            body = open(f"{DIR}/WebMCP_Technical_Report.pdf", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/report.pdf":
            body = open(f"{DIR}/WebMCP_Comparison_Report.pdf", "rb").read()
            self.send_response(200)
            self.send_header("Content-Type", "application/pdf")
            self.send_header("Content-Disposition", "inline; filename=\"WebMCP_Comparison_Report.pdf\"")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif path == "/.well-known/mcp" and MODE == "mcp":
            self._json(200, {"mcp": "1.0", "transport": "http", "endpoint": "/mcp", "server": {"name": "WebMCP Demo Store", "version": "1.0.0"}, "tools": MCP_TOOLS})
        elif path != "/" and "/" not in path[1:] and not path[1:].startswith("."):
            fn = os.path.join(DIR, path[1:])
            if os.path.isfile(fn):
                ctype = {"html": "text/html", "pdf": "application/pdf", "md": "text/markdown",
                         "png": "image/png", "jpg": "image/jpeg", "svg": "image/svg+xml"}.get(path[1:].rsplit(".", 1)[-1], "application/octet-stream")
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.end_headers()
                with open(fn, "rb") as f:
                    self.wfile.write(f.read())
            else:
                # not a real static file (e.g. GET /mcp on plain mode) → clean 404,
                # never a silent connection close (that reads as 502 through nginx)
                self._json(404, {"error": "not found"})
        else:
            with open(f"{DIR}/index.html", "rb") as f:
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f.read().replace(b"__MODE__", MODE.encode()))

    def do_POST(self):
        path = urlparse(self.path).path
        n = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json(400, {"error": "bad json"})
        sid = self._sid()
        if path == "/api/cart/add":
            pid = str(body.get("id"))
            if pid not in PRODUCTS:
                return self._json(404, {"error": "not found"})
            with LOCK:
                CARTS.setdefault(sid, {})
                CARTS[sid][pid] = CARTS[sid].get(pid, 0) + int(body.get("qty", 1))
            self._json(200, {"ok": True, "total": cart_total(sid)})
        elif path == "/api/checkout":
            items = cart_items(sid)
            if not items:
                return self._json(400, {"error": "cart empty"})
            order = {"order_id": len(ORDERS) + 1001, "items": [{"id": i["product"]["id"], "name": i["product"]["name"], "qty": i["qty"], "price": i["product"]["price"]} for i in items], "total": cart_total(sid)}
            ORDERS.append(order)
            CARTS[sid] = {}
            self._json(200, {"ok": True, **order})
        elif path == "/mcp" and MODE == "mcp":
            self._mcp(body, sid)
        else:
            self._json(404, {"error": "not found"})

    def _mcp(self, body, sid):
        method = body.get("method")
        mid = body.get("id")
        if method == "initialize":
            return self._json(200, {"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": "2025-06-18", "capabilities": {"tools": {}},
                "serverInfo": {"name": "WebMCP Demo Store", "version": "1.0.0"}}})
        if method == "tools/list":
            return self._json(200, {"jsonrpc": "2.0", "id": mid, "result": {"tools": MCP_TOOLS}})
        if method == "tools/call":
            t = body.get("params", {})
            try:
                out = handle_tool(t.get("name"), t.get("arguments") or {}, sid)
                return self._json(200, {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": json.dumps(out)}], "structuredContent": out}})
            except Exception as e:
                return self._json(200, {"jsonrpc": "2.0", "id": mid, "result": {
                    "content": [{"type": "text", "text": f"error: {e}"}], "isError": True}})
        return self._json(200, {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found"}})

if __name__ == "__main__":
    print(f"serving mode={MODE} port={PORT}")
    ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
