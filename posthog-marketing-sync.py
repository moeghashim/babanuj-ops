#!/usr/bin/env python3
"""
posthog-marketing-sync.py — pull DAILY marketing metrics from every channel and
push them to PostHog as snapshot events, so the "Babanuj Command Center"
dashboard can show paid (Amazon/Meta/Google) + organic (SEO/Amazon store)
alongside the native web-analytics + Shopify-revenue tiles.

Channels (all already authenticated via their CLIs / helpers):
  - amazon_sp / amazon_sb / amazon_sd : ~/babanuj-ops/amazon-ads-report.py (DAILY)
  - meta                              : `meta` CLI (account-level daily insights)
  - google_ads                        : Google Ads REST GoogleAdsService.search
  - gsc (SEO)                         : google-search-console-pp-cli local SQLite
  - amazon_seller (organic store)     : SP-API GET_SALES_AND_TRAFFIC_REPORT (DAY)

MODEL — restatement-safe via re-send + argMax:
  Each (channel, metric_date) is sent as an event carrying `ingested_at`
  (unix seconds). We RE-SEND the trailing `--days` window every run, so when
  Amazon's 14-day attribution restates an old day, a newer event lands with a
  higher `ingested_at`. Dashboard insights use `argMax(<metric>, ingested_at)`
  grouped by (channel, metric_date) to read the latest value per day. No
  $insert_id (we WANT duplicates so argMax can pick the freshest).

  Events:
    marketing_snapshot   distinct_id=marketing::<channel>   (paid: spend/sales/orders/clicks/impressions)
    store_sales_snapshot distinct_id=marketing::amazon_seller (sales/orders/units/sessions/pageviews)
    seo_snapshot         distinct_id=marketing::gsc          (clicks/impressions/ctr/position)
  All carry $process_person_profile:false so they never mint person profiles.

Usage:
  python3 posthog-marketing-sync.py [--days 14] [--channels all]
                                    [--dry-run] [--refresh-amazon] [--verbose]
  --channels: comma list of {amazon_ads,meta,google,gsc,amazon_seller} or "all".
"""
import argparse, csv, glob, gzip, io, json, os, subprocess, sys, time, urllib.request, urllib.parse
from datetime import date, datetime, timedelta, timezone

# Optional second sink: the Command Center Postgres. Imported lazily and
# defensively so a missing driver / module NEVER affects the PostHog path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    from lib import pg_sync as _pg_sync
except Exception as _pg_imp_err:  # pragma: no cover
    _pg_sync = None
    _PG_IMPORT_ERR = _pg_imp_err

HOME = os.path.expanduser("~")
REPO_ENV = "/Users/moeghashim/babanuj/.env.local"   # source of the PostHog project key
PH_HOST = os.environ.get("POSTHOG_HOST", "https://us.i.posthog.com")
AMZ_ADS_DIR = os.path.join(HOME, "babanuj-ops", "amazon-ads")
US_MARKETPLACE = "ATVPDKIKX0DER"
GOOGLE_ADS_ACCOUNT = "1604376990"   # Babanuj ad account (NOT the manager 6457175449)
GSC_SITE = "sc-domain:babanuj.com"  # MUST filter — shared store also holds myjam.*

PURCHASE_ACTION_TYPES = {
    "purchase", "omni_purchase", "offsite_conversion.fb_pixel_purchase",
}

# Per-campaign daily rows captured for the Postgres sink ONLY (PostHog stores
# channel-level rollups). Populated as a side effect of pull_amazon_ads /
# pull_google so the existing return shapes / PostHog path stay byte-identical.
# Each row: {channel, platform, external_id, name, status, metric_date,
#            spend, sales, orders, clicks, impressions}
CAMPAIGN_ROWS = []

# Per-ASIN store rollups for the Postgres sink ONLY → product_metrics_daily +
# platform_listings (ASIN used as the product id / external listing id for now;
# a real crosswalk replaces this later). Each row: {asin, metric_date, units, sales}.
AMAZON_ASIN_ROWS = []

# Per-query SEO rows for the Postgres sink ONLY → seo_queries. PostHog only gets
# the date-level seo_snapshot. Each row: {captured_date, query, clicks, impressions, position}.
SEO_QUERY_ROWS = []

