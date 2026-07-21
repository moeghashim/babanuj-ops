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



# --- Relevance guard -------------------------------------------------------
# A term that CONVERTED is not automatically a term this listing should target.
# Auto campaigns match broadly, so a shopper searching "ajwa dates" can land on a
# Safawi listing and buy. Recommending "ajwa" for a Safawi product misdescribes
# it, pulls wrong-intent traffic, and depresses conversion. So: if a search term
# names a product variety or type that this listing is NOT, drop it.
VARIETIES = {  # mutually exclusive product identities
 "date_variety": ["ajwa", "safawi", "sukkari", "sukari", "sukkary", "khodhri", "khodri", "khudri",
                  "medjool", "medjoul", "mabroom", "mabroum", "khalas", "sagai", "sagaie", "saghai",
                  "amber", "rutab", "deglet"],
 "sweet_type":   ["baklava", "baklawa", "maamoul", "mamoul", "mamool", "ghraybeh", "graybah",
                  "barazek", "kunafa", "knafeh", "kunafah", "lokum", "turkish delight", "nougat",
                  "halva", "halawa", "tamriyah", "mabrumah", "mabrouma"],
 "other_food":   ["tahini", "tahina", "honey", "cola", "coffee", "espresso", "chocolate bar",
                  "cashew", "pistachio paste", "olive oil", "za'atar", "zaatar"],
}
# Terms too generic to earn a place in copy — they describe a shelf, not a product.
# Regulated claims: real converting searches, but unusable without certification
# on file. Ranking for them risks listing suppression, which costs more than the
# traffic is worth. Surfaced separately so the exclusion is deliberate.
CLAIM_TERMS = ["organic", "halal", "kosher", "non-gmo", "non gmo", "gluten free", "gluten-free",
               "sugar free", "sugar-free", "keto", "vegan"]
GENERIC_TERMS = {"sweets", "sweet", "produce", "food", "snacks", "snack", "candy", "dessert",
                 "desserts", "gift", "gifts", "groceries", "grocery", "treats", "arabic sweets",
                 "middle eastern sweets", "datiles", "dattes", "dates"}



# Brands we do not own. A converting search for a competitor is real demand, but
# putting their name in our copy is both a trademark risk and a promise we break.
COMPETITOR_BRANDS = ["lindt", "lindts", "ferrero", "patchi", "bateel", "zalatimo", "amos",
                     "godiva", "kinder", "nutella", "sadaf", "ziyad", "haribo", "turkiye market",
                     "shatila", "oh nuts", "sukkary house", "al rifai", "arabica", "hallab"]

# Words that carry no product identity — ignored when testing whether a search
# term is about this product at all.
NOISE = {"the","and","for","with","from","premium","luxury","authentic","traditional","natural",
         "fresh","best","top","quality","gift","gifts","box","pack","packs","bulk","oz","lb","g",
         "kg","count","pouch","tin","jar","assorted","assortment","mix","mixed","classic","real",
         "delicious","tasty","gourmet","handmade","imported","large","small","medium","value",
         "buy","online","free","shipping","delivery","overnight","near","me","in","of","to","a"}

SYNONYMS = [  # different words for the same thing — treat as overlapping
 {"lokum", "turkish", "delight"}, {"maamoul", "mamoul", "mamool", "mamul"},
 {"ghraybeh", "graybah", "ghraybah"}, {"baklava", "baklawa"},
 {"kunafa", "knafeh", "kunafah", "kataifi"}, {"tahini", "tahina", "sesame"},
 {"date", "dates", "tamr", "tamriyah"}, {"cookie", "cookies", "biscuit", "biscuits"},
 {"nut", "nuts", "pistachio", "pistachios", "cashew", "walnut", "almond"},
 {"chocolate", "choc"}, {"honey"}, {"cola"}, {"coffee", "espresso"},
]


def content_tokens(text):
    return {t for t in norm(text).split() if len(t) > 2 and t not in NOISE}


def expand(tokens):
    out = set(tokens)
    for grp in SYNONYMS:
        if out & grp:
            out |= grp
    return out

