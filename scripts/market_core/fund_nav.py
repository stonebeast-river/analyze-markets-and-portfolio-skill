"""NAV line curves and frozen charts, without inventing off-exchange OHLC or volume."""
import json,math,html,hashlib
from datetime import datetime,timezone
from pathlib import Path
from .indicators import ema,macd
from .stock_technicals import bollinger
from .fund_products import verified_nav_currency


def nav_curves(observations):
    if not observations:raise ValueError('Fund NAV history required')
    keys={(r['provider'],r['identity'],r['currency'],r['price_basis']) for r in observations}
    if len(keys)!=1 or any(r['dataset']!='fund_unit_nav' for r in observations):raise ValueError('Select one exact NAV source/share/currency/basis')
    if observations[0]['currency'] in ('','unknown') or observations[0]['price_basis']!='unit_nav_price_return':
        raise ValueError('Known currency and unit-NAV basis required')
    rows=sorted(observations,key=lambda r:r['as_of']);dates=[r['as_of'] for r in rows]
    if len(set(dates))!=len(dates):raise ValueError('NAV dates must be unique')
    values=[r['value'] for r in rows]
    if any(type(v) not in (int,float) or not math.isfinite(v) or v<=0 for v in values):raise ValueError('Positive finite unit NAV required')
    b=bollinger(values);e20=ema(values,20);e60=ema(values,60);dif,dea,hist=macd(values);peak=values[0];curves=[]
    for i,value in enumerate(values):
        peak=max(peak,value)
        curves.append({'date':dates[i],'unit_nav':value,'ema20':e20[i] if i>=19 else None,'ema60':e60[i] if i>=59 else None,
            'boll_middle':b['middle'][i],'boll_upper':b['upper'][i],'boll_lower':b['lower'][i],
            'macd_dif':dif[i] if i>=33 else None,'macd_dea':dea[i] if i>=33 else None,
            'macd_histogram':hist[i] if i>=33 else None,'unit_NAV_drawdown_from_loaded_history_peak':value/peak-1})
    return curves