# channel_key (used by PostHog + channel_metrics_daily) → dashboard platform.
CHANNEL_PLATFORM = {
    "amazon_sp": "amazon", "amazon_sb": "amazon", "amazon_sd": "amazon",
    "google_ads": "google", "meta": "meta",
}
CHANNEL_DISPLAY = {
    "amazon_sp": "Amazon SP", "amazon_sb": "Amazon SB", "amazon_sd": "Amazon SD",
    "google_ads": "Google Ads", "meta": "Meta",
}
# Store-channel (kind=store) → marketplace platform (marketplace_metrics_daily). (#16)
STORE_PLATFORM = {"amazon_seller": "amazon"}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def vlog(verbose, *a):
    if verbose:
        log(*a)


def parse_kv(path):
    """Mirror ga-pull.py: read k=v config/.env files, strip section headers + quotes."""
    d = {}
    with open(path) as f:
        for line in f:
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith("[") and "=" in s:
                k, v = s.split("=", 1)
                d[k.strip()] = v.strip().strip('"').strip("'").strip()
    return d


def which(name, fallback=None):
    for d in os.environ.get("PATH", "").split(os.pathsep) + [
        os.path.join(HOME, ".local", "bin"), os.path.join(HOME, "go", "bin")
    ]:
        p = os.path.join(d, name)
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return p
    return fallback or name


def run(cmd, env=None, timeout=120, stdin=None):
    e = dict(os.environ)
    if env:
        e.update(env)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                       env=e, input=stdin)
    if r.returncode != 0:
        raise RuntimeError(f"cmd {cmd[0]} exited {r.returncode}: {r.stderr.strip()[:400]}")
    return r.stdout


def daterange(days):
    end = date.today() - timedelta(days=1)          # yesterday (today is incomplete)
    start = end - timedelta(days=days - 1)
    return start, end


# ---------------------------------------------------------------- channels ---
def pull_amazon_ads(days, refresh, verbose):
    """SP/SB/SD per-campaign-per-day → summed to per-channel-per-day."""
    _, end = daterange(days)
    helper = os.path.join(HOME, "babanuj-ops", "amazon-ads-report.py")
    records = []
    for p in ("sp", "sb", "sd"):
        # Async helper: resumes a report queued by a previous run (downloads it when
        # ready) and/or queues a fresh one. It never blocks on slow Amazon report
        # generation, so it's safe to run every sync and never hard-fails on latency.
        try:
            vlog(verbose, f"[amazon_{p}] running async report helper (DAILY {days}d)…")
            run([sys.executable, "-u", helper, "--ad-product", p,
                 "--days", str(days), "--time-unit", "DAILY"], timeout=180)
            time.sleep(15)                      # space out create calls — avoid 429 throttle
        except Exception as ex:
            log(f"[amazon_{p}] helper error: {ex}")
        # Read the freshest report the async helper has produced so far — today's once
        # ready, otherwise the most recent prior run's (data never regresses).
        cands = sorted(glob.glob(os.path.join(AMZ_ADS_DIR, f"{p}-report-*.json")))
        if not cands:
            log(f"[amazon_{p}] no report available yet (queued — appears next run) — skipping")
            continue
        outfile = cands[-1]
        try:
            rows = json.load(open(outfile))
        except Exception as ex:
            log(f"[amazon_{p}] cannot read {outfile}: {ex}")
            continue
        agg = {}
        camp_agg = {}                                   # (campaignId, date) → metrics, for Postgres
        for r in rows:
            d = r.get("date")
            if not d:
                continue
            m = agg.setdefault(d, {"spend": 0.0, "sales": 0.0, "orders": 0,
                                   "clicks": 0, "impressions": 0})
            row_spend = float(r.get("cost") or 0)
            # SP uses sales30d/purchases30d; SB/SD use sales/purchases.
            row_sales = float(r.get("sales30d", r.get("sales", 0)) or 0)
            row_orders = int(r.get("purchases30d", r.get("purchases", 0)) or 0)
            row_clicks = int(r.get("clicks") or 0)
            row_impr = int(r.get("impressions") or 0)
            m["spend"] += row_spend
            m["sales"] += row_sales
            m["orders"] += row_orders
            m["clicks"] += row_clicks
            m["impressions"] += row_impr
            # --- per-campaign capture for the Postgres sink (SP has status; SB/SD don't) ---
            cid = r.get("campaignId")
            if cid is not None:
                ck = (cid, d)
                cm = camp_agg.setdefault(ck, {
                    "name": r.get("campaignName") or str(cid),
                    "status": r.get("campaignStatus"),   # ENABLED/PAUSED/ARCHIVED or None
                    "spend": 0.0, "sales": 0.0, "orders": 0, "clicks": 0, "impressions": 0})
                cm["spend"] += row_spend
                cm["sales"] += row_sales
                cm["orders"] += row_orders
                cm["clicks"] += row_clicks
                cm["impressions"] += row_impr
        for (cid, d), cm in camp_agg.items():
            CAMPAIGN_ROWS.append({
                "channel": f"amazon_{p}", "platform": "amazon",
                "external_id": str(cid),
                # Stable, collision-free PK distinct from seed slugs: "amazon_sp:<id>".
                "campaign_id": f"amazon_{p}:{cid}",
                "name": cm["name"], "status": cm["status"], "metric_date": d,
                "spend": round(cm["spend"], 2), "sales": round(cm["sales"], 2),
                "orders": cm["orders"], "clicks": cm["clicks"],
                "impressions": cm["impressions"]})
        for d, m in agg.items():
            records.append({"kind": "paid", "channel": f"amazon_{p}", "metric_date": d,
                            "spend": round(m["spend"], 2), "sales": round(m["sales"], 2),
                            "orders": m["orders"], "clicks": m["clicks"],
                            "impressions": m["impressions"]})
        vlog(verbose, f"[amazon_{p}] {len(agg)} days")
    return records


