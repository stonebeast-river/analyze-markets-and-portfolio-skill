import copy
import hashlib
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from market_core.fund_reviewed_holdings import reviewed_snapshot,reviewed_lookthrough


class ReviewedHoldingTests(unittest.TestCase):
    def fixture(self,root):
        body=b'%PDF original-fixture';digest=hashlib.sha256(body).hexdigest();(root/(digest+'.pdf')).write_bytes(body)
        pages=['示例全球股票基金 2026年6月30日 基金主代码 123456 报告送出日期：二〇二六年八月三十一日',
               '单位：人民币元 本期末 2026年6月30日 净资产合计 1000.00 总资产 1100.00 股票资产 800.00',
               '占基金资产净值比例 MU US 美光 100.00 10.00',
               '占基金总资产比例 股票 800.00 72.73 中国香港 80.00 7.27']
        evidence=lambda page,excerpt:{'page':page,'excerpt':excerpt}
        review={'fund_code':'123456','fund_family_name':'示例全球股票基金','report_date':'2026-06-30','publication_date':'2026-08-31',
            'source':{'url':'https://example.test/original.pdf','sha256':digest},'report_currency':'CNY',
            'identity_evidence':evidence(1,'基金主代码 123456'),'report_date_evidence':evidence(1,'2026年6月30日'),
            'publication_date_evidence':evidence(1,'报告送出日期：二〇二六年八月三十一日'),
            'unit_evidence':evidence(2,'单位：人民币元'),
            'denominators':{'fund_net_assets':{'value':1000,'evidence':evidence(2,'净资产合计 1000.00')},
                            'total_assets':{'value':1100,'evidence':evidence(2,'总资产 1100.00')}},
            'securities':[{'identity':'US:MU','source_identifier':'MU US','name':'美光','asset_class':'stock',
                          'value':100,'reported_percent':10,'denominator':'fund_net_assets',
                          'denominator_evidence':evidence(3,'占基金资产净值比例'),'evidence':evidence(3,'MU US 美光 100.00 10.00')}],
            'allocations':[{'dimension':'asset_class','category':'股票','value':800,'reported_percent':72.73,
                            'denominator':'total_assets','denominator_evidence':evidence(4,'占基金总资产比例'),
                            'evidence':evidence(4,'股票 800.00 72.73')}]}
        pdf=SimpleNamespace(pages=[SimpleNamespace(extract_text=lambda text=p:text) for p in pages])
        return review,pdf

    def test_weight_denominators_converted_without_top_holdings_normalization(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            with patch('pypdf.PdfReader',return_value=pdf):result=reviewed_snapshot(review,root)
            self.assertEqual(result['security_detail_of_fund_NAV'],.1)
            self.assertEqual(result['remaining_net_NAV_after_disclosed_detail'],.9)
            self.assertEqual(result['allocations'][0]['weight_of_fund_NAV'],.8)
            output=reviewed_lookthrough(result)
            self.assertFalse(output['today_holdings_reconstructed']);self.assertFalse(result['economic_FX_verified'])

    def test_changed_bytes_identity_period_or_unbound_number_reject(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);original,pdf=self.fixture(root)
            alterations=[lambda r:r.update(fund_code='654321'),lambda r:r.update(report_date='2026-05-31'),
                         lambda r:r.update(publication_date='2026-07-01'),
                         lambda r:r['securities'][0].update(value=101),
                         lambda r:r['allocations'][0].update(denominator='fund_net_assets')]
            for edit in alterations:
                review=copy.deepcopy(original);edit(review)
                with patch('pypdf.PdfReader',return_value=pdf),self.assertRaises(ValueError):reviewed_snapshot(review,root)
            (root/(original['source']['sha256']+'.pdf')).write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'bytes differ'):reviewed_snapshot(original,root)

    def test_duplicate_security_or_allocation_cannot_inflate_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            for key in ('securities','allocations'):
                altered=copy.deepcopy(review);altered[key].append(copy.deepcopy(altered[key][0]))
                with patch('pypdf.PdfReader',return_value=pdf),self.assertRaises(ValueError):reviewed_snapshot(altered,root)

    def test_child_fund_stays_unresolved_and_wrong_report_unit_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            review['securities'][0]['asset_class']='fund'
            with patch('pypdf.PdfReader',return_value=pdf):result=reviewed_snapshot(review,root)
            self.assertEqual(len(reviewed_lookthrough(result)['unresolved_child_funds']),1)
            altered=copy.deepcopy(review);altered['report_currency']='USD'
            with patch('pypdf.PdfReader',return_value=pdf),self.assertRaisesRegex(ValueError,'currency'):reviewed_snapshot(altered,root)

    def test_price_mapping_must_match_original_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            review['securities'][0].update(price_market='US',price_identity='MU')
            with patch('pypdf.PdfReader',return_value=pdf):self.assertEqual(reviewed_snapshot(review,root)['securities'][0]['price_identity'],'MU')
            review['securities'][0]['price_identity']='MSFT'
            with patch('pypdf.PdfReader',return_value=pdf),self.assertRaisesRegex(ValueError,'price identity'):reviewed_snapshot(review,root)

    def test_child_fund_link_cannot_borrow_an_unrelated_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            review['securities'][0].update(asset_class='fund',child_fund_code='654321')
            with patch('pypdf.PdfReader',return_value=pdf),self.assertRaisesRegex(ValueError,'Child fund code'):reviewed_snapshot(review,root)

    def test_amount_only_FX_measure_does_not_fabricate_reported_percent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            row=review['allocations'][0];row['dimension']='balance_sheet_FX';row['reported_percent']=None
            with patch('pypdf.PdfReader',return_value=pdf):result=reviewed_snapshot(review,root)
            self.assertEqual(result['allocations'][0]['weight_of_fund_NAV'],.8)
            self.assertFalse(result['allocations'][0]['reported_percent_available'])
            self.assertFalse(result['economic_FX_verified'])

    def test_derivative_market_exposure_is_separate_from_stock_and_book_coverage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            pdf.pages.append(SimpleNamespace(extract_text=lambda:'NQU6 持仓量(买/卖) -2 合约市值 200.00 公允价值 0.00'))
            review['derivatives']=[{'identity':'NQU6','source_identifier':'NQU6','signed_contracts':-2,'contract_value':200,
                'evidence':{'page':5,'excerpt':'NQU6 持仓量(买/卖) -2 合约市值 200.00 公允价值 0.00'},
                'contract_value_evidence':{'page':5,'excerpt':'合约市值'}}]
            with patch('pypdf.PdfReader',return_value=pdf):snapshot=reviewed_snapshot(review,root)
            result=reviewed_lookthrough(snapshot)
            self.assertEqual(result['coverage']['security_detail_of_fund_NAV'],.1)
            self.assertEqual(result['derivatives']['known_contract_rows'][0]['signed_contract_exposure_fraction_of_NAV'],-.2)
            self.assertEqual(result['derivatives']['known_gross_contract_market_fraction_of_NAV'],.2)
            self.assertFalse(result['derivatives']['added_to_stock_or_asset_weights'])

    def test_reported_notional_is_not_relabelled_as_contract_market_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);review,pdf=self.fixture(root)
            pdf.pages.append(SimpleNamespace(extract_text=lambda:'NQU6 持仓量 -2 合同/名义金额 200.00'))
            review['derivatives']=[{'identity':'NQU6','source_identifier':'NQU6','signed_contracts':-2,'contract_value':200,
                'evidence':{'page':5,'excerpt':'NQU6 持仓量 -2 合同/名义金额 200.00'},
                'contract_value_evidence':{'page':5,'excerpt':'合同/名义金额'}}]
            with patch('pypdf.PdfReader',return_value=pdf):snapshot=reviewed_snapshot(review,root)
            result=reviewed_lookthrough(snapshot)['derivatives']
            self.assertIsNone(result['known_gross_contract_market_fraction_of_NAV'])
            self.assertEqual(result['known_gross_reported_notional_fraction_of_NAV'],.2)
