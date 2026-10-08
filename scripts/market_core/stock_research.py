"""Focused stock collection, frozen curves, causal forecast and explicit review conditions."""
import hashlib,json,math,base64
import contextlib,io
from dataclasses import asdict
from datetime import datetime,timedelta,timezone
from pathlib import Path
from .models import Bar
from .conventions import SHANGHAI
from .sessions import expected_session
from .providers.tencent import TencentProvider
from .providers.baostock_provider import BaoStockProvider
from .providers.tencent_history import TencentHistoryProvider
from .providers.issuer_financials import IssuerFinancialProvider
from .providers.tencent_intraday import TencentIntradayProvider
from .providers.eastmoney import EastmoneyProvider
from .responses import ResponseVault
from .stock_technicals import technical_series,technical_context
from .directional_forecast import chronological_forecast
from .stock_chart import render_stock_chart
from .research import evidence_pack
from .symbols import normalize_cn_symbol
from .stock_conditions import chart_condition_plan,evaluate_chart_conditions,expected_closed_session
from .indicators import indicator_rows_grouped,quote_indicator_rows
from .issuer_events import current_event_context,review_issuer_events
from .stock_decision import decide_stock
from .stock_execution import paper_stock_strategy
from .providers.cninfo_announcements import CninfoAnnouncementsProvider
from .announcement_selection import select_material_documents

def resolve_stock_identifier(store,value,*,allow_network=True):
    try:return normalize_cn_symbol(value,stock_only=True)
    except ValueError:pass
    with store.connect() as db:
        names=[row[0] for row in db.execute('SELECT DISTINCT symbol FROM quotes WHERE name=? AND at_or_before(as_of,?)',
                                           (value.strip(),datetime.now(timezone.utc).isoformat()))]
    if len(names)==1:return normalize_cn_symbol(names[0],stock_only=True)
    if len(names)>1:raise ValueError('Stock name is ambiguous: '+', '.join(sorted(names)))
    if not allow_network:raise ValueError('Exact stock name has not been resolved in stored data')
    try:import baostock as bs
    except ImportError:raise ValueError('Name lookup needs the optional BaoStock package or an explicit ticker') from None
    with contextlib.redirect_stdout(io.StringIO()):
        login=bs.login()
        if login.error_code!='0':raise ValueError('Stock-name lookup login failed')
        try:records=BaoStockProvider._records(bs.query_stock_basic(code_name=value.strip()))
        finally:bs.logout()
    matching=[r['code'].replace('.','') for r in records if r.get('code_name')==value.strip() and r.get('type')=='1']
    if len(set(matching))!=1:raise ValueError('No unique exact stock name; use a market-qualified ticker')
    return normalize_cn_symbol(matching[0],stock_only=True)

