"""Frozen research inputs, reference-bound market views and a holdings-last interface."""
import hashlib
import json
import math
from datetime import datetime,timezone
from pathlib import Path

from .market_scan import scan_market
from .market_scan import scan_input_rows
from .lineage import canonical, freeze_inputs, read_frozen_inputs
from .reproduction import calculator_sources, freeze_indicator, calculate_from_frozen, measurement_matches
from .task_health import profile_health
from .sector_windows import sector_price_scan,compare_price_windows
from .models import Bar


OPPORTUNITY_CORE = {
    'fundamental improvement': {'fundamental_driver': {'issuer_financial'}},
    'policy or liquidity transmission': {
        'implemented_change': {'official_event'},
        'transmission_measure': {'issuer_financial', 'official_macro_statistics', 'exposure_measure'},
    },
    'valuation mean reversion with catalyst': {
        'valuation': {'valuation_measure'},
        'catalyst': {'official_event', 'issuer_financial'},
    },
    'defensive or diversification value': {
        'exposure_measure': {'exposure_measure'},
        'risk_scenario': {'official_event', 'official_macro_statistics', 'market_price'},
    },
}
TARGET_SPECIFIC_ROLES = {'fundamental_driver', 'valuation', 'exposure_measure'}


def validate_promotion(item, register):
    """Check cited core measurements; this does not certify the economic argument."""
    opportunity_type = item.get('opportunity_type')
    if opportunity_type not in OPPORTUNITY_CORE:
        raise ValueError('Use one of the four documented opportunity types')
    if item['status'] == 'not yet':
        return
    if item.get('core_missing') not in ([],):
        raise ValueError('Promotion requires an explicit empty core_missing list')
    target = item.get('target_identity')
    core = item.get('core_evidence')
    if not isinstance(target, str) or not target or not isinstance(core, dict):
        raise ValueError('Promotion requires target_identity and role-bound core_evidence')
    ids = set(item['evidence_ids'])
    for role, allowed_types in OPPORTUNITY_CORE[opportunity_type].items():
        role_ids = core.get(role)
        if not isinstance(role_ids, list) or not role_ids:
            raise ValueError('Missing core evidence role: ' + role)
        for key in role_ids:
            if key not in ids:
                raise ValueError('Core evidence must also be cited in evidence_ids')
            fact = register[key]
            if not fact['eligible'] or fact['kind'] not in allowed_types:
                raise ValueError('Ineligible or wrong evidence type for core role: ' + role)
            if role in TARGET_SPECIFIC_ROLES and fact['identity'] != target:
                raise ValueError('Core evidence does not match target_identity: ' + role)
    # A single record cannot act as both a catalyst and its independent confirmation.
    role_sets = [set(core[role]) for role in OPPORTUNITY_CORE[opportunity_type]]
    if len(role_sets) > 1 and role_sets[0] & role_sets[1]:
        raise ValueError('Distinct core roles need distinct evidence records')


def write_new(path,value):
    with Path(path).open('xb') as handle:handle.write(canonical(value))