def pull_meta(days, verbose):
    env = parse_kv(os.path.join(HOME, ".config", "meta", ".env"))
    start, end = daterange(days)
    out = run([which("meta", os.path.join(HOME, ".local/bin/meta")),
               "-o", "json", "ads", "insights", "get",
               "--since", start.isoformat(), "--until", end.isoformat(),
               "--time-increment", "daily",
               "--fields", "spend,impressions,clicks,actions,action_values"],
              env=env, timeout=120)
    data = json.loads(out).get("data", [])
    records = []
    for row in data:
        d = row.get("date_start")
        if not d:
            continue

        def conv(arr):
            return round(sum(float(a.get("value", 0)) for a in row.get(arr, [])
                             if a.get("action_type") in PURCHASE_ACTION_TYPES), 2)
        records.append({"kind": "paid", "channel": "meta", "metric_date": d,
                        "spend": round(float(row.get("spend") or 0), 2),
                        "sales": conv("action_values"), "orders": int(conv("actions")),
                        "clicks": int(float(row.get("clicks") or 0)),
                        "impressions": int(float(row.get("impressions") or 0))})
    vlog(verbose, f"[meta] {len(records)} days")
    return records


def pull_google(days, verbose):
    cfg = parse_kv(os.path.join(HOME, ".config", "google-ads-pp-cli", "config.toml"))
    env = parse_kv(os.path.join(HOME, ".config", "google-ads-pp-cli", ".env"))
    tok = urllib.parse.urlencode({
        "client_id": cfg["client_id"], "client_secret": cfg["client_secret"],
        "refresh_token": cfg["refresh_token"], "grant_type": "refresh_token"}).encode()
    at = json.load(urllib.request.urlopen(
        "https://oauth2.googleapis.com/token", data=tok))["access_token"]
    hdr = {"Authorization": "Bearer " + at,
           "developer-token": env["GOOGLE_ADS_DEVELOPER_TOKEN"],
           "Content-Type": "application/json"}
    start, end = daterange(days)
    gaql = ("SELECT campaign.id, campaign.name, campaign.status, segments.date, "
            "metrics.cost_micros, metrics.clicks, "
            "metrics.impressions, metrics.conversions, metrics.conversions_value "
            f"FROM campaign WHERE segments.date BETWEEN '{start.isoformat()}' "
            f"AND '{end.isoformat()}'")
    agg, camp_agg, page = {}, {}, None
    while True:
        body = {"query": gaql}
        if page:
            body["pageToken"] = page
        req = urllib.request.Request(
            f"https://googleads.googleapis.com/v22/customers/{GOOGLE_ADS_ACCOUNT}/googleAds:search",
            data=json.dumps(body).encode(), headers=hdr)
        res = json.loads(urllib.request.urlopen(req).read().decode())
        for r in res.get("results", []):
            d = r.get("segments", {}).get("date")
            m = r.get("metrics", {})
            if not d:
                continue
            spend = int(m.get("costMicros", 0)) / 1e6
            sales = float(m.get("conversionsValue", 0))
            orders = float(m.get("conversions", 0))
            clicks = int(m.get("clicks", 0))
            impr = int(m.get("impressions", 0))
            a = agg.setdefault(d, {"spend": 0.0, "sales": 0.0, "orders": 0.0,
                                   "clicks": 0, "impressions": 0})
            a["spend"] += spend
            a["sales"] += sales
            a["orders"] += orders
            a["clicks"] += clicks
            a["impressions"] += impr
            # --- per-campaign capture for the Postgres sink ---
            camp = r.get("campaign", {})
            cid = camp.get("id")
            if cid is not None:
                ck = (cid, d)
                cm = camp_agg.setdefault(ck, {
                    "name": camp.get("name") or str(cid),
                    "status": camp.get("status"),    # ENABLED/PAUSED/REMOVED
                    "spend": 0.0, "sales": 0.0, "orders": 0.0, "clicks": 0, "impressions": 0})
                cm["spend"] += spend
                cm["sales"] += sales
                cm["orders"] += orders
                cm["clicks"] += clicks
                cm["impressions"] += impr
        page = res.get("nextPageToken")
        if not page:
            break
    for (cid, d), cm in camp_agg.items():
        CAMPAIGN_ROWS.append({
            "channel": "google_ads", "platform": "google",
            "external_id": str(cid), "campaign_id": f"google_ads:{cid}",
            "name": cm["name"], "status": cm["status"], "metric_date": d,
            "spend": round(cm["spend"], 2), "sales": round(cm["sales"], 2),
            "orders": round(cm["orders"]), "clicks": cm["clicks"],
            "impressions": cm["impressions"]})
    records = [{"kind": "paid", "channel": "google_ads", "metric_date": d,
                "spend": round(m["spend"], 2), "sales": round(m["sales"], 2),
                "orders": round(m["orders"], 2), "clicks": m["clicks"],
                "impressions": m["impressions"]} for d, m in agg.items()]
    vlog(verbose, f"[google_ads] {len(records)} days")
    return records


