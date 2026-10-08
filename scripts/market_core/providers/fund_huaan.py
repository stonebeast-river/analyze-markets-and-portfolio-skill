"""Dated Huaan issuer dealing tables, with exact share rows and merged-cell provenance."""
import hashlib,json,re
from datetime import date,datetime,timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from ..http import HttpClient,DataSourceError
from ..models import Observation
from ..conventions import SHANGHAI

LANDING='https://www.huaan.com.cn/news/2021-08-30/202457_1.shtml'

class LandingParser(HTMLParser):
    def __init__(self):super().__init__();self.text=[];self.xls=[];self.blocks=[];self.block=None
    def handle_starttag(self,tag,attrs):
        if tag=='p':self.block={'text':[],'xls':[]}
        href=dict(attrs).get('href','')
        if tag=='a' and urlsplit(href).path.lower().endswith('.xls'):
            self.xls.append(href)
            if self.block is not None:self.block['xls'].append(href)
    def handle_endtag(self,tag):
        if tag=='p' and self.block is not None:self.blocks.append(self.block);self.block=None
    def handle_data(self,text):
        self.text.append(text)
        if self.block is not None:self.block['text'].append(text)

def name_key(value):return re.sub(r'[（(]QDII[）)]','',re.sub(r'\s+','',value)).replace('ETF','')

def cell_source(sheet,row,col):
    anchor=(row,col);covered=[]
    for r0,r1,c0,c1 in sheet.merged_cells:
        if r0<=row<r1 and c0<=col<c1:
            anchor=(r0,c0)
            covered=[str(sheet.cell_value(i,2)).strip() for i in range(r0,r1)
                     if re.fullmatch(r'\d{6}',str(sheet.cell_value(i,2)).strip())]
            break
    return {'value':sheet.cell_value(*anchor),'cell':f'{chr(65+col)}{row+1}',
            'anchor':f'{chr(65+anchor[1])}{anchor[0]+1}','merged_share_codes':covered}

def business_state(cell):
    raw=str(cell['value']).strip()
    state={'√':'reported_open','X':'reported_not_enabled','暂停':'reported_paused','同申购':'same_as_subscription'}.get(raw,'reported_text_unparsed')
    result={'state':state,'source_text':raw,'cell_source':cell}
    match=re.fullmatch(r'单日单账户累计申购应不超过(\d+(?:\.\d+)?)元',raw)
    if match:
        result.update(state='reported_limited',daily_account_quota_yuan=float(Decimal(match.group(1))),
                      quota_source_unit='yuan',cross_share_class_aggregation='not_established_by_table')
    return result

