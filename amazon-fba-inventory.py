#!/usr/bin/env python3
"""amazon-fba-inventory.py — daily FBA stock snapshot (SP-API FBA Inventory) → prod bcc.

  amazon-fba-inventory.py

Table: fba_inventory_daily(snapshot_date, sku, asin, product_name, fulfillable,
inbound_working, inbound_shipped, inbound_receiving, reserved, researching,
unfulfillable, total). One row per SKU per Chicago day; re-runs replace that day.
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo

from lib.amazon_sync import SELLER_ENV, batch_upsert_sql, load_env, prod_psql, refresh_lwa_token, require_vps

HOST = "https://sellingpartnerapi-na.amazon.com"
MARKETPLACE = "ATVPDKIKX0DER"
COLUMNS = ["snapshot_date", "sku", "asin", "product_name", "fulfillable", "inbound_working",
           "inbound_shipped", "inbound_receiving", "reserved", "researching", "unfulfillable", "total"]
DDL = """create table if not exists fba_inventory_daily(
  snapshot_date date not null, sku text not null, asin text not null, product_name text,
  fulfillable integer not null, inbound_working integer not null, inbound_shipped integer not null,
  inbound_receiving integer not null, reserved integer not null, researching integer not null,
  unfulfillable integer not null, total integer not null,
  archived_at timestamptz not null default now(),
  primary key(snapshot_date, sku));"""


def fetch(token, next_token=None):
    params = {"granularityType": "Marketplace", "granularityId": MARKETPLACE,
              "marketplaceIds": MARKETPLACE, "details": "true"}
    if next_token:
        params["nextToken"] = next_token
    request = urllib.request.Request(f"{HOST}/fba/inventory/v1/summaries?{urllib.parse.urlencode(params)}",
                                     headers={"x-amz-access-token": token})
    for attempt in range(5):
        try:
            return json.load(urllib.request.urlopen(request, timeout=60))
        except urllib.error.HTTPError as e:
            if e.code != 429 or attempt == 4:
                raise
            time.sleep(2 * (attempt + 1))


def main():
    require_vps()
    env = load_env(SELLER_ENV)
    token = refresh_lwa_token(env, "SP_API")
    day = datetime.now(ZoneInfo("America/Chicago")).date().isoformat()
    rows, next_token = [], None
    while True:
        data = fetch(token, next_token)
        for s in data["payload"]["inventorySummaries"]:
            d = s.get("inventoryDetails") or {}
            rows.append([day, s["sellerSku"], s["asin"], s.get("productName"),
                         d.get("fulfillableQuantity", 0), d.get("inboundWorkingQuantity", 0),
                         d.get("inboundShippedQuantity", 0), d.get("inboundReceivingQuantity", 0),
                         (d.get("reservedQuantity") or {}).get("totalReservedQuantity", 0),
                         (d.get("researchingQuantity") or {}).get("totalResearchingQuantity", 0),
                         (d.get("unfulfillableQuantity") or {}).get("totalUnfulfillableQuantity", 0),
                         s.get("totalQuantity", 0)])
        next_token = (data.get("pagination") or {}).get("nextToken")
        if not next_token:
            break
        time.sleep(0.6)
    if not rows:
        sys.exit("no FBA inventory summaries returned; refusing to write an empty snapshot")
    sql = "\n".join(["begin;", DDL, f"delete from fba_inventory_daily where snapshot_date='{day}';",
                     batch_upsert_sql("fba_inventory_daily", COLUMNS, rows, ["snapshot_date", "sku"], COLUMNS[2:]),
                     "commit;"])
    prod_psql(sql)
    print(f"[fba-inventory] {day}: {len(rows)} SKUs, {sum(r[4] for r in rows)} fulfillable units")


if __name__ == "__main__":
    main()
