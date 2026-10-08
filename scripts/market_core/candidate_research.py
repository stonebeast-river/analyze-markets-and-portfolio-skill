"""Continue an analyst-selected shortlist into each instrument's own price evidence."""
import hashlib
import json
import re
from dataclasses import asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .http import redact_error
from .providers import BaoStockProvider, TencentProvider
from .providers.tencent_history import TencentHistoryProvider
from .providers.yahoo import YahooProvider
from .symbols import normalize_cn_symbol, is_cn_exchange_fund
from .task_health import completed_cash_session
from .stock_technicals import technical_series, technical_context
from .stock_chart import render_stock_chart
from .sector_windows import compare_price_windows
from .fund_research import create_fund_research, resolve_fund_identifier


def normalize_candidates(records):
    if not isinstance(records,list) or not 1<=len(records)<=12:
        raise ValueError('Use one to twelve independently selected candidates')
    result=[];seen=set()
    for row in records:
        if not isinstance(row,dict) or row.get('market') not in {'CN','HK','US'}:
            raise ValueError('Each candidate needs a supported market')
        kind=row.get('kind');identity=str(row.get('identity','')).strip()
        if kind not in {'stock','ETF','off_exchange_fund'}:
            raise ValueError('Candidate kind must be stock, ETF or off_exchange_fund')
        if kind=='off_exchange_fund':
            if row['market']!='CN' or not re.fullmatch(r'\d{6}',identity):
                raise ValueError('Off-exchange share needs its exact six-digit issuer code')
        elif row['market']=='CN':
            identity=normalize_cn_symbol(identity,stock_only=kind=='stock')
            if kind=='ETF' and not is_cn_exchange_fund(identity):
                raise ValueError('CN ETF identity is not an exchange-traded fund')
        elif row['market']=='HK':
            if not re.fullmatch(r'\d{4,5}\.HK',identity.upper()):
                raise ValueError('Use a native Hong Kong chart ticker')
            identity=str(int(identity.split('.')[0])).zfill(4)+'.HK'
        else:
            identity=identity.upper()
            if not re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',identity):
                raise ValueError('Use a native US equity/ETF ticker')
        key=(row['market'],identity)
        if key in seen:raise ValueError('Duplicate candidate identity')
        if not isinstance(row.get('selection_reason'),str) or not row['selection_reason'].strip():
            raise ValueError('Retain the independent selection reason')
        seen.add(key);result.append({**row,'identity':identity})
    return result


def collect_prices(store,row,*,lookback_days=800):
    """Public source failures remain visible; no portfolio is used in this route."""
    identity=row['identity'];runs=[]
    closed=completed_cash_session(row['market']+'_CASH',datetime.now(timezone.utc).isoformat())
    if not closed:raise ValueError('Extend the candidate venue calendar before collecting daily evidence')
    start=(datetime.fromisoformat(closed)-timedelta(days=lookback_days)).date().isoformat()
    def run(provider,label,fetch,write):
        client=getattr(provider,'client',None)
        if client is not None:client.archive=store.response_vault;client.retries=0
        began=datetime.now(timezone.utc).isoformat()
        try:
            rows=fetch();count=write(rows)
            store.record_run(provider.name,label,began,'ok',count)
            runs.append({'source':provider.name,'task':label,'status':'ok','records':count})
            return rows
        except Exception as error:
            message=redact_error(str(error));store.record_run(provider.name,label,began,'failed',0,error=message)
            runs.append({'source':provider.name,'task':label,'status':'failed','error':message})
            return None
    if row['market']=='CN':
        quote= TencentProvider()
        run(quote,'candidate_quote:'+identity,lambda:quote.fetch_quotes([identity]),store.upsert_quotes)
        history=BaoStockProvider()
        bars=run(history,'candidate_daily:'+identity,
                 lambda:history.fetch_bars(identity,start_date=start,end_date=closed,adjustment='none'),store.upsert_bars)
        if not bars:
            history=TencentHistoryProvider()
            bars=run(history,'candidate_daily_fallback:'+identity,
                     lambda:history.fetch_bars(identity,start_date=start,end_date=closed,adjustment='none'),store.upsert_bars)
        if bars:
            run(history,'candidate_benchmark:sh000300',
                lambda:history.fetch_bars('sh000300',start_date=start,end_date=closed,adjustment='none'),store.upsert_bars)
        if bars and row['kind']=='stock':
            metrics=BaoStockProvider()
            run(metrics,'candidate_daily_metrics:'+identity,
                lambda:metrics.fetch_daily_metrics(identity,start_date=start,end_date=closed),store.upsert_observations)
    else:
        provider=YahooProvider()
        def write(payload):
            bars,obs=payload
            expected='ETF' if row['kind']=='ETF' else 'EQUITY'
            if any(b.raw.get('instrument_type')!=expected for b in bars if b.symbol==identity):
                raise ValueError('Issuer instrument kind disagrees with candidate kind')
            return store.upsert_bars(bars)+store.upsert_observations(obs)
        symbols=list(dict.fromkeys([identity,'SPY' if row['market']=='US' else '^HSI']))
        run(provider,'candidate_daily:'+identity,
            lambda:provider.fetch_evidence(symbols,lookback_days=lookback_days),write)
    return runs


