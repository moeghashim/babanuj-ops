#!/usr/bin/env python3
"""product-catalog-sync-prod.py — populate the prod Command Center bcc with the
Amazon + Shopify product catalogs and name-match SUGGESTIONS, for the
ops.babanuj.com Product Matching UI.

- Amazon: ASINs+SKUs from the SP ads pull; title+image from the seller Catalog API.
- Shopify: handle/title/price/image via the Admin API (read-only creds).
- Suggestions: brand-agnostic variety+size name match (operator confirms in the UI).
- Writes amazon_products, shopify_products, product_crosswalk to prod bcc over SSH.
  product_crosswalk upsert NEVER overwrites the operator's manual shopify_handle /
  amazon_only — it only refreshes suggested_handle/score.

Amazon creds stay on this Mac; prod bcc (no host port) is reached via the
babanuj_deploy SSH key + `docker exec psql`.
"""
import os, sys, json, re, subprocess, urllib.request, urllib.parse, gzip, time

HOME = os.path.expanduser("~")
VPS = "root@<vps-host>"
KEY = f"{HOME}/.ssh/babanuj_deploy"
MKT = "ATVPDKIKX0DER"
ADS = "/private/tmp/claude-501/-Users-moeghashim-marketing/8cc4d981-9321-43a0-a641-daa0fa40ac24/scratchpad/amz-audit/productads.json"

# ---------- name-match (compact) ----------
CANON = {
 "sukkari":["sukkari","sukari","sukary"],"safawi":["safawi"],"ajwa":["ajwa"],
 "khodhri":["khodhri","khudri","khodri","khudari"],"mabroom":["mabroom","mabroum"],
 "khalas":["khalas"],"medjool":["medjool","medjoul"],"sagaie":["sagaie","saghai"],
 "goldenmix":["golden mix","goldenmix","mixed dates","date mix"],"maamoul":["maamoul","mamoul","mamool"],
 "barazek":["barazek"],"graybah":["graybah","ghraybeh","ghraybah"],"tamriah":["tamriah"],
 "cola":["cola"],"coffee":["coffee","espresso","date seed","brewdates","groundate","datespresso"],
 "baklava":["baklava","baklawa"],"honey":["honey"],"walnut":["walnut"],"pistachio":["pistachio"],
 "kunafa":["kunafa","kunafah","knafeh"],"vegan":["vegan"],"biscuit":["biscuit","cookie"],"date":["dates","date"]}
STRONG={"sukkari","safawi","ajwa","khodhri","mabroom","khalas","medjool","sagaie","goldenmix","cola","coffee","kunafa"}
def toks(t):
    t=re.sub(r"[^a-z0-9 ]"," ",(t or "").lower()); f=set()
    for c,vs in CANON.items():
        if any(v in t for v in vs): f.add(c)
    return f
def szs(t):
    t=(t or "").lower(); o=set()
    for m in re.finditer(r"(\d+(?:\.\d+)?)\s?(g|kg|oz|ml|l|pcs)\b",t): o.add(m.group(1))
    return o
def score(at,asz,st,ssz):
    if not at or not st: return 0.0
    inter=at&st
    if not inter: return 0.0
    j=len(inter)/len(at|st); sb=0.25 if asz&ssz else 0.0; xb=0.2 if inter&STRONG else 0.0
    return round(min(1.0,j+sb+xb),2)

def load_env(p):
    e={}
    for l in open(p):
        l=l.strip()
        if l and not l.startswith("#") and "=" in l:
            k,v=l.split("=",1); e[k.strip()]=v.strip().strip('"').strip("'")
    return e

