#!/usr/bin/env python3
"""Archive daily Amazon keyword, target, and search-term performance.

The rolling, idempotent archive writes two prod bcc tables:

* ``amazon_search_term_daily`` — search queries and 7-day conversions.
* ``amazon_target_daily`` — keyword/target performance and top-of-search share.

Amazon limits daily reports to 31 days, so longer windows are chunked and each
chunk receives a fresh LWA token.  The default is 14 days; ``--days`` accepts
1–90 days for attribution restatement and backfill.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from lib.amazon_sync import ADS_ENV, AdsReportClient, batch_upsert_sql, load_env, prod_psql, require_vps


def decimal_value(value) -> Decimal:
    if value in (None, ""):
        return Decimal(0)
    try:
        return Decimal(str(value).rstrip("%"))
    except (InvalidOperation, ValueError):
        return Decimal(0)


def integer_value(value) -> int:
    return int(decimal_value(value))


def search_term_rows(report_rows: list[dict]) -> list[tuple]:
    aggregates = defaultdict(lambda: {
        "keyword": "", "match_type": "", "impressions": 0, "clicks": 0,
        "cost": Decimal(0), "purchases": 0, "sales": Decimal(0), "units": 0,
    })
    for row in report_rows:
        day = str(row.get("date") or "")[:10]
        campaign_id = str(row.get("campaignId") or "")
        ad_group_id = str(row.get("adGroupId") or "")
        keyword_id = str(row.get("keywordId") or row.get("targetingId") or "")
        search_term = str(row.get("searchTerm") or "")
        if not (day and campaign_id and ad_group_id and search_term):
            continue
        value = aggregates[(day, campaign_id, ad_group_id, keyword_id, search_term)]
        value["keyword"] = str(row.get("keyword") or row.get("targeting") or "")
        value["match_type"] = str(row.get("matchType") or "")
        value["impressions"] += integer_value(row.get("impressions"))
        value["clicks"] += integer_value(row.get("clicks"))
        value["cost"] += decimal_value(row.get("cost"))
        value["purchases"] += integer_value(row.get("purchases7d"))
        value["sales"] += decimal_value(row.get("sales7d"))
        value["units"] += integer_value(row.get("unitsSoldClicks7d") or row.get("units7d"))
    return [
        (day, campaign_id, ad_group_id, keyword_id, value["keyword"], value["match_type"],
         search_term, value["impressions"], value["clicks"], value["cost"],
         value["purchases"], value["sales"], value["units"])
        for (day, campaign_id, ad_group_id, keyword_id, search_term), value in sorted(aggregates.items())
    ]


def target_rows(report_rows: list[dict]) -> list[tuple]:
    aggregates = defaultdict(lambda: {
        "bid": Decimal(0), "impressions": 0, "clicks": 0, "cost": Decimal(0),
        "purchases": 0, "sales": Decimal(0), "top_share": Decimal(0),
    })
    for row in report_rows:
        day = str(row.get("date") or "")[:10]
        campaign_id = str(row.get("campaignId") or "")
        ad_group_id = str(row.get("adGroupId") or "")
        keyword_id = str(row.get("keywordId") or row.get("targetingId") or "")
        keyword = str(row.get("keyword") or row.get("targeting") or "")
        match_type = str(row.get("matchType") or "")
        if not (day and campaign_id and ad_group_id):
            continue
        value = aggregates[(day, campaign_id, ad_group_id, keyword_id, keyword, match_type)]
        value["bid"] = None if row.get("keywordBid") in (None, "") else decimal_value(row["keywordBid"])
        value["impressions"] += integer_value(row.get("impressions"))
        value["clicks"] += integer_value(row.get("clicks"))
        value["cost"] += decimal_value(row.get("cost"))
        value["purchases"] += integer_value(row.get("purchases7d"))
        value["sales"] += decimal_value(row.get("sales7d"))
        share = row.get("topOfSearchImpressionShare")
        value["top_share"] = None if share in (None, "") else decimal_value(share)
    return [
        (day, campaign_id, ad_group_id, keyword_id, keyword, match_type, value["bid"],
         value["impressions"], value["clicks"], value["cost"], value["purchases"],
         value["sales"], value["top_share"])
        for (day, campaign_id, ad_group_id, keyword_id, keyword, match_type), value in sorted(aggregates.items())
    ]


SCHEMA_SQL = """
create table if not exists amazon_search_term_daily(
  date date not null, campaign_id text not null, ad_group_id text not null,
  keyword_id text not null default '', keyword text, match_type text,
  search_term text not null, search_term_hash text generated always as (md5(search_term)) stored,
  impressions bigint not null default 0, clicks bigint not null default 0,
  cost numeric(14,2) not null default 0, purchases7d bigint not null default 0,
  sales7d numeric(14,2) not null default 0, units7d bigint not null default 0,
  archived_at timestamptz not null default now(),
  primary key(date,campaign_id,ad_group_id,keyword_id,search_term_hash));