def price_packet(store,row,root,cutoff):
    identity=row['identity'];market=row['market'];closed=completed_cash_session(market+'_CASH',cutoff)
    requested_currency=row.get('currency') or ('CNY' if market=='CN' else None)
    bars=store.get_bars(identity,'1d',limit=1800,as_of=cutoff)
    groups={}
    for b in bars:
        if b.currency in {'','unknown'} or (requested_currency and b.currency!=requested_currency) or not closed or b.timestamp[:10]>closed:continue
        if b.price_basis not in {'unadjusted','provider_split_adjusted_close'}:continue
        if market!='CN' and b.session!='completed_regular_session':continue
        source_kind=b.raw.get('instrument_type')
        if source_kind is not None and source_kind!=('ETF' if row['kind']=='ETF' else 'EQUITY'):
            continue
        groups.setdefault((b.provider,b.price_basis,b.volume_unit,b.currency),[]).append(b)
    selected=max(groups.values(),key=lambda x:(x[-1].timestamp,len(x))) if groups else []
    if len(selected)<60:raise ValueError('At least60 native-currency completed daily bars required')
    currency=selected[-1].currency
    curves=technical_series(selected);context=technical_context(curves)
    benchmark={'CN':'sh000300','US':'SPY','HK':'^HSI'}[market]
    base=store.get_bars(benchmark,'1d',provider=selected[-1].provider,
                        price_basis=selected[-1].price_basis,limit=1800,as_of=cutoff)
    base=[b for b in base if b.timestamp[:10]<=closed and b.currency==currency]
    comparison=compare_price_windows(selected,base)
    quotes=store.get_quotes([identity],as_of=cutoff) if market=='CN' else []
    source={'provider':selected[-1].provider,'price_basis':selected[-1].price_basis,'currency':currency,
            'volume_unit':selected[-1].volume_unit,'market':market,'expected_completed_session':closed,
            'source_last_session':selected[-1].timestamp,'current_completed_session_covered':selected[-1].timestamp[:10]==closed}
    for name,value in [('daily-inputs.json',[asdict(b) for b in selected]),('benchmark-inputs.json',[asdict(b) for b in base]),('curves.json',curves)]:
        (root/name).write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8')
    render_stock_chart(curves,root/'chart.html',title=identity,provider=source['provider'],
                       basis=source['price_basis'],currency=currency,volume_unit=source['volume_unit'])
    result={'candidate':row,'source':source,'daily_bars':len(selected),'technical_context':context,
            'regional_broad_benchmark_comparison':comparison,'quotes':quotes,
            'decision_core_followups':['target company earnings/valuation/events and strongest countercase',
                'ETF/product exact holdings, fees and investability when applicable',
                'native-currency entry/addition/invalidation and venue review times',
                'independent final judgment before personal sizing'],
            'fundamental_due_diligence_complete':False,'final_investment_decision_complete':False,
            'portfolio_used':False,'total_return_verified':False}
    (root/'candidate-evidence.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    seals={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.iterdir() if p.is_file()}
    (root/'artifact-seal.json').write_text(json.dumps(seals,indent=2),encoding='utf-8')
    return {'identity':identity,'status':'candidate_price_evidence_ready','directory':str(root),
            'source':source,'daily_bars':len(selected),'final_investment_decision_complete':False}


def research_candidates(store,records,directory,*,collect=True,lookback_days=800):
    selected=normalize_candidates(records);root=Path(directory).resolve()
    if root.exists() and any(root.iterdir()):raise ValueError('Use a new candidate research directory')
    root.mkdir(parents=True,exist_ok=True);results=[]
    for i,row in enumerate(selected,1):
        folder=root/(str(i).zfill(2)+'-'+row['identity']);folder.mkdir()
        runs=[]
        try:
            if row['kind']=='off_exchange_fund':
                code=resolve_fund_identifier(store,row['identity'],allow_network=collect)
                result=create_fund_research(store,code,folder,collect=collect,registry_path=row.get('registry_path'))
            else:
                if collect:runs=collect_prices(store,row,lookback_days=lookback_days)
                result=price_packet(store,row,folder,datetime.now(timezone.utc).isoformat())
            results.append({'candidate':row,'collection_runs':runs,**result})
        except Exception as error:
            results.append({'candidate':row,'collection_runs':runs,'status':'candidate_evidence_incomplete',
                            'error':redact_error(str(error)),'directory':str(folder)})
    (root/'candidate-research.json').write_text(json.dumps({'candidates':results,'portfolio_used':False,
        'selection':'analyst independent shortlist; prices do not validate its investment thesis',
        'final_investment_decisions_complete':False},ensure_ascii=False,indent=2),encoding='utf-8')
    return {'directory':str(root),'results':results,'portfolio_used':False,'final_investment_decisions_complete':False}