def pull_gsc(days, verbose):
    cli = which("google-search-console-pp-cli",
                os.path.join(HOME, "go/bin/google-search-console-pp-cli"))
    try:                                            # best-effort freshen; GSC lags ~2-3d
        run([cli, "sync", GSC_SITE], timeout=180)
    except Exception as ex:
        vlog(verbose, f"[gsc] sync skipped: {ex}")
    start, _ = daterange(days)
    sql = (f"SELECT date, SUM(clicks) clicks, SUM(impressions) impressions, "
           f"SUM(position*impressions) wpos FROM search_analytics_rows "
           f"WHERE site_url='{GSC_SITE}' AND date >= '{start.isoformat()}' GROUP BY date")
    out = run([cli, "sql", sql, "--csv"], timeout=60)
    records = []
    for r in csv.DictReader(io.StringIO(out)):      # CSV columns are alpha-sorted → parse by name
        imp = float(r.get("impressions") or 0)
        clk = float(r.get("clicks") or 0)
        wpos = float(r.get("wpos") or 0)
        records.append({"kind": "seo", "channel": "gsc", "metric_date": r["date"],
                        "clicks": int(clk), "impressions": int(imp),
                        "ctr": round(clk / imp, 4) if imp else 0,
                        "position": round(wpos / imp, 2) if imp else 0})
    vlog(verbose, f"[gsc] {len(records)} days")
    # --- per-query rows for the Postgres sink (seo_queries); top by clicks over the window ---
    try:
        _, end = daterange(days)
        qsql = (f"SELECT query, SUM(clicks) clicks, SUM(impressions) impressions, "
                f"SUM(position*impressions) wpos FROM search_analytics_rows "
                f"WHERE site_url='{GSC_SITE}' AND date >= '{start.isoformat()}' "
                f"GROUP BY query ORDER BY clicks DESC LIMIT 100")
        qout = run([cli, "sql", qsql, "--csv"], timeout=60)
        captured = end.isoformat()                  # stamp the window end as capture date
        for r in csv.DictReader(io.StringIO(qout)):
            q = (r.get("query") or "").strip()
            if not q:
                continue
            imp = float(r.get("impressions") or 0)
            clk = float(r.get("clicks") or 0)
            wpos = float(r.get("wpos") or 0)
            SEO_QUERY_ROWS.append({
                "captured_date": captured, "query": q,
                "clicks": int(clk), "impressions": int(imp),
                "position": round(wpos / imp, 2) if imp else None})
        vlog(verbose, f"[gsc] {len(SEO_QUERY_ROWS)} query rows")
    except Exception as ex:
        vlog(verbose, f"[gsc] per-query capture skipped: {ex}")
    return records


