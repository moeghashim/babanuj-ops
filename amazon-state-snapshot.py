#!/usr/bin/env python3
"""Record a daily Sponsored Products configuration snapshot in prod bcc.

Tables are keyed by ``(snapshot_date, entity_id)`` and retain campaign,
portfolio, product-ad/listing, keyword, and target state.  Re-running on the
same day updates that day's facts instead of creating duplicates.
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date

from lib.amazon_sync import (
    ADS_ENV,
    ADS_HOST,
    SELLER_ENV,
    batch_upsert_sql,
    load_env,
    prod_psql,
    require_vps,
    refresh_lwa_token,
)

MARKETPLACE_ID = "ATVPDKIKX0DER"
LISTINGS_HOST = "https://sellingpartnerapi-na.amazon.com"
LIST_ENDPOINTS = {
    "campaigns": ("/sp/campaigns/list", "application/vnd.spCampaign.v3+json", "campaigns"),
    "productAds": ("/sp/productAds/list", "application/vnd.spProductAd.v3+json", "productAds"),
    "keywords": ("/sp/keywords/list", "application/vnd.spKeyword.v3+json", "keywords"),
    "targets": ("/sp/targets/list", "application/vnd.spTargetingClause.v3+json", "targetingClauses"),
}


def retry_urlopen(request: urllib.request.Request, timeout: int = 90):
    for attempt in range(5):
        try:
            return urllib.request.urlopen(request, timeout=timeout)
        except urllib.error.HTTPError as error:
            if error.code in (429, 500, 502, 503, 504) and attempt < 4:
                retry_after = error.headers.get("Retry-After")
                time.sleep(float(retry_after) if retry_after else min(2 ** attempt, 16))
                continue
            raise


def make_ads_post(access_token: str, env: dict[str, str]):
    client_id = env.get("AMAZON_ADS_API_CLIENT_ID") or env["AMAZON_ADS_CLIENT_ID"]
    headers = {
        "Authorization": "Bearer " + access_token,
        "Amazon-Advertising-API-ClientId": client_id,
        "Amazon-Advertising-API-Scope": env["AMAZON_ADS_PROFILE_ID"],
    }

    def post(path: str, content_type: str, body: dict) -> dict:
        request_headers = dict(headers)
        request_headers.update({"Content-Type": content_type, "Accept": content_type})
        request = urllib.request.Request(
            ADS_HOST + path,
            data=json.dumps(body).encode(),
            headers=request_headers,
            method="POST",
        )
        with retry_urlopen(request) as response:
            return json.load(response)

    return post


def pull(post, path: str, content_type: str, key: str, campaign_ids=None) -> list[dict]:
    """Paginate a v3 list endpoint, batching campaign filters at 100 IDs."""
    items: list[dict] = []
    batches = (
        [campaign_ids[index:index + 100] for index in range(0, len(campaign_ids), 100)]
        if campaign_ids is not None else [None]
    )
    for batch in batches:
        token = None
        while True:
            body = {"maxResults": 500, "includeExtendedDataFields": True}
            if batch is not None:
                body["campaignIdFilter"] = {"include": batch}
            if token:
                body["nextToken"] = token
            response = post(path, content_type, body)
            items.extend(response.get(key, []))
            token = response.get("nextToken")
            if not token:
                break
    return items


def pull_portfolios(post) -> list[dict]:
    items: list[dict] = []
    token = None
    content_type = "application/vnd.spPortfolio.v3+json"
    while True:
        body = {"includeExtendedDataFields": True}
        if token:
            body["nextToken"] = token
        response = post("/portfolios/list", content_type, body)
        items.extend(response.get("portfolios", []))
        token = response.get("nextToken")
        if not token:
            return items


def serving_status(entity: dict):
    return (entity.get("extendedData") or {}).get("servingStatus")


def campaign_budget(campaign: dict):
    budget = campaign.get("budget")
    if isinstance(budget, dict):
        return budget.get("budget", budget.get("amount")), budget.get("budgetType") or budget.get("type")
    return campaign.get("dailyBudget", budget), campaign.get("budgetType")


def campaign_bidding(campaign: dict):
    bidding = campaign.get("dynamicBidding") or campaign.get("bidding") or {}
    return (
        bidding.get("strategy") or campaign.get("biddingStrategy"),
        bidding.get("placementBidding") or bidding.get("placementAdjustments") or [],
    )


class ListingClient:
    """SP-API listing lookup limited to roughly five distinct SKUs per second."""

    def __init__(self, env: dict[str, str]):
        self.env = env
        self.seller_id = env["SP_API_SELLER_ID"]
        self.access_token = refresh_lwa_token(env, "SP_API")
        self.last_request = 0.0

    def _throttle(self):
        remaining = 0.21 - (time.monotonic() - self.last_request)
        if remaining > 0:
            time.sleep(remaining)
        self.last_request = time.monotonic()

    def get(self, sku: str) -> tuple[str | None, str]:
        path = "/listings/2021-08-01/items/{}/{}?{}".format(
            urllib.parse.quote(self.seller_id, safe=""),
            urllib.parse.quote(sku, safe=""),
            urllib.parse.urlencode({
                "marketplaceIds": MARKETPLACE_ID,
                "includedData": "fulfillmentAvailability,summaries",
            }),
        )
        for attempt in range(6):
            self._throttle()
            request = urllib.request.Request(
                LISTINGS_HOST + path,
                headers={"x-amz-access-token": self.access_token, "Accept": "application/json"},
            )
            try:
                with urllib.request.urlopen(request, timeout=60) as response:
                    payload = json.load(response)
                return self._parse(payload)
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    return None, "GONE"
                if error.code == 401 and attempt == 0:
                    self.access_token = refresh_lwa_token(self.env, "SP_API")
                    continue
                if error.code == 429 and attempt < 5:
                    retry_after = error.headers.get("Retry-After")
                    time.sleep(float(retry_after) if retry_after else min(2 ** attempt, 16))
                    continue
                raise
        raise RuntimeError(f"listing lookup exhausted retries for SKU {sku!r}")

    @staticmethod
    def _parse(payload: dict) -> tuple[str | None, str]:
        channels = {
            item.get("fulfillmentChannelCode")
            for item in payload.get("fulfillmentAvailability", [])
        }
        if "AMAZON_NA" in channels:
            fulfillment = "FBA"
        elif "DEFAULT" in channels:
            fulfillment = "FBM"
        else:
            fulfillment = next((value for value in channels if value), None)

        summaries = payload.get("summaries") or []
        status = summaries[0].get("status") if summaries else None
        if isinstance(status, list):
            status = ",".join(str(value) for value in status)
        return fulfillment, str(status or "UNKNOWN")


SCHEMA_SQL = """
create table if not exists amazon_campaign_snapshot(
  snapshot_date date not null, campaign_id text not null, name text, state text,
  serving_status text, portfolio_id text, portfolio_name text,
  daily_budget numeric(14,2), budget_type text, bidding_strategy text,
  placement_bidding jsonb, targeting_type text, start_date date, end_date date,
  primary key(snapshot_date,campaign_id));
