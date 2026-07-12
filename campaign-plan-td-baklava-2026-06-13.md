# Google Ads — New Campaign Plan: Turkish Delight + Baklava

_Prepared 2026-06-13. Account 1604376990 (Babanuj). Brand = Zaitoune._

## TL;DR

Build **two dedicated non-brand Search campaigns** — one for Turkish Delight, one
for Baklava — each pointed at its existing collection page. This is the one paid
lever that is genuinely *new*: it captures generic "buy baklava / turkish delight
online" demand that (a) organic can't reach (we rank position 13–58 for it) and
(b) PMax deprioritizes once a Search exact/phrase keyword matches. We do **not**
add Standard Shopping — the existing Sales-PMax already owns the product feed and
would simply out-rank it.

Frame honestly: at ~1% site conversion rate and ~1.1x real (purchase-only) blended
ROAS, non-brand Search is a **customer-acquisition** play, not a first-order
profit machine. The levers that make it pay: tight high-intent keywords, the
$10-off hook, the $70 free-ship threshold to lift AOV, and collection-page CR.

## Account context (real numbers)

- 3 enabled PMax: Sales-PMax ($423/mo, tROAS just set to 5), Fresh Phoenicia
  Bread ($171/mo), Eid Adha 2026 ($136/mo). ~$730/mo total, ~$24/day.
- 2 empty PAUSED shells: "search-campaign", "search-campaign #2" → delete/rename.
- Real purchase-only ROAS ≈ **1.10x** blended (reported 4.9x was inflated by the
  now-fixed add-to-cart/checkout-start biddable goals).