def pull_amazon_seller(days, verbose):
    env = parse_kv(os.path.join(HOME, ".config", "amazon-seller-pp-cli", ".env"))
    cli = which("amazon-seller-pp-cli")
    end = date.today()                              # dataEndTime exclusive → last day = yesterday
    start = end - timedelta(days=days)
    end_iso = (end - timedelta(days=1)).isoformat()  # last covered day; stamps PARENT-ASIN rollups
    body = json.dumps({
        "reportType": "GET_SALES_AND_TRAFFIC_REPORT", "marketplaceIds": [US_MARKETPLACE],
        "dataStartTime": start.isoformat() + "T00:00:00Z",
        "dataEndTime": end.isoformat() + "T00:00:00Z",
        "reportOptions": {"dateGranularity": "DAY", "asinGranularity": "PARENT"}})
    rid = json.loads(run([cli, "reports", "create", "--stdin", "--json"],
                         env=env, stdin=body, timeout=90))["data"]["reportId"]
    vlog(verbose, f"[amazon_seller] report {rid} — polling…")
    doc_id = None
    for _ in range(48):                             # ~8 min budget (report can queue)
        time.sleep(10)
        g = json.loads(run([cli, "reports", "get", rid, "--json"], env=env, timeout=60))["results"]
        st = g.get("processingStatus")
        if st == "DONE":
            doc_id = g.get("reportDocumentId")
            break
        if st in ("CANCELLED", "FATAL"):
            raise RuntimeError(f"report {rid} status {st}")
    if not doc_id:
        raise RuntimeError(f"report {rid} not DONE in time")
    url = json.loads(run([cli, "reports", "document", doc_id, "--json"],
                         env=env, timeout=60))["results"]["url"]
    raw = urllib.request.urlopen(url).read()
    try:
        raw = gzip.decompress(raw)
    except OSError:
        pass                                        # some docs arrive uncompressed
    payload = json.loads(raw)
    rows = payload.get("salesAndTrafficByDate", [])
    records = []
    for r in rows:
        s, t = r.get("salesByDate", {}), r.get("trafficByDate", {})
        records.append({"kind": "store", "channel": "amazon_seller", "metric_date": r["date"],
                        "sales": round(float(s.get("orderedProductSales", {}).get("amount", 0)), 2),
                        "orders": int(s.get("totalOrderItems", 0)),
                        "units": int(s.get("unitsOrdered", 0)),
                        "sessions": int(t.get("sessions", 0)),
                        "pageviews": int(t.get("pageViews", 0))})
    # Per-(parent)ASIN rows for the Postgres sink → product_metrics_daily.
    # Note: with asinGranularity=PARENT this is a single bucket per ASIN over the
    # whole window (no per-day breakdown), so we stamp it on the window's end date.
    for ar in payload.get("salesAndTrafficByAsin", []):
        asin = ar.get("parentAsin") or ar.get("childAsin") or ar.get("asin")
        if not asin:
            continue
        s = ar.get("salesByAsin", {})
        AMAZON_ASIN_ROWS.append({
            "asin": str(asin), "metric_date": end_iso,
            "units": int(s.get("unitsOrdered", 0)),
            "sales": round(float(s.get("orderedProductSales", {}).get("amount", 0)), 2)})
    vlog(verbose, f"[amazon_seller] {len(records)} days, {len(AMAZON_ASIN_ROWS)} asin rows")
    return records


# --------------------------------------------------------------- posthog ----
def to_events(records, ingested_at):
    ev_for = {"paid": "marketing_snapshot", "store": "store_sales_snapshot",
              "seo": "seo_snapshot"}
    events = []
    for r in records:
        props = {k: v for k, v in r.items() if k != "kind"}
        props["ingested_at"] = ingested_at
        props["$process_person_profile"] = False
        events.append({"event": ev_for[r["kind"]], "distinct_id": f"marketing::{r['channel']}",
                       "timestamp": r["metric_date"] + "T12:00:00Z", "properties": props})
    return events


def posthog_key():
    if os.environ.get("POSTHOG_KEY"):
        return os.environ["POSTHOG_KEY"]
    return parse_kv(REPO_ENV)["NEXT_PUBLIC_POSTHOG_KEY"]


