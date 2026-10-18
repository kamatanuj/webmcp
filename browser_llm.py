#!/usr/bin/env python3
"""REAL-BROWSER WebMCP side-by-side: same 8 tasks, two live demo shops.
Agent brain = glm-5.3-flash (same as compare_llm.py). Difference: ALL site
traffic now executes INSIDE headless Chrome via CDP — real page load, real
JS context, real fetch()es from the page. LLM calls stay in Python.
Traffic metered two ways (both from the browser):
  - page load: PerformanceRouter transferSize (compressed wire bytes)
  - actions:   in-page fetch meter (decoded payload bytes)
Results -> results_browser.json (incremental)."""
import json, time, os, subprocess, urllib.request, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.expanduser("~"))
from cdp import CDP
from compare_llm import llm, clean, TASKS, CHECKS, LLM_KEY

DIR = os.path.dirname(os.path.abspath(__file__))
PLAIN = "https://demonomcp.converso.work"
MCP   = "https://demowithmcp.converso.work"
DEBUG = "http://127.0.0.1:9335"

INJECT = """(sid)=>{window.SID=sid;window.__m={n:0,b:0};
window.__f=async(u,b)=>{const r=await fetch(u,b===undefined?{headers:{"X-Session-Id":window.SID}}
:{method:"POST",headers:{"Content-Type":"application/json","X-Session-Id":window.SID,"Mcp-Session-Id":window.SID},body:JSON.stringify(b)});
const t=await r.text();window.__m.n++;window.__m.b+=t.length;try{return JSON.parse(t)}catch(e){return t}};
return "ok"}"""

def ev(cdp, expr, await_p=True):
    r = cdp.cmd("Runtime.evaluate", expression=expr, awaitPromise=await_p, returnByValue=True)
    if "exceptionDetails" in r["result"]:
        raise RuntimeError(str(r["result"]["exceptionDetails"].get("exception", {}).get("description", "?"))[:200])
    return r["result"]["result"].get("value")

def nav(cdp, url, sid):
    cdp.cmd("Page.navigate", url=url)
    for _ in range(60):
        time.sleep(0.25)
        try:
            if ev(cdp, "document.readyState", await_p=False) == "complete": break
        except Exception: pass
    ev(cdp, f"({INJECT})({json.dumps(sid)})", await_p=False)

def page_bytes(cdp):
    return ev(cdp, "performance.getEntriesByType('navigation')[0].transferSize + "
                   "performance.getEntriesByType('resource').reduce((a,e)=>a+e.transferSize,0)")

def meter_state(cdp):
    return ev(cdp, "({n:window.__m.n,b:window.__m.b})")

class LLMOnlyMeter:
    """llm() from compare_llm needs: tok_in, tok_out, llm_calls, http(url,body)->(res,dt).
    Site traffic must come from Chrome — hard-fail if it tries otherwise."""
    def __init__(self): self.tok_in = 0; self.tok_out = 0; self.llm_calls = 0
    def http(self, url, body=None):
        assert "chat/completions" in url, "browser run: non-LLM http from Python is forbidden"
        data = json.dumps(body).encode()
        req = urllib.request.Request(url, data=data, method="POST",
            headers={"Content-Type": "application/json", "Authorization": "Bearer " + LLM_KEY})
        res = json.loads(urllib.request.urlopen(req, timeout=90).read())
        return res, 0

def run_plain(cdp, task, m):
    nav(cdp, PLAIN, f"brw-plain")
    prods, html = ev(cdp, "__f('/api/products')"), ev(cdp, "__f('/')")
    brief = [{"id": p["id"], "name": p["name"], "price": p["price"], "rating": p["rating"],
              "category": p["category"], "spec": p["spec"]} for p in prods]
    msg = [{"role": "system", "content":
        "You are a shopping agent on an ecommerce site. You get the task and the product catalog JSON. "
        "Reply ONLY JSON: {\"pick\": [product ids in add order], \"checkout\": true|false, \"why\": \"<short reason>\"}."},
        {"role": "user", "content": f"TASK: {task}\n\nCATALOG: {json.dumps(brief)}"}]
    ans = clean(llm(msg, m))
    if isinstance(ans, list): ans = {"pick": ans}
    if not isinstance(ans, dict): ans = {}
    picks = ans.get("pick", [])
    picks = [picks] if isinstance(picks, int) else picks
    total, last = 0, None
    for pid in picks:
        ev(cdp, f"__f('/api/cart/add', {{'id': {pid}}})")
        p = next((x for x in brief if x["id"] == pid), None)
        total += p["price"]; last = p
    oid = None
    if ans.get("checkout"):
        oid = (ev(cdp, "__f('/api/checkout', {})") or {}).get("order_id")
    return {"added_name": last and last["name"], "added_price": last and last["price"],
            "added_spec": last and last["spec"], "cart_total": total, "order_id": oid,
            "why": ans.get("why", "")}