# ---------- Shopify ----------
def shopify_pull():
    env=load_env(f"{HOME}/.config/shopify-pp-cli/.env")
    body=urllib.parse.urlencode({"client_id":env["SHOPIFY_CLIENT_ID"],"client_secret":env["SHOPIFY_CLIENT_SECRET"],"grant_type":"client_credentials"}).encode()
    tok=json.load(urllib.request.urlopen(urllib.request.Request(f"https://{env['SHOPIFY_STORE_DOMAIN']}/admin/oauth/access_token",data=body,method="POST"),timeout=30))["access_token"]
    url=f"https://{env['SHOPIFY_STORE_DOMAIN']}/admin/api/2026-04/graphql.json"; items=[]; cur=None
    while True:
        after=f', after: "{cur}"' if cur else ""
        q='{ products(first:100'+after+'){pageInfo{hasNextPage endCursor} edges{node{handle title status featuredImage{url} priceRangeV2{minVariantPrice{amount}}}}} }'
        d=json.load(urllib.request.urlopen(urllib.request.Request(url,data=json.dumps({"query":q}).encode(),headers={"Content-Type":"application/json","X-Shopify-Access-Token":tok},method="POST"),timeout=45))
        p=d["data"]["products"]
        for e in p["edges"]:
            n=e["node"]; img=(n.get("featuredImage") or {}).get("url")
            price=((n.get("priceRangeV2") or {}).get("minVariantPrice") or {}).get("amount")
            items.append({"handle":n["handle"],"title":n["title"],"status":n.get("status"),"image":img,"price":price})
        if p["pageInfo"]["hasNextPage"]: cur=p["pageInfo"]["endCursor"]
        else: break
    return items

# ---------- Amazon ----------
def amazon_pull():
    pads=json.load(open(ADS)); seen={}
    for p in pads:
        a=p.get("asin")
        if a and a not in seen: seen[a]=p.get("sku")
    out=[]
    for i,(asin,sku) in enumerate(seen.items()):
        title=image=None
        try:
            r=subprocess.run(["amazon-seller-pp-cli","catalog","get",asin,"--marketplace-ids",MKT,
                              "--included-data","summaries,images","--agent"],capture_output=True,text=True,timeout=40).stdout
            res=json.loads(r).get("results",{})
            s=(res.get("summaries") or [{}])[0]; title=s.get("itemName")
            imgs=res.get("images") or []
            if imgs:
                lst=imgs[0].get("images") or []
                if lst: image=sorted(lst,key=lambda x:-(x.get("width",0)))[0].get("link")
        except Exception: pass
        out.append({"asin":asin,"sku":sku,"title":title,"image":image})
        if (i+1)%20==0: print(f"  amazon {i+1}/{len(seen)}",file=sys.stderr)
    return out

def amazon_prices():
    """asin -> selling price, from a GET_MERCHANT_LISTINGS_ALL_DATA report.
    One report covers every active listing (SKU, ASIN, price) — far cheaper than
    a per-SKU Listings-API call. Returns {} on any failure so the sync still runs
    (prices just stay whatever they were; the dashboard falls back to 'Listed')."""
    def cli(args, inp=None, t=60):
        return subprocess.run(["amazon-seller-pp-cli", *args, "--agent"],
                              input=inp, capture_output=True, text=True, timeout=t).stdout
    try:
        rid = json.loads(cli(["reports", "create", "--stdin"],
              inp=json.dumps({"reportType": "GET_MERCHANT_LISTINGS_ALL_DATA",
                              "marketplaceIds": [MKT]})))["data"]["reportId"]
    except Exception as e:
        print(f"[amazon-price] create failed: {e}", file=sys.stderr); return {}
    docid = None
    for _ in range(60):  # ~20 min ceiling; reports usually finish in <2 min
        try:
            r = json.loads(cli(["reports", "get", rid]))["results"]
            st = r["processingStatus"]
            if st == "DONE": docid = r["reportDocumentId"]; break
            if st in ("FATAL", "CANCELLED"):
                print(f"[amazon-price] report {st}", file=sys.stderr); return {}
        except Exception: pass
        time.sleep(20)
    if not docid:
        print("[amazon-price] report never finished", file=sys.stderr); return {}
    try:
        doc = json.loads(cli(["reports", "document", docid]))["results"]
        raw = urllib.request.urlopen(doc["url"], timeout=60).read()
        text = gzip.decompress(raw).decode("utf-8", "replace") \
            if doc.get("compressionAlgorithm") == "GZIP" else raw.decode("utf-8", "replace")
        lines = text.splitlines()
        hdr = [h.lstrip("﻿") for h in lines[0].split("\t")]
        ia, ip = hdr.index("asin1"), hdr.index("price")
        out = {}
        for ln in lines[1:]:
            c = ln.split("\t")
            if len(c) <= max(ia, ip): continue
            a, p = c[ia].strip(), c[ip].strip()
            if a and p:
                try: out[a] = float(p)
                except ValueError: pass
        return out
    except Exception as e:
        print(f"[amazon-price] parse failed: {e}", file=sys.stderr); return {}

