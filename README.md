# WebMCP Demo Store — one-file server, two modes, one benchmark

[![Listed on mcpservers.org](https://mcpservers.org/badge.svg)](https://mcpservers.org/servers/kamatanuj/webmcp)

Same store, same tools, two delivery modes:

- **WebMCP mode** — the page exposes its catalog through MCP tool calls (MCP-over-HTTP `/mcp`, plus Chrome-native `document.modelContext`), so an agent reads only what the task needs.
- **Plain mode** — the same store as an ordinary website; the agent parses full HTML pages, as every agent must today.

**Benchmark (150-product catalog, identical tasks): 79% less action bytes, 42% fewer input tokens, 8/8 tasks correct in both modes.** DOM mode wins on small catalogs then collapses; WebMCP wins with age. Crossover report: `report.html` → `WebMCP_Comparison_Report.pdf`.

## Run it

```bash
python3 server.py                    # plain mode      → http://localhost:9501
MCP=1 PORT=9502 python3 server.py    # WebMCP mode     → http://localhost:9502 + /mcp
```

stdlib-only (`http.server`, `json`, `uuid`, `threading`) — no pip install, no dependencies.

## Live demos

- plain: https://demonomcp.converso.work
- WebMCP: https://demowithmcp.converso.work (`.well-known/mcp` discovery, `/mcp` endpoint)
- launch package (deck, whitepaper, reports): https://demowithmcp.converso.work/launch.html

## Chrome-native WebMCP test (13 Oct 2026)

Chrome 154 + `--enable-features=WebMCP` exposes `document.modelContext` on HTTPS origins (about:blank excluded).

- Registered the 5-tool store contract via the IMPERATIVE API (`registerTool`): search_products, add_to_cart, get_cart, checkout (server-backed; all fetches in-page).
- Standard client flow verified: `getTools()` discovery → `executeTool()` calls → orders 1017/1018 placed, T2/T4/T8 picks correct (HP Pavilion 14, Razer DeathAdder, OnePlus 12R).
- 154 build quirks found & worked around:
  1. `executeTool(tool, args)` requires args as a JSON **string** (object form throws "Failed to parse input arguments"); return values are JSON strings too — JSON.parse both sides.
  2. Tools can't be re-registered under the same name (InvalidStateError) — reload the page to reset.
  3. Flag/feature name: `--enable-features=WebMCP` works headless; docs' `chrome://flags/#enable-webmcp-testing` is the manual path. Note: API is `document.modelContext` (moved from navigator since July 2026 build).
- Takeaway: the demo's tool contract is compatible with Chrome's native WebMCP, not just our JSON-RPC shim. When Chrome ships the client agent (Gemini-in-Chrome), the store is already agent-ready.

## Repo layout

| path | what |
|---|---|
| `server.py` | the whole thing: store + cart + orders + MCP transport (`MCP=1`) + static/report serving |
| `catalog.json` / `catalog_10.json` | 150-product / 10-product demo catalogs |
| `compare.py`, `compare_llm.py`, `browser_llm.py` | benchmark harnesses (DOM-mode agent, LLM-token accounting, browser-native flow) |
| `make_report.py` | regenerates the HTML/PDF reports from `results.json` / `agg_150_vs_30.json` |
| `whitepaper.html`, `report*.html`, `*.pdf`, `chart_*.png` | strategy + evidence artifacts (launch deck included) |
| `weekly_recap.py` | counters + live-URL digest (used by the ops cron) |

## License

MIT.