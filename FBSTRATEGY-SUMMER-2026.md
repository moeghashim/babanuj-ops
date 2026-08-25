# Babanuj Meta Ads — Summer 2026 Launch

**Focus products:** Phoenicia bread · Turkish Delight · Baklava
**Drafted:** 2026-06-13 · **Status:** plan approved, build pending
**Companion to:** [FBSTRATEGY.md](./FBSTRATEGY.md) (Eid sprint history + account/asset IDs)

This is the post-Eid summer launch. It reuses all infrastructure provisioned for
the Eid sprint and adds a new, separate lane for Phoenicia bread. No spend runs
until campaigns are reviewed in Ads Manager and explicitly activated.

## Approved configuration

- **Daily budget:** `$100/day`
- **Bread lane:** launches alongside the sweets lane, as an AddToCart test.
- **Framing:** evergreen summer (hosting, gifting, "taste of home" care
  packages). No Eid copy. Dubai-chocolate hold stays in effect.

## Reused assets (from FBSTRATEGY.md)

- Ad account: `act_1318507353009105` (USD, America/Chicago)
- Pixel / dataset: `983699467355178` (Babanuj Website Pixel)
- Facebook Page: `1159939973863006`
- Business portfolio: `Babanuj` (`365739834433686`)
- Catalog: `Babanuj Product Catalog` (`3804009119741863`)
- Product set (sweets lane DPA): `Zaitoune Baklava and Turkish Delight`
  (`1416041600294095`)

## Why two prospecting lanes, not one

Organic demand (GSC, last 4 months, `babanuj.com`) splits these products into
two different buyers:

| Category | Distinct queries | Impressions | Clicks | Read |
| --- | ---: | ---: | ---: | --- |
| Baklava | 29 | 1,166 | 7 | Strongest pull; tied to the Zaitoune brand |
| Turkish Delight | 16 | 354 | 5 | Real but smaller; same Zaitoune buyer |
| Phoenicia bread | 3 | 6 | 0 | Invisible organically — true cold start |

- **Baklava + Turkish Delight** are the same gift/hosting audience, heat-stable,
  and proven in the Eid sprint → one Sales campaign optimized for Purchase.
- **Phoenicia bread** is a diaspora/craving buy at a $43–47 price point, is
  perishable, and has zero warm signal → a separate, cheaper validation test on
  AddToCart before committing it to Purchase optimization.

## Campaign structure — $100/day

| # | Campaign | Objective / optimization | Audience | Daily |
| --- | --- | --- | --- | ---: |
| A | Sweets — Baklava + Turkish Delight | Sales → Purchase (fallback AddToCart) | Broad US + Advantage+ | `$45` |
| B | Phoenicia Bread (validation) | Sales → **AddToCart** | Broad US, diaspora-leaning | `$25` |
| C | Retargeting — all 3 | Sales → Purchase | Warm 30d + engagers 365d, excl. purchasers | `$20` |
| D | Creative testing | Sales, one variable per test | Broad US | `$10` |

Suggested names (matching the existing convention):

- A: `BAB | Sweets Prospecting | Sales | US | 2026-06`
- B: `BAB | Bread Test | Sales-ATC | US | 2026-06`
- C: `BAB | Retargeting | Sales | US | 2026-06`
- D: `BAB | Creative Test | Sales | US | 2026-06`

## Audiences

- **A (Sweets):** Broad US + Advantage+ Audience. The retargeting pool is too
  thin to seed lookalikes yet, so let Meta find buyers. Optional interest stack:
  Middle Eastern / Mediterranean cuisine, baklava, gourmet gifting, halal food.
- **B (Bread):** Broad US leaning into diaspora + craving signals — Lebanese /
  Levantine / Syrian cuisine, manakish / zaatar, Arabic-language affinity,
  Mediterranean groceries. Consider concentrating on large-MENA metros
  (Dearborn, Houston, Dallas, LA, NJ/NY, DC, Chicago): closer to the Houston
  kitchen means fresher arrival on a perishable and lower refund risk.
- **C (Retargeting):** site visitors 30d, product viewers 30d, add-to-cart 30d,
  IG/FB engagers 365d; exclude purchasers 30d.

