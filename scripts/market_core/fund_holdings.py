"""Disclosed equity-report snapshots and denominator-aware feeder/ETF look-through."""
import math,re,unicodedata
from decimal import Decimal
from datetime import date,datetime,timezone
from .symbols import normalize_cn_symbol


def number(text):
    return Decimal(text.replace(',',''))


def parse_equity_report(pages,*,fund_code,expected_name,publication_date,source_url,document_sha256):
    """Parse this supported Chinese report layout; never claim live portfolio reconstruction."""
    if not re.fullmatch(r'\d{6}',fund_code) or not expected_name or not re.fullmatch(r'[0-9a-f]{64}',document_sha256):
        raise ValueError('Exact fund code/name and document SHA required')
    compact=lambda s:re.sub(r'\s+','',unicodedata.normalize('NFKC',s))
    cover=compact(pages[0]);name=compact(expected_name)
    if not cover.startswith(name) or not re.search(r'\d{4}年(?:中期|年度)报告',cover):
        raise ValueError('Report cover does not establish exact fund family and supported report kind')
    dated=re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})日',cover)
    if not dated:raise ValueError('Report-date cover missing')
    report_date=date(*map(int,dated.groups())).isoformat()
    if date.fromisoformat(publication_date)<date.fromisoformat(report_date):raise ValueError('Publication precedes report date')
    lines=[(i+1,unicodedata.normalize('NFKC',line).strip()) for i,p in enumerate(pages) for line in p.splitlines() if line.strip()]
    def section(start,end):
        a=next((i for i,(_,line) in enumerate(lines) if re.fullmatch(start,line)),None)
        if a is None:raise ValueError('Supported report section missing: '+start)
        b=next((i for i in range(a+1,len(lines)) if re.match(end,lines[i][1])),len(lines))
        return lines[a:b]
    own=section(r'2\.1\s*基金基本情况',r'2\.1\.1|2\.2\s*基金产品说明')
    own_text=unicodedata.normalize('NFKC','\n'.join(x[1] for x in own))
    if not re.search(r'(?<!\d)'+fund_code+r'(?!\d)',own_text):raise ValueError('Requested share identity absent from own fund table')
    balance=section(r'6\.1\s*资产负债表',r'6\.2\s*利润表')
    balance_text=compact(''.join(x[1] for x in balance))
    if ('单位:人民币元' not in balance_text or '本期末'+dated.group(0) not in balance_text
            or '上年度末' not in balance_text or balance_text.index('本期末'+dated.group(0))>balance_text.index('上年度末')):
        raise ValueError('Current balance column or CNY unit not established')
    def balance_value(label):
        matches=[(p,line,re.fullmatch(label+r'\s+([\d,]+\.\d{2})\s+([\d,]+\.\d{2})',line)) for p,line in balance]
        matches=[(p,line,m) for p,line,m in matches if m]
        if len(matches)!=1:raise ValueError('Balance row is not unique: '+label)
        p,line,m=matches[0];return number(m.group(1)),{'page':p,'source_text':line,'column':'本期末'}
    nav,nav_source=balance_value('净资产合计');assets,asset_source=balance_value('资产总计')
    if nav<=0 or assets<=0:raise ValueError('Positive denominators required')
    share_match=re.search(r'基金份额总额([\d,]+(?:\.\d+)?)份',balance_text)
    total_shares=float(number(share_match.group(1))) if share_match else None
    unit_match=re.search(r'基金份额净值([\d.]+)元',balance_text) if '联接基金' not in name else None
    reported_unit_nav=float(number(unit_match.group(1))) if unit_match else None
    asset_section=section(r'7\.1\s*期末基金资产组合情况',r'7\.2\s*报告期末按行业分类')
    if '占基金总资产的比例' not in compact(''.join(x[1] for x in asset_section)):
        raise ValueError('Asset composition denominator missing')
    asset_rows=[]
    for p,line in asset_section:
        m=re.fullmatch(r'([1-9])\s+(.+?)\s+([\d,]+\.\d{2}|-)\s+([\d.]+|-)',line)
        if not m:continue
        amount=Decimal(0) if m.group(3)=='-' else number(m.group(3))
        row={'name':m.group(2),'value_CNY':float(amount),'weight_of_net_assets':float(amount/nav),
             'reported_percent':None if m.group(4)=='-' else float(m.group(4)),
             'reported_denominator':'total_assets','page':p,'source_text':line}
        if row['name']=='合计':
            if amount!=assets:raise ValueError('Composition total differs from balance assets')
        else:asset_rows.append(row)
    if len(asset_rows)!=8 or sum(number(str(x['value_CNY'])) for x in asset_rows)!=assets:
        raise ValueError('Asset composition rows do not reconcile')
    equity=next(number(str(x['value_CNY'])) for x in asset_rows if x['name']=='权益投资')
    industry_section=section(r'7\.2\.1\s*报告期末按行业分类的境内股票投资组合',r'7\.2\.2|7\.3\s*期末按公允价值')
    if '占基金资产净值比例' not in compact(''.join(x[1] for x in industry_section)):
        raise ValueError('Industry net-assets denominator missing')
    industries=[]
    for p,line in industry_section:
        m=re.fullmatch(r'([A-S])\s+(.+?)\s+([\d,]+\.\d{2}|-)\s+([\d.]+|-)',line)
        if m:
            amount=Decimal(0) if m.group(3)=='-' else number(m.group(3))
            industries.append({'code':m.group(1),'name':m.group(2),'value_CNY':float(amount),
                'weight_of_net_assets':float(amount/nav),'reported_percent_NAV':None if m.group(4)=='-' else float(m.group(4)),
                'classification':'report_industry_categories','page':p,'source_text':line})
    totals=[(p,line,re.fullmatch(r'合计\s+([\d,]+\.\d{2})\s+([\d.]+)',line)) for p,line in industry_section]
    totals=[(p,line,m) for p,line,m in totals if m]
    if len(totals)!=1:raise ValueError('Industry total missing or ambiguous')
    industry_total=number(totals[0][2].group(1))
    if sorted(x['code'] for x in industries)!=list('ABCDEFGHIJKLMNOPQRS') or sum(number(str(x['value_CNY'])) for x in industries)!=industry_total:
        raise ValueError('Domestic industry rows are incomplete or unmatched to their own total')
    stock_section=section(r'7\.3\.1\s*期末按公允价值占基金资产净值比例大小排序的所有股票投资明细',r'7\.4\s*报告期内股票投资组合')
    if not all(word in compact(''.join(x[1] for x in stock_section[:12])) for word in ('数量(股)','公允价值','占基金资产净值比例')):
        raise ValueError('Stock table header/unit/denominator missing')
    stocks=[]
    for p,line in stock_section:
        m=re.fullmatch(r'(\d+)\s+(\d{6})\s+(.+?)\s+([\d,]+(?:\.\d+)?)\s+([\d,]+\.\d{2})\s+([\d.]+)',line)
        if not m:continue
        amount=number(m.group(5));reported=number(m.group(6));weight=amount/nav
        if abs(weight*100-reported)>Decimal('.0051'):raise ValueError('Stock percentage disagrees with current NAV denominator')
        stock_code=m.group(2)
        identity=normalize_cn_symbol('sz'+stock_code if stock_code.startswith('000') else stock_code,stock_only=True)
        stocks.append({'rank':int(m.group(1)),'identity':identity,
            'name':m.group(3),'quantity_shares':float(number(m.group(4))),'value_CNY':float(amount),
            'weight_of_net_assets':float(weight),'reported_percent_NAV':float(reported),
            'region':'CN_listed','valuation_currency':'CNY','page':p,'source_text':line})
    if not stocks or [r['rank'] for r in stocks]!=list(range(1,len(stocks)+1)) or len({r['identity'] for r in stocks})!=len(stocks):
        raise ValueError('Stock detail has missing/duplicate ranks or identities')
    stock_sum=sum(number(str(r['value_CNY'])) for r in stocks);reconciled=abs(stock_sum-industry_total)<=Decimal('.02')
    targets=[]
    if '联接基金' in name:
        target_section=section(r'2\.1\.1\s*目标基金基本情况',r'2\.1\.2')
        target_text=compact(''.join(x[1] for x in target_section));match=re.search(r'基金主代码(\d{6})(?!\d)',target_text)
        if not match:raise ValueError('Feeder target identity missing')
        target_code=match.group(1)
        amount=next(number(str(x['value_CNY'])) for x in asset_rows if x['name']=='基金投资')
        fund_section=section(r'7\.12\.1\s*报告期末按公允价值占基金资产净值比例大小排序的所有基金投资明细',r'7\.12\.2|7\.13')
        fund_text=compact(''.join(x[1] for x in fund_section))
        if fund_text.count(format(amount,',.2f'))!=1 or '占基金资产净值比例' not in fund_text:
            raise ValueError('Single target holding is not matched to its explicit NAV table')
        targets=[{'identity':('sh' if target_code.startswith('5') else 'sz')+target_code,'value_CNY':float(amount),
            'weight_of_net_assets':float(amount/nav),'page':fund_section[0][0],
            'source_text':'\n'.join(x[1] for x in fund_section),'identity_page':target_section[0][0]}]
        quantities=[]
        for i,page in enumerate(pages):
            m=re.search(r'截至'+re.escape(dated.group(0))+r'止,本基金持有([\d,]+(?:\.\d+)?)份目标ETF基金份额',compact(page))
            if m:quantities.append({'quantity_ETF_shares':float(number(m.group(1))),
                'quantity_evidence':{'page':i+1,'source_text':m.group(0)}})
        if len(quantities)>1:raise ValueError('Target share-count evidence is ambiguous')
        if quantities:targets[0].update(quantities[0])
    futures=[];futures_status='section_not_available'
    if any(re.fullmatch(r'6\.4\.7\.3\.2\s*期末基金持有的期货合约情况',line) for _,line in lines):
        future_lines=section(r'6\.4\.7\.3\.2\s*期末基金持有的期货合约情况',r'6\.4\.7\.4')
        future_text=compact(''.join(x[1] for x in future_lines))
        starts=[i for i,(_,line) in enumerate(future_lines) if re.fullmatch(r'[A-Z]{1,4}\d{3,4}',line)]
        declared_empty=not starts and any(re.fullmatch(r'无[。.]?|本基金本报告期末未持有期货合约[。.]?',line) for _,line in future_lines)
        if not declared_empty and not all(word in future_text for word in ('单位:人民币元','持仓量(买/卖)','合约市值','公允价值变动')):
            raise ValueError('Futures unit/position/value headers not established')
        for k,start in enumerate(starts):
            p,code=future_lines[start]
            if not re.fullmatch(r'[A-Z]{1,2}\d{4}',code):raise ValueError('Unsupported futures contract-code layout')
            block=future_lines[start:(starts[k+1] if k+1<len(starts) else len(future_lines))]
            body=' '.join(line for _,line in block)
            values=re.search(r'(?<![\dA-Z])(-?[\d,]+(?:\.\d+)?)\s+(-?[\d,]+\.\d{2})\s+(-?[\d,]+\.\d{2})',body)
            if not values:raise ValueError('Futures position/value row incomplete')
            quantity=number(values.group(1));market=number(values.group(2));change=number(values.group(3))
            futures.append({'contract_code':code,'position_contracts_signed':float(quantity),'reported_contract_market_value_CNY':float(market),
                'reported_fair_value_change_CNY':float(change),'signed_contract_exposure_CNY':float(abs(market)*(1 if quantity>0 else -1 if quantity<0 else 0)),
                'exposure_fraction_of_net_assets':float(abs(market)*(1 if quantity>0 else -1 if quantity<0 else 0)/nav),
                'method':'contract market value; direction from signed buy/sell position; not balance-sheet asset value',
                'page':p,'source_text':body[:values.end()]})
        futures_status='parsed_contract_rows' if futures else 'reported_no_contract_positions' if declared_empty else 'no_contract_rows_parsed_not_a_proof_of_no_derivatives'
    return {'fund_code':fund_code,'fund_family_name':expected_name,'holdings_scope':'shared_fund_family_portfolio',
        'report_date':report_date,'publication_date':publication_date,'source_url':source_url,'document_sha256':document_sha256,
        'net_assets_CNY':float(nav),'total_assets_CNY':float(assets),'denominator_evidence':nav_source,
        'total_fund_shares':total_shares,'reported_unit_NAV_CNY':reported_unit_nav,
        'reported_unit_NAV_decimal_places':len(unit_match.group(1).partition('.')[2]) if unit_match else None,
        'share_count_and_unit_NAV_evidence':[{'page':p,'source_text':line} for p,line in balance if '基金份额总额' in line or '基金份额净值' in line],
        'asset_total_evidence':asset_source,'asset_composition':asset_rows,'industries':industries,'stocks':stocks,'target_funds':targets,
        'futures_contracts':futures,'futures_detail_status':futures_status,'other_derivative_instruments_reviewed':False,
        'industry_total_CNY':float(industry_total),'industry_total_evidence':{'page':totals[0][0],'source_text':totals[0][1]},
        'asset_composition_equity_CNY':float(equity),'industry_vs_asset_composition_gap_CNY':float(industry_total-equity),
        'asset_composition_notes':[{'page':p,'source_text':line} for p,line in asset_section if line.startswith('注:')],
        'stock_detail_value_CNY':float(stock_sum),'stock_detail_reconciliation_gap_CNY':float(industry_total-stock_sum),
        'stock_detail_reconciled':reconciled,'stock_detail_coverage_of_equity':float(stock_sum/industry_total) if industry_total else None,
        'today_holdings_reconstructed':False,'classification_source':'reported_domestic_industry_table',
        'economic_currency_exposure_verified':False,'format_scope':'Chinese equity/ETF-feeder annual or interim layout with full stock table'}


