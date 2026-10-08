"""Route a focused stock request into the security's actual cash market."""
import json,re
from pathlib import Path
from .candidate_research import normalize_candidates,research_candidates
from .stock_research import create_stock_research,resolve_stock_identifier


def stock_route(value,market='auto'):
    if market not in {'auto','CN','HK','US'}:raise ValueError('Use auto, CN, HK or US stock market')
    identity=value.strip()
    prefix=re.fullmatch(r'(CN|HK|US):(.+)',identity,re.I)
    if prefix:
        named=prefix.group(1).upper()
        if market!='auto' and market!=named:raise ValueError('Stock market prefix and explicit market disagree')
        market=named;identity=prefix.group(2).strip()
    if market=='auto':
        if re.fullmatch(r'(?:sh|sz|bj)[.:]?\d{6}|\d{6}',identity,re.I):market='CN'
        elif re.fullmatch(r'\d{4,5}\.HK',identity,re.I):market='HK'
        elif re.fullmatch(r'[A-Z][A-Z0-9.\-]{0,14}',identity,re.I):market='US'
        else:market='CN'
    if market!='CN':
        if market=='HK' and re.fullmatch(r'\d{4,5}',identity):identity+='.HK'
        row=normalize_candidates([{'market':market,'kind':'stock','identity':identity,
                                   'selection_reason':'User requested independent research on this exact stock'}])[0]
        identity=row['identity']
    return market,identity


def research_stock_request(store,value,directory,*,market='auto',collect=True,lookback_years=5,
                           horizon=20,provider=None,registry_path=None,position_state='unknown',risk_budget_CNY=None):
    venue,identity=stock_route(value,market)
    if venue=='CN':
        return create_stock_research(store,resolve_stock_identifier(store,identity,allow_network=collect),directory,
            collect=collect,lookback_years=lookback_years,horizon=horizon,provider=provider,registry_path=registry_path,
            position_state=position_state,risk_budget_CNY=risk_budget_CNY)
    if provider is not None:raise ValueError('A domestic provider override does not apply to foreign stock research')
    if risk_budget_CNY is not None:raise ValueError('Foreign sizing requires native currency and a verified FX basis; do not apply the domestic CNY sizing option')
    if not 2<=lookback_years<=20 or not 1<=horizon<=250:raise ValueError('Use 2-20 history years and a 1-250 observation horizon')
    request={'market':venue,'kind':'stock','identity':identity,
             'selection_reason':'User requested independent research on this exact stock'}
    # Candidate collection already retains public HTTP receipts and the venue benchmark.
    result=research_candidates(store,[request],directory,collect=collect,lookback_days=lookback_years*366)
    target=result['results'][0]
    source_identity=None
    if target.get('status')=='candidate_price_evidence_ready':
        inputs=json.loads((Path(target['directory'])/'daily-inputs.json').read_text(encoding='utf-8'))
        metadata=inputs[-1]['raw'].get('metadata') or {}
        zone='America/New_York' if venue=='US' else 'Asia/Hong_Kong'
        if str(metadata.get('symbol','')).upper()!=identity or metadata.get('instrumentType')!='EQUITY' or metadata.get('exchangeTimezoneName')!=zone:
            raise ValueError('Native stock identity, equity kind and exchange timezone metadata remain unverified')
        source_identity={k:metadata.get(k) for k in ('symbol','longName','shortName','exchangeName','fullExchangeName','currency','instrumentType','exchangeTimezoneName')}
    packet={'identity':identity,'market':venue,'requested_horizon_observations':horizon,
        'price_result':target,'source_instrument_metadata':source_identity,'portfolio_used':False,'position_state':position_state,
        'final_investment_decision_complete':False,
        'primary_research_routes':(['company investor relations and SEC filings, with exact ticker/issuer identity',
            'US industry/market evidence and native USD plans'] if venue=='US' else
            ['HKEX issuer disclosures and company investor relations, with exact stock-code identity',
             'Hong Kong industry/market evidence and native currency/board-lot plans']),
        'remaining_research':['material earnings/cash flow, valuation and current event status',
            'industry evidence and strongest countercase','horizon-specific independent action and review plan'],
        'domestic_execution_rules_applied':False}
    (Path(directory)/'stock-request.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2),encoding='utf-8')
    return packet
