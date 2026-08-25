# Babanuj Facebook Ads Strategy

This document defines the first Meta ads strategy for Babanuj. The goal is to
launch a controlled sales-focused account structure, keep spend paused until
reviewed, and build around measurable purchase intent rather than vanity traffic.

## Current Setup

- Meta Ads CLI is installed as `meta`.
- Local credentials live in `.env.local`, which is gitignored. Do not print or
  commit the access token.
- Business portfolio: `Babanuj` (`365739834433686`).
- System user: `automation` (`61589803752965`).
- Active ad account configured for CLI: `act_1318507353009105`.
- Facebook Page ID: `1159939973863006`.
- Dataset discovered in the Babanuj business:
  - Name: `WhatsApp Marketing Message Event Sharing`
  - ID: `1297858335746827`
  - Last fired: empty at discovery time.
- Website dataset/pixel created on May 19, 2026:
  - Name: `Babanuj Website Pixel`
  - ID: `983699467355178`
  - Connected to ad account `act_1318507353009105`.
  - Assigned to the automation system user with advertise, analyze, edit, and
    upload permissions.
- Product catalog created on May 19, 2026:
  - Name: `Babanuj Product Catalog`
  - ID: `3804009119741863`
  - Products loaded: 13 priority sweets.
  - Connected dataset: `983699467355178`.
- Product sets:
  - `Eid Sweets - High AOV` (`977592524643567`)
  - `Zaitoune Baklava and Turkish Delight` (`1416041600294095`)
  - `Zaitoune Maamoul` (`1844674889823942`)
  - `Leen Maamoul` (`2075721163294249`)
- Account currency: USD.
- Account timezone: America/Chicago.
- App status: `babanuj-ad` is Published/Live.
- Payment method: added after initial ad creation was blocked.
- Privacy policy URL for Meta:
  `https://www.babanuj.com/privacy-policy`.

Do not commit access tokens, ad account secrets, app secrets, or exported env
files.

## Created Meta Assets

Created on May 18, 2026 through Meta Ads CLI:

- Campaign: `Eid Sprint 2026 - Product Traffic`
  - ID: `52533892689027`
  - Objective: `OUTCOME_TRAFFIC`
  - Budget: `$50/day`
  - Status: `PAUSED`
- Ad set: `Broad US - Eid Product Visitors`
  - ID: `52533892795627`
  - Campaign ID: `52533892689027`
  - Optimization: landing page views
  - Billing event: impressions
  - Audience: broad US
  - Flight: May 18, 2026 8:44 PM CDT to May 22, 2026 8:44 PM CDT
  - Status: `PAUSED`
- Creatives:

  - `Eid 2026 - Zaitoune Turkish Delight`
    - ID: `1008148524890748`
    - URL: `https://www.babanuj.com/product/zaitoune-turkish-delight-250g`
  - `Eid 2026 - Zaitoune Mix Baklava`
    - ID: `975625665205560`
    - URL: `https://www.babanuj.com/product/zaitoune-mix-baklava-250g`
  - `Eid 2026 - Pistachio Honey Baklawa`
    - ID: `881174701659446`
    - URL: `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`
  - `Eid 2026 - Milaf Date Cola`
    - ID: `980572817781463`
    - URL: `https://www.babanuj.com/product/milaf-date-cola-240ml-8-1-fl-oz`

- Ads:
  - `Eid 2026 - Zaitoune Turkish Delight`
    - ID: `52533895583227`
    - Creative ID: `1008148524890748`
  - `Eid 2026 - Zaitoune Mix Baklava`
    - ID: `52533895603227`
    - Creative ID: `975625665205560`
  - `Eid 2026 - Pistachio Honey Baklawa`
    - ID: `52533895591227`
    - Creative ID: `881174701659446`
  - `Eid 2026 - Milaf Date Cola`
    - ID: `52533895596627`
    - Creative ID: `980572817781463`

The campaign and ad set are paused, so no spend is running. Newly created ads
showed `IN_PROCESS` immediately after creation, which is Meta's review/setup
state.

Activated on May 18, 2026 at 9:05 PM CDT after user approval:

- Campaign `52533892689027`: `ACTIVE`
- Ad set `52533892795627`: `ACTIVE`
- Ads `52533895583227`, `52533895603227`, `52533895591227`, and
  `52533895596627`: updated to active; Meta reported `IN_PROCESS` immediately
  after activation.

Optimized on May 19, 2026 after user approval:

- The four active Eid ads were swapped to enhanced creatives with Meta creative
  features enabled for image touchups, text optimizations, text overlays, and
  automatic image crop. Meta placed the ads back into `IN_PROCESS`, which is
  expected after creative changes.
  - Turkish Delight enhanced creative: `1959537381348008`
  - Mix Baklava enhanced creative: `1006201405267017`
  - Pistachio Honey Baklawa enhanced creative: `1701096157696075`
  - Milaf Date Cola enhanced creative: `1352173970059064`
- Milaf Date Cola ad `52533895596627` was paused so it no longer consumes
  primary prospecting spend. Keep it as an add-on/upsell item.
- Created a 9:16 Reels video asset from approved product imagery:
  `/tmp/babanuj-meta-assets/reels/eid-high-aov-reel.mp4`.
- Uploaded the Reels creative:
  - Creative: `Eid 2026 - Reels - High AOV Sweets`
  - Creative ID: `1721135682245136`
  - Destination:
    `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`
- Added active Reels ad to the Eid ad set:
  - Ad: `Eid 2026 - Reels - High AOV Sweets`
  - Ad ID: `52534370695227`

Meta also recommended auto music for image/video ads. Do not enable this
account-wide without creative review; Babanuj should use controlled audio or
approved music only.

Created on May 19, 2026 as the paused sales replacement structure:

- Campaign: `Eid Sales - 7x ROAS Test`
  - ID: `52534364160227`
  - Objective: `OUTCOME_SALES`
  - Budget: `$50/day`
  - Bid strategy: lowest cost without cap
  - Status: `PAUSED`
- Ad set: `Broad US - Purchase - Eid High AOV`
  - ID: `52534364877027`
  - Optimization: offsite conversions
  - Custom event: purchase
  - Pixel/dataset: `983699467355178`
  - Audience: broad US with Advantage audience
  - Status: `PAUSED`
- Ads:
  - `Sales - Zaitoune Honey Baklava 500g` (`52534365070427`)
  - `Sales - Zaitoune Pistachio Maamoul 500g` (`52534365094827`)
  - `Sales - Zaitoune Mix Baklava 250g` (`52534365110027`)
  - `Sales - Zaitoune Turkish Delight 250g` (`52534365141227`)

Do not activate the sales campaign until the Pixel/CAPI changes are deployed
and Events Manager confirms clean `ViewContent`, `AddToCart`,
`InitiateCheckout`, and ideally `Purchase` events.

Created on May 18, 2026 as paused Maamoul growth campaigns:

- Campaign: `Maamoul Growth - Zaitoune Product Traffic`
  - ID: `52533918886627`
  - Objective: `OUTCOME_TRAFFIC`
  - Budget: `$25/day`
  - Status: `PAUSED`
- Ad set: `Broad US - Zaitoune Maamoul Visitors`
  - ID: `52533918905427`
  - Campaign ID: `52533918886627`
  - Optimization: landing page views
  - Billing event: impressions
  - Audience: broad US
  - Status: `PAUSED`
- Zaitoune Maamoul ads:

  - `Maamoul Growth - Zaitoune Date 500g`
    - Ad ID: `52533919124627`
    - Creative ID: `27364986189785708`
    - URL: `https://www.babanuj.com/product/zaitoune-dates-mamoul-500g`
  - `Maamoul Growth - Zaitoune Date 250g`
    - Ad ID: `52533919144627`
    - Creative ID: `1344598750862305`
    - URL: `https://www.babanuj.com/product/zaitoune-maamoul-date-250g`
  - `Maamoul Growth - Zaitoune Walnut`
    - Ad ID: `52533919116827`
    - Creative ID: `749658451502543`
    - URL: `https://www.babanuj.com/product/zaitoune-sweets-maamoul-with-walnut-500g`
  - `Maamoul Growth - Zaitoune Pistachio`
    - Ad ID: `52533919134027`
    - Creative ID: `1682293429740192`
    - URL: `https://www.babanuj.com/product/zaitoune-sweets-pistachio-maamoul-500g`

