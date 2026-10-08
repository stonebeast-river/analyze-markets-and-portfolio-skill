"""One-code fund evidence workflow; calculations support the skill's final independent report."""
import json,re,hashlib
import unicodedata
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone,date,timedelta
from .http import HttpClient,redact_error
from .fund_products import verified_nav_currency,assemble_product
from .fund_holdings import stored_lookthrough
from .fund_nav import create_fund_nav_chart
from .fund_fee_contracts import load_fee_contract
from .fund_costs import forward_share_cost_comparison
from .stock_technicals import technical_series,technical_context
from .stock_conditions import expected_closed_session,chart_condition_plan
from .providers.fund_official import ChinaAMCFundProvider
from .providers.fund_documents import FundDocumentProvider
from .providers.fund_eastmoney import EastmoneyFundProvider
from .providers.fund_catalog import FundCatalogProvider
from .providers.fund_holdings import ChinaAMCHoldingsProvider
from .providers.fund_chinaamc_status import ChinaAMCBusinessProvider
from .providers.tencent_history import TencentHistoryProvider
from .providers.csi_valuation import CsiValuationProvider
from .providers.yahoo import YahooProvider
from .providers.chinabond_curve import ChinaBondCurveProvider
from .task_health import completed_cash_session


def resolve_fund_identifier(store,value,*,allow_network=True):
    value=value.strip()
    if re.fullmatch(r'\d{6}',value):return value
    cutoff=datetime.now(timezone.utc).isoformat()
    def matches():
        found=set()
        for dataset in ('fund_product','fund_profile_basics','instrument_listing'):
            for r in store.get_observations(dataset,limit=1,as_of=cutoff):
                v=r['value'];name=v.get('fund_name',v.get('name'))
                if name==value and re.fullmatch(r'\d{6}',r['identity']) and (dataset!='instrument_listing' or v.get('scope')=='funds'):
                    found.add(r['identity'])
        return found
    candidates=matches()
    if not candidates and allow_network:
        provider=FundCatalogProvider();provider.client.archive=store.response_vault
        rows=provider.fetch_universe();store.upsert_observations(rows);candidates=matches()
    if len(candidates)!=1:raise ValueError('Fund name is absent or ambiguous; exact share/family research required')
    return next(iter(candidates))


def product_record(store,code,cutoff):
    rows=store.get_observations('fund_product',code,limit=1,as_of=cutoff,include_raw=True)
    if not rows:return None
    # A reviewed assembler retains structured terms; live issuer pages remain separate evidence.
    rows.sort(key=lambda r:(r['provider']=='issuer_assembled_terms',r['as_of']))
    return rows[-1]


