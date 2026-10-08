"""Dated official public ChinaBond curve snapshots, distinct from fund returns."""
import math,re
from datetime import date,datetime,timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from ..http import DataSourceError,HttpClient
from ..models import Observation


CURVES={
 'ChinaBond Government Bond Yield Curve':'CN:GOVERNMENT_YIELD',
 'ChinaBond Financial Bond of Commercial Bank Yield Curve (AAA)':'CN:AAA_BANK_YIELD',
 'ChinaBond CP&Note Yield Curve (AAA)':'CN:AAA_CP_NOTE_YIELD'}


class _Tables(HTMLParser):
    def __init__(self):super().__init__();self.rows=[];self.row=None;self.cell=None;self.dates=[]
    def handle_starttag(self,tag,attrs):
        values=dict(attrs)
        if tag=='input' and values.get('id')=='gzr':self.dates.append(values.get('value'))
        if tag=='tr':self.row=[]
        if tag in {'td','th'} and self.row is not None:self.cell=[]
    def handle_data(self,text):
        if self.cell is not None:self.cell.append(text)
    def handle_endtag(self,tag):
        if tag in {'td','th'} and self.cell is not None:
            self.row.append(' '.join(''.join(self.cell).split()));self.cell=None
        if tag=='tr' and self.row is not None:self.rows.append(self.row);self.row=None


def parse_curve_snapshot(page,*,cutoff=None):
    parser=_Tables();parser.feed(page)
    headers=[r for r in parser.rows if r and re.fullmatch(r'\d{4}-\d{2}-\d{2}\(%\)',r[0])]
    if len(headers)!=1:raise DataSourceError('Unique dated percent yield-curve header required')
    header=headers[0];day=header[0][:10];date.fromisoformat(day)
    if set(parser.dates)!={day}:raise DataSourceError('Displayed yield date and table date disagree')
    if cutoff and day>cutoff[:10]:raise DataSourceError('Yield curve lies after requested observation cutoff')
    maturities=[]
    for text in header[1:]:
        match=re.fullmatch(r'(\d+(?:\.\d+)?)(月|年)',text)
        if not match:raise DataSourceError('Unknown yield maturity header')
        years=float(match[1])/(12 if match[2]=='月' else 1)
        if not 0<years<=100 or years in maturities:raise DataSourceError('Invalid/duplicate yield maturity')
        maturities.append(years)
    curves=[];seen=set()
    for row in parser.rows:
        if not row or row[0] not in CURVES:continue
        if row[0] in seen or len(row)!=len(header):raise DataSourceError('Yield rows have duplicate identities or mismatched maturity columns')
        seen.add(row[0]);points=[]
        for years,text in zip(maturities,row[1:]):
            value=None if text in {'','-','--','—'} else float(text)
            if value is not None and not math.isfinite(value):raise DataSourceError('Non-finite yield')
            points.append({'maturity_years':years,'yield_percent':value,'reported_cell':text})
        if not any(p['yield_percent'] is not None for p in points):raise DataSourceError('Official curve has no usable reported yields')
        curves.append({'curve_identity':CURVES[row[0]],'curve_name':row[0],'observation_date':day,
            'country':'CN','currency':'CNY','points':points,'missing_cells':sum(p['yield_percent'] is None for p in points),
            'measurement':'annualized source curve yield percent; not fund NAV return or an executable bond quote',
            'original_publication_time_verified':False,'historical_vintage_verified':False})
    if seen!=set(CURVES):raise DataSourceError('Expected official government/bank/CP-note curve identities missing')
    return curves


class ChinaBondCurveProvider:
    name='chinabond_public_yield_curve'
    URL='https://yield.chinabond.com.cn/cbweb-cbrc-web/cbrc/showCbrc'
    def __init__(self,client=None):self.client=client or HttpClient(timeout=12,retries=1)
    def fetch_evidence(self):
        page,url=self.client.get_text(self.URL)
        if urlsplit(url).hostname!='yield.chinabond.com.cn':raise DataSourceError('Official curve response host changed')
        cutoff=datetime.now(timezone.utc).isoformat()
        curves=parse_curve_snapshot(page,cutoff=cutoff)
        rows=[Observation(self.name,'cn_bond_yield_curve',c['curve_identity'],c['observation_date'],c,
            unit='annualized_yield_percent_by_maturity_years',currency='CNY',quality='official_public_snapshot',
            source_url=url,latency='daily_public_snapshot',raw={'retrieved_at':cutoff,'publication_schedule_not_actual_release':'17:30 Beijing per public methodology',
              'scope':'current displayed curve; no historical download or fund duration inference'}) for c in curves]
        return self.client.bind_rows(rows)
