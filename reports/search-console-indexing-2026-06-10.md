# Babanuj Search Console Indexing Report

Generated: 2026-06-10

Source inspected in Chrome:
`https://search.google.com/search-console/index?resource_id=sc-domain%3Ababanuj.com`

Search Console report state:

- Property: `sc-domain:babanuj.com`
- Report: Page indexing
- Last update shown by Search Console: `5/31/26`
- Indexed: `75`
- Not indexed: `153`
- Not indexed reasons: `8`

## Failed Search Console Buckets

| Reason | Source | Validation | Affected pages | Validation detail |
| --- | --- | --- | ---: | --- |
| Page with redirect | Website | Failed | 54 | Started `6/1/26`, failed `6/1/26`; details show `50` pending and `4` failed |
| Duplicate without user-selected canonical | Website | Failed | 9 | Started `5/25/26`, failed `6/1/26`; details show `8` pending and `1` failed |
| Crawled - currently not indexed | Google systems | Failed | 22 | Started `6/1/26`, failed `6/1/26`; details show `21` pending and `1` failed |

## Validation-Failed URLs

### Page with redirect

Validation failed URL examples:

- `https://www.babanuj.com/collections/all`
- `https://checkout.babanuj.com/products/zaitoune-mix-baklava-500g`
- `https://babanuj.com/pages/contact`
- `https://www.babanuj.com/pages/contact`

Live checks:

| URL | Live result | Notes |
| --- | --- | --- |
| `https://www.babanuj.com/collections/all` | `308` to `/search`, final `200` | Expected legacy collection redirect. Final page canonical is `https://www.babanuj.com/search`. |
| `https://babanuj.com/pages/contact` | `307` to `https://www.babanuj.com/pages/contact`, then `308` to `/contact`, final `200` | Expected apex and legacy page redirect chain, though the first `307` appears to come from platform/domain config before app redirects. |
| `https://www.babanuj.com/pages/contact` | `308` to `/contact`, final `200` | Expected legacy Shopify page redirect. |
| `https://checkout.babanuj.com/products/zaitoune-mix-baklava-500g` | `200` on the checkout subdomain | This is the highest-risk item. It serves an HTML product page with title `Zaitoune Mix Baklava Pistachio and Cashew - 500g - Babanuj`, canonical `https://checkout.babanuj.com/products/zaitoune-mix-baklava-500g`, and no robots meta. This is not controlled by the Next.js app routes. |

Interpretation:

- Most `Page with redirect` rows are expected stale URL inventory and should stay redirected.
- The `checkout.babanuj.com` product URL is different: it is crawlable as a separate host with a self-canonical product URL. That can compete with `www.babanuj.com` and is likely an operational/domain or Shopify theme issue, not a normal Next.js route issue.

### Duplicate without user-selected canonical

Validation failed URL:

- `https://www.babanuj.com/`

Pending examples:

- `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-1kg`
- `https://www.babanuj.com/product/zaitoune-mix-baklava-250g`
- `https://www.babanuj.com/product/zaitoune-sweets-mabrouma-400g`
- `https://www.babanuj.com/product/zaitoune-premium-turkish-delight-650g`
- `https://www.babanuj.com/product/zaitoune-sweets-royal-petit-four-lotus-bounty-350g`
- `https://www.babanuj.com/product/phoenicia-herbed-akawi-cheese-bread-2-pieces-411g-total-authentic-middle-eastern-flatbread-with-akawi-cheese-herbs-fresh-baked`
- `https://www.babanuj.com/product/leen-premium-ajwa-dates-resealable-zipper-pouch-fresh-authentic-ajwa-from-al-madinah-al-munawarah-natural-soft-rich-flavor-premium-saudi-dates`
- `https://www.babanuj.com/product/zaitoune-coffee-with-cardamom-500g`

Live checks:

- `https://www.babanuj.com/` returns `200`, `robots: index, follow`, and canonical `https://www.babanuj.com`.
- Most pending product examples return `200`, `robots: index, follow`, and self-canonical `/product/...` URLs on `www.babanuj.com`.
- `https://www.babanuj.com/product/zaitoune-sweets-royal-petit-four-lotus-bounty-350g` now returns `404`, `robots: noindex`, and no canonical. If this product has a replacement or collection fallback, add it to stale product redirects.

Interpretation:

- The homepage failed validation despite serving a canonical. The only obvious mismatch is root URL shape: inspected URL is `https://www.babanuj.com/`, canonical emits `https://www.babanuj.com` with no trailing slash.
- That may be acceptable to Google, so verify via URL Inspection before changing broad canonical behavior.
- Product pages likely need URL Inspection comparison of `User-declared canonical` vs `Google-selected canonical`; do not assume all pending rows need code changes.

### Crawled - currently not indexed

Validation failed URL:

- `https://www.babanuj.com/search`

Pending examples include:

- `https://www.babanuj.com/product/lord-honey`
- `https://www.babanuj.com/product/zaitoune-ghraybeh-250g`
- old `/_next/static/chunks/...` URLs returning `404`
- stale apex `/products/...` URLs that redirect to canonical `/product/...`
- old `.atom` collection feed URLs that redirect to the brand/collection destination

Live checks:

- `https://www.babanuj.com/search` returns `200`, `robots: index, follow`, canonical `https://www.babanuj.com/search`, title `Search the pantry | Babanuj`.
- `https://www.babanuj.com/product/lord-honey` returns `200`, `robots: index, follow`, self-canonical.
- `https://www.babanuj.com/product/zaitoune-ghraybeh-250g` returns `200`, `robots: index, follow`, self-canonical.
- Old `/_next/static/chunks/...` URLs return `404`; they are stale deployment artifacts and should not be redirected.

Interpretation:

- The only failed validation URL is `/search`.
- Decide intentionally whether `/search` should be an indexable all-products landing page. If yes, strengthen it and include it in `app/sitemap.ts`. If not, set it `noindex` and stop trying to validate it as indexable.

## Relevant Repo Map

- `next.config.ts`: app-level redirects, including apex to `www`, `/products/:handle` to `/product/:handle`, legacy `/pages/:page`, collection feeds, and stale product redirects.
- `lib/babanuj/redirects.ts`: shared stale product and legacy collection redirect maps.
- `app/layout.tsx`: root `metadataBase`, default robots, site metadata.
- `app/page.tsx`: homepage metadata and canonical.
- `app/search/page.tsx`: search page metadata and canonical.
- `app/product/[handle]/page.tsx`: product canonical metadata and stale product redirect hook.
- `app/collections/[handle]/page.tsx`: collection canonical metadata and legacy collection redirect hook.
- `app/sitemap.ts`: currently includes root, brands, fetched collections, and fetched products. It does not include `/search`.
- `app/robots.ts`: robots host and sitemap.

## Recommended Fix Direction

1. Treat ordinary `Page with redirect` rows as expected unless live URL Inspection says otherwise.
2. Investigate `checkout.babanuj.com/products/...` separately. It is serving product pages as `200` with a self-canonical checkout-subdomain URL. Fix likely requires Shopify/domain/theme configuration, not just this Next.js repo. Do not modify Shopify settings without explicit confirmation.
3. Add a stale-product redirect for `zaitoune-sweets-royal-petit-four-lotus-bounty-350g` if there is a sensible replacement product or category.
4. Verify whether the homepage canonical should emit `https://www.babanuj.com/` rather than `https://www.babanuj.com`.
5. Make an intentional SEO decision for `/search`: either make it an indexable all-products landing page and include it in the sitemap, or mark it `noindex`.
6. After code changes, deploy first, then use Search Console URL Inspection on the exact failed URLs before starting new validation.

## Prompt For Claude

Copy this prompt into Claude:

```text
You are working in /Users/moeghashim/babanuj, a Next.js 15 App Router storefront for Babanuj.

Read AGENTS.md first and follow it. Important constraints:
- Do not touch main directly.
- Do not commit secrets.
- Do not modify Shopify webhooks, store settings, domain settings, product data, or theme settings without explicit user confirmation.
- Any website change must append a progress.md entry before handoff.
- Before coding, inspect affected code for small behavior-preserving prefactors that make the fix safer.

Task:
Fix the actionable Google Search Console Page indexing issues summarized in reports/search-console-indexing-2026-06-10.md.

Current live Search Console state from Chrome:
- Page indexing last update: 5/31/26
- Indexed: 75
- Not indexed: 153
- Failed buckets:
  - Page with redirect: 54 affected, validation failed, details 50 pending and 4 failed.
  - Duplicate without user-selected canonical: 9 affected, validation failed, details 8 pending and 1 failed.
  - Crawled - currently not indexed: 22 affected, validation failed, details 21 pending and 1 failed.

Validation-failed URLs:
- Page with redirect:
  - https://www.babanuj.com/collections/all
  - https://checkout.babanuj.com/products/zaitoune-mix-baklava-500g
  - https://babanuj.com/pages/contact
  - https://www.babanuj.com/pages/contact
- Duplicate without user-selected canonical:
  - https://www.babanuj.com/
- Crawled - currently not indexed:
  - https://www.babanuj.com/search

Live HTTP findings:
- https://www.babanuj.com/collections/all redirects to /search and final page is 200 with canonical https://www.babanuj.com/search.
- https://babanuj.com/pages/contact redirects through www/pages/contact to /contact and final page is 200 with canonical https://www.babanuj.com/contact.
- https://www.babanuj.com/pages/contact redirects to /contact and final page is 200 with canonical https://www.babanuj.com/contact.
- https://checkout.babanuj.com/products/zaitoune-mix-baklava-500g returns 200 on the checkout subdomain with canonical https://checkout.babanuj.com/products/zaitoune-mix-baklava-500g and no robots meta. This is the risky item and may not be fixable in the Next.js repo.
- https://www.babanuj.com/ returns 200 with robots index, follow and canonical https://www.babanuj.com (no trailing slash).
- Most duplicate-canonical product examples return 200 with self-canonical /product/... URLs.
- https://www.babanuj.com/product/zaitoune-sweets-royal-petit-four-lotus-bounty-350g returns 404/noindex. Add a stale-product redirect if there is a sensible replacement.
- https://www.babanuj.com/search returns 200 with robots index, follow and canonical https://www.babanuj.com/search, but it is not in app/sitemap.ts.
- Old /_next/static/chunks/... examples return 404 and should not be redirected.

Focus:
1. Inspect next.config.ts, lib/babanuj/redirects.ts, app/layout.tsx, app/page.tsx, app/search/page.tsx, app/product/[handle]/page.tsx, app/collections/[handle]/page.tsx, app/sitemap.ts, and app/robots.ts.
2. Do not remove good legacy redirects just because Search Console has a Page with redirect bucket.
3. Decide and implement the repo-side fixes:
   - Root canonical: confirm whether homepage canonical should preserve trailing slash as https://www.babanuj.com/ and adjust safely if needed.
   - Search page: either make /search intentionally indexable by improving its SEO surface and adding it to sitemap, or mark it noindex if it should not be indexed. Be explicit in the handoff.
   - Stale product: add redirect for zaitoune-sweets-royal-petit-four-lotus-bounty-350g to the best replacement product or /collections/cookies if no exact replacement exists.
4. For checkout.babanuj.com, do not silently change external settings. Document the required operational fix and ask the user for confirmation if Shopify/domain/theme work is required.
5. Verify with:
   - pnpm exec tsc --noEmit
   - pnpm build
   - live or local HTTP checks showing status, final URL, robots, and canonical for the failed URLs above.
6. Append progress.md with date, scope, files touched, verification, and follow-up.

Expected handoff:
- List code changes made.
- List any Search Console rows that are intentionally not fixed in code and why.
- List exact URLs to inspect in Search Console before starting a new validation.
```
