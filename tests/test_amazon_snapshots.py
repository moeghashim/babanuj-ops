"""Focused regression checks for API boundaries, history keys and SQL escaping."""
import importlib.util
from datetime import date
from pathlib import Path
import unittest
import tempfile
from types import SimpleNamespace
from unittest.mock import patch

from lib.amazon_sync import AdsReportClient, batch_upsert_sql, require_vps
from lib import amazon_sync


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).resolve().parents[1] / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


snapshot = load('amazon-state-snapshot')
archive = load('amazon-keyword-archive')


class SnapshotTests(unittest.TestCase):
    def test_empty_campaign_filter_never_pulls_all_children(self):
        def post(*args):
            self.fail('must not issue an unfiltered child request')
        self.assertEqual(snapshot.pull(post, *snapshot.LIST_ENDPOINTS['keywords'], campaign_ids=[]), [])

    def test_pagination_preserves_extended_data_and_filter(self):
        calls = []
        def post(path, content_type, body):
            calls.append(body)
            return {'keywords': [{'keywordId': len(calls)}], **({'nextToken': 'next'} if len(calls) == 1 else {})}
        result = snapshot.pull(post, *snapshot.LIST_ENDPOINTS['keywords'], campaign_ids=['fixture'])
        self.assertEqual(len(result), 2)
        self.assertEqual(calls[1]['nextToken'], 'next')
        self.assertTrue(all(call['includeExtendedDataFields'] for call in calls))
        self.assertTrue(all(call['campaignIdFilter'] == {'include': ['fixture']} for call in calls))

    def test_zero_budget_is_preserved(self):
        self.assertEqual(snapshot.campaign_budget({'budget': {'budget': 0, 'budgetType': 'DAILY'}}), (0, 'DAILY'))

    def test_listing_channels_and_status(self):
        self.assertEqual(snapshot.ListingClient._parse({'fulfillmentAvailability': [{'fulfillmentChannelCode': 'AMAZON_NA'}], 'summaries': [{'status': ['BUYABLE']}]}), ('FBA', 'BUYABLE'))
        self.assertEqual(snapshot.ListingClient._parse({'fulfillmentAvailability': [{'fulfillmentChannelCode': 'DEFAULT'}]}), ('FBM', 'UNKNOWN'))

    def test_requires_prod_destination(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaises(KeyError):
                require_vps()

    def test_transport_retry_replays_the_same_idempotent_sql(self):
        failed = SimpleNamespace(returncode=255, stdout='', stderr='connection closed')
        success = SimpleNamespace(returncode=0, stdout='verified', stderr='')
        with patch.dict('os.environ', {'BCC_VPS': 'fixture@fixture.invalid'}), patch.object(amazon_sync.subprocess, 'run', side_effect=[failed, success]) as run, patch.object(amazon_sync.time, 'sleep'):
            self.assertEqual(amazon_sync.prod_psql('begin; commit;'), 'verified')
            self.assertEqual(run.call_count, 2)
            self.assertTrue(all(call.kwargs['input'] == 'begin; commit;' for call in run.call_args_list))

    def test_sql_errors_are_not_retried_and_hide_destinations_and_row_context(self):
        failed = SimpleNamespace(returncode=3, stdout='', stderr='ERROR: fixture.invalid rejected query\nCONTEXT: private row')
        with patch.dict('os.environ', {'BCC_VPS': 'fixture@fixture.invalid'}), patch.object(amazon_sync.subprocess, 'run', return_value=failed) as run:
            with self.assertRaises(RuntimeError) as error:
                amazon_sync.prod_psql('fixture SQL')
            self.assertEqual(run.call_count, 1)
            self.assertNotIn('fixture.invalid', str(error.exception))
            self.assertNotIn('private row', str(error.exception))


class ArchiveTests(unittest.TestCase):
    def test_90_days_chunked_inclusive_and_refresh_each_window(self):
        client = AdsReportClient({})
        windows = []
        with patch.object(client, 'refresh') as refresh, patch.object(client, '_window', side_effect=lambda *args: windows.append(args[-2:]) or []):
            client.report('fixture', [], [], date(2026, 7, 18), date(2026, 10, 15))
        self.assertEqual(windows, [(date(2026, 7, 18), date(2026, 8, 17)), (date(2026, 8, 18), date(2026, 9, 17)), (date(2026, 9, 18), date(2026, 10, 15))])
        self.assertEqual(refresh.call_count, 3)

    def test_search_terms_aggregate_by_entity_and_exact_term(self):
        row = {'date': '2026-10-15', 'campaignId': 'campaign', 'adGroupId': 'group', 'keywordId': 'keyword', 'searchTerm': "buy 'dates'", 'cost': '0.10', 'clicks': 1, 'unitsSoldClicks7d': 2}
        rows = archive.search_term_rows([row, row, dict(row, searchTerm='other')])
        self.assertEqual(len(rows), 2)
        self.assertEqual(str(rows[0][9]), '0.20')
        self.assertEqual(rows[0][8], 2)
        self.assertEqual(rows[0][-1], 4)

    def test_opt_in_report_cache_reuses_only_same_day_profile_configuration(self):
        body = {'configuration': {'reportTypeId': 'fixture'}, 'startDate': '2026-10-01'}
        client = AdsReportClient({'AMAZON_ADS_PROFILE_ID': 'fixture-profile'})
        with tempfile.TemporaryDirectory() as directory, patch.dict('os.environ', {'AMAZON_REPORT_CACHE': str(Path(directory) / 'reports.json')}), patch.object(client, 'request', return_value={'reportId': 'fixture-report'}) as request:
            self.assertEqual(client.report_id(body), 'fixture-report')
            self.assertEqual(client.report_id(body), 'fixture-report')
            self.assertEqual(request.call_count, 1)
            cache_key = client.report_cache_key(body)
            other = AdsReportClient({'AMAZON_ADS_PROFILE_ID': 'other-fixture-profile'})
            self.assertNotEqual(cache_key, other.report_cache_key(body))
            self.assertNotEqual(cache_key, client.report_cache_key(dict(body, startDate='2026-10-02')))
            with patch.object(amazon_sync, 'date') as clock:
                clock.today.return_value = date(2027, 1, 1)
                self.assertNotEqual(cache_key, client.report_cache_key(body))
            self.assertEqual((Path(directory) / 'reports.json').stat().st_mode & 0o777, 0o600)

    def test_absent_target_bid_and_share_remain_unknown(self):
        rows = archive.target_rows([{'date': '2026-10-15', 'campaignId': 'campaign', 'adGroupId': 'group', 'keywordId': 'keyword'}])
        self.assertIsNone(rows[0][6])
        self.assertIsNone(rows[0][-1])

    def test_failed_reports_never_write_partial_archive(self):
        with patch.object(archive, 'parse_args') as args, patch.object(archive, 'require_vps'), patch.object(archive, 'load_env', return_value={}), patch.object(archive, 'AdsReportClient') as client, patch.object(archive, 'prod_psql') as write:
            args.return_value.days = 14
            client.return_value.report.side_effect = [
                [{'date': '2026-10-15', 'campaignId': 'campaign', 'adGroupId': 'group', 'searchTerm': 'dates'}],
                RuntimeError('second report failed'),
            ]
            with self.assertRaises(RuntimeError):
                archive.main()
            write.assert_not_called()

    def test_batch_sql_escapes_values_and_bounds_batches(self):
        sql = batch_upsert_sql('fixture', ['id', 'value'], [('a', "quote' slash\\ newline\n\\.\n"), ('b', None)], ['id'], ['value'])
        self.assertIn("quote'' slash\\\\", sql)
        self.assertIn('NULL', sql)
        self.assertEqual(batch_upsert_sql('fixture', ['id'], [], ['id'], ['id']), '')
        sql = batch_upsert_sql('fixture', ['id'], [(str(i),) for i in range(501)], ['id'], ['id'])
        self.assertEqual(sql.count('insert into'), 2)
        with self.assertRaises(ValueError):
            batch_upsert_sql('fixture;drop', ['id'], [], ['id'], ['id'])


if __name__ == '__main__':
    unittest.main()