def collect_stock_inputs(store,symbol,*,lookback_years=5,registry_path=None):
    if not 2<=lookback_years<=20:raise ValueError('Use 2-20 years of daily history')
    day=expected_closed_session()
    if day is None:raise ValueError('The mainland trading calendar needs current coverage')
    start=(datetime.fromisoformat(day)-timedelta(days=int(lookback_years*365.25)+90)).date().isoformat()
    runs=[]
    def collect(provider,dataset,fetch,write):
        stamp=datetime.now(timezone.utc).isoformat()
        vault=store.response_vault
        if hasattr(provider,'client'):
            vault=vault or ResponseVault(store.path.parent/'raw-responses');store.response_vault=vault;provider.client.archive=vault
        event_start=len(vault.events) if vault else 0
        try:
            if provider.name=='baostock_free_history':
                with contextlib.redirect_stdout(io.StringIO()):rows=fetch(provider)
            else:rows=fetch(provider)
            if not rows:raise ValueError('No rows returned')
            count=write(rows);status='partial' if any(getattr(r,'quality','').endswith('needs_review')
                or getattr(r,'dataset','')=='issuer_announcement_audit' and r.value.get('status')!='complete_catalogue_window'
                or getattr(r,'dataset','')=='issuer_document_gap' for r in rows) else 'ok'
            store.record_run(provider.name,dataset,stamp,status,count,details={'response_receipts':vault.events[event_start:] if vault else []})
            runs.append({'provider':provider.name,'dataset':dataset,'status':status,'rows':count});return rows
        except Exception as error:
            from .http import redact_error
            message=redact_error(str(error))
            if vault:
                for event in list(vault.events[event_start:]):
                    if event.get('status') in {'http_ok','cache_hit'}:vault.reject(event,'Focused stock operation failed validation')
            store.record_run(provider.name,dataset,stamp,'failed',0,error=message,details={'response_receipts':vault.events[event_start:] if vault else []})
            runs.append({'provider':provider.name,'dataset':dataset,'status':'failed','error':message});return []
    def write_quotes(rows):
        count=store.upsert_quotes(rows);store.upsert_indicators(quote_indicator_rows(rows));return count
    def write_bars(rows):
        count=store.upsert_bars(rows);store.upsert_indicators(indicator_rows_grouped(rows));return count
    collect(TencentProvider(),'stock_research_quote:'+symbol,lambda p:p.fetch_quotes([symbol]),write_quotes)
    bars=collect(BaoStockProvider(),'stock_research_daily:'+symbol,
        lambda p:p.fetch_bars(symbol,start_date=start,end_date=day,adjustment='none'),write_bars)
    if not bars:
        bars=collect(TencentHistoryProvider(),'stock_research_daily_fallback:'+symbol,
            lambda p:p.fetch_bars(symbol,start_date=start,end_date=day,adjustment='none',count=640),write_bars)
    if not bars:raise ValueError('No complete daily source succeeded')
    collect(BaoStockProvider(),'stock_research_corporate_actions:'+symbol,
        lambda p:p.fetch_corporate_actions(symbol,start_date=start,end_date=day),store.upsert_observations)
    collect(BaoStockProvider(),'stock_research_valuation:'+symbol,
        lambda p:p.fetch_daily_metrics(symbol,start_date=(datetime.fromisoformat(day)-timedelta(days=45)).date().isoformat(),end_date=day),store.upsert_observations)
    collect(TencentIntradayProvider(),'stock_research_minutes:'+symbol,
        lambda p:p.fetch_bars(symbol,interval='5m',count=240),write_bars)
    collect(EastmoneyProvider(),'stock_research_vendor_flow:'+symbol,
        lambda p:p.fetch_stock_flow(symbol,interval='1d'),store.upsert_observations)
    now=datetime.now(SHANGHAI);year=now.year;quarter=(now.month-1)//3
    if quarter==0:year-=1;quarter=4
    for _ in range(2):
        financials=collect(BaoStockProvider(),f'stock_research_financials:{symbol}:{year}Q{quarter}',
            lambda p,year=year,quarter=quarter:p.fetch_financials(symbol,year=year,quarter=quarter),store.upsert_observations)
        if financials:break
        quarter-=1
        if quarter==0:year-=1;quarter=4
    if registry_path:
        registry=json.loads(Path(registry_path).read_text(encoding='utf-8-sig'))
        reports=[r for r in registry.get('reports',{}).values() if r['identity']==symbol and r['publication_date']<=now.date().isoformat()]
        if reports:
            report=max(reports,key=lambda r:r['period_end'])
            collect(IssuerFinancialProvider(registry_path,store.path.parent/'documents'),'stock_research_primary:'+symbol,
                lambda p:p.fetch_evidence(symbol,report['period_end']),store.upsert_observations)
    event_provider=CninfoAnnouncementsProvider(store.path.parent/'issuer-announcements')
    def fetch_event_rows(p):
        rows,audit=p.fetch_catalogue(symbol,start_date=f'{now.year}-01-01',end_date=now.date().isoformat())
        output=[*rows,audit]
        # Retrieve recent material documents; catalogue titles never grant content verification.
        selected,selection=select_material_documents(rows)
        audit.value['material_document_selection']=selection
        for row in {r.value['announcement_id']:r for r in selected}.values():
            try:output.append(p.fetch_document(row))
            except Exception as error:
                from .models import Observation
                from .http import redact_error
                output.append(Observation(p.name,'issuer_document_gap',row.identity,datetime.now(timezone.utc).isoformat(),
                    {'symbol':symbol,'announcement_id':row.value['announcement_id'],'title':row.value['title'],
                     'error':redact_error(str(error))},quality='unavailable',source_url=row.source_url,
                    source_receipts=row.source_receipts))
        return output
    def write_events(rows):
        count=store.upsert_observations(rows)
        if registry_path:
            event_registry=Path(registry_path).parent/'issuer-event-reviews.json'
            if event_registry.exists():store.upsert_observations(review_issuer_events(store,symbol,event_registry))
        return count
    collect(event_provider,'stock_research_announcements:'+symbol,fetch_event_rows,write_events)
    return bars,runs

