# Buyhatke Endpoint Map (reference for WebMCP launch deck)

Captured 2026-10-18 via desktop browser (CDP) + curl. All public, no auth.

## 1. Product-as-Distribution: the URL prefix trick
- `https://buyhatke.com/<any amazon.in product URL or path>` → server-side ASIN lookup →
  redirects to `/search?product=<slug>` → canonical product page:
  `/amazon-<slug>-price-in-india-63-<pid>` (63 = amazon vendor id; flipkart = 2).
  Example: `buyhatke.com/http://www.amazon.in/dp/B08N5WRWNW` → resolved instantly, zero install.

## 2. pid / vendor identity resolution
- `GET https://buyhatke.com/api/getGlobalPosAndPid?cb=<cachebust>`
  → per-site config: position code + `pidRegex` list for ASIN extraction:
  - `/dp/([A-Z0-9]+)`
  - `/(?:dp|gp(/product)?|product)/([A-Z0-9]{10})`
  - `/gp/aw/d/([A-Z0-9]{10})`
  - `MiniDP-AddToCart-([A-Z0-9]+)`
  - last-10-chars fallback
  → currency map per TLD, `skuRegex`, search param keys.

## 3. Price history data service
- `POST https://search-new.bitbns.com/buyhatke/thunder/priceData`
  - Headers: `Content-Type: application/json`, Referer buyhatke.com (no auth)
  - Body: `{"param": [[63, "B009HLUFEY"]]}`  → `[[vendorId, "ASIN"]]`
  - Response (verified): `{"status": 1, "data": {...}}` — note: host is bitbns.com
    (sister company), i.e. Buyhatke reuses internal infra for the tracker API.
  - Wrong-params reply: `{"status":0,"msg":"Invalid Params!"}`
- UI: product page "Price History" card, tabs `1 Month / 3 Month / Max`.

## 4. Related products
- `GET https://buyhatke.com/userDeals/relatedProducts?items=[[ "B009HLUFEY", 63]]`
  (ASIN, vendorId pairs, JSON-stringified array)

## 5. Identity / content services
- `GET https://ext1.buyhatke.com/spend-apis/login/loggedIn?platform=0` (session state)
- `https://ch.buyhatke.com/bhs/identity/init|update`, `/bhs/content/slots|serve` (personalization)

## 6. Misc platform APIs on main domain
`/api/getSiteLogo?countryCode=IN&countryName=India`, `/api/giftCardOutages`.

## WebMCP relevance
- The prefix URL = the UX template for webmcp.dev's "$0-install demo": resolve
  any product URL server-side, show instant value, no extension/SDK.
- ASIN regex list + vendor ids = the exact contract a WebMCP `catalog`
  tool would expose to agents (getPid → getPriceHistory → relatedProducts).
- compare.buyhatke.com (older service host) 502s datacenter traffic →
  bot-walled; browser-grade TLS needed. WebMCP replaces scraping with
  first-party tool calls — this is the pitch.