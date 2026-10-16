# Babanuj operations syncs

## Amazon Ads history

`amazon-state-snapshot.py` records the current campaign, portfolio, product-ad,
keyword, and target configuration in dated `amazon_*_snapshot` tables. Product
ads also capture the SKU's current SP-API fulfillment channel and listing
status. The job runs daily and same-day reruns upsert the existing snapshot.

`amazon-keyword-archive.py` maintains rolling daily performance in
`amazon_search_term_daily` and `amazon_target_daily`. It defaults to the last
14 days so attribution can restate, accepts `--days 1..90` for backfills, and
chunks Amazon reports into their maximum 31-day windows.

Both jobs write to the production `bcc` Postgres through `bin/run-sync.sh` and
require `BCC_VPS` in the untracked `~/.config/babanuj/.env` file. Amazon and
SP-API credentials remain in their existing untracked config files.

Snapshot tables are `amazon_campaign_snapshot` (budget, bidding, portfolio and
serving status), `amazon_portfolio_snapshot` (budget policy and serving status),
`amazon_product_ad_snapshot` (SKU, ASIN, serving and listing status, FBA/FBM),
`amazon_keyword_snapshot` (text, match type, state, bid), and
`amazon_target_snapshot` (expression, state, bid). All use the machine's local
snapshot date and `(snapshot_date, entity_id)` keys. Campaigns include enabled
and paused campaigns; archived campaigns and their children are excluded.
Fulfillment is fetched once per distinct SKU per run; a missing listing is
recorded as `GONE` with no fulfillment channel.

Performance rows retain daily impressions, clicks, cost, 7-day purchases and
sales. Amazon currently limits the [Sponsored Products search-term report](https://advertising.amazon.com/help/G3HEFZYWZF84NPS9)
to a 65-day lookback, so a 90-day request can return shorter search-term history.
Previously archived rows remain in bcc. Search-term rows additionally retain units; target rows retain bid and
top-of-search impression share as returned by Amazon. Reports end yesterday.
Search-term keys include a generated MD5 of the query to avoid index length
limits. Same-window reruns update metrics for attribution restatement.
Historical rows are never purged. The reports describe ad-attributed metrics,
not additional marketplace order revenue.

Run manually from the checkout:

```sh
bin/run-sync.sh amazon-state-snapshot.py
bin/run-sync.sh amazon-keyword-archive.py --days 90
```

The runner appends output and verification counts to `logs/<script>.log`.
The new launchd plists schedule snapshots daily at 07:00 and performance
archives Wednesday/Sunday at 07:15, in the machine's local timezone. The Chief
installs them after deploying this checkout to the path in `ProgramArguments`;
this change does not load any launchd jobs. Neither job changes Amazon
campaigns, budgets, bids, keywords, targets, or ads. List/report POSTs only read
Amazon data; all persistence is in prod bcc. Both scripts fail before API work
if `BCC_VPS` is missing. Report failures/timeouts abort without writing partial
performance data, and database batches commit in one transaction.

Focused regression checks (no credentials or network required):

```sh
python3 -m unittest discover -s tests -v
```

For a long backfill, set `AMAZON_REPORT_CACHE` to an untracked JSON file outside
this checkout. The job saves private report IDs there (mode 0600) and can resume
completed or pending windows on a same-day rerun. Keys isolate the profile,
report configuration, and local date. This is opt-in: same-day cache reuse
retains the earlier report's attribution values; omit it for a fresh pull.

Database writes use SSH keepalives and retry transport failures by replaying
the same idempotent transaction; SQL errors fail immediately.
