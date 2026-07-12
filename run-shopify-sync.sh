#!/usr/bin/env bash
# Babanuj — Shopify → Command Center Postgres sync (idempotent UPSERT).
#
# Invoked by cron (/etc/cron.d/babanuj-shopify). Reads the prod DB password from
# the app's env file at runtime so NO secret lives in crontab, and runs the
# extractor as a one-shot container on bcc-prod-net (reaches the internal `db`).
#
#   /opt/babanuj-ops/run-shopify-sync.sh [DAYS]   # DAYS window, default 2
set -euo pipefail
ENVF=/opt/babanuj-command-center/.env.production
PW=$(grep -E '^POSTGRES_PASSWORD=' "$ENVF" | cut -d= -f2- | tr -d "\"'")
DAYS="${1:-2}"
echo "=== $(date -u +%FT%TZ) shopify-sync --days $DAYS ==="
exec docker run --rm --network bcc-prod-net \
  -e DATABASE_URL="postgres://bcc:${PW}@db:5432/bcc" \
  -v /opt/babanuj-ops/secrets/shopify.env:/root/.config/shopify-pp-cli/.env:ro \
  babanuj-ops:latest shopify-sync.py --days "$DAYS" --verbose
