"""Read-only Amazon report helpers and transactional prod bcc upserts.

No account identifiers or credentials are stored here. Only list/report API
operations are allowed; production SQL travels over the existing SSH tunnel.
"""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, timedelta

ADS_ENV = os.path.expanduser('~/.config/amazon-ads-pp-cli/.env')
SELLER_ENV = os.path.expanduser('~/.config/amazon-seller-pp-cli/.env')
ADS_HOST = 'https://advertising-api.amazon.com'

# Reuse the audited, side-effect-free credential parser from this checkout.
_spec = importlib.util.spec_from_file_location('amazon_audit', Path(__file__).resolve().parents[1] / 'amazon-ads-audit.py')
_audit = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_audit)
load_env = _audit.load_env


def require_vps():
    vps = os.environ['BCC_VPS']
    if not vps or '<' in vps or vps.startswith('-'):
        raise ValueError('BCC_VPS must be set to a valid SSH destination')
    return vps


def prod_psql(sql, timeout=600):
    """Execute idempotent SQL; retry SSH transport failures, never SQL errors."""
    vps = require_vps()
    command = [
        'ssh', '-i', os.path.expanduser('~/.ssh/babanuj_deploy'),
        '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
        '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=6', vps,
        'docker exec -i bcc-prod-postgres psql -X -q -U bcc -d bcc -At -v ON_ERROR_STOP=1',
    ]
    for attempt in range(3):
        result = subprocess.run(command, input=sql, text=True,
                                capture_output=True, timeout=timeout)
        if result.returncode == 0:
            return result.stdout
        if result.returncode == 255 and attempt < 2:
            print('[bcc] SSH transport failed; retrying idempotent transaction',
                  file=sys.stderr, flush=True)
            time.sleep(2 ** attempt)
            continue
        # Keep the useful first error, excluding row context and destinations.
        lines = result.stderr.strip().splitlines()
        diagnostic = lines[0] if lines else 'no diagnostic'
        for destination in (vps, vps.rsplit('@', 1)[-1]):
            diagnostic = diagnostic.replace(destination, '<BCC_VPS>')
        diagnostic = re.sub(r'\b(?:\d{1,3}\.){3}\d{1,3}\b', '<IP>', diagnostic)
        raise RuntimeError(f'prod bcc psql failed (exit {result.returncode}): {diagnostic}')


def batch_upsert_sql(table, columns, rows, conflict, updates):
    """Build bounded multi-row upserts; escape all API values as SQL literals."""
    for identifier in [table, *columns, *conflict, *updates]:
        if not re.fullmatch(r'[a-z_][a-z_0-9]*', identifier):
            raise ValueError('invalid SQL identifier')

    def literal(value):
        if value is None:
            return 'NULL'
        if isinstance(value, (list, dict)):
            value = json.dumps(value)
        # E-strings make escaping independent of the server's SQL settings.
        return "E'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"

    statements = []
    for offset in range(0, len(rows), 500):
        values = []
        for row in rows[offset:offset + 500]:
            if len(row) != len(columns):
                raise ValueError('row does not match INSERT columns')
            values.append('(' + ','.join(literal(value) for value in row) + ')')
        assignments = ','.join(
            f'{name}=now()' if name == 'archived_at' else f'{name}=excluded.{name}'
            for name in updates
        )
        statements.append(
            f'insert into {table} ({",".join(columns)}) values ' + ','.join(values)
            + f' on conflict ({",".join(conflict)}) do update set {assignments};'
        )
    return '\n'.join(statements)


