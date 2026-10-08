"""Disclosure-date-aware recursive fund exposures; wrappers are replaced, never counted twice."""
import math
import re
from datetime import date


def node_from_snapshot(snapshot):
    code=snapshot['fund_code']
    source={k:snapshot[k] for k in ('report_date','publication_date','document_sha256','source_url')}
    source['valuation_currency']=snapshot.get('report_currency','CNY' if 'net_assets_CNY' in snapshot else 'unknown')
    source['holdings_scope']=snapshot.get('holdings_scope','disclosed_snapshot')
    if 'stocks' in snapshot:
        positions=[{**r,'asset_class':'stock','weight_of_fund_NAV':r['weight_of_net_assets'],
                    'price_market':'CN','price_identity':r['identity']} for r in snapshot['stocks']]
        positions.extend({**r,'asset_class':'ETF','weight_of_fund_NAV':r['weight_of_net_assets'],
                          'child_fund_code':r['identity'][2:]} for r in snapshot.get('target_funds',[]))
        allocations=[{**r,'dimension':'industry','category':r['name'],'weight_of_fund_NAV':r['weight_of_net_assets'],
                      'scope':'direct_equity_table'} for r in snapshot['industries']]
        derivatives=[{**r,'signed_contract_exposure_fraction_of_NAV':r['exposure_fraction_of_net_assets'],
                      'contract_measurement_basis':'contract_market_value'} for r in snapshot.get('futures_contracts',[])]
    else:
        positions=snapshot['securities'];allocations=snapshot['allocations'];derivatives=snapshot.get('derivative_contracts',[])
    return {'fund_code':code,'source':source,'positions':positions,'allocations':allocations,'derivatives':derivatives,
            'derivative_review':{'futures_detail_status':snapshot.get('futures_detail_status',
                'known_contract_rows_reviewed' if derivatives else 'no_contract_rows_reviewed_not_a_proof_of_none'),
                'other_derivative_instruments_reviewed':snapshot.get('other_derivative_instruments_reviewed',False),
                'all_derivatives_reviewed':snapshot.get('all_derivatives_reviewed',False)},
            'today_holdings_reconstructed':False,'fees':snapshot.get('fee_terms'),
            'source_semantic_scope':snapshot.get('review_method',snapshot.get('format_scope'))}