def push(events, key):
    sent = 0
    for i in range(0, len(events), 100):
        chunk = events[i:i + 100]
        data = json.dumps({"api_key": key, "batch": chunk}).encode()
        req = urllib.request.Request(PH_HOST + "/batch/", data=data,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=60) as resp:
            if resp.status not in (200, 201):
                raise RuntimeError(f"PostHog /batch/ returned {resp.status}")
        sent += len(chunk)
    return sent


# ------------------------------------------------------- postgres (sink 2) ----
def write_postgres(all_records, campaign_rows, asin_rows, query_rows,
                   sources_ok, verbose=False):
    """Second sink: UPSERT the SAME numbers into the Command Center Postgres.

    Reads DATABASE_URL from env; a no-op (returns a skip note) when unset, so the
    PostHog path is the only one with no DB configured. Wraps the whole thing in
    one transaction and NEVER raises into main() — failures are reported, not
    fatal, so they can't take down the (already-completed) PostHog push.

    Mapping (per-source → table):
      channel rollups (kind=paid, all_records)         → channel_metrics_daily (+channels)
      campaign rows (Amazon Ads/Google per-campaign)   → campaigns + campaign_metrics_daily
      store rollups (kind=store, amazon_seller)        → marketplace_metrics_daily (#16)
      per-ASIN store rows                              → products + platform_listings(amazon) + product_metrics_daily
      SEO date rollups (kind=seo, gsc)                 → seo_metrics_daily
      SEO per-query rows                              → seo_queries
      sources_ok                                      → sync_runs (one row per source attempted)
    """
    if _pg_sync is None:
        return {"skipped": f"pg_sync import failed: {_PG_IMPORT_ERR!r}"}
    pg = _pg_sync.PgSync.from_env(verbose=verbose)
    if pg is None:
        return {"skipped": "DATABASE_URL not set — Postgres dual-write off"}

    counts = {"channel_metrics": 0, "campaign_metrics": 0, "marketplace": 0,
              "product_metrics": 0, "seo_metrics": 0, "seo_queries": 0,
              "ad_spend_days": 0, "sync_runs": 0}
    channel_dates = set()   # dates touched by channel upserts → recompute ad_spend
    try:
        with pg:
            # 1) channel rollups + 3) store KPIs + 5) SEO date rollups
            for r in all_records:
                kind = r.get("kind")
                d = r.get("metric_date")
                if not d:
                    continue
                if kind == "paid":
                    ck = r["channel"]
                    pg.upsert_channel_metrics(
                        channel_key=ck, date=d,
                        spend=r.get("spend", 0), sales=r.get("sales", 0),
                        impressions=r.get("impressions", 0), clicks=r.get("clicks", 0),
                        channel_name=CHANNEL_DISPLAY.get(ck, ck),
                        platform=CHANNEL_PLATFORM.get(ck, "amazon"))
                    counts["channel_metrics"] += 1
                    channel_dates.add(d)
                elif kind == "store":
                    # amazon_seller MARKETPLACE store rollup → marketplace_metrics_daily
                    # (NOT web_kpis_daily — that's Shopify's WEBSITE revenue). The DAL
                    # sums website + marketplace for the cockpit total, so this ADDS
                    # rather than clobbers. (#16)
                    pg.upsert_marketplace_metrics(
                        platform=STORE_PLATFORM.get(r["channel"], "amazon"),
                        date=d, revenue=r.get("sales", 0),
                        orders=r.get("orders", 0), units=r.get("units", 0),
                        sessions=r.get("sessions"))
                    counts["marketplace"] += 1
                elif kind == "seo":
                    pg.upsert_seo_metrics(
                        date=d, clicks=r.get("clicks", 0),
                        impressions=r.get("impressions", 0), position=r.get("position"))
                    counts["seo_metrics"] += 1

            # 2) per-campaign rows → campaigns + campaign_metrics_daily
            for c in campaign_rows:
                pg.upsert_campaign(
                    campaign_id=c["campaign_id"], name=c["name"],
                    platform=c["platform"], date=c["metric_date"],
                    external_id=c.get("external_id"), status=(c.get("status") or "Active"),
                    spend=c.get("spend", 0), sales=c.get("sales", 0),
                    impressions=c.get("impressions", 0), clicks=c.get("clicks", 0),
                    orders=c.get("orders", 0))
                counts["campaign_metrics"] += 1

            # 4) per-ASIN store rows → products + platform_listings + product_metrics_daily
            #    ASIN doubles as the canonical product id AND the amazon listing id
            #    until the real crosswalk (shared barcode / manual map) is wired.
            for ar in asin_rows:
                asin = ar["asin"]
                pg.ensure_product(product_id=asin, name=asin, subtitle="amazon ASIN")
                pg.upsert_platform_listing(
                    product_id=asin, platform="amazon",
                    external_listing_id=asin, status="active")
                pg.upsert_product_metrics(
                    product_id=asin, platform="amazon", date=ar["metric_date"],
                    units=ar.get("units", 0), sales=ar.get("sales", 0))
                counts["product_metrics"] += 1

            # 6) per-query SEO rows → seo_queries
            for q in query_rows:
                pg.upsert_seo_query(
                    captured_date=q["captured_date"], query=q["query"],
                    clicks=q.get("clicks", 0), impressions=q.get("impressions", 0),
                    position=q.get("position"))
                counts["seo_queries"] += 1

            # Keep web_kpis_daily.ad_spend = SUM(channel spend) for touched days
            # (the dashboard's spend line). Done AFTER channel upserts so it sees
            # the freshest per-channel numbers.
            pg.upsert_web_ad_spend_from_channels(channel_dates)
            counts["ad_spend_days"] = len(channel_dates)

            # bookkeeping: one sync_runs row per source we attempted this run
            for src, ok in sources_ok.items():
                pg.log_sync_run(src, ok=ok)
                counts["sync_runs"] += 1
        return {"ok": True, "upserts": counts}
    except Exception as ex:
        log(f"[postgres] dual-write FAILED (PostHog unaffected): {ex}")
        return {"error": str(ex)[:300]}