- Campaign: `Maamoul Growth - Leen Product Traffic`
  - ID: `52533918887827`
  - Objective: `OUTCOME_TRAFFIC`
  - Budget: `$25/day`
  - Status: `PAUSED`
- Ad set: `Broad US - Leen Maamoul Visitors`
  - ID: `52533918905027`
  - Campaign ID: `52533918887827`
  - Optimization: landing page views
  - Billing event: impressions
  - Audience: broad US
  - Status: `PAUSED`
- Leen Maamoul ads:
  - `Maamoul Growth - Leen Date Rings`
    - Ad ID: `52533919111427`
    - Creative ID: `2141424723305564`
    - URL: `https://www.babanuj.com/product/leen-date-rings-maamoul-with-sesame-black-seeds-260g-crunchy-pastry-filled-with-sweet-dates`
  - `Maamoul Growth - Leen Whole Wheat`
    - Ad ID: `52533919134227`
    - Creative ID: `1061963902850251`
    - URL: `https://www.babanuj.com/product/leen-whole-wheat-date-maamoul-240g-traditional-pastry-with-natural-date-filling-rich-nutty-flavor-soft-crumbly-texture-healthier-dessert-with-no-preservatives`
  - `Maamoul Growth - Leen Chocolate`
    - Ad ID: `52533919153227`
    - Creative ID: `1049685537741202`
    - URL: `https://www.babanuj.com/product/leen-dates-maamoul-chocolate-200g-date-paste-cookies-with-chocolate-middle-eastern-sweets-individually-shaped-pieces-great-for-tea-coffee`

The Maamoul campaigns and ad sets are paused, so they are not spending. Newly
created ads showed `IN_PROCESS` immediately after creation, which is Meta's
review/setup state.

## Strategic Positioning

Babanuj should not advertise as a generic sweets shop. The strongest positioning
is specialty Middle Eastern sweets and giftable indulgence, with product-led
angles that are easy to understand in-feed.

Primary hooks:

- Eid al-Adha sweets for gifting, hosting, and coffee service.
- Premium baklava and Turkish sweets for gifting.
- Stuffed dates for hosting, gatherings, and Eid.
- Houston-based Middle Eastern sweets, delivered.
- Gift-ready sweets without needing to visit a specialty market.
- Summer-safe sweets for gifting, hosting, and coffee service.

Primary product lanes:

- Zaitoune: baklava, Turkish delight, petit four, barazek.
- Leen: stuffed dates, chocolate dates, premium date gift boxes.
- Babanuj: house gift boxes, holiday assortments, seasonal drops.

Best-performing launch items:

- Zaitoune Turkish Delight 250g:
  `https://www.babanuj.com/product/zaitoune-turkish-delight-250g`
- Zaitoune Mix Baklava 250g:
  `https://www.babanuj.com/product/zaitoune-mix-baklava-250g`
- Zaitoune Sweets Mix Baklawa Pistachio and Honey 500g:
  `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`
- Milaf Date Cola 240ml:
  `https://www.babanuj.com/product/milaf-date-cola-240ml-8-1-fl-oz`

Use these items as the first paid landing pages unless inventory, margin, or
shipping constraints change.

Seasonal hold:

- Avoid Dubai chocolate and other heat-sensitive chocolate-led offers during
  summer unless cold-pack shipping, delivery timing, and refund risk are
  explicitly accounted for. Do not use Dubai chocolate as a launch angle while
  this hold is active.

## Eid Al-Adha Sprint

Eid al-Adha 2026 is expected around Wednesday, May 27, 2026, with observance
beginning at sundown Tuesday, May 26. Dates can vary by moon sighting and local
community practice.

Because this is close, treat Eid as a fast gifting and hosting sprint rather
than a long learning cycle.

Flight plan:

- Run a 4-day Eid ad flight starting today.
- Keep the campaign simple: one Eid campaign, one broad US ad set, and 4-6 ads
  around the best-performing products.
- Start with ads as `PAUSED` if building through CLI, then activate only after
  final review of budget, creative, destination URLs, and delivery language.

Primary offer framing:

- Eid sweets for the coffee table.
- Gift-ready Turkish delight and baklava.
- Sweets for hosting family after Eid prayer.
- Add Milaf Date Cola as a unique beverage add-on.

Priority landing pages:

- `https://www.babanuj.com/product/zaitoune-turkish-delight-250g`
- `https://www.babanuj.com/product/zaitoune-mix-baklava-250g`
- `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`
- `https://www.babanuj.com/product/milaf-date-cola-240ml-8-1-fl-oz`

Timing:

- Next 4 days: run product-led Eid gifting and hosting ads.
- After the 4-day flight: decide whether to extend through May 25 based on
  spend, CTR, add-to-cart behavior, and fulfillment confidence.
- May 23-25, if extended: shift copy toward "Eid is this week" and
  delivery/availability clarity.
- May 26: use last-call language only if fulfillment can still support it.
- May 27-29: pivot to Eid hosting, visiting family, and post-Eid gatherings.

Do not imply guaranteed Eid delivery unless the operations team has confirmed
the shipping cutoff and service area.

Eid-specific copy should avoid fake discounts, religious overreach, and
hardcoded scarcity. Use practical hosting and gifting language.

## Measurement Prerequisites

Before launching sales campaigns, verify the pixel is firing the key ecommerce
events on `babanuj.com`:

- `PageView`
- `ViewContent`
- `AddToCart`
- `InitiateCheckout`
- `Purchase`

For a sales campaign, optimize for `Purchase` only if purchase volume is present
and reliable. If purchase signal is weak during launch, start with
`AddToCart` or `InitiateCheckout`, then move to `Purchase` once the account has
enough signal.

Recommended measurement improvement:

- Add Meta Conversions API through Shopify or a server-side integration.
- Keep browser pixel and Conversions API deduplicated with event IDs.
- Verify event match quality in Meta Events Manager.

Implemented locally on May 19, 2026:

- Meta browser Pixel is gated by `NEXT_PUBLIC_META_PIXEL_ID`.
- Server-side CAPI endpoint is available at `/api/meta/capi`.
- Events are deduped with shared browser/server `event_id` values.
- Browser + CAPI events wired:
  - `PageView` through the browser Pixel.
  - `ViewContent` on product pages.
  - `AddToCart` after successful Shopify cart mutation.
  - `InitiateCheckout` before redirecting to Shopify checkout.

Production configuration:

- Configure the same env vars in Vercel before deploy:
  - `NEXT_PUBLIC_META_PIXEL_ID=983699467355178`
  - `META_PIXEL_ID=983699467355178`
  - `META_CAPI_ACCESS_TOKEN=<system user token>`
- Because checkout completes on Shopify's hosted checkout domain, purchase
  tracking is handled through a Shopify Customer Events custom pixel. The Next
  storefront can track onsite pre-checkout events, but it cannot observe the
  final Shopify-hosted purchase by itself.

Checkout-side customer-events pixel:

- Source file: `scripts/meta-shopify-checkout-pixel.js`
- Installed in Shopify Admin -> Settings -> Customer events as
  `Meta checkout CAPI`, then connected.
- Purpose: send CAPI events from Shopify-hosted checkout events:
  - `checkout_started` -> `InitiateCheckout`
  - `payment_info_submitted` -> `AddPaymentInfo`
  - `checkout_completed` -> `Purchase`

Reference:

- https://www.facebook.com/business/help/AboutConversionsAPI

## Campaign Structure

Create campaigns as `PAUSED` first. Review them in Ads Manager before
activation.

### 1. Prospecting Sales

Purpose: find new buyers.

- Objective: `outcome_sales`
- Optimization: `purchase` if ready, otherwise `add_to_cart` or
  `initiate_checkout`
- Audience: broad US
- Placements: Advantage+ placements
- Budget: 70% of launch spend
- Creative: best product-led ads for Turkish Delight 250g, Mix Baklava 250g,
  Sweets Mix Baklawa 500g, and Milaf Date Cola

Initial budget:

- Conservative launch: `$35/day`
- Faster learning launch: `$70/day`

### 2. Retargeting Sales

Purpose: convert warm shoppers and social engagers.

- Objective: `outcome_sales`
- Audience:
  - Website visitors, 30 days
  - Product viewers, 30 days
  - Add-to-cart, 30 days
  - Facebook and Instagram engagers, 365 days
