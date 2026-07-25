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
import importlib.util, os, sys, json, time, gzip, subprocess, urllib.request, urllib.error
from datetime import date, timedelta
spec=importlib.util.spec_from_file_location("audit", os.path.expanduser("~/babanuj-ops/amazon-ads-audit.py"))
A=importlib.util.module_from_spec(spec); spec.loader.exec_module(A)
DAYS=int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 90
VPS="root@<vps-host>"; KEY=os.path.expanduser("~/.ssh/babanuj_deploy")

env=A.load_env(A.ENV); access=A.refresh_token(env)
cid=env.get("AMAZON_ADS_API_CLIENT_ID") or env["AMAZON_ADS_CLIENT_ID"]
H={"Authorization":"Bearer "+access,"Amazon-Advertising-API-ClientId":cid,
   "Amazon-Advertising-API-Scope":env["AMAZON_ADS_PROFILE_ID"]}
END=date.today()-timedelta(days=1); START=END-timedelta(days=DAYS-1)

def report(report_type, group_by, columns):
    """Amazon caps DAILY reports at 31 days per request — chunk and concatenate."""
    out=[]; s=START
    while s<=END:
        e=min(s+timedelta(days=30), END)
        out.extend(_report_window(report_type, group_by, columns, s, e))
        s=e+timedelta(days=1)
    return out

def _report_window(report_type, group_by, columns, win_start, win_end):
    body={"name":"archive","startDate":win_start.isoformat(),"endDate":win_end.isoformat(),
          "configuration":{"adProduct":"SPONSORED_PRODUCTS","groupBy":group_by,"columns":columns,
                           "reportTypeId":report_type,"timeUnit":"DAILY","format":"GZIP_JSON"}}
    ch=dict(H); ch["Content-Type"]="application/vnd.createasyncreportrequest.v3+json"
    rid=json.loads(urllib.request.urlopen(urllib.request.Request(
        "https://advertising-api.amazon.com/reporting/reports",data=json.dumps(body).encode(),
        headers=ch,method="POST"),timeout=60).read())["reportId"]
    print(f"[{report_type}] {win_start}..{win_end} report {rid} — polling…", file=sys.stderr)
    for _ in range(80):
        try:
            r=json.loads(urllib.request.urlopen(urllib.request.Request(
                "https://advertising-api.amazon.com/reporting/reports/"+rid,headers=H),timeout=60).read())
        except urllib.error.URLError:
            time.sleep(30); continue
        if r["status"]=="COMPLETED":
            return json.loads(gzip.decompress(urllib.request.urlopen(r["url"],timeout=120).read()).decode())
        if r["status"]=="FAILED":
            print(f"[{report_type}] FAILED {r.get('failureReason')}", file=sys.stderr); return []
        time.sleep(30)
    print(f"[{report_type}] timed out", file=sys.stderr); return []

def num(x): 
    try: return float(x or 0)
    except: return 0.0

sql=["begin;",
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

rows=report("spAdvertisedProduct",["advertiser"],
            ["date","advertisedAsin","cost","sales30d","purchases30d","clicks","impressions"])
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
             ["date","campaignId","campaignName","cost","sales30d","purchases30d","clicks","impressions"])
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
                  "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                 input="\n".join(sql),capture_output=True,text=True,timeout=600)
if p.returncode!=0: print(p.stderr[-400:], file=sys.stderr); sys.exit(1)
print(f"[archive] {START}..{END} written (ad {len(agg)}, campaign {len(cagg)})")
