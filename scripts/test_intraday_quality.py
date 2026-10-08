import unittest
from datetime import datetime
from dataclasses import replace
from market_core.models import Bar
from market_core.intraday_quality import audit_intraday_quality,mark_volume_indicator_quality
from types import SimpleNamespace
import tempfile,json
from pathlib import Path
from datetime import timedelta
from market_core.intraday_quality import quality_observations
from market_core.store import MarketStore
from market_core.indicators import indicator_rows_grouped
from market_core.workflow import prepare_research
from market_core.research import evidence_pack
from market_core.reproduction import measurement_matches
from dataclasses import asdict
from market_core.models import IndicatorValue


def row(volume=100,total=50):
    stamp=lambda s:int(datetime.fromisoformat(s).timestamp())
    return Bar('fixture','NVDA','1m','2026-10-07T14:14:00+00:00',10,11,9,10,volume=volume,volume_unit='share',currency='USD',
        raw={'metadata':{'exchangeTimezoneName':'America/New_York','regularMarketTime':stamp('2026-10-07T14:15:04+00:00'),
            'regularMarketVolume':total,'currentTradingPeriod':{'regular':{'start':stamp('2026-10-07T13:30:00+00:00'),'end':stamp('2026-10-07T20:00:00+00:00')}}}})


class IntradayQualityTests(unittest.TestCase):
    def test_conflicting_volume_cannot_confirm_volume_but_price_is_retained(self):
        result=audit_intraday_quality([row()])[0]
        self.assertFalse(result['volume_confirmation_eligible'])
        self.assertEqual(result['volume_reconciliation_state'],'completed_bar_sum_exceeds_later_vendor_cumulative')
        self.assertEqual(result['volume_comparison']['completed_bar_volume_sum_shares'],100)
        self.assertTrue(result['price_latest_snapshot_retained'])
        self.assertFalse(result['conflicting_volume_normalized'])

    def test_larger_later_partial_total_is_not_a_false_contradiction(self):
        result=audit_intraday_quality([row(total=120)])[0]
        self.assertIsNone(result['volume_confirmation_eligible'])
        self.assertEqual(result['volume_reconciliation_state'],'compatible_wider_cumulative_window_not_exact_reconciliation')

    def test_missing_volume_metadata_and_revision_are_not_zero_or_verified(self):
        changed=row(total=120);old=replace(changed,volume=90)
        result=audit_intraday_quality([changed],[old])[0]
        self.assertEqual(result['volume_revision_count'],1);self.assertFalse(result['volume_confirmation_eligible'])
        missing=replace(changed,raw={});result=audit_intraday_quality([missing])[0]
        self.assertFalse(result['volume_confirmation_eligible']);self.assertEqual(result['volume_comparison'],{})

    def test_volume_warning_propagates_without_masking_price_or_other_symbols(self):
        metrics=[SimpleNamespace(symbol='NVDA',name='close_volume_ratio',quality='locally_derived'),
                 SimpleNamespace(symbol='NVDA',name='macd_dif',quality='locally_derived'),
                 SimpleNamespace(symbol='OTHER',name='close_volume_ratio',quality='locally_derived')]
        result=mark_volume_indicator_quality(metrics,audit_intraday_quality([row()]))
        self.assertEqual(result[0].quality,'unverified_for_volume_confirmation')
        self.assertEqual(result[1].quality,'locally_derived');self.assertEqual(result[2].quality,'locally_derived')

    def test_quality_survives_store_evidence_and_freeze_without_becoming_macro_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=MarketStore(root/'data.sqlite3')
            first=datetime.fromisoformat('2026-10-07T13:30:00+00:00')
            rows=[replace(row(),timestamp=(first+timedelta(minutes=i)).isoformat(),close=10+i/1000,
                          price_basis='provider_split_adjusted_close') for i in range(45)]
            audits=audit_intraday_quality(rows)
            store.upsert_bars(rows);store.upsert_observations(quality_observations(audits,'2026-10-07T14:15:05+00:00'))
            store.upsert_indicators(mark_volume_indicator_quality(indicator_rows_grouped(rows),audits))
            evidence=evidence_pack(store,'NVDA',interval='1m',question='trend')
            self.assertEqual(len(evidence['source_quality_context']),1)
            prepare_research(store,root/'freeze',profile='tactical')
            frozen=json.loads((root/'freeze/research-inputs.json').read_text(encoding='utf-8'))['evidence_register'].values()
            volume=[x for x in frozen if x['record'].get('name')=='close_volume_ratio']
            self.assertTrue(volume);self.assertFalse(any(x['eligible'] for x in volume))
            price=[x for x in frozen if x['record'].get('name')=='macd_dif']
            self.assertTrue(any(x['eligible'] for x in price))
            quality=[x for x in frozen if x['record'].get('dataset')=='intraday_source_quality']
            self.assertTrue(quality);self.assertTrue(all(x['kind']=='market_price' and not x['eligible'] for x in quality))

    def test_known_use_downgrade_preserves_math_but_not_arbitrary_quality_or_value_edits(self):
        value=IndicatorValue('NVDA','1m','2026-10-07T14:14:00+00:00','close_volume_ratio',.8,
            parameters={},input_provider='fixture',quality='locally_derived')
        restricted=asdict(value);restricted['quality']='unverified_for_volume_confirmation'
        self.assertTrue(measurement_matches(restricted,value))
        restricted['value']=.9;self.assertFalse(measurement_matches(restricted,value))
        restricted['value']=.8;restricted['quality']='fabricated_quality';self.assertFalse(measurement_matches(restricted,value))
        price=replace(value,name='macd_dif');restricted=asdict(price);restricted['quality']='unverified_for_volume_confirmation'
        self.assertFalse(measurement_matches(restricted,price))