def look_through_feeder(feeder,target):
    """Retain direct + indirect weights and source paths; never renormalize disclosed stocks."""
    target_identity=('sh' if target['fund_code'].startswith('5') else 'sz')+target['fund_code']
    links=[r for r in feeder['target_funds'] if r['identity']==target_identity]
    if len(links)!=1:raise ValueError('Exact disclosed feeder/target identity mismatch')
    for snapshot in (feeder,target):
        nav=snapshot['net_assets_CNY']
        if not math.isfinite(nav) or nav<=0:raise ValueError('Positive finite NAV denominator required')
        for row in [*snapshot['stocks'],*snapshot['industries'],*snapshot['target_funds']]:
            value=row['value_CNY'];weight=row['weight_of_net_assets']
            if not math.isfinite(value) or value<0 or not math.isfinite(weight) or abs(value/nav-weight)>1e-12:
                raise ValueError('Unmatched fair-value/net-assets weight')
    factor=links[0]['weight_of_net_assets'];by_security={};industries={};paths=[]
    derivative_paths=[]
    for snapshot,multiplier,layer in ((feeder,1.0,'direct'),(target,factor,'via_target_ETF')):
        source={'fund_code':snapshot['fund_code'],'report_date':snapshot['report_date'],'publication_date':snapshot['publication_date'],
            'document_sha256':snapshot['document_sha256'],'source_url':snapshot['source_url'],
            'retrieved_at':snapshot.get('retrieved_at','unknown'),
            'report_selection_scope':snapshot.get('issuer_report_selection',{}).get('scope','caller_supplied_report_snapshot')}
        paths.append({**source,'layer':layer,'multiplier':multiplier})
        for row in snapshot['stocks']:
            contribution=multiplier*row['weight_of_net_assets']
            result=by_security.setdefault(row['identity'],{'identity':row['identity'],'name':row['name'],'estimated_weight_of_feeder_NAV':0,'paths':[]})
            result['estimated_weight_of_feeder_NAV']+=contribution
            result['paths'].append({**source,'layer':layer,'page':row['page'],'contribution':contribution})
        for row in snapshot.get('futures_contracts',[]):
            derivative_paths.append({**source,'layer':layer,**row,
                'estimated_contract_exposure_fraction_of_feeder_NAV':multiplier*row['exposure_fraction_of_net_assets']})
        for row in snapshot['industries']:
            key=row['code'];item=industries.setdefault(key,{'code':key,'name':row['name'],'estimated_weight_of_feeder_NAV':0,'paths':[]})
            item['estimated_weight_of_feeder_NAV']+=multiplier*row['weight_of_net_assets']
            item['paths'].append({**source,'page':row['page'],'layer':layer})
    disclosed=sum(x['estimated_weight_of_feeder_NAV'] for x in by_security.values())
    equity=sum(x['estimated_weight_of_feeder_NAV'] for x in industries.values())
    futures_complete=all(s.get('futures_detail_status') in ('parsed_contract_rows','reported_no_contract_positions') for s in (feeder,target))
    known_futures_exposure=sum(x['estimated_contract_exposure_fraction_of_feeder_NAV'] for x in derivative_paths)
    bridge={'status':'quantity_or_target_total_shares_not_available','same_report_date':feeder['report_date']==target['report_date'],
        'booked_target_value_CNY':links[0]['value_CNY'],'economic_cause_verified':False,'quantity_evidence':links[0].get('quantity_evidence'),
        'target_NAV_and_share_count_evidence':target.get('share_count_and_unit_NAV_evidence',[])}
    held=links[0].get('quantity_ETF_shares');total=target.get('total_fund_shares')
    if held is not None and total is not None and total>0 and bridge['same_report_date']:
        exact_unit_nav=target['net_assets_CNY']/total;expected=held*exact_unit_nav;gap=links[0]['value_CNY']-expected
        reported_nav=target.get('reported_unit_NAV_CNY')
        digits=target.get('reported_unit_NAV_decimal_places')
        rounding_bound=held*.5*10**(-digits)+.01 if reported_nav is not None and digits is not None else .01
        direct_equity=sum(r['weight_of_net_assets'] for r in feeder['industries']);underlying_equity=sum(r['weight_of_net_assets'] for r in target['industries'])
        quantity_factor=expected/feeder['net_assets_CNY']
        bridge.update({'status':'within_reported_NAV_rounding_bound' if abs(gap)<=rounding_bound else 'unresolved_cross_layer_amount_difference',
            'held_target_ETF_shares':held,'target_total_shares':total,'target_exact_NAV_per_share':exact_unit_nav,
            'target_reported_unit_NAV':reported_nav,'booked_implied_target_NAV_per_share':links[0]['value_CNY']/held if held else None,
            'quantity_times_target_NAV_value_CNY':expected,'booked_minus_quantity_value_CNY':gap,
            'reported_unit_NAV_rounding_bound_CNY':rounding_bound,
            'target_internal_unit_NAV_matches_display_precision':abs(exact_unit_nav-reported_nav)<=.5*10**(-digits) if reported_nav is not None and digits is not None else None,
            'quantity_based_target_weight_of_feeder_NAV':quantity_factor,
            'quantity_based_equity_of_feeder_NAV_sensitivity':direct_equity+quantity_factor*underlying_equity,
            'main_exposure_basis':'feeder_reported_holding_value; quantity basis is sensitivity, not a silent replacement'})
    elif not bridge['same_report_date']:bridge['status']='different_report_dates_not_comparable'
    return {'fund_code':feeder['fund_code'],'target_identity':target_identity,'target_weight_of_feeder_NAV':factor,
        'cross_layer_value_bridge':bridge,
        'snapshot_paths':paths,'mixed_report_dates':feeder['report_date']!=target['report_date'],
        'securities':sorted(by_security.values(),key=lambda r:-r['estimated_weight_of_feeder_NAV']),
        'industries':sorted(industries.values(),key=lambda r:-r['estimated_weight_of_feeder_NAV']),
        'source_table_reconciliation':[{'fund_code':s['fund_code'],'stock_detail_vs_industry_gap_CNY':
            s['industry_total_CNY']-sum(r['value_CNY'] for r in s['stocks']),
            'industry_vs_asset_composition_gap_CNY':s['industry_vs_asset_composition_gap_CNY'],
            'asset_composition_notes':s['asset_composition_notes']} for s in (feeder,target)],
        'futures_exposure':{'separate_contract_paths':derivative_paths,
            'estimated_signed_contract_market_exposure_fraction_of_feeder_NAV':known_futures_exposure if futures_complete else None,
            'known_disclosed_contract_subtotal_fraction_of_feeder_NAV':known_futures_exposure,
            'both_futures_sections_verified':futures_complete,
            'section_coverage':[{'fund_code':s['fund_code'],'status':s.get('futures_detail_status','unknown')} for s in (feeder,target)],
            'added_to_stock_or_asset_weights':False,'allocated_to_index_constituents':False,
            'scope':'disclosed futures market-value exposure only; not delta-adjusted total portfolio risk or today positions'},
        'coverage':{'estimated_CN_listed_equity_of_feeder_NAV':equity,'security_detail_of_feeder_NAV':disclosed,
            'security_detail_of_equity':round(disclosed/equity,12) if equity else None,'not_covered_by_equity_detail_of_NAV':1-disclosed,
            'region_classification_scope':'reported CN-listed equity only','valuation_currency':'CNY',
            'economic_FX_or_revenue_currency_verified':False},
        'today_holdings_reconstructed':False,'method':'exact fair values divided by each layer net assets, retain residual and report dates'}


