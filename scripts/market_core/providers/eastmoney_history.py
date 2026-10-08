"""Public completed-day OHLC and turnover inputs, not vendor chip outputs."""
import math
from datetime import date
from ..http import HttpClient,DataSourceError
from ..symbols import normalize_cn_symbol,eastmoney_secid
from ..models import Bar,Observation

class EastmoneyHistoryProvider:
    name='eastmoney_daily_price_turnover'
    def __init__(self,client=None):
        self.client=client or HttpClient(timeout=8,retries=0)
    def fetch_inputs(self,symbol,*,start,end,adjustment='qfq'):
        symbol=normalize_cn_symbol(symbol,stock_only=True)
        if adjustment not in {'qfq','hfq','unadjusted'}:raise ValueError('Explicit price basis required')
        if date.fromisoformat(start)>date.fromisoformat(end):raise ValueError('Invalid history window')
        data,url=self.client.get_json('https://push2his.eastmoney.com/api/qt/stock/kline/get',
            params={'secid':eastmoney_secid(symbol),'klt':101,'fqt':{'qfq':1,'hfq':2,'unadjusted':0}[adjustment],
                'beg':start.replace('-',''),'end':end.replace('-',''),'lmt':500,
                'fields1':'f1,f2,f3,f4,f5,f6','fields2':'f51,f52,f53,f54,f55,f56,f57,f58,f59,f60,f61'},
            headers={'Referer':'https://quote.eastmoney.com/'})
        body=data.get('data') or {}
        if body.get('code')!=symbol[2:] or not body.get('klines'):raise DataSourceError('Missing or mismatched daily identity')
        bars=[];turns=[]
        for line in body['klines']:
            p=line.split(',')
            if len(p)!=11:raise DataSourceError('Changed daily field contract')
            day=date.fromisoformat(p[0]).isoformat()
            if not start<=day<=end:raise DataSourceError('History outside requested completed-day window')
            o,c,h,l,v,a,turn=(float(p[i]) for i in (1,2,3,4,5,6,10))
            if not all(math.isfinite(x) for x in (o,c,h,l,v,a,turn)) or not 0<l<=min(o,c)<=max(o,c)<=h or min(v,a,turn)<0:
                raise DataSourceError('Invalid price/volume/turnover input')
            bars.append(Bar(self.name,symbol,'1d',day,o,h,l,c,v,a,'hands_100_shares','CNY','CNY',
                price_basis=adjustment,source_url=url,raw={'line':line}))
            turns.append(Observation(self.name,'cn_daily_turnover',symbol,day,{'turnover_pct':turn},
                unit='percent',currency='CNY',source_url=url,raw={'line':line}))
        if [b.timestamp for b in bars]!=sorted(set(b.timestamp for b in bars)):raise DataSourceError('Duplicate or unordered days')
        return self.client.bind_rows(bars),self.client.bind_rows(turns)
