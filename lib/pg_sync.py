"""pg_sync.py — UPSERT helpers for the Babanuj Command Center Postgres.

Second sink for the marketing extractors (posthog-marketing-sync.py). PostHog
remains the primary, restatement-via-argMax store; THIS writes the same daily
numbers into the Command Center's relational schema so the dashboard can read
plain SQL.

Schema (source of truth): ~/babanuj-command-center/db/migrations/0001_init.sql
  - channels(key, ...)                + channel_metrics_daily(channel_key, date / spend,sales,impressions,clicks)
  - campaigns(id, external_id, name, platform, status, sort_order)
                                       + campaign_metrics_daily(campaign_id, date / spend,sales,impressions,clicks,orders)
  - web_kpis_daily(date / revenue,ad_spend,orders,units,sessions)
  - seo_metrics_daily(date / clicks,impressions,position)
  - seo_queries(captured_date, query / clicks,impressions,position)
  - products(id,...) + platform_listings(product_id,platform / external_listing_id,selling_price,status)
                     + product_metrics_daily(product_id,platform,date / units,sales)
  - sync_runs(source, finished_at, ok)

DESIGN NOTES
  - Every write is idempotent: ON CONFLICT (<pk>) DO UPDATE so re-sending the
    trailing window (Amazon's 14-day attribution restatement) overwrites the
    older value — mirrors the PostHog argMax behaviour, but with a plain UPSERT.
  - FK-safe: parent rows (channels / campaigns / products) are ensured BEFORE
    their *_metrics_daily children. Channel/campaign metric upserts call the
    parent-ensure helpers automatically.
  - Money/ratios are passed straight through; the DB columns are `numeric`.
    ACOS/ROAS are DERIVED in the app at query time — never stored here.
  - This module imports psycopg2 lazily so importing it never crashes a caller
    that only wants the PostHog path; connect() raises a clear message if the
    driver or DATABASE_URL is missing.

USAGE
    from lib import pg_sync
    pg = pg_sync.PgSync.from_env()        # None if DATABASE_URL unset
    if pg:
        with pg:                          # opens a single connection/transaction
            pg.upsert_channel_metrics(channel_key="amazon_sp", date="2026-06-18",
                                      spend=12.3, sales=80.0, impressions=900, clicks=12)
            pg.log_sync_run("amazon_ads", ok=True)
"""
from __future__ import annotations

import os
import sys
from typing import Optional


def _require_psycopg2():
    try:
        import psycopg2  # noqa: F401
        import psycopg2.extras  # noqa: F401
        return psycopg2
    except ImportError as ex:  # pragma: no cover - environment dependent
        raise RuntimeError(
            "psycopg2 is not installed. Install it for THIS interpreter:\n"
            f"    {sys.executable} -m pip install --user psycopg2-binary\n"
            f"(original error: {ex})"
        )


# Map a free-form ad-channel status string (Amazon ENABLED/PAUSED/ARCHIVED,
# Google ENABLED/PAUSED/REMOVED, etc.) to the campaigns.status CHECK domain.
def normalize_campaign_status(raw: Optional[str]) -> str:
    s = (raw or "").strip().upper()
    if s in ("PAUSED", "DISABLED", "REMOVED", "ARCHIVED"):
        return "Paused"
    return "Active"  # ENABLED / unknown / missing → Active (safe default)


def _num(v) -> float:
    try:
        return float(v or 0)
    except (TypeError, ValueError):
        return 0.0


def _int(v) -> int:
    try:
        return int(round(_num(v)))
    except (TypeError, ValueError):
        return 0