- Exclusions:
  - Purchasers, 30 days, if audience is available
- Budget: 20% of launch spend
- Creative: gift urgency, bestsellers, shipping reassurance, product proof

Initial budget:

- Conservative launch: `$10/day`
- Faster learning launch: `$20/day`

### 3. Creative Testing

Purpose: learn which hooks and products deserve more budget.

- Objective: `outcome_sales`
- Audience: broad US
- Placements: Advantage+ placements
- Budget: 10% of launch spend
- Rotate tests weekly, not daily.

Initial budget:

- Conservative launch: `$5/day`
- Faster learning launch: `$10/day`

Test only one main variable per ad:

- Product angle
- Hook
- Format
- Offer framing
- Landing page

## Budget Plan

Recommended first 14 days:

| Launch Mode     | Prospecting | Retargeting |   Testing |      Total |
| --------------- | ----------: | ----------: | --------: | ---------: |
| Conservative    |   `$35/day` |   `$10/day` |  `$5/day` |  `$50/day` |
| Faster learning |   `$70/day` |   `$20/day` | `$10/day` | `$100/day` |

Do not judge performance before the campaigns have enough spend and event
volume. Early decisions should focus on broken tracking, weak CTR, landing page
issues, and obvious creative losers.

## Creative Plan

Launch with 6-10 creatives.

Required formats:

- 3 vertical product videos, 9:16
- 2 unboxing or gift-box videos
- 2 static product closeups
- 1 carousel grouped by category

Creative directions:

- Eid table setup with Turkish delight, baklava, and coffee.
- Eid gift handoff using Zaitoune boxes.
- Zaitoune Turkish Delight box closeups and serving tray shots.
- Zaitoune Mix Baklava texture and pistachio detail.
- Zaitoune Sweets Mix Baklawa 500g as a larger hosting or gifting tray.
- Milaf Date Cola as a curiosity/refreshment hook.
- Gift box reveal on a clean table.
- Dates being served with coffee.
- Turkish delight and petit four assortment closeups.
- Fast product lineup: Turkish delight, baklava, baklawa mix, date cola.

Avoid:

- Fake discounts or sale claims.
- Hardcoded reviews or star ratings.
- Generic stock footage.
- Overly abstract brand ads before product demand is proven.

## Copy Bank

### Eid Sweets

Primary text:

> Bring gift-ready sweets to the Eid table: Turkish delight, baklava, pistachio
> and honey baklawa, and date cola from Babanuj.

Headline:

> Eid Sweets From Babanuj

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/`

### Eid Hosting Tray

Primary text:

> Hosting for Eid? Zaitoune baklawa and Turkish delight make an easy sweet tray
> for coffee, guests, and family visits.

Headline:

> Eid Hosting Sweets

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`

### Turkish Delight 250g

Primary text:

> A giftable box of Zaitoune Turkish delight: soft, fragrant, and ready for the
> coffee table.

Headline:

> Turkish Delight 250g

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/product/zaitoune-turkish-delight-250g`

### Mix Baklava 250g

Primary text:

> A classic Zaitoune baklava mix in a 250g box, made for gifting, hosting, and
> the sweet tray after dinner.

Headline:

> Zaitoune Mix Baklava

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/product/zaitoune-mix-baklava-250g`

### Pistachio And Honey Baklawa 500g

Primary text:

> Pistachio and honey baklawa in a larger 500g sweets mix, ready for gatherings,
> gifting, and weekend coffee.

Headline:

> Pistachio Honey Baklawa

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`

### Milaf Date Cola

Primary text:

> A date-based cola from Milaf: a unique Middle Eastern refreshment to add to
> your sweets order.

Headline:

> Try Milaf Date Cola

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/product/milaf-date-cola-240ml-8-1-fl-oz`

### Baklava Gift

Primary text:

> Premium baklava made for gifting, hosting, and the sweet tray after dinner.

Headline:

> Gift-Ready Baklava

CTA:

> Shop Now

Landing page:

> `https://www.babanuj.com/product/zaitoune-mix-baklava-250g` or
> `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`

### Stuffed Dates

Primary text:

