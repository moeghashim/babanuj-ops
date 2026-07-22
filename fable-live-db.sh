#!/bin/zsh
# fable-live-db.sh — open an SSH tunnel to the prod bcc Postgres and print the
# DATABASE_URL to use. The DB container has no host port (by design); we resolve
# its docker-network IP and password over SSH each run, so restarts don't break it.
#   source ~/babanuj-ops/fable-live-db.sh   # exports DATABASE_URL, opens tunnel
set -e
VPS="root@<vps-host>"; KEY="$HOME/.ssh/babanuj_deploy"; LPORT=15432
IP=$(ssh -i "$KEY" -o BatchMode=yes "$VPS" "docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' bcc-prod-postgres")
PW=$(ssh -i "$KEY" -o BatchMode=yes "$VPS" "grep '^POSTGRES_PASSWORD=' /opt/babanuj-command-center/.env.production | cut -d= -f2-")
pkill -f "ssh.*-L $LPORT:" 2>/dev/null || true
ssh -i "$KEY" -o BatchMode=yes -f -N -L $LPORT:$IP:5432 "$VPS"
export DATABASE_URL="postgres://bcc:${PW}@localhost:${LPORT}/bcc"
echo "tunnel up: localhost:$LPORT → bcc-prod-postgres ($IP)"
