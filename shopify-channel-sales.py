#!/usr/bin/env python3
"""shopify-channel-sales.py — per-CHANNEL, per-product Shopify sales → prod bcc.

Every sales channel lives in Shopify (website, Walmart, Temu, TikTok Shop, …)
except Amazon FBA. The existing shopify-sync collapses all of them into
"website"; this records the channel dimension so /performance can split them.

  shopify-channel-sales.py [--days 60]       # rolling 60-day window; history accrues via upsert

Table: shopify_channel_sales_daily(date, channel, product_handle, product_title, units, sales)
Sales = price actually charged (after all discounts) minus refunds. Cancelled and
unpaid (pending/voided/expired) orders are excluded. Each run replaces every full day
in its window, so orders deleted or edited in Shopify drop out; older days are kept.
"""
import importlib.util, os, sys, json, subprocess
from datetime import date, timedelta
spec=importlib.util.spec_from_file_location("shop", os.path.expanduser("~/babanuj-ops/shopify-sync.py"))
S=importlib.util.module_from_spec(spec); spec.loader.exec_module(S)
DAYS=int(sys.argv[sys.argv.index("--days")+1]) if "--days" in sys.argv else 60  # rolling window; upserts accumulate history
VPS=os.environ["BCC_VPS"]; KEY=os.path.expanduser(os.environ.get("BCC_SSH_KEY", "~/.ssh/babanuj_deploy"))

UNPAID = {"PENDING", "VOIDED", "EXPIRED"}

QUERY = """
query($q: String!, $cursor: String) {
  orders(first: 100, after: $cursor, query: $q, sortKey: CREATED_AT, reverse: false) {
    pageInfo { hasNextPage endCursor }
    edges { node {
      createdAt test displayFinancialStatus cancelledAt
      refunds { refundLineItems(first: 100) { edges { node {
        quantity subtotalSet { shopMoney { amount } } lineItem { product { handle } } } } } }
      channelInformation { channelDefinition { handle channelName } }
      lineItems(first: 100) { edges { node {
        quantity product { handle title }
        discountedUnitPriceAfterAllDiscountsSet { shopMoney { amount } } } } }
    } }
  }
}
"""

def main():
    sh=S.Shopify()
    end=date.today(); start=end-timedelta(days=DAYS)
    q=f"created_at:>={start.isoformat()} created_at:<={end.isoformat()}"
    agg={}; cursor=None; n=0
    while True:
        d=sh.gql(QUERY, {"q": q, "cursor": cursor})
        orders=(d.get("data") or d)["orders"]
        for e in orders["edges"]:
            o=e["node"]
            if o.get("test") or o.get("cancelledAt"): continue
            if o.get("displayFinancialStatus") in UNPAID: continue
            ci=(o.get("channelInformation") or {}).get("channelDefinition") or {}
            channel=(ci.get("channelName") or ci.get("handle") or "online-store").strip()
            # Shop app and Headless storefront are the same selling channel as the
            # online store (Moe, 2026-07-25) — fold them in so the split stays true.
            if channel.lower() in ("shop","headless","online store","online-store"):
                channel="Online Store"
            day=o["createdAt"][:10]
            if day<=start.isoformat(): continue  # partial first day: keep the archived row
            for le in o["lineItems"]["edges"]:
                li=le["node"]; prod=li.get("product") or {}
                h=prod.get("handle")
                if not h: continue
                price=float(li["discountedUnitPriceAfterAllDiscountsSet"]["shopMoney"]["amount"])
                qty=int(li.get("quantity") or 0)
                k=(day,channel,h)
                v=agg.setdefault(k,[prod.get("title") or "",0,0.0])
                v[1]+=qty; v[2]+=price*qty
            for r in o.get("refunds") or []:
                for re_ in r["refundLineItems"]["edges"]:
                    ri=re_["node"]; h=((ri.get("lineItem") or {}).get("product") or {}).get("handle")
                    k=(day,channel,h)
                    if not h or k not in agg: continue
                    agg[k][1]-=int(ri.get("quantity") or 0)
                    agg[k][2]-=float(ri["subtotalSet"]["shopMoney"]["amount"])
            n+=1
        if not orders["pageInfo"]["hasNextPage"]: break
        cursor=orders["pageInfo"]["endCursor"]
    print(f"orders scanned: {n}; rows: {len(agg)}", file=sys.stderr)
    lines=["begin;","""create table if not exists shopify_channel_sales_daily(
      date date not null, channel text not null, product_handle text not null,
      product_title text, units integer not null default 0,
      sales numeric(12,2) not null default 0,
      updated_at timestamptz not null default now(),
      primary key(date, channel, product_handle));""",
      f"delete from shopify_channel_sales_daily where date>'{start.isoformat()}' and date<='{end.isoformat()}';"]
    for (day,channel,h),v in agg.items():
        lines.append("insert into shopify_channel_sales_daily(date,channel,product_handle,product_title,units,sales) "
                     f"values('{day}',$q${channel}$q$,$q${h}$q$,$q${v[0]}$q$,{v[1]},{v[2]:.2f}) "
                     "on conflict(date,channel,product_handle) do update set units=excluded.units,"
                     "sales=excluded.sales,product_title=excluded.product_title,updated_at=now();")
    lines.append("commit;")
    p=subprocess.run(["ssh","-i",KEY,"-o","BatchMode=yes",VPS,
                      "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                     input="\n".join(lines),capture_output=True,text=True,timeout=900)
    if p.returncode!=0: print(p.stderr[-400:], file=sys.stderr); sys.exit(1)
    chans=sorted({c for _,c,_ in agg})
    print(f"[channels] {len(agg)} day-channel-product rows; channels seen: {chans}")

if __name__=="__main__": main()
