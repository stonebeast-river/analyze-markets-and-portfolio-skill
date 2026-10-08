import json,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from market_core.http import DataSourceError
from market_core.providers.fund_huaan import HuaanDealingProvider,LANDING
from market_core.fund_products import assemble_product
from market_core.models import Observation
from market_core.store import MarketStore
from market_core.pipeline import MarketPipeline

class Client:
    def __init__(self):
        self.landing=('个人投资者 <p>基金申购限额一览表——更新至2026年09月24日。'
                      '<a href="/limits/current.xls">点此查看</a></p>'
                      '<p>境外节假日汇总——更新至2026年03月31日。</p>').encode()
        self.final=LANDING;self.calls=[]
    def get_bytes(self,url):
        self.calls.append(url)
        return (self.landing,self.final) if url==LANDING else (bytes.fromhex('d0cf11e0a1b11ae1')+b'fixture',url)
    def source_receipts(self):return []
    def bind_rows(self,rows,receipts):return rows

class HuaanDealingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.client=Client()
        self.rows=[['注：“√”代表此业务开放；“X”代表尚未开通此业务；“暂停”代表暂停受理此业务',*['']*8],
            ['']*9,['']*9,['','基金代码','基金简称','申购','赎回','定期定额','转换转入','转换转出',''],
            ['QDII','华安纳斯达克100联接A','040046','单日单账户累计申购应不超过5元','√','同申购','X','X',''],
            ['','华安纳斯达克100联接C','014978','','√','','X','X',''],
            ['指数型','华安黄金ETF联接C','000217','√','√','√','√','√','']]
        self.sheet=SimpleNamespace(nrows=len(self.rows),ncols=9,name='SQL Results',
            merged_cells=[(4,6,3,4),(4,6,5,6)],row_values=lambda i:self.rows[i],cell_value=lambda r,c:self.rows[r][c])
        self.book=SimpleNamespace(nsheets=1,sheet_by_index=lambda _:self.sheet)
        self.registry=self.root/'registry.json'
        self.registry.write_text(json.dumps({'funds':{code:{'manager':'华安基金','name':name} for code,name in
            [('040046','华安纳斯达克100ETF联接(QDII)A'),('014978','华安纳斯达克100ETF联接(QDII)C'),('000217','华安黄金ETF联接C')]}}),encoding='utf-8')
    def tearDown(self):self.temp.cleanup()
    def fetch(self,codes=None):
        with patch('xlrd.open_workbook',return_value=self.book):
            return HuaanDealingProvider(self.registry,self.client).fetch_evidence(codes or ['040046','014978','000217'])
    def test_exact_codes_use_body_columns_and_preserve_merged_quota_scope(self):
        rows=self.fetch();a,c,gold=[r.value for r in rows]
        self.assertEqual(c['business']['subscription']['daily_account_quota_yuan'],5)
        self.assertEqual(c['business']['subscription']['cell_source']['cell'],'D6')
        self.assertEqual(c['business']['subscription']['cell_source']['anchor'],'D5')
        self.assertEqual(c['business']['subscription']['cell_source']['merged_share_codes'],['040046','014978'])
        self.assertEqual(a['business']['subscription']['cross_share_class_aggregation'],'not_established_by_table')
        self.assertTrue(a['source_code_name_headers_reversed'])
        self.assertEqual(gold['business']['subscription']['state'],'reported_open')
        self.assertFalse(gold['current_subscription_verified']);self.assertFalse(gold['holiday_calendar_applied'])
    def test_wrong_share_name_or_duplicated_code_is_rejected(self):
        self.rows[4][1]='华安纳斯达克100联接C'
        with self.assertRaisesRegex(DataSourceError,'name/code mismatch'):self.fetch(['040046'])
        self.rows[4][1]='华安纳斯达克100联接A';self.rows[5][2]='040046'
        with self.assertRaisesRegex(DataSourceError,'duplicated'):self.fetch(['040046'])
    def test_unknown_date_or_offsite_link_fails_before_workbook_request(self):
        self.client.landing=self.client.landing.replace('更新至2026年09月24日'.encode(),b'')
        with self.assertRaisesRegex(DataSourceError,'date'):self.fetch()
        self.assertEqual(len(self.client.calls),1)
        self.client.landing=('个人投资者 <p>基金申购限额一览表 更新至2026年09月24日'
                             '<a href="https://other.test/current.xls">表</a></p>').encode()
        with self.assertRaisesRegex(DataSourceError,'leaves issuer'):self.fetch()
        self.assertEqual(len(self.client.calls),2)
    def test_swapped_legend_meanings_cannot_keep_old_business_states(self):
        self.rows[0][0]='注：“√”代表尚未开通此业务；“X”代表此业务开放；“暂停”代表暂停受理此业务'
        with self.assertRaisesRegex(DataSourceError,'legend changed'):self.fetch()
    def test_dated_open_snapshot_does_not_approve_current_product(self):
        row=self.fetch(['000217'])[0];store=MarketStore(self.root/'data.sqlite3');store.upsert_observations([row])
        store.upsert_observations([Observation('fixture','fund_document','summary:000217','2026-03-17',
            {'code':'000217','name':'华安黄金ETF联接C','kind':'summary','publication_date':'2026-03-17',
             'sha256':'fixture','source_url':'https://www.huaan.com.cn/summary.pdf',
             'facts_verified_against_current_bytes':True,'reviewed_facts':{'currency':'CNY','share_class':'C','fund_type':'etf_link'}})])
        product=assemble_product(store,'000217').value
        self.assertEqual(product['dated_manager_dealing_snapshot']['business']['subscription']['state'],'reported_open')
        self.assertEqual(product['subscription_status'],'unknown')
        self.assertFalse(product['subscription_currentness_verified']);self.assertFalse(product['selection_ready'])

    def test_configured_allocation_collects_status_without_other_sources(self):
        rows=self.fetch(['000217'])
        config={'database':str(self.root/'configured.sqlite3'),
                'profiles':{'allocation':{'huaan_fund_codes':['000217']}},
                'providers':{'huaan_dealing':{'enabled':True}}}
        pipeline=MarketPipeline(config,config_path=self.root/'config.json')
        with patch('market_core.pipeline.HuaanDealingProvider') as provider:
            provider.return_value.name='huaan_issuer_dealing';provider.return_value.client=None
            provider.return_value.fetch_evidence.return_value=rows
            runs=pipeline.run_profile('allocation')
        self.assertEqual(len(runs),1);self.assertEqual(runs[0].status,'ok')
        self.assertEqual(len(pipeline.store.get_observations('fund_dealing_snapshot','000217')),1)

if __name__=='__main__':unittest.main()
