"""Causal, same-security analogue forecasts with nonoverlapping chronological evaluation."""
import math
from .stock_technicals import feature_vector

def percentile(values,fraction):
    values=sorted(values)
    return values[min(len(values)-1,int((len(values)-1)*fraction))] if values else None

def analogue_at(rows,index,*,horizon=20,neighbours=15,min_samples=15):
    if type(horizon)!=int or not 2<=horizon<=60:raise ValueError('Use a 2-60 trading-bar horizon')
    if type(neighbours)!=int or neighbours<5 or type(min_samples)!=int or min_samples<5:
        raise ValueError('Use at least five historical analogues and training samples')
    current=feature_vector(rows,index)
    if current is None:return {'status':'insufficient_feature_history'}
    # Fixed origin and spacing; adding future rows cannot change an old forecast.
    training=[]
    for t in range(119,index-horizon+1,horizon):
        vector=feature_vector(rows,t)
        if vector is not None:
            training.append((t,vector,rows[t+horizon]['close']/rows[t]['close']-1))
    if len(training)<min_samples:return {'status':'insufficient_matured_nonoverlapping_samples','training_samples':len(training)}
    dimensions=len(current);scales=[]
    for dim in range(dimensions):
        values=[x[1][dim] for x in training];mean=sum(values)/len(values)
        scales.append(max(math.sqrt(sum((x-mean)**2 for x in values)/len(values)),1e-8))
    ranked=sorted(training,key=lambda item:sum(((item[1][d]-current[d])/scales[d])**2 for d in range(dimensions)))
    selected=ranked[:min(neighbours,len(ranked))];outcomes=[x[2] for x in selected]
    return {'status':'estimated','forecast_as_of':rows[index]['date'],'horizon_trading_bars':horizon,
        'training_samples':len(training),'selected_samples':len(selected),
        'analogue_up_rate':sum(value>0 for value in outcomes)/len(outcomes),
        'smoothed_up_estimate':(sum(value>0 for value in outcomes)+1)/(len(outcomes)+2),
        'baseline_up_rate':sum(item[2]>0 for item in training)/len(training),
        'median_price_return':percentile(outcomes,0.5),'historical_return_p10':percentile(outcomes,0.1),
        'historical_return_p90':percentile(outcomes,0.9),
        'latest_training_outcome_date':max(rows[t+horizon]['date'] for t,_,_ in training),
        'analogues':[{'signal_date':rows[t]['date'],'outcome_date':rows[t+horizon]['date'],'price_return':outcome} for t,_,outcome in selected]}

def chronological_forecast(rows,*,horizon=20,neighbours=15,min_samples=15):
    latest=analogue_at(rows,len(rows)-1,horizon=horizon,neighbours=neighbours,min_samples=min_samples)
    evaluations=[]
    for t in range(119+horizon*min_samples,len(rows)-horizon,horizon):
        prediction=analogue_at(rows,t,horizon=horizon,neighbours=neighbours,min_samples=min_samples)
        if prediction['status']!='estimated':continue
        realised=rows[t+horizon]['close']/rows[t]['close']-1;label=int(realised>0)
        evaluations.append({'signal_date':rows[t]['date'],'outcome_date':rows[t+horizon]['date'],
            'analogue_up_rate':prediction['smoothed_up_estimate'],'baseline_up_rate':prediction['baseline_up_rate'],
            'median_predicted_price_return':prediction['median_price_return'],'actual_price_return':realised,
            'actual_up':label,'latest_training_outcome_date':prediction['latest_training_outcome_date']})
    n=len(evaluations)
    brier=sum((r['analogue_up_rate']-r['actual_up'])**2 for r in evaluations)/n if n else None
    baseline=sum((r['baseline_up_rate']-r['actual_up'])**2 for r in evaluations)/n if n else None
    bins=[];ece=0.0
    for lo,hi in ((0,1/3),(1/3,2/3),(2/3,1.0000001)):
        sample=[r for r in evaluations if lo<=r['analogue_up_rate']<hi]
        if sample:
            predicted=sum(r['analogue_up_rate'] for r in sample)/len(sample)
            observed=sum(r['actual_up'] for r in sample)/len(sample)
            ece+=len(sample)/max(1,n)*abs(predicted-observed)
            bins.append({'lower':lo,'upper':min(hi,1),'count':len(sample),'mean_predicted':predicted,'observed_up_rate':observed})
    latest_bin=next((bucket for bucket in bins if latest['status']=='estimated'
                     and bucket['lower']<=latest['smoothed_up_estimate']<=bucket['upper']),None)
    publishable=bool(n>=30 and brier<baseline and ece<=0.15 and latest_bin
                     and latest_bin['count']>=15 and abs(latest_bin['mean_predicted']-latest_bin['observed_up_rate'])<=0.15)
    if latest['status']=='estimated':
        median=latest['median_price_return'];latest['direction']='up' if median>0.01 else 'down' if median< -0.01 else 'range'
        latest['published_up_probability']=latest['smoothed_up_estimate'] if publishable else None
        latest['probability_publication_allowed']=publishable
    return {'method':'standardized_historical_nearest_analogues_v1','latest':latest,
        'evaluation':{'mode':'expanding_past_only_nonoverlapping_walk_forward','evaluations':n,'brier':brier,
            'past_frequency_baseline_brier':baseline,'calibration_error_3bins':ece if n else None,'bins':bins,
            'probability_publication_gate':{'minimum_evaluations':30,'brier_better_than_past_frequency':True,
                'maximum_calibration_error':0.15,'minimum_latest_bin_evaluations':15,'latest_bin_calibration_required':True},
            'probability_publication_allowed':publishable,'records':evaluations},
        'data_scope':'Current-vintage price returns; excludes dividend reinvestment and historical publication-vintage certification',
        'strategy_performance_verified':False,'position_sizing_verified':False,
        'interpretation':'Analogue frequencies and quantiles are measured historical comparisons; probability is withheld unless the chronological gate passes'}
