#!/bin/zsh
# apply-settings-worker.sh — every 5 min: pull pending /setup edits from prod
# bcc, validate+apply via `fable setup --set` (schema-enforced), make verify,
# commit signed-off to main, mark applied/rejected, resync the page.
set -eu
REPO="$HOME/marketing"; VPS="${BCC_VPS:?BCC_VPS is required}"; KEY="${BCC_SSH_KEY:-$HOME/.ssh/babanuj_deploy}"
LOG="$HOME/babanuj-ops/logs/apply-settings.log"; mkdir -p "$HOME/babanuj-ops/logs"
psqlc(){ ssh -i "$KEY" -o BatchMode=yes "$VPS" "docker exec -i bcc-prod-postgres psql -U bcc -d bcc -tA" ; }
{
echo "[$(date '+%F %T')] tick"
PENDING=$(echo "select id||'|'||key||'|'||new_value from strategy_setting_edits where status='pending' order by id;" | psqlc)
[ -z "$PENDING" ] && { echo "  nothing pending"; exit 0; }
cd "$REPO"
[ -n "$(git status --porcelain)" ] && { echo "  repo dirty — skipping cycle"; exit 0; }
git checkout -q main && git pull -q origin main
APPLIED=0
OKIDS=""
echo "$PENDING" > /tmp/pending_edits.txt
while IFS='|' read -r id k v; do
  [ -z "$id" ] && continue
  if ERR=$(node --import tsx src/cli.ts setup --set "$k=$v" 2>&1); then
    echo "  staged #$id $k=$v"; OKIDS="$OKIDS $id"
  else
    R=$(echo "$ERR" | tail -1 | head -c 180 | sed "s/'//g")
    echo "  REJECTED #$id $k=$v — $R"
    echo "update strategy_setting_edits set status='rejected', applied_at=now(), reason='$R' where id=$id;" | psqlc >/dev/null
  fi
done < /tmp/pending_edits.txt
if [ -n "$(git status --porcelain)" ]; then
  # freshness targets name their own regen command — run them, up to 4 rounds
  for round in 1 2 3 4; do
    OUT=$(make verify 2>&1) && break
    CMD=$(echo "$OUT" | grep -oE "regenerate it with fable [^)]*" | head -1 | sed 's/regenerate it with fable //')
    [ -z "$CMD" ] && break
    echo "  regen: fable $CMD"
    rm -f /tmp/regen-lineage.sqlite; node --import tsx src/cli.ts ${=CMD} --db /tmp/regen-lineage.sqlite >/dev/null 2>&1 || node --import tsx src/cli.ts ${=CMD} >/dev/null 2>&1 || true
    git add -A strategy strategy.lock.json 2>/dev/null || true
  done
  git add -A strategy strategy.lock.json 2>/dev/null || true
  if make verify >/dev/null 2>&1; then
    git -c user.name="Moe Ghashim" -c user.email="mohanadgh@gmail.com" commit -q --signoff -m "Settings: apply operator edits from /setup

Co-Authored-By: Moe Ghashim <mohanadgh@gmail.com>" && git push -q origin main
    for id in $OKIDS; do echo "update strategy_setting_edits set status='applied', applied_at=now() where id=$id;" | psqlc >/dev/null; done
    echo "  committed + pushed; marked applied:$OKIDS"
  else
    git reset -q --hard origin/main
    echo "  VERIFY FAILED — batch reverted; edits left pending for triage"; exit 0
  fi
fi
python3 "$HOME/babanuj-ops/settings-sync-prod.py" >/dev/null && echo "  page resynced"
} >> "$LOG" 2>&1