> Stuffed dates, premium date boxes, and sweets for gatherings,
> gifting, and everyday coffee.

Headline:

> Premium Date Boxes

CTA:

> Shop Now

Landing page:

> `/brand/leen`

### Middle Eastern Sweets

Primary text:

> Middle Eastern sweets delivered from Babanuj: baklava, Turkish delight,
> stuffed dates, petit four, and gift boxes.

Headline:

> Shop Babanuj Sweets

CTA:

> Shop Now

Landing page:

> `/`

## Landing Page Plan

Match the ad promise to the page:

- Turkish delight ads should land on
  `https://www.babanuj.com/product/zaitoune-turkish-delight-250g`.
- Baklava ads should land on
  `https://www.babanuj.com/product/zaitoune-mix-baklava-250g` or
  `https://www.babanuj.com/product/zaitoune-sweets-mix-baklawa-pistachio-and-honey-500g`.
- Date cola ads should land on
  `https://www.babanuj.com/product/milaf-date-cola-240ml-8-1-fl-oz`.
- Date ads should land on Leen.
- Broad gift ads should land on a gift-box or homepage collection section.

Every paid landing page should make these obvious above the fold:

- Product image
- Price
- Add to bag
- Shipping/availability context
- Related products

## Catalog Plan

Set up or verify Shopify product catalog sync to Meta. Once product catalog and
pixel events are reliable, test catalog ads for:

- Dynamic retargeting
- Bestsellers carousel
- Giftable product sets
- Brand-based product sets

Reference:

- https://www.facebook.com/business/ads/meta-advantage/advantage-plus-shopping-ads

## CLI Workflow

Load credentials:

```bash
set -a
source .env.local
set +a
```

Verify access:

```bash
meta auth status
meta ads adaccount get "$AD_ACCOUNT_ID"
meta ads campaign list
```

Useful discovery commands:

```bash
meta ads dataset list
meta ads page list --business-id <BUSINESS_ID>
meta ads insights get --date-preset last_30d
```

Create campaigns as paused. Example shape:

```bash
meta ads campaign create \
  --name "BAB | Prospecting | Sales | US | 2026-05" \
  --objective outcome_sales \
  --daily-budget 3500 \
  --status paused
```

For conversion ad sets, use the pixel ID:

```bash
meta ads adset create <CAMPAIGN_ID> \
  --name "BAB | Broad US | Purchase" \
  --optimization-goal offsite_conversions \
  --billing-event impressions \
  --pixel-id <WEBSITE_PIXEL_OR_DATASET_ID> \
  --custom-event-type purchase \
  --targeting-countries US \
  --status paused
```

Creatives require a Facebook Page ID:

```bash
meta ads creative create \
  --name "BAB | Mix Baklava 250g | Static 01" \
  --image ./path/to/image.jpg \
  --page-id <PAGE_ID> \
  --body "A classic Zaitoune baklava mix in a 250g box, made for gifting, hosting, and the sweet tray after dinner." \
  --link-url https://www.babanuj.com/product/zaitoune-mix-baklava-250g \
  --title "Zaitoune Mix Baklava" \
  --call-to-action shop_now
```

## Launch Checklist

- Confirm the correct Facebook Page ID.
- Confirm Instagram actor ID if Instagram identity should be attached.
- Verify pixel events on `babanuj.com`.
- Confirm Shopify catalog sync or defer catalog ads.
- Choose launch mode: `$50/day` or `$100/day`.
- Select 6-10 launch creatives around the four best-performing items.
- Create campaigns, ad sets, creatives, and ads as `PAUSED`.
- Review all ads in Ads Manager.
- Activate only after reviewing URLs, budgets, copy, assets, and tracking.

## First 14-Day Review

Review after meaningful spend, not after a few clicks.

Watch:

- Spend
- CTR
- CPC
- Landing page views
- Add to carts
- Initiated checkouts
- Purchases
- Cost per purchase
- ROAS
- Frequency, especially in retargeting

Decision rules:

- Kill ads with spend and no meaningful click-through or cart activity.
- Keep ads with strong cart or checkout behavior even before purchases.
- Move winning creative angles from Testing into Prospecting.
- Do not scale budget more than 20-30% at a time unless performance is clearly
  stable.
