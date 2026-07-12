<!--
  Operations log — the operator's manual record of actions taken across channels.

  HOW IT WORKS
  - Append a row to the table below whenever you make a move (pause a campaign,
    change a bid/budget/price, launch something, toggle a product).
  - `operations-sync.py` parses this file, UPSERTs each row into the Command
    Center's `operations` table, and asks Claude to write the "event of the day"
    brief for each day → the `operation_summaries` table.
  - The dashboard then shows: one chart marker per day (Claude's brief + that
    day's actions) and the detailed per-event "Recent operations" panel.

  COLUMNS
  - Date     YYYY-MM-DD (the day you took the action)
  - Platform amazon | google | meta | tiktok | website
  - Type     Pause | Bid | Budget | Launch | Price | Product   (free text ok)
  - Title    short headline of what you did
  - Detail   the why / context (no `|` characters — it breaks the table)
  - Impact   good | warn | bad | neutral   (tints the entry)
  - Marker   yes | no   (yes = annotate it on the revenue chart)

  NOTE: the rows below were migrated from the old demo data so the dashboard
  isn't empty — REVIEW + edit them to reality, and add your real ones on top.
  Keep newest first (order within a day is preserved).
-->

# Operations

| Date | Platform | Type | Title | Detail | Impact | Marker |
|------|----------|------|-------|--------|--------|--------|
| 2026-06-19 | amazon | Pause | Paused SD remarketing campaign | ACOS hit 327% over the trailing 7 days, 0.3x ROAS. Reallocating budget to the SB Eid Gifting campaign. | bad | yes |
| 2026-06-18 | website | Product | Disabled Milaf Date Cola (4pk) | Out of stock on Shopify. Hidden from the storefront and paused in the product feed. Still selling on Amazon. | warn | yes |
| 2026-06-18 | meta | Budget | Raised Eid retargeting budget $5 to $15/day | Ahead of the Eid weekend. Audience: 30-day site visitors + Amazon glance views. | good | yes |
| 2026-06-15 | google | Bid | Raised Google Shopping bid +20% | Impression share was capped at 41%. Targeting higher coverage on branded + maamoul terms. | good | yes |
| 2026-06-12 | amazon | Launch | Launched SB "Eid Gifting" campaign | Sponsored Brands with a dedicated gift-box landing page. Starting budget $10/day. | good | yes |
| 2026-06-09 | tiktok | Launch | Enabled TikTok Shop checkout | Native checkout went live. Seeded 3 Spark ads on Date Cola and Turkish Delight. | good | yes |
| 2026-06-07 | amazon | Bid | Cut SP bids on losing keywords | Reduced bids on 28 keywords above 80% ACOS in the Auto Discovery campaign. | good | yes |
| 2026-06-05 | website | Price | Raised Baklava 500g price $29 to $32 | Margin protection after a cocoa + pistachio cost increase. Monitoring conversion impact. | neutral | no |
| 2026-06-03 | amazon | Price | Matched Turkish Delight buy-box price | Set Amazon price to $19.99 to win the buy box against a reseller listing. | neutral | no |
