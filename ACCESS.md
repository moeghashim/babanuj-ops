# Babanuj Command Center — Access Ledger

One place to see what API access we have across channels. Update as access lands.
_Last updated: 2026-06-09_

| Channel | CLI | Status |
|---|---|---|
| Amazon Seller (SP-API) | `amazon-seller-pp-cli` | ✅ **LIVE** — authed; store "Babanuj" on Amazon US/CA/MX/BR |
| Amazon Ads | `amazon-ads-pp-cli` | ⏳ API access submitted 2026-06-09 (~June 12); `auth login` blocked until scope assigned |
| Google Ads | `google-ads-pp-cli` | ✅ **LIVE** — OAuth2'd, Basic access (15k ops/day); 4 accounts accessible |
| Google Search Console | `google-search-console-pp-cli` | ✅ live (authenticated) |

---

## Amazon Seller — SP-API ✅ LIVE (verified 2026-06-09)
- **App:** Babanuj Production (private app, Solution Provider Portal)
- **Org type:** Private Solution Provider (self-integration)
- **Credentials:** `~/.config/amazon-seller-pp-cli/.env` — Client ID + Secret + Refresh Token all set (self-authorized).
- **⚠️ Loading quirk:** this CLI does NOT auto-read the `.env`; it needs the creds as **env vars**. Source them first:
  ```bash
  while IFS='=' read -r k v; do case "$k" in ''|\#*) continue;; esac; export "$k=$v"; done < ~/.config/amazon-seller-pp-cli/.env
  ```
- **Marketplaces (store "Babanuj"):** US `ATVPDKIKX0DER` · CA `A2EUQ1WTGCTBG2` · MX `A1AM78C64UM0Y8` · BR `A2Q3Y263D00KWC` (+ non-Amazon stores channels).

### Roles granted (non-PII)
✅ Product Listing · Pricing · Amazon Fulfillment · Inventory and Order Tracking · Brand Analytics · Finance and Accounting
- *Not granted:* **Selling Partner Insights** (wasn't in the final request) — request later if Sales & Traffic / account-health data needs it.
- *Excluded (PII/unneeded):* Buyer Communication, Buyer Solicitation, Amazon Logistics, Sustainability, AWD.

## Amazon Ads — Advertising API
- **App / LwA:** Babanuj Ads Manager (Client ID `amzn1.application-oa2-client.f22…`)
- **Scope:** `advertising::campaign_management`
- **Credentials:** `~/.config/amazon-ads-pp-cli/.env` (Client ID + Secret set; refresh token pending)
- **Status:** API access submitted 2026-06-09 (~72h → ~June 12). `auth login` returns "unknown scope" until access is assigned to the LwA app at `advertising.amazon.com/developer`.

## Google Ads ✅ LIVE (verified 2026-06-09)
- **Basic access** granted (15k ops/day, production). OAuth2 via Desktop client.
- Creds in `~/.config/google-ads-pp-cli/.env`: developer token + OAuth client id/secret + customer id. OAuth2 refresh token saved by `auth login` → `config.toml`.
- **⚠️ Loading:** source the `.env` for the dev token (env var). `doctor` flags "missing GOOGLE_ADS_ACCESS_TOKEN" — **harmless** (OAuth2 path supersedes it; Auth=configured, Credentials=valid).
- Accessible accounts: `customers/4443273101`, `1604376990`, `4868554799`, `6457175449`. Active account = `GOOGLE_ADS_CUSTOMER_ID` in `.env`.
- Design doc (Basic-access application): `~/babanuj-ops/Babanuj-GoogleAds-API-Design-Document.pdf`.

## Google Search Console
- ✅ Live (`google-search-console-pp-cli`, authenticated under babanuj-gsc).
