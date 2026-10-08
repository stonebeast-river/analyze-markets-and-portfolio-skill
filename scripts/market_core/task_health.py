"""Configured collection/data readiness, separate from unrelated historical failures."""
import json
import math
import os
from collections import Counter
from datetime import datetime,timedelta,timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .conventions import interval_name,parse_time
from .sessions import expected_session,quote_freshness
from .symbols import is_cn_index,normalize_cn_symbol,is_cn_exchange_fund


def cash_calendar(market):
    root=Path(__file__).resolve().parents[2]/'assets'
    registry=json.loads((root/'cash-market-calendars-2026.json').read_text(encoding='utf-8'))
    item=registry['markets'].get(market)
    if item is None:return None
    item=dict(item)
    if item.get('holiday_file'):
        item['closed_dates']=json.loads((root/item['holiday_file']).read_text(encoding='utf-8'))['closed_dates']
    return {**item,'coverage_start':registry['coverage_start'],'coverage_end':registry['coverage_end']}


def completed_cash_session(market,as_of):
    calendar=cash_calendar(market)
    if calendar is None:return None
    now=parse_time(as_of).astimezone(ZoneInfo(calendar['timezone']));day=now.date()
    if not calendar['coverage_start']<=day.isoformat()<=calendar['coverage_end']:return None
    hour,minute=map(int,calendar.get('early_closes',{}).get(day.isoformat(),calendar['close']).split(':'))
    if now<now.replace(hour=hour,minute=minute,second=0,microsecond=0):day-=timedelta(days=1)
    closed=set(calendar['closed_dates'])
    while day.weekday()>=5 or day.isoformat() in closed:day-=timedelta(days=1)
    return day.isoformat() if day.isoformat()>=calendar['coverage_start'] else None


def recent_cash_sessions(market,ending,count):
    calendar=cash_calendar(market)
    if not calendar or not ending:return None
    day=datetime.fromisoformat(ending).date();closed=set(calendar['closed_dates']);dates=[]
    while len(dates)<count:
        if day.isoformat()<calendar['coverage_start']:return None
        if day.weekday()<5 and day.isoformat() not in closed:dates.append(day.isoformat())
        day-=timedelta(days=1)
    return dates


def selected_sources(config):
    settings=config.get('providers',{})
    def licensed(name,public,private,public_modes):
        row=settings.get(name) or {};mode=row.get('source','auto')
        env=row.get('api_key_env') or {'twelve_data':'TWELVE_DATA_API_KEY','fred':'FRED_API_KEY'}[name]
        key=bool(os.environ.get(env))
        enabled=bool(row.get('enabled'))
        if key and mode not in public_modes:return private,enabled
        if mode in public_modes or mode=='auto':return public,enabled
        return private,False
    global_source,global_configured=licensed('twelve_data','yahoo_public_chart','twelve_data_registered_api',{'yahoo'})
    macro_source,macro_configured=licensed('fred','fred_public_csv','fred_official_api',{'csv'})
    return {'global':(global_source,global_configured),'macro':(macro_source,macro_configured)}


