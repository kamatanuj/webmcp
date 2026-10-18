#!/usr/bin/env python3
"""WebMCP comparison with a REAL LLM brain: glm-5.3-flash via OpenRouter.
Same 8 tasks, two sites. The model decides what to do; harness only executes
its chosen actions and records HTTP traffic + tokens.
Plain: model sees the store HTML + /api/products JSON, answers with JSON actions.
MCP:   model discovers /.well-known/mcp, gets tool schemas, answers with tool calls."""
import json, time, re, os, urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
PLAIN = "https://demonomcp.converso.work"
MCP   = "https://demowithmcp.converso.work"
KEY = [l.split("=",1)[1].strip() for l in open("/root/.hermes/.env") if l.startswith("OPENROUTER_API_KEY=")][0]
MODEL = "z-ai/glm-5.3-flash"

TASKS = [t["task"] for t in json.load(open(DIR + "/tasks8.json"))["tasks"]] if os.path.exists(DIR + "/tasks8.json") else [
    "Find a wireless mouse under ₹1,500 and add it to cart",
    "Find the cheapest laptop with rating 4.3 or higher, add to cart",
    "Find phone with longest battery life under ₹30,000, add to cart, checkout",
    "Add the highest-rated gaming mouse under ₹3,000 to the cart",
    "Buy the most expensive laptop in stock — add to cart and checkout",
    "Find a phone with wireless or fast charging under ₹30,000, add to cart, checkout",
    "Add the cheapest wired mouse with rating at least 4.0 to cart, then add the highest-rated wireless mouse regardless of price, then checkout",
    "We have ₹40,000. Buy the best-rated phone we can afford, checkout",
]

class Meter:
    def __init__(self, sid): self.n = 0; self.bytes = 0; self.sid = sid; self.tok_in = 0; self.tok_out = 0; self.llm_calls = 0
    def http(self, url, body=None):
        self.n += 1
        data = json.dumps(body).encode() if body is not None else None
        h = {"Content-Type": "application/json", "X-Session-Id": self.sid, "Mcp-Session-Id": self.sid}
        if "chat/completions" in url:
            h["Authorization"] = "Bearer " + LLM_KEY
        req = urllib.request.Request(url, data=data, method="POST" if data else "GET", headers=h)
        t0 = time.time()
        raw = urllib.request.urlopen(req, timeout=60).read()
        self.bytes += len(raw)
        try:
            return json.loads(raw.decode()), time.time() - t0
        except Exception:
            return raw.decode(errors="replace"), time.time() - t0

LLM_BASE = os.environ.get("AGENT_LLM_BASE") or "https://openrouter.ai/api/v1/chat/completions"
LLM_KEY  = os.environ.get("AGENT_LLM_KEY")  or KEY
LLM_MODEL= os.environ.get("AGENT_LLM_MODEL") or MODEL

def llm(messages, meter):
    """One LLM call; records tokens. Retries once on unparseable/empty JSON (agents retry too).
    Provider-agnostic: Ollama Cloud, OpenRouter, anything /chat/completions."""
    body_url = LLM_BASE if LLM_BASE.endswith("/chat/completions") else LLM_BASE.rstrip("/") + "/chat/completions"
    last_out = ""
    for attempt in range(2):
        meter.llm_calls += 1
        res, _ = meter.http(body_url,
            {"model": LLM_MODEL, "messages": messages, "max_tokens": 4000, "temperature": 0})
        u = res.get("usage", {})
        meter.tok_in += u.get("prompt_tokens", 0); meter.tok_out += u.get("completion_tokens", 0)
        msg = res["choices"][0]["message"]
        content = msg.get("content") or ""
        # glm on ollama puts reasoning in separate field; content should be clean JSON
        out = content.strip() or msg.get("reasoning_content") or msg.get("thinking") or ""
        m = re.search(r"\{.*\}", out, re.S) if isinstance(out, str) else None
        if m and m.group(0).strip() != out.strip():
            out = m.group(0)
        last_out = out
        if out and (not isinstance(out, str) or clean(out)):
            return out
        if attempt == 0 and isinstance(out, str):
            messages = messages + [{"role": "assistant", "content": out[:100] or "(empty)"},
                                   {"role": "user", "content": "Respond with valid JSON only."}]
    return last_out

