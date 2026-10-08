"""Source-bound reviewed holdings for managers without a validated table adapter."""
import hashlib
import re
import unicodedata
from datetime import date
from decimal import Decimal
from pathlib import Path


def compact(text):
    return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))


def printed_date(text):
    """Dates explicitly following a report dispatch/publication label, including Chinese digits."""
    text=compact(text)
    match=re.search(r'(?:报告送出日期|公告送出日期|送出日期|发布日期|披露日期)[:：]?([^\n]{1,40})',text)
    if not match:return None
    tail=match.group(1)
    m=re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})',tail)
    if m:return date(*map(int,m.groups())).isoformat()
    digits={c:i for i,c in enumerate('〇一二三四五六七八九')};digits['零']=0
    def integer(token):
        if token.isdigit():return int(token)
        if '十' in token:
            a,b=token.split('十');return (digits[a] if a else 1)*10+(digits[b] if b else 0)
        return int(''.join(str(digits[c]) for c in token))
    m=re.match(r'([〇零一二三四五六七八九十\d]+)年([〇零一二三四五六七八九十\d]+)月([〇零一二三四五六七八九十\d]+)日',tail)
    return date(*(integer(x) for x in m.groups())).isoformat() if m else None


def reviewed_snapshot(review,document_dir):
    """Check original bytes, cited passages and weight arithmetic; review is still human analysis."""
    source=review['source'];digest=source['sha256'];code=review['fund_code']
    if not re.fullmatch(r'[0-9a-f]{64}',digest) or not re.fullmatch(r'\d{6}',code):
        raise ValueError('Exact share code and original PDF SHA required')
    if not str(source.get('url','')).startswith('https://'):
        raise ValueError('Direct original disclosure source required')
    path=Path(document_dir)/(digest+'.pdf')
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise ValueError('Original holdings PDF bytes differ from the review')
    receipts=source.get('source_receipts',[])
    if receipts:
        from .responses import ResponseVault
        for reference in receipts:
            record=ResponseVault.verify_reference(reference)
            if record.get('decoded_sha256')!=digest:
                raise ValueError('Holdings PDF does not match archived response bytes')
            if record['final_url']!=source['url']:
                raise ValueError('Holdings source URL differs from archived original response')
    from pypdf import PdfReader
    pages=[p.extract_text() or '' for p in PdfReader(path).pages]
    def passage(evidence):
        page=evidence.get('page');excerpt=evidence.get('excerpt','')
        if type(page)!=int or not 1<=page<=len(pages) or not excerpt or compact(excerpt) not in compact(pages[page-1]):
            raise ValueError('Reviewed passage does not match original page')
        return excerpt
    identity=review['identity_evidence'];own=passage(identity)
    if identity['page']>5 or not re.search(r'(?<!\d)'+code+r'(?!\d)',own):
        raise ValueError('Exact share code must be in the own-fund identity table near report front')
    if compact(review['fund_family_name']) not in compact(pages[0]):
        raise ValueError('Report cover fund family mismatch')
    report_day=date.fromisoformat(review['report_date']);published=date.fromisoformat(review['publication_date'])
    if published<report_day:raise ValueError('Holdings publication precedes the report date')
    if review['publication_date_evidence'].get('page',0)>3 or printed_date(passage(review['publication_date_evidence']))!=review['publication_date']:
        raise ValueError('Publication/dispatch date does not match original cited date')
    period_text=compact(passage(review['report_date_evidence']))
    chinese_dates=[date(*map(int,m)) for m in re.findall(r'(\d{4})年(\d{1,2})月(\d{1,2})日',period_text)]
    if report_day.isoformat() not in period_text and report_day not in chinese_dates:
        raise ValueError('Report date does not match original cited date')
    currency=review['report_currency']
    labels={'CNY':('人民币',),'USD':('美元',),'HKD':('港币','港元')}
    unit_text=passage(review['unit_evidence'])
    if currency not in labels or not any(x in compact(unit_text) for x in labels[currency]) or '元' not in compact(unit_text) or re.search(r'万元|亿元|百万|千元',compact(unit_text)):
        raise ValueError('Original reporting currency/base unit not established')
    def scalar(value,evidence,*,signed=False):
        text=passage(evidence);numeric=Decimal(str(value))
        if not numeric.is_finite() or (numeric<0 and not signed):raise ValueError('Finite disclosed amount/percent with correct sign required')
        tokens=re.findall(r'(?<![\d.])[+-]?\d[\d,]*(?:\.\d+)?(?![\d.])',unicodedata.normalize('NFKC',text))
        if not any(Decimal(t.replace(',',''))==numeric for t in tokens):
            raise ValueError('Reviewed numeric value absent from cited passage')
        return numeric
    denominators={}
    for name,item in review['denominators'].items():
        if name not in {'fund_net_assets','total_assets','stock_assets','bond_assets'}:
            raise ValueError('Unknown report weight denominator')
        amount=scalar(item['value'],item['evidence'])
        if amount<=0:raise ValueError('Positive disclosed denominator required')
        denominators[name]=amount
    if 'fund_net_assets' not in denominators:raise ValueError('Fund NAV denominator missing')
    nav=denominators['fund_net_assets'];securities=[];allocations=[];seen=set()
    def normalize_row(row):
        denominator=row['denominator']
        if denominator not in denominators:raise ValueError('Row denominator amount missing')
        header=passage(row['denominator_evidence'])
        expected={'fund_net_assets':('净资产','资产净值'),'total_assets':('总资产',),
                  'stock_assets':('股票资产','权益资产'),'bond_assets':('债券资产',)}[denominator]
        if not any(x in compact(header) for x in expected):raise ValueError('Row denominator header mismatch')
        percent=scalar(row['reported_percent'],row['evidence']) if row.get('reported_percent') is not None else None
        amount=scalar(row['value'],row['evidence']) if row.get('value') is not None else None
        if percent is None and amount is None:raise ValueError('Disclosed amount or percent required')
        ratio=amount/denominators[denominator] if amount is not None else percent/100
        precision=row.get('percent_decimal_places',2)
        if type(precision)!=int or not 0<=precision<=6:raise ValueError('Original percent precision required')
        if amount is not None and percent is not None and abs(ratio-percent/100)>Decimal('.5')*Decimal(10)**(-precision)/100+Decimal('1e-12'):
            raise ValueError('Reported weight differs beyond displayed rounding from amount/denominator')
        return {**row,'weight_of_fund_NAV':float(ratio*denominators[denominator]/nav),
                'original_weight_denominator':denominator,'report_currency':currency,
                'weight_is_derived_from_amounts':amount is not None,'reported_percent_available':percent is not None}
    for row in review.get('securities',[]):
        identity=row.get('identity');identifier=row.get('source_identifier','')
        excerpt=passage(row['evidence'])
        if not identity or identity in seen or not identifier or compact(identifier) not in compact(excerpt):
            raise ValueError('Unique security identity and original identifier required')
        if row.get('asset_class') not in {'stock','bond','fund','ETF','cash','other'}:
            raise ValueError('Unknown disclosed asset class')
        if row.get('child_fund_code'):
            codes=re.findall(r'(?<!\d)\d{6}(?!\d)',identifier)
            if row['asset_class'] not in {'fund','ETF'} or codes!=[row['child_fund_code']]:
                raise ValueError('Child fund code must match the exact disclosed held share identifier')
        market=row.get('price_market');price_identity=row.get('price_identity')
        if market or price_identity:
            raw_identifier=compact(identifier).upper()
            if market=='US':matched=raw_identifier==str(price_identity).upper()+'US'
            elif market=='HK':
                found=re.fullmatch(r'(\d+)HK',raw_identifier)
                native=re.fullmatch(r'(\d+)\.HK',str(price_identity).upper())
                matched=bool(found and native and int(found.group(1))==int(native.group(1)))
            elif market=='CN':
                found=re.fullmatch(r'(\d{6})CH',raw_identifier)
                from .symbols import normalize_cn_symbol
                matched=bool(found and normalize_cn_symbol(found.group(1))==price_identity)
            else:matched=False
            if not matched or identity!=market+':'+str(price_identity):
                raise ValueError('Native price identity is not matched to the disclosed security identifier')
        seen.add(identity);securities.append(normalize_row(row))
    allocation_keys=set()
    for row in review.get('allocations',[]):
        if row.get('dimension') not in {'asset_class','listing_region','industry','trading_currency','balance_sheet_FX','economic_FX'}:
            raise ValueError('Unsupported allocation dimension')
        if not row.get('category') or compact(row['category']) not in compact(passage(row['evidence'])):
            raise ValueError('Allocation category absent from original passage')
        key=(row['dimension'],row['category'],row.get('classification_scheme'))
        if key in allocation_keys:raise ValueError('Duplicate allocation category would double count coverage')
        allocation_keys.add(key)
        allocations.append(normalize_row(row))
    derivatives=[];derivative_ids=set()
    for row in review.get('derivatives',[]):
        identity=row.get('identity');identifier=row.get('source_identifier','')
        if not identity or identity in derivative_ids or not identifier or compact(identifier) not in compact(passage(row['evidence'])):
            raise ValueError('Unique derivative identity and source identifier required')
        header=compact(passage(row['contract_value_evidence']))
        market_value='合约市值' in header;notional='名义金额' in header or '名义本金' in header
        if market_value==notional:
            raise ValueError('Derivative contract value must be separate from book value')
        quantity=scalar(row['signed_contracts'],row['evidence'],signed=True)
        amount=scalar(row['contract_value'],row['evidence'],signed=True)
        if quantity!=quantity.to_integral_value() or quantity==0:
            raise ValueError('Nonzero signed contract quantity required')
        derivatives.append({**row,'signed_contracts':float(quantity),'contract_value':float(amount),
            'contract_measurement_basis':'contract_market_value' if market_value else 'reported_notional_amount',
            'signed_contract_exposure_fraction_of_NAV':float(abs(amount)/nav)*(1 if quantity>0 else -1),
            'added_to_asset_or_stock_weights':False,'delta_adjusted_exposure_verified':False})
        derivative_ids.add(identity)
    disclosed=sum(r['weight_of_fund_NAV'] for r in securities)
    classification_coverage={}
    for row in allocations:
        key=row['dimension'];classification_coverage[key]=classification_coverage.get(key,0)+row['weight_of_fund_NAV']
    return {'fund_code':code,'fund_family_name':review['fund_family_name'],'report_date':review['report_date'],
        'publication_date':review['publication_date'],'source_url':source['url'],'document_sha256':digest,
        'source_receipts':receipts,'HTTP_response_dependencies_verified':bool(receipts),
        'report_currency':currency,'net_assets':float(nav),'holdings_scope':review.get('holdings_scope','disclosed_fund_family_snapshot'),
        'publication_date_basis':'printed report dispatch/publication date; original intraday availability unverified',
        'publication_dispatch_date_bound_to_original':True,
        'securities':securities,'allocations':allocations,'classification_coverage_of_NAV':classification_coverage,
        'derivative_contracts':derivatives,
        'security_detail_of_fund_NAV':disclosed,'remaining_net_NAV_after_disclosed_detail':1-disclosed,
        'today_holdings_reconstructed':False,'report_dates_preserved':True,
        'economic_FX_verified':any(r['dimension']=='economic_FX' for r in allocations),
        'all_derivatives_reviewed':False,'review_method':'analyst reviewed original disclosure; byte/passage/numeric/denominator checks',
        'automatic_semantic_extraction_verified':False,'source_review':review}


