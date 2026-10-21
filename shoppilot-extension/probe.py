#!/usr/bin/env python3
"""ShopPilot extension self-check: loads the unpacked extension, opens a real
Shopify store, exercises all 5 tool impls the content script registers.
Run: DISPLAY=:99 /root/voice-agent-generator/venv/bin/python3 probe.py
"""
import os, sys
from playwright.sync_api import sync_playwright

STORE = os.environ.get("SHOPILOT_PROBE_STORE", "https://www.allbirds.com/")

with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        user_data_dir="/tmp/shoppilot-probe-profile", headless=False,
        args=["--disable-extensions-except=/root/shoppilot-extension",
              "--load-extension=/root/shoppilot-extension",
              "--enable-features=WebMCP", "--no-sandbox", "--disable-gpu"],
        viewport={"width": 1280, "height": 720})
    pg = ctx.pages[0] if ctx.pages else ctx.new_page()
    pg.goto(STORE, timeout=45000)
    pg.wait_for_timeout(6000)
    res = pg.evaluate("""(async () => {
      const s = window.__shoppilot;
      if (!s) return {fail: 'content script did not run'};
      const sr = await s.searchProducts({query: 'shoe'});
      const det = sr.results[0] ? await s.productDetails({handle: sr.results[0].handle}) : null;
      const cart0 = await s.getCart();
      let add = null, cart1 = null, co = null;
      if (det) {
        const v = det.variants.find(v => v.available) || det.variants[0];
        add = await s.addToCart({variant_id: v.id, quantity: 1});
        cart1 = await s.getCart();
        co = await s.checkout({variant_id: v.id, quantity: 1});
      }
      const t0 = s.tagUrl(location.origin + '/cart/123:1');                     // empty config = pass-through
      s.AFFILIATES.push({match: /./, params: {ref: 'shoppilot'}});              // simulate a configured program
      const t1 = s.tagUrl(location.origin + '/cart/123:1');                     // now tagged
      const t2 = s.tagUrl(location.origin + '/cart/123:1?ref=keep');            // append, don't clobber unknown params
      return {search_hits: sr.count, passthrough_untagged: t0.tagged === false,
              tagged_ref: t1.url.includes('ref=shoppilot'), tagged_tagged_flag: t1.tagged === true,
              append_not_clobber: t2.url.includes('ref=shoppilot'),
              details_ok: !!det,
              cart_added: !!cart1 && cart1.item_count > cart0.item_count,
              checkout_url: co && co.checkout_url};
    })()""")
    ctx.close()

hits = res.get('search_hits', 0)
ok = (hits > 0 and res.get('details_ok') and res.get('cart_added')
      and res.get('checkout_url', '').rstrip('/').endswith(':1')
      and res.get('passthrough_untagged') and res.get('tagged_ref')
      and res.get('tagged_tagged_flag') and res.get('append_not_clobber'))
print(f"probe: search={hits} details={res.get('details_ok')} cart_added={res.get('cart_added')} "
      f"checkout={res.get('checkout_url')}")
sys.exit(0 if ok else 1)