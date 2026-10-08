"""Freeze a holdings-independent market scan and native-currency follow-up evidence."""
import json,hashlib
from pathlib import Path
from dataclasses import asdict
from datetime import datetime,timezone
from .market_scan import scan_market
from .sector_windows import sector_price_scan,compare_price_windows
from .providers.yahoo import YahooProvider
from .http import redact_error
from .task_health import completed_cash_session
from .conventions import parse_time


def prepare_opportunity_research(store,config,directory,*,refresh_global=False,as_of=None):
    if as_of and datetime.fromisoformat(as_of.replace('Z','+00:00')).tzinfo is None:
        raise ValueError('as_of requires a timezone')
    cutoff=parse_time(as_of).isoformat() if as_of else datetime.now(timezone.utc).isoformat()
    if refresh_global and as_of is not None:
        raise ValueError('Historical cutoff research must reuse frozen inputs without live refresh')
    root=Path(directory).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('Use a new opportunity research directory')
    root.mkdir(parents=True,exist_ok=True);runs=[]
    # These are market-universe proxies, never derived from a user's portfolio.
    global_universe=['SPY','XLK','XLF','XLE','XLY','XLP','XLI','XLV','XLU','XLB','XLRE','XLC','^HSI','2800.HK','3033.HK']
    if refresh_global:
        provider=YahooProvider();provider.client.archive=store.response_vault;provider.client.retries=0
        for identity in global_universe:
            started=datetime.now(timezone.utc).isoformat()
            try:
                bars,obs=provider.fetch_evidence([identity],lookback_days=500)
                count=store.upsert_bars(bars)+store.upsert_observations(obs)
                store.record_run(provider.name,'opportunity_market:'+identity,started,'ok',count)
                runs.append({'identity':identity,'status':'ok','records':count})
            except Exception as error:
                store.record_run(provider.name,'opportunity_market:'+identity,started,'failed',0,error=redact_error(str(error)))
                runs.append({'identity':identity,'status':'failed','error':redact_error(str(error))})
    if refresh_global:cutoff=datetime.now(timezone.utc).isoformat()
    broad=scan_market(store,as_of=cutoff,limit=20,include_inputs=True)
    sectors=sector_price_scan(store,config,as_of=cutoff);HK=[];global_inputs={};session_audit={}
    for identity in global_universe:
        rows=store.get_bars(identity,'1d',provider='yahoo_public_chart',price_basis='provider_split_adjusted_close',limit=180,as_of=cutoff)
        market='HK_CASH' if identity.endswith('.HK') or identity=='^HSI' else 'US_CASH'
        closed=completed_cash_session(market,cutoff)
        excluded=[r.timestamp for r in rows if closed and r.timestamp[:10]>closed]
        if closed:rows=[r for r in rows if r.timestamp[:10]<=closed]
        session_audit[identity]={'market':market,'expected_completed_session':closed,
            'source_last_session':rows[-1].timestamp[:10] if rows else None,
            'completed_session_aligned':bool(rows and closed and rows[-1].timestamp[:10]==closed),
            'calendar_coverage_verified':closed is not None,'excluded_uncompleted_bars':excluded}
        global_inputs[identity]=[asdict(r) for r in rows]
    from .models import Bar
    base=[Bar(**r) for r in global_inputs['^HSI']]
    for identity in ('2800.HK','3033.HK'):
        rows=[Bar(**r) for r in global_inputs[identity]]
        HK.append({'scope':'bounded_Hong_Kong_broad_and_technology_proxies',**compare_price_windows(rows,base)})
    macro=store.get_observations('macro_series',limit=1,as_of=cutoff)
    result={'created_at':cutoff,'status':'opportunity_research_evidence_stage','collection_runs':runs,
        'mainland_breadth_and_anomaly_questions':broad,'configured_sector_price_windows':sectors,
        'Hong_Kong_bounded_proxy_windows':HK,'macro_observations':macro,'global_session_audit':session_audit,
        'discovery_is_independent_of_portfolio':True,'personal_portfolio_used':False,
        'market_scope':'mainland supplier quote census, configured CN/US sector proxies, bounded HK proxies',
        'full_Hong_Kong_sector_scan_verified':False,'prices_are_not_fundamental_confirmation':True,
        'required_continuation':['derive economic hypotheses from material divergence',
            'find and research exact securities/products without another user choice',
            'verify target-matched fundamental/valuation/policy/exposure evidence',
            'compare strongest countercase, credible alternative and waiting',
            'produce horizon-specific ranked entry/addition/invalidation/review recommendations'],
        'complete_autonomous_recommendation_verified':False}
    (root/'opportunity-inputs.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'global-price-inputs.json').write_text(json.dumps(global_inputs,ensure_ascii=False,indent=2),encoding='utf-8')
    (root/'research-tasks.md').write_text('# 自主机会研究材料\n\n扫描独立于用户持仓。数据窗口和实际范围见opportunity-inputs.json。\n\n'+
        '完成下列研究后再交付研报：\n\n'+''.join('- '+x+'\n' for x in result['required_continuation'])+
        '\n板块涨幅、价格异常和研究标签不是最终投资意见。用新出现的经营/估值/政策证据决定排序，缺乏合格机会时明确等待。\n',encoding='utf-8')
    seal={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    (root/'artifact-seal.json').write_text(json.dumps(seal,indent=2),encoding='utf-8')
    return {'status':result['status'],'directory':str(root),'mainland_scan_status':broad['status'],
        'sector_proxy_rows':len(sectors['rows']),'global_price_histories':sum(bool(x) for x in global_inputs.values()),
        'personal_portfolio_used':False,'complete_autonomous_recommendation_verified':False}