- AOV ≈ **$52** (GA4) / ~$54 (Ads). Site CR ≈ **1%**.
- Conversion tracking: Shopify Google & YouTube app (server-side, "Google Shopping
  App Purchase"). Purchase = primary/biddable; ATC + checkout-start = secondary.
- Offers live: **$10 off first order**, **free US shipping over $70**.
- Houston-based ("packed fresh in Houston"), ships US.

## Demand signal (GSC, last 120d, sc-domain:babanuj.com)

- Branded ranks well organically (zaitoune sweets, zaitoune baklava/turkish
  delight at pos 2–7) → don't overspend defending it.
- Generic non-brand is unreached: buy turkish delight, turkish sweets online,
  arabic sweets online usa, turkish delights houston, turkish delight assortment,
  mabrouma baklava, 100g/250g baklava — all pos 13–58. **This is the paid gap.**
- Turkey/AU brand-hunter noise to exclude: fiyatları, üsküdar, istanbul, kimin,
  zeytunoğlu, borabi/bankstown, yenigun.

## Live catalog (authoritative, in stock)

**Turkish Delight** → `/collections/turkish-delight`
- Zaitoune Turkish Delight (Lokum) 250g — $19.99
- Zaitoune Turkish Delight (Lokum) 650g — $34.40

**Baklava** → `/collections/baklava`
- Baklava 100g $8.90 · 250g $18.00 · 500g $34.80 · With Honey 500g $48.70 ·
  Kol Shkor (Honey, Special Ed.) 500g $46.40 · 1kg $64.80 · Mabrouma Rolls $43.20

---

## Campaign 1 — Search · Turkish Delight · Nonbrand · US

- **Final URL:** https://www.babanuj.com/collections/turkish-delight
- **Network:** Search only (no Display/partners). **Geo:** US (presence). +Texas bid
  observation (Houston local + cheaper ship). **Language:** English (+Arabic obs).
- **Bidding:** Maximize Conversions (no target) for the learning period → add
  tCPA once ≥15–20 conv. **Goal:** account-default (Purchase primary).

**Ad groups & keywords** (phrase + exact)
- *TD — Core:* [turkish delight], "buy turkish delight", "turkish delight online",
  "order turkish delight", [lokum], "turkish lokum", [authentic turkish delight],
  "turkish delight candy"
- *TD — Flavors:* "pistachio turkish delight", "rose turkish delight",
  "pomegranate turkish delight", "assorted turkish delight",
  "turkish delight assortment", "turkish delight variety pack"
- *TD — Gift:* "turkish delight gift box", "turkish delight gift", "turkish delight box"

**RSA headlines:** Authentic Turkish Delight · Turkish Delight, Shipped Fresh ·
$10 Off Your First Order · Free US Shipping Over $70 · Rose, Pistachio &
Pomegranate · Real Lokum, Made Fresh · Order Turkish Delight Online · Made Fresh
in Houston · Zaitoune Turkish Delight · Gift-Ready Lokum · Ships Across the USA ·
250g & 650g Boxes · No Artificial Shortcuts · Levantine Sweets Online · Shop
Turkish Delight Today
**Descriptions:** (1) Authentic lokum made fresh and shipped to your door. $10 off
your first order. (2) Rose, pistachio & pomegranate. Free US shipping over $70.
(3) Real ingredients, no shortcuts — packed fresh in Houston, shipped nationwide.
(4) Gift-ready boxes of Zaitoune Turkish delight. Fast US shipping.

---

## Campaign 2 — Search · Baklava · Nonbrand · US

- **Final URL:** https://www.babanuj.com/collections/baklava
- Same network/geo/language/bidding/goal settings as Campaign 1.

**Ad groups & keywords** (phrase + exact)
- *Baklava — Core:* [baklava], "buy baklava", "buy baklava online", "baklava online",
  "order baklava online", "baklava delivery", "fresh baklava", [authentic baklava]
- *Baklava — Type:* "pistachio baklava", "walnut baklava", "assorted baklava",
  "mixed baklava", "baklava assortment", "baklava rolls", "mabrouma",
  "baklava with honey"
- *Baklava — Gift/Occasion:* "baklava gift box", "baklava gift", "baklava box",
  "baklava for eid"

**RSA headlines:** Fresh Baklava, Shipped Weekly · Authentic Pistachio Baklava ·
$10 Off Your First Order · Free US Shipping Over $70 · Pistachio & Walnut Baklava ·
Order Baklava Online · Made Fresh in Houston · Baklava From $8.90 · Zaitoune
Baklava Boxes · Baklava With Honey · Mabrouma Rolls & Assortments · Ships Across
the USA · Gift-Ready Baklava Boxes · 250g, 500g & 1kg · Real Honey, Real Pistachio
**Descriptions:** (1) Authentic Levantine baklava made fresh and shipped
nationwide. $10 off your first order. (2) Pistachio, walnut, honey & mabrouma
rolls. Free US shipping over $70. (3) Packed fresh in Houston — no frozen, no
shortcuts. (4) Build a gift box of Zaitoune baklava. From $8.90.

---

## Shared setup (both campaigns)

**Assets**
- Sitelinks: Shop Baklava · Shop Turkish Delight · Baklava With Honey · 1kg
  Baklava Box · Gift Boxes · $10 Off First Order
- Callouts: Free US Shipping Over $70 · $10 Off First Order · Made Fresh Weekly ·
  Packed in Houston, TX · Ships Nationwide
- Structured snippets — Types: (Baklava) Pistachio, Walnut, With Honey, Mabrouma;
  (TD) Rose, Pistachio, Pomegranate, Assorted. Brands: Zaitoune
- Price assets: use the live SKU prices above. Image assets: reuse PMax creative.

**Negative keywords** (apply as a shared list + per-theme)
- Intent: recipe, recipes, how to make, calories, nutrition, sugar free, diabetic,
  wholesale*, franchise, jobs, hiring, recall
- TD-specific: narnia, "c.s. lewis", wikipedia
- Retail competitors: costco, aldi, "trader joe", "sam's club"
- Geo/brand-hunter noise: fiyat, fiyatları, istanbul, üsküdar, kimin, zeytunoğlu,
  borabi, bankstown, yenigun
- Monitor (don't block yet): "near me" (local-pickup intent, lower CR)
- *Leave "wholesale" in if B2B leads are wanted — split to its own campaign.

**Hygiene:** delete/rename the two empty "search-campaign" shells.

## Budget & honest projection (per campaign, Moderate $10/day)

| Metric | Assumption | ~Monthly |
|---|---|---|
| Spend | $10/day | ~$300 |
| CPC | ~$0.90 (US nonbrand) | — |
| Clicks | — | ~330 |
| CR | ~1.2% (tight intent) | — |
| Orders | — | ~4 |
| Revenue | AOV $52 | ~$208 |
| **First-order ROAS** | | **~0.7x** |

Below first-order breakeven — expected for nonbrand prospecting. It pays only via
(a) lifting collection-page CR toward 2%, (b) pushing AOV over the $70 free-ship
line, and (c) repeat/LTV. Start small, judge on **blended new-customer CPA incl.
30–90d repeat**, not day-one ROAS. <$10/day starves learning; don't go lower if
we want a verdict in 30 days.

## Measurement & next steps

- Week 1–2: daily search-terms review → prune to negatives aggressively.
- Day 30: evaluate CPA + collection-page CR; kill/scale per theme (not whole campaign).
- Ties into the existing re-measure cadence (baseline-2026-06-13 → ~2026-06-27).
- Bonus (not in ask): a cheap **brand-defense Search** campaign on "zaitoune…"
  runs very high ROAS and blocks competitor poaching — flag for later.
