"""Standalone SVG stock chart with candles, BOLL/EMA, MACD and volume, no network scripts."""
import html
from pathlib import Path

def render_stock_chart(rows,path,*,title,provider,basis,currency,volume_unit,display=180):
    shown=rows[-display:]
    if not shown:raise ValueError('No chart rows')
    width=1120;left=80;right=1060;span=right-left;count=len(shown);step=span/count
    chunks=[]
    def text(x,y,value,size=12,color='#526579'):
        chunks.append(f'<text x="{x:.2f}" y="{y:.2f}" font-size="{size}" fill="{color}">{html.escape(str(value))}</text>')
    def line(x1,y1,x2,y2,color,width=1):chunks.append(f'<line x1="{x1:.2f}" y1="{y1:.2f}" x2="{x2:.2f}" y2="{y2:.2f}" stroke="{color}" stroke-width="{width}"/>')
    text(20,30,title,21,'#172b3a');text(20,55,f'{provider} · {basis} · {currency} · {shown[0]["date"]} — {shown[-1]["date"]}')
    price_values=[r[key] for r in shown for key in ('low','high','boll_upper','boll_lower') if r.get(key) is not None]
    pmin=min(price_values);pmax=max(price_values);padding=max((pmax-pmin)*.08,pmax*.01);pmin-=padding;pmax+=padding
    def py(value):return 370-(value-pmin)/(pmax-pmin)*275
    for i in range(6):
        value=pmin+(pmax-pmin)*i/5;y=py(value);line(left,y,right,y,'#dce5ed');text(10,y+4,f'{value:.2f}')
    colors={'boll_upper':'#678aac','boll_middle':'#df9a2e','boll_lower':'#678aac','ema20':'#9258b2','ema60':'#267b68'}
    for field,color in colors.items():
        points=[f'{left+(i+.5)*step:.2f},{py(r[field]):.2f}' for i,r in enumerate(shown) if r.get(field) is not None]
        if len(points)>1:chunks.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.5"/>')
    for i,row in enumerate(shown):
        x=left+(i+.5)*step;color='#c74442' if row['close']>=row['open'] else '#18896a'
        line(x,py(row['high']),x,py(row['low']),color)
        chunks.append(f'<rect x="{x-max(1,step*.29):.2f}" y="{min(py(row["open"]),py(row["close"])):.2f}" width="{max(2,step*.58):.2f}" height="{max(1,abs(py(row["open"])-py(row["close"]))):.2f}" fill="{color}"><title>{html.escape(row["date"])} O {row["open"]} H {row["high"]} L {row["low"]} C {row["close"]}</title></rect>')
    text(left,400,'BOLL上下轨(20, 2σ)',color='#678aac');text(left+220,400,'BOLL中轨',color='#df9a2e')
    text(left+370,400,'EMA20',color='#9258b2');text(left+480,400,'EMA60',color='#267b68')
    mmax=max([abs(r[k]) for r in shown for k in ('macd_dif','macd_dea','macd_histogram') if r.get(k) is not None]+[1e-8])
    def my(value):return 485-value/mmax*60
    line(left,485,right,485,'#ccd8e1');text(15,440,'MACD')
    for i,row in enumerate(shown):
        if row['macd_histogram'] is None:continue
        x=left+(i+.5)*step;v=row['macd_histogram'];line(x,485,x,my(v),'#c74442' if v>=0 else '#18896a',max(1,step*.55))
    for field,color in (('macd_dif','#df9a2e'),('macd_dea','#346ac0')):
        points=[f'{left+(i+.5)*step:.2f},{my(r[field]):.2f}' for i,r in enumerate(shown) if r.get(field) is not None]
        chunks.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.6"/>')
    text(left,568,'DIF(12−26) · DEA(9) · Histogram = 2 × (DIF−DEA)')
    volumes=[r['volume'] for r in shown if r['volume'] is not None];vmax=max(volumes+[1])
    text(15,606,'成交量');text(left,606,volume_unit)
    for i,row in enumerate(shown):
        if row['volume'] is None:continue
        x=left+i*step;height=max(0,row['volume']/vmax*100)
        chunks.append(f'<rect x="{x:.2f}" y="{720-height:.2f}" width="{max(1,step*.65):.2f}" height="{height:.2f}" fill="{"#c74442" if row["close"]>=row["open"] else "#18896a"}"/>')
    for i in sorted({0,count//4,count//2,3*count//4,count-1}):text(left+(i+.1)*step-20,744,shown[i]['date'][:10],10)
    for title_y, bottom, fields, label in (
        (785,875,('kdj_k','kdj_d','kdj_j'),'KDJ(9,3,3) · K/D初值50 · J不截断'),
        (915,1005,('rsi14',),'RSI14 · Wilder平滑')):
        values=[r[f] for r in shown for f in fields if r.get(f) is not None]
        low=min([0]+values);high=max([100]+values)
        def oy(v):return bottom-(v-low)/(high-low)*75
        text(left,title_y,label)
        for level in (20,80):line(left,oy(level),right,oy(level),'#dce5ed');text(35,oy(level)+4,level)
        for field,color in zip(fields,('#df9a2e','#346ac0','#9258b2')):
            points=[f'{left+(i+.5)*step:.2f},{oy(r[field]):.2f}' for i,r in enumerate(shown) if r.get(field) is not None]
            chunks.append(f'<polyline points="{" ".join(points)}" fill="none" stroke="{color}" stroke-width="1.5"/>')
            text(left+500+fields.index(field)*140,title_y,field,color=color)
    svg=f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} 1035" role="img" aria-label="{html.escape(title,quote=True)}">'+''.join(chunks)+'</svg>'
    target=Path(path);target.write_text('<!doctype html><meta charset="utf-8"><title>'+html.escape(title)+'</title><style>body{margin:24px;background:#f2f5f8;font:15px system-ui}main{max-width:1200px;margin:auto;background:white;padding:16px;border-radius:10px}svg{width:100%;height:auto}p{color:#526579}</style><main>'+svg+'<p>图表来自冻结日线输入。BOLL 上下轨使用总体标准差；成交量单位保留供应商口径。鼠标停留在蜡烛上可查看当日 OHLC。</p></main>',encoding='utf-8')
    return str(target)