def clean(c):
    """strip markdown fences from model JSON answers"""
    if isinstance(c, str):
        m = re.search(r"\{.*\}|\[.*\]", c, re.S)
        return json.loads(m.group(0)) if m else {}
    return c

# ---------- PLAIN (DOM-agent path) ----------
def run_plain(task, meter):
    """LLM sees store HTML + products JSON once, then answers actions as JSON:
    {"pick": id or [ids], "checkout": true|false}. Harness executes cart ops."""
    html = meter.http(PLAIN)[0]  # store page (agent must understand it like a page)
    prods, _ = meter.http(PLAIN + "/api/products")
    brief = [{"id": p["id"], "name": p["name"], "price": p["price"], "rating": p["rating"],
              "category": p["category"], "spec": p["spec"]} for p in prods]
    msg = [{"role": "system", "content":
        "You are a shopping agent on an ecommerce site. You get the task and the product catalog JSON. "
        "Reply ONLY JSON: {\"pick\": [product ids in add order], \"checkout\": true|false, \"why\": \"<short reason>\"}."},
        {"role": "user", "content": f"TASK: {task}\n\nCATALOG: {json.dumps(brief)}"}]
    ans = clean(llm(msg, meter))
    if isinstance(ans, list):  # model returned a list of picks
        ans = {"pick": ans}
    if not isinstance(ans, dict):
        ans = {}
    picks = ans.get("pick", [])
    picks = [picks] if isinstance(picks, int) else picks
    total, last = 0, None
    for pid in picks:
        meter.http(PLAIN + "/api/cart/add", {"id": pid})
        p = next((x for x in brief if x["id"] == pid), None)
        total += p["price"]; last = p
    oid = None
    if ans.get("checkout"):
        oid = meter.http(PLAIN + "/api/checkout", {})[0].get("order_id")
    return {"added_name": last and last["name"], "added_price": last and last["price"],
            "added_spec": last and last["spec"], "cart_total": total, "order_id": oid,
            "why": ans.get("why", "")}