create index if not exists amazon_search_term_daily_campaign_idx
  on amazon_search_term_daily(campaign_id,date);
create index if not exists amazon_search_term_daily_term_idx
  on amazon_search_term_daily(search_term_hash,date);

create table if not exists amazon_target_daily(
  date date not null, campaign_id text not null, ad_group_id text not null,
  keyword_id text not null default '', keyword text not null default '',
  match_type text not null default '', keyword_bid numeric(14,2),
  impressions bigint not null default 0, clicks bigint not null default 0,
  cost numeric(14,2) not null default 0, purchases7d bigint not null default 0,
  sales7d numeric(14,2) not null default 0, top_of_search_share numeric(12,6),
  archived_at timestamptz not null default now(),
  primary key(date,campaign_id,ad_group_id,keyword_id,keyword,match_type));
create index if not exists amazon_target_daily_campaign_idx
  on amazon_target_daily(campaign_id,date);
create index if not exists amazon_target_daily_keyword_idx
  on amazon_target_daily(keyword_id,date);
"""


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="trailing days to archive (1-90; default 14)")
    args = parser.parse_args()
    if not 1 <= args.days <= 90:
        parser.error("--days must be between 1 and 90")
    return args


def main() -> None:
    args = parse_args()
    require_vps()
    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=args.days - 1)
    client = AdsReportClient(load_env(ADS_ENV))

    search_report = client.report(
        "spSearchTerm", ["searchTerm"],
        ["date", "campaignId", "adGroupId", "keywordId", "keyword", "matchType",
         "searchTerm", "impressions", "clicks", "cost", "purchases7d", "sales7d",
         "unitsSoldClicks7d"],
        start, end,
    )
    targeting_report = client.report(
        "spTargeting", ["targeting"],
        ["date", "campaignId", "adGroupId", "keywordId", "keyword", "matchType",
         "keywordBid", "impressions", "clicks", "cost", "purchases7d", "sales7d",
         "topOfSearchImpressionShare"],
        start, end,
    )
    search_rows = search_term_rows(search_report)
    targets = target_rows(targeting_report)

    search_columns = [
        "date", "campaign_id", "ad_group_id", "keyword_id", "keyword", "match_type",
        "search_term", "impressions", "clicks", "cost", "purchases7d", "sales7d", "units7d",
    ]
    target_columns = [
        "date", "campaign_id", "ad_group_id", "keyword_id", "keyword", "match_type",
        "keyword_bid", "impressions", "clicks", "cost", "purchases7d", "sales7d",
        "top_of_search_share",
    ]
    sql = [
        "begin;", SCHEMA_SQL,
        batch_upsert_sql(
            "amazon_search_term_daily", search_columns, search_rows,
            ["date", "campaign_id", "ad_group_id", "keyword_id", "search_term_hash"],
            [name for name in search_columns[4:] if name != "search_term"] + ["archived_at"],
        ),
        batch_upsert_sql(
            "amazon_target_daily", target_columns, targets,
            ["date", "campaign_id", "ad_group_id", "keyword_id", "keyword", "match_type"],
            target_columns[6:] + ["archived_at"],
        ),
        "commit;",
        "select 'verification';",
        f"select 'amazon_search_term_daily|' || count(*) || '|' || coalesce(min(date)::text,'NULL') || '|' || coalesce(max(date)::text,'NULL') from amazon_search_term_daily where date between '{start}' and '{end}';",
        f"select 'amazon_target_daily|' || count(*) || '|' || coalesce(min(date)::text,'NULL') || '|' || coalesce(max(date)::text,'NULL') from amazon_target_daily where date between '{start}' and '{end}';",
    ]
    print(prod_psql("\n".join(sql), timeout=1200).strip())


if __name__ == "__main__":
    main()