def reviewed_lookthrough(snapshot):
    """Direct snapshot; linked/FOF children remain unresolved until their own sources are reviewed."""
    securities=[{**r,'estimated_weight_of_fund_NAV':r['weight_of_fund_NAV']} for r in snapshot['securities']]
    return {'fund_code':snapshot['fund_code'],'report_date':snapshot['report_date'],
        'snapshot_paths':[{'fund_code':snapshot['fund_code'],'report_date':snapshot['report_date'],
            'publication_date':snapshot['publication_date'],'document_sha256':snapshot['document_sha256'],
            'source_url':snapshot['source_url'],'layer':'direct_disclosed_snapshot'}],
        'securities':securities,'allocations':snapshot['allocations'],
        'derivatives':{'known_contract_rows':snapshot.get('derivative_contracts',[]),
            'all_derivatives_reviewed':snapshot['all_derivatives_reviewed'],
            'known_gross_contract_market_fraction_of_NAV':sum(abs(r['signed_contract_exposure_fraction_of_NAV']) for r in snapshot.get('derivative_contracts',[]) if r.get('contract_measurement_basis')=='contract_market_value') or None,
            'known_gross_reported_notional_fraction_of_NAV':sum(abs(r['signed_contract_exposure_fraction_of_NAV']) for r in snapshot.get('derivative_contracts',[]) if r.get('contract_measurement_basis')=='reported_notional_amount') or None,
            'legacy_contract_basis_requires_review':any(r.get('contract_measurement_basis') not in {'contract_market_value','reported_notional_amount'} for r in snapshot.get('derivative_contracts',[])),
            'aggregated_into_net_portfolio_risk':False,'added_to_stock_or_asset_weights':False},
        'unresolved_child_funds':[r for r in securities if r['asset_class'] in {'fund','ETF'}],
        'coverage':{'security_detail_of_fund_NAV':snapshot['security_detail_of_fund_NAV'],
            'classification_coverage_of_NAV':snapshot['classification_coverage_of_NAV'],
            'economic_FX_or_revenue_currency_verified':snapshot['economic_FX_verified'],
            'valuation_currency':snapshot['report_currency']},
        'today_holdings_reconstructed':False,'method':snapshot['review_method'],
        'full_recursive_lookthrough_verified':False}
