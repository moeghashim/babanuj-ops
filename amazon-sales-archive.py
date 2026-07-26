#!/usr/bin/env python3
"""amazon-sales-archive.py — TRUE Amazon sales (organic + ad) → amazon_sales_daily.

Ad reports only carry ad-ATTRIBUTED sales, so organic FBA orders are invisible.
This reads the Orders API and records real per-ASIN daily sales.

FULFILLMENT RULE (Moe): FBM already lands in Shopify's "Amazon" channel, so only
**FBA** is recorded here or Amazon totals double-count. Orders carry no
fulfillment field in this API version, so each item's sellerSku is classified via
the merchant-listings report (AMAZON* = FBA, DEFAULT = FBM). Unknown SKUs are
recorded as 'UNKNOWN' and excluded from FBA totals — never guessed into FBA.

  amazon-sales-archive.py [--days 90]
"""
import json, os, subprocess, sys, time, gzip, urllib.request
from collections import defaultdict
from datetime import timedelta, datetime, timezone
DAYS=int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 90
MKT="ATVPDKIKX0DER"; VPS=os.environ.get("BCC_VPS","root@<vps-host>"); KEY=os.path.expanduser("~/.ssh/babanuj_deploy")

def cli(args, inp=None, t=180):
    r=subprocess.run(["amazon-seller-pp-cli",*args,"--json","--no-input","--no-color"],
                     input=inp,capture_output=True,text=True,timeout=t)
    if r.returncode!=0: raise RuntimeError((r.stderr or r.stdout)[-300:])
    return json.loads(r.stdout or "{}")

def sku_fulfillment():
    """sellerSku -> 'FBA' | 'FBM' from GET_MERCHANT_LISTINGS_ALL_DATA."""
    rid=cli(["reports","create","--stdin"],
            inp=json.dumps({"reportType":"GET_MERCHANT_LISTINGS_ALL_DATA","marketplaceIds":[MKT]}))["data"]["reportId"]
    doc=None
    for _ in range(60):
        r=cli(["reports","get",rid])["results"]
        if r["processingStatus"]=="DONE": doc=r["reportDocumentId"]; break
        if r["processingStatus"] in ("FATAL","CANCELLED"): return {}
        time.sleep(15)
    if not doc: return {}
    d=cli(["reports","document",doc])["results"]
    raw=urllib.request.urlopen(d["url"],timeout=60).read()
    text=gzip.decompress(raw).decode("utf-8","replace") if d.get("compressionAlgorithm")=="GZIP" else raw.decode("utf-8","replace")
    lines=text.splitlines(); hdr=[h.lstrip("﻿") for h in lines[0].split("\t")]
    isku,ifc=hdr.index("seller-sku"), hdr.index("fulfillment-channel")
    out={}
    for ln in lines[1:]:
        c=ln.split("\t")
        if len(c)>max(isku,ifc) and c[isku].strip():
            out[c[isku].strip()]="FBA" if c[ifc].strip().upper().startswith("AMAZON") else "FBM"
    return out

FUL=sku_fulfillment()
print(f"[map] {len(FUL)} SKUs ({sum(1 for v in FUL.values() if v=='FBA')} FBA)", file=sys.stderr)

start=(datetime.now(timezone.utc)-timedelta(days=DAYS)).replace(microsecond=0).isoformat().replace("+00:00","Z")
agg=defaultdict(lambda:[0,0.0]); token=None; pages=0; n=0
while True:
    args=["orders","search","--marketplace-ids",MKT,"--max-results-per-page","100","--created-after",start]
    if token: args += ["--pagination-token",token]
    res=cli(args).get("results",{})
    for o in res.get("orders",[]):
        day=(o.get("createdTime") or "")[:10]
        if not day: continue
        for it in o.get("orderItems",[]):
            p=it.get("product") or {}
            asin=p.get("asin"); sku=p.get("sellerSku")
            if not asin: continue
            ful=FUL.get(sku,"UNKNOWN")
            qty=int(it.get("quantityOrdered") or 0)
            amt=float(((p.get("price") or {}).get("unitPrice") or {}).get("amount") or 0)
            v=agg[(asin,day,ful)]; v[0]+=qty; v[1]+=amt*max(qty,1)
        n+=1
    pages+=1; token=(res.get("pagination") or {}).get("nextToken")
    print(f"  page {pages}: {n} orders", file=sys.stderr)
    if not token: break
    time.sleep(1)

fba_rows={k:v for k,v in agg.items() if k[2]=="FBA"}
print(f"[sales] {n} orders, {len(agg)} asin-day-ful rows ({len(fba_rows)} FBA)", file=sys.stderr)
lines=["begin;","""create table if not exists amazon_sales_daily(
  asin text not null, date date not null, fulfillment text not null default 'FBA',
  units integer not null default 0, sales numeric(12,2) not null default 0,
  archived_at timestamptz not null default now(),
  primary key(asin,date,fulfillment));"""]
for (asin,day,ful),v in agg.items():
    lines.append(f"insert into amazon_sales_daily(asin,date,fulfillment,units,sales) values('{asin}','{day}','{ful}',{v[0]},{v[1]:.2f}) "
                 f"on conflict(asin,date,fulfillment) do update set units=excluded.units,sales=excluded.sales,archived_at=now();")
lines.append("commit;")
p=subprocess.run(["ssh","-i",KEY,"-o","BatchMode=yes",VPS,"docker exec -i bcc-prod-postgres psql -U bcc -d bcc -v ON_ERROR_STOP=1"],
                 input="\n".join(lines),capture_output=True,text=True,timeout=900)
if p.returncode!=0: print(p.stderr[-400:],file=sys.stderr); sys.exit(1)
print(f"[sales] wrote {len(agg)} rows ({len(fba_rows)} FBA)")