def refresh_lwa_token(env, prefix):
    if prefix == 'AMAZON_ADS':
        return _audit.refresh_token(env)
    body = urllib.parse.urlencode({
        'grant_type': 'refresh_token', 'refresh_token': env['SP_API_REFRESH_TOKEN'],
        'client_id': env['SP_API_LWA_CLIENT_ID'],
        'client_secret': env['SP_API_LWA_CLIENT_SECRET'],
    }).encode()
    request = urllib.request.Request('https://api.amazon.com/auth/o2/token', data=body,
                                    headers={'Content-Type': 'application/x-www-form-urlencoded'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)['access_token']


class AdsReportClient:
    """Async v3 DAILY reports, max 31 days per window; fail on incomplete data."""

    def __init__(self, env):
        self.env = env
        self.headers = {}
        self.refreshed_at = 0

    def refresh(self):
        self.headers = {
            'Authorization': 'Bearer ' + refresh_lwa_token(self.env, 'AMAZON_ADS'),
            'Amazon-Advertising-API-ClientId': self.env.get('AMAZON_ADS_API_CLIENT_ID') or self.env['AMAZON_ADS_CLIENT_ID'],
            'Amazon-Advertising-API-Scope': self.env['AMAZON_ADS_PROFILE_ID'],
        }
        self.refreshed_at = time.monotonic()

    def request(self, path, body=None):
        for attempt in range(6):
            if time.monotonic() - self.refreshed_at > 3000:
                self.refresh()
            headers = dict(self.headers)
            if body is not None:
                headers['Content-Type'] = 'application/vnd.createasyncreportrequest.v3+json'
            request = urllib.request.Request(ADS_HOST + path, headers=headers,
                data=json.dumps(body).encode() if body is not None else None)
            try:
                with urllib.request.urlopen(request, timeout=90) as response:
                    return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code == 425 and body is not None:
                    # Amazon reuses a report for an identical request.
                    detail = json.loads(error.read()).get('detail', '')
                    match = re.search(r'\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b', detail)
                    if match:
                        return {'reportId': match.group()}
                if error.code == 401 and attempt < 5:
                    self.refresh()
                    continue
                if error.code in (429, 500, 502, 503, 504) and attempt < 5:
                    time.sleep(min(2 ** attempt, 30))
                    continue
                raise

    def report(self, report_type, group_by, columns, start, end):
        rows = []
        while start <= end:
            last = min(start + timedelta(days=30), end)
            self.refresh()
            rows.extend(self._window(report_type, group_by, columns, start, last))
            start = last + timedelta(days=1)
        return rows

    def report_cache_key(self, body):
        # A local-day key permits explicit backfill resumption without sharing
        # reports across profiles, configurations, or attribution refresh days.
        identity = [date.today().isoformat(), self.env['AMAZON_ADS_PROFILE_ID'], body]
        return hashlib.sha256(json.dumps(identity, sort_keys=True).encode()).hexdigest()

    def report_id(self, body):
        """Optionally retain IDs for resuming one long backfill on the same day."""
        cache_path = os.environ.get('AMAZON_REPORT_CACHE')
        if not cache_path:
            return self.request('/reporting/reports', body)['reportId']
        path = Path(cache_path).expanduser()
        cached = json.loads(path.read_text()) if path.exists() else {}
        key = self.report_cache_key(body)
        if key in cached:
            return cached[key]
        report_id = self.request('/reporting/reports', body)['reportId']
        cached[key] = report_id
        # Atomic replacement, mode 0600; the cache contains private report IDs.
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(cached, stream)
        try:
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return report_id

    def _window(self, report_type, group_by, columns, start, end):
        body = {'name': 'keyword archive', 'startDate': str(start), 'endDate': str(end),
                'configuration': {'adProduct': 'SPONSORED_PRODUCTS', 'groupBy': group_by,
                    'columns': columns, 'reportTypeId': report_type,
                    'timeUnit': 'DAILY', 'format': 'GZIP_JSON'}}
        report_id = self.report_id(body)
        print(f'[{report_type}] {start}..{end}: polling', file=sys.stderr, flush=True)
        previous_status = None
        for _ in range(120):
            result = self.request('/reporting/reports/' + report_id)
            if result['status'] != previous_status:
                print(f"[{report_type}] {start}..{end}: {result['status']}", file=sys.stderr, flush=True)
                previous_status = result['status']
            if result['status'] == 'COMPLETED':
                with urllib.request.urlopen(result['url'], timeout=180) as response:
                    rows = json.loads(gzip.decompress(response.read()))
                if not isinstance(rows, list):
                    raise ValueError('report payload must be a list')
                print(f'[{report_type}] {start}..{end}: {len(rows)} rows', file=sys.stderr, flush=True)
                return rows
            if result['status'] == 'FAILED':
                raise RuntimeError(f'{report_type} report failed')
            time.sleep(30)
        raise TimeoutError(f'{report_type} report timed out')
