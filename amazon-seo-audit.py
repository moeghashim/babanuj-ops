#!/usr/bin/env python3
"""amazon-seo-audit.py — per-ASIN Amazon SEO audit → prod Command Center.

Scores every advertised ASIN against Amazon listing-SEO standards and measures
how much of its demand is earned (organic) versus bought (ads).

Inputs (all read-only):
  - Sales & Traffic report (per ASIN): sessions, page views, buy-box %,
    unit-session % (conversion), units + TOTAL ordered product sales.
  - Catalog Items (per ASIN): title, bullets, description, images.
  - SP search-term report: the queries that actually converted for the ASIN —
    used as the keyword signal that the listing should cover.
  - amazon_products.ad_sales_30d (already in bcc): ad-attributed sales, so
    organic = total − ad.

Scoring is deliberately explicit: each check states the standard, the observed
value, and a verdict. No opaque composite — the operator must be able to see
why an ASIN scored what it did, and what to change.

Writes ONE JSONB snapshot to dashboard_seo_snapshots (mirrors the ads-audit
pattern). Amazon creds stay on this Mac; prod is reached over SSH.

    python3 amazon-seo-audit.py            # artifact only
    python3 amazon-seo-audit.py --push     # + write to prod bcc
"""
import json, os, re, sys, gzip, time, subprocess, urllib.request
from collections import defaultdict
from datetime import datetime, timezone, timedelta

HOME = os.path.expanduser("~")
OPS = f"{HOME}/babanuj-ops"
OUTDIR = f"{OPS}/amazon-seo"
VPS = "root@<vps-host>"
KEY = f"{HOME}/.ssh/babanuj_deploy"
MKT = "ATVPDKIKX0DER"

# --- Amazon listing-SEO standards (the bar each check is judged against) ---
TITLE_MIN, TITLE_MAX = 80, 200          # under 80 wastes indexable space; over 200 truncates
BULLETS_EXPECTED = 5                     # Amazon allows 5; fewer = lost keyword surface
BULLET_MIN_CHARS = 100                   # thin bullets carry little keyword weight
IMAGES_MIN = 6                           # main + 5; below this conversion suffers
DESC_MIN_CHARS = 200
CVR_HEALTHY = 10.0                       # unit-session % — below this the listing, not the ad, is the problem
BUYBOX_MIN = 90.0


def sh(args, inp=None, t=120):
    return subprocess.run(args, input=inp, capture_output=True, text=True, timeout=t).stdout


def cli(args, inp=None, t=120):
    return sh(["amazon-seller-pp-cli", *args, "--agent"], inp, t)


def sales_traffic(days=30):
    """asin -> traffic/sales facts from the Sales & Traffic report."""
    end = datetime.now(timezone.utc).date() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    body = {"reportType": "GET_SALES_AND_TRAFFIC_REPORT", "marketplaceIds": [MKT],
            "reportOptions": {"dateGranularity": "DAY", "asinGranularity": "CHILD"},
            "dataStartTime": f"{start}T00:00:00Z", "dataEndTime": f"{end}T00:00:00Z"}
    try:
        rid = json.loads(cli(["reports", "create", "--stdin"], json.dumps(body)))["data"]["reportId"]
    except Exception as e:
        print(f"[seo] sales-traffic create failed: {e}", file=sys.stderr); return {}
    docid = None
    for _ in range(60):
        try:
            r = json.loads(cli(["reports", "get", rid]))["results"]
            if r["processingStatus"] == "DONE": docid = r["reportDocumentId"]; break
            if r["processingStatus"] in ("FATAL", "CANCELLED"): return {}
        except Exception: pass
        time.sleep(15)
    if not docid:
        print("[seo] sales-traffic never finished", file=sys.stderr); return {}
    d = json.loads(cli(["reports", "document", docid]))["results"]
    raw = urllib.request.urlopen(d["url"], timeout=90).read()
    txt = gzip.decompress(raw).decode() if d.get("compressionAlgorithm") == "GZIP" else raw.decode()
    agg = defaultdict(lambda: {"sessions": 0, "page_views": 0, "units": 0, "sales": 0.0,
                               "buybox": [], "cvr": []})
    for row in json.loads(txt).get("salesAndTrafficByAsin", []):
        a = row.get("childAsin") or row.get("parentAsin")
        if not a: continue
        t, s = row.get("trafficByAsin", {}), row.get("salesByAsin", {})
        v = agg[a]
        v["sessions"] += int(t.get("sessions", 0) or 0)
        v["page_views"] += int(t.get("pageViews", 0) or 0)
        v["units"] += int(s.get("unitsOrdered", 0) or 0)
        v["sales"] += float((s.get("orderedProductSales") or {}).get("amount", 0) or 0)
        if t.get("buyBoxPercentage") is not None: v["buybox"].append(float(t["buyBoxPercentage"]))
        if t.get("unitSessionPercentage") is not None: v["cvr"].append(float(t["unitSessionPercentage"]))
    out = {}
    for a, v in agg.items():
        out[a] = {"sessions": v["sessions"], "page_views": v["page_views"], "units": v["units"],
                  "sales": round(v["sales"], 2),
                  "buybox_pct": round(sum(v["buybox"]) / len(v["buybox"]), 1) if v["buybox"] else None,
                  # session CVR recomputed from totals — averaging daily percentages skews small days
                  "cvr_pct": round(v["units"] / v["sessions"] * 100, 2) if v["sessions"] else None}
    return out


