#!/usr/bin/env python3
"""amazon-asin-perf-prod.py — per-ASIN Amazon Ads performance → prod bcc.

Pulls a Sponsored Products *advertised product* report (30-day SUMMARY: cost +
sales30d per advertised ASIN) from the Amazon Ads v3 reporting API and upserts
ad_spend_30d / ad_sales_30d onto amazon_products in the PROD Command Center DB.
The dashboard derives ROAS = ad_sales_30d / ad_spend_30d at read time.

Creds read from the amazon-ads-pp-cli .env (same as amazon-ads-audit.py); the
prod DB has no host port, so the write ships over the babanuj_deploy SSH key +
`docker exec psql`. Amazon creds never leave this Mac.

Run standalone (e.g. daily via launchd, alongside the audit refresh):
    python3 amazon-asin-perf-prod.py
"""
import json, os, sys, gzip, time, subprocess, urllib.request, urllib.parse, urllib.error
from collections import defaultdict
from datetime import datetime, timedelta, timezone

ENV = os.path.expanduser("~/.config/amazon-ads-pp-cli/.env")
HOST = "https://advertising-api.amazon.com"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"
VPS = os.environ.get("BCC_VPS","root@<vps-host>")
KEY = os.path.expanduser("~/.ssh/babanuj_deploy")


def load_env(path):
    env = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def access_token(env):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": env["AMAZON_ADS_REFRESH_TOKEN"],
        "client_id": env["AMAZON_ADS_CLIENT_ID"],
        "client_secret": env["AMAZON_ADS_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=60).read())["access_token"]


def headers(env, access):
    cid = env.get("AMAZON_ADS_API_CLIENT_ID") or env["AMAZON_ADS_CLIENT_ID"]
    return {"Authorization": "Bearer " + access,
            "Amazon-Advertising-API-ClientId": cid,
            "Amazon-Advertising-API-Scope": env["AMAZON_ADS_PROFILE_ID"]}


def asin_perf(env):
    """advertised ASIN -> {'spend': float, 'sales': float} over the last 30 days."""
    access = access_token(env)
    H = headers(env, access)
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=29)
    body = {"name": "asin-perf", "startDate": start.isoformat(), "endDate": end.isoformat(),
            "configuration": {"adProduct": "SPONSORED_PRODUCTS", "groupBy": ["advertiser"],
                              "columns": ["advertisedAsin", "cost", "sales30d", "purchases30d"],
                              "reportTypeId": "spAdvertisedProduct", "timeUnit": "SUMMARY",
                              "format": "GZIP_JSON"}}
    ch = dict(H); ch["Content-Type"] = "application/vnd.createasyncreportrequest.v3+json"
    req = urllib.request.Request(HOST + "/reporting/reports", data=json.dumps(body).encode(), headers=ch, method="POST")
    rid = json.loads(urllib.request.urlopen(req, timeout=60).read())["reportId"]
    print(f"[perf] report {rid} — polling…", file=sys.stderr)
    url = None
    for _ in range(40):  # ~20 min ceiling
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(HOST + "/reporting/reports/" + rid, headers=H), timeout=60).read())
        except urllib.error.URLError:
            time.sleep(30); continue
        if r["status"] == "COMPLETED": url = r["url"]; break
        if r["status"] == "FAILED":
            print(f"[perf] report FAILED: {r.get('failureReason')}", file=sys.stderr); return {}
        time.sleep(30)
    if not url:
        print("[perf] report never completed", file=sys.stderr); return {}
    rows = json.loads(gzip.decompress(urllib.request.urlopen(url, timeout=60).read()).decode())
    agg = defaultdict(lambda: [0.0, 0.0, 0])
    for x in rows:
        a = x.get("advertisedAsin")
        if not a:
            continue
        agg[a][0] += float(x.get("cost", 0) or 0)
        agg[a][1] += float(x.get("sales30d", 0) or 0)
        agg[a][2] += int(float(x.get("purchases30d", 0) or 0))
    return {a: {"spend": c, "sales": s, "orders": o} for a, (c, s, o) in agg.items()}


