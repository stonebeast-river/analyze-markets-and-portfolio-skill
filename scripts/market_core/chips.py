"""Transparent turnover-decay cost model; no beneficial-owner or vendor CYQ claim."""
import base64,hashlib,html,json,math,contextlib,io
from pathlib import Path
from datetime import datetime,timedelta
from dataclasses import asdict
from .models import Bar
from .stock_conditions import expected_closed_session
from .symbols import normalize_cn_symbol

def estimate_chips(bars,turnover,*,bins=200,window=240,minimum=60):
    if type(bins)!=int or not 20<=bins<=1000 or type(window)!=int or window<minimum or minimum<2:
        raise ValueError('Invalid chip model parameters')
    if not bars or len(bars)!=len(turnover):raise ValueError('One turnover value per price day required')
    identities={(b.provider,b.symbol,b.interval,b.currency,b.price_basis) for b in bars}
    if len(identities)!=1 or bars[0].interval!='1d' or bars[0].currency!='CNY':raise ValueError('One CNY daily stock source required')
    normalize_cn_symbol(bars[0].symbol,stock_only=True)
    if bars[0].price_basis not in {'qfq','hfq','unadjusted'}:raise ValueError('Known chip price basis required')
    if [b.timestamp for b in bars]!=sorted(set(b.timestamp for b in bars)):raise ValueError('Unique increasing chip dates required')
    for b,t in zip(bars,turnover):
        if not all(math.isfinite(x) for x in (b.open,b.high,b.low,b.close)) or not 0<b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high:
            raise ValueError('Invalid chip OHLC')
        if t is None or not math.isfinite(t) or t<0:raise ValueError('Missing or invalid turnover; never replace with zero')
    bars=bars[-window:];turnover=turnover[-window:]
    if len(bars)<minimum:raise ValueError('At least '+str(minimum)+' matched completed trading days required')
    low=min(b.low for b in bars);high=max(b.high for b in bars)
    prices=[low] if low==high else [low+(high-low)*i/(bins-1) for i in range(bins)]
    weights=[0.0]*len(prices);seed_weight=1.0;clamped=0
    for index,(bar,t) in enumerate(zip(bars,turnover)):
        # Seed all mass from the first observed day; retain its unknown-survival share.
        rate=1.0 if index==0 else min(1.0,t/100)
        if t>100:clamped+=1
        if index:seed_weight*=1-rate
        midpoint=(bar.high+bar.low)/2
        spread=max(bar.high-bar.low,(high-low)/max(1,bins-1),1e-12)
        density=[max(0,1-abs(p-midpoint)/(spread/2)) if bar.low<=p<=bar.high else 0 for p in prices]
        if not sum(density):density[min(range(len(prices)),key=lambda i:abs(prices[i]-midpoint))]=1
        total=sum(density)
        weights=[w*(1-rate)+rate*x/total for w,x in zip(weights,density)]
    total=sum(weights);weights=[w/total for w in weights]
    def quantile(q):
        running=0
        for p,w in zip(prices,weights):
            running+=w
            if running>=q:return p
        return prices[-1]
    regions={}
    for coverage in (.7,.9):
        a,b=quantile((1-coverage)/2),quantile((1+coverage)/2)
        regions[str(int(coverage*100))]={'low':a,'high':b,'concentration':(b-a)/(b+a)}
    return {'status':'estimated','model':'triangular_daily_range_turnover_decay_v1',
        'symbol':bars[-1].symbol,'provider':bars[-1].provider,'as_of':bars[-1].timestamp,
        'currency':'CNY','price_basis':bars[-1].price_basis,'close':bars[-1].close,
        'window_start':bars[0].timestamp,'matched_days':len(bars),'parameters':{'bins':bins,'window':window,'minimum':minimum},
        'mean_cost':sum(p*w for p,w in zip(prices,weights)),'median_cost':quantile(.5),
        'profit_fraction':sum(w for p,w in zip(prices,weights) if p<=bars[-1].close),
        'cost_regions':regions,'dominant_peak_price':prices[max(range(len(weights)),key=lambda i:weights[i])],
        'unknown_initial_weight_fraction':seed_weight,'turnover_over_100pct_capped_days':clamped,
        'distribution':[{'price':p,'weight':w} for p,w in zip(prices,weights)],
        'interpretation':'Estimated cost structure from daily range/turnover; not real accounts, institutional costs, or an exact vendor CYQ replica'}

def render_chip_chart(result,path):
    rows=result['distribution'];maxw=max(r['weight'] for r in rows);a=rows[0]['price'];b=rows[-1]['price']
    parts=[]
    for r in rows:
        y=570-(r['price']-a)/(b-a if b>a else 1)*500
        parts.append(f'<rect x="130" y="{y:.2f}" width="{r["weight"]/maxw*620:.2f}" height="2.5" fill="#347aa0"><title>{r["price"]:.4f}: {r["weight"]:.4%}</title></rect>')
    summary=result['cost_regions'];title=html.escape(result['symbol']+' 估算筹码分布')
    for value,label,color in ((result['close'],'收盘','#c74442'),(result['mean_cost'],'平均成本','#df9a2e')):
        y=570-(value-a)/(b-a if b>a else 1)*500
        parts.append(f'<line x1="120" x2="780" y1="{y:.2f}" y2="{y:.2f}" stroke="{color}"/><text x="10" y="{y:.2f}">{label} {value:.2f}</text>')
    text=f'{result["as_of"]} · {result["provider"]} · {result["price_basis"]} · {result["matched_days"]}交易日；初始未知存量残留 {result["unknown_initial_weight_fraction"]:.1%}'
    details='；'.join(f'{key}%成本区 {v["low"]:.2f}—{v["high"]:.2f}' for key,v in summary.items())
    Path(path).write_text(f'<!doctype html><meta charset="utf-8"><title>{title}</title><style>body{{font:16px system-ui;margin:24px;background:#f2f5f8}}main{{max-width:950px;background:white;padding:24px;margin:auto}}svg{{width:100%}}</style><main><h1>{title}</h1><p>{html.escape(text)}</p><p>{details}；估算获利比例 {result["profit_fraction"]:.1%}</p><svg viewBox="0 0 820 620">'+''.join(parts)+'</svg><p>日价格区间采用三角分布，以换手率衰减旧筹码。成本位置用于辅助量价研究。</p></main>',encoding='utf-8')

