import unittest
from dataclasses import replace
from market_core.models import Bar
from market_core.sector_windows import compare_price_windows


class SectorWindowTests(unittest.TestCase):
    def series(self,symbol,currency='CNY',provider='fixture'):
        return [Bar(provider,symbol,'1d','2026-09-'+str(day).zfill(2),10,12,9,10+day/100,
                    currency=currency,price_basis='unadjusted') for day in range(1,7)]

    def test_missing_sector_session_does_not_extend_week_window(self):
        sector=self.series('sector');benchmark=self.series('benchmark');sector.pop(2)
        result=compare_price_windows(sector,benchmark,periods=(5,))
        self.assertEqual(result['windows'][0]['status'],'missing_sector_sessions')

    def test_currency_mismatch_cannot_produce_relative_return(self):
        result=compare_price_windows(self.series('sector','CNY'),self.series('benchmark','USD'))
        self.assertEqual(result['status'],'incomplete')

    def test_source_providers_stay_separate_in_valid_pair(self):
        result=compare_price_windows(self.series('sector',provider='one'),self.series('benchmark',provider='two'),periods=(5,))
        self.assertTrue(result['different_provider_pair'])
        self.assertEqual(result['windows'][0]['relative_return_percentage_points'],0)

    def test_current_endpoints_must_match(self):
        sector=self.series('sector');sector.pop()
        result=compare_price_windows(sector,self.series('benchmark'))
        self.assertIn('matched_latest_session',result['missing'])

    def test_other_symbol_or_interval_cannot_enter_a_price_series(self):
        for change in ({'symbol':'other'},{'interval':'5m'}):
            with self.subTest(change=change):
                rows=self.series('sector');rows[0]=replace(rows[0],**change)
                result=compare_price_windows(rows,self.series('benchmark'))
                self.assertIn('one_symbol_and_interval_per_series',result['missing'])
        rows=[replace(r,interval='5m') for r in self.series('sector')]
        self.assertIn('matched_intervals',compare_price_windows(rows,self.series('benchmark'))['missing'])

    def test_invalid_prices_or_nonchronological_dates_refuse_comparison(self):
        original=self.series('sector');base=self.series('benchmark')
        fixtures=[original[::-1],original+[original[-1]],
                  [replace(original[0],close=0),*original[1:]],
                  [replace(original[0],close=float('nan')),*original[1:]]]
        for rows in fixtures:
            self.assertEqual(compare_price_windows(rows,base)['status'],'incomplete')

    def test_interior_gap_retains_fixed_endpoint_return_separately(self):
        rows=self.series('sector');first,last=rows[0],rows[-1];rows.pop(2)
        result=compare_price_windows(rows,self.series('benchmark'),periods=(5,))
        self.assertEqual(result['windows'][0]['status'],'missing_sector_sessions')
        endpoint=result['endpoint_windows_with_gaps'][0]
        self.assertEqual(endpoint['start'],first.timestamp);self.assertEqual(endpoint['end'],last.timestamp)
        self.assertAlmostEqual(endpoint['sector_price_return'],last.close/first.close-1)
        self.assertEqual(endpoint['missing_dates'],['2026-09-03'])
        self.assertFalse(endpoint['complete_window'])
        self.assertFalse(endpoint['continuous_indicator_or_path_measure_supported'])

    def test_missing_endpoint_does_not_select_an_earlier_common_date(self):
        rows=self.series('sector')[1:]
        result=compare_price_windows(rows,self.series('benchmark'),periods=(5,))
        self.assertEqual(result['endpoint_windows_with_gaps'],[])


if __name__=='__main__':unittest.main(verbosity=2)
