#!/usr/bin/env python3
# Google Ads — pull campaign metrics for the Babanuj ad account via the REST
# GoogleAdsService.search endpoint. This works AROUND the CLI's broken `sync`
# (which sends an unsupported `limit` param to listAccessibleCustomers).
#
# Note: GOOGLE_ADS_CUSTOMER_ID in the .env is the MANAGER (6457175449), which
# can't return metrics. The real Babanuj ad account is 1604376990.
import json, urllib.request, urllib.parse, os, urllib.error

HOME = os.path.expanduser('~')
DATA = HOME + '/babanuj-ops/data'
ACCOUNT = '1604376990'   # Babanuj ad account (client under manager 6457175449)

def parse(path):
    d = {}
    for line in open(path):
        s = line.strip()
        if s and not s.startswith('#') and not s.startswith('[') and '=' in s:
            k, v = s.split('=', 1)
            # config.toml uses single-quoted literal strings; strip both quote types
            d[k.strip()] = v.strip().strip('"').strip("'").strip()
    return d

cfg = parse(HOME + '/.config/google-ads-pp-cli/config.toml')
env = parse(HOME + '/.config/google-ads-pp-cli/.env')

# Mint a fresh access token from the refresh token (matched OAuth client from config.toml)
tok = urllib.parse.urlencode({
    'client_id': cfg['client_id'], 'client_secret': cfg['client_secret'],
    'refresh_token': cfg['refresh_token'], 'grant_type': 'refresh_token',
}).encode()
at = json.load(urllib.request.urlopen('https://oauth2.googleapis.com/token', data=tok))['access_token']

hdr = {'Authorization': 'Bearer ' + at,
       'developer-token': env['GOOGLE_ADS_DEVELOPER_TOKEN'],
       'Content-Type': 'application/json'}
gaql = ("SELECT campaign.name, campaign.status, metrics.cost_micros, metrics.clicks, "
        "metrics.impressions, metrics.conversions, metrics.conversions_value "
        "FROM campaign WHERE segments.date DURING LAST_30_DAYS "
        "ORDER BY metrics.cost_micros DESC")
req = urllib.request.Request(
    f'https://googleads.googleapis.com/v24/customers/{ACCOUNT}/googleAds:search',
    data=json.dumps({'query': gaql}).encode(), headers=hdr)
res = json.loads(urllib.request.urlopen(req).read().decode())

rows = []
for r in res.get('results', []):
    c, m = r['campaign'], r.get('metrics', {})
    rows.append({
        'name': c.get('name'), 'status': c.get('status'),
        'cost': round(int(m.get('costMicros', 0)) / 1e6, 2),
        'clicks': int(m.get('clicks', 0)), 'impressions': int(m.get('impressions', 0)),
        'conversions': round(float(m.get('conversions', 0)), 2),
        'conv_value': round(float(m.get('conversionsValue', 0)), 2),
    })
out = {
    'account': ACCOUNT, 'date_range': 'last_30_days', 'campaigns': rows,
    'totals': {
        'cost': round(sum(r['cost'] for r in rows), 2),
        'clicks': sum(r['clicks'] for r in rows),
        'impressions': sum(r['impressions'] for r in rows),
        'conversions': round(sum(r['conversions'] for r in rows), 2),
        'conv_value': round(sum(r['conv_value'] for r in rows), 2),
    },
}
os.makedirs(DATA, exist_ok=True)
json.dump(out, open(DATA + '/google-ads-campaigns.json', 'w'), indent=2)
print('google-ads: %d campaigns, $%.2f spend, %d clicks' % (
    len(rows), out['totals']['cost'], out['totals']['clicks']))