def entry_scenarios(context,forecast):
    if context['state']!='measured':return {'status':'insufficient_history','scenarios':[]}
    atr=context['atr14'];support=context['support_previous20'];resistance=context['resistance_previous20']
    if not atr or support<=0 or resistance<=support:return {'status':'levels_unusable','scenarios':[]}
    scenarios=[
            {'name':'突破确认','entry_condition':f'后续完整日线收盘高于 {resistance:.2f}，并检查量能和行业同步性',
             'level':resistance,'invalidation_reference':resistance-2*atr,
             'execution':'最早下一可交易时点复核；不假定按触发日收盘成交'},
            {'name':'等待或撤销','condition':'跌破前20根低点、催化失效，或已上涨但量价与行业证据不支持',
             'level':support}]
    if context['close']>=support and support>atr:
        scenarios.insert(1,{'name':'回踩观察','entry_zone':[max(support,context['close']-atr),context['close']],
             'entry_condition':'回踩后价格止跌、MACD走弱停止，并有基本面/事件证据支持',
             'invalidation_reference':support-atr})
    return {'status':'technical_conditions_for_review','final_investment_decision_complete':False,
        'price_basis':'unadjusted','currency':'CNY','personal_position_size_verified':False,
        'scenarios':scenarios,
        'sizing_formula':'风险预算金额 / (预计成交价 - 失效参考价)，再检查计划资金、交易单位和跳空情景',
        'scope':'Explicit chart-based review levels; not a verified entry strategy or completed portfolio recommendation'}

def constructive_review(context,forecast,finance,relative,*,current):
    supporting=[];counter=[]
    if context.get('trend')=='upward_trend':supporting.append('价格处于EMA20/60定义的上行趋势')
    elif context.get('trend')=='downward_trend':counter.append('EMA20低于EMA60且继续下降，趋势证据不支持立即追买')
    if context.get('macd_histogram_change',0)>0:supporting.append('MACD柱较上一完整日线改善')
    elif context.get('macd_histogram_change',0)<0:counter.append('MACD柱较上一完整日线走弱')
    for comparison in relative:
        if comparison['window_daily_bars']==20:
            phrase=f"20根日线相对沪深300表现 {comparison['relative_return']:+.2%}（{comparison['benchmark_provider']}，日期对齐）"
            (supporting if comparison['relative_return']>0 else counter).append(phrase)
    primary=finance['financial_coverage']['primary_fields']
    for name in ('operating_revenue','net_profit_parent'):
        matches=[f for f in primary if f['name']==name and f['usable'] and f.get('prior_reported_decimal')]
        if matches:
            field=max(matches,key=lambda f:f['period_end']);previous=float(field['prior_reported_decimal'])
            if previous>0:
                change=field['value']/previous-1
                phrase=f"{field['period_end']} {'营业收入' if name=='operating_revenue' else '归母净利润'}对登记比较期变化 {change:+.2%}，范围为{field['period_kind']}"
                (supporting if change>0 else counter).append(phrase)
    if not any(f['usable'] for f in primary):counter.append('尚未取得可用的原报表财务字段，财务改善不能由价格走势替代')
    if not forecast['latest'].get('probability_publication_allowed'):counter.append('历史类比模型尚未通过本次概率发布门槛，不能把样本上涨比例当成确定性')
    if not current:counter.append('日线未覆盖当前已完成交易日')
    counter.append('最新公告与具体催化尚未完成核对，技术图形不足以完成投资决策')
    return {'supporting_case':supporting,'strongest_countercase':counter,'recommendation_stage':'wait_for_completed_due_diligence',
        'reason_for_waiting':'价格/模型条件是研究线索；结合决定本轮判断的公司、行业与事件证据形成独立意见。个人预算用于金额，策略验证用于概率或优势的宣称，不作为推迟市场判断的通用前提',
        'alternatives':[{'choice':'继续观察当前标的','condition':'突破/回踩条件出现且反证得到解释'},
                        {'choice':'比较沪深300或相关行业的可投资表达','condition':'当标的持续落后或公司特有风险较大时，另做具体产品尽调'},
                        {'choice':'暂不新增风险敞口','condition':'核心证据、时机或风险预算仍不支持行动'}],
        'user_preference_used_to_increase_confidence':False,'personal_position_loaded':False}