def prepare_research(store,directory,*,profile,config=None):
    if profile not in {'allocation','tactical'}:raise ValueError('Use allocation or tactical')
    target=Path(directory).resolve();target.mkdir(parents=True,exist_ok=True)
    if (target/'research-inputs.json').exists():raise ValueError('Use a new research run directory; original inputs are immutable')
    cutoff=datetime.now(timezone.utc).isoformat()
    snapshot=store.snapshot(as_of=cutoff)
    tactical_identities=[]
    if profile=='tactical':
        settings=(config or {}).get('profiles',{}).get('tactical',{})
        tactical_identities=settings.get('cn_symbols') or sorted({row['symbol'] for row in snapshot['latest_bars']
            if row['interval'] not in {'1d','1w','1mo'}})
        if tactical_identities:
            # Global snapshot caps must not remove the profile's actual research targets.
            quotes=store.get_quotes(tactical_identities,as_of=cutoff)
            snapshot['latest_quotes']=list({(row['provider'],row['symbol'],row['as_of']):row
                for row in snapshot['latest_quotes']+quotes}.values())
            indicators=store.get_indicators(tactical_identities,
                intervals=(settings.get('intraday_interval','5m'),'snapshot','1d'),as_of=cutoff)
            snapshot['latest_indicators']=list({(row['symbol'],row['interval'],row['name'],row['input_provider'],row['price_basis']):row
                for row in snapshot['latest_indicators']+indicators}.values())
    broad=scan_market(store,as_of=cutoff,limit=30,include_inputs=True)
    broad_inputs=broad.pop('calculation_inputs')
    broad_reference=freeze_inputs(target,'market_scan',[broad_inputs])
    broad_reproduced=canonical(scan_input_rows(**broad_inputs))==canonical(broad)
    source_reference=freeze_inputs(target,'calculator_sources',calculator_sources())
    input_references={broad_reference['sha256']:broad_reference,source_reference['sha256']:source_reference}
    lineage_cache={};lineage_counts={}
    sector_scan=None;sector_reference=None;sector_source_reference=None
    if config is not None and profile=='allocation':
        sector_scan=sector_price_scan(store,config,as_of=cutoff)
        sector_inputs=sector_scan.pop('calculation_inputs')
        sector_reference=freeze_inputs(target,'sector_price_histories',[sector_inputs])
        source_path=Path(__file__).parent/'sector_windows.py'
        sector_source_reference=freeze_inputs(target,'sector_calculator_sources',[{'name':source_path.name,
            'sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),'source':source_path.read_text(encoding='utf-8')}])
        input_references[sector_reference['sha256']]=sector_reference
        input_references[sector_source_reference['sha256']]=sector_source_reference
    observations=[row for row in snapshot['recent_observations'] if row['dataset'] in {
        'macro_series','financials','financials_primary','announcement','cn_daily_valuation_liquidity','exposure_measure','intraday_source_quality'}]
    quality_context={}
    for row in sorted(observations,key=lambda r:r['as_of']):
        if row['dataset']=='intraday_source_quality':
            quality_context[(row['identity'],row['value'].get('provider'))]=row['value']
    tactical_summaries=[]
    for identity in tactical_identities:
        for dataset in ('transaction_aggregate_summary','tick_order_size_summary','stock_order_size_flow_1m','stock_order_size_flow_1d'):
            for row in store.get_observations(dataset,identity,limit=1,as_of=cutoff):
                if dataset=='transaction_aggregate_summary':
                    source_rows=[item for item in store.get_observations('transaction_aggregate',limit=1,as_of=cutoff)
                        if item['provider']==row['provider'] and item['identity'].startswith(identity+'#')
                        and item['as_of'][:10]==row['as_of'][:10]]
                    reference=freeze_inputs(target,'transaction_aggregate_rows',source_rows)
                    input_references[reference['sha256']]=reference
                    row={**row,'aggregate_input_reference':reference}
                tactical_summaries.append(row)
    facts=[]
    if sector_scan:
        for row in sector_scan['rows']:
            measured_end=next((window['end'] for window in row.get('windows',[]) if window.get('status')=='measured'),cutoff)
            facts.append({'kind':'market_price','identity':row['identity'],'as_of':measured_end,
                'source_url':'frozen_sector_price_inputs','eligible':row.get('status')=='price_proxy_comparison',
                'record':{**row,'measurement':'sector_price_windows','independent_evidence_type':False,
                          'input_reference':sector_reference}})
    if broad.get('status')=='research_scan':
        session=(broad.get('source_sessions') or [cutoff[:10]])[-1]
        facts.append({'kind':'market_price','identity':'CN_A_supplier_universe','as_of':session,
            'source_url':'https://qt.gtimg.cn/','eligible':broad['coverage']['missing_requested']==0,
            'record':{'measurement':'cross_sectional_breadth','coverage':broad['coverage'],'breadth':broad['breadth'],
                      'source_sessions':broad['source_sessions'],'derived_from':'dated_supplier_quotes','exchange_census_verified':False,
                      'lineage':{'input_reference':broad_reference,'recomputed_matches':broad_reproduced}}})
        for sector in broad.get('industry_breadth',[]):
            facts.append({'kind':'market_price','identity':'CN_industry:'+str(sector['industry']),'as_of':session,
                'source_url':'https://www.baostock.com/','eligible':sector['observed_members']>0,
                'record':{**sector,'measurement':'industry_price_breadth','quote_source':'tencent_web_quote',
                          'taxonomy_source':'baostock_free_history','taxonomy_is_current_snapshot_not_historical_membership':True,
                          'lineage':{'input_reference':broad_reference,'recomputed_matches':broad_reproduced}}})
    for row in snapshot['latest_quotes']:
        facts.append({'kind':'market_price','identity':row['symbol'],'as_of':row['as_of'],'source_url':row['source_url'],
            'eligible':row['freshness']['status']=='current_session' and row['currency'] not in {'','unknown',None}
                       and type(row['last']) in (int,float) and math.isfinite(row['last']) and row['last']>0,'record':row})
    for row in snapshot['latest_bars']:
        volume_context=quality_context.get((row['symbol'],row['provider'])) if row['interval']=='1m' else None
        facts.append({'kind':'market_price','identity':row['symbol'],'as_of':row['timestamp'],'source_url':row['source_url'],
            'eligible':row['price_basis'] not in {'unknown','legacy_unknown'} and row['currency'] not in {'','unknown',None}
                       and all(type(row[field]) in (int,float) and math.isfinite(row[field]) and row[field]>0 for field in ('open','high','low','close')),
            'record':{**row,**({'volume_quality_context':volume_context,'volume_confirmation_eligible':volume_context['volume_confirmation_eligible']} if volume_context else {})}})
    for row in snapshot['latest_indicators']:
        if profile=='allocation' and row['interval'] not in {'1d','1w','1mo'}:continue
        if profile=='tactical' and row['interval'] in {'1w','1mo'}:continue
        lineage=freeze_indicator(store,row,target,lineage_cache,as_of=cutoff)
        lineage_counts[lineage['status']]=lineage_counts.get(lineage['status'],0)+1
        if lineage.get('input_reference'):
            reference=lineage['input_reference'];input_references[reference['sha256']]=reference
        facts.append({'kind':'market_price','identity':row['symbol'],'as_of':row['timestamp'],
            'source_url':'local_indicator_receipt:'+row['input_provider'],
            'eligible':row['value'] is not None and row['price_basis'] not in {'unknown','legacy_unknown'}
                       and row['currency'] not in {'','unknown',None} and lineage['recomputed_matches']
                       and row['quality']!='unverified_for_volume_confirmation',
            'record':{**row,'measurement':('vendor_derived_trading_metric' if row['quality']=='vendor_derived'
                                         else 'locally_derived_price_or_trading_metric'),
                      'lineage':lineage,'independent_evidence_type':False,
                      'indicator_snapshot_sample_truncated':snapshot['indicator_sample_truncated']}})
    rate_fx_prefixes=('DGS','DFII','DEX','DTW','T10Y','BAML','SOFR')
    for row in observations:
        kind = ({'financials':'issuer_financial','financials_primary':'issuer_financial','announcement':'official_event',
                 'cn_daily_valuation_liquidity':'valuation_measure','exposure_measure':'exposure_measure','intraday_source_quality':'market_price'}.get(row['dataset'])
                or ('market_price' if row['identity'].startswith(rate_fx_prefixes) else 'official_macro_statistics'))
        eligible=row['quality'] not in {'provider_financials_units_unverified','imported_requires_source_verification','stale','unavailable'}
        if row['dataset']=='intraday_source_quality':
            eligible=False
            row={**row,'measurement':'local_source_quality_context','independent_evidence_type':False}
        if row['dataset']=='financials_primary':
            value=row['value'];fields=value.get('fields',[])
            eligible=(eligible and bool(fields) and value.get('provenance',{}).get('review_matches_current_bytes') is True
                      and all(field.get('semantic_verification',{}).get('row_column_values_verified') is True
                              and field.get('semantic_verification',{}).get('period_and_scope_schema_verified') is True
                              for field in fields))
        if row['dataset']=='cn_daily_valuation_liquidity':
            multiples=row['value'] if isinstance(row['value'],dict) else {}
            eligible=eligible and any(type(multiples.get(field)) in (int,float) and math.isfinite(multiples[field]) and multiples[field]!=0
                                      for field in ('pe_ttm','pb_mrq','ps_ttm','pcf_ncf_ttm'))
        if row['dataset']=='exposure_measure':
            measure=row['value']
            number=measure.get('value') if isinstance(measure,dict) else None
            eligible=eligible and isinstance(measure,dict) and all(measure.get(field) for field in ('measurement','unit','window')) and type(number) in (int,float) and math.isfinite(number)
        facts.append({'kind':kind,'identity':row['identity'],'as_of':row['as_of'],'source_url':row['source_url'],'eligible':eligible,'record':row})
    for row in tactical_summaries:
        complete=(row['value'].get('status')=='complete_supplier_window'
                  if row['dataset']=='transaction_aggregate_summary' else row['quality'] not in {'unavailable','unverified'})
        facts.append({'kind':'market_price','identity':row['identity'],'as_of':row['as_of'],
                      'source_url':row['source_url'],'eligible':complete,
                      'record':{**row,'measurement':'supplier_classified_flow_or_local_summary','independent_evidence_type':False}})
    register={}
    for fact in facts:
        key='E-'+hashlib.sha256(canonical(fact)).hexdigest()[:16]
        register[key]=fact
    value={'schema_version':2,'profile':profile,'cutoff':cutoff,'holdings_loaded':False,
           'coverage':store.universe(limit=30,as_of=cutoff),'market_scan':broad,'evidence_register':register,
           'data_health':profile_health(store,config,profile,as_of=cutoff) if config is not None else snapshot['health'],
           'health_scope':'configured_research_requirements' if config is not None else 'all_database_history_not_a_profile_acceptance',
           'numerical_evidence_only':True,
           'input_references':list(input_references.values()),'calculator_source_reference':source_reference,
           'lineage_validation':{'indicator_status_counts':lineage_counts,'market_scan_reproduced':broad_reproduced},
           'sector_price_scan':sector_scan,'sector_source_reference':sector_source_reference,
           'tactical_input_coverage':{'target_identities':tactical_identities,
                'target_indicator_count':sum(row['symbol'] in tactical_identities for row in snapshot['latest_indicators']),
                'flow_summary_count':len(tactical_summaries),
                'target_inputs_override_global_snapshot_cap':bool(tactical_identities)},
           'analysis_instructions':['Form and lock independent market conclusions before loading holdings.',
             'Use source-bound evidence IDs; two market price/flow measurements are not independent evidence types.',
             'Retrieve dated primary event/financial evidence where a thesis requires it; add it to a new prepared run.',
             'Compare support, strongest countercase, alternatives and waiting; no candidate quota.',
             'Screen anomalies prioritize investigation and cannot establish expected return.']}
    write_new(target/'research-inputs.json',value)
    digest=hashlib.sha256(canonical(value)).hexdigest()
    write_new(target/'input-seal.json',{'sha256':digest,'created_at':cutoff})
    return {'directory':str(target),'input_sha256':digest,'evidence_count':len(register),'holdings_loaded':False,
            'lineage_validation':value['lineage_validation'],'frozen_input_count':len(input_references)}


def read_prepared(directory):
    target=Path(directory).resolve()
    inputs=json.loads((target/'research-inputs.json').read_text(encoding='utf-8'))
    seal=json.loads((target/'input-seal.json').read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(inputs)).hexdigest()!=seal['sha256']:raise ValueError('Frozen research inputs were changed')
    for reference in inputs.get('input_references',[]):read_frozen_inputs(target,reference)
    return target,inputs,seal


def verify_research(directory):
    target,inputs,_=read_prepared(directory)
    if inputs.get('schema_version',1)<2:
        return {'status':'legacy_inputs_without_complete_lineage','recomputation_verified':False}
    original_sources=read_frozen_inputs(target,inputs['calculator_source_reference'])
    if canonical(original_sources)!=canonical(calculator_sources()):
        return {'status':'calculator_version_mismatch','recomputation_verified':False}
    cache={};checked=0;missing=0;failures=[]
    for key,fact in inputs['evidence_register'].items():
        row=fact['record'];lineage=row.get('lineage')
        if 'input_provider' not in row:continue
        if not lineage or not lineage.get('recomputed_matches'):
            missing+=1;continue
        reference=lineage['input_reference'];digest=reference['sha256']
        if digest not in cache:
            frozen=read_frozen_inputs(target,reference)
            cache[digest]={(item.name,item.timestamp):item for item in calculate_from_frozen(reference['kind'],frozen)}
        result=cache[digest].get((row['name'],row['timestamp']))
        if result is None or not measurement_matches(row,result):failures.append(key)
        checked+=1
    broad_reference=next(ref for ref in inputs['input_references'] if ref['kind']=='market_scan')
    broad_inputs=read_frozen_inputs(target,broad_reference)[0]
    replayed_scan=scan_input_rows(**broad_inputs)
    if canonical(replayed_scan)!=canonical(inputs['market_scan']):failures.append('market_scan')
    aggregate_count=0
    for key,fact in inputs['evidence_register'].items():
        if key!='E-'+hashlib.sha256(canonical(fact)).hexdigest()[:16]:failures.append(key+':evidence_hash')
        record=fact['record'];measurement=record.get('measurement')
        if measurement not in {'cross_sectional_breadth','industry_price_breadth'}:continue
        aggregate_count+=1
        if measurement=='cross_sectional_breadth':
            expected={field:replayed_scan[field] for field in ('coverage','breadth','source_sessions')}
            identity='CN_A_supplier_universe'
        else:
            sector=next((row for row in replayed_scan.get('industry_breadth',[])
                         if row['classification']==record.get('classification') and row['industry']==record.get('industry')),None)
            if sector is None:failures.append(key+':unmatched_industry');continue
            expected=sector;identity='CN_industry:'+str(sector['industry'])
        reference=record.get('lineage',{}).get('input_reference')
        if (fact['kind']!='market_price' or fact['identity']!=identity or reference!=broad_reference
                or any(canonical(record.get(field))!=canonical(value) for field,value in expected.items())):
            failures.append(key+':registered_aggregate')
    sector_count=0
    tactical_aggregate_count=0
    for key,fact in inputs['evidence_register'].items():
        row=fact['record']
        if row.get('dataset')!='transaction_aggregate_summary':continue
        reference=row.get('aggregate_input_reference')
        if not reference:failures.append(key+':aggregate_inputs_missing');continue
        records=read_frozen_inputs(target,reference);totals={'buy_amount':0.0,'sell_amount':0.0,'neutral_amount':0.0,'unknown_amount':0.0,
            'large_aggregate_buy_amount':0.0,'large_aggregate_sell_amount':0.0}
        for item in records:
            value=item['value']
            if (item['provider']!=row['provider'] or value.get('symbol')!=row['identity'] or item['as_of'][:10]!=row['as_of'][:10]):
                failures.append(key+':aggregate_identity_or_date');continue
            side={'provider_buy':'buy','provider_sell':'sell','provider_neutral':'neutral'}.get(value.get('direction'),'unknown')
            amount=value.get('amount')
            if type(amount) not in (int,float) or not math.isfinite(amount) or amount<0:
                failures.append(key+':aggregate_amount');continue
            totals[side+'_amount']+=amount
            if side in {'buy','sell'} and amount>=row['value']['order_size_threshold_CNY']:
                totals['large_aggregate_'+side+'_amount']+=amount
        totals.update(net_amount=totals['buy_amount']-totals['sell_amount'],records=len(records))
        if any(type(row['value'].get(field)) not in (int,float) or not math.isclose(row['value'][field],number,rel_tol=1e-10,abs_tol=1e-8)
               for field,number in totals.items()):failures.append(key+':aggregate_summary_mismatch')
        tactical_aggregate_count+=1
    if inputs.get('sector_price_scan'):
        source_path=Path(__file__).parent/'sector_windows.py'
        original=read_frozen_inputs(target,inputs['sector_source_reference'])
        if original[0]['sha256']!=hashlib.sha256(source_path.read_bytes()).hexdigest():failures.append('sector_calculator_version')
        series_reference=next(ref for ref in inputs['input_references'] if ref['kind']=='sector_price_histories')
        histories=read_frozen_inputs(target,series_reference)[0]
        for key,fact in inputs['evidence_register'].items():
            row=fact['record']
            if row.get('measurement')!='sector_price_windows':continue
            sector_count+=1
            identity=row['identity'];benchmark=row.get('benchmark_identity')
            if not benchmark:
                if row.get('status')=='missing_series':continue
                failures.append(key+':sector_identity');continue
            calculated=compare_price_windows([Bar(**bar) for bar in histories.get(identity,[])],
                                             [Bar(**bar) for bar in histories.get(benchmark,[])])
            if any(canonical(row.get(field))!=canonical(value) for field,value in calculated.items()):
                failures.append(key+':sector_window')
    return {'status':'failed' if failures else 'partial' if missing else 'ok',
            'recomputation_verified':not failures and not missing,'indicators_checked':checked,
            'aggregates_checked':aggregate_count,
            'sector_windows_checked':sector_count,
            'tactical_aggregates_checked':tactical_aggregate_count,
            'indicators_without_verified_lineage':missing,'failures':failures,'live_database_used':False}


def lock_market_view(directory,view_path):
    target,inputs,input_seal=read_prepared(directory)
    if (target/'market-view.json').exists():raise ValueError('Market view is already locked; start a new run for revisions')
    if inputs.get('schema_version',1)>=2:
        verification=verify_research(directory)
        if verification['status'] not in {'ok','partial'}:
            raise ValueError('Research recomputation failed before market-view locking: '+verification['status'])
    view=json.loads(Path(view_path).read_text(encoding='utf-8-sig'))
    if any(key in view for key in ('holdings','portfolio','positions','portfolio_weights')):
        raise ValueError('Personal holdings do not belong in the independent market view')
    for field in ('market_summary','theses','opportunities','alternatives','waiting_case'):
        if field not in view:raise ValueError('Missing market-view field: '+field)
    if not isinstance(view['theses'],list) or not isinstance(view['opportunities'],list):raise ValueError('Theses and opportunities must be lists')
    register=inputs['evidence_register']
    for item in view['theses']+view['opportunities']:
        ids=item.get('evidence_ids',[])
        if not ids or any(key not in register for key in ids):raise ValueError('Every thesis/candidate requires real prepared evidence IDs')
        if not item.get('countercase') or not item.get('invalidation'):raise ValueError('Countercase and invalidation are required')
        if item in view['opportunities']:
            status=item.get('status')
            if status not in {'worth dedicated research','watch','not yet'}:raise ValueError('Use one opportunity research state')
            types={register[key]['kind'] for key in ids if register[key]['eligible']}
            if status in {'worth dedicated research','watch'} and len(types)<2:
                raise ValueError('Promotion needs at least two independent evidence-generating types')
            validate_promotion(item,register)
    sealed={'schema_version':1,'cutoff':inputs['cutoff'],'input_sha256':input_seal['sha256'],'view':view,
            'locked_at':datetime.now(timezone.utc).isoformat(),'holdings_loaded':False}
    write_new(target/'market-view.json',sealed)
    digest=hashlib.sha256(canonical(sealed)).hexdigest()
    write_new(target/'market-view-seal.json',{'sha256':digest})
    return {'market_view_sha256':digest,'holdings_loaded':False,'opportunity_count':len(view['opportunities'])}


def load_portfolio_after_view(directory,portfolio_path):
    target,_,_=read_prepared(directory)
    view_path=target/'market-view.json';seal_path=target/'market-view-seal.json'
    if not view_path.exists() or not seal_path.exists():raise ValueError('Lock the independent market view before loading holdings')
    view=json.loads(view_path.read_text(encoding='utf-8'))
    seal=json.loads(seal_path.read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(view)).hexdigest()!=seal['sha256']:raise ValueError('Locked market view was modified')
    portfolio=json.loads(Path(portfolio_path).read_text(encoding='utf-8-sig'))
    if not portfolio.get('authoritative_source') or not isinstance(portfolio.get('positions'),list):
        raise ValueError('Provide an authoritative source and explicit positions')
    overlay={'market_view_sha256':seal['sha256'],'loaded_at':datetime.now(timezone.utc).isoformat(),
             'portfolio':portfolio,'market_view_unchanged':True}
    write_new(target/'portfolio-inputs.private.json',overlay)
    return {'positions_loaded':len(portfolio['positions']),'market_view_unchanged':True,'portfolio_amounts_printed':False}
