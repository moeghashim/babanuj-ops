#!/usr/bin/env python3
"""shopify-sync.py — Shopify (Babanuj store) → Command Center Postgres.

Standalone extractor for the WEBSITE channel. Unlike posthog-marketing-sync.py
(which dual-writes PostHog + Postgres for the *marketing* sources), Shopify is
store data: there is NO PostHog path here — it writes Postgres ONLY.

Source of truth for the schema:
  ~/babanuj-command-center/db/migrations/0001_init.sql
UPSERT helpers (reused, idempotent ON-CONFLICT):
  ~/babanuj-ops/lib/pg_sync.py

WHAT IT WRITES
  ORDERS  (windowed, default --days 30) ──► web_kpis_daily   (one row per calendar day)
            date     = order createdAt, in the SHOP timezone (calendar-day bucket)
            revenue  = sum(currentTotalPriceSet.shopMoney.amount)
            orders   = count(orders)
            units    = sum(lineItem.quantity)
            sessions = NULL  (needs the Analytics/ShopifyQL API; client_credentials
                              does not grant it — left null on purpose, see below)
          ──► product_metrics_daily (platform='website', per product per day)
            units    = sum(lineItem.quantity)   for that product/day
            sales    = sum(lineItem quantity * variant price)  [discount-naive; see note]
  PRODUCTS + variants ──► products            (id = slug(handle), name, subtitle)
                      ──► platform_listings   (platform='website',
                            external_listing_id = Shopify product GID,
                            selling_price       = product min-variant price,
                            status = 'active' if product ACTIVE else 'disabled')

web_kpis_daily OVERLAP (documented, intentional — DO NOT "fix" by editing the
other script):  posthog-marketing-sync.py ALSO upserts web_kpis_daily today, from
the Amazon Seller store rollup (kind="store"). That is being reconciled separately
(Amazon will move to a marketplace table). Both scripts use the SAME idempotent
pg_sync.upsert_web_kpis(...), and both pass ad_spend=None (ad_spend is owned by
the channel-spend rollup, never by a store source). So whichever runs LAST wins
the revenue/orders/units for a given date. Once Amazon moves off web_kpis_daily,
this script is the sole WEBSITE source. This script does NOT modify
posthog-marketing-sync.py.

AUTH
  client_credentials grant each run (token cached for the run, ~24h TTL):
    POST https://$SHOPIFY_STORE_DOMAIN/admin/oauth/access_token
         {client_id, client_secret, grant_type:"client_credentials"}
      -> {access_token, scope, expires_in}
  Header on every Admin call: X-Shopify-Access-Token: <access_token>
  Creds: ~/.config/shopify-pp-cli/.env (SHOPIFY_STORE_DOMAIN / _CLIENT_ID / _CLIENT_SECRET)

RATE LIMITS
  GraphQL Admin API (2026-04). Each response carries
  extensions.cost.throttleStatus {maximumAvailable, currentlyAvailable, restoreRate}.
  We read it after every call and, when currentlyAvailable would dip below a
  safety floor, sleep enough for the leaky bucket to refill (currentlyAvailable +=
  restoreRate per second). Plus exponential backoff + Retry-After on HTTP 429/5xx
  and on GraphQL THROTTLED userErrors. Orders are paged with cursor pagination
  (pageInfo.endCursor) at 100/page. No bulk-operations job is needed for the
  default 30-day window; for very large historical backfills see the --days note
  in the report (cost-throttle pacing handles tens of thousands of orders fine).

CONSTRAINTS
  - READ-ONLY against Shopify: only queries (orders/products), never a mutation.
  - Writes to LOCAL Postgres only (DATABASE_URL). Never a prod DB.
  - No secrets committed; creds read from ~/.config at runtime.

USAGE
    DATABASE_URL=postgres://bcc:bcc@localhost:5433/bcc \
        /usr/bin/python3 shopify-sync.py --days 7 --verbose
    # incremental cron (only orders touched since a timestamp):
    ... shopify-sync.py --updated-since 2026-06-20T00:00:00Z
    # dry run (pull + aggregate, print, NO writes):
    ... shopify-sync.py --days 7 --dry-run --verbose
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone

HOME = os.path.expanduser("~")
SHOPIFY_ENV = os.path.join(HOME, ".config", "shopify-pp-cli", ".env")
API_VERSION = "2026-04"
PLATFORM = "website"           # platform_listings.platform / product_metrics_daily.platform
SOURCE = "shopify"             # sync_runs.source label
ORDERS_PAGE = 100              # orders per page (max 250; 100 keeps query cost modest)
COST_FLOOR = 200              # refill the leaky bucket before available dips under this

# pg_sync lives in ./lib — import it the same way the marketing sync does.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import pg_sync as _pg_sync
    _PG_IMPORT_ERR = None
except Exception as ex:  # pragma: no cover
    _pg_sync = None
    _PG_IMPORT_ERR = ex


# --------------------------------------------------------------- small utils ---
def log(*a):
    print(*a, file=sys.stderr, flush=True)


def vlog(verbose, *a):
    if verbose:
        log(*a)


def parse_kv(path):
    """Read a k=v .env file (mirrors posthog-marketing-sync.parse_kv)."""
    d = {}
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("[") and "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'").strip()
    return d


def slugify(text: str) -> str:
    """Canonical product id from a Shopify handle (already slug-ish) — keep
    [a-z0-9-], collapse the rest. The handle IS the natural slug, so this is
    mostly a guard for stray characters."""
    out = []
    prev_dash = False
    for ch in (text or "").strip().lower():
        if ch.isalnum():
            out.append(ch)
            prev_dash = False
        elif ch in (" ", "-", "_", "/"):
            if not prev_dash:
                out.append("-")
                prev_dash = True
    s = "".join(out).strip("-")
    return s or "product"


def daterange(days: int, tz=None):
    """Window = the last `days` calendar days through yesterday (today is partial).
    Anchored to *yesterday in the shop timezone* so the window boundary, Shopify's
    (shop-local) created_at filter, and our calendar-day bucketing all agree.
    Falls back to UTC when tz is None."""
    now = datetime.now(tz) if tz is not None else datetime.now(timezone.utc)
    end = now.date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    return start, end


# ---------------------------------------------------------------- shopify io ---
class Shopify:
    """Thin GraphQL Admin client: client_credentials token (cached for the run)
    + cost-aware throttling + 429/5xx backoff. Read-only by construction."""

    def __init__(self, verbose: bool = False):
        env = parse_kv(SHOPIFY_ENV)
        try:
            self.domain = env["SHOPIFY_STORE_DOMAIN"]
            self.client_id = env["SHOPIFY_CLIENT_ID"]
            self.client_secret = env["SHOPIFY_CLIENT_SECRET"]
        except KeyError as e:
            raise RuntimeError(f"missing {e} in {SHOPIFY_ENV}")
        self.verbose = verbose
        self._token = None
        self.shop_name = None
        self.shop_tz = None         # IANA tz string, e.g. "America/New_York"
        self._gql_url = f"https://{self.domain}/admin/api/{API_VERSION}/graphql.json"

    # -- auth ---------------------------------------------------------------
    def token(self) -> str:
        if self._token:
            return self._token
        body = json.dumps({
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "grant_type": "client_credentials",
        }).encode()
        req = urllib.request.Request(
            f"https://{self.domain}/admin/oauth/access_token",
            data=body, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=30) as r:
            tok = json.loads(r.read().decode())
        self._token = tok["access_token"]
        vlog(self.verbose, f"[auth] token OK; scope={tok.get('scope')} "
                           f"expires_in={tok.get('expires_in')}s")
        return self._token

    # -- core call with throttle handling -----------------------------------
    def gql(self, query: str, variables: dict | None = None, _attempt: int = 0) -> dict:
        payload = {"query": query}
        if variables:
            payload["variables"] = variables
        req = urllib.request.Request(
            self._gql_url, data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json",
                     "X-Shopify-Access-Token": self.token()},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                data = json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            # 429 throttle or 5xx → exponential backoff (respect Retry-After).
            if e.code in (429, 500, 502, 503, 504) and _attempt < 6:
                retry_after = e.headers.get("Retry-After")
                wait = float(retry_after) if retry_after else min(2 ** _attempt, 30)
                log(f"[shopify] HTTP {e.code} — backoff {wait:.1f}s "
                    f"(attempt {_attempt + 1})")
                time.sleep(wait)
                return self.gql(query, variables, _attempt + 1)
            body = e.read().decode()[:500]
            raise RuntimeError(f"Shopify HTTP {e.code}: {body}")
        except urllib.error.URLError as e:
            if _attempt < 6:
                wait = min(2 ** _attempt, 30)
                log(f"[shopify] network error {e} — backoff {wait:.1f}s")
                time.sleep(wait)
                return self.gql(query, variables, _attempt + 1)
            raise

        # GraphQL-level THROTTLED (rare; cost guard usually prevents it).
        errs = data.get("errors")
        if errs:
            codes = {(e.get("extensions") or {}).get("code") for e in errs}
            if "THROTTLED" in codes and _attempt < 6:
                wait = min(2 ** _attempt, 30)
                log(f"[shopify] GraphQL THROTTLED — backoff {wait:.1f}s")
                time.sleep(wait)
                return self.gql(query, variables, _attempt + 1)
            raise RuntimeError(f"GraphQL errors: {json.dumps(errs)[:500]}")

        self._respect_cost(data)
        return data

    def _respect_cost(self, data: dict):
        """Leaky-bucket pacing: if the points left would dip under COST_FLOOR,
        sleep long enough for the bucket to refill past the floor."""
        cost = (data.get("extensions") or {}).get("cost") or {}
        ts = cost.get("throttleStatus") or {}
        avail = ts.get("currentlyAvailable")
        restore = ts.get("restoreRate") or 1000.0
        if avail is not None and avail < COST_FLOOR and restore > 0:
            need = (COST_FLOOR - avail) / restore
            vlog(self.verbose, f"[shopify] cost {avail:.0f} < floor {COST_FLOOR}; "
                               f"sleep {need:.2f}s to refill")
            time.sleep(min(need, 5.0))

    # -- shop metadata (name + tz for calendar bucketing) -------------------
    def fetch_shop(self):
        d = self.gql("{ shop { name ianaTimezone currencyCode } }")
        shop = d["data"]["shop"]
        self.shop_name = shop.get("name")
        self.shop_tz = shop.get("ianaTimezone")
        return shop


# ----------------------------------------------------------- pulls + aggregate ---
ORDERS_QUERY = """
query($q: String!, $cursor: String) {
  orders(first: %d, after: $cursor, query: $q,
         sortKey: CREATED_AT, reverse: false) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        createdAt
        test
        displayFinancialStatus
        currentTotalPriceSet { shopMoney { amount } }
        lineItems(first: 100) {
          edges {
            node {
              quantity
              product { id handle title }
              variant { id price }
            }
          }
        }
      }
    }
  }
}
""" % ORDERS_PAGE


def _shop_day(created_at: str, tz) -> str:
    """Bucket an ISO8601 'Z' timestamp into a calendar day in the shop tz."""
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if tz is not None:
        dt = dt.astimezone(tz)
    return dt.date().isoformat()


def pull_orders(sh: "Shopify", *, days: int, updated_since: str | None, verbose: bool):
    """Page through orders in the window, aggregating two grains:
       day_kpis[date]            -> {revenue, orders, units}   (for web_kpis_daily)
       prod_daily[(pid,date)]    -> {product_id, name, subtitle, units, sales}
                                     (for products + product_metrics_daily 'website')
    Returns (day_kpis, prod_daily, window_dates, n_orders).
    """
    # Resolve shop tz once (best-effort; falls back to UTC).
    tz = None
    try:
        from zoneinfo import ZoneInfo
        if sh.shop_tz:
            tz = ZoneInfo(sh.shop_tz)
    except Exception:
        tz = None

    if updated_since:
        # Incremental cron mode: everything touched since a timestamp.
        q = f"updated_at:>='{updated_since}'"
        vlog(verbose, f"[orders] incremental: {q}")
    else:
        start, end = daterange(days, tz)
        # created_at window, inclusive of `end` (use < end+1 day, shop-local).
        end_excl = (end + timedelta(days=1)).isoformat()
        q = f"created_at:>='{start.isoformat()}' created_at:<'{end_excl}'"
        vlog(verbose, f"[orders] window {start}..{end} (query: {q})")

    day_kpis: dict[str, dict] = {}
    prod_daily: dict[tuple, dict] = {}
    window_dates: set[str] = set()
    n_orders = 0
    cursor = None
    page = 0

    while True:
        page += 1
        data = sh.gql(ORDERS_QUERY, {"q": q, "cursor": cursor})
        conn = data["data"]["orders"]
        for edge in conn["edges"]:
            o = edge["node"]
            if o.get("test"):
                continue  # skip Shopify test orders
            d = _shop_day(o["createdAt"], tz)
            # In incremental mode an order may have been created before the
            # window we care about but updated recently — keep it; its day is
            # whatever createdAt says, restatement is idempotent.
            amount = float(((o.get("currentTotalPriceSet") or {})
                            .get("shopMoney") or {}).get("amount") or 0)
            dk = day_kpis.setdefault(d, {"revenue": 0.0, "orders": 0, "units": 0})
            dk["revenue"] += amount
            dk["orders"] += 1
            window_dates.add(d)
            n_orders += 1

            for le in o["lineItems"]["edges"]:
                li = le["node"]
                qty = int(li.get("quantity") or 0)
                dk["units"] += qty
                prod = li.get("product")
                if not prod:
                    continue  # deleted product / custom line item
                pid = slugify(prod.get("handle") or prod.get("id"))
                var = li.get("variant") or {}
                price = float(var.get("price") or 0)
                pd = prod_daily.setdefault((pid, d), {
                    "product_id": pid,
                    "name": prod.get("title") or pid,
                    "subtitle": "",
                    "units": 0, "sales": 0.0})
                pd["units"] += qty
                pd["sales"] += qty * price

        vlog(verbose, f"[orders] page {page}: cumulative orders={n_orders}")
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]

    return day_kpis, prod_daily, window_dates, n_orders


PRODUCTS_QUERY = """
query($cursor: String) {
  products(first: 100, after: $cursor, sortKey: TITLE) {
    pageInfo { hasNextPage endCursor }
    edges {
      node {
        id
        handle
        title
        status
        priceRangeV2 { minVariantPrice { amount } }
        variants(first: 1) { edges { node { id price barcode } } }
      }
    }
  }
}
"""


def pull_products(sh: "Shopify", *, verbose: bool):
    """All products → list of dicts for products + platform_listings('website')."""
    out = []
    cursor = None
    page = 0
    while True:
        page += 1
        data = sh.gql(PRODUCTS_QUERY, {"cursor": cursor})
        conn = data["data"]["products"]
        for edge in conn["edges"]:
            p = edge["node"]
            pid = slugify(p.get("handle") or p["id"])
            status_raw = (p.get("status") or "").upper()  # ACTIVE/DRAFT/ARCHIVED
            status = "active" if status_raw == "ACTIVE" else "disabled"
            price = ((p.get("priceRangeV2") or {})
                     .get("minVariantPrice") or {}).get("amount")
            v0 = (p.get("variants") or {}).get("edges") or []
            barcode = (v0[0]["node"].get("barcode") if v0 else None) or None
            out.append({
                "product_id": pid,
                "name": p.get("title") or pid,
                "subtitle": "",
                "barcode": barcode,
                "external_listing_id": p["id"],          # Shopify product GID
                "selling_price": (None if price is None else float(price)),
                "status": status,
                "status_raw": status_raw,
            })
        vlog(verbose, f"[products] page {page}: cumulative={len(out)}")
        if not conn["pageInfo"]["hasNextPage"]:
            break
        cursor = conn["pageInfo"]["endCursor"]
    return out


# --------------------------------------------------------------------- write ---
def write_postgres(day_kpis, prod_daily, products, *, verbose: bool):
    """Idempotent UPSERT into the Command Center schema (Postgres only).

    Mapping:
      day_kpis[date]            -> web_kpis_daily(date / revenue, orders, units;
                                                  ad_spend=None, sessions=None)
      products[*]               -> products(id,name,subtitle,barcode)
                                 + platform_listings(platform='website',
                                       external_listing_id, selling_price, status)
      prod_daily[(pid,date)]    -> product_metrics_daily(platform='website',
                                       date / units, sales)
                                   (parent product/listing ensured first; FK-safe)
    """
    if _pg_sync is None:
        return {"skipped": f"pg_sync import failed: {_PG_IMPORT_ERR!r}"}
    pg = _pg_sync.PgSync.from_env(verbose=verbose)
    if pg is None:
        return {"skipped": "DATABASE_URL not set — nothing written"}

    counts = {"web_kpis": 0, "products": 0, "listings": 0,
              "product_metrics": 0, "sync_runs": 0}
    # Catalog product ids (have a real listing). product_metrics for products NOT
    # in the catalog pull (e.g. a since-deleted product still in an order) would
    # trip the FK, so we ensure a minimal parent for those too.
    catalog_ids = {p["product_id"] for p in products}

    try:
        with pg:
            # 1) PRODUCTS + website listings
            for p in products:
                pg.ensure_product(product_id=p["product_id"], name=p["name"],
                                  subtitle=p["subtitle"], barcode=p["barcode"])
                counts["products"] += 1
                pg.upsert_platform_listing(
                    product_id=p["product_id"], platform=PLATFORM,
                    external_listing_id=p["external_listing_id"],
                    selling_price=p["selling_price"], status=p["status"])
                counts["listings"] += 1

            # 2) WEBSITE daily KPIs. ad_spend=None (owned by channel rollup),
            #    sessions=None (Analytics API not covered by client_credentials).
            for d, k in sorted(day_kpis.items()):
                pg.upsert_web_kpis(date=d, revenue=k["revenue"], ad_spend=None,
                                   orders=k["orders"], units=k["units"],
                                   sessions=None)
                counts["web_kpis"] += 1

            # 3) per-product/day website metrics (ensure FK parent if needed)
            for (pid, d), pd in sorted(prod_daily.items()):
                if pid not in catalog_ids:
                    pg.ensure_product(product_id=pid, name=pd["name"],
                                      subtitle=pd["subtitle"])
                    pg.upsert_platform_listing(product_id=pid, platform=PLATFORM,
                                               status="disabled")
                    catalog_ids.add(pid)
                pg.upsert_product_metrics(product_id=pid, platform=PLATFORM,
                                          date=d, units=pd["units"],
                                          sales=pd["sales"])
                counts["product_metrics"] += 1

            pg.log_sync_run(SOURCE, ok=True)
            counts["sync_runs"] += 1
        return {"ok": True, "upserts": counts}
    except Exception as ex:
        # Try to still record the failed run (best-effort, separate txn).
        try:
            with pg:
                pg.log_sync_run(SOURCE, ok=False)
        except Exception:
            pass
        log(f"[postgres] write FAILED: {ex}")
        return {"error": str(ex)[:400]}


# ---------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description="Shopify → Command Center Postgres.")
    ap.add_argument("--days", type=int, default=30,
                    help="window size in calendar days (default 30; through yesterday)")
    ap.add_argument("--updated-since", default=None,
                    help="ISO8601 timestamp (e.g. 2026-06-20T00:00:00Z) for "
                         "incremental cron pulls (orders updated_at >=); overrides --days")
    ap.add_argument("--no-products", action="store_true",
                    help="skip the products/listings pull (orders only)")
    ap.add_argument("--dry-run", action="store_true",
                    help="pull + aggregate + print, but DO NOT write Postgres")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    sh = Shopify(verbose=args.verbose)
    shop = sh.fetch_shop()
    log(f"[shopify] store={shop.get('name')} tz={shop.get('ianaTimezone')} "
        f"currency={shop.get('currencyCode')} api={API_VERSION}")

    # ORDERS
    day_kpis, prod_daily, window_dates, n_orders = pull_orders(
        sh, days=args.days, updated_since=args.updated_since, verbose=args.verbose)
    log(f"[orders] {n_orders} orders over {len(day_kpis)} day(s); "
        f"{len(prod_daily)} product-day metric rows")

    # PRODUCTS
    products = []
    if not args.no_products:
        products = pull_products(sh, verbose=args.verbose)
        active = sum(1 for p in products if p["status"] == "active")
        log(f"[products] {len(products)} products ({active} active / "
            f"{len(products) - active} disabled)")

    if args.dry_run:
        sample_days = sorted(day_kpis.items())[-7:]
        print(json.dumps({
            "dry_run": True,
            "orders": n_orders,
            "day_kpis_tail": [
                {"date": d, **{k: round(v, 2) if isinstance(v, float) else v
                               for k, v in m.items()}}
                for d, m in sample_days],
            "products": len(products),
            "product_metric_rows": len(prod_daily),
        }, indent=2))
        log("[dry-run] no Postgres writes.")
        return

    res = write_postgres(day_kpis, prod_daily, products, verbose=args.verbose)
    print(json.dumps(res, indent=2))
    if res.get("error"):
        sys.exit(1)


if __name__ == "__main__":
    main()
