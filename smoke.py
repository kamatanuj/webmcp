#!/usr/bin/env python3
"""CI smoke test: boot both modes of the demo store, exercise every public
surface the README promises, fail fast on any non-200 or contract drift.

Covers issue #3 (smoke both modes every push) and issue #4 (tools/list
baseline: any silent change to tool names/schemas/descriptions trips CI until
mcp_baseline.json is re-baselined).

Stdlib only. Exits 0 on green, 1 with a message on the first failure.
"""
import hashlib, json, os, signal, subprocess, sys, time, urllib.error, urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
BASE = int(os.environ.get("SMOKE_PORT", "18761"))  # +1 for the MCP instance
BASELINE = json.load(open(f"{DIR}/mcp_baseline.json"))

# (port, env) pairs — plain mode first, then MCP mode
instances = [
    (BASE, {"PORT": str(BASE)}),                     # plain
    (BASE + 1, {"PORT": str(BASE + 1), "MCP": "1"}),  # mcp
]

def get(port, path):
    try:
        r = urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=10)
        body = r.read()
        try:
            return r.status, json.loads(body or b"null")
        except json.JSONDecodeError:
            return r.status, body  # non-JSON body (HTML pages)
    except urllib.error.HTTPError as e:
        return e.code, None

def post(port, path, obj):
    r = urllib.request.urlopen(urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(obj).encode(),
        headers={"Content-Type": "application/json"}), timeout=10)
    return r.status, json.loads(r.read())

fails = []
def check(desc, ok):
    print(("ok   " if ok else "FAIL ") + desc)
    if not ok:
        fails.append(desc)

procs = []
try:
    for port, extra in instances:
        env = dict(os.environ, **extra)
        procs.append(subprocess.Popen(
            [sys.executable, f"{DIR}/server.py"], cwd=DIR, env=env,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True))

    # wait for both /health to answer (max ~5s)
    for port, _ in instances:
        for _ in range(50):
            try:
                if get(port, "/health")[0] == 200:
                    break
            except OSError:
                pass
            time.sleep(0.1)
        else:
            fails.append(f"server on :{port} never answered /health")

    plain, mcp = instances[0][0], instances[1][0]

    # --- plain mode ---
    st, body = get(plain, "/health")
    check("plain /health 200 mode=plain", st == 200 and body == {"ok": True, "mode": "plain"})
    st, items = get(plain, "/api/products")
    check("plain /api/products 200 + 150 items", st == 200 and isinstance(items, list) and len(items) == 150)
    st, _ = get(plain, "/")
    check("plain / (index.html) 200", st == 200)
    st, _ = get(plain, "/mcp")
    check("plain /mcp is NOT the MCP layer (404)", st == 404)

    # --- mcp mode ---
    st, body = get(mcp, "/health")
    check("mcp /health 200 mode=mcp", st == 200 and body == {"ok": True, "mode": "mcp"})
    st, disc = get(mcp, "/.well-known/mcp")
    check("mcp /.well-known/mcp 200 + 5 tools", st == 200 and isinstance(disc, dict) and len(disc.get("tools", [])) == 5)
    st, init = post(mcp, "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize",
                                  "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}})
    check("mcp /mcp initialize 200 protocolVersion 2025-06-18",
          st == 200 and init.get("result", {}).get("protocolVersion") == "2025-06-18")

    st, tl = post(mcp, "/mcp", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    tools = tl.get("result", {}).get("tools", []) if st == 200 else []
    check("tools/list 200 + 5 tools", st == 200 and len(tools) == BASELINE["tool_count"])
    compact = json.dumps(tools, sort_keys=True, separators=(",", ":"))
    got = hashlib.sha256(compact.encode()).hexdigest()
    check(f"tools baseline hash {BASELINE['tools_sha256'][:12]}…", got == BASELINE["tools_sha256"])
    check("tool names match baseline", [t["name"] for t in tools] == BASELINE["tool_names"])

    # --- one tool call so the contract is exercised, not just listed ---
    st, call = post(mcp, "/mcp", {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                                  "params": {"name": "search_products", "arguments": {"category": "mice"}}})
    out = call.get("result", {}).get("structuredContent") if st == 200 else None
    check("tools/call search_products returns 10 mice", isinstance(out, list) and len(out) == 10)
finally:
    for p in procs:
        try:
            os.killpg(p.pid, signal.SIGTERM)
        except OSError:
            p.kill()

if fails:
    print(f"\n{len(fails)} check(s) failed:\n" + "\n".join(fails))
    sys.exit(1)
print("\nsmoke: all green")