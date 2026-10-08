import unittest
from market_core.providers.chinabond_curve import parse_curve_snapshot,CURVES
from market_core.http import DataSourceError


def page():
    rows='<tr><th>2026-09-30(%)</th><th>3<!--月-->月</th><th>10年</th><th>30年</th></tr>'
    for name in CURVES:rows+='<tr><td>'+name+'</td><!--<td>999</td>--><td>1.1611</td><td>1.6822</td><td></td></tr>'
    return '<input id="gzr" value="2026-09-30"><table>'+rows+'</table>'


class ChinaBondCurveTests(unittest.TestCase):
    def test_dated_terms_percent_and_missing_cell_preserved(self):
        result=parse_curve_snapshot(page(),cutoff='2026-10-07')
        self.assertEqual(result[0]['points'][0]['maturity_years'],.25)
        self.assertEqual(result[0]['points'][1]['yield_percent'],1.6822)
        self.assertIsNone(result[0]['points'][2]['yield_percent'])
        self.assertEqual(result[0]['missing_cells'],1)
        self.assertFalse(result[0]['historical_vintage_verified'])

    def test_wrong_dates_units_columns_and_missing_identity_refuse(self):
        for changed in [page().replace('value="2026-09-30"','value="2026-09-29"'),
                        page().replace('(%)','(BP)'),page().replace('<th>30年</th>',''),
                        page().replace('ChinaBond Government Bond Yield Curve','Unverified curve'),
                        page().replace('1.6822','nan')]:
            with self.assertRaises((DataSourceError,ValueError)):parse_curve_snapshot(changed)
        with self.assertRaisesRegex(DataSourceError,'after'):parse_curve_snapshot(page(),cutoff='2026-09-29')