def listing(asin):
    """Title / bullets / description / image count for one ASIN."""
    try:
        r = json.loads(cli(["catalog", "get", asin, "--marketplace-ids", MKT,
                            "--included-data", "attributes,summaries,images"], t=60)).get("results", {})
    except Exception:
        return None
    a = r.get("attributes", {}) or {}
    val = lambda k: [x.get("value", "") for x in (a.get(k) or []) if isinstance(x, dict)]
    title = (val("item_name") or [""])[0]
    if not title:
        title = ((r.get("summaries") or [{}])[0]).get("itemName", "") or ""
    imgs = (r.get("images") or [{}])[0].get("images", [])
    return {"title": title, "bullets": val("bullet_point"),
            "description": (val("product_description") or [""])[0],
            "n_images": len({i.get("link") for i in imgs if i.get("link")})}


def norm(s):
    return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower())


def score(asin, lst, st, kw, ad_sales):
    """Explicit per-check verdicts + the actions that follow from them."""
    checks, actions = [], []
    title = lst["title"]; tl = len(title)
    if tl < TITLE_MIN:
        checks.append({"check": "title_length", "standard": f"{TITLE_MIN}-{TITLE_MAX} chars",
                       "value": tl, "verdict": "fail"})
        actions.append(f"Lengthen title to ≥{TITLE_MIN} chars — unused indexable space.")
    elif tl > TITLE_MAX:
        checks.append({"check": "title_length", "standard": f"{TITLE_MIN}-{TITLE_MAX} chars",
                       "value": tl, "verdict": "warn"})
        actions.append(f"Trim title below {TITLE_MAX} chars — it truncates in search.")
    else:
        checks.append({"check": "title_length", "standard": f"{TITLE_MIN}-{TITLE_MAX} chars",
                       "value": tl, "verdict": "pass"})

    nb = len(lst["bullets"])
    checks.append({"check": "bullets", "standard": f"{BULLETS_EXPECTED} bullets", "value": nb,
                   "verdict": "pass" if nb >= BULLETS_EXPECTED else "fail"})
    if nb < BULLETS_EXPECTED:
        actions.append(f"Add {BULLETS_EXPECTED - nb} bullet(s) — lost keyword surface.")
    thin = sum(1 for b in lst["bullets"] if len(b) < BULLET_MIN_CHARS)
    if thin:
        checks.append({"check": "bullet_depth", "standard": f"≥{BULLET_MIN_CHARS} chars each",
                       "value": f"{thin} thin", "verdict": "warn"})
        actions.append(f"Expand {thin} thin bullet(s).")

    checks.append({"check": "images", "standard": f"≥{IMAGES_MIN}", "value": lst["n_images"],
                   "verdict": "pass" if lst["n_images"] >= IMAGES_MIN else "fail"})
    if lst["n_images"] < IMAGES_MIN:
        actions.append(f"Add images to reach {IMAGES_MIN}+.")

    dl = len(lst["description"])
    checks.append({"check": "description", "standard": f"≥{DESC_MIN_CHARS} chars", "value": dl,
                   "verdict": "pass" if dl >= DESC_MIN_CHARS else "fail"})
    if dl < DESC_MIN_CHARS:
        actions.append("Write a fuller description / A+ content.")

    # Keyword coverage: do converting search terms appear in title+bullets?
    hay = norm(title + " " + " ".join(lst["bullets"]) + " " + lst["description"])
    covered, missing = [], []
    for term, orders in kw:
        toks = [t for t in norm(term).split() if len(t) > 2]
        (covered if toks and all(t in hay for t in toks) else missing).append(term)
    cov_pct = round(len(covered) / len(kw) * 100) if kw else None
    checks.append({"check": "keyword_coverage", "standard": "converting terms present in copy",
                   "value": f"{len(covered)}/{len(kw)}" if kw else "no signal",
                   "verdict": "pass" if cov_pct is not None and cov_pct >= 70 else
                              ("warn" if cov_pct is not None and cov_pct >= 40 else
                               ("fail" if cov_pct is not None else "n/a"))})
    if missing:
        actions.append(f"Work {min(len(missing),5)} converting term(s) into title/bullets: "
                       + ", ".join(missing[:5]) + ".")

    # Earned vs bought demand — the SEO strength signal
    total = st["sales"] if st else 0.0
    organic = round(total - ad_sales, 2) if total else None
    organic_pct = round(organic / total * 100, 1) if total and organic is not None else None
    if organic_pct is not None:
        checks.append({"check": "organic_share", "standard": "majority of sales earned",
                       "value": f"{organic_pct}%",
                       "verdict": "pass" if organic_pct >= 60 else ("warn" if organic_pct >= 30 else "fail")})
        if organic_pct < 30:
            actions.append("Ad-dependent — organic rank is not carrying this ASIN; fix copy/keywords before scaling spend.")

    if st and st.get("cvr_pct") is not None:
        ok = st["cvr_pct"] >= CVR_HEALTHY
        checks.append({"check": "conversion_rate", "standard": f"≥{CVR_HEALTHY}% unit-session",
                       "value": f"{st['cvr_pct']}%", "verdict": "pass" if ok else "fail"})
        if not ok:
            actions.append("Low session conversion — the listing, not the bid, is losing the sale.")
    if st and st.get("buybox_pct") is not None and st["buybox_pct"] < BUYBOX_MIN:
        checks.append({"check": "buy_box", "standard": f"≥{BUYBOX_MIN}%", "value": f"{st['buybox_pct']}%",
                       "verdict": "fail"})
        actions.append("Buy box below target — price/stock issue suppresses everything else.")

    fails = sum(1 for c in checks if c["verdict"] == "fail")
    warns = sum(1 for c in checks if c["verdict"] == "warn")
    passes = sum(1 for c in checks if c["verdict"] == "pass")
    grade = "strong" if fails == 0 and warns <= 1 else ("weak" if fails >= 3 else "needs work")
    return {"asin": asin, "title": title, "grade": grade,
            "passes": passes, "warns": warns, "fails": fails,
            "sessions": st["sessions"] if st else None,
            "cvr_pct": st.get("cvr_pct") if st else None,
            "buybox_pct": st.get("buybox_pct") if st else None,
            "total_sales": total or None, "ad_sales": ad_sales or None,
            "organic_sales": organic, "organic_pct": organic_pct,
            "keyword_coverage_pct": cov_pct, "n_signal_terms": len(kw),
            "missing_terms": missing[:10], "checks": checks, "actions": actions}