create index if not exists amazon_campaign_snapshot_portfolio_idx
  on amazon_campaign_snapshot(snapshot_date,portfolio_id);

create table if not exists amazon_portfolio_snapshot(
  snapshot_date date not null, portfolio_id text not null, name text, state text,
  serving_status text, budget_policy text, budget_amount numeric(14,2),
  primary key(snapshot_date,portfolio_id));

create table if not exists amazon_product_ad_snapshot(
  snapshot_date date not null, ad_id text not null, campaign_id text,
  ad_group_id text, asin text, sku text, state text, serving_status text,
  fulfillment_channel text, listing_status text,
  primary key(snapshot_date,ad_id));
create index if not exists amazon_product_ad_snapshot_campaign_idx
  on amazon_product_ad_snapshot(snapshot_date,campaign_id);
create index if not exists amazon_product_ad_snapshot_sku_idx
  on amazon_product_ad_snapshot(snapshot_date,sku);

create table if not exists amazon_keyword_snapshot(
  snapshot_date date not null, keyword_id text not null, campaign_id text,
  ad_group_id text, keyword_text text, match_type text, state text, bid numeric(14,2),
  primary key(snapshot_date,keyword_id));
create index if not exists amazon_keyword_snapshot_campaign_idx
  on amazon_keyword_snapshot(snapshot_date,campaign_id);

create table if not exists amazon_target_snapshot(
  snapshot_date date not null, target_id text not null, campaign_id text,
  ad_group_id text, expression jsonb, state text, bid numeric(14,2),
  primary key(snapshot_date,target_id));
create index if not exists amazon_target_snapshot_campaign_idx
  on amazon_target_snapshot(snapshot_date,campaign_id);
