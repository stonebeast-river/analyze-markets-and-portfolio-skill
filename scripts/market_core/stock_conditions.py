"""Executable chart-review predicates; conditions do not authorize a trade."""
from datetime import datetime,timedelta
from .sessions import exchange_calendar,expected_session
from .conventions import SHANGHAI,parse_time

def expected_closed_session(as_of=None):
    now=parse_time(as_of).astimezone(SHANGHAI) if as_of else datetime.now(SHANGHAI)
    if now.hour<15:now=now.replace(hour=8,minute=59,second=0,microsecond=0)
    return expected_session(now.isoformat())

def next_daily_review(day):
    calendar=exchange_calendar();value=datetime.fromisoformat(day[:10]).date()+timedelta(days=1)
    while value.weekday()>=5 or value.isoformat() in calendar['closed_dates']:value+=timedelta(days=1)
    return value.isoformat()+'T15:10:00+08:00' if value.isoformat()<=calendar['coverage_end'] else 'calendar_extension_required'

def chart_condition_plan(context,source):
    if context.get('state')!='measured' or not context.get('atr14'):
        return {'status':'insufficient_chart_context','conditions':[],'trade_authorized':False}
    support=context['support_previous20'];resistance=context['resistance_previous20'];price=context['close'];atr=context['atr14']
    condition_source={key:source[key] for key in ('symbol','provider','interval','price_basis','currency')}
    baseline=context['as_of'];review=next_daily_review(baseline)
    def predicate(metric,operator,threshold,window):
        return {'metric':metric,'operator':operator,'threshold':threshold,'source':condition_source,
                'window':window,'baseline':baseline,'next_review':review}
    conditions=[{'name':'突破图形复核','predicates':[predicate('close','gt',resistance,'next_completed_daily_bar'),
        predicate('volume_ratio5','gte',1.2,'current_volume_over_previous5_completed_bars')],
        'meaning':'Chart confirmation for due-diligence review only'},
        {'name':'价格失效复核','predicates':[predicate('close','lt',support,'next_completed_daily_bar')],
         'meaning':'Review the thesis if the prior20 low is lost'}]
    if price>=support and support>atr:
        conditions.insert(1,{'name':'回踩图形复核','predicates':[predicate('close','gte',max(support,price-atr),'next_completed_daily_bar'),
            predicate('close','lte',price,'next_completed_daily_bar'),predicate('close_change','gt',0,'previous_completed_daily_bar'),
            predicate('macd_histogram_change','gte',0,'previous_completed_daily_bar')],
            'meaning':'Price holds the defined zone and close/MACD improve; investment evidence remains separate'})
    return {'status':'operational_chart_predicates','conditions':conditions,'trade_authorized':False,
        'parameters':{'volume_confirmation_ratio':1.2,'support_resistance_lookback':20,'pullback_atr_multiplier':1},
        'strategy_validation':'declared hypotheses; profitability/execution not certified',
        'fundamental_and_catalyst_confirmation':'not_operational_until_specific_source_event_is_defined'}

def evaluate_chart_conditions(plan,rows,source,*,as_of=None):
    if not rows:return {'status':'insufficient_data','results':[],'trade_authorized':False}
    latest=rows[-1];results=[]
    closed=expected_closed_session(as_of)
    for condition in plan.get('conditions',[]):
        checks=[]
        for rule in condition['predicates']:
            if rule['source']!={key:source.get(key) for key in rule['source']}:
                state='unknown';reason='source_identity_or_basis_mismatch';value=None
            elif closed is None or latest['date'][:10]>closed:
                state='unknown';reason='future_or_uncompleted_daily_bar';value=None
            elif latest['date']<=rule['baseline']:
                state='pending';reason='no_post_baseline_completed_bar';value=None
            else:
                metric=rule['metric'];value=latest.get(metric)
                if metric=='close_change':value=latest['close']-rows[-2]['close'] if len(rows)>1 else None
                if metric=='macd_histogram_change':
                    value=(latest['macd_histogram']-rows[-2]['macd_histogram']
                           if len(rows)>1 and latest.get('macd_histogram') is not None and rows[-2].get('macd_histogram') is not None else None)
                if value is None:state='unknown';reason='required_metric_missing'
                else:
                    operator=rule['operator'];threshold=rule['threshold']
                    passed={'gt':value>threshold,'gte':value>=threshold,'lt':value<threshold,'lte':value<=threshold}[operator]
                    state='passed' if passed else 'not_passed';reason='measured_comparison'
            checks.append({'rule':rule,'value':value,'state':state,'reason':reason})
        states=[row['state'] for row in checks]
        combined='not_passed' if 'not_passed' in states else 'unknown' if 'unknown' in states else 'pending' if 'pending' in states else 'passed'
        results.append({'name':condition['name'],'state':combined,'checks':checks})
    return {'status':'evaluated','results':results,'trade_authorized':False}
