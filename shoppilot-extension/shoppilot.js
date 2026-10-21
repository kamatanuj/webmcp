// ShopPilot — WebMCP toolkit injected into store pages (MAIN world).
// Detects a Shopify storefront and registers 5 agent tools on navigator.modelContext
// using the store's own public storefront APIs + the user's session. No proxy servers.
(() => {
  if (window.__shoppilot_mcp) return;  // SPA re-injection guard
  const AFFILIATES = [
    // Attribution layer: fill tags from your affiliate programs (EarnKaro dashboard
    // shows the tag/affid per network; Shopify Collabs issues ?ref= codes per store).
    // Empty objects = no rewrite, tools behave exactly as before.
    {match: /(^|\.)amazon\.(com|in)$/, params: {}},          // e.g. {tag: 'shoppilot-21'}
    {match: /(^|\.)flipkart\.com$/, params: {}},              // e.g. {affExtParam1: 'PID', affExtParam2: 'SID'}
    {match: /(^|\.)myntra\.com$/, params: {}},                // e.g. {aff_id: '...'}
    // Generic Shopify Collabs-style referral, set the store's code here:
    // {match: /(^|\.)allbirds\.com$/, params: {ref: 'shoppilot'}},
  ];
  function tagUrl(u) {
    try {
      const url = new URL(u, location.origin);
      const cfg = AFFILIATES.find(a => a.match.test(url.hostname) && Object.keys(a.params).length);
      if (!cfg) return {url: u, tagged: false};
      for (const [k, v] of Object.entries(cfg.params)) url.searchParams.set(k, v);
      return {url: url.toString(), tagged: true};
    } catch { return {url: u, tagged: false}; }
  }
  const t = { q: null };
  async function isShopify() {
    try {
      const r = await fetch('/products.json?limit=1', {credentials: 'same-origin'});
      if (!r.ok) return false;
      const j = await r.json();
      return Array.isArray(j.products);
    } catch { return false; }
  }
  async function searchProducts({query}) {
    const r = await fetch('/products.json?limit=250', {credentials: 'same-origin'});
    const {products} = await r.json();
    const ql = (query || '').toLowerCase();
    const hits = products.filter(p =>
      [p.title, p.vendor, p.product_type, ...(p.tags||[])].join(' ').toLowerCase().includes(ql))
      .slice(0, 10)
      .map(p => ({handle: p.handle, title: p.title, vendor: p.vendor, type: p.product_type,
        price: (p.variants[0] && p.variants[0].price) || '', variants: p.variants.length,
        tags: (p.tags || []).slice(0, 5),
        url: tagUrl(location.origin + '/products/' + p.handle).url}));
    return {store: location.origin, results: hits, count: hits.length};
  }
  async function productDetails({handle}) {
    const r = await fetch('/products/' + encodeURIComponent(handle) + '.js', {credentials: 'same-origin'});
    if (!r.ok) throw new Error('product not found: ' + handle);
    const p = await r.json();
    return {handle, title: p.title, vendor: p.vendor, description: (p.description || '').slice(0, 500),
      variants: p.variants.map(v => ({id: v.id, title: v.title, price: v.price, available: v.available}))};
  }
  async function addToCart({variant_id, quantity}) {
    const r = await fetch('/cart/add.js', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({items: [{id: Number(variant_id), quantity: Number(quantity) || 1}]})});
    if (!r.ok) throw new Error('add failed (' + r.status + ') — check variant_id is a valid variant ID');
    const item = await r.json();
    return {added: item.product_title, variant: item.variant_title || String(variant_id),
      qty: item.quantity, price: item.price};
  }
  async function getCart() {
    const c = await (await fetch('/cart.js', {credentials: 'same-origin'})).json();
    return {items: c.items.map(i => ({product: i.product_title, variant: i.variant_title,
        qty: i.quantity, line_price: i.final_line_price / 100})),
      total: c.total_price / 100, currency: c.currency, item_count: c.item_count};
  }
  async function checkout({variant_id, quantity}) {
    // Shopify cart permalink: browser resolves it server-side to a real /checkouts/cn/<token>
    // page where payment completes (human or desktop agent). Nothing is charged by the tool.
    const tagged = tagUrl(location.origin + '/cart/' + variant_id + ':' + (Number(quantity) || 1));
    return {checkout_url: tagged.url, affiliate_tagged: tagged.tagged,
      note: 'Open this URL to complete payment — requires user consent.'};
  }
  const T = (name, description, properties, required, execute) =>
    ({name, description, inputSchema: {type: 'object', properties, required}, execute});
  window.__shoppilot = {searchProducts, productDetails, addToCart, getCart, checkout, tagUrl, AFFILIATES};
  function registerAll() {
    window.__shoppilot_mcp = true;
    const mc = navigator.modelContext;
    mc.registerTool(T('search_products', 'Search products in this store. Use for any product discovery.',
      {query: {type: 'string', description: 'search text, e.g. "white wool runners size 8"'}}, ['query'], searchProducts));
    mc.registerTool(T('get_product_details', 'Get full details of one product by its handle (from search results).',
      {handle: {type: 'string', description: 'product handle, e.g. "wool-runner-go"'}}, ['handle'], productDetails));
    mc.registerTool(T('add_to_cart', 'Add a specific variant to the shopping cart.',
      {variant_id: {type: 'number', description: 'numeric variant ID from get_product_details'},
       quantity: {type: 'number', description: 'quantity, default 1'}}, ['variant_id'], addToCart));
    mc.registerTool(T('get_cart', 'Get current cart contents and total.', {}, [], getCart));
    mc.registerTool(T('checkout', 'Get the checkout URL for a variant. Payment completes in the browser with user consent.',
      {variant_id: {type: 'number', description: 'numeric variant ID'},
       quantity: {type: 'number', description: 'quantity, default 1'}}, ['variant_id'], checkout));
    console.info('[ShopPilot] 5 WebMCP tools + affiliate attribution registered for', location.origin);
  }
  isShopify().then(ok => { if (ok) registerAll(); });
})();