def run_mcp(cdp, task, m):
    nav(cdp, MCP, "brw-mcp")
    ev(cdp, "__f('/.well-known/mcp')")
    ev(cdp, "__f('/mcp', {'jsonrpc':'2.0','id':0,'method':'initialize','params':{}})")
    tools = ev(cdp, "__f('/mcp', {'jsonrpc':'2.0','id':1,'method':'tools/list','params':{}})")["result"]["tools"]
    sysmsg = ("You are a shopping agent using MCP tools: " +
              json.dumps([{"name": t["name"], "description": t["description"], "parameters": t.get("inputSchema")} for t in tools]) +
              ". Given a task, reply ONLY JSON {\"tool\": name, \"arguments\": {...}, \"done\": true|false}. "
              "Use search_products to find products, add_to_cart per product (you may need several), get_cart to verify, checkout when the task says to buy/checkout. "
              "Set done=true when the task is fully completed.")
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": f"TASK: {task}"}]
    added, oid, total, last = [], None, 0, None
    seen = {}
    for _ in range(10):
        ans = clean(llm(msgs, m))
        if not ans: break
        name, args = ans.get("tool"), ans.get("arguments", {})
        will_finish = bool(ans.get("done"))
        outjson = json.dumps(args)
        if name == "search_products":
            out = ev(cdp, f"__f('/mcp', {{'jsonrpc':'2.0','id':'s','method':'tools/call','params':{{'name':'search_products','arguments':{outjson}}}}})")
            sc = out.get("result", {}).get("structuredContent", [])
            seen.update({p["id"]: p for p in (sc if isinstance(sc, list) else [])})
        elif name == "add_to_cart":
            out = ev(cdp, f"__f('/mcp', {{'jsonrpc':'2.0','id':'a','method':'tools/call','params':{{'name':'add_to_cart','arguments':{outjson}}}}})")
            p = seen.get(args.get("id"))
            if p and not any(x["id"] == p["id"] for x in added):
                added.append(p); total += p["price"]; last = p
        elif name == "get_cart":
            out = ev(cdp, "__f('/mcp', {'jsonrpc':'2.0','id':'g','method':'tools/call','params':{'name':'get_cart','arguments':{}}})").get("result", {}).get("structuredContent")
        elif name == "checkout":
            out = ev(cdp, "__f('/mcp', {'jsonrpc':'2.0','id':'c','method':'tools/call','params':{'name':'checkout','arguments':{}}})").get("result", {}).get("structuredContent")
            if isinstance(out, dict) and out.get("order_id") and oid is None:
                oid = out["order_id"]
        else:
            out = {"error": f"unknown tool {name}"}
        msgs.append({"role": "assistant", "content": json.dumps(ans)})
        msgs.append({"role": "user", "content": "RESULT: " + json.dumps(out)})
        if will_finish: break
    if ("checkout" in task.lower() or "buy" in task.lower()) and oid is None:
        cart = ev(cdp, "__f('/mcp', {'jsonrpc':'2.0','id':'g','method':'tools/call','params':{'name':'get_cart','arguments':{}}})").get("result", {}).get("structuredContent") or {}
        items = cart.get("items", []) if isinstance(cart, dict) else []
        for it in items:
            pr = it.get("product") or {}
            p = seen.get(pr.get("id")) or pr
            if p and not any(x["id"] == p["id"] for x in added):
                added.append(p); total += p["price"]; last = p
        if items:
            out = ev(cdp, "__f('/mcp', {'jsonrpc':'2.0','id':'c','method':'tools/call','params':{'name':'checkout','arguments':{}}})").get("result", {}).get("structuredContent")
            oid = (out or {}).get("order_id")
    return {"added_name": last and last["name"], "added_price": last and last["price"],
            "added_spec": last and last["spec"], "cart_total": total, "order_id": oid}

def main():
    tabs = json.loads(urllib.request.urlopen(DEBUG + "/json").read())
    page = next(t for t in tabs if t["type"] == "page")
    cdp = CDP(page["webSocketDebuggerUrl"])
    rows = []
    path = DIR + "/results_browser.json"
    for i, task in enumerate(TASKS, 1):
        for site, runner in [("plain", run_plain), ("mcp", run_mcp)]:
            m = LLMOnlyMeter()
            t0 = time.time()
            try:
                res = runner(cdp, task, m)
                ok = bool(CHECKS[i-1](res))
                err = ""
            except Exception as e:
                res, ok, err = {}, False, repr(e)[:120]
            ms = meter_state(cdp)
            pb = page_bytes(cdp)
            rows.append({"task": i, "site": site, "requests": ms["n"], "bytes": ms["b"],
                         "page_bytes": pb, "secs": round(time.time()-t0, 1), "success": ok,
                         "pick": res.get("added_name"), "order_id": res.get("order_id"),
                         "tok_in": m.tok_in, "tok_out": m.tok_out, "llm_calls": m.llm_calls, "err": err})
            json.dump(rows, open(path, "w"), indent=1)
            print(f"T{i} {site}: {'OK' if ok else 'FAIL'} pick={res.get('added_name')} oid={res.get('order_id')} req={ms['n']} bytes={ms['b']} page={pb} tok={m.tok_in}/{m.tok_out} {err}", flush=True)
    print("\n== BROWSER SUMMARY ==")
    for site in ["plain", "mcp"]:
        rs = [r for r in rows if r["site"] == site]
        print(f"{site:5} | reqs {sum(r['requests'] for r in rs)} | action-bytes {sum(r['bytes'] for r in rs):,} | "
              f"wire-page-bytes {sum(r['page_bytes'] for r in rs):,} | success {sum(r['success'] for r in rs)}/{len(rs)} | "
              f"tokens {sum(r['tok_in'] for r in rs):,}/{sum(r['tok_out'] for r in rs):,}")
    cdp.close()

if __name__ == "__main__":
    main()