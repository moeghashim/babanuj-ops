#!/usr/bin/env python3
"""OFFLINE validation for the Postgres dual-write — NO live API calls.

Exercises the REAL pull_amazon_ads() cached-file path + the REAL write_postgres()
mapping against local Postgres, plus a tiny synthetic test for the sources that
have no cached data here (Google campaigns, Amazon-Seller ASIN, GSC per-query).

Run:  DATABASE_URL=postgres://bcc:bcc@localhost:5433/bcc \
      /usr/bin/python3 validate_pg_dualwrite.py
"""
import importlib, os, sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DATABASE_URL", "postgres://bcc:bcc@localhost:5433/bcc")

sync = importlib.import_module("posthog-marketing-sync".replace("-", "_")) \
    if False else None  # noqa: hyphenated module → import via importlib below


def load_orchestrator():
    # Module name has hyphens; load it from file.
    import importlib.util
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "posthog-marketing-sync.py")
    spec = importlib.util.spec_from_file_location("phms", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    m = load_orchestrator()

    # --- Pin the report "end" date to a day we have CACHED reports for, so
    #     pull_amazon_ads reads the cached *.json instead of calling the API. ---
    CACHED_END = date(2026, 6, 19)   # sp/sb/sd-report-2026-06-19.json all exist
    # sd's freshest cached file is 06-18; pull picks {p}-report-<end>.json, so we
    # alias the end-dated names to whatever cached file is freshest per product.
    import glob
    amzdir = m.AMZ_ADS_DIR
    for p in ("sp", "sb", "sd"):
        want = os.path.join(amzdir, f"{p}-report-{CACHED_END.isoformat()}.json")
        if not os.path.isfile(want):
            cands = sorted(glob.glob(os.path.join(amzdir, f"{p}-report-*.json")))
            if cands:
                # symlink freshest cached → expected end-dated name (cleanup after)
                os.symlink(os.path.abspath(cands[-1]), want)
                print(f"[setup] aliased {os.path.basename(cands[-1])} -> {os.path.basename(want)}")

    # Force the helper's daterange() to return our cached window (NO api refresh).
    orig_daterange = m.daterange
    m.daterange = lambda days: (date(2026, 6, 6), CACHED_END)
    try:
        # refresh=False → pure cached parse, real aggregation + real CAMPAIGN_ROWS
        records = m.pull_amazon_ads(days=14, refresh=False, verbose=True)
    finally:
        m.daterange = orig_daterange

    print(f"\n[amazon_ads] channel rollup records: {len(records)}")
    print(f"[amazon_ads] CAMPAIGN_ROWS captured : {len(m.CAMPAIGN_ROWS)}")
    if m.CAMPAIGN_ROWS:
        print("  sample campaign row:", {k: m.CAMPAIGN_ROWS[0][k] for k in
              ("campaign_id", "external_id", "name", "status", "metric_date",
               "spend", "sales", "orders")})

    # --- Synthetic rows for sources with no cached data here ---
    # Google campaign (mirrors pull_google output shape):
    m.CAMPAIGN_ROWS.append({
        "channel": "google_ads", "platform": "google",
        "external_id": "TEST123", "campaign_id": "google_ads:TEST123",
        "name": "TEST Google Shopping Core", "status": "ENABLED",
        "metric_date": "2026-06-19", "spend": 12.34, "sales": 100.0,
        "orders": 3, "clicks": 20, "impressions": 1500})
    # Amazon-Seller per-ASIN (mirrors AMAZON_ASIN_ROWS):
    asin_rows = [{"asin": "B0TEST0001", "metric_date": "2026-06-19",
                  "units": 7, "sales": 139.93}]
    # GSC per-query (mirrors SEO_QUERY_ROWS):
    query_rows = [{"captured_date": "2026-06-19", "query": "test baklava near me",
                   "clicks": 5, "impressions": 220, "position": 4.2}]
    # store rollup (kind=store) + seo date rollup (kind=seo) synthetic:
    store_seo = [
        {"kind": "store", "channel": "amazon_seller", "metric_date": "2026-06-19",
         "sales": 999.99, "orders": 30, "units": 41, "sessions": 800, "pageviews": 1200},
        {"kind": "seo", "channel": "gsc", "metric_date": "2026-06-19",
         "clicks": 88, "impressions": 4000, "ctr": 0.022, "position": 6.1},
    ]
    all_records = records + store_seo
    sources_ok = {"amazon_ads": True, "google": True, "amazon_seller": True, "gsc": True}

    res = m.write_postgres(all_records, m.CAMPAIGN_ROWS, asin_rows, query_rows,
                           sources_ok, verbose=True)
    print("\n[write_postgres] result:")
    import json
    print(json.dumps(res, indent=2))

    # cleanup any symlinks we created
    for p in ("sp", "sb", "sd"):
        link = os.path.join(amzdir, f"{p}-report-{CACHED_END.isoformat()}.json")
        if os.path.islink(link):
            os.unlink(link)
            print(f"[cleanup] removed alias {os.path.basename(link)}")

    print("\nVALIDATION DONE.")


if __name__ == "__main__":
    main()
