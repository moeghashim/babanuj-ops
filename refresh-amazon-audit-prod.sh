#!/bin/zsh
# refresh-amazon-audit-prod.sh — refresh the Amazon SP structure audit and push
# the snapshot to the PROD Command Center Postgres (behind ops.babanuj.com).
#
# Runs the extractor locally (it reads Amazon creds from
# ~/.config/amazon-ads-pp-cli/.env), then ships the resulting JSONB snapshot to
# the prod `bcc` DB via the babanuj_deploy SSH key + `docker exec psql`. Amazon
# creds never leave this Mac; the prod DB has no host port, so SSH is the path.
#
# Scheduled daily via ~/Library/LaunchAgents/com.babanuj.amazon-audit.plist.
set -euo pipefail

OPS="$HOME/babanuj-ops"
VPS="${BCC_VPS:-${BCC_VPS}}"
KEY="$HOME/.ssh/babanuj_deploy"
LOG="$OPS/logs/amazon-audit.log"
mkdir -p "$OPS/logs" "$OPS/amazon-ads"

ts() { date "+%Y-%m-%d %H:%M:%S"; }
{
  echo "[$(ts)] refresh-amazon-audit-prod: start"

  # 1. produce the audit artifact (no DATABASE_URL → artifact only, no local write)
  /usr/bin/env -u DATABASE_URL python3 "$OPS/amazon-ads-audit.py"

  ART="$(ls -t "$OPS"/amazon-ads/asin-audit-*.json 2>/dev/null | head -1)"
  if [[ -z "${ART:-}" || ! -s "$ART" ]]; then
    echo "[$(ts)] ERROR: no audit artifact produced"; exit 1
  fi
  echo "[$(ts)] artifact: $ART"

  # 2. ship the snapshot to prod bcc (dollar-quoted JSON → no escaping)
  {
    printf "INSERT INTO dashboard_ads_audit_snapshots (platform, payload) VALUES ('amazon_sp', \$payload\$"
    cat "$ART"
    printf "\$payload\$::jsonb);\n"
  } | ssh -i "$KEY" -o BatchMode=yes -o ConnectTimeout=20 "$VPS" \
        "docker exec -i bcc-prod-postgres psql -U bcc -d bcc" >/dev/null

  echo "[$(ts)] pushed snapshot to prod bcc — done"
} >> "$LOG" 2>&1