def asin_perf_daily(env, days=30):
    """[(asin, date, spend, sales, orders)] per day, for range-queryable metrics.

    Feeds asin_metrics_daily so the dashboard can total any start/end window with
    correct ASIN attribution — summing campaign metrics up to an ASIN would
    over-count, since one campaign can advertise several ASINs. History simply
    accumulates: each run refreshes the trailing window, older days stay put.
    """
    access = access_token(env)
    H = headers(env, access)
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    body = {"name": "asin-perf-daily", "startDate": start.isoformat(), "endDate": end.isoformat(),
            "configuration": {"adProduct": "SPONSORED_PRODUCTS", "groupBy": ["advertiser"],
                              "columns": ["date", "advertisedAsin", "cost", "sales30d", "purchases30d"],
                              "reportTypeId": "spAdvertisedProduct", "timeUnit": "DAILY",
                              "format": "GZIP_JSON"}}
    ch = dict(H); ch["Content-Type"] = "application/vnd.createasyncreportrequest.v3+json"
    req = urllib.request.Request(HOST + "/reporting/reports", data=json.dumps(body).encode(), headers=ch, method="POST")
    rid = json.loads(urllib.request.urlopen(req, timeout=60).read())["reportId"]
    print(f"[perf-daily] report {rid} — polling…", file=sys.stderr)
    url = None
    for _ in range(40):
        try:
            r = json.loads(urllib.request.urlopen(urllib.request.Request(HOST + "/reporting/reports/" + rid, headers=H), timeout=60).read())
        except urllib.error.URLError:
            time.sleep(30); continue
        if r["status"] == "COMPLETED": url = r["url"]; break
        if r["status"] == "FAILED":
            print(f"[perf-daily] FAILED: {r.get('failureReason')}", file=sys.stderr); return []
        time.sleep(30)
    if not url:
        print("[perf-daily] report never completed", file=sys.stderr); return []
    rows = json.loads(gzip.decompress(urllib.request.urlopen(url, timeout=60).read()).decode())
    out = defaultdict(lambda: [0.0, 0.0, 0])
    for x in rows:
        a, d = x.get("advertisedAsin"), x.get("date")
        if not (a and d):
            continue
        k = (a, d[:10])
        out[k][0] += float(x.get("cost", 0) or 0)
        out[k][1] += float(x.get("sales30d", 0) or 0)
        out[k][2] += int(float(x.get("purchases30d", 0) or 0))
    return [(a, d, c, s, o) for (a, d), (c, s, o) in out.items()]


def main():
    env = load_env(ENV)
    perf = asin_perf(env)
    print(f"[perf] {len(perf)} ASINs with spend/sales", file=sys.stderr)
    if not perf:
        sys.exit(1)
    lines = ["begin;",
             "alter table amazon_products add column if not exists ad_spend_30d numeric(12,2);",
             "alter table amazon_products add column if not exists ad_sales_30d numeric(12,2);",
             "alter table amazon_products add column if not exists ad_orders_30d integer;"]
    for a, v in perf.items():
        lines.append(f"update amazon_products set ad_spend_30d={v['spend']:.2f}, ad_sales_30d={v['sales']:.2f}, ad_orders_30d={v['orders']}, updated_at=now() where asin='{a}';")

    # Daily ASIN-attributed series (range-queryable). Upsert so re-running just
    # refreshes the trailing window; earlier days accumulate untouched.
    daily = asin_perf_daily(env)
    print(f"[perf-daily] {len(daily)} asin-day rows", file=sys.stderr)
    lines.append("""create table if not exists asin_metrics_daily(
      asin text not null, date date not null,
      spend numeric(12,2) not null default 0,
      sales numeric(12,2) not null default 0,
      orders integer not null default 0,
      primary key (asin, date));""")
    for a, d, c, s, o in daily:
        lines.append(f"insert into asin_metrics_daily(asin,date,spend,sales,orders) values('{a}','{d}',{c:.2f},{s:.2f},{o}) "
                     f"on conflict(asin,date) do update set spend=excluded.spend, sales=excluded.sales, orders=excluded.orders;")
    lines.append("commit;")
    p = subprocess.run(["ssh", "-i", KEY, "-o", "BatchMode=yes", "-o", "ConnectTimeout=20", VPS,
                        "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                       input="\n".join(lines), capture_output=True, text=True, timeout=120)
    if p.returncode != 0:
        print("STDERR:", p.stderr[-500:], file=sys.stderr); sys.exit(1)
    tot_c = sum(v["spend"] for v in perf.values()); tot_s = sum(v["sales"] for v in perf.values())
    print(f"[perf] wrote {len(perf)} ASINs — spend ${tot_c:,.0f} sales ${tot_s:,.0f} roas {tot_s/tot_c if tot_c else 0:.2f}")


if __name__ == "__main__":
    main()
