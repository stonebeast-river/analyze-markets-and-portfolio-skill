"""Reproducible stock curves and trend context, separate from return probabilities."""
import math
from dataclasses import asdict
from .indicators import macd,ema,rsi,atr,close_volume_ratio,kdj

def bollinger(closes,period=20,deviations=2.0):
    if type(period)!=int or period<2 or not math.isfinite(deviations) or deviations<=0:
        raise ValueError('BOLL needs period >= 2 and a positive deviation multiplier')
    middle=[];upper=[];lower=[];width=[]
    for i in range(len(closes)):
        if i+1<period:values=(None,)*4
        else:
            window=closes[i+1-period:i+1];mean=sum(window)/period
            sigma=math.sqrt(sum((value-mean)**2 for value in window)/period)
            values=(mean,mean+deviations*sigma,mean-deviations*sigma,2*deviations*sigma/mean if mean else None)
        for target,value in zip((middle,upper,lower,width),values):target.append(value)
    return {'middle':middle,'upper':upper,'lower':lower,'bandwidth':width,
            'parameters':{'period':period,'deviations':deviations,'standard_deviation':'population'}}

def technical_series(bars):
    if not bars:raise ValueError('Daily price history is required')
    identities={(b.symbol,b.provider,b.interval,b.price_basis,b.currency,b.volume_unit) for b in bars}
    if len(identities)!=1 or bars[0].interval!='1d':raise ValueError('Choose one daily source, symbol, basis, currency and volume unit')
    if bars[0].currency in {'','unknown'} or bars[0].price_basis in {'','unknown','legacy_unknown'}:
        raise ValueError('Verified currency and price basis are required')
    dates=[b.timestamp for b in bars]
    if dates!=sorted(set(dates)):raise ValueError('Daily bars must have unique increasing timestamps')
    if any(not all(math.isfinite(x) and x>0 for x in (b.open,b.high,b.low,b.close))
           or not b.low<=min(b.open,b.close)<=max(b.open,b.close)<=b.high for b in bars):
        raise ValueError('Invalid OHLC history')
    if any(value is not None and (not math.isfinite(value) or value<0) for b in bars for value in (b.volume,b.amount)):
        raise ValueError('Invalid volume or amount history')
    closes=[b.close for b in bars];dif,dea,hist=macd(closes);boll=bollinger(closes)
    ma20=ema(closes,20);ma60=ema(closes,60);rsis=rsi(closes);atrs=atr(bars)
    ks,ds,js=kdj(bars)
    ratios=close_volume_ratio([b.volume for b in bars]);rows=[]
    for i,b in enumerate(bars):
        rows.append({'date':b.timestamp,'open':b.open,'high':b.high,'low':b.low,'close':b.close,
            'volume':b.volume,'amount':b.amount,'ema20':ma20[i] if i>=19 else None,'ema60':ma60[i] if i>=59 else None,
            'macd_dif':dif[i] if i>=33 else None,'macd_dea':dea[i] if i>=33 else None,
            'macd_histogram':hist[i] if i>=33 else None,'rsi14':rsis[i],'atr14':atrs[i],
            'kdj_k':ks[i],'kdj_d':ds[i],'kdj_j':js[i],
            'volume_ratio5':ratios[i],**{'boll_'+key:values[i] for key,values in boll.items() if key!='parameters'}})
    return rows

def feature_vector(rows,index):
    if index<119:return None
    row=rows[index];price=row['close'];atr_value=row['atr14']
    if not atr_value or row['volume_ratio5'] is None:return None
    return [price/rows[index-5]['close']-1,price/rows[index-20]['close']-1,
            price/rows[index-60]['close']-1,(price-row['ema20'])/price,
            row['macd_histogram']/price,row['boll_bandwidth'],min(row['volume_ratio5'],5.0)/5.0]

def technical_context(rows):
    if len(rows)<120:return {'state':'insufficient_history','required_daily_bars':120,'received_daily_bars':len(rows)}
    latest=rows[-1];prior=rows[-21:-1];price=latest['close']
    support=min(r['low'] for r in prior);resistance=max(r['high'] for r in prior)
    rising=latest['ema20']>latest['ema60'] and latest['ema20']>rows[-6]['ema20']
    falling=latest['ema20']<latest['ema60'] and latest['ema20']<rows[-6]['ema20']
    direction='upward_trend' if rising else 'downward_trend' if falling else 'mixed_or_range'
    widths=sorted(r['boll_bandwidth'] for r in rows[-120:-1] if r['boll_bandwidth'] is not None)
    width_rank=sum(w<=latest['boll_bandwidth'] for w in widths)/len(widths)
    phase=('breakout' if price>resistance else 'breakdown' if price<support else
           'compressed_range' if width_rank<=0.2 else 'range_or_trend')
    return {'state':'measured','as_of':latest['date'],'trend':direction,'price_phase':phase,
        'close':price,'support_previous20':support,'resistance_previous20':resistance,
        'boll_bandwidth_percentile_previous119':width_rank,'macd_histogram':latest['macd_histogram'],
        'macd_histogram_change':latest['macd_histogram']-rows[-2]['macd_histogram'],
        'volume_ratio_previous5':latest['volume_ratio5'],'atr14':latest['atr14'],
        'rsi14':latest['rsi14'],'kdj':{'k':latest['kdj_k'],'d':latest['kdj_d'],'j':latest['kdj_j'],
            'parameters':{'period':9,'k_smoothing':3,'d_smoothing':3,'seed':50,'flat_rsv':50}},
        'interpretation':'Observed trend/range and historical levels; not a calibrated forecast or identified institution'}