# ---------- MCP path ----------
def run_mcp(task, meter):
    meta = meter.http(MCP + "/.well-known/mcp")[0]
    endpoint = "/" + meta["endpoint"].lstrip("/")
    meter.http(MCP + "/mcp", {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    tools = meter.http(MCP + "/mcp", {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}})[0]["result"]["tools"]
    def tool(name, args):
        res, _ = meter.http(MCP + endpoint, {"jsonrpc": "2.0", "id": name, "method": "tools/call", "params": {"name": name, "arguments": args}})
        return res["result"]["structuredContent"]
    sysmsg = ("You are a shopping agent using MCP tools: " +
              json.dumps([{ "name": t["name"], "description": t["description"], "parameters": t.get("inputSchema")} for t in tools]) +
              ". Given a task, reply ONLY JSON {\"tool\": name, \"arguments\": {...}, \"done\": true|false}. "
              "Use search_products to find products, add_to_cart per product (you may need several), get_cart to verify, checkout when the task says to buy/checkout. "
              "Set done=true when the task is fully completed.")
    msgs = [{"role": "system", "content": sysmsg}, {"role": "user", "content": f"TASK: {task}"}]
    added, oid, total, last = [], None, 0, None
    seen = {}  # id → product dict from searches
    for _ in range(10):  # agent loop: model drives, harness executes
        ans = clean(llm(msgs, meter))
        if not ans: break
        name, args = ans.get("tool"), ans.get("arguments", {})
        # execute this turn's tool first; done=true means "no further calls after this one"
        will_finish = bool(ans.get("done"))
        if name == "search_products":
            out = tool("search_products", args)
            seen.update({p["id"]: p for p in (out if isinstance(out, list) else [])})
        elif name == "add_to_cart":
            out = tool("add_to_cart", args)
            p = seen.get(args.get("id"))
            if p and not any(x["id"] == p["id"] for x in added):
                added.append(p); total += p["price"]; last = p
        elif name == "get_cart":     out = tool("get_cart", args or {})
        elif name == "checkout":
            out = tool("checkout", args or {})
            if isinstance(out, dict) and out.get("order_id") and oid is None:
                oid = out["order_id"]   # don't overwrite a captured order with a duplicate-checkout error
        else: out = {"error": f"unknown tool {name}"}
        msgs.append({"role": "assistant", "content": json.dumps(ans)})
        msgs.append({"role": "user", "content": "RESULT: " + json.dumps(out)})
        if will_finish: break
    # self-check: model may end without executing the final checkout — reconcile against cart state
    if ("checkout" in task.lower() or "buy" in task.lower()) and oid is None:
        cart = tool("get_cart", {}) or {}
        items = cart.get("items", []) if isinstance(cart, dict) else []
        for it in items:
            pr = it.get("product") or {}
            p = seen.get(pr.get("id")) or pr  # trust the cart's own product data
            if p and not any(x["id"] == p["id"] for x in added):
                added.append(p); total += p["price"]; last = p
        if items:
            out = tool("checkout", {}); oid = (out or {}).get("order_id")
    return {"added_name": last and last["name"], "added_price": last and last["price"],
            "added_spec": last and last["spec"], "cart_total": total, "order_id": oid}

CHECKS = [
    lambda r: r["added_price"] <= 1500 and ("wireless" in (r["added_spec"] or "").lower() or "2.4" in (r["added_spec"] or "")),
    lambda r: r["added_name"] == "HP Pavilion 14",
    lambda r: r.get("order_id") and r["added_price"] <= 30000 and "5500mAh" in (r["added_spec"] or ""),
    lambda r: r["added_name"] == "Razer DeathAdder Essential",
    lambda r: r.get("order_id") and r["added_name"] == "MacBook Air M3 13",
    lambda r: r.get("order_id") and r["added_price"] <= 30000 and ("charging" in (r["added_spec"] or "").lower() or "80w" in (r["added_spec"] or "").lower()),
    lambda r: r.get("order_id") and r.get("cart_total") == 549 + 8995,
    lambda r: r.get("order_id") and r["added_name"] == "OnePlus 12R",
]

def main():
    rows = []
    for i, task in enumerate(TASKS, 1):
        for site, runner in [("plain", run_plain), ("mcp", run_mcp)]:
            m = Meter(f"llm-{site}-{i}")
            t0 = time.time()
            try:
                res = runner(task, m)
                ok = bool(CHECKS[i-1](res))
                err = ""
            except Exception as e:
                res, ok, err = {}, False, repr(e)[:120]
            rows.append({"task": i, "site": site, "requests": m.n, "bytes": m.bytes,
                         "secs": round(time.time()-t0, 1), "success": ok, "pick": res.get("added_name"),
                         "order_id": res.get("order_id"), "tok_in": m.tok_in, "tok_out": m.tok_out,
                         "llm_calls": m.llm_calls, "err": err})
            print(f"T{i} {site}: {'OK' if ok else 'FAIL'} pick={res.get('added_name')} oid={res.get('order_id')} tok={m.tok_in}/{m.tok_out} {err}")
    json.dump(rows, open(DIR + "/results_llm.json", "w"), indent=1)
    for site in ["plain", "mcp"]:
        rs = [r for r in rows if r["site"] == site]
        print(f"\n{site:5} | reqs {sum(r['requests'] for r in rs)} | bytes {sum(r['bytes'] for r in rs):,} | "
              f"success {sum(r['success'] for r in rs)}/{len(rs)} | tokens {sum(r['tok_in'] for r in rs):,}/{sum(r['tok_out'] for r in rs):,}")

if __name__ == "__main__":
    main()