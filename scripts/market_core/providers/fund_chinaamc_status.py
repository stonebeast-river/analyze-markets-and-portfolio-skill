"""Dated issuer business-state table: preserve its update date, never promote receipt time."""
import re,unicodedata
from html.parser import HTMLParser
from datetime import datetime,timezone
from ..http import HttpClient,DataSourceError
from ..models import Observation
from ..parsing import html_text


class TableRows(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='tr':self.row=[]
        if tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def parse_business_table(page,codes):
    text=html_text(page);normalized=unicodedata.normalize('NFKC',text)
    heading='华夏基金旗下基金开放状态一览表';start=normalized.find(heading)
    if start<0:raise DataSourceError('Issuer business table identity heading missing')
    dates=re.findall(r'更新日期\s*[:：]\s*(\d{4}-\d{2}-\d{2})',normalized[start:start+300])
    if len(set(dates))!=1:raise DataSourceError('Business table update date is not uniquely bound to heading')
    parser=TableRows();parser.feed(page)
    expected=['产品份额代码','产品份额简称','申购-当日可否交易','赎回-当日可否交易',
              '转换转入-当日可否交易','转换转出-当日可否交易','定期定额申购-当日可否交易','限制-当日可否交易']
    clean=lambda x:re.sub(r'\s+','',unicodedata.normalize('NFKC',x))
    headers=[i for i,row in enumerate(parser.rows) if [clean(x) for x in row]==expected]
    if len(headers)!=1:raise DataSourceError('Exact business table header order unrecognized')
    rows=parser.rows[headers[0]+1:];result=[]
    for code in codes:
        matches=[r for r in rows if r and r[0]==code]
        if len(matches)!=1 or len(matches[0])!=8:raise DataSourceError('Exact business share row absent, duplicate or malformed: '+code)
        row=matches[0]
        result.append({'fund_code':code,'fund_name':row[1],'source_update_date':dates[0],
            'subscription_flag':row[2],'redemption_flag':row[3],'conversion_in_flag':row[4],
            'conversion_out_flag':row[5],'DCA_flag':row[6],'restriction_text':row[7],
            'restriction_dash_is_not_unlimited_today':True,'current_subscription_verified':False,
            'source_header_and_row':{'headers':expected,'cells':row},
            'scope':'dated issuer business table; opening-day/channel/later-notice verification separate'})
    return result


class ChinaAMCBusinessProvider:
    name='chinaamc_dated_business_table'
    def __init__(self,client=None):self.client=client or HttpClient(timeout=12,retries=0,user_agent='Mozilla/5.0')
    def fetch_evidence(self,codes):
        if not codes or any(not re.fullmatch(r'\d{6}',c) for c in codes):raise ValueError('Exact share codes required')
        page,url=self.client.get_text('https://www.chinaamc.com/ProductForWeb/getCalendar')
        values=parse_business_table(page,codes);received=datetime.now(timezone.utc).isoformat()
        rows=[Observation(self.name,'fund_dealing_snapshot',v['fund_code'],received,
            {**v,'retrieved_at':received,'as_of_means':'response_receipt_time; page_update_label_retained_separately',
             'original_business_time_known':False},currency='unknown',
            unit='issuer_business_flags',source_url=url,quality='dated_primary_business_table') for v in values]
        return self.client.bind_rows(rows)
