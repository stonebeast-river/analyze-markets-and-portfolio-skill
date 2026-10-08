import os
import tempfile
import unittest
from datetime import datetime,timedelta
from pathlib import Path
from unittest.mock import patch

from market_core.models import Bar,Quote,Observation
from market_core.store import MarketStore
from market_core.task_health import completed_cash_session,profile_health,recent_cash_sessions


class TaskHealthTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.store=MarketStore(self.root/'fixture.sqlite3')
        self.cutoff='2026-10-05T12:00:00+00:00'
        self.config={'profiles':{'allocation':{'global_symbols':['SPY']}},
                     'providers':{'twelve_data':{'enabled':True,'source':'yahoo'}}}
        dates=list(reversed(recent_cash_sessions('US_CASH','2026-10-02',61)))
        self.store.upsert_bars([Bar('yahoo_public_chart','SPY','1d',day,100,102,99,101,currency='USD',
                                   price_basis='provider_split_adjusted_close',
                                   raw={'exchange_timezone':'America/New_York','instrument_type':'ETF'}) for day in dates])

    def tearDown(self):self.temp.cleanup()

    def failed_run(self,provider,dataset):
        with patch.object(self.store,'_now',return_value='2026-10-05T09:01:00+00:00'):
            self.store.record_run(provider,dataset,'2026-10-05T09:00:00+00:00','failed',0)

    def test_unrelated_retired_failure_does_not_fail_current_requirements(self):
        self.failed_run('yahoo_public_chart','global_daily_bars:CNY=X')
        result=profile_health(self.store,self.config,'allocation',as_of=self.cutoff)
        self.assertEqual(result['status'],'ok')
        self.assertEqual(result['ignored_failure_stream_count'],1)
        self.assertEqual(result['required_streams'],1)

    def test_relevant_source_failure_is_degraded_even_when_stored_data_are_current(self):
        self.failed_run('yahoo_public_chart','global_daily_bars:SPY')
        result=profile_health(self.store,self.config,'allocation',as_of=self.cutoff)
        self.assertEqual(result['status'],'degraded')
        self.assertEqual(result['requirements'][0]['state'],'ready')

    def test_mixed_sources_are_not_combined_to_complete_window(self):
        self.config['profiles']['allocation']['global_symbols']=['IWM']
        self.store.upsert_bars([Bar('other','IWM','1d','2026-10-02',100,102,99,101,currency='USD',price_basis='provider_split_adjusted_close')])
        result=profile_health(self.store,self.config,'allocation',as_of=self.cutoff)
        self.assertEqual(result['requirements'][0]['state'],'missing')

    def test_missing_scheduled_session_is_not_hidden_by_row_count(self):
        with self.store.connect() as db:db.execute("DELETE FROM bars WHERE timestamp='2026-09-30'")
        self.store.upsert_bars([Bar('yahoo_public_chart','SPY','1d','2026-06-01',100,102,99,101,currency='USD',price_basis='provider_split_adjusted_close')])
        result=profile_health(self.store,self.config,'allocation',as_of=self.cutoff)
        self.assertIn('missing_scheduled_daily_sessions',result['requirements'][0]['issues'])
        self.assertIn('2026-09-30',result['requirements'][0]['missing_sessions'])

    def test_completed_daily_session_differs_from_intraday_clock(self):
        self.assertEqual(completed_cash_session('CN_CASH','2026-10-08T10:00:00+08:00'),'2026-09-30')
        self.assertEqual(completed_cash_session('CN_CASH','2026-10-08T16:00:00+08:00'),'2026-10-08')

    def test_dst_and_us_early_close_are_applied(self):
        self.assertEqual(completed_cash_session('US_CASH','2026-11-27T17:59:00+00:00'),'2026-11-25')
        self.assertEqual(completed_cash_session('US_CASH','2026-11-27T18:01:00+00:00'),'2026-11-27')
        self.assertEqual(completed_cash_session('US_CASH','2026-07-06T19:59:00+00:00'),'2026-07-02')
        self.assertEqual(completed_cash_session('US_CASH','2026-07-06T20:01:00+00:00'),'2026-07-06')

    def test_calendar_scope_expiry_and_futures_are_unknown(self):
        self.assertIsNone(completed_cash_session('US_CASH','2027-01-04T22:00:00+00:00'))
        self.assertIsNone(completed_cash_session(None,self.cutoff))

    def test_unknown_fund_currency_and_calendar_do_not_pass_by_presence(self):
        config={'profiles':{'allocation':{'fund_codes':['000051']}},'providers':{'fund_eastmoney':{'enabled':True}}}
        self.store.upsert_observations([Observation('eastmoney_fund_page_fallback','fund_unit_nav','000051','2026-09-30',1.2,currency='unknown')])
        result=profile_health(self.store,config,'allocation',as_of=self.cutoff)
        self.assertIn('verified_NAV_currency',result['requirements'][0]['issues'])
        self.assertIn('fund_NAV_currentness:unknown',result['requirements'][0]['issues'])

    def test_compatible_complete_alternative_is_recovery_without_merging(self):
        config={'profiles':{'allocation':{'cn_benchmarks':['sh000929']}},
                'providers':{'baostock':{'enabled':True},'tencent':{'enabled':True}}}
        days=list(reversed(recent_cash_sessions('CN_CASH','2026-09-30',61)))
        self.store.upsert_quotes([Quote('tencent_web_quote','sh000929','2026-09-30T15:00:00+08:00',last=101,previous_close=100,currency='CNY')])
        self.store.upsert_bars([Bar('tencent_web_history','sh000929','1d',day,100,102,99,101,currency='CNY',price_basis='unadjusted') for day in days])
        self.failed_run('baostock_free_history','cn_daily_bars:sh000929')
        result=profile_health(self.store,config,'allocation',as_of=self.cutoff)
        self.assertEqual(result['status'],'recovered')
        selected=next(row for row in result['requirements'] if row['kind']=='daily_bars')
        self.assertEqual(selected['provider'],'tencent_web_history')
        self.assertTrue(selected['alternative_used'])
        self.assertEqual(len(result['recovered_primary_failures']),1)


if __name__=='__main__':unittest.main(verbosity=2)
