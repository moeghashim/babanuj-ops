#!/usr/bin/env bash
# Babanuj — marketing channels → Command Center PROD Postgres.
#
# Runs LOCALLY (orchestrates the local CLIs: meta / amazon-seller-pp-cli /
# google-search-console-pp-cli + ~/.config creds + the amazon-ads-report.py
# helper) and writes to PROD over an EPHEMERAL SSH tunnel (the prod DB has no
# host port). Scheduled by launchd: com.babanuj.marketing-sync.
#
# Includes amazon_seller: as of #16 its store rollup writes marketplace_metrics_daily
# (NOT web_kpis_daily), so it no longer clobbers Shopify's website revenue, and it
# also fills the Amazon product column (per-ASIN units/sales).
#
#   run-marketing-sync.sh [DAYS] [CHANNELS]
#     DAYS      trailing window, default 14
#     CHANNELS  comma list, default amazon_ads,meta,google,gsc,amazon_seller
set -uo pipefail
KEY="$HOME/.ssh/babanuj_deploy"; VPS="${BCC_VPS:-${BCC_VPS}}"; PORT=5544
DAYS="${1:-14}"; CHANNELS="${2:-amazon_ads,meta,google,gsc,amazon_seller}"
LOG="$HOME/babanuj-ops/marketing-sync.log"
# launchd starts with a bare PATH — add where the channel CLIs live.
export PATH="$HOME/.local/bin:$HOME/go/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
exec >>"$LOG" 2>&1
echo "===== $(date '+%F %T') marketing-sync days=$DAYS channels=$CHANNELS ====="

SSH="ssh -i $KEY -o BatchMode=yes -o ConnectTimeout=15"
DBIP=$($SSH "$VPS" "docker inspect bcc-prod-postgres --format '{{(index .NetworkSettings.Networks \"bcc-prod-net\").IPAddress}}'" 2>/dev/null)
[ -z "$DBIP" ] && { echo "FATAL: VPS unreachable / no db IP"; exit 1; }
PW=$($SSH "$VPS" 'grep -E "^POSTGRES_PASSWORD=" /opt/babanuj-command-center/.env.production | cut -d= -f2- | tr -d "\r"')
[ -z "$PW" ] && { echo "FATAL: could not read DB password"; exit 1; }

pkill -f "$PORT:.*:5432" 2>/dev/null
$SSH -fN -o ServerAliveInterval=30 -o ExitOnForwardFailure=yes -L "$PORT:$DBIP:5432" "$VPS" \
  || { echo "FATAL: tunnel failed"; exit 1; }
TUN=$(pgrep -f "$PORT:$DBIP:5432" | head -1)
trap '[ -n "${TUN:-}" ] && kill "$TUN" 2>/dev/null' EXIT

cd "$HOME/babanuj-ops" || exit 1
DATABASE_URL="postgres://bcc:${PW}@127.0.0.1:${PORT}/bcc" \
  python3 posthog-marketing-sync.py --days "$DAYS" --channels "$CHANNELS" --verbose
echo "----- exit $? at $(date '+%F %T') -----"