class HuaanDealingProvider:
    name='huaan_issuer_dealing'
    def __init__(self,registry_path,client=None):
        self.registry_path=Path(registry_path);self.client=client or HttpClient(user_agent='Mozilla/5.0',timeout=18,retries=0)

    def fetch_evidence(self,codes):
        codes=list(dict.fromkeys(codes));funds=json.loads(self.registry_path.read_text(encoding='utf-8-sig'))['funds']
        if not codes:raise DataSourceError('Choose at least one registered exact Huaan share code')
        for code in codes:
            if code not in funds or funds[code].get('manager') not in {'华安基金','华安基金管理有限公司'}:
                raise DataSourceError('No exact Huaan share registration: '+code)
        landing,source=self.client.get_bytes(LANDING)
        if urlsplit(source).hostname!='www.huaan.com.cn':raise DataSourceError('Huaan landing redirect leaves issuer host')
        landing_refs=self.client.source_receipts();parser=LandingParser();parser.feed(landing.decode('utf-8'))
        text=' '.join(parser.text)
        blocks=[block for block in parser.blocks if block['xls'] and '基金申购限额一览表' in ''.join(block['text'])]
        bound_text=''.join(blocks[0]['text']) if len(blocks)==1 else ''
        match=re.search(r'更新至(\d{4})年(\d{1,2})月(\d{1,2})日',bound_text)
        if not match or len(set(parser.xls))!=1 or '个人投资者' not in text:
            raise DataSourceError('Issuer table date, scope or unique workbook link is missing')
        source_date=date(*map(int,match.groups())).isoformat()
        if source_date>datetime.now(SHANGHAI).date().isoformat():raise DataSourceError('Issuer table date is in the future')
        workbook_url=urljoin(source,blocks[0]['xls'][0])
        if urlsplit(workbook_url).hostname!='www.huaan.com.cn' or urlsplit(workbook_url).scheme!='https':
            raise DataSourceError('Huaan workbook link leaves issuer HTTPS host')
        body,final=self.client.get_bytes(workbook_url);workbook_refs=self.client.source_receipts()
        if urlsplit(final).hostname!='www.huaan.com.cn':raise DataSourceError('Huaan workbook redirect leaves issuer host')
        if body[:8]!=bytes.fromhex('d0cf11e0a1b11ae1') or len(body)>2097152:
            raise DataSourceError('Issuer dealing table is not a bounded legacy XLS')
        try:import xlrd
        except ImportError:raise DataSourceError('Huaan legacy XLS requires the optional xlrd dependency') from None
        book=xlrd.open_workbook(file_contents=body,formatting_info=True)
        if book.nsheets!=1:raise DataSourceError('Unreviewed multi-sheet Huaan dealing layout')
        sheet=book.sheet_by_index(0)
        if sheet.nrows<5 or sheet.ncols!=9 or sheet.row_values(3)[3:8]!=['申购','赎回','定期定额','转换转入','转换转出']:
            raise DataSourceError('Huaan dealing business columns changed')
        headers=sheet.row_values(3)
        if headers[1:3] not in (['基金代码','基金简称'],['基金简称','基金代码']):
            raise DataSourceError('Huaan dealing identity columns changed')
        reversed_headers=headers[1:3]==['基金代码','基金简称']
        legend=str(sheet.cell_value(0,0))
        legend_compact=re.sub(r'\s+','',legend).replace('“','"').replace('”','"')
        if not all(re.search(pattern,legend_compact) for pattern in (
            r'"√"代表此业务开放',r'"X"代表(?:目前)?尚未开通此业务',r'"暂停"代表(?:目前)?暂停受理此业务')):
            raise DataSourceError('Huaan dealing legend changed')
        digest=hashlib.sha256(body).hexdigest();rows=[]
        for code in codes:
            matches=[i for i in range(4,sheet.nrows) if str(sheet.cell_value(i,2)).strip()==code]
            if len(matches)!=1:raise DataSourceError('Exact share row missing or duplicated: '+code)
            row=matches[0];name=str(sheet.cell_value(row,1)).strip()
            if name_key(name)!=name_key(funds[code]['name']):raise DataSourceError('Huaan table share name/code mismatch')
            business={field:business_state(cell_source(sheet,row,col)) for col,field in enumerate(
                ('subscription','redemption','periodic_subscription','conversion_in','conversion_out'),start=3)}
            value={'fund_code':code,'fund_name':name,'source_date':source_date,'investor_scope':'personal_investors',
                'business':business,'sheet':sheet.name,'source_row':row+1,'workbook_sha256':digest,
                'landing_sha256':hashlib.sha256(landing).hexdigest(),'landing_url':source,'workbook_url':final,
                'source_headers':sheet.row_values(3),'code_cell':f'C{row+1}','name_cell':f'B{row+1}',
                'source_code_name_headers_reversed':reversed_headers,
                'layout_note':('Body share codes are in C and names in B; the source B/C headings are reversed'
                               if reversed_headers else 'Body and headings match names in B and share codes in C'),
                'current_subscription_verified':False,'platform_channel_verified':False,
                'later_notice_audit_complete':False,'holiday_calendar_applied':False,
                'original_publication_time_known':False,
                'source_date_binding':'same_paragraph_as_selected_XLS_link','legend_semantics_verified':True,
                'currentness':'Dated issuer table; later changes, channels and current opening day require separate evidence'}
            rows.append(Observation(self.name,'fund_dealing_snapshot',code,source_date,value,
                publication=source_date,unit='business_symbols_and_source_yuan_quota',
                quality='issuer_dated_dealing_snapshot',source_url=final,
                raw={'row_values':sheet.row_values(row),'legend':legend}))
        return self.client.bind_rows(rows,[*landing_refs,*workbook_refs])