def recursive_lookthrough(root_code,resolve,*,max_depth=8,max_paths=2000):
    """resolve returns an exact-code reviewed node or None; missing children remain weighted unknowns."""
    if type(max_depth)!=int or not 1<=max_depth<=20:raise ValueError('Bounded positive look-through depth required')
    if type(max_paths)!=int or max_paths<1:raise ValueError('Positive graph path budget required')
    leaves={};unresolved=[];residuals=[];paths=[];allocations=[];derivatives=[];derivative_reviews=[];fees=[];dates=set()
    def visit(code,multiplier,ancestors,links):
        if len(paths)>=max_paths:
            unresolved.append({'fund_code':code,'weight_of_root_NAV':multiplier,'reason':'path_budget','path':links});return
        if code in ancestors:
            unresolved.append({'fund_code':code,'weight_of_root_NAV':multiplier,'reason':'cycle','path':links});return
        if len(ancestors)>=max_depth:
            unresolved.append({'fund_code':code,'weight_of_root_NAV':multiplier,'reason':'depth_limit','path':links});return
        node=resolve(code)
        if node is None:
            unresolved.append({'fund_code':code,'weight_of_root_NAV':multiplier,'reason':'missing_child_disclosure','path':links});return
        if node.get('fund_code')!=code:raise ValueError('Child disclosure does not match exact requested fund code')
        source=node['source']
        if date.fromisoformat(source['publication_date'][:10])<date.fromisoformat(source['report_date']):
            raise ValueError('Child publication precedes the report date')
        dates.add(source['report_date'])
        path=links+[{'fund_code':code,**source,'weight_multiplier_from_root':multiplier}]
        paths.append(path[-1]);positions=node['positions'];seen=set();total=0
        for row in positions:
            identity=row.get('identity');weight=row.get('weight_of_fund_NAV')
            if row.get('price_market') and row.get('price_identity'):
                identity=row['price_market']+':'+row['price_identity']
            elif re.fullmatch(r'(sh|sz|bj)\d{6}',identity or ''):
                identity='CN:'+identity
            if not identity or identity in seen:raise ValueError('Duplicate or absent identity in one fund disclosure')
            if type(weight) not in (int,float) or not math.isfinite(weight) or weight<0:
                raise ValueError('Finite nonnegative NAV-denominated position required')
            seen.add(identity);total+=weight;contribution=multiplier*weight
            if not contribution:continue
            child=row.get('child_fund_code')
            if row['asset_class'] in {'fund','ETF'}:
                if not child:
                    unresolved.append({'identity':identity,'weight_of_root_NAV':contribution,
                        'reason':'child_identity_not_verified','path':path,'source_position':row});continue
                visit(child,contribution,ancestors+(code,),path+[{'holding_identity':identity,
                    'parent_weight_of_NAV':weight,'parent_report_date':source['report_date']}])
            else:
                item=leaves.setdefault(identity,{'identity':identity,'name':row.get('name',identity),
                    'asset_class':row['asset_class'],'price_market':row.get('price_market'),
                    'price_identity':row.get('price_identity'),'estimated_weight_of_root_NAV':0,'paths':[]})
                if item['asset_class']!=row['asset_class']:raise ValueError('Conflicting asset class for the same leaf identity')
                if row.get('price_identity'):
                    if item.get('price_identity') and (item['price_identity'],item['price_market'])!=(row['price_identity'],row['price_market']):
                        raise ValueError('Conflicting native price identities for the same leaf')
                    item.update(price_identity=row['price_identity'],price_market=row['price_market'])
                item['estimated_weight_of_root_NAV']+=contribution
                item['paths'].append({'source_position':row,'contribution_to_root_NAV':contribution,'path':path})
        residuals.append({'fund_code':code,'report_date':source['report_date'],
            'net_fraction_not_detailed_at_node':1-total,'contribution_to_root_NAV':multiplier*(1-total),
            'meaning':'unreported details/cash/other assets minus liabilities; may be negative for gross assets', 'path':path})
        for row in node.get('allocations',[]):
            weight=row['weight_of_fund_NAV']
            if not math.isfinite(weight):raise ValueError('Finite allocation weight required')
            allocations.append({**row,'fund_code':code,'estimated_layer_measure_of_root_NAV':multiplier*weight,'path':path})
        for row in node.get('derivatives',[]):
            weight=row['signed_contract_exposure_fraction_of_NAV']
            if not math.isfinite(weight):raise ValueError('Finite separate contract exposure required')
            derivatives.append({**row,'fund_code':code,'estimated_contract_measure_of_root_NAV':multiplier*weight,'path':path})
        derivative_reviews.append({'fund_code':code,**node.get('derivative_review',{'futures_detail_status':'not_established','all_derivatives_reviewed':False}), 'path':path})
        fees.append({'fund_code':code,'fees':node.get('fees'),'path':path,
                     'effective_total_fee_computed':False,'historical_NAV_charged_again':False})
    visit(root_code,1.0,(),[])
    leaf_total=sum(r['estimated_weight_of_root_NAV'] for r in leaves.values())
    missing_total=sum(r['weight_of_root_NAV'] for r in unresolved)
    residual_total=sum(r['contribution_to_root_NAV'] for r in residuals)
    accounting=leaf_total+missing_total+residual_total
    if abs(accounting-1)>1e-9:raise ValueError('Recursive exposure accounting did not reconcile')
    return {'fund_code':root_code,'securities':sorted(leaves.values(),key=lambda r:-r['estimated_weight_of_root_NAV']),
        'snapshot_paths':paths,'unresolved_child_funds':unresolved,'node_residuals':residuals,
        'layer_classifications':allocations,'classification_layers_automatically_merged':False,
        'separate_derivative_paths':derivatives,'derivatives_added_to_asset_or_stock_weights':False,
        'derivative_review_by_layer':derivative_reviews,
        'fee_layers':fees,'mixed_report_dates':len(dates)>1,'report_dates':sorted(dates),
        'coverage':{'leaf_detail_of_root_NAV':leaf_total,'unresolved_child_of_root_NAV':missing_total,
                    'net_residual_of_root_NAV':residual_total,'accounting_sum':accounting},
        'all_referenced_children_resolved':not unresolved,
        'all_holdings_disclosed':bool(paths) and not unresolved and all(abs(r['net_fraction_not_detailed_at_node'])<1e-9 for r in residuals),
        'recursive_path_arithmetic_verified':True,
        'today_holdings_reconstructed':False,'full_recursive_lookthrough_verified':not unresolved and all(abs(r['net_fraction_not_detailed_at_node'])<1e-9 for r in residuals),
        'personal_portfolio_used':False,'method':'multiply each exact disclosed child NAV weight; replace fund wrappers with leaves; retain dates/unknowns'}


