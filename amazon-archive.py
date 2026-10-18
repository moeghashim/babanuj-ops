#!/usr/bin/env python3
"""amazon-archive.py — permanent, append-only archive of ALL Amazon metrics.

Amazon retains ~90 days; this owns the history forever. Pulls a rolling window
and upserts into archive tables so re-runs are idempotent and old days survive
long after Amazon drops them.

FULFILLMENT RULE (Moe, 2026-07-25): FBM orders are already recorded in Shopify's
"Amazon" channel, so any Amazon SALES pull must be FBA-only or it double-counts
FBM. Ad metrics below are ad-attributed performance, not a second copy of the
order, so they are exempt. Any sales-report added here must filter to FBA.

  amazon-archive.py [--days 90]     # default 90 (Amazon's practical max)

Tables (created on demand, in prod bcc):
  amazon_sales_daily(asin, date, units, sales, sessions, ...)  -- business sales
  amazon_ad_daily(asin, date, spend, sales, orders, clicks, impressions)
  amazon_campaign_daily(campaign_id, date, spend, sales, orders, clicks, impressions)
"""
import argparse, importlib.util, os, sys, json, time, gzip, subprocess, urllib.request, urllib.error
from datetime import date, timedelta
spec=importlib.util.spec_from_file_location("audit", os.path.expanduser("~/babanuj-ops/amazon-ads-audit.py"))
A=importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
parser=argparse.ArgumentParser()
parser.add_argument("--days", type=int, help="pull an explicit trailing window")
parser.add_argument("--full", action="store_true", help="pull the full Amazon retention window")
args=parser.parse_args()
if args.days is not None and args.days < 1:
    parser.error("--days must be at least 1")
if args.days is not None and args.full:
    parser.error("--days and --full are mutually exclusive")

VPS=os.environ["BCC_VPS"]
KEY=os.path.expanduser(os.environ.get("BCC_SSH_KEY", "~/.ssh/babanuj_deploy"))

env=A.load_env(A.ENV)
cid=env.get("AMAZON_ADS_API_CLIENT_ID") or env["AMAZON_ADS_CLIENT_ID"]
H={}
END=date.today()-timedelta(days=1)
FULL_DAYS=90

def refresh_headers():
    global H
    H.clear()
    H.update({"Authorization":"Bearer "+A.refresh_token(env),
              "Amazon-Advertising-API-ClientId":cid,
              "Amazon-Advertising-API-Scope":env["AMAZON_ADS_PROFILE_ID"]})

def prod_psql(sql, timeout=180):
    p=subprocess.run(["ssh","-i",KEY,"-o","BatchMode=yes",VPS,
                      "docker exec -i bcc-prod-postgres psql -U bcc -d bcc -At -v ON_ERROR_STOP=1"],
                     input=sql,capture_output=True,text=True,timeout=timeout)
    if p.returncode != 0:
        detail=(p.stderr or p.stdout).strip()[-500:]
        raise RuntimeError(f"prod DB command failed: {detail}")
    return p.stdout

def max_date(table):
    if table not in {"amazon_ad_daily", "amazon_campaign_daily"}:
        raise ValueError(f"unsupported archive table: {table}")
    value=prod_psql(f"select max(date) from {table};").strip()
    return date.fromisoformat(value) if value else None

def window_start(table):
    if args.days is not None:
        return END-timedelta(days=args.days-1)
    if args.full:
        return END-timedelta(days=FULL_DAYS-1)
    latest=max_date(table)
    return (latest-timedelta(days=3)) if latest else END-timedelta(days=FULL_DAYS-1)

def report(report_type, group_by, columns, start):
    """Amazon caps DAILY reports at 31 days per request — chunk and concatenate."""
    out=[]; s=start
    while s<=END:
        e=min(s+timedelta(days=30), END)
        out.extend(_report_window(report_type, group_by, columns, s, e))
        s=e+timedelta(days=1)
    return out

def _report_window(report_type, group_by, columns, win_start, win_end):
    # A fresh token per window keeps a deep backfill from crossing the LWA
    # token lifetime. The poll is capped at 80 * 30s = 40 minutes.
    refresh_headers()
    body={"name":"archive","startDate":win_start.isoformat(),"endDate":win_end.isoformat(),
          "configuration":{"adProduct":"SPONSORED_PRODUCTS","groupBy":group_by,"columns":columns,
                           "reportTypeId":report_type,"timeUnit":"DAILY","format":"GZIP_JSON"}}
    ch=dict(H); ch["Content-Type"]="application/vnd.createasyncreportrequest.v3+json"
    def request(url, data=None, headers=None, method=None, timeout=60, authenticate=True):
        for attempt in range(2):
            try:
                return urllib.request.urlopen(urllib.request.Request(
                    url, data=data,
                    headers=(headers if headers is not None else (H if authenticate else {})),
                    method=method), timeout=timeout)
            except urllib.error.HTTPError as e:
                if e.code != 401 or attempt:
                    raise
                refresh_headers()
                if headers is not None and authenticate:
                    headers.clear()
                    headers.update(H)

    try:
        response=request("https://advertising-api.amazon.com/reporting/reports",
                         data=json.dumps(body).encode(),headers=ch,method="POST")
        with response:
            rid=json.loads(response.read())["reportId"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"[{report_type}] report request failed with HTTP {e.code}") from e
    print(f"[{report_type}] {win_start}..{win_end} report {rid} — polling…", file=sys.stderr)
    for _ in range(80):
        try:
            response=request("https://advertising-api.amazon.com/reporting/reports/"+rid,
                             headers=H)
            with response:
                r=json.loads(response.read())
        except urllib.error.HTTPError as e:
            if e.code == 401:
                print(f"[{report_type}] poll unauthorized after token refresh", file=sys.stderr)
            raise RuntimeError(f"[{report_type}] poll failed with HTTP {e.code}") from e
        except urllib.error.URLError:
            time.sleep(30); continue
        if r["status"]=="COMPLETED":
            try:
                # Amazon's completed-report URL is pre-signed; bearer headers
                # turn an otherwise valid download into HTTP 400.
                response=request(r["url"],headers={},timeout=120,authenticate=False)
                with response:
                    return json.loads(gzip.decompress(response.read()).decode())
            except urllib.error.HTTPError as e:
                raise RuntimeError(f"[{report_type}] download failed with HTTP {e.code}") from e
        if r["status"]=="FAILED":
            raise RuntimeError(f"[{report_type}] FAILED {r.get('failureReason')}")
        time.sleep(30)
    raise RuntimeError(f"[{report_type}] timed out after 40 minutes")