"""


def main() -> None:
    require_vps()
    snapshot_date = date.today().isoformat()
    ads_env = load_env(ADS_ENV)
    post = make_ads_post(refresh_lwa_token(ads_env, "AMAZON_ADS"), ads_env)

    campaigns = pull(post, *LIST_ENDPOINTS["campaigns"])
    campaigns = [item for item in campaigns if item.get("state") != "ARCHIVED"]
    print(f"[snapshot] {len(campaigns)} non-archived campaigns", file=sys.stderr, flush=True)
    campaign_ids = [item["campaignId"] for item in campaigns]
    portfolios = pull_portfolios(post)
    product_ads = pull(post, *LIST_ENDPOINTS["productAds"], campaign_ids=campaign_ids)
    keywords = pull(post, *LIST_ENDPOINTS["keywords"], campaign_ids=campaign_ids)
    targets = pull(post, *LIST_ENDPOINTS["targets"], campaign_ids=campaign_ids)
    print(f"[snapshot] portfolios={len(portfolios)} product_ads={len(product_ads)} keywords={len(keywords)} targets={len(targets)}", file=sys.stderr, flush=True)
    portfolio_names = {str(item["portfolioId"]): item.get("name") for item in portfolios}

    seller_env = load_env(SELLER_ENV)
    listing_client = ListingClient(seller_env)
    listing_by_sku = {}
    skus = sorted({item.get("sku") for item in product_ads if item.get("sku")})
    print(f"[snapshot] looking up {len(skus)} distinct SKUs", file=sys.stderr, flush=True)
    for sku in skus:
        listing_by_sku[sku] = listing_client.get(sku)

    campaign_rows = []
    for item in campaigns:
        budget, budget_type = campaign_budget(item)
        strategy, placement = campaign_bidding(item)
        portfolio_id = str(item["portfolioId"]) if item.get("portfolioId") is not None else None
        campaign_rows.append((
            snapshot_date, str(item["campaignId"]), item.get("name"), item.get("state"),
            serving_status(item), portfolio_id, portfolio_names.get(portfolio_id),
            budget, budget_type, strategy, placement, item.get("targetingType"),
            item.get("startDate"), item.get("endDate"),
        ))

    portfolio_rows = []
    for item in portfolios:
        budget = item.get("budget") or {}
        portfolio_rows.append((
            snapshot_date, str(item["portfolioId"]), item.get("name"), item.get("state"),
            serving_status(item), budget.get("policy"), budget.get("amount"),
        ))

    product_rows = []
    for item in product_ads:
        sku = item.get("sku")
        fulfillment, listing_status = listing_by_sku.get(sku, (None, "UNKNOWN"))
        product_rows.append((
            snapshot_date, str(item["adId"]), str(item.get("campaignId") or ""),
            str(item.get("adGroupId") or ""), item.get("asin"), sku,
            item.get("state"), serving_status(item), fulfillment, listing_status,
        ))

    keyword_rows = [(
        snapshot_date, str(item["keywordId"]), str(item.get("campaignId") or ""),
        str(item.get("adGroupId") or ""), item.get("keywordText"),
        item.get("matchType"), item.get("state"), item.get("bid"),
    ) for item in keywords]
    target_rows = [(
        snapshot_date, str(item["targetId"]), str(item.get("campaignId") or ""),
        str(item.get("adGroupId") or ""), item.get("expression") or [],
        item.get("state"), item.get("bid"),
    ) for item in targets]

    statements = ["begin;", SCHEMA_SQL]
    specs = [
        ("amazon_campaign_snapshot", ["snapshot_date", "campaign_id", "name", "state", "serving_status", "portfolio_id", "portfolio_name", "daily_budget", "budget_type", "bidding_strategy", "placement_bidding", "targeting_type", "start_date", "end_date"], campaign_rows, ["snapshot_date", "campaign_id"]),
        ("amazon_portfolio_snapshot", ["snapshot_date", "portfolio_id", "name", "state", "serving_status", "budget_policy", "budget_amount"], portfolio_rows, ["snapshot_date", "portfolio_id"]),
        ("amazon_product_ad_snapshot", ["snapshot_date", "ad_id", "campaign_id", "ad_group_id", "asin", "sku", "state", "serving_status", "fulfillment_channel", "listing_status"], product_rows, ["snapshot_date", "ad_id"]),
        ("amazon_keyword_snapshot", ["snapshot_date", "keyword_id", "campaign_id", "ad_group_id", "keyword_text", "match_type", "state", "bid"], keyword_rows, ["snapshot_date", "keyword_id"]),
        ("amazon_target_snapshot", ["snapshot_date", "target_id", "campaign_id", "ad_group_id", "expression", "state", "bid"], target_rows, ["snapshot_date", "target_id"]),
    ]
    for table, columns, rows, conflict in specs:
        statements.append(batch_upsert_sql(table, columns, rows, conflict, columns[2:]))
    statements.extend([
        "commit;",
        "select 'counts';",
        *[
            f"select '{table}|' || count(*) from {table} where snapshot_date='{snapshot_date}';"
            for table, *_ in specs
        ],
    ])
    print(prod_psql("\n".join(statements)).strip())


if __name__ == "__main__":
    main()