## Creative plan

**Sweets (A) — adapt existing Eid assets, strip the Eid framing.** New frame:
summer hosting, coffee-table sweets, hostess gifts, care packages. Lead SKUs:

- Zaitoune Mix Baklava 250g — `/product/zaitoune-mix-baklava-250g`
- Zaitoune Sweets Mix Baklawa Pistachio & Honey 500g (higher AOV) —
  `/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`
- Zaitoune Turkish Delight 250g — `/product/zaitoune-turkish-delight-250g`

Formats: 3× 9:16 Reels (texture/pistachio detail, serving tray with coffee,
gift-box reveal), 2 statics, 1 category carousel.

**Bread (B) — NET-NEW, and the gating item for this lane.** No bread creative
exists yet; lane B cannot run ads until it is shot. Highest-craving SKUs:

- Zaatar bread (340g, $42.99) — manakish hero shot
- Akawi / Feta cheese bread (411g, $46.99) — the cheese pull is the best video
- Pita puff / pocket ($42.99–46.99) — "fresh from Houston" freshness/unboxing

Angles: real Levantine bread shipped fresh · diaspora nostalgia ("tastes like
home") · cheese pull · how-to-serve.

## Offer / AOV lever

Free US shipping at `$75`.

- Sweets are ~$15–25 each → push "build a box / hit $75 for free shipping."
- Bread is $43–47 → "2 loaves = free shipping" as the explicit CTA on lane B.
- A gift-box / bundle SKU would lift AOV and conversion on both lanes.

## Measurement & optimization

Prerequisite before activation: confirm `ViewContent`, `AddToCart`,
`InitiateCheckout`, and `Purchase` fire cleanly with good match quality in
Events Manager (browser Pixel + CAPI deduped by event ID; Purchase via the
Shopify checkout custom pixel).

- **A:** optimize for Purchase if post-Eid purchase volume is reliable;
  otherwise start on AddToCart / InitiateCheckout and graduate to Purchase.
- **B:** start on AddToCart. A brand-new account at a $43+ price point will not
  feed the Purchase optimizer enough events to exit learning. Prove cheap
  add-to-carts first, then graduate. If it can't produce ATCs cheaply, that is a
  cheap, fast learning — not a sunk purchase budget.

## Pre-launch checklist

1. Events Manager: verify the four ecommerce events + match quality.
2. Add the 9 Phoenicia bread SKUs to catalog `3804009119741863` and create a
   `Phoenicia Bread` product set (enables DPA retargeting later).
3. QA the bread PDPs above the fold: image, price, add-to-bag, and explicit
   freshness/shipping context (it is perishable — say how it ships).
4. Shoot the bread creative (blocks lane B going live).
5. Archive the expired Eid campaigns (`52533892689027`, `52534364160227`, and
   the two Maamoul Growth campaigns) so they don't pollute reporting.
6. Create all campaigns PAUSED → review in Ads Manager → activate only after
   reviewing URLs, budgets, copy, assets, and tracking.

## Build skeleton (paused) — `meta` CLI

Load credentials first (see FBSTRATEGY.md → CLI Workflow). Budgets are in cents.

```bash
# A — Sweets prospecting
meta ads campaign create \
  --name "BAB | Sweets Prospecting | Sales | US | 2026-06" \
  --objective outcome_sales --daily-budget 4500 --status paused

# B — Bread validation (AddToCart)
meta ads campaign create \
  --name "BAB | Bread Test | Sales-ATC | US | 2026-06" \
  --objective outcome_sales --daily-budget 2500 --status paused

# C — Retargeting
meta ads campaign create \
  --name "BAB | Retargeting | Sales | US | 2026-06" \
  --objective outcome_sales --daily-budget 2000 --status paused

# D — Creative testing
meta ads campaign create \
  --name "BAB | Creative Test | Sales | US | 2026-06" \
  --objective outcome_sales --daily-budget 1000 --status paused
```

Ad sets use pixel/dataset `983699467355178`. Sweets/retargeting/testing use
`--custom-event-type purchase`; bread uses `--custom-event-type add_to_cart`.
Retargeting requires website/engagement custom audiences (build in Ads Manager
or via CLI) with a 30-day purchaser exclusion.

## 14-day review

Review on spend, CTR, CPC, landing-page views, add-to-carts, initiated
checkouts, purchases, cost per purchase, ROAS, and retargeting frequency — not
after a handful of clicks. Move winning testing angles into prospecting; scale
budget no more than 20–30% at a time once performance is stable.

## Copy Bank — Summer 2026

Product-led, summer framing. No Eid copy, no fake discounts, no invented
reviews or star ratings, no hardcoded scarcity, and no delivery-time guarantees
ops hasn't confirmed.

### Lane A — Sweets (Baklava + Turkish Delight)

**A1 · Baklava, summer hosting**
- Primary: Set out a tray that does the talking. Zaitoune mix baklava — flaky,
  pistachio-rich, made for summer guests and the after-dinner coffee.
- Headline: Baklava, Made for Hosting
- CTA: Shop Now · LP: `/product/zaitoune-mix-baklava-250g`

**A2 · Baklava, gifting**
- Primary: A gift that feels like you went to the specialty market — without the
  trip. Premium Zaitoune baklava, shipped fresh from Houston.
- Headline: Gift-Ready Baklava
- CTA: Shop Now · LP: `/product/zaitoune-mix-baklava-250g`

**A3 · Pistachio & Honey Baklawa 500g (higher AOV)**
- Primary: Feeding a crowd? The 500g pistachio-and-honey baklawa mix is the easy
  centerpiece for gatherings, gifting, and weekend coffee.
- Headline: Pistachio & Honey Baklawa
- CTA: Shop Now · LP: `/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`

**A4 · Turkish Delight, coffee table**
- Primary: Soft, fragrant, and ready for the coffee table. A giftable box of
  Zaitoune Turkish delight to keep on hand all summer.
- Headline: Turkish Delight, 250g
- CTA: Shop Now · LP: `/product/zaitoune-turkish-delight-250g`

**A5 · Build a box (AOV / free shipping)**
- Primary: Baklava, Turkish delight, and more — build your own box of Middle
  Eastern sweets. Free U.S. shipping over $75, fresh from Houston.
- Headline: Build Your Sweets Box
- CTA: Shop Now · LP: `/`

### Lane B — Phoenicia Bread

**B1 · Zaatar bread, nostalgia**
- Primary: Real zaatar bread — the manakish you grew up on, baked the Levantine
  way and shipped fresh to your door. No specialty-market trip required.
- Headline: Zaatar Bread, Delivered Fresh
- CTA: Shop Now · LP: Phoenicia zaatar bread PDP

**B2 · Cheese bread, cheese pull**
- Primary: That cheese pull. Phoenicia akawi cheese bread, baked fresh in
  Houston and shipped to your table.
- Headline: Fresh Akawi Cheese Bread
- CTA: Shop Now · LP: Phoenicia akawi cheese bread PDP

**B3 · Pita, fresh staple**
- Primary: Soft, puffy, fresh pita — the real thing, shipped from Houston. Keep
  bread on hand that actually tastes like home.
- Headline: Authentic Pita Bread
- CTA: Shop Now · LP: Phoenicia pita PDP

**B4 · Free shipping / taste of home**
- Primary: Two loaves and your U.S. shipping is free. Zaatar, cheese, and pita
  breads — a taste of home, baked fresh in Houston.
- Headline: Levantine Bread, Shipped Fresh
- CTA: Shop Now · LP: Phoenicia bread collection

### Lane C — Retargeting

**C1 · Cart reassurance**
- Primary: Still thinking it over? Your sweets are waiting — fresh from Houston,
  with free U.S. shipping over $75 and a money-back freshness guarantee.
- Headline: Your Cart Is Waiting
- CTA: Shop Now · LP: cart / last product

**C2 · Bestseller nudge**
- Primary: The baklava and Turkish delight you looked at are some of our
  most-loved — packed fresh and shipped from Houston.
- Headline: Come Back for the Baklava
- CTA: Shop Now · LP: last viewed PDP

**C3 · Freshness / trust**
- Primary: Direct from heritage producers, shipped fresh from Houston, with a
  money-back freshness guarantee.
- Headline: Fresh, Guaranteed
- CTA: Shop Now · LP: `/`

## Bread Creative Brief (shot list)

Goal: manufacture craving + trust for a perishable, cold-start category that has
no warm audience yet. Texture and freshness do the selling.

Hero scenes:

1. **Cheese pull** — slow tear of warm akawi cheese bread, cheese strings, macro
   close-up. The scroll-stopper. Shoot 9:16 and 1:1.
2. **Zaatar manakish** — overhead, olive-oil drizzle, a hand tearing a piece,
   mint and tomato alongside. "Tastes like home."
3. **Pita puff** — bread puffing with steam, then folded/stuffed. Freshness cue.
4. **Unboxing** — box opens, bread revealed, a "shipped fresh from Houston"
   card. Trust/freshness.
5. **Table spread** — breads + zaatar + tea, summer-morning light. Hosting.

Deliverables: 3× 9:16 Reels (cheese pull, manakish, unboxing), 2 statics (cheese
macro, zaatar overhead), 1 carousel (zaatar / cheese / pita / "2 = free
shipping").

Props: olive oil, fresh mint, tomatoes, tea glasses, linen, wood board, Babanuj
box. Supers: "Fresh from Houston" and "2 loaves = free U.S. shipping."

Avoid: fake discounts, star ratings, generic stock footage, delivery-time
guarantees ops can't back, Eid framing. Audio: owned or licensed only — do not
enable Meta auto-music account-wide (see FBSTRATEGY.md note).

## Build log — 2026-06-13

Created via `meta` CLI against `act_1318507353009105`. All PAUSED; no spend.

**Campaigns (objective `OUTCOME_SALES`, ad-set-level budgets / ABO):**

| Lane | Campaign | ID |
| --- | --- | --- |
| A | BAB \| Sweets Prospecting \| Sales \| US \| 2026-06 | `52558618935427` |
| B | BAB \| Bread Test \| Sales-ATC \| US \| 2026-06 | `52558618937027` |
| C | BAB \| Retargeting \| Sales \| US \| 2026-06 | `52558618956027` |
| D | BAB \| Creative Test \| Sales \| US \| 2026-06 | `52558618959227` |

(Four earlier CBO shells were created then deleted — CBO forced a bid-cap
strategy the CLI can't unset.)

**Ad sets: PENDING — blocked on bid strategy.** This ad account's default bid
strategy for conversion ad sets requires a bid/cost cap, and the `meta` CLI
exposes no flag to set "lowest cost (no cap)" — the strategy your Eid Sales
campaign uses. Two ways to finish (do not activate until done + reviewed):

- **Recommended:** in Ads Manager, create each ad set below with **Bid strategy =
  Lowest cost (no cap)**.
- **Or via CLI:** add `--bid-amount <cents>` (a cost cap, e.g. target cost per
  purchase) to `meta ads adset create`.

Ad-set specs (pixel/dataset `983699467355178`, billing event IMPRESSIONS,
country US, status PAUSED):

| Lane | Parent campaign | Optimization | Event | Daily |
| --- | --- | --- | --- | ---: |
| A | `52558618935427` | Offsite conversions | Purchase | `$45` |
| B | `52558618937027` | Offsite conversions | Add to cart | `$25` |
| C | `52558618956027` | Offsite conversions | Purchase | `$20` |
| D | `52558618959227` | Offsite conversions | Purchase | `$10` |

**Lane C also needs audiences (Ads Manager only — CLI has no custom-audience
command):** include site visitors 30d, product viewers 30d, add-to-cart 30d,
IG/FB engagers 365d; exclude purchasers 30d.

**Still outstanding before any activation:** bread creative (lane B ads),
adapted sweets creative (lanes A/C/D ads), add 9 Phoenicia bread SKUs to catalog
`3804009119741863` + a `Phoenicia Bread` product set, verify pixel events in
Events Manager, archive the expired Eid campaigns.