def requirements(config,profile_name):
    profile=config.get('profiles',{}).get(profile_name)
    if not isinstance(profile,dict) or profile_name not in {'allocation','tactical'}:raise ValueError('Unknown allocation/tactical profile')
    providers=config.get('providers',{});selected=selected_sources(config);rows=[]
    enabled=lambda name:bool((providers.get(name) or {}).get('enabled'))
    def add(kind,identity,source,configured,**extra):
        rows.append({'id':kind+':'+identity,'kind':kind,'identity':identity,'provider':source,'configured':configured,**extra})
    symbols=list(dict.fromkeys((profile.get('cn_benchmarks',[])+profile.get('cn_sector_indices',[])) if profile_name=='allocation' else profile.get('cn_symbols',[])))
    history_tencent=profile.get('history_source')=='tencent'
    for symbol in symbols:
        symbol=normalize_cn_symbol(symbol)
        add('quote',symbol,'tencent_web_quote',enabled('tencent'),run_dataset='cn_benchmark_quotes' if profile_name=='allocation' else 'cn_watchlist_quotes')
        add('daily_bars',symbol,'tencent_web_history' if history_tencent else 'baostock_free_history',
            enabled('tencent') if history_tencent else enabled('baostock'),interval='1d',market='CN_CASH',
            price_basis='unadjusted' if is_cn_index(symbol) or is_cn_exchange_fund(symbol) else 'qfq',minimum=int(profile.get('minimum_daily_observations',61)),run_dataset='cn_daily_bars:'+symbol,
            alternative_providers=['tencent_web_history'] if not history_tencent and enabled('tencent') and 'tencent' in profile.get('history_fallback_sources',['tencent']) else [])
        if not history_tencent and not is_cn_index(symbol) and not is_cn_exchange_fund(symbol):
            add('daily_metrics',symbol,'baostock_free_history',enabled('baostock'),dataset='cn_daily_valuation_liquidity',run_dataset='cn_daily_metrics:'+symbol)
    if profile_name=='allocation':
        for symbol in profile.get('global_symbols',[]):
            market=(profile.get('global_calendars') or {}).get(symbol)
            if market is None:
                market='HK_CASH' if symbol=='^HSI' or symbol.endswith('.HK') else 'JP_CASH' if symbol=='^N225' else 'STOXX_EUROPE' if symbol=='^STOXX50E' else None
            add('daily_bars',symbol,*selected['global'],interval='1d',market=market,
                price_basis='provider_split_adjusted_close' if selected['global'][0]=='yahoo_public_chart' else 'provider_price_return',minimum=int(profile.get('minimum_daily_observations',61)),run_dataset='global_daily_bars:'+symbol)
        for identity in profile.get('fred_series',[]):
            add('macro',identity,*selected['macro'],dataset='macro_series',run_dataset='macro_series:'+identity,
                freshness_mode='source_collection_recency',max_collection_age_hours=float(profile.get('macro_max_collection_age_hours',24)))
        for identity in profile.get('fund_codes',[]):
            add('fund_nav',identity,'eastmoney_fund_page_fallback',enabled('fund_eastmoney'),dataset='fund_unit_nav',minimum=61,run_dataset='fund_unit_nav:'+identity)
    else:
        tencent=profile.get('intraday_source')=='tencent';source='tencent_public_intraday' if tencent else 'mootdx_tdx_protocol'
        for symbol in symbols:
            interval=interval_name(profile.get('intraday_interval','5m'))
            add('intraday',symbol,source,enabled('tencent') if tencent else enabled('mootdx'),interval=interval,
                price_basis='unadjusted',minimum=int(profile.get('intraday_count',240)),run_dataset='bars_'+interval+':'+symbol)
        for symbol in profile.get('flow_symbols',[]):
            identity=normalize_cn_symbol(symbol,stock_only=True)
            add('flow',identity,'eastmoney_provider_derived',enabled('eastmoney'),dataset='stock_order_size_flow_1m',run_dataset='stock_order_size_flow_1m:'+identity)
        for symbol in profile.get('tick_symbols',[]):
            identity=normalize_cn_symbol(symbol,stock_only=True)
            add('aggregate' if tencent else 'ticks',identity,source,enabled('tencent') if tencent else enabled('mootdx'),
                dataset='transaction_aggregate_summary' if tencent else 'transaction_summary',
                requested_session=profile.get('tick_date'),run_dataset=('transaction_aggregates:' if tencent else 'tick_transactions:')+identity)
    for board_type in profile.get('board_types',[]):
        for period in profile.get('board_periods',[]) or ['today']:
            dataset='board_'+board_type+'_'+period
            add('board',dataset,'eastmoney_provider_derived',enabled('eastmoney'),dataset=dataset,run_dataset=dataset)
    return rows


def numeric(value):return type(value) in (int,float) and math.isfinite(value)


