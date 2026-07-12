# Codex review prompt — PR #57 (Search Console indexing fixes)

Copy everything below into Codex.

---

You are reviewing a pull request in `/Users/moeghashim/babanuj`, a Next.js 15
App Router storefront. This is a **review-only** task.

## Hard constraints

- Do NOT commit, push, edit files, or touch `main`. Produce a review report only.
- Do NOT read `.env.local` or any secret.
- Do NOT touch anything outside the repo (no Shopify admin, no domains, no
  Search Console changes).

## Required context — read these first, in this order

1. `AGENTS.md` — especially the new "Site architecture" section at the top
   (it is part of the diff under review, but it is also factually how this
   site works, so review *from* that frame):
   - This is **headless Shopify (Next.js Commerce on Vercel)**. It is NOT a
     Shopify theme. There is no Liquid in this repo.
   - `www.babanuj.com` → this repo on Vercel (all customer-facing pages,
     SEO-canonical site).
   - `checkout.babanuj.com` → Shopify's primary domain (checkout
     `/cart/c/<token>`, `/checkouts/*`, customer accounts, order status,
     Shopify email links, and the `/contact` endpoint the newsletter server
     action posts to). This subdomain is **correct by design**. Do not flag
     it as misconfigured and do not propose "fixing" it in this PR.
2. `reports/search-console-indexing-2026-06-10.md` (untracked local file) —
   the Google Search Console report this PR acts on.
3. The PR: branch `fix/search-console-indexing` vs `main`
   (https://github.com/moeghashim/babanuj/pull/57). Three commits, six files:
   `app/search/page.tsx`, `app/sitemap.ts`, `lib/babanuj/redirects.ts`,
   `progress.md`, `AGENTS.md`, `CLAUDE.md`.
   Diff: `git diff main...fix/search-console-indexing`

## What the PR claims to do

1. Make `/search` an intentional, indexable all-products landing page:
   title "Search the pantry" → "Shop All Middle Eastern Sweets & Pantry",
   explicit `robots: { index: true, follow: true }`, canonical `/search`
   unchanged.
2. Pin `/search` statically in `app/sitemap.ts` and filter the synthetic
   Shopify "All" collection (`path === "/search"`, injected by
   `getCollections()` in `lib/shopify/index.ts` around line 436) so the
   sitemap lists `/search` exactly once even if the Shopify fetch fails.
3. Add stale-product redirect
   `zaitoune-sweets-royal-petit-four-lotus-bounty-350g` →
   `/product/zaitoune-sweets-royal-petit-four-mix-chocolate-350g` via
   `STALE_PRODUCT_HANDLE_REDIRECTS` (covers `/product/…` and legacy
   `/products/…`; also consumed at runtime by
   `app/product/[handle]/page.tsx`). The old handle 404s in production; the
   target is live (200, self-canonical, indexable).
4. Document the headless architecture as prerequisite reading
   (`AGENTS.md` "Site architecture" section + two new Don'ts bullets +
   pointer in `CLAUDE.md`) and append a `progress.md` entry.

## Deliberate decisions — challenge them as decisions, not as omissions

- **Homepage canonical left emitting `https://www.babanuj.com` (no trailing
  slash).** Rationale: Next 15 hardcodes emitting the bare origin for
  root canonicals — verify yourself in
  `node_modules/next/dist/lib/metadata/resolvers/resolve-url.js`
  (`result.pathname === '/' && result.searchParams.size === 0 ?
  result.origin : result.href`; installed version 15.6.0-canary.60) — and
  per the WHATWG URL spec the slashless origin normalizes to the identical
  URL, so it cannot cause Google's "Duplicate without user-selected
  canonical" flag. Agree or refute.
- **`/search?q=…` results keep `index, follow` + canonical `/search`**
  (metadata is static; the page reads `searchParams` only in the body).
  Judged acceptable consolidation vs. making metadata dynamic under PPR.
  Agree or refute.
- **"Page with redirect" GSC rows intentionally untouched** — they are
  correct legacy 301/308s (`/collections/all` → `/search`,
  `/pages/:page` → `/:page`, apex → www).
- **checkout.babanuj.com serving the full legacy-theme catalog** is a known
  condition, documented in AGENTS.md, remedied (if ever) by publishing
  Vercel's Shopify Headless Theme in Shopify admin — explicitly out of
  scope for this repo and this PR.

## Review focus — verify, don't trust

1. **Regression risk:** could any change affect checkout, the cart
   (`checkoutUrl` from the Storefront API), customer accounts, or the
   newsletter action (`app/actions/newsletter.ts`)? (Claim: no — confirm.)
2. **Sitemap filter safety:** can `collection.path !== "/search"` ever drop
   a *real* collection? Check how `reshapeCollection` builds `path` in
   `lib/shopify/index.ts` and whether any real handle could produce
   `/search`.
3. **Redirect-map correctness:** entry syntax, alphabetical placement,
   no handle collisions, and that `next.config.ts` expands it to both
   `/products/<handle>` and `/product/<handle>`. Is redirecting to the
   chocolate-variant product better than `/collections/cookies` here?
4. **Metadata correctness:** the explicit `robots` object in
   `app/search/page.tsx` — confirm Next.js emits `index, follow` (not
   `noindex`) and nothing else in the metadata tree overrides it.
5. **Docs accuracy:** every factual claim in the new AGENTS.md section and
   CLAUDE.md pointer — especially (a) newsletter `POST /contact` treating
   Shopify 30x as success (read `app/actions/newsletter.ts:47-64`), and
   (b) the claim that Online Store password protection would break checkout
   and newsletter. Flag anything overstated.
6. **progress.md entry:** matches what was actually done.

## Empirical verification — run these and compare to expected results

```bash
pnpm exec tsc --noEmit            # expect: clean
pnpm build                        # expect: clean; /search listed as ◐ (PPR)

pnpm exec next start -p 3199 &    # then:
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  http://localhost:3199/product/zaitoune-sweets-royal-petit-four-lotus-bounty-350g
# expect: 308 → /product/zaitoune-sweets-royal-petit-four-mix-chocolate-350g
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  http://localhost:3199/products/zaitoune-sweets-royal-petit-four-lotus-bounty-350g
# expect: 308 → same target
curl -s http://localhost:3199/search | grep -o '<title>[^<]*</title>'
# expect: Shop All Middle Eastern Sweets &amp; Pantry | Babanuj
curl -s http://localhost:3199/search | grep -o '<meta name="robots"[^>]*>'
# expect: content="index, follow"
curl -s http://localhost:3199/sitemap.xml | grep -c '/search</loc>'
# expect: 1
curl -s -o /dev/null -w "%{http_code} %{redirect_url}\n" \
  http://localhost:3199/collections/all
# expect: 308 → /search
kill %1
```

Known non-issue: locally, canonical/sitemap hosts render as
`http://localhost:3000` because `baseUrl` falls back when
`VERCEL_PROJECT_PRODUCTION_URL` is unset. On Vercel it resolves to
`https://www.babanuj.com`. Do not flag this.

## Output format

1. **Verdict:** APPROVE or REQUEST CHANGES.
2. **Findings:** severity (blocker / major / minor / nit), `file:line`,
   issue, suggested fix.
3. **Decision review:** for each "deliberate decision" above — agree or
   disagree, with reasoning.
4. **Evidence:** which claims you verified empirically (commands + output)
   vs. accepted by reading code.
5. **Safety confirmation:** explicit yes/no — does any change in this PR
   touch checkout, cart, accounts, newsletter, or anything served by
   `checkout.babanuj.com`?
