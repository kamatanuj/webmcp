# ShopPilot Chrome Extension (MVP)

One install -> every Shopify store you visit gets 5 WebMCP tools
(`search_products`, `get_product_details`, `add_to_cart`, `get_cart`, `checkout`)
registered on `navigator.modelContext` — the store's own storefront APIs,
the user's logged-in session, zero proxy servers.

## Verify
```
DISPLAY=:99 /path-to-venv/bin/python3 probe.py      # exit 0 = all 5 tools pass on a real store
```

## Load for dev
chrome://extensions -> Load unpacked -> this folder (or `--load-extension=` in Playwright).
WebMCP ships enabled on Chrome 151+; on older builds launch with `--enable-features=WebMCP`.