# ------------------------------------------------------------------- main ----
CHANNELS = {
    "amazon_ads": lambda a: pull_amazon_ads(a.days, a.refresh_amazon, a.verbose),
    "meta": lambda a: pull_meta(a.days, a.verbose),
    "google": lambda a: pull_google(a.days, a.verbose),
    "gsc": lambda a: pull_gsc(a.days, a.verbose),
    "amazon_seller": lambda a: pull_amazon_seller(a.days, a.verbose),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--channels", default="all")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--refresh-amazon", action="store_true",
                    help="force re-pull Amazon Ads reports even if a cached file exists")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--no-postgres", action="store_true",
                    help="disable the Command Center Postgres dual-write for this run")
    a = ap.parse_args()

    want = list(CHANNELS) if a.channels == "all" else [c.strip() for c in a.channels.split(",")]
    ingested_at = int(datetime.now(timezone.utc).timestamp())
    all_records, summary, sources_ok = [], {}, {}
    for name in want:
        if name not in CHANNELS:
            log(f"[{name}] unknown channel — skipping"); continue
        try:
            recs = CHANNELS[name](a)
            all_records += recs
            spend = round(sum(r.get("spend", 0) for r in recs), 2)
            sales = round(sum(r.get("sales", 0) for r in recs), 2)
            summary[name] = {"days": len({r["metric_date"] for r in recs}),
                             "rows": len(recs), "spend": spend, "sales": sales}
            sources_ok[name] = True
        except Exception as ex:
            summary[name] = {"error": str(ex)[:300]}
            sources_ok[name] = False
            log(f"[{name}] FAILED: {ex}")

    events = to_events(all_records, ingested_at)
    if a.dry_run:
        log("\n=== DRY RUN — not pushing (PostHog or Postgres) ===")
        print(json.dumps({"ingested_at": ingested_at, "summary": summary,
                          "sample": events[:6],
                          "postgres_preview": {
                              "campaign_rows": len(CAMPAIGN_ROWS),
                              "asin_rows": len(AMAZON_ASIN_ROWS),
                              "seo_query_rows": len(SEO_QUERY_ROWS)}}, indent=2))
        return
    # --- sink 1: PostHog (primary; unchanged) ---
    if events:
        sent = push(events, posthog_key())
        summary["_pushed"] = sent
    # --- sink 2: Command Center Postgres (additive; never breaks the run) ---
    if not a.no_postgres:
        summary["_postgres"] = write_postgres(
            all_records, CAMPAIGN_ROWS, AMAZON_ASIN_ROWS, SEO_QUERY_ROWS,
            sources_ok, verbose=a.verbose)
    print(json.dumps({"ingested_at": ingested_at, "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
