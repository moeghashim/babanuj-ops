#!/usr/bin/env python3
"""amazon-ads-audit.py — Sponsored Products structure audit → Command Center.

Pulls the ENABLED Sponsored Products structure (campaigns, ad groups, product
ads, keywords, targeting clauses) straight from the Amazon Ads v3 API, audits it
against the 1-1-5 container doctrine, and writes ONE JSONB snapshot into the
Command Center Postgres (`dashboard_ads_audit_snapshots`) so the ops-dashboard
"Amazon Ads Audit" panel can read it. Also drops a JSON artifact under
~/babanuj-ops/amazon-ads/ and logs a sync_run.

Mirrors amazon-ads-report.py: reads creds from the amazon-ads-pp-cli .env,
refreshes the LWA token, talks REST. Read-only against Amazon; write-only to the
LOCAL Command Center Postgres (DATABASE_URL). Never mutates an ad account.

Usage:
  DATABASE_URL=postgres://bcc:bcc@localhost:5433/bcc amazon-ads-audit.py [--top-cannibalization 60]
"""
import os, sys, json, time, argparse, urllib.request, urllib.error, urllib.parse
from datetime import datetime, timezone
from collections import defaultdict, Counter

ENV = os.path.expanduser("~/.config/amazon-ads-pp-cli/.env")
OUTDIR = os.path.expanduser("~/babanuj-ops/amazon-ads")
HOST = "https://advertising-api.amazon.com"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"

LIST = {
    "campaigns": ("/sp/campaigns/list", "application/vnd.spCampaign.v3+json", "campaigns"),
    "adGroups":  ("/sp/adGroups/list",  "application/vnd.spAdGroup.v3+json", "adGroups"),
    "productAds":("/sp/productAds/list", "application/vnd.spProductAd.v3+json", "productAds"),
    "keywords":  ("/sp/keywords/list",  "application/vnd.spKeyword.v3+json", "keywords"),
    "targets":   ("/sp/targets/list",   "application/vnd.spTargetingClause.v3+json", "targetingClauses"),
}


