import unittest
from market_core.global_history_request import public_history_request,completed_public_intraday
from market_core.models import Bar


class GlobalHistoryRequestTests(unittest.TestCase):
    def test_minute_budget_is_not_interpreted_as_years_of_minute_history(self):
        self.assertEqual(public_history_request('1min',300),('1m',2))
        self.assertEqual(public_history_request('5min',500),('5m',2))
        self.assertEqual(public_history_request('1day',300),('1d',600))
        self.assertEqual(public_history_request('1day',100),('1d',450))
        with self.assertRaises(ValueError):public_history_request('1m',0)

    def test_cutoff_uses_request_time_and_keeps_formed_minute_out_of_indicators(self):
        rows=[Bar('fixture','NVDA','1m','2026-10-07T14:04:00+00:00',10,11,9,10),
              Bar('fixture','NVDA','1m','2026-10-07T14:05:00+00:00',10,11,9,10)]
        result=completed_public_intraday(rows,'1m','2026-10-07T14:05:45+00:00')
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].timestamp,rows[0].timestamp)
        self.assertEqual(result[0].session,'completed_provider_intraday_bar')
        self.assertTrue(result[0].raw['intraday_clock_check_is_local'])
        self.assertEqual(len(completed_public_intraday(rows,'1m','2026-10-07T14:06:00+00:00')),2)
