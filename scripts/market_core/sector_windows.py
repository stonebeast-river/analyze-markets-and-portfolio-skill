"""Named sector price proxies on common dated windows, without rotation/prediction labels."""
from datetime import datetime,timezone
import math

from .lineage import computational_input,prefix_lineages
from .task_health import profile_health


def compare_price_windows(sector,benchmark,*,periods=(1,5,20,60)):
    if not sector or not benchmark:return {'status':'missing_series','missing':['price_histories']}
    if len({(r.symbol,r.interval) for r in sector})!=1 or len({(r.symbol,r.interval) for r in benchmark})!=1:
        return {'status':'incomplete','missing':['one_symbol_and_interval_per_series']}
    if sector[-1].interval!=benchmark[-1].interval:
        return {'status':'incomplete','missing':['matched_intervals']}
    for series in (sector,benchmark):
        stamps=[r.timestamp for r in series]
        if stamps!=sorted(set(stamps)):
            return {'status':'incomplete','missing':['unique_chronological_timestamps']}
        if any(type(r.close) not in (int,float) or not math.isfinite(r.close) or r.close<=0 for r in series):
            return {'status':'incomplete','missing':['positive_finite_close']}
    contracts={(row.provider,row.price_basis,row.currency) for row in sector}
    benchmark_contracts={(row.provider,row.price_basis,row.currency) for row in benchmark}
    if len(contracts)!=1 or len(benchmark_contracts)!=1:return {'status':'incomplete','missing':['one_provider_basis_currency_per_series']}
    left=sector[-1];right=benchmark[-1]
    if left.currency in {'','unknown'} or left.currency!=right.currency or left.price_basis!=right.price_basis:
        return {'status':'incomplete','missing':['matched_currency_and_return_basis']}
    left_map={row.timestamp:row.close for row in sector};right_map={row.timestamp:row.close for row in benchmark}
    if sector[-1].timestamp!=benchmark[-1].timestamp:return {'status':'incomplete','missing':['matched_latest_session']}
    dates=sorted(right_map);windows=[];endpoint_windows=[]
    for period in periods:
        if len(dates)<=period:
            windows.append({'periods':period,'status':'missing_window'});continue
        start,end=dates[-period-1],dates[-1]
        required_dates=dates[-period-1:]
        absent=[day for day in required_dates if day not in left_map]
        if absent:
            windows.append({'periods':period,'status':'missing_sector_sessions','missing_dates':absent})
            if start in left_map and end in left_map:
                lr=left_map[end]/left_map[start]-1;rr=right_map[end]/right_map[start]-1
                endpoint_windows.append({'periods':period,'window_unit':'fixed_benchmark_trading_observation_endpoints',
                    'start':start,'end':end,'sector_price_return':lr,'benchmark_price_return':rr,
                    'relative_return_percentage_points':(lr-rr)*100,'status':'measured_endpoints_with_gaps',
                    'missing_dates':absent,'complete_window':False,
                    'continuous_indicator_or_path_measure_supported':False})
            continue
        left_return=left_map[end]/left_map[start]-1;right_return=right_map[end]/right_map[start]-1
        windows.append({'periods':period,'window_unit':'matching_benchmark_trading_observations','start':start,'end':end,
                        'sector_price_return':left_return,'benchmark_price_return':right_return,
                        'relative_return_percentage_points':(left_return-right_return)*100,'status':'measured'})
    return {'status':'price_proxy_comparison','sector_identity':left.symbol,'benchmark_identity':right.symbol,
            'sector_provider':left.provider,'benchmark_provider':right.provider,
            'different_provider_pair':left.provider!=right.provider,'currency':left.currency,'price_basis':left.price_basis,
            'windows':windows,'endpoint_windows_with_gaps':endpoint_windows,
            'holdings_used':False,'return_basis':'price_return_not_verified_total_return',
            'input_lineages':{'sector':prefix_lineages(sector,'bars')[-1],'benchmark':prefix_lineages(benchmark,'bars')[-1]}}


def sector_price_scan(store,config,*,as_of=None):
    cutoff=as_of or datetime.now(timezone.utc).isoformat();health=profile_health(store,config,'allocation',as_of=cutoff)
    requirements={row['identity']:row for row in health['requirements'] if row['kind']=='daily_bars'}
    profile=config['profiles']['allocation'];groups=[('mainland_CSI_sector_index_proxies',profile.get('cn_sector_indices',[]),'sh000300'),
            ('US_sector_ETF_proxies',[symbol for symbol in profile.get('global_symbols',[]) if symbol in
             {'XLK','XLF','XLE','XLY','XLP','XLI','XLV','XLU','XLB','XLRE','XLC'}],'SPY')]
    rows=[];inputs={}
    def selected(identity):
        requirement=requirements.get(identity)
        if not requirement or requirement['state']!='ready':return []
        series=store.get_bars(identity,'1d',provider=requirement['provider'],price_basis=requirement['price_basis'],limit=120,as_of=cutoff)
        inputs[identity]=[computational_input(row,'bars') for row in series];return series
    for scheme,identities,benchmark in groups:
        reference=selected(benchmark)
        for identity in identities:
            measured=compare_price_windows(selected(identity),reference)
            rows.append({'scheme':scheme,'identity':identity,**measured})
    return {'as_of':cutoff,'status':'bounded_price_proxy_scan','rows':rows,'calculation_inputs':inputs,
            'missing':{'Hong_Kong_sector_windows':'not_collected','constituent_multi_period_breadth':'not_reconstructed',
                       'earnings_policy_valuation_confirmation':'not_established_by_price_windows'},
            'holdings_used':False,'interpretation':'Index/ETF price windows prioritize research; they do not establish sector rotation or expected return'}