def stored_fund_graph(store,code,*,as_of=None,max_depth=8):
    from datetime import datetime,timezone
    cutoff=as_of or datetime.now(timezone.utc).isoformat();cache={};snapshots={}
    def resolve(identity):
        if identity in cache:return cache[identity]
        rows=[r for r in store.get_observations('fund_holdings',identity,limit=1,as_of=cutoff)
              if (r['provider']=='reviewed_primary_holdings' and r['quality']=='source_bound_reviewed_snapshot') or
                 (r['provider']=='chinaamc_disclosed_holdings' and r['quality']=='primary_report_parsed_with_explicit_reconciliation')]
        if not rows:cache[identity]=None;return None
        latest=max(r['as_of'] for r in rows);rows=[r for r in rows if r['as_of']==latest]
        if len({r['value']['document_sha256'] for r in rows})!=1:raise ValueError('Conflicting same-date child disclosures')
        selected=next((r for r in rows if r['provider']=='chinaamc_disclosed_holdings'),rows[-1])
        if selected['provider']=='reviewed_primary_holdings' and selected['value'].get('publication_dispatch_date_bound_to_original') is not True:
            raise ValueError('Child disclosure publication date requires original-source re-review')
        snapshot=selected['value']
        if selected['provider']=='reviewed_primary_holdings':
            from .fund_reviewed_holdings import reviewed_snapshot
            snapshot=reviewed_snapshot(snapshot['source_review'],store.path.parent/'documents')
            if snapshot['publication_date']>cutoff[:10] or snapshot['report_date']>cutoff[:10]:
                cache[identity]=None;return None
        snapshots[identity]=snapshot;node=node_from_snapshot(snapshot)
        products=store.get_observations('fund_product',identity,limit=1,as_of=cutoff)
        if products:
            value=products[-1]['value'];node['fees']={'terms':value.get('fee_terms'),
                'field_sources':value.get('field_sources'),'contract_missing':value.get('fee_contract_missing')}
        cache[identity]=node;return node
    result=recursive_lookthrough(code,resolve,max_depth=max_depth)
    if not result['snapshot_paths']:raise ValueError('Root fund disclosure is unavailable')
    from .fund_holdings import look_through_feeder
    reconciliations=[]
    for parent in snapshots.values():
        if 'stocks' not in parent:continue
        for link in parent.get('target_funds',[]):
            child=snapshots.get(link['identity'][2:])
            if child and 'stocks' in child:
                measured=look_through_feeder(parent,child)
                reconciliations.append({'parent_code':parent['fund_code'],'child_code':child['fund_code'],
                    'quantity_value_bridge':measured['cross_layer_value_bridge'],
                    'source_table_reconciliation':measured['source_table_reconciliation']})
    result['source_reconciliations']=reconciliations
    result['as_of']=cutoff;return result