def render_nav_chart(curves,path,*,title,provider,currency,display=260):
    shown=curves[-display:]
    if not shown:raise ValueError('NAV chart rows required')
    left=85;right=1060;step=(right-left)/max(1,len(shown)-1);chunks=[]
    def label(x,y,value,color='#526579',size=12):chunks.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}">{html.escape(str(value))}</text>')
    def line(x1,y1,x2,y2,color='#dce5ed',width=1):chunks.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{width}"/>')
    label(20,30,title,'#172b3a',21);label(20,55,f'{provider} · {currency}/份 · {shown[0]["date"]} — {shown[-1]["date"]}')
    values=[r[k] for r in shown for k in ('unit_nav','boll_lower','boll_upper') if r[k] is not None]
    low=min(values);high=max(values);pad=max((high-low)*.08,high*.01);low-=pad;high+=pad
    py=lambda v:365-(v-low)/(high-low)*275
    for i in range(6):
        value=low+(high-low)*i/5;y=py(value);line(left,y,right,y);label(12,round(y+4,2),f'{value:.4f}')
    fields=(('unit_nav','#346ac0'),('boll_lower','#678aac'),('boll_upper','#678aac'),('boll_middle','#df9a2e'),('ema60','#267b68'))
    for field,color in fields:
        points=[f'{left+i*step:.2f},{py(r[field]):.2f}' for i,r in enumerate(shown) if r[field] is not None]
        if len(points)>1:chunks.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="{2 if field=="unit_nav" else 1.3}"/>')
    label(left,394,'单位净值（蓝） · BOLL20总体标准差/2σ · 中轨（橙） · EMA60（绿）')
    mmax=max([abs(r[k]) for r in shown for k in ('macd_dif','macd_dea','macd_histogram') if r[k] is not None]+[1e-8]);my=lambda v:475-v/mmax*55
    line(left,475,right,475,'#a8bccb');label(15,425,'MACD')
    for i,row in enumerate(shown):
        value=row['macd_histogram']
        if value is not None:line(left+i*step,475,left+i*step,my(value),'#c74442' if value>=0 else '#18896a',max(1,step*.5))
    for field,color in (('macd_dif','#df9a2e'),('macd_dea','#346ac0')):
        points=[f'{left+i*step:.2f},{my(r[field]):.2f}' for i,r in enumerate(shown) if r[field] is not None]
        if len(points)>1:chunks.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.6"/>')
    label(left,554,'MACD(12,26,9) · DIF（橙） · DEA（蓝） · 柱 = 2×(DIF−DEA)')
    label(15,594,'净值回撤');floor=min([r['unit_NAV_drawdown_from_loaded_history_peak'] for r in shown]+[-.01]);dy=lambda v:590+v/floor*95
    points=[f'{left+i*step:.2f},{dy(r["unit_NAV_drawdown_from_loaded_history_peak"]):.2f}' for i,r in enumerate(shown)]
    chunks.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="#9258b2" stroke-width="1.7"/>')
    label(15,688,f'{floor:.1%}');label(left,716,'相对于所载全部净值历史高点；单位净值口径，不等于分红再投资收益。')
    for i in sorted({0,len(shown)//3,2*len(shown)//3,len(shown)-1}):label(round(left+i*step-22,2),747,shown[i]['date'][:10],size=10)
    svg='<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1120 775" role="img" aria-label="'+html.escape(title,quote=True)+'">'+''.join(chunks)+'</svg>'
    target=Path(path);target.write_text('<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{margin:24px;background:#f2f5f8;font:15px system-ui}main{max-width:1200px;margin:auto;background:white;padding:16px}svg{width:100%;height:auto}</style><main>'+svg+'</main>',encoding='utf-8')
    return str(target)


def create_fund_nav_chart(store,code,directory,*,provider=None,as_of=None):
    as_of=as_of or datetime.now(timezone.utc).isoformat()
    contract=verified_nav_currency(store,code,as_of=as_of)
    if not contract['verified']:raise ValueError('Current exact-share currency contract required')
    rows=[r for r in store.get_observations('fund_unit_nav',code,limit=20000,as_of=as_of,include_raw=True)
          if r['currency']==contract['currency'] and (provider is None or r['provider']==provider)]
    if len(rows)<60:raise ValueError('At least 60 NAV observations required for this complete chart')
    curves=nav_curves(rows);root=Path(directory).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('Use a new fund chart directory')
    root.mkdir(parents=True,exist_ok=True)
    rows.sort(key=lambda r:r['as_of']);frozen=json.dumps(rows,ensure_ascii=False,sort_keys=True,allow_nan=False).encode('utf-8')
    (root/'nav-inputs.json').write_bytes(frozen)
    (root/'nav-curves.json').write_text(json.dumps(curves,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf-8')
    chart=render_nav_chart(curves,root/'chart.html',title=rows[-1].get('raw',{}).get('fund_name',code)+' '+code,provider=rows[0]['provider'],currency=contract['currency'])
    metadata={'fund_code':code,'currency_contract':contract,'provider':rows[0]['provider'],'currency':contract['currency'],
        'basis':'unit_NAV_not_reinvested_total_return','first_valuation_date':curves[0]['date'],'last_valuation_date':curves[-1]['date'],
        'NAV_rows':len(rows),'requested_history_limit_per_source':20000,'input_sha256':hashlib.sha256(frozen).hexdigest(),'calculator_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'parameters':{'BOLL':[20,2,'population_std'],'MACD':[12,26,9],'windows_are_NAV_observations':True},
        'returns':{str(n):curves[-1]['unit_nav']/curves[-1-n]['unit_nav']-1 for n in (5,20,60) if len(curves)>n},
        'personal_portfolio_used':False,'final_investment_decision_complete':False,'chart_path':chart}
    (root/'chart-metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'artifact-seal.json').write_text(json.dumps({f:hashlib.sha256((root/f).read_bytes()).hexdigest() for f in ('nav-inputs.json','nav-curves.json','chart.html','chart-metadata.json')},indent=2),encoding='utf-8')
    return metadata