def evaluate_requirement(store,requirement,cutoff):
    item=dict(requirement);kind=item['kind'];provider=item['provider'];identity=item['identity'];issues=[]
    if kind=='quote':
        rows=[row for row in store.get_quotes([identity],as_of=cutoff) if row['provider']==provider]
        if rows:
            row=rows[-1]
            if any(not numeric(row.get(field)) or row[field]<=0 for field in ('last','previous_close')):issues.append('valid_price_pair')
            if row.get('currency') in {'','unknown',None}:issues.append('verified_currency')
            if row['freshness']['status']!='current_session':issues.append('quote_freshness:'+row['freshness']['status'])
            item['observation_time']=row['as_of'];item['freshness']=row['freshness']
    elif kind in {'daily_bars','intraday'}:
        rows=store.get_bars(identity,item['interval'],provider=provider,price_basis=item['price_basis'],limit=max(item['minimum'],500),as_of=cutoff)
        if rows:
            latest=rows[-1];item['observation_time']=latest.timestamp
            if len(rows)<item['minimum']:issues.append('minimum_observations')
            if latest.currency in {'','unknown',None}:issues.append('verified_currency')
            if kind=='daily_bars':
                if not item.get('market'):
                    meta=latest.raw.get('metadata') or latest.raw.get('meta') or {}
                    zone=latest.raw.get('exchange_timezone') or meta.get('exchange_timezone')
                    cash_type=latest.raw.get('instrument_type') or meta.get('type')
                    if zone=='America/New_York' and cash_type in {'ETF','EQUITY','INDEX','Common Stock','ETFs'}:
                        item['market']='US_CASH';item['calendar_mapping']='supplier_cash_venue_metadata'
                expected=completed_cash_session(item.get('market'),cutoff)
                item['expected_completed_session']=expected
                if expected is None:issues.append('verified_instrument_calendar')
                else:
                    if latest.timestamp[:10]!=expected:issues.append('completed_daily_session_alignment')
                    required_dates=recent_cash_sessions(item['market'],expected,item['minimum'])
                    if required_dates is None:issues.append('history_calendar_coverage')
                    else:
                        missing=sorted(set(required_dates)-{row.timestamp[:10] for row in rows})
                        if missing:issues.append('missing_scheduled_daily_sessions');item['missing_sessions']=missing
            else:
                freshness=quote_freshness({'as_of':latest.timestamp,'quality':latest.quality},cutoff)
                item['freshness']=freshness
                if freshness['status']!='current_session':issues.append('intraday_freshness:'+freshness['status'])
            if any(row.quality in {'stale','unavailable','incomplete','legacy_basis_unverified'} for row in rows):issues.append('source_quality')
            if any(not all(numeric(value) and value>0 for value in (row.open,row.high,row.low,row.close))
                   or row.high<max(row.open,row.close) or row.low>min(row.open,row.close) for row in rows):issues.append('valid_OHLC')
    else:
        rows=[row for row in store.get_observations(item['dataset'],None if kind=='board' else identity,
              limit=500,as_of=cutoff,include_raw=True) if row['provider']==provider]
        if rows:
            row=rows[-1];item['observation_time']=row['as_of'];item['collected_at']=row['collected_at']
            if kind=='macro':
                if not numeric(row['value']) or row['unit'] in {'','unknown',None}:issues.append('numeric_value_and_verified_units')
                age=(parse_time(cutoff)-parse_time(row['collected_at'])).total_seconds()/3600
                if age<0 or age>item['max_collection_age_hours']:issues.append('source_collection_recency')
                item['source_collection_age_hours']=age
                item['publication_window_verified']=False
                item['freshness_meaning']='recent_source_snapshot; observation date and original publication/vintage are separate'
                if identity in {'DEXCHUS','DEXUSEU'}:item['contract']='dated_official_noon_fixing_not_intraday_FX_OHLC'
            elif kind=='fund_nav':
                if len(rows)<item['minimum']:issues.append('minimum_NAV_observations')
                if row['currency'] in {'','unknown',None}:issues.append('verified_NAV_currency')
                from .fund_clocks import nav_currentness
                products=store.get_observations('fund_product',identity,limit=1,as_of=cutoff)
                product=next((candidate['value'] for candidate in reversed(products) if candidate['value'].get('nav_calendar_contract')), {})
                currentness=nav_currentness(product,row['as_of'][:10],cutoff);item['NAV_currentness']=currentness
                if currentness['status']!='current_publication_window':issues.append('fund_NAV_currentness:'+currentness['status'])
            elif kind=='board':
                issues.append('source_observation_time_is_retrieval_time_not_verified_exchange_session')
            elif kind in {'aggregate','ticks'}:
                expected=expected_session(cutoff);requested=item.get('requested_session') or expected
                item['expected_session']=expected
                if requested!=expected:issues.append('historical_aggregate_not_current_tactical_session')
                if row['as_of'][:10]!=requested:issues.append('transaction_session_alignment')
                if kind=='aggregate' and row['value'].get('status')!='complete_supplier_window':issues.append('complete_supplier_window')
            elif kind=='flow':
                if quote_freshness({'as_of':row['as_of'],'quality':row['quality']},cutoff)['status']!='current_session':issues.append('flow_session_or_clock_alignment')
                if not numeric(row['value'].get('main_net')):issues.append('provider_main_net_measure')
            elif kind=='daily_metrics':
                if row['as_of'][:10]!=completed_cash_session('CN_CASH',cutoff):issues.append('daily_metrics_session_alignment')
                if row['unit']!='percent_and_multiples' or not numeric(row['value'].get('turnover_pct')):issues.append('defined_turnover_units')
                if not any(numeric(row['value'].get(field)) and row['value'][field]!=0 for field in ('pe_ttm','pb_mrq','ps_ttm','pcf_ncf_ttm')):
                    issues.append('usable_stock_valuation_multiple')
    item['row_count']=len(rows)
    if not rows:issues.append('missing_selected_source_data')
    if not item['configured']:issues.append('collector_not_configured')
    item['issues']=issues;item['state']='ready' if not issues else 'missing' if not rows else 'incomplete'
    return item