def num(x): 
    try: return float(x or 0)
    except: return 0.0

SCHEMA_SQL=[
 """create table if not exists amazon_ad_daily(
      asin text not null, date date not null,
      spend numeric(12,2) not null default 0, sales numeric(12,2) not null default 0,
      orders integer not null default 0, clicks integer not null default 0,
      impressions integer not null default 0,
      archived_at timestamptz not null default now(),
      primary key(asin,date));""",
 """create table if not exists amazon_campaign_daily(
      campaign_id text not null, campaign_name text, date date not null,
      spend numeric(12,2) not null default 0, sales numeric(12,2) not null default 0,
      orders integer not null default 0, clicks integer not null default 0,
      impressions integer not null default 0,
      archived_at timestamptz not null default now(),
      primary key(campaign_id,date));"""]

# Ensure max(date) queries work on a fresh archive as well as an existing one.
prod_psql("begin;\n"+"\n".join(SCHEMA_SQL)+"\ncommit;")
ad_start=window_start("amazon_ad_daily")
campaign_start=window_start("amazon_campaign_daily")
print(f"[window] ad {ad_start}..{END}; campaign {campaign_start}..{END}", file=sys.stderr)

sql=["begin;", *SCHEMA_SQL]

rows=report("spAdvertisedProduct",["advertiser"],
            ["date","advertisedAsin","cost","sales30d","purchases30d","clicks","impressions"], ad_start)
agg={}
for x in rows:
    a,d=x.get("advertisedAsin"),(x.get("date") or "")[:10]
    if not (a and d): continue
    v=agg.setdefault((a,d),[0.0,0.0,0,0,0])
    v[0]+=num(x.get("cost")); v[1]+=num(x.get("sales30d")); v[2]+=int(num(x.get("purchases30d")))
    v[3]+=int(num(x.get("clicks"))); v[4]+=int(num(x.get("impressions")))
for (a,d),v in agg.items():
    sql.append(f"insert into amazon_ad_daily(asin,date,spend,sales,orders,clicks,impressions) "
               f"values('{a}','{d}',{v[0]:.2f},{v[1]:.2f},{v[2]},{v[3]},{v[4]}) "
               f"on conflict(asin,date) do update set spend=excluded.spend,sales=excluded.sales,"
               f"orders=excluded.orders,clicks=excluded.clicks,impressions=excluded.impressions,archived_at=now();")
print(f"[ad] {len(agg)} asin-days", file=sys.stderr)

crows=report("spCampaigns",["campaign"],
             ["date","campaignId","campaignName","cost","sales30d","purchases30d","clicks","impressions"], campaign_start)
cagg={}
for x in crows:
    c,d=str(x.get("campaignId") or ""),(x.get("date") or "")[:10]
    if not (c and d): continue
    v=cagg.setdefault((c,d),[x.get("campaignName") or "",0.0,0.0,0,0,0])
    v[1]+=num(x.get("cost")); v[2]+=num(x.get("sales30d")); v[3]+=int(num(x.get("purchases30d")))
    v[4]+=int(num(x.get("clicks"))); v[5]+=int(num(x.get("impressions")))
for (c,d),v in cagg.items():
    nm=v[0].replace("'","''")
    sql.append(f"insert into amazon_campaign_daily(campaign_id,campaign_name,date,spend,sales,orders,clicks,impressions) "
               f"values('{c}',$q${v[0]}$q$,'{d}',{v[1]:.2f},{v[2]:.2f},{v[3]},{v[4]},{v[5]}) "
               f"on conflict(campaign_id,date) do update set campaign_name=excluded.campaign_name,spend=excluded.spend,"
               f"sales=excluded.sales,orders=excluded.orders,clicks=excluded.clicks,impressions=excluded.impressions,archived_at=now();")
print(f"[campaign] {len(cagg)} campaign-days", file=sys.stderr)

sql.append("commit;")
p=subprocess.run(["ssh","-i",KEY,"-o","BatchMode=yes",VPS,
                  "docker exec -i bcc-prod-postgres psql -U bcc -d bcc -v ON_ERROR_STOP=1"],
                 input="\n".join(sql),capture_output=True,text=True,timeout=600)
if p.returncode!=0:
    detail=(p.stderr or p.stdout).strip()[-500:]
    print(f"FATAL: prod archive DB write failed: {detail}", file=sys.stderr)
    sys.exit(1)
print(f"[archive] ad {ad_start}..{END}; campaign {campaign_start}..{END} written (ad {len(agg)}, campaign {len(cagg)})")
