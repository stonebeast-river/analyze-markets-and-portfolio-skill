"""Bounded deep evidence collection after independent cross-sectional discovery."""
from datetime import datetime,timedelta

from .conventions import SHANGHAI
from .market_scan import scan_market
from .providers.baostock_provider import BaoStockProvider
from .sessions import expected_session


def collect_followups(pipeline,*,limit=5,year=None,quarter=None):
    if not 1<=limit<=30:raise ValueError('Use a bounded deep-research limit')
    scan=scan_market(pipeline.store,limit=limit)
    if scan.get('status')!='research_scan':raise ValueError('Independent current-session discovery is unavailable')
    selected=[row['identity'] for row in scan['anomaly_sample']]
    day=expected_session()
    if day is None:raise ValueError('Trading calendar needs current coverage')
    start=(datetime.fromisoformat(day)-timedelta(days=450)).date().isoformat()
    provider=BaoStockProvider();runs=[]
    for symbol in selected:
        result=pipeline._run(provider.name,'followup_daily_bars:'+symbol,lambda symbol=symbol:pipeline._store_bars(provider.fetch_bars(symbol,start_date=start,end_date=day,adjustment='none')))
        runs.append({'identity':symbol,'dataset':'daily_bars','status':result.status,'rows':result.row_count,'error':result.error})
        result=pipeline._run(provider.name,'followup_daily_metrics:'+symbol,lambda symbol=symbol:pipeline._store_observations(provider.fetch_daily_metrics(symbol,start_date=start,end_date=day)))
        runs.append({'identity':symbol,'dataset':'daily_metrics','status':result.status,'rows':result.row_count,'error':result.error})
        if year is not None and quarter is not None:
            result=pipeline._run(provider.name,'followup_financials:'+symbol,lambda symbol=symbol:pipeline._store_observations(provider.fetch_financials(symbol,year=year,quarter=quarter)))
            runs.append({'identity':symbol,'dataset':'financials','status':result.status,'rows':result.row_count,'error':result.error})
    return {'selection_source':'independent_quote_anomalies','holdings_used':False,'selected':selected,'scan_cutoff':scan['as_of'],
            'history_window':{'start':start,'end':day,'basis':'unadjusted'},'financial_period':{'year':year,'quarter':quarter},
            'runs':runs,'interpretation':'Evidence collection does not promote a candidate; verify units, events, countercase and opportunity-type core data'}