def load_env(path):
    env = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def refresh_token(env):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": env["AMAZON_ADS_REFRESH_TOKEN"],
        "client_id": env["AMAZON_ADS_CLIENT_ID"],
        "client_secret": env["AMAZON_ADS_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode())["access_token"]


def make_post(access, env):
    # The working header combo: token uses CLIENT_ID+SECRET; the API-ClientId
    # header uses AMAZON_ADS_API_CLIENT_ID (falls back to AMAZON_ADS_CLIENT_ID).
    cid = env.get("AMAZON_ADS_API_CLIENT_ID") or env["AMAZON_ADS_CLIENT_ID"]
    prof = env["AMAZON_ADS_PROFILE_ID"]

    def post(path, ct, body):
        req = urllib.request.Request(HOST + path, data=json.dumps(body).encode(),
            headers={"Authorization": "Bearer " + access,
                     "Amazon-Advertising-API-ClientId": cid,
                     "Amazon-Advertising-API-Scope": prof,
                     "Content-Type": ct, "Accept": ct}, method="POST")
        with urllib.request.urlopen(req, timeout=90) as r:
            return json.load(r)
    return post


def pull(post, path, ct, key, campaign_ids=None):
    """Paginate a v3 list endpoint. If campaign_ids given, batch-filter to them."""
    items = []
    batches = [campaign_ids[i:i+100] for i in range(0, len(campaign_ids), 100)] if campaign_ids else [None]
    for batch in batches:
        tok = None
        while True:
            body = {"maxResults": 500, "includeExtendedDataFields": True}
            if batch is not None:
                body["campaignIdFilter"] = {"include": batch}
            if tok:
                body["nextToken"] = tok
            for _ in range(4):
                try:
                    d = post(path, ct, body); break
                except urllib.error.HTTPError as e:
                    if e.code in (429, 500, 502, 503):
                        time.sleep(2); continue
                    raise
            items += d.get(key, [])
            tok = d.get("nextToken")
            if not tok:
                break
    return items


def pull_portfolios(post):
    """List all portfolios (id → name/state). Small list, minimal body."""
    ct = "application/vnd.spPortfolio.v3+json"
    items, tok = [], None
    while True:
        body = {"nextToken": tok} if tok else {}
        for _ in range(4):
            try:
                d = post("/portfolios/list", ct, body); break
            except urllib.error.HTTPError as e:
                if e.code in (429, 500, 502, 503):
                    time.sleep(2); continue
                raise
        items += d.get("portfolios", [])
        tok = d.get("nextToken")
        if not tok:
            break
    return items


def classify(cid, camps, kw_by_c, tg_by_c):
    c = camps.get(cid)
    if not c:
        return "unknown"
    if c.get("targetingType") == "AUTO":
        return "Auto"
    mts = {k["matchType"] for k in kw_by_c[cid]}
    prod = any(t.get("expressionType") == "MANUAL"
               or any(str(e.get("type", "")).startswith("ASIN") for e in (t.get("expression") or []))
               for t in tg_by_c[cid])
    if mts == {"EXACT"}: return "Exact"
    if mts == {"PHRASE"}: return "Phrase"
    if mts == {"BROAD"}: return "Broad"
    if mts: return "Manual-mixed(" + "/".join(sorted(m[0] for m in mts)) + ")"
    if prod: return "ProductTarget"
    return "Manual-empty"


def build_audit(data, top_cannibal, portfolios=None):
    camps = {c["campaignId"]: c for c in data["campaigns"] if c.get("state") == "ENABLED"}
    eids = list(camps)
    ags = [a for a in data["adGroups"] if a["campaignId"] in camps]
    pads = [p for p in data["productAds"] if p["campaignId"] in camps]
    kws = [k for k in data["keywords"] if k["campaignId"] in camps]
    tgs = [t for t in data["targets"] if t["campaignId"] in camps]

    kw_by_c = defaultdict(list); [kw_by_c[k["campaignId"]].append(k) for k in kws]
    tg_by_c = defaultdict(list); [tg_by_c[t["campaignId"]].append(t) for t in tgs]
    ag_by_c = defaultdict(list); [ag_by_c[a["campaignId"]].append(a) for a in ags]
    cls = {cid: classify(cid, camps, kw_by_c, tg_by_c) for cid in eids}

    # Portfolio names, and each campaign's portfolio (None = campaign sits outside any portfolio).
    port_name = {p["portfolioId"]: p.get("name") for p in (portfolios or [])}
    camp_port = {c: camps[c].get("portfolioId") for c in eids}
    # Per-campaign 1-1-5 violations (Exact >1 kw, Broad/Phrase >5 kw, >1 ad group).
    v_exact_c = {c for c in eids if cls[c] == "Exact" and len(kw_by_c[c]) > 1}
    v_bp_c = {c for c in eids if cls[c] in ("Broad", "Phrase") and len(kw_by_c[c]) > 5}
    v_ag_c = {c for c in eids if len(ag_by_c[c]) > 1}

    live = lambda x: x.get("state") == "ENABLED"
    asin_camps = defaultdict(set); asin_ads = defaultdict(int)
    for p in pads:
        if live(p) and p.get("asin"):
            asin_camps[p["asin"]].add(p["campaignId"]); asin_ads[p["asin"]] += 1

    def recommend(missing, viol, n_ports, n_camps):
        """Structural (doctrine-diff) recommendations for one ASIN. No efficiency
        math — anchors are unset; see strategy.md 1-1-5 container + portfolio rule."""
        recs = []
        if "Auto" in missing:
            recs.append("Add 1 Auto campaign (split loose / close / substitutes / complements).")
        if "Exact" in missing:
            recs.append("Add Exact campaign(s) — 1 keyword each — from graduated discovery winners.")
        if "Broad/Phrase" in missing:
            recs.append("Add 1 discovery campaign (Broad or Phrase, ≤5 keywords).")
        if viol["exact_multi_kw"]:
            recs.append(f"Split {viol['exact_multi_kw']} Exact campaign(s) to 1 keyword each.")
        if viol["broadphrase_over5"]:
            recs.append(f"Trim/split {viol['broadphrase_over5']} Broad/Phrase campaign(s) over 5 keywords.")
        if viol["multi_adgroup"]:
            recs.append(f"Consolidate {viol['multi_adgroup']} campaign(s) to one ad group each.")
        if n_ports > 1:
            recs.append(f"ASIN spans {n_ports} portfolios — consolidate to one portfolio per parent ASIN.")
        elif n_ports == 0 and n_camps:
            recs.append("Campaigns sit outside any portfolio — assign to the parent ASIN's portfolio.")
        return recs

    asins = []
    for asin, cids in asin_camps.items():
        types = Counter(cls[c] for c in cids)
        has_auto = types.get("Auto", 0) > 0
        has_exact = types.get("Exact", 0) > 0
        has_bp = types.get("Broad", 0) + types.get("Phrase", 0) > 0
        missing = ([] if has_auto else ["Auto"]) + ([] if has_exact else ["Exact"]) + ([] if has_bp else ["Broad/Phrase"])
        viol = {"exact_multi_kw": sum(1 for c in cids if c in v_exact_c),
                "broadphrase_over5": sum(1 for c in cids if c in v_bp_c),
                "multi_adgroup": sum(1 for c in cids if c in v_ag_c)}
        pids = {camp_port[c] for c in cids if camp_port.get(c)}
        ports = sorted(({"id": str(pid), "name": port_name.get(pid)} for pid in pids),
                       key=lambda p: (p["name"] or ""))
        has_viol = any(viol.values()) or len(pids) > 1
        status = "violations" if has_viol else ("gaps" if missing else "compliant")
        asins.append({"asin": asin, "n_campaigns": len(cids), "n_product_ads": asin_ads[asin],
                      "types": dict(types), "has_auto": has_auto, "has_exact": has_exact,
                      "has_broad_phrase": has_bp, "missing": missing,
                      "violations": viol, "portfolios": ports, "n_portfolios": len(pids),
                      "status": status,
                      "recommendations": recommend(missing, viol, len(pids), len(cids))})
    # Worst-first: violations, then gaps, then compliant; ties by campaign count.
    _rank = {"violations": 0, "gaps": 1, "compliant": 2}
    asins.sort(key=lambda r: (_rank[r["status"]], -r["n_campaigns"]))

    v_exact_multi = len(v_exact_c)
    v_bp_over5 = len(v_bp_c)
    v_multi_ag = len(v_ag_c)

    # Per-portfolio rollup: each ASIN's parent portfolio (the one holding most of
    # its campaigns); ASINs whose campaigns span >1 portfolio are flagged split.
    asin_primary_port = {}
    for asin, cids in asin_camps.items():
        pc = Counter(camp_port[c] for c in cids if camp_port.get(c))
        asin_primary_port[asin] = pc.most_common(1)[0][0] if pc else None
    by_status = {a["asin"]: a["status"] for a in asins}
    NONE = "__none__"
    port_roll = defaultdict(lambda: {"asins": [], "n_campaigns": 0})
    for asin, cids in asin_camps.items():
        pid = asin_primary_port[asin]  # None for portfolio-less; else the API's portfolioId
        r = port_roll[pid if pid is not None else NONE]
        r["asins"].append(asin); r["n_campaigns"] += len(cids)
    portfolios_out = []
    for pid, r in port_roll.items():
        st = Counter(by_status[a] for a in r["asins"])
        is_none = pid == NONE
        portfolios_out.append({
            "portfolio_id": None if is_none else str(pid),
            "name": "(no portfolio)" if is_none else (port_name.get(pid) or str(pid)),
            "n_asins": len(r["asins"]), "n_campaigns": r["n_campaigns"],
            "compliant": st.get("compliant", 0), "gaps": st.get("gaps", 0),
            "violations": st.get("violations", 0),
            "asins": sorted(r["asins"])})
    portfolios_out.sort(key=lambda p: (-(p["gaps"] + p["violations"]), -p["n_asins"]))

    kwmap = defaultdict(set)
    for k in kws:
        if live(k):
            kwmap[(k["keywordText"].lower().strip(), k["matchType"])].add(k["campaignId"])
    cannib = [{"keyword": t, "match": m, "campaigns": len(cs)} for (t, m), cs in kwmap.items() if len(cs) > 1]
    cannib.sort(key=lambda x: -x["campaigns"])

    return {
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "scope": "sp_enabled",
        "summary": {
            "campaigns": len(camps), "ad_groups": len(ags), "product_ads": len(pads),
            "keywords": len(kws), "targets": len(tgs), "asins": len(asin_camps),
            "portfolios": len(portfolios_out),
            "type_mix": dict(Counter(cls[c] for c in eids)),
            "compliance": {
                "compliant": sum(1 for r in asins if r["status"] == "compliant"),
                "gaps": sum(1 for r in asins if r["status"] == "gaps"),
                "violations": sum(1 for r in asins if r["status"] == "violations"),
            },
            "gaps": {
                "missing_auto": sum(1 for r in asins if not r["has_auto"]),
                "missing_exact": sum(1 for r in asins if not r["has_exact"]),
                "no_broad_phrase": sum(1 for r in asins if not r["has_broad_phrase"]),
                "single_campaign": sum(1 for r in asins if r["n_campaigns"] == 1),
                "multi_portfolio": sum(1 for r in asins if r["n_portfolios"] > 1),
                "no_portfolio": sum(1 for r in asins if r["n_portfolios"] == 0),
            },
            "violations": {"exact_multi_kw": v_exact_multi, "broadphrase_over5": v_bp_over5, "multi_adgroup": v_multi_ag},
            "cannibalized_keywords": len(cannib),
        },
        "asins": asins,
        "portfolios": portfolios_out,
        "cannibalization": cannib[:top_cannibal],
    }


def write_pg(payload):
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("[audit] DATABASE_URL not set — skipping Postgres write")
        return False
    import psycopg2
    conn = psycopg2.connect(dsn)
    try:
        with conn, conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_ads_audit_snapshots (
                  id          BIGSERIAL PRIMARY KEY,
                  platform    TEXT NOT NULL DEFAULT 'amazon_sp',
                  captured_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                  payload     JSONB NOT NULL
                )""")
            cur.execute("""
                CREATE INDEX IF NOT EXISTS dashboard_ads_audit_latest_idx
                ON dashboard_ads_audit_snapshots (platform, captured_at DESC)""")
            cur.execute(
                "INSERT INTO dashboard_ads_audit_snapshots (platform, payload) VALUES (%s, %s::jsonb)",
                ("amazon_sp", json.dumps(payload)))
            cur.execute("""
                CREATE TABLE IF NOT EXISTS sync_runs (
                  id bigserial primary key, source text not null,
                  finished_at timestamptz not null default now(), ok boolean not null default true)""")
            cur.execute("INSERT INTO sync_runs (source, ok) VALUES ('amazon_ads_audit', true)")
        print("[audit] wrote snapshot + sync_run to Postgres")
        return True
    finally:
        conn.close()


def main():
    ap = argparse.ArgumentParser(description="Sponsored Products structure audit → Command Center.")
    ap.add_argument("--top-cannibalization", type=int, default=60)
    args = ap.parse_args()

    env = load_env(ENV)
    print("[auth] refreshing LWA access token…")
    access = refresh_token(env)
    post = make_post(access, env)

    print("[pull] campaigns…")
    all_camps = pull(post, *LIST["campaigns"])
    eids = [c["campaignId"] for c in all_camps if c.get("state") == "ENABLED"]
    print(f"[pull] {len(all_camps)} campaigns total, {len(eids)} enabled — pulling children scoped to enabled…")
    data = {"campaigns": [c for c in all_camps if c.get("state") == "ENABLED"]}
    for name in ("adGroups", "productAds", "keywords", "targets"):
        path, ct, key = LIST[name]
        data[name] = pull(post, path, ct, key, campaign_ids=eids)
        print(f"[pull] {name}: {len(data[name])}")

    print("[pull] portfolios…")
    portfolios = pull_portfolios(post)
    print(f"[pull] portfolios: {len(portfolios)}")

    audit = build_audit(data, args.top_cannibalization, portfolios)
    s = audit["summary"]
    print(f"\n[audit] {s['campaigns']} campaigns · {s['asins']} ASINs · {s['portfolios']} portfolios · "
          f"compliance {s['compliance']} · gaps {s['gaps']} · violations {s['violations']} · "
          f"cannibalized {s['cannibalized_keywords']}")

    os.makedirs(OUTDIR, exist_ok=True)
    day = audit["captured_at"][:10]
    art = os.path.join(OUTDIR, f"asin-audit-{day}.json")
    json.dump(audit, open(art, "w"), indent=1)
    print(f"[audit] artifact → {art}")
    write_pg(audit)


if __name__ == "__main__":
    main()
