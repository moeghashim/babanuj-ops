#!/usr/bin/env python3
"""Amazon Ads v3 async reporting helper (Babanuj Command Center).

The installed `amazon-ads-pp-cli` (2026.6.2) exposes no v3 /reporting/reports
interface, so SP/SB *performance* reports can't be generated through it. This
pulls them directly from the current v3 reporting API. Mirrors the ga-pull.py
pattern: read creds from the CLI's own .env, refresh the LWA token, REST calls.

Usage:
  amazon-ads-report.py --ad-product sp|sb [--days 30] [--time-unit SUMMARY|DAILY]

Output: ~/babanuj-ops/amazon-ads/<sp|sb>-report-<endDate>.json  (+ console summary)
"""
import os, sys, json, gzip, time, re, argparse, urllib.request, urllib.error, urllib.parse
from datetime import date, timedelta

ENV = os.path.expanduser("~/.config/amazon-ads-pp-cli/.env")
OUTDIR = os.path.expanduser("~/babanuj-ops/amazon-ads")
HOST = "https://advertising-api.amazon.com"
TOKEN_URL = "https://api.amazon.com/auth/o2/token"

# v3 reporting report specs. Column names are validated server-side; a 400 lists
# any invalid ones (the script prints the full body so they're easy to fix).
REPORTS = {
    "sp": {
        "adProduct": "SPONSORED_PRODUCTS", "reportTypeId": "spCampaigns",
        "groupBy": ["campaign"],
        "cols_summary": ["campaignId", "campaignName", "campaignStatus",
                         "impressions", "clicks", "cost", "purchases30d", "sales30d"],
        "cols_daily": ["date", "campaignId", "campaignName", "campaignStatus",
                       "impressions", "clicks", "cost", "purchases30d", "sales30d"],
        "spend": "cost", "sales": "sales30d", "orders": "purchases30d",
    },
    "sb": {
        "adProduct": "SPONSORED_BRANDS", "reportTypeId": "sbCampaigns",
        "groupBy": ["campaign"],
        "cols_summary": ["campaignId", "campaignName",
                         "impressions", "clicks", "cost", "purchases", "sales"],
        "cols_daily": ["date", "campaignId", "campaignName",
                       "impressions", "clicks", "cost", "purchases", "sales"],
        "spend": "cost", "sales": "sales", "orders": "purchases",
    },
    "sd": {
        "adProduct": "SPONSORED_DISPLAY", "reportTypeId": "sdCampaigns",
        "groupBy": ["campaign"],
        "cols_summary": ["campaignId", "campaignName",
                         "impressions", "clicks", "cost", "purchases", "sales"],
        "cols_daily": ["date", "campaignId", "campaignName",
                       "impressions", "clicks", "cost", "purchases", "sales"],
        "spend": "cost", "sales": "sales", "orders": "purchases",
    },
    # DSP is a separate API (POST /dsp/.../reports) and requires the AGENCY
    # profile 3266811360014596, not the seller profile — handle separately.
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


def _req(url, headers, data=None, method="GET", timeout=60):
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def refresh_token(env):
    data = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": env["AMAZON_ADS_REFRESH_TOKEN"],
        "client_id": env["AMAZON_ADS_CLIENT_ID"],
        "client_secret": env["AMAZON_ADS_CLIENT_SECRET"],
    }).encode()
    st, body = _req(TOKEN_URL, {"Content-Type": "application/x-www-form-urlencoded"},
                    data=data, method="POST")
    if st != 200:
        print(f"[auth] token refresh failed HTTP {st}: {body.decode()[:400]}")
        sys.exit(1)
    return json.loads(body.decode())["access_token"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ad-product", required=True, choices=["sp", "sb", "sd"])
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--time-unit", default="SUMMARY", choices=["SUMMARY", "DAILY"])
    args = ap.parse_args()

    env = load_env(ENV)
    spec = REPORTS[args.ad_product]
    os.makedirs(OUTDIR, exist_ok=True)

    end = date.today() - timedelta(days=1)            # yesterday; today is usually incomplete
    start = end - timedelta(days=args.days - 1)
    cols = spec["cols_daily"] if args.time_unit == "DAILY" else spec["cols_summary"]

    print(f"[auth] refreshing LWA access token…")
    access = refresh_token(env)
    base_headers = {
        "Amazon-Advertising-API-ClientId": env["AMAZON_ADS_CLIENT_ID"],
        "Amazon-Advertising-API-Scope": env["AMAZON_ADS_PROFILE_ID"],
        "Authorization": f"Bearer {access}",
    }
    create_headers = dict(base_headers)
    create_headers["Content-Type"] = "application/vnd.createasyncreportrequest.v3+json"

    body = json.dumps({
        "name": f"{args.ad_product} {args.time_unit} {start}..{end}",
        "startDate": start.isoformat(), "endDate": end.isoformat(),
        "configuration": {
            "adProduct": spec["adProduct"], "groupBy": spec["groupBy"],
            "columns": cols, "reportTypeId": spec["reportTypeId"],
            "timeUnit": args.time_unit, "format": "GZIP_JSON",
        },
    }).encode()

    pend_file = os.path.join(OUTDIR, f".pending-{args.ad_product}.json")

    def _summary(rows):
        tot = {"impressions": 0, "clicks": 0, spec["spend"]: 0.0,
               spec["sales"]: 0.0, spec["orders"]: 0}
        for r in rows:
            for k in tot:
                tot[k] += r.get(k, 0) or 0
        spend, sales, orders = tot[spec["spend"]], tot[spec["sales"]], tot[spec["orders"]]
        acos = (spend / sales * 100) if sales else 0
        print(f"\n=== {args.ad_product.upper()} summary ===")
        print(f"campaign rows : {len(rows)}")
        print(f"impressions   : {tot['impressions']:,}")
        print(f"clicks        : {tot['clicks']:,}")
        print(f"spend         : ${spend:,.2f}")
        print(f"sales         : ${sales:,.2f}")
        print(f"orders        : {orders:,}")
        print(f"ACOS          : {acos:.1f}%")

    def _download(url, report_end):
        print("[download] fetching gz artifact from S3…")
        raw = urllib.request.urlopen(url, timeout=120).read()
        try:
            rows = json.loads(gzip.decompress(raw).decode())
        except OSError:
            rows = json.loads(raw.decode())
        out = os.path.join(OUTDIR, f"{args.ad_product}-report-{report_end}.json")
        with open(out, "w") as f:
            json.dump(rows, f, indent=2)
        print(f"[saved] {len(rows)} rows -> {out}")
        _summary(rows)
        return out

    def poll_download(rid, report_end, budget):
        """Poll report `rid` up to `budget` seconds. Returns the written path when
        COMPLETED, False when FAILED/CANCELLED, or None if still processing."""
        deadline = time.time() + budget
        while True:
            st, raw = _req(f"{HOST}/reporting/reports/{rid}", base_headers)
            if st == 200:
                resp = json.loads(raw.decode())
                status = resp.get("status")
                print(f"[poll] {rid} status={status}")
                if status == "COMPLETED":
                    return _download(resp.get("url"), report_end)
                if status in ("FAILED", "CANCELLED"):
                    print(json.dumps(resp, indent=2))
                    return False
            else:
                print(f"[poll] HTTP {st}: {raw.decode()[:300]}")
            if time.time() >= deadline:
                return None
            time.sleep(8)

    # ---- Phase 1: resume a report queued by a previous run (async — never a long wait) ----
    if os.path.isfile(pend_file):
        try:
            pend = json.load(open(pend_file))
        except Exception:
            pend = {}
        rid = pend.get("reportId")
        if rid:
            rend = pend.get("end", end.isoformat())
            print(f"[pending] resuming queued report {rid} (end={rend})…")
            res = poll_download(rid, rend, 45)
            if isinstance(res, str):
                os.remove(pend_file)
                print("[pending] delivered — up to date, nothing new queued this run.")
                return
            if res is False:
                os.remove(pend_file)
                print("[pending] report failed/cancelled — creating a fresh one.")
            else:
                print(f"[pending] report {rid} still processing — will retry next run.")
                return
        else:
            os.remove(pend_file)

    # ---- Phase 2: create a fresh async report and queue it for next run ----
    print(f"[create] {spec['adProduct']} {start}..{end} timeUnit={args.time_unit}")
    rid = None
    for attempt in range(1, 7):
        st, raw = _req(f"{HOST}/reporting/reports", create_headers, data=body, method="POST")
        if st in (200, 201, 202):
            rid = json.loads(raw.decode()).get("reportId")
            break
        if st == 425:
            # Amazon dedupes identical requests within its retention window and
            # returns the id of the already-queued report — adopt & resume it
            # instead of failing (this is the async happy path on re-runs).
            try:
                detail = json.loads(raw.decode()).get("detail", "")
            except Exception:
                detail = raw.decode()
            m = re.search(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", detail)
            if m:
                rid = m.group(0)
                print(f"[create] duplicate of an in-flight report — adopting {rid}")
                break
            print(f"[create] duplicate but couldn't parse reportId: {detail[:300]}")
            sys.exit(1)
        if st in (429, 500, 502, 503) and attempt < 6:
            wait = min(60, 5 * attempt)
            print(f"[create] HTTP {st} (throttle/transient) — retry {attempt}/5 in {wait}s…")
            time.sleep(wait)
            continue
        print(f"[create] FAILED HTTP {st}:\n{raw.decode()[:1500]}")
        sys.exit(1)
    if not rid:
        print("[create] no reportId obtained"); sys.exit(1)
    print(f"[create] queued reportId={rid}")
    with open(pend_file, "w") as f:
        json.dump({"reportId": rid, "end": end.isoformat(),
                   "start": start.isoformat(), "created_at": time.time()}, f)

    # Opportunistic short poll: deliver same-run if the report is ready, else defer.
    res = poll_download(rid, end.isoformat(), 45)
    if isinstance(res, str):
        os.remove(pend_file)
        print("[create] delivered this run.")
    elif res is False:
        os.remove(pend_file)
        print("[create] report failed/cancelled.")
    else:
        print("[create] not ready within grace window — queued for next run.")


if __name__ == "__main__":
    main()