def relevance(term, title_norm, known_vocab=None):
    """(keep, reason). Drops cross-variety and generic terms."""
    t = norm(term).strip()
    for c in CLAIM_TERMS:
        if c in t:
            return False, f"regulated claim ('{c}') — needs certification on file"
    if t in GENERIC_TERMS:
        return False, "too generic to describe this product"
    for b in COMPETITOR_BRANDS:
        if re.search(rf"\b{re.escape(b)}\b", t) and b not in title_norm:
            return False, f"competitor brand ('{b}') — not ours to claim"
    for group, words in VARIETIES.items():
        for w in words:
            if w in t and w not in title_norm:
                # the term names an identity this product does not have
                mine = [x for x in words if x in title_norm]
                if mine:
                    return False, f"different {group.replace('_',' ')} — this is {mine[0]}, not {w}"
                return False, f"names a {group.replace('_',' ')} ({w}) this listing is not"
    # Finally: does this search share ANY product identity with the listing? A term
    # with zero overlap converted by accident (broad auto match), not by intent.
    tt, pt = expand(content_tokens(term)), expand(content_tokens(title_norm))
    if pt and not (tt & pt):
        return False, "unrelated to this product — no shared product terms"
    # A hardcoded brand list can never be complete. Instead use our own catalogue
    # as the vocabulary: a token that appears in NO listing we sell is probably a
    # brand or product we do not carry. Flag for review rather than recommend it.
    if known_vocab:
        unknown = sorted(t for t in content_tokens(term) if t not in known_vocab)
        if unknown:
            return "review", f"contains unrecognised term(s): {', '.join(unknown[:3])} — check before using"
    return True, None