def create_stock_research(store,symbol,directory,*,collect=True,lookback_years=5,horizon=20,provider=None,registry_path=None,
                          position_state='unknown',risk_budget_CNY=None):
    target=Path(directory).resolve()
    if target.exists() and any(target.iterdir()):raise ValueError('Use a new stock research directory')
    target.mkdir(parents=True,exist_ok=True);runs=[]
    if collect:
        bars,runs=collect_stock_inputs(store,symbol,lookback_years=lookback_years,registry_path=registry_path)
    else:
        bars=store.get_bars(symbol,'1d',provider=provider,price_basis='unadjusted',limit=5500)
        if len({b.provider for b in bars})>1:raise ValueError('Select an explicit daily provider for stored research')
    if not bars:raise ValueError('No daily bars for this stock')
    cutoff=datetime.now(timezone.utc).isoformat()
    if any(b.price_basis!='unadjusted' for b in bars):raise ValueError('Absolute stock review levels require unadjusted prices')
    closed=expected_closed_session()
    if closed is not None:bars=[b for b in bars if b.timestamp[:10]<=closed]
    if not bars:raise ValueError('No completed daily bars at the current cutoff')
    curves=technical_series(bars);context=technical_context(curves);forecast=chronological_forecast(curves,horizon=horizon)
    from .chips import create_chip_research
    try:
        chip_context=create_chip_research(store,symbol,target/'chips',collect=collect,end=closed or bars[-1].timestamp[:10])
    except Exception as exc:
        from .http import redact_error
        chip_context={'status':'unavailable','reason':redact_error(str(exc))}
    current=closed is not None and bars[-1].timestamp[:10]==closed
    if not current:
        forecast['latest']['published_up_probability']=None;forecast['latest']['probability_publication_allowed']=False
        forecast['evaluation']['probability_publication_allowed']=False
    quotes=store.get_quotes([symbol],as_of=cutoff);quote=max(quotes,key=lambda r:r['as_of']) if quotes else None
    name=quote.get('name',symbol) if quote else symbol
    finance=evidence_pack(store,symbol,question='valuation',window=20,as_of=cutoff)
    benchmark=store.get_bars('sh000300','1d',price_basis='unadjusted',limit=80,as_of=cutoff)
    benchmark_groups={}
    for b in benchmark:benchmark_groups.setdefault(b.provider,{})[b.timestamp[:10]]=b
    relative=[]
    for source,by_date in benchmark_groups.items():
        for window in (5,20,60):
            if len(bars)<=window:continue
            a,b=bars[-1],bars[-1-window];start=by_date.get(b.timestamp[:10]);end=by_date.get(a.timestamp[:10])
            if start and end and start.currency==end.currency==a.currency:
                relative.append({'window_daily_bars':window,'benchmark':'sh000300','benchmark_provider':source,
                    'stock_return':a.close/b.close-1,'benchmark_return':end.close/start.close-1,
                    'relative_return':a.close/b.close-end.close/start.close,
                    'start':b.timestamp,'end':a.timestamp,'source_series_not_merged':True})
    (target/'benchmark-inputs.json').write_text(json.dumps([asdict(b) for b in benchmark],ensure_ascii=False,sort_keys=True,allow_nan=False),encoding='utf-8')
    frozen=[asdict(b) for b in bars];encoded=json.dumps(frozen,ensure_ascii=False,sort_keys=True,allow_nan=False).encode()
    (target/'daily-inputs.json').write_bytes(encoded)
    software={}
    software_sources=[]
    for file in ('stock_research.py','stock_technicals.py','directional_forecast.py','stock_chart.py','stock_conditions.py','indicators.py','stock_decision.py','stock_execution.py','issuer_events.py'):
        path=Path(__file__).parent/file;software[file]=hashlib.sha256(path.read_bytes()).hexdigest()
        software_sources.append({'name':file,'sha256':software[file],
            'source_base64':base64.b64encode(path.read_bytes()).decode(),'source':path.read_text(encoding='utf-8')})
    (target/'calculator-sources.json').write_text(json.dumps(software_sources,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    condition_source={'symbol':symbol,'provider':bars[-1].provider,'interval':'1d','price_basis':'unadjusted','currency':bars[-1].currency}
    conditions=chart_condition_plan(context,condition_source)
    events=current_event_context(store,symbol,as_of=cutoff)
    documents=[r for r in store.get_observations('issuer_announcement_document',limit=1,as_of=cutoff)
               if r['value'].get('symbol')==symbol]
    catalogue=[r for r in store.get_observations('announcement_catalogue_entry',limit=1,as_of=cutoff)
               if r['value'].get('symbol')==symbol]
    decision=decide_stock(context,finance['financial_coverage'],events,symbol=symbol,current=current,
                          position_state=position_state,risk_budget_CNY=risk_budget_CNY)
    cash_events=[{**r['facts'],'event_id':r['announcement_id'],'source_url':r['source_url'],
                  'document_sha256':r['document_sha256']} for r in events['reviewed_events'] if r['event_type']=='cash_dividend']
    # Event-aware execution sample uses only the reviewed catalogue's declared year window.
    audit=events.get('catalogue_audit')
    execution_bars=[b for b in bars if audit and audit['start_date']<=b.timestamp[:10]<=audit['end_date']]
    warmup=[b for b in bars if execution_bars and b.timestamp<execution_bars[0].timestamp]
    execution=paper_stock_strategy(execution_bars,dividends=cash_events,warmup_bars=warmup) if len(execution_bars)>=80 else None
    result={'symbol':symbol,'name':name,'created_at':cutoff,'evidence_cutoff':cutoff,
        'source_session':bars[-1].timestamp,'expected_closed_session':closed,'daily_history_current':current,
        'daily_source':bars[-1].provider,'price_basis':'unadjusted','currency':bars[-1].currency,
        'daily_bars':len(bars),'input_sha256':hashlib.sha256(encoded).hexdigest(),'software_sha256':software,
        'forecast_parameters':{'horizon':horizon,'neighbours':15,'min_samples':15},
        'collection_runs':runs,'quote':quote,'technical_context':context,'directional_forecast':forecast,
        'chip_context':chip_context,
        'corporate_action_records':store.get_observations('corporate_adjustment_factors',symbol,limit=100,as_of=cutoff),
        'dividend_source_records':store.get_observations('corporate_dividend_record',symbol,limit=10,as_of=cutoff),
        'benchmark_comparisons':relative,'benchmark_inputs_file':'benchmark-inputs.json',
        'financial_coverage':finance['financial_coverage'],
        'valuation_missing':finance['missing'],'entry_scenarios':entry_scenarios(context,forecast),
        'constructive_review':constructive_review(context,forecast,finance,relative,current=current),
        'issuer_event_context':events,'primary_document_records':documents,'announcement_catalogue_records':catalogue,
        'investment_opinion':decision,'paper_execution_sample':execution,
        'chart_conditions':conditions,'chart_condition_review':evaluate_chart_conditions(conditions,curves,condition_source),
        'available_vendor_flows':store.get_observations('stock_order_size_flow_1d',symbol,limit=120,as_of=cutoff),
        'industry_classification':store.get_observations('industry_classification',symbol,limit=1,as_of=cutoff),
        'uncompleted_research':['latest_unregistered_report_discovery','primary_announcements_and_catalysts',
            'historical_strategy_cost_and_execution_validation','portfolio_context_and_final_action_decision'],
        'holdings_loaded':False,'research_state':'stock_data_and_forecast_stage','complete_stock_decision_verified':False}
    (target/'curves.json').write_text(json.dumps(curves,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (target/'stock-research.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    chart=render_stock_chart(curves,target/'chart.html',title=name+' '+symbol,provider=bars[-1].provider,
                             basis='unadjusted',currency=bars[-1].currency,volume_unit=bars[-1].volume_unit)
    labels={'up':'偏涨','down':'偏跌','range':'震荡'};latest=forecast['latest'];evaluation=forecast['evaluation']
    direction=labels.get(latest.get('direction'),'样本不足，暂未形成历史类比预测')
    trend={'upward_trend':'上行','downward_trend':'下行','mixed_or_range':'分歧或区间'}.get(context.get('trend'),'历史不足')
    probability=(f"模型估计上涨概率 {latest['published_up_probability']:.1%}" if latest.get('probability_publication_allowed') else '未达到上涨概率发布门槛')
    text=f'# {name}（{symbol}）研究\n\n数据截至 {bars[-1].timestamp}，来自 {bars[-1].provider}，未复权，{bars[-1].currency}。冻结了 {len(bars)} 根日线。\n\n[查看价格、BOLL、MACD和量能图](chart.html)\n\n'
    text+=f'动量补充：RSI14 {curves[-1]["rsi14"]}；KDJ(9,3,3) K {curves[-1]["kdj_k"]}、D {curves[-1]["kdj_d"]}、J {curves[-1]["kdj_j"]}。[曲线含KDJ与RSI](chart.html)。\n\n'
    if chip_context['status'] in {'estimated','historical_estimate'}:
        text+=f'[查看估算筹码分布](chips/chips.html)：截至 {chip_context["as_of"]}，{chip_context["price_basis"]}；估算平均成本 {chip_context["mean_cost"]:.2f}、获利比例 {chip_context["profit_fraction"]:.1%}，初始未知存量残留 {chip_context["unknown_initial_weight_fraction"]:.1%}。\n\n'
    text+=f'截至数据日的价格趋势为{trend}。历史类比模型对数据日后 {horizon} 根日线的方向判断为：**{direction}**。{probability}。\n\n'
    if not current:text+='日线未覆盖当前已完成交易日，本记录用于历史研究，尚不能作为当前入场判断。\n\n'
    if latest['status']=='estimated':
        text+=f"相似历史窗口 {latest['selected_samples']} 个，价格收益中位数 {latest['median_price_return']:.2%}；历史样本的10%与90%分位为 {latest['historical_return_p10']:.2%}、{latest['historical_return_p90']:.2%}。这些分位描述类比样本，不能直接当作未来置信区间。\n\n"
    text+=f"按时间顺序评估了 {evaluation['evaluations']} 个不重叠收益窗口。模型Brier为 {evaluation['brier']}，历史上涨频率基准为 {evaluation['past_frequency_baseline_brier']}；三组校准误差为 {evaluation['calibration_error_3bins']}。当前使用今日取得的历史价格版本；价格收益不包含分红再投资。\n\n"
    if context['state']=='measured':
        text+=f"前20根日线低点 {context['support_previous20']:.2f}、高点 {context['resistance_previous20']:.2f}，ATR14为 {context['atr14']:.2f}。这些是可观察的复核参考位。突破、回踩和撤销条件保存在研究记录中；基本面/催化、执行成本及个人仓位决策仍需接入。\n\n"
    text+='已核验的财务字段与未核验供应商字段分别保留。此阶段不把历史类比或图形条件升级为已经通过检验的建仓策略。\n'
    review=result['constructive_review']
    text+='\n支持当前研究的证据：\n\n'+''.join('- '+item+'\n' for item in review['supporting_case'])
    text+='\n需要面对的反证：\n\n'+''.join('- '+item+'\n' for item in review['strongest_countercase'])
    action_names={'avoid_new_entry':'当前不新增仓位','do_not_add':'当前不加仓','refresh_required':'先更新当前数据',
        'build_next_session_conditionally':'下一可交易时点符合条件时分批建仓','add_conditionally':'符合条件时分批加仓',
        'early_entry_watch':'提前跟踪，等待入场确认','hold_or_wait_pullback':'持有或等待回踩复核','wait_pullback':'等待回踩',
        'wait_for_confirmation':'等待证据确认'}
    action_names.update({'review_reduce':'复核降低现有风险敞口','wait_for_critical_review':'先核对重要风险公告'})
    action_names.update({'assess_early_entry':'比较提前分批进入与确认后进入','assess_hold_or_add':'判断持有或加仓的经济性',
        'assess_current_entry':'判断当前进入的经济性','independent_assessment_required':'完成独立方向和行动判断'})
    text+='\n本轮操作判断：**'+action_names[decision['action']]+'**。'+decision['reason']+'。\n'
    text+='\n公告与催化核对：\n\n'+''.join('- '+e['interpretation']+'（'+e['publication_date']+'）\n' for e in events['reviewed_events'])
    if execution:
        text+=f"\n执行场景覆盖 {execution['period_start']} 至 {execution['period_end']}，使用此前 {execution['warmup_daily_bars']} 根日线预热：信号在完整日线后形成，最早次日可交易开盘成交；包含T+1、100股交易单位、成本/滑点假设及已提供现金红利。成交 {execution['fills_count']} 笔，策略场景收益 {execution['strategy_result']['return']:.2%}，同标的持有场景 {execution['passive_same_stock']['return']:.2%}。这些是声明假设下的纸面结果，未确认真实队列成交或策略稳定优势。\n"
        if not execution['fills_count']:text+='\n本窗口没有策略成交，策略收益只是持有现金的结果，不能宣称预测优势。\n'
    text+='\n可执行的图形复核条件：\n\n'
    metric_names={'close':'完整日线收盘价','volume_ratio5':'当日量/前5日均量','close_change':'收盘价较上一日变化',
                  'macd_histogram_change':'MACD柱较上一日变化'}
    operators={'gt':'>','gte':'≥','lt':'<','lte':'≤'}
    for condition in conditions.get('conditions',[]):
        text+='- '+condition['name']+'：'+' 且 '.join(f"{metric_names[p['metric']]} {operators[p['operator']]} {p['threshold']:.4f}" for p in condition['predicates'])+'。\n'
    if conditions.get('conditions'):text+='\n下一复核点：'+conditions['conditions'][0]['predicates'][0]['next_review']+'。这些条件从下一完整日线起判断，满足图形条件后仍需完成对应的投资证据复核。\n'
    (target/'report.md').write_text(text,encoding='utf-8')
    sealed={file:hashlib.sha256((target/file).read_bytes()).hexdigest() for file in (
        'daily-inputs.json','benchmark-inputs.json','curves.json','stock-research.json','calculator-sources.json','chart.html','report.md')}
    (target/'artifact-seal.json').write_text(json.dumps({'schema_version':1,'files':sealed},indent=2)+'\n',encoding='utf-8')
    return {'status':'stock_data_and_forecast_stage','symbol':symbol,'daily_bars':len(bars),'horizon':horizon,
        'forecast_status':latest['status'],'direction':latest.get('direction'),'probability_publication_allowed':latest.get('probability_publication_allowed',False),
        'chronological_evaluations':evaluation['evaluations'],'report_path':str(target/'report.md'),'chart_path':chart,
        'complete_stock_decision_verified':False}

def verify_stock_research(directory):
    target=Path(directory).resolve();seal=json.loads((target/'artifact-seal.json').read_text(encoding='utf-8'))
    failures=[]
    for file,digest in seal['files'].items():
        if Path(file).name!=file:raise ValueError('Stock seal path is not a local artifact name')
        if hashlib.sha256((target/file).read_bytes()).hexdigest()!=digest:failures.append(file+':hash')
    if failures:return {'status':'failed','failures':failures,'live_database_used':False}
    result=json.loads((target/'stock-research.json').read_text(encoding='utf-8'))
    raw=(target/'daily-inputs.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=result['input_sha256']:failures.append('input_reference')
    sources=json.loads((target/'calculator-sources.json').read_text(encoding='utf-8'))
    for source in sources:
        if hashlib.sha256(base64.b64decode(source['source_base64'])).hexdigest()!=source['sha256']:failures.append('frozen_source:'+source['name'])
        if result['software_sha256'].get(source['name'])!=source['sha256']:failures.append('source_reference:'+source['name'])
    critical=['stock_technicals.py','directional_forecast.py','indicators.py']
    if 'investment_opinion' in result:critical.append('stock_decision.py')
    if result.get('paper_execution_sample') is not None:critical.append('stock_execution.py')
    mismatches=[name for name in critical if hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=result['software_sha256'][name]]
    if mismatches:return {'status':'calculator_version_mismatch','files':mismatches,'live_database_used':False}
    bars=[Bar(**row) for row in json.loads(raw)];curves=technical_series(bars)
    def canonical(value):return json.dumps(value,ensure_ascii=False,sort_keys=True,allow_nan=False,separators=(',',':'))
    if canonical(curves)!=canonical(json.loads((target/'curves.json').read_text(encoding='utf-8'))):failures.append('curves')
    if result.get('chip_context',{}).get('status') in {'estimated','historical_estimate'}:
        from .chips import verify_chip_research
        if verify_chip_research(target/'chips')['status']!='ok':failures.append('chip_context_replay')
        frozen_chips=json.loads((target/'chips/chips.json').read_text(encoding='utf-8'))
        for key,value in frozen_chips.items():
            if key!='distribution' and result['chip_context'].get(key)!=value:failures.append('chip_context:'+key)
    if canonical(technical_context(curves))!=canonical(result['technical_context']):failures.append('technical_context')
    forecast=chronological_forecast(curves,**result['forecast_parameters'])
    if not result['daily_history_current']:
        forecast['latest']['published_up_probability']=None;forecast['latest']['probability_publication_allowed']=False
        forecast['evaluation']['probability_publication_allowed']=False
    if canonical(forecast)!=canonical(result['directional_forecast']):failures.append('forecast')
    benchmark_checked=False
    if result.get('benchmark_inputs_file'):
        name=result['benchmark_inputs_file']
        if name!='benchmark-inputs.json' or name not in seal['files']:
            raise ValueError('Benchmark input must be a sealed local artifact')
        references=[Bar(**row) for row in json.loads((target/name).read_text(encoding='utf-8'))]
        groups={}
        for row in references:
            if row.symbol!='sh000300' or row.interval!='1d' or row.price_basis!='unadjusted':
                failures.append('benchmark_contract');continue
            groups.setdefault(row.provider,{})[row.timestamp[:10]]=row
        measured=[]
        for source,by_date in groups.items():
            for window in (5,20,60):
                if len(bars)<=window:continue
                a,b=bars[-1],bars[-1-window];start=by_date.get(b.timestamp[:10]);end=by_date.get(a.timestamp[:10])
                if start and end and start.currency==end.currency==a.currency:
                    measured.append({'window_daily_bars':window,'benchmark':'sh000300','benchmark_provider':source,
                        'stock_return':a.close/b.close-1,'benchmark_return':end.close/start.close-1,
                        'relative_return':a.close/b.close-end.close/start.close,
                        'start':b.timestamp,'end':a.timestamp,'source_series_not_merged':True})
        if canonical(measured)!=canonical(result['benchmark_comparisons']):failures.append('benchmark_comparisons')
        benchmark_checked=True
    decision_checked=False;execution_checked=False
    if 'investment_opinion' in result:
        opinion=result['investment_opinion']
        replay=decide_stock(technical_context(curves),result['financial_coverage'],result['issuer_event_context'],
            symbol=result['symbol'],current=result['daily_history_current'],position_state=opinion['position_state'],
            risk_budget_CNY=opinion['plan']['risk_budget_CNY'])
        if canonical(replay)!=canonical(opinion):failures.append('investment_opinion')
        decision_checked=True
    if result.get('paper_execution_sample') is not None:
        recorded=result['paper_execution_sample'];audit=result['issuer_event_context']['catalogue_audit']
        selected=[b for b in bars if audit['start_date']<=b.timestamp[:10]<=audit['end_date']]
        warmup=[b for b in bars if selected and b.timestamp<selected[0].timestamp]
        parameters=recorded['parameters']
        replay=paper_stock_strategy(selected,warmup_bars=warmup,dividends=recorded['dividend_events'],
            initial_cash=parameters['initial_simulation_cash_CNY'],lot_size=parameters['lot_size'],
            holding_bars=parameters['holding_daily_bars'],side_cost_fraction=parameters['side_cost_fraction'],
            slippage_fraction=parameters['slippage_fraction'],dividend_tax_fraction=parameters['dividend_tax_scenario_fraction'])
        if canonical(replay)!=canonical(recorded):failures.append('paper_execution_sample')
        execution_checked=True
    return {'status':'failed' if failures else 'ok','daily_rows':len(bars),'curve_field_comparisons':sum(len(row) for row in curves),
        'chronological_evaluations_checked':forecast['evaluation']['evaluations'],'failures':failures,
        'live_database_used':False,'archived_source_bytes_verified':len(sources),
        'benchmark_comparisons_replayed':benchmark_checked,
        'conditional_opinion_replayed':decision_checked,'paper_execution_replayed':execution_checked,
        'complete_stock_decision_verified':False}
