import copy
import unittest
from market_core.fund_graph import recursive_lookthrough,node_from_snapshot


def node(code,positions,day='2026-06-30',currency='CNY'):
    return {'fund_code':code,'source':{'report_date':day,'publication_date':'2026-08-31',
        'document_sha256':code*10,'source_url':'https://example.test/'+code,'currency':currency},
        'positions':positions,'allocations':[],'derivatives':[],
        'fees':{'annual_fraction':.01,'charge_base':'not independently validated in synthetic graph fixture'}}


def stock(identity,weight):return {'identity':identity,'name':identity,'asset_class':'stock','weight_of_fund_NAV':weight}
def fund(code,weight):return {'identity':'FUND:'+code,'asset_class':'fund','weight_of_fund_NAV':weight,'child_fund_code':code}


class FundGraphTests(unittest.TestCase):
    def graph(self):
        return {'111111':node('111111',[fund('222222',.6),stock('X',.2)]),
                '222222':node('222222',[stock('X',.4),fund('333333',.5)],currency='USD'),
                '333333':node('333333',[stock('X',.5),stock('Y',.3)],day='2026-08-15',currency='HKD')}

    def test_three_layers_merge_same_stock_without_wrapper_double_count_or_currency_conversion(self):
        graph=self.graph();r=recursive_lookthrough('111111',graph.get)
        weights={x['identity']:x['estimated_weight_of_root_NAV'] for x in r['securities']}
        self.assertAlmostEqual(weights['X'],.59);self.assertAlmostEqual(weights['Y'],.09)
        self.assertEqual(len(r['securities'][0]['paths']),3)
        self.assertAlmostEqual(r['coverage']['net_residual_of_root_NAV'],.32)
        self.assertAlmostEqual(r['coverage']['accounting_sum'],1)
        self.assertTrue(r['mixed_report_dates']);self.assertTrue(r['all_referenced_children_resolved'])
        self.assertFalse(r['full_recursive_lookthrough_verified']);self.assertFalse(r['today_holdings_reconstructed'])

    def test_missing_child_retains_exact_unknown_weight_instead_of_zero(self):
        graph=self.graph();graph.pop('333333');r=recursive_lookthrough('111111',graph.get)
        self.assertAlmostEqual(r['coverage']['leaf_detail_of_root_NAV'],.44)
        self.assertAlmostEqual(r['coverage']['unresolved_child_of_root_NAV'],.3)
        self.assertAlmostEqual(r['coverage']['net_residual_of_root_NAV'],.26)
        self.assertFalse(r['all_referenced_children_resolved'])

    def test_shared_child_counts_both_parent_paths_while_cycle_is_bounded(self):
        graph=self.graph();graph['111111']['positions']=[fund('222222',.5),fund('333333',.5)]
        r=recursive_lookthrough('111111',graph.get)
        y=next(s for s in r['securities'] if s['identity']=='Y')
        self.assertAlmostEqual(y['estimated_weight_of_root_NAV'],.225)
        graph['333333']['positions']=[fund('111111',.8)]
        r=recursive_lookthrough('111111',graph.get)
        self.assertTrue(any(x['reason']=='cycle' for x in r['unresolved_child_funds']))
        self.assertAlmostEqual(r['coverage']['accounting_sum'],1)

    def test_depth_budget_bad_identity_and_nonfinite_weights_are_explicit(self):
        graph=self.graph();r=recursive_lookthrough('111111',graph.get,max_depth=1)
        self.assertEqual(r['unresolved_child_funds'][0]['reason'],'depth_limit')
        r=recursive_lookthrough('111111',graph.get,max_paths=1)
        self.assertEqual(r['unresolved_child_funds'][0]['reason'],'path_budget')
        graph['222222']['fund_code']='999999'
        with self.assertRaisesRegex(ValueError,'exact requested'):recursive_lookthrough('111111',graph.get)
        graph=self.graph();graph['111111']['positions'][0]['weight_of_fund_NAV']=float('nan')
        with self.assertRaisesRegex(ValueError,'Finite'):recursive_lookthrough('111111',graph.get)

    def test_residual_cancellation_does_not_claim_all_holdings_or_aggregate_fees(self):
        graph={'111111':node('111111',[fund('222222',.8)]),'222222':node('222222',[stock('X',1.25)])}
        r=recursive_lookthrough('111111',graph.get)
        self.assertAlmostEqual(r['coverage']['net_residual_of_root_NAV'],0)
        self.assertFalse(r['all_holdings_disclosed']);self.assertFalse(r['full_recursive_lookthrough_verified'])
        self.assertTrue(all(not x['effective_total_fee_computed'] for x in r['fee_layers']))

    def test_derivative_and_classification_layers_do_not_add_into_leaf_assets(self):
        graph=self.graph();graph['222222']['derivatives']=[{'identity':'future','signed_contract_exposure_fraction_of_NAV':-.2}]
        graph['222222']['allocations']=[{'dimension':'industry','category':'tech','weight_of_fund_NAV':.4}]
        r=recursive_lookthrough('111111',graph.get)
        self.assertAlmostEqual(r['separate_derivative_paths'][0]['estimated_contract_measure_of_root_NAV'],-.12)
        self.assertAlmostEqual(r['layer_classifications'][0]['estimated_layer_measure_of_root_NAV'],.24)
        self.assertAlmostEqual(r['coverage']['leaf_detail_of_root_NAV'],.68)
        self.assertFalse(r['classification_layers_automatically_merged']);self.assertFalse(r['derivatives_added_to_asset_or_stock_weights'])

    def test_native_identity_merges_legacy_and_reviewed_rows_and_keeps_price_route(self):
        graph=self.graph();graph['111111']['positions']=[{**stock('sh600519',.2),'price_market':'CN','price_identity':'sh600519'},fund('222222',.6)]
        graph['222222']['positions']=[{**stock('CN:sh600519',.4),'price_market':'CN','price_identity':'sh600519'}]
        result=recursive_lookthrough('111111',graph.get)
        self.assertEqual(len(result['securities']),1)
        self.assertAlmostEqual(result['securities'][0]['estimated_weight_of_root_NAV'],.44)
        self.assertEqual(result['securities'][0]['price_identity'],'sh600519')

    def test_impossible_child_date_is_not_accepted_as_a_valid_snapshot(self):
        graph=self.graph();graph['222222']['source']['publication_date']='2026-05-01'
        with self.assertRaisesRegex(ValueError,'precedes'):recursive_lookthrough('111111',graph.get)

    def test_missing_root_or_fully_fund_invested_missing_child_does_not_claim_full_disclosure(self):
        r=recursive_lookthrough('111111',{}.get)
        self.assertFalse(r['all_holdings_disclosed'])
        r=recursive_lookthrough('111111',{'111111':node('111111',[fund('222222',1)])}.get)
        self.assertFalse(r['all_holdings_disclosed']);self.assertEqual(r['coverage']['unresolved_child_of_root_NAV'],1)

    def test_confirmed_no_futures_is_distinct_from_unreviewed_empty_rows(self):
        snapshot={'fund_code':'111111','report_date':'2026-06-30','publication_date':'2026-08-31',
            'document_sha256':'a'*64,'source_url':'https://example.test/a.pdf','stocks':[],'target_funds':[],'industries':[],
            'futures_contracts':[],'futures_detail_status':'reported_no_contract_positions','other_derivative_instruments_reviewed':False}
        a=recursive_lookthrough('111111',lambda code:node_from_snapshot(snapshot))
        snapshot['futures_detail_status']='section_not_reviewed'
        b=recursive_lookthrough('111111',lambda code:node_from_snapshot(snapshot))
        self.assertNotEqual(a['derivative_review_by_layer'],b['derivative_review_by_layer'])
        self.assertEqual(a['separate_derivative_paths'],b['separate_derivative_paths'])