def profile_health(store,config,profile_name,*,as_of=None):
    cutoff=as_of or datetime.now(timezone.utc).isoformat()
    requested=requirements(config,profile_name)
    items=[]
    for requirement in requested:
        item=evaluate_requirement(store,requirement,cutoff)
        for alternate in requirement.get('alternative_providers',[]):
            if item['state']=='ready':break
            alternative=evaluate_requirement(store,{**requirement,'provider':alternate,'configured':True},cutoff)
            if alternative['state']=='ready':
                alternative['primary_provider']=requirement['provider'];alternative['primary_issues']=item['issues']
                alternative['alternative_used']=True;item=alternative;break
        items.append(item)
    scopes={(row['provider'],row['run_dataset']) for row in requested}
    scopes.update((alternate,row['run_dataset']) for row in requested for alternate in row.get('alternative_providers',[]))
    with store.connect() as db:
        runs=[dict(row) for row in db.execute('SELECT * FROM provider_runs WHERE at_or_before(finished_at,?) ORDER BY id DESC',(cutoff,))]
    latest={}
    for row in runs:
        key=(row['provider'],row['dataset'])
        if key in scopes:latest.setdefault(key,row)
    problems=[row for row in latest.values() if row['status']!='ok']
    recovered={(row.get('primary_provider'),row['run_dataset']) for row in items if row.get('alternative_used')}
    unresolved=[row for row in problems if (row['provider'],row['dataset']) not in recovered]
    ignored={ (row['provider'],row['dataset']) for row in runs if (row['provider'],row['dataset']) not in scopes and row['status']=='failed'}
    counts=dict(Counter(row['state'] for row in items))
    status='unconfigured' if not items else 'incomplete' if any(row['state']!='ready' for row in items) else 'degraded' if unresolved else 'recovered' if recovered else 'ok'
    return {'profile':profile_name,'as_of':cutoff,'status':status,'required_streams':len(items),'state_counts':counts,
            'requirements':items,'scoped_latest_problems':problems,'ignored_failure_stream_count':len(ignored),
            'recovered_primary_failures':[row for row in problems if (row['provider'],row['dataset']) in recovered],
            'interpretation':'Configured collection/data readiness; not thesis sufficiency, release acceptance or publication-PIT verification'}
