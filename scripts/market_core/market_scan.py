"""Measured cross-sectional breadth and anomaly questions; no expected-return ranking."""
from collections import Counter,defaultdict
from datetime import datetime,timezone
from statistics import median


def scan_market(store, *, as_of=None, limit=30, include_inputs=False):
    cutoff=as_of or datetime.now(timezone.utc).isoformat()
    quotes=store.get_quotes(as_of=cutoff)
    listings=store.get_observations('instrument_listing',as_of=cutoff,limit=1)
    listings=[row for row in listings if row['value'].get('scope')=='mainland_A_shares' and row['value'].get('trade_status')=='1']
    taxonomies=store.get_observations('industry_classification',as_of=cutoff,limit=1)
    result=scan_input_rows(quotes,listings,taxonomies,as_of=cutoff,limit=limit)
    if include_inputs:
        result['calculation_inputs']={'quotes':quotes,'listings':listings,'taxonomies':taxonomies,'as_of':cutoff,'limit':limit}
    return result


def scan_input_rows(quotes,listings,taxonomies,*,as_of,limit=30):
    """Replay a scan from frozen rows without consulting the current database."""
    cutoff=as_of
    expected={row['identity'] for row in listings if row['value'].get('scope')=='mainland_A_shares' and row['value'].get('trade_status')=='1'}
    industry_by_identity={row['identity']:row for row in taxonomies}
    valid=[]; excluded=Counter()
    for row in quotes:
        if row.get('asset_class')!='equity': continue
        if row['freshness']['status']!='current_session':
            excluded['session_or_quality']+=1;continue
        if not row.get('previous_close') or not row.get('last'):
            excluded['valid_price_pair']+=1;continue
        change=row['last']/row['previous_close']-1
        valid.append((row,change))
    if not valid:
        return {'as_of':cutoff,'status':'insufficient_evidence','missing':['usable_current_session_equity_quotes'],'excluded':dict(excluded)}
    changes=[change for _,change in valid]
    observations=[]
    industry_changes=defaultdict(list)
    for row,change in valid:
        mapping=industry_by_identity.get(row['symbol'])
        if mapping:
            key=(mapping['value'].get('classification'),mapping['value'].get('industry'))
            industry_changes[key].append(change)
        signals=[]
        if abs(change)>=0.05: signals.append({'kind':'large_daily_price_move','value':change,'absolute_threshold':0.05})
        ratio=row.get('volume_ratio_vendor')
        if ratio is not None and ratio>=2: signals.append({'kind':'supplier_volume_ratio','value':ratio,'threshold':2,'definition':'provider_derived_not_local_volume_ratio'})
        if signals:
            observations.append({'identity':row['symbol'],'name':row['name'],'as_of':row['as_of'],'provider':row['provider'],
                'change_fraction':change,'amount':row.get('amount'),'currency':row.get('currency'),'signals':signals,
                'status':'needs_investigation','missing_for_investment_thesis':['multi_period_history','company_or_policy_core_evidence','countercase'],
                'source_url':row['source_url']})
    observations.sort(key=lambda row:(-len(row['signals']),-(row.get('amount') or 0),row['identity']))
    got={row['symbol'] for row,_ in valid}
    sectors=[]
    for (classification,industry),values in industry_changes.items():
        sectors.append({'classification':classification,'industry':industry,'observed_members':len(values),
                        'advancers':sum(value>0 for value in values),'decliners':sum(value<0 for value in values),
                        'median_change_fraction':median(values),'weighting':'unweighted_observed_members'})
    sectors.sort(key=lambda row:row['median_change_fraction'],reverse=True)
    return {'as_of':cutoff,'source_sessions':sorted({row['as_of'][:10] for row,_ in valid}),'status':'research_scan',
        'coverage':{'requested_supplier_active_A_shares':len(expected),'usable_equity_quotes':len(valid),
                    'covered_requested':len(expected & got),'missing_requested':len(expected-got),'exchange_census_verified':False},
        'breadth':{'advancers':sum(value>0 for value in changes),'decliners':sum(value<0 for value in changes),
                   'unchanged':sum(value==0 for value in changes),'median_change_fraction':median(changes),
                   'mean_weighting':'unweighted_valid_quotes'},
        'anomaly_count':len(observations),'anomaly_sample':observations[:limit],'sample_truncated':len(observations)>limit,
        'industry_breadth':sectors,'industry_mapping_coverage':sum(len(values) for values in industry_changes.values()),
        'excluded':dict(excluded),'holdings_used':False,'interpretation':'Questions from price and trading activity, not investable opportunities'}
