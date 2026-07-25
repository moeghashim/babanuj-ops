# fable-env.sh — source this before running fable so all three ad channels are wired.
#   source ~/babanuj-ops/fable-env.sh && fable run --tick daily --live-read
# References existing credential files; contains no secrets itself.

# Meta: system-user token + ad account (ads_management scope)
if [ -f "$HOME/.config/meta/.env" ]; then
  set -a; . "$HOME/.config/meta/.env"; set +a
  # #113 scoping: fable's Meta executor honors FABLE_META_ACCOUNT_ID ?? AD_ACCOUNT_ID
  export FABLE_META_ACCOUNT_ID="${FABLE_META_ACCOUNT_ID:-$AD_ACCOUNT_ID}"
fi

# Amazon: OAuth refresh env (5 vars) for amazon-ads-pp-cli
if [ -f "$HOME/.config/amazon-ads-pp-cli/.env" ]; then
  while IFS='=' read -r k v; do
    case "$k" in ''|'#'*) continue;; esac
    export "$k=$v"
  done < "$HOME/.config/amazon-ads-pp-cli/.env"
fi

# Google: OAuth lives in config.toml; the shared GOOGLE_ADS_CUSTOMER_ID is the MANAGER (MCC)
# account, so point fable at the Babanuj CLIENT account explicitly.
if [ -f "$HOME/.config/google-ads-pp-cli/.env" ]; then
  set -a; . "$HOME/.config/google-ads-pp-cli/.env"; set +a
fi
export FABLE_GOOGLE_CUSTOMER_ID="${FABLE_GOOGLE_CUSTOMER_ID:-1604376990}"