def collect_fund_inputs(store,code,*,registry_path=None):
    registry_path=Path(registry_path) if registry_path else Path(__file__).resolve().parents[2]/'assets/fund-document-sources.json'
    registry=json.loads(registry_path.read_text(encoding='utf-8-sig'));runs=[];document_dir=store.path.parent/'documents'
    def call(provider,label,fetch):
        started=datetime.now(timezone.utc).isoformat();offset=len(store.response_vault.events)
        if isinstance(getattr(provider,'client',None),HttpClient):provider.client.archive=store.response_vault
        try:
            rows=fetch();count=store.upsert_observations(rows)
            store.record_run(provider.name,label,started,'ok',count)
            runs.append({'step':label,'status':'ok','records':count});return rows
        except Exception as error:
            for event in list(store.response_vault.events[offset:]):
                if event.get('status') in ('http_ok','cache_hit'):store.response_vault.reject(event,'Fund step failed validation')
            store.record_run(provider.name,label,started,'failed',0,error=redact_error(str(error)))
            runs.append({'step':label,'status':'failed','error':redact_error(str(error))});return []
    now=datetime.now(timezone.utc).isoformat();old=product_record(store,code,now)
    name=old['value'].get('fund_name','') if old else ''
    if not name:
        listings=store.get_observations('instrument_listing',code,limit=1,as_of=now)
        name=next((r['value'].get('name','') for r in listings if r['value'].get('scope')=='funds'),'')
    chinaamc=bool(old and 'chinaamc.com' in old['source_url']) or name.startswith('华夏')
    if chinaamc:
        provider=ChinaAMCFundProvider(document_dir=document_dir)
        call(provider,'fund_product:'+code,lambda:provider.fetch_evidence(code))
    elif code in registry.get('funds',{}):
        provider=FundDocumentProvider(registry_path,document_dir)
        docs=call(provider,'fund_documents:'+code,lambda:provider.fetch_evidence(code))
        if docs:store.upsert_observations([assemble_product(store,code)])
    else:runs.append({'step':'primary_product_identity','status':'official_source_research_required','code':code})
    cutoff=datetime.now(timezone.utc).isoformat();currency=verified_nav_currency(store,code,as_of=cutoff)
    provider=EastmoneyFundProvider()
    call(provider,'fund_NAV:'+code,lambda:provider.fetch_evidence(code,currency=currency['currency']))
    current_product=product_record(store,code,datetime.now(timezone.utc).isoformat())
    fund_type=str((current_product or {}).get('value',{}).get('fund_type','')).lower()
    if specialized_underlying_action(fund_type)!='review_foreign_or_specialized_underlying':
        rates=ChinaBondCurveProvider()
        call(rates,'fund_rates_context:'+code,rates.fetch_evidence)
    if chinaamc:
        holdings=ChinaAMCHoldingsProvider(document_dir)
        rows=call(holdings,'fund_holdings:'+code,lambda:holdings.fetch_evidence(code))
        if rows and len(rows[0].value['target_funds'])==1:
            target=rows[0].value['target_funds'][0]['identity'][2:]
            call(holdings,'fund_target_holdings:'+target,lambda:holdings.fetch_evidence(target))
        business=ChinaAMCBusinessProvider()
        call(business,'fund_business_snapshot:'+code,lambda:business.fetch_evidence([code]))
    current=product_record(store,code,datetime.now(timezone.utc).isoformat())
    if current:
        v=current['value'];symbol=v.get('underlying_identity')
        if symbol in (None,'','unknown'):symbol=v.get('target_etf')
        if symbol and re.fullmatch(r'(sh|sz|bj)\d{6}',symbol):
            history=TencentHistoryProvider();history.client.archive=store.response_vault;started=datetime.now(timezone.utc).isoformat()
            try:
                end=expected_closed_session() or date.today().isoformat()
                bars=history.fetch_bars(symbol,start_date=(date.fromisoformat(end)-timedelta(days=365*4)).isoformat(),end_date=end,adjustment='none')
                count=store.upsert_bars(bars);store.record_run(history.name,'fund_underlying:'+symbol,started,'ok',count)
                runs.append({'step':'fund_underlying:'+symbol,'status':'ok','records':count})
            except Exception as error:
                store.record_run(history.name,'fund_underlying:'+symbol,started,'failed',0,error=redact_error(str(error)))
                runs.append({'step':'fund_underlying:'+symbol,'status':'failed','error':redact_error(str(error))})
        if symbol in ('sh000300','sh000905','sh000016'):
            valuation=CsiValuationProvider()
            call(valuation,'fund_underlying_valuation:'+symbol,lambda:valuation.fetch_evidence(symbol[2:],end_date=expected_closed_session()))
        elif symbol not in (None,'','unknown') and not re.fullmatch(r'(sh|sz|bj)\d{6}',symbol) and not symbol.startswith('CSI:'):
            provider=YahooProvider();provider.client.archive=store.response_vault;provider.client.retries=0
            began=datetime.now(timezone.utc).isoformat()
            try:
                bars,observations=provider.fetch_evidence([symbol],lookback_days=900)
                count=store.upsert_bars(bars)+store.upsert_observations(observations)
                store.record_run(provider.name,'fund_foreign_underlying:'+symbol,began,'ok',count)
                runs.append({'step':'fund_foreign_underlying:'+symbol,'status':'ok','records':count})
            except Exception as error:
                store.record_run(provider.name,'fund_foreign_underlying:'+symbol,began,'failed',0,error=redact_error(str(error)))
                runs.append({'step':'fund_foreign_underlying:'+symbol,'status':'failed','error':redact_error(str(error))})
    return runs


