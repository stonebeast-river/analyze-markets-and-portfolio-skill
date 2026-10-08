"""Load dated reviewed share-class terms only while their source PDF and passages match."""
import json,re,hashlib,unicodedata
from decimal import Decimal
from pathlib import Path


def load_fee_contract(code,document_dir,registry_path=None,*,as_of=None):
    registry_path=Path(registry_path) if registry_path else Path(__file__).resolve().parents[2]/'assets/fund-fee-contracts.json'
    registry=json.loads(registry_path.read_text(encoding='utf-8'))
    entries=[v for v in registry['families'].values() if code in v['codes'].values()]
    if len(entries)!=1:raise ValueError('No unique reviewed A/C fee family for requested exact share')
    contract=entries[0];path=Path(document_dir)/(contract['source']['sha256']+'.pdf')
    if as_of and contract['source']['publication_date']>as_of[:10]:raise ValueError('Fee document is beyond research cutoff')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=contract['source']['sha256']:raise ValueError('Reviewed fee source PDF hash differs')
    from pypdf import PdfReader
    pages=[p.extract_text() or '' for p in PdfReader(path).pages]
    if len(pages)<143:
        raise ValueError('This fee layout is unsupported; review the actual share-specific terms separately')
    compact=lambda t:re.sub(r'\s+','',unicodedata.normalize('NFKC',t))
    text=compact(''.join(pages))
    if compact(contract['fund_family_name']) not in text:raise ValueError('Fee document legal family identity missing')
    identity_text=unicodedata.normalize('NFKC','\n'.join(pages));bridge_source=None
    if any(not re.search(r'(?<!\d)'+c+r'(?!\d)',identity_text) for c in contract['codes'].values()):
        bridge_source=contract.get('identity_bridge')
        if not bridge_source:raise ValueError('Fee document exact shares missing without reviewed identity bridge')
        if as_of and bridge_source['publication_date']>as_of[:10]:raise ValueError('Fee identity bridge is beyond research cutoff')
        bridge_path=Path(document_dir)/(bridge_source['sha256']+'.pdf')
        if hashlib.sha256(bridge_path.read_bytes()).hexdigest()!=bridge_source['sha256']:
            raise ValueError('Exact-share identity bridge PDF changed')
        bridge_pages=[p.extract_text() or '' for p in PdfReader(bridge_path).pages]
        identity_text=unicodedata.normalize('NFKC','\n'.join(bridge_pages[p-1] for p in bridge_source['pages']))
        if compact(contract['fund_family_name']) not in compact(identity_text) or any(not re.search(r'(?<!\d)'+c+r'(?!\d)',identity_text) for c in contract['codes'].values()):
            raise ValueError('Reviewed bridge does not establish same legal family/exact shares')
    for passage in contract['reviewed_passages']:
        if not 1<=passage['page']<=len(pages) or compact(passage['text']) not in compact(pages[passage['page']-1]):
            raise ValueError('Reviewed fee source passage missing')
    # This registered layout has explicit named rates and amount bands, not unbound percentage tokens.
    annual=compact(pages[142]);fees=compact(pages[95])
    c=re.search(r'C类销售服务费年费率为([\d.]+)%',annual)
    management=re.search(r'本基金的管理费.{0,120}?([\d.]+)%年费率',annual)
    custody=re.search(r'本基金的托管费.{0,120}?([\d.]+)%的年费率',annual)
    if not c or not management or not custody:raise ValueError('Named annual fee rates not found in registered source layout')
    percent=lambda s:float(Decimal(s)/100)
    if (contract['classes']['C']['sales_service_annual_fraction']!=percent(c.group(1))
            or contract['classes']['A']['sales_service_annual_fraction']!=0
            or contract['common_management_annual_fraction']!=percent(management.group(1))
            or contract['common_custody_annual_fraction']!=percent(custody.group(1))):
        raise ValueError('Registered fee values disagree with named source rates')
    if 'A类、Y类不收取销售服务费' not in annual or '若为负数,则E取0' not in annual:
        raise ValueError('Class-specific service exemption or ETF-excluded charge base missing')
    first=re.search(r'(\d+)万元以下([\d.]+)%',fees)
    bands=re.findall(r'(\d+)万元以上\(含\d+万元\)-(\d+)万元以下([\d.]+)%',fees)
    fixed=re.search(r'(\d+)万元以上\(含\d+万元\)每笔([\d,.]+)元',fees)
    if not first or len(bands)!=2 or not fixed:raise ValueError('Reviewed amount fee bands no longer match')
    expected=[{'min_amount':0,'max_amount_exclusive':int(first.group(1))*10000,'fraction':percent(first.group(2))}]
    expected.extend({'min_amount':int(lo)*10000,'max_amount_exclusive':int(hi)*10000,'fraction':percent(rate)} for lo,hi,rate in bands)
    expected.append({'min_amount':int(fixed.group(1))*10000,'max_amount_exclusive':None,'fixed_CNY':float(fixed.group(2).replace(',',''))})
    if contract['classes']['A']['subscription_tiers']!=expected:raise ValueError('Registered A tiers differ from source amount bands')
    if contract['classes']['C']['subscription_tiers']!=[{'min_amount':0,'max_amount_exclusive':None,'fraction':0}]:
        raise ValueError('C subscription exemption does not match source')
    if contract['sales_service_charge_base']!='previous_calendar_day_full_share_class_NAV' or contract['common_management_custody_base']!='max(previous_fund_NAV_minus_held_target_ETF_NAV,0)':
        raise ValueError('Registered charge bases disagree with reviewed clauses')
    a_under=re.search(r'7天以内([\d.]+)%',fees);a_mid=re.search(r'7天以上\(含7天\)-1年以内([\d.]+)%',fees)
    c_under=re.search(r'持有不满7天的,收取([\d.]+)%的赎回费',fees)
    if not a_under or not a_mid or not c_under or '1年以上(含1年)0' not in fees:
        raise ValueError('Named share redemption fee clauses missing')
    expected_A={'type':'seven_day_and_one_year','under_7_day_fraction':percent(a_under.group(1)),
        'seven_days_to_one_year_fraction':percent(a_mid.group(1)),'at_least_one_year_fraction':0}
    expected_C={'type':'seven_day_only','under_7_day_fraction':percent(c_under.group(1)),'at_least_7_day_fraction':0}
    if contract['classes']['A']['redemption']!=expected_A or contract['classes']['C']['redemption']!=expected_C:
        raise ValueError('Registered redemption values disagree with share-specific source clauses')
    return {**contract,'verified_against_current_source_bytes':True,
        'exact_share_identity_source':bridge_source or contract['source'],
        'latest_superseding_fee_notice_audit_verified':False,'platform_discount_verified':False,
        'common_ongoing_fees_already_inside_historical_NAV':True,'fee_scope':'dated standard contract; actual channel costs remain separate'}