def sql_lit(s):
    if s is None: return "NULL"
    return "$q$"+str(s)+"$q$"

def main():
    if "--amz-creds" in sys.argv: pass
    print("[shopify] pull…",file=sys.stderr); shop=shopify_pull(); print(f"[shopify] {len(shop)}",file=sys.stderr)
    print("[amazon] pull catalog…",file=sys.stderr); amz=amazon_pull(); print(f"[amazon] {len(amz)}",file=sys.stderr)
    print("[amazon] pull prices…",file=sys.stderr); prices=amazon_prices(); print(f"[amazon] {len(prices)} priced",file=sys.stderr)

    # suggestions
    shop_sig=[(toks(s["handle"].replace("-"," ")+" "+s["title"]), szs(s["handle"]+" "+s["title"]), s) for s in shop]
    sugg={}
    for a in amz:
        at,asz=toks((a["sku"] or "")+" "+(a["title"] or "")),szs((a["sku"] or "")+" "+(a["title"] or ""))
        best=(0,None)
        for st,ssz,s in shop_sig:
            sc=score(at,asz,st,ssz)
            if sc>best[0]: best=(sc,s["handle"])
        sugg[a["asin"]]=best

    lines=["begin;",
      "create table if not exists amazon_products(asin text primary key, sku text, title text, image_url text, price numeric(10,2), updated_at timestamptz not null default now());",
      "create table if not exists shopify_products(handle text primary key, title text not null, price numeric(10,2), image_url text, status text, updated_at timestamptz not null default now());",
      "create table if not exists product_crosswalk(amazon_asin text primary key, shopify_handle text, amazon_only boolean not null default false, suggested_handle text, suggested_score numeric, updated_at timestamptz not null default now());"]
    for s in shop:
        lines.append(f"insert into shopify_products(handle,title,price,image_url,status) values({sql_lit(s['handle'])},{sql_lit(s['title'])},{s['price'] or 'NULL'},{sql_lit(s['image'])},{sql_lit(s['status'])}) on conflict(handle) do update set title=excluded.title,price=excluded.price,image_url=excluded.image_url,status=excluded.status,updated_at=now();")
    for a in amz:
        pr = prices.get(a["asin"])
        prlit = f"{pr:.2f}" if pr is not None else "NULL"
        # coalesce keeps a prior price when this report didn't cover the ASIN.
        lines.append(f"insert into amazon_products(asin,sku,title,image_url,price) values({sql_lit(a['asin'])},{sql_lit(a['sku'])},{sql_lit(a['title'])},{sql_lit(a['image'])},{prlit}) on conflict(asin) do update set sku=excluded.sku,title=excluded.title,image_url=excluded.image_url,price=coalesce(excluded.price,amazon_products.price),updated_at=now();")
    for a in amz:
        sc,h=sugg[a["asin"]]
        lines.append(f"insert into product_crosswalk(amazon_asin,suggested_handle,suggested_score) values({sql_lit(a['asin'])},{sql_lit(h)},{sc}) on conflict(amazon_asin) do update set suggested_handle=excluded.suggested_handle,suggested_score=excluded.suggested_score;")
    lines.append("commit;")
    sqltext="\n".join(lines)

    print("[prod] writing to bcc via ssh…",file=sys.stderr)
    p=subprocess.run(["ssh","-i",KEY,"-o","BatchMode=yes","-o","ConnectTimeout=20",VPS,
                      "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                     input=sqltext,capture_output=True,text=True,timeout=120)
    print(p.stdout[-500:]);
    if p.returncode!=0: print("STDERR:",p.stderr[-500:]); sys.exit(1)
    print(f"[done] shopify={len(shop)} amazon={len(amz)} matched-suggestions written")

if __name__=="__main__":
    main()
