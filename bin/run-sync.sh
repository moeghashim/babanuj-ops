#!/usr/bin/env bash
# Shared launchd entrypoint for the local Babanuj scheduled syncs.
set -euo pipefail

OPS_DIR="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="${BABANUJ_ENV_FILE:-$HOME/.config/babanuj/.env}"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  . "$ENV_FILE"
  set +a
fi

if [[ -z "${BCC_VPS:-}" || "$BCC_VPS" == *"<"* ]]; then
  echo "FATAL: BCC_VPS is unset or still contains a placeholder; refusing to run sync" >&2
  exit 78
fi

export PATH="$HOME/.local/bin:$HOME/go/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
mkdir -p "$OPS_DIR/logs"

if [[ $# -lt 1 ]]; then
  echo "usage: $0 SCRIPT [ARGS...]" >&2
  exit 64
fi

script="$1"
shift
if [[ "$script" != /* ]]; then
  script="$OPS_DIR/$script"
fi
if [[ ! -f "$script" ]]; then
  echo "FATAL: sync script not found: $script" >&2
  exit 66
fi

log="$OPS_DIR/logs/$(basename "$script").log"
exec >>"$log" 2>&1
echo "===== $(date '+%F %T') $(basename "$script") ====="

case "$script" in
  *.py) exec /usr/bin/python3 "$script" "$@" ;;
  *.sh)
    shebang="$(head -n 1 "$script")"
    if [[ "$shebang" == *zsh* ]]; then
      exec /bin/zsh "$script" "$@"
    fi
    exec /bin/bash "$script" "$@"
    ;;
  *) exec "$script" "$@" ;;
esac