def score(asin, lst, st, kw, ad_sales, known_vocab=None):
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
    # Record WHERE each converting term appears, not just whether it does — a term
    # present only in the description carries far less ranking weight than one in
    # the title, and the fix differs accordingly.
    fields = {"title": norm(title),
              "bullets": norm(" ".join(lst["bullets"])),
              "description": norm(lst["description"])}
    hay = " ".join(fields.values())
    covered, missing, keywords, irrelevant, review = [], [], [], [], []
    tnorm = fields["title"]
    for term, orders in kw:
        keep, why = relevance(term, tnorm, known_vocab)
        if keep == "review":
            review.append({"term": term, "orders": orders, "reason": why}); continue
        if not keep:
            irrelevant.append({"term": term, "orders": orders, "reason": why})
            continue
        toks = [t for t in norm(term).split() if len(t) > 2]
        where = [f for f, txt in fields.items() if toks and all(t in txt for t in toks)]
        is_cov = bool(toks) and all(t in hay for t in toks)
        (covered if is_cov else missing).append(term)
        keywords.append({"term": term, "orders": orders, "covered": is_cov,
                         "in_title": "title" in where, "in_bullets": "bullets" in where,
                         "in_description": "description" in where,
                         # covered only via words scattered across fields, not in any single one
                         "split_across_fields": is_cov and not where})
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
    # Ad-attributed sales use a 30-day attribution window that does not align with
    # the traffic window, so ad_sales can exceed total ordered sales. Clamp at zero
    # and flag it rather than reporting a negative organic share as if it were real.
    raw_organic = round(total - ad_sales, 2) if total else None
    attribution_mismatch = bool(total and raw_organic is not None and raw_organic < 0)
    organic = max(0.0, raw_organic) if raw_organic is not None else None
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

    # Score /10. Weights are explicit and auditable: keyword coverage and earned
    # demand dominate because they are what SEO actually moves; copy hygiene is
    # necessary but not sufficient. pass = full, warn = half, fail = 0. Checks
    # that could not be evaluated are excluded and the rest renormalised, so a
    # missing signal never silently reads as a failure. Buy box is a gate, not a
    # credit: it can only subtract.
    WEIGHTS = {"keyword_coverage": 2.5, "organic_share": 2.0, "conversion_rate": 1.5,
               "title_length": 1.0, "bullets": 1.0, "images": 1.0,
               "bullet_depth": 0.5, "description": 0.5}
    by = {c["check"]: c["verdict"] for c in checks}
    earned = available = 0.0
    breakdown = []
    for name, w in WEIGHTS.items():
        v = by.get(name)
        if v is None or v == "n/a":
            continue
        got = w if v == "pass" else (w / 2 if v == "warn" else 0.0)
        earned += got; available += w
        breakdown.append({"check": name, "weight": w, "verdict": v, "earned": round(got, 2)})
    # An ASIN with no traffic has no evaluable performance checks. Renormalising
    # over copy hygiene alone would hand a never-sold listing a perfect score, so
    # withhold the score instead of inventing confidence from absent data.
    has_perf = any(k in by for k in ("organic_share", "conversion_rate"))
    raw = (earned / available * 10) if available and has_perf else None
    penalty = 1.0 if by.get("buy_box") == "fail" else 0.0
    score = None if raw is None else max(0.0, round(raw - penalty, 1))
    if penalty:
        breakdown.append({"check": "buy_box", "weight": -1.0, "verdict": "fail", "earned": -1.0})

    grade = ("unrated" if score is None else
             "strong" if fails == 0 and warns <= 1 else ("weak" if fails >= 3 else "needs work"))
    return {"asin": asin, "title": title, "grade": grade,
            "score": score, "score_breakdown": breakdown,
            "passes": passes, "warns": warns, "fails": fails,
            "sessions": st["sessions"] if st else None,
            "cvr_pct": st.get("cvr_pct") if st else None,
            "buybox_pct": st.get("buybox_pct") if st else None,
            "total_sales": total or None, "ad_sales": ad_sales or None,
            "organic_sales": organic, "organic_pct": organic_pct,
            "attribution_mismatch": attribution_mismatch,
            "keyword_coverage_pct": cov_pct, "n_signal_terms": len(kw),
            "missing_terms": missing[:10], "covered_terms": covered,
            "irrelevant_terms": irrelevant, "review_terms": review,
            "keywords": keywords,
            "kw_in_title": sum(1 for k in keywords if k["in_title"]), "checks": checks, "actions": actions}


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

    # Scope: ADVERTISED ASINs only (Moe, 2026-07-20). Widening to every ASIN with
    # traffic was tried and explicitly scoped back — do not re-widen without asking.
    targets = sorted(ad)
    print(f"[seo] roster {len(targets)} advertised ASINs", file=sys.stderr)
    results = []
    skipped = []
    listings = {}
    for a in targets:
        l = listing(a)
        if l: listings[a] = l
        else: skipped.append(a)
    # our own brands, incl. spelling variants shoppers actually type
    OWN_BRANDS = {"zaitoun","zaitoune","zaytoun","leen","bal","milaf","ribal","babanuj","babanouj",
                  "bab","sharqi","crush","reeq","alnahl","nahl","alkanater","kanater","dessert",
                  "desert","arabic","middle","eastern","turkish","saudi","syrian","lebanese"}
    known_vocab = set(OWN_BRANDS)
    for l in listings.values():
        known_vocab |= content_tokens(l["title"] + " " + " ".join(l["bullets"]))
    print(f"[seo] catalogue vocabulary: {len(known_vocab)} terms from {len(listings)} listings", file=sys.stderr)
    for i, a in enumerate(sorted(listings), 1):
        lst = listings[a]
        results.append(score(a, lst, st.get(a), kw_by_asin.get(a, []), ad.get(a, 0.0), known_vocab))
        if i % 20 == 0: print(f"[seo] {i}/{len(targets)}", file=sys.stderr)

    # Worst score first, but weight by money at stake so a bad ASIN with real
    # revenue outranks a bad ASIN nobody buys.
    results.sort(key=lambda r: (r["score"] if r["score"] is not None else 99,
                                -(r["total_sales"] or 0)))
    scored = [r["score"] for r in results if r["score"] is not None]
    summary = {"asins": len(results),
               "avg_score": round(sum(scored)/len(scored), 1) if scored else None,
               "score_8_plus": sum(1 for x in scored if x >= 8),
               "score_5_to_8": sum(1 for x in scored if 5 <= x < 8),
               "score_under_5": sum(1 for x in scored if x < 5),
               "unrated": sum(1 for r in results if r["grade"] == "unrated"),
               "strong": sum(1 for r in results if r["grade"] == "strong"),
               "needs_work": sum(1 for r in results if r["grade"] == "needs work"),
               "weak": sum(1 for r in results if r["grade"] == "weak"),
               "ad_dependent": sum(1 for r in results if (r["organic_pct"] or 100) < 30),
               "low_cvr": sum(1 for r in results if r["cvr_pct"] is not None and r["cvr_pct"] < CVR_HEALTHY),
               "skipped_unreadable": len(skipped),
               "total_sales": round(sum(r["total_sales"] or 0 for r in results), 2),
               "organic_sales": round(sum(r["organic_sales"] or 0 for r in results), 2)}
    if skipped:
        print(f"[seo] {len(skipped)} ASIN(s) skipped — catalog unreadable", file=sys.stderr)
    payload = {"captured_at": datetime.now(timezone.utc).isoformat(), "channel": "amazon",
               "standards": {"title": [TITLE_MIN, TITLE_MAX], "bullets": BULLETS_EXPECTED,
                             "images_min": IMAGES_MIN, "cvr_healthy": CVR_HEALTHY,
                             "buybox_min": BUYBOX_MIN},
               "summary": summary, "asins": results,
               "skipped_asins": skipped}
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