class PgSync:
    """A thin, idempotent UPSERT facade over the Command Center schema.

    Open it as a context manager to wrap a whole sync in one transaction:
    everything commits on clean exit, rolls back on exception.
    """

    def __init__(self, dsn: str, verbose: bool = False):
        self.dsn = dsn
        self.verbose = verbose
        self._conn = None
        self._psycopg2 = _require_psycopg2()

    # -- lifecycle -----------------------------------------------------------
    @classmethod
    def from_env(cls, verbose: bool = False) -> Optional["PgSync"]:
        """Return a PgSync if DATABASE_URL is set, else None (dual-write off)."""
        dsn = os.environ.get("DATABASE_URL")
        if not dsn:
            return None
        return cls(dsn, verbose=verbose)

    def connect(self):
        if self._conn is None or self._conn.closed:
            self._conn = self._psycopg2.connect(self.dsn)
        return self._conn

    def __enter__(self) -> "PgSync":
        self.connect()
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._conn is None:
            return False
        try:
            if exc_type is None:
                self._conn.commit()
            else:
                self._conn.rollback()
        finally:
            self._conn.close()
            self._conn = None
        return False  # never swallow exceptions

    def _log(self, *a):
        if self.verbose:
            print(*a, file=sys.stderr, flush=True)

    def _exec(self, sql: str, params):
        with self.connect().cursor() as cur:
            cur.execute(sql, params)

    # -- parent-row ensures (FK safety) --------------------------------------
    def ensure_channel(self, key: str, name: str, platform: str,
                       status: str = "active", sort_order: int = 0):
        """Insert a channel if missing; never clobbers an operator-set name/status."""
        self._exec(
            """
            insert into channels (key, name, platform, status, sort_order)
            values (%s, %s, %s, %s, %s)
            on conflict (key) do nothing
            """,
            (key, name, platform, status, sort_order),
        )

    def ensure_campaign(self, campaign_id: str, name: str, platform: str,
                        external_id: Optional[str] = None,
                        status: str = "Active", sort_order: int = 0):
        """Upsert a campaign. Refreshes name/status/external_id so renames and
        pause/enable flips from the ad platform flow through; sort_order is only
        set on first insert (preserves any manual display ordering)."""
        self._exec(
            """
            insert into campaigns (id, external_id, name, platform, status, sort_order)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (id) do update set
              external_id = coalesce(excluded.external_id, campaigns.external_id),
              name        = excluded.name,
              platform    = excluded.platform,
              status      = excluded.status
            """,
            (campaign_id, external_id, name, platform,
             normalize_campaign_status(status), sort_order),
        )

    def ensure_product(self, product_id: str, name: str, subtitle: str = "",
                       barcode: Optional[str] = None, sort_order: int = 0):
        self._exec(
            """
            insert into products (id, name, subtitle, barcode, sort_order)
            values (%s, %s, %s, %s, %s)
            on conflict (id) do update set
              name     = excluded.name,
              subtitle = excluded.subtitle,
              barcode  = coalesce(excluded.barcode, products.barcode)
            """,
            (product_id, name, subtitle, barcode, sort_order),
        )

    def upsert_platform_listing(self, product_id: str, platform: str,
                                external_listing_id: Optional[str] = None,
                                selling_price=None, status: str = "active",
                                status_note: Optional[str] = None):
        self._exec(
            """
            insert into platform_listings
              (product_id, platform, external_listing_id, selling_price, status, status_note, updated_at)
            values (%s, %s, %s, %s, %s, %s, now())
            on conflict (product_id, platform) do update set
              external_listing_id = coalesce(excluded.external_listing_id, platform_listings.external_listing_id),
              selling_price       = coalesce(excluded.selling_price, platform_listings.selling_price),
              status              = excluded.status,
              status_note         = coalesce(excluded.status_note, platform_listings.status_note),
              updated_at          = now()
            """,
            (product_id, platform, external_listing_id,
             (None if selling_price is None else round(_num(selling_price), 2)),
             status, status_note),
        )

    # -- metric upserts ------------------------------------------------------
    def upsert_channel_metrics(self, channel_key: str, date: str, spend=0,
                               sales=0, impressions=0, clicks=0,
                               channel_name: Optional[str] = None,
                               platform: Optional[str] = None):
        """One channel/day rollup. Ensures the parent channel row first so a
        brand-new channel (e.g. tiktok_shop) can't trip the FK on a fresh DB."""
        if channel_name or platform:
            self.ensure_channel(channel_key, channel_name or channel_key,
                                platform or "amazon")
        self._exec(
            """
            insert into channel_metrics_daily
              (channel_key, date, spend, sales, impressions, clicks)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (channel_key, date) do update set
              spend       = excluded.spend,
              sales       = excluded.sales,
              impressions = excluded.impressions,
              clicks      = excluded.clicks
            """,
            (channel_key, date, round(_num(spend), 2), round(_num(sales), 2),
             _int(impressions), _int(clicks)),
        )

    def upsert_campaign_metrics(self, campaign_id: str, date: str, spend=0,
                                sales=0, impressions=0, clicks=0, orders=0):
        """One campaign/day row. Caller must have ensure_campaign'd it (or pass
        through upsert_campaign + this). Does NOT auto-ensure to avoid guessing
        a name/platform here."""
        self._exec(
            """
            insert into campaign_metrics_daily
              (campaign_id, date, spend, sales, impressions, clicks, orders)
            values (%s, %s, %s, %s, %s, %s, %s)
            on conflict (campaign_id, date) do update set
              spend       = excluded.spend,
              sales       = excluded.sales,
              impressions = excluded.impressions,
              clicks      = excluded.clicks,
              orders      = excluded.orders
            """,
            (campaign_id, date, round(_num(spend), 2), round(_num(sales), 2),
             _int(impressions), _int(clicks), _int(orders)),
        )

    def upsert_campaign(self, campaign_id: str, name: str, platform: str, date: str,
                        spend=0, sales=0, impressions=0, clicks=0, orders=0,
                        external_id: Optional[str] = None, status: str = "Active",
                        sort_order: int = 0):
        """Convenience: ensure the campaign row, then upsert its day metrics."""
        self.ensure_campaign(campaign_id, name, platform, external_id=external_id,
                             status=status, sort_order=sort_order)
        self.upsert_campaign_metrics(campaign_id, date, spend=spend, sales=sales,
                                     impressions=impressions, clicks=clicks, orders=orders)

    def upsert_web_kpis(self, date: str, revenue=None, ad_spend=None, orders=None,
                        units=None, sessions=None):
        """Partial upsert of the daily store KPIs. Any argument left as None is
        NOT overwritten (COALESCE keeps the existing value) — this lets the
        amazon_seller store path set revenue/orders/units/sessions WITHOUT
        clobbering ad_spend (which is owned by the channel-spend rollup), and
        vice-versa. New rows default un-passed numerics to 0.

        Postgres note: psycopg2 sends Python None as a true NULL, so the
        `coalesce(excluded.col, web_kpis_daily.col)` keeps the prior value; on a
        fresh insert there's no prior row, so we coalesce to 0 there instead."""
        self._exec(
            """
            insert into web_kpis_daily (date, revenue, ad_spend, orders, units, sessions)
            values (%s, coalesce(%s,0), coalesce(%s,0), coalesce(%s,0), coalesce(%s,0), %s)
            on conflict (date) do update set
              revenue  = coalesce(excluded.revenue,  web_kpis_daily.revenue),
              ad_spend = coalesce(excluded.ad_spend, web_kpis_daily.ad_spend),
              orders   = coalesce(excluded.orders,   web_kpis_daily.orders),
              units    = coalesce(excluded.units,    web_kpis_daily.units),
              sessions = coalesce(excluded.sessions, web_kpis_daily.sessions)
            """,
            (date,
             (None if revenue is None else round(_num(revenue), 2)),
             (None if ad_spend is None else round(_num(ad_spend), 2)),
             (None if orders is None else _int(orders)),
             (None if units is None else _int(units)),
             (None if sessions is None else _int(sessions))),
        )

    def upsert_web_ad_spend_from_channels(self, dates):
        """Recompute web_kpis_daily.ad_spend as SUM(channel_metrics_daily.spend)
        per day, for the given dates. Keeps the dashboard's spend line in sync
        with the per-channel truth after channel upserts land. revenue/orders/etc
        are preserved (this only touches ad_spend; rows are created if missing)."""
        if not dates:
            return
        with self.connect().cursor() as cur:
            cur.execute(
                """
                insert into web_kpis_daily (date, ad_spend)
                select date, round(sum(spend), 2)
                from channel_metrics_daily
                where date = any(%s::date[])
                group by date
                on conflict (date) do update set ad_spend = excluded.ad_spend
                """,
                (list(dates),),
            )

    def upsert_marketplace_metrics(self, platform: str, date: str, revenue=0,
                                   orders=0, units=0, sessions=None):
        """Per-platform/day MARKETPLACE store rollup (Amazon Seller now, TikTok
        Shop later) → marketplace_metrics_daily. Kept SEPARATE from web_kpis_daily
        (the Shopify WEBSITE store) so marketplace revenue ADDS to the website
        total in the DAL instead of clobbering it. (#16)"""
        self._exec(
            """
            insert into marketplace_metrics_daily (platform, date, revenue, orders, units, sessions)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (platform, date) do update set
              revenue  = excluded.revenue,
              orders   = excluded.orders,
              units    = excluded.units,
              sessions = excluded.sessions
            """,
            (platform, date, round(_num(revenue), 2), _int(orders), _int(units),
             (None if sessions is None else _int(sessions))),
        )

    def upsert_product_metrics(self, product_id: str, platform: str, date: str,
                               units=0, sales=0):
        """Per-product/platform/day. Parent product + listing must exist; on the
        Amazon-Seller path we ensure them with the ASIN as id/external id first."""
        self._exec(
            """
            insert into product_metrics_daily (product_id, platform, date, units, sales)
            values (%s, %s, %s, %s, %s)
            on conflict (product_id, platform, date) do update set
              units = excluded.units,
              sales = excluded.sales
            """,
            (product_id, platform, date, _int(units), round(_num(sales), 2)),
        )

    def upsert_seo_metrics(self, date: str, clicks=0, impressions=0, position=None):
        self._exec(
            """
            insert into seo_metrics_daily (date, clicks, impressions, position)
            values (%s, %s, %s, %s)
            on conflict (date) do update set
              clicks      = excluded.clicks,
              impressions = excluded.impressions,
              position    = excluded.position
            """,
            (date, _int(clicks), _int(impressions),
             (None if position is None else round(_num(position), 2))),
        )

    def upsert_seo_query(self, captured_date: str, query: str, clicks=0,
                         impressions=0, position=None):
        self._exec(
            """
            insert into seo_queries (captured_date, query, clicks, impressions, position)
            values (%s, %s, %s, %s, %s)
            on conflict (captured_date, query) do update set
              clicks      = excluded.clicks,
              impressions = excluded.impressions,
              position    = excluded.position
            """,
            (captured_date, query, _int(clicks), _int(impressions),
             (None if position is None else round(_num(position), 2))),
        )

    # -- operations (manual log parsed from Operations.md) -------------------
    def upsert_operation(self, op_id: str, occurred_at: str, platform: str,
                         type_: str, title: str, detail: str = "",
                         impact: str = "neutral", is_marker: bool = False):
        """One operator action → operations. op_id is deterministic (date+title)
        so re-runs UPSERT instead of duplicating. (#19)"""
        self._exec(
            """
            insert into operations (id, occurred_at, platform, type, title, detail, impact, is_marker)
            values (%s, %s, %s, %s, %s, %s, %s, %s)
            on conflict (id) do update set
              occurred_at = excluded.occurred_at,
              platform    = excluded.platform,
              type        = excluded.type,
              title       = excluded.title,
              detail      = excluded.detail,
              impact      = excluded.impact,
              is_marker   = excluded.is_marker
            """,
            (op_id, occurred_at, platform, type_, title, detail,
             impact if impact in ("good", "warn", "bad", "neutral") else "neutral",
             bool(is_marker)),
        )

    def delete_operations_except(self, keep_ids):
        """Operations.md is the source of truth — drop operation rows whose id is
        no longer in the file (handles edits/deletions). No-op on an empty set so a
        parse miss can't nuke the table. (#19)"""
        if not keep_ids:
            return
        self._exec("delete from operations where id <> all(%s)", (list(keep_ids),))

    def upsert_operation_summary(self, date: str, summary: str, op_count: int = 0,
                                 ops_hash: Optional[str] = None):
        """Per-day 'event of the day' brief → operation_summaries. (#19)"""
        self._exec(
            """
            insert into operation_summaries (date, summary, op_count, ops_hash, generated_at)
            values (%s, %s, %s, %s, now())
            on conflict (date) do update set
              summary      = excluded.summary,
              op_count     = excluded.op_count,
              ops_hash     = excluded.ops_hash,
              generated_at = now()
            """,
            (date, summary, _int(op_count), ops_hash),
        )

    # -- bookkeeping ---------------------------------------------------------
    def log_sync_run(self, source: str, ok: bool = True):
        """Append a sync_runs row (drives the dashboard's 'last synced' chip)."""
        self._exec(
            "insert into sync_runs (source, ok) values (%s, %s)",
            (source, bool(ok)),
        )