def stored_lookthrough(store,code,*,as_of=None):
    as_of=as_of or datetime.now(timezone.utc).isoformat()
    reviewed=[r for r in store.get_observations('fund_holdings',code,limit=1,as_of=as_of)
              if r['provider']=='reviewed_primary_holdings' and r['quality']=='source_bound_reviewed_snapshot']
    parsed=[r for r in store.get_observations('fund_holdings',code,limit=1,as_of=as_of)
              if r['provider']=='chinaamc_disclosed_holdings' and r['quality']=='primary_report_parsed_with_explicit_reconciliation']
    if reviewed and (not parsed or max(r['as_of'] for r in reviewed)>max(r['as_of'] for r in parsed)):
        from .fund_reviewed_holdings import reviewed_lookthrough
        newest=max(r['as_of'] for r in reviewed);latest=[r for r in reviewed if r['as_of']==newest]
        if len({r['value']['document_sha256'] for r in latest})!=1:raise ValueError('Conflicting reviewed holdings documents')
        if latest[-1]['value'].get('publication_dispatch_date_bound_to_original') is not True:
            raise ValueError('Reviewed snapshot predates source-bound publication date check; re-review original source')
        value=latest[-1]['value']
        if any(r.get('child_fund_code') for r in value['securities'] if r['asset_class'] in {'fund','ETF'}):
            from .fund_graph import stored_fund_graph
            return stored_fund_graph(store,code,as_of=as_of)
        return reviewed_lookthrough(value)
    def snapshot(identity):
        rows=[r for r in store.get_observations('fund_holdings',identity,limit=1,as_of=as_of)
              if r['provider']=='chinaamc_disclosed_holdings' and r['quality']=='primary_report_parsed_with_explicit_reconciliation']
        if not rows:raise ValueError('No supported primary holdings snapshot for '+identity)
        newest=max(r['as_of'] for r in rows);latest=[r for r in rows if r['as_of']==newest]
        if len({r['value']['document_sha256'] for r in latest})!=1:raise ValueError('Conflicting same-date holdings documents')
        return latest[-1]['value']
    feeder=snapshot(code)
    if len(feeder['target_funds'])!=1:raise ValueError('This stored helper requires one exact disclosed target ETF')
    target=snapshot(feeder['target_funds'][0]['identity'][2:])
    return look_through_feeder(feeder,target)