def create_chip_research(store,symbol,directory,*,collect=True,end=None):
    from .providers.eastmoney_history import EastmoneyHistoryProvider
    from .providers.baostock_provider import BaoStockProvider
    from .responses import ResponseVault
    symbol=normalize_cn_symbol(symbol,stock_only=True);end=end or expected_closed_session()
    if end is None:raise ValueError('Current completed exchange session required')
    start=(datetime.fromisoformat(end)-timedelta(days=550)).date().isoformat();attempts=[];bars=[];turns=[]
    if collect:
        source=EastmoneyHistoryProvider();source.client.archive=ResponseVault(store.path.parent/'raw-responses')
        try:
            bars,turns=source.fetch_inputs(symbol,start=start,end=end)
            attempts.append({'provider':source.name,'status':'ok','rows':len(bars)})
        except Exception as exc:
            attempts.append({'provider':source.name,'status':'failed','error':str(exc)})
            source=BaoStockProvider()
            with contextlib.redirect_stdout(io.StringIO()):
                bars=source.fetch_bars(symbol,start_date=start,end_date=end,adjustment='qfq')
                turns=source.fetch_daily_metrics(symbol,start_date=start,end_date=end)
            attempts.append({'provider':source.name,'status':'ok','rows':len(bars)})
        store.upsert_bars(bars);store.upsert_observations(turns)
    else:
        bars=store.get_bars(symbol,'1d',price_basis='qfq',limit=500,as_of=end+'T23:59:59+08:00')
        if len({b.provider for b in bars})>1:raise ValueError('Choose one stored chip source; do not merge')
        if bars:
            dataset='cn_daily_turnover' if bars[0].provider==EastmoneyHistoryProvider.name else 'cn_daily_valuation_liquidity'
            turns=store.get_observations(dataset,symbol,limit=500,as_of=end+'T23:59:59+08:00')
    values={}
    for row in turns:
        r=asdict(row) if hasattr(row,'to_dict') else row
        if bars and r['provider']==bars[0].provider:values[r['as_of'][:10]]=r['value']['turnover_pct']
    bars=[b for b in bars if start<=b.timestamp[:10]<=end]
    if not bars:raise ValueError('No price/turnover source for chips')
    result=estimate_chips(bars,[values.get(b.timestamp[:10]) for b in bars])
    result['current_completed_day_covered']=bars[-1].timestamp[:10]==end
    if not result['current_completed_day_covered']:result['status']='historical_estimate'
    target=Path(directory)
    if target.exists() and any(target.iterdir()):raise ValueError('Use a new chip research directory')
    target.mkdir(parents=True,exist_ok=True)
    inputs={'bars':[asdict(b) for b in bars],'turnover_pct':[values.get(b.timestamp[:10]) for b in bars],'collection_attempts':attempts}
    result['chart_file']='chips.html'
    for file,data in (('inputs.json',inputs),('chips.json',result)):
        (target/file).write_text(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    render_chip_chart(result,target/'chips.html')
    source=Path(__file__).read_bytes()
    (target/'calculator.json').write_text(json.dumps({'sha256':hashlib.sha256(source).hexdigest(),'source_base64':base64.b64encode(source).decode()}),encoding='utf-8')
    seal={f:hashlib.sha256((target/f).read_bytes()).hexdigest() for f in ('inputs.json','chips.json','chips.html','calculator.json')}
    (target/'seal.json').write_text(json.dumps(seal,indent=2),encoding='utf-8')
    return {k:v for k,v in result.items() if k!='distribution'}|{'directory':str(target),'collection_attempts':attempts}

def verify_chip_research(directory):
    target=Path(directory);seal=json.loads((target/'seal.json').read_text(encoding='utf-8'))
    failures=[name for name,digest in seal.items() if hashlib.sha256((target/name).read_bytes()).hexdigest()!=digest]
    source=json.loads((target/'calculator.json').read_text(encoding='utf-8'))
    if hashlib.sha256(base64.b64decode(source['source_base64'])).hexdigest()!=source['sha256']:failures.append('frozen_calculator')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest()!=source['sha256']:return {'status':'calculator_version_mismatch'}
    inputs=json.loads((target/'inputs.json').read_text(encoding='utf-8'));result=json.loads((target/'chips.json').read_text(encoding='utf-8'))
    replay=estimate_chips([Bar(**b) for b in inputs['bars']],inputs['turnover_pct'],**result['parameters'])
    for key,value in replay.items():
        if key!='status' and result.get(key)!=value:failures.append(key)
    return {'status':'failed' if failures else 'ok','failures':failures,'live_database_used':False}