def matched_price_comparisons(nav_rows,bars):
    by_date={b.timestamp[:10]:b for b in bars};rows=sorted(nav_rows,key=lambda r:r['as_of']);result=[]
    for n in (5,20,60):
        if len(rows)<=n:continue
        selected=rows[-n-1:];first,last=selected[0],selected[-1]
        a,b=by_date.get(first['as_of'][:10]),by_date.get(last['as_of'][:10])
        if not a or not b or a.currency!=first['currency']:continue
        fund_return=last['value']/first['value']-1;proxy_return=b.close/a.close-1
        result.append({'window_NAV_observations':n,'start_valuation_date':first['as_of'],'end_valuation_date':last['as_of'],
            'fund_unit_NAV_return':fund_return,'underlying_unadjusted_price_return':proxy_return,
            'difference_of_these_price_returns':fund_return-proxy_return,'all_window_dates_matched':all(r['as_of'][:10] in by_date for r in selected),
            'actual_policy_benchmark_tracking_measure':False,'reinvested_total_return_compared':False})
    return result


def specialized_underlying_action(fund_type):
    kind=str(fund_type or '').lower()
    if kind.startswith('bond') or '债券' in kind:return 'review_rates_credit_duration_and_funding'
    if kind in {'money','money_market'} or '货币' in kind:return 'review_cash_yields_liquidity_and_fees'
    if kind=='fof' or '基金中基金' in kind:return 'review_child_fund_allocation_and_overlap'
    return 'review_foreign_or_specialized_underlying'


def disclosed_tracking_review(product,document_dir):
    meta=product.get('documents',{}).get('report')
    if not meta:return None
    path=Path(document_dir)/(meta['sha256']+'.pdf')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=meta['sha256']:return None
    from pypdf import PdfReader
    pages=[p.extract_text() or '' for p in PdfReader(path).pages];records=[]
    pattern=r'华夏沪深300ETF联接([ACY])份额净值为([\d.]+)元,本报告期份额净值增长率为([+-]?[\d.]+)%,同期业绩比较基准增长率([+-]?[\d.]+)%,本报告期跟踪偏离度为([+-]?[\d.]+)%'
    for i,page in enumerate(pages):
        text=re.sub(r'\s+','',unicodedata.normalize('NFKC',page))
        for m in re.finditer(pattern,text):
            records.append({'share_class':m.group(1),'reported_period_NAV':float(m.group(2)),
                'reported_fund_period_return':float(m.group(3))/100,'reported_policy_benchmark_period_return':float(m.group(4))/100,
                'reported_period_difference':float(m.group(5))/100,'source_page':i+1,'source_text':m.group(0)})
    if not records:return None
    if any(abs(r['reported_fund_period_return']-r['reported_policy_benchmark_period_return']-r['reported_period_difference'])>.000051 for r in records):
        raise ValueError('Issuer reported period return difference does not reconcile')
    return {'report_publication_date':meta['publication_date'],'source_url':meta['url'],'document_sha256':meta['sha256'],
        'records':records,'measurement':'issuer_reported_period_return_difference_not_daily_tracking_error',
        'daily_tracking_error_reproduced':False,'current_period_performance_inferred':False}