def main():
    push = "--push" in sys.argv
    os.makedirs(OUTDIR, exist_ok=True)

    print("[seo] sales & traffic…", file=sys.stderr)
    st = sales_traffic()
    print(f"[seo] {len(st)} ASINs with traffic", file=sys.stderr)

    # ad sales + the advertised ASIN roster, from prod
    rows = sh(["ssh", "-i", KEY, "-o", "BatchMode=yes", VPS,
               "docker exec bcc-prod-postgres psql -U bcc -d bcc -tAc "
               "\"select asin, coalesce(ad_sales_30d,0) from amazon_products\""], t=120)
    ad = {}
    for line in rows.strip().splitlines():
        if "|" in line:
            a, v = line.split("|", 1)
            try: ad[a.strip()] = float(v)
            except ValueError: pass
    print(f"[seo] {len(ad)} advertised ASINs", file=sys.stderr)

    # keyword signal: converting search terms per ASIN (from the SP search-term pull)
    kw_by_asin = defaultdict(list)
    stp = "/tmp/search_terms.json"
    if os.path.exists(stp):
        aud = sorted(__import__("glob").glob(f"{OPS}/amazon-ads/asin-audit-*.json"))
        camp_asins = defaultdict(set)
        if aud:
            for a in json.load(open(aud[-1]))["asins"]:
                for c in a["evidence"].get("campaigns", []):
                    camp_asins[str(c["id"])].add(a["asin"])
        tmp = defaultdict(lambda: defaultdict(int))
        for r in json.load(open(stp)):
            cid = str(r.get("campaignId")); term = (r.get("searchTerm") or "").strip().lower()
            o = int(float(r.get("purchases30d", 0) or 0))
            if not term or term.startswith("b0") or o < 1: continue
            for a in camp_asins.get(cid, ()):
                tmp[a][term] += o
        for a, d in tmp.items():
            kw_by_asin[a] = sorted(d.items(), key=lambda x: -x[1])[:15]

    results = []
    targets = sorted(ad)
    for i, a in enumerate(targets, 1):
        lst = listing(a)
        if not lst:
            continue
        results.append(score(a, lst, st.get(a), kw_by_asin.get(a, []), ad.get(a, 0.0)))
        if i % 20 == 0: print(f"[seo] {i}/{len(targets)}", file=sys.stderr)

    rank = {"weak": 0, "needs work": 1, "strong": 2}
    results.sort(key=lambda r: (rank[r["grade"]], -(r["total_sales"] or 0)))
    summary = {"asins": len(results),
               "strong": sum(1 for r in results if r["grade"] == "strong"),
               "needs_work": sum(1 for r in results if r["grade"] == "needs work"),
               "weak": sum(1 for r in results if r["grade"] == "weak"),
               "ad_dependent": sum(1 for r in results if (r["organic_pct"] or 100) < 30),
               "low_cvr": sum(1 for r in results if r["cvr_pct"] is not None and r["cvr_pct"] < CVR_HEALTHY),
               "total_sales": round(sum(r["total_sales"] or 0 for r in results), 2),
               "organic_sales": round(sum(r["organic_sales"] or 0 for r in results), 2)}
    payload = {"captured_at": datetime.now(timezone.utc).isoformat(), "channel": "amazon",
               "standards": {"title": [TITLE_MIN, TITLE_MAX], "bullets": BULLETS_EXPECTED,
                             "images_min": IMAGES_MIN, "cvr_healthy": CVR_HEALTHY,
                             "buybox_min": BUYBOX_MIN},
               "summary": summary, "asins": results}
    day = payload["captured_at"][:10]
    art = f"{OUTDIR}/seo-audit-{day}.json"
    json.dump(payload, open(art, "w"), indent=1)
    print(f"\n[seo] {summary}")
    print(f"[seo] artifact → {art}")

    if push:
        sql = ["create table if not exists dashboard_seo_snapshots ("
               "id bigserial primary key, channel text not null default 'amazon',"
               "captured_at timestamptz not null default now(), payload jsonb not null);",
               "create index if not exists dashboard_seo_latest_idx on dashboard_seo_snapshots (channel, captured_at desc);"]
        p = subprocess.run(["ssh", "-i", KEY, "-o", "BatchMode=yes", VPS,
                            "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                           input="\n".join(sql), capture_output=True, text=True, timeout=120)
        if p.returncode != 0:
            print("STDERR:", p.stderr[-400:], file=sys.stderr); sys.exit(1)
        ins = ("insert into dashboard_seo_snapshots (channel, payload) values ('amazon', $payload$"
               + json.dumps(payload) + "$payload$::jsonb);")
        p = subprocess.run(["ssh", "-i", KEY, "-o", "BatchMode=yes", VPS,
                            "docker exec -i bcc-prod-postgres psql -U bcc -d bcc"],
                           input=ins, capture_output=True, text=True, timeout=180)
        if p.returncode != 0:
            print("STDERR:", p.stderr[-400:], file=sys.stderr); sys.exit(1)
        print("[seo] pushed snapshot to prod bcc")


if __name__ == "__main__":
    main()