def create_fund_research(store,code,directory,*,collect=True,horizon=20,position_state='unknown',
                         holding_fee_age_days=90,A_subscription_rate_scenario=None,registry_path=None):
    if position_state not in ('unknown','held','unheld'):raise ValueError('Position state must be user supplied or unknown')
    if type(horizon)!=int or horizon<1:raise ValueError('Positive research horizon required')
    root=Path(directory).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('Use a new fund research directory')
    root.mkdir(parents=True,exist_ok=True);runs=collect_fund_inputs(store,code,registry_path=registry_path) if collect else []
    cutoff=datetime.now(timezone.utc).isoformat();product=product_record(store,code,cutoff)
    if not product:raise ValueError('Primary exact-share product layer still required; continue official-source research')
    nav_chart=create_fund_nav_chart(store,code,root/'NAV',as_of=cutoff)
    nav_rows=json.loads((root/'NAV/nav-inputs.json').read_text(encoding='utf-8'))
    v=product['value'];followups=[];exposure=None
    try:exposure=stored_lookthrough(store,code,as_of=cutoff)
    except ValueError as error:followups.append({'task':'dated_holdings_and_exposure_research','reason':str(error)})
    major_holding_research=None
    if exposure:
        holding_requests=[]
        for row in sorted(exposure['securities'],key=lambda r:-r.get('estimated_weight_of_root_NAV',r.get('weight_of_fund_NAV',r.get('estimated_weight_of_feeder_NAV',0)))):
            if row.get('price_market') not in {'CN','US','HK'} or not row.get('price_identity') or row.get('asset_class') not in {'stock','ETF'}:continue
            holding_requests.append({'market':row['price_market'],'kind':row['asset_class'],'identity':row['price_identity'],
                'selection_reason':'Major disclosed product holding; dated exposure, not assumed current personal position'})
            if len(holding_requests)>=4:break
        if holding_requests:
            from .candidate_research import research_candidates
            major_holding_research=research_candidates(store,holding_requests,root/'major-holdings',collect=collect)
            cutoff=datetime.now(timezone.utc).isoformat()
    underlying=v.get('underlying_identity');role='named_underlying_index'
    if underlying in (None,'','unknown'):underlying=v.get('target_etf');role='target_ETF_market_price_proxy'
    if underlying in (None,'','unknown'):
        underlying=None;role='portfolio_or_composite_underlying_without_verified_single_price_proxy'
    mainland=bool(underlying and re.fullmatch(r'(sh|sz|bj)\d{6}',underlying));closed=expected_closed_session()
    bars=store.get_bars(underlying,'1d',price_basis='unadjusted' if mainland else 'provider_split_adjusted_close',limit=1500,as_of=cutoff) if underlying not in (None,'','unknown') else []
    if mainland:bars=[b for b in bars if closed and b.timestamp[:10]<=closed and b.currency=='CNY']
    else:
        def complete_foreign(bar):
            market=bar.raw.get('completion_calendar') or {'America/New_York':'US_CASH','Asia/Hong_Kong':'HK_CASH','Asia/Tokyo':'JP_CASH'}.get(bar.raw.get('exchange_timezone'))
            foreign_closed=completed_cash_session(market,cutoff) if market else None
            return foreign_closed and bar.timestamp[:10]<=foreign_closed and bar.session=='completed_regular_session'
        bars=[b for b in bars if complete_foreign(b)]
    groups={}
    for bar in bars:groups.setdefault((bar.provider,bar.currency,bar.price_basis),[]).append(bar)
    chosen=max(groups.values(),key=lambda group:(group[-1].timestamp,len(group))) if groups else []
    context=technical_context(technical_series(chosen)) if len(chosen)>=120 else {'state':'insufficient_underlying_history'}
    comparisons=matched_price_comparisons(nav_rows,chosen) if chosen else []
    source={'symbol':underlying,'provider':chosen[-1].provider if chosen else 'unknown','interval':'1d',
        'price_basis':chosen[-1].price_basis if chosen else 'unknown','currency':chosen[-1].currency if chosen else 'unknown'}
    conditions=chart_condition_plan(context,source) if mainland and context.get('state')=='measured' else None
    fee_scenarios=[];fee_contract=None
    try:
        fee_contract=load_fee_contract(code,store.path.parent/'documents',as_of=cutoff)
        known_sha=v.get('documents',{}).get('prospectus',{}).get('sha256')
        if known_sha and known_sha!=fee_contract['source']['sha256']:raise ValueError('Latest known prospectus has not passed this fee review')
        for rate in (None,0,.0012) if A_subscription_rate_scenario is None else (A_subscription_rate_scenario,):
            fee_scenarios.append(forward_share_cost_comparison(fee_contract,holding_fee_age_days=holding_fee_age_days,A_subscription_rate_scenario=rate))
    except (ValueError,FileNotFoundError) as error:
        fee_contract=None;followups.append({'task':'exact_share_fee_comparison','reason':str(error)})
    dealing=store.get_observations('fund_dealing_snapshot',code,limit=1,as_of=cutoff,include_raw=True)
    valuation=store.get_observations('index_valuation','CSI:'+underlying[2:],limit=1,as_of=cutoff) if underlying in ('sh000300','sh000905','sh000016') else []
    macro=[r for r in store.get_observations('macro_series',limit=1,as_of=cutoff) if isinstance(r['value'],dict) and r['value'].get('country')=='CN'] if underlying in ('sh000300','sh000905','sh000016') else []
    tracking_review=disclosed_tracking_review(v,store.path.parent/'documents')
    underlying_current=bool(chosen and closed and chosen[-1].timestamp[:10]==closed) if mainland else None
    # This is a price-phase aid, not a completed macro/valuation/product thesis.
    trend=context.get('trend');action='wait_for_research'
    if underlying_current is None:action=specialized_underlying_action(v.get('fund_type'))
    elif not underlying_current:action='refresh_underlying'
    elif trend=='downward_trend':action='do_not_add' if position_state=='held' else 'wait_for_price_repair'
    elif trend=='upward_trend':action='review_conditional_addition' if position_state=='held' else 'review_conditional_entry'
    preferred=fee_scenarios[0]['lower_relative_cost_code'] if fee_scenarios else None
    followups.extend([{'task':'underlying_valuation_fundamentals_macro_and_strongest_countercase'},
        {'task':'actual_policy_benchmark_return_and_daily_tracking_measure','disclosed_period_review_available':tracking_review is not None},
        {'task':'current_opening_day_channel_limits_and_actual_discount'},
        {'task':'final_independent_investment_opinion_and_user_budget_plan'}])
    result={'fund_code':code,'fund_name':v.get('fund_name',code),'evidence_cutoff':cutoff,'horizon_NAV_observations':horizon,
        'collection_runs':runs,'product_record':product,'NAV_chart':nav_chart,'disclosed_lookthrough':exposure,
        'major_disclosed_holding_price_research':major_holding_research,
        'underlying':{'identity':underlying,'role':role,'source':source,'source_session':chosen[-1].timestamp if chosen else None,
            'current_completed_CN_session_covered':underlying_current,'technical_context':context,'review_conditions':conditions,
            'matched_price_comparisons':comparisons,'price_only_aid_action':action},
        'fee_contract':fee_contract,'fee_scenarios':fee_scenarios,'relative_cost_preference_code':preferred,
        'underlying_official_valuation':valuation,'matched_country_macro':macro,'disclosed_tracking_review':tracking_review,
        'dealing_snapshots':dealing,
        'official_CN_yield_curves':store.get_observations('cn_bond_yield_curve',limit=1,as_of=cutoff) if specialized_underlying_action(v.get('fund_type'))!='review_foreign_or_specialized_underlying' else [],
        'material_followups':followups,'personal_portfolio_used':False,
        'full_fund_investment_decision_complete':False,'status':'fund_research_evidence_stage'}
    (root/'underlying-inputs.json').write_text(json.dumps([asdict(b) for b in chosen],ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'fund-research.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    text=f"# {result['fund_name']}（{code}）研究材料\n\n净值截至 {nav_chart['last_valuation_date']}，{nav_chart['currency']}。\n\n[净值、BOLL、MACD与回撤图](NAV/chart.html)\n\n"
    text+=f"底层 {underlying}，证据角色 {role}。价格阶段 {trend or '尚未核对'}，价格辅助意见 {action}；最终研报还需综合下列经营、估值、产品及反证证据。\n\n"
    if exposure:
        coverage=exposure['coverage'];detail=coverage.get('leaf_detail_of_root_NAV',coverage.get('security_detail_of_fund_NAV',coverage.get('security_detail_of_feeder_NAV')))
        text+=f"披露快照取得 {len(exposure['securities'])} 项证券明细，约占基金净资产 {detail:.2%}；报告期、每层来源和未知部分保存在研究记录中，不推作今日持仓。\n\n"
    if fee_scenarios:
        text+=f"按 {holding_fee_age_days} 天费用年龄和已核对标准条款，费用情景优先份额为 {preferred}。比较基准资金为10000元，不是个人预算；A类折扣情景与实际渠道费用分别保留。历史净值没有再次扣费。\n\n"
    text+='需要继续完成的研究：\n\n'+''.join('- '+x['task']+'\n' for x in followups)
    (root/'research-materials.md').write_text(text,encoding='utf-8')
    paths=[p for p in root.rglob('*') if p.is_file()]
    (root/'artifact-seal.json').write_text(json.dumps({str(p.relative_to(root)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},indent=2),encoding='utf-8')
    return {'status':result['status'],'fund_code':code,'NAV_rows':nav_chart['NAV_rows'],'underlying_phase':trend,
        'price_aid_action':action,'relative_cost_preference_code':preferred,'report_path':str(root/'research-materials.md'),
        'full_fund_investment_decision_complete':False}
