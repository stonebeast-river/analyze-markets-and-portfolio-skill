"""SHA- and page-reviewed primary issuer fields, with explicit period and scope."""
import hashlib,io,json,re,unicodedata
from decimal import Decimal,InvalidOperation
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit

from ..http import HttpClient,DataSourceError
from ..models import Observation

METRIC_UNITS={**{name:'CNY_yuan' for name in ('operating_revenue','total_revenue','net_profit_total',
    'net_profit_parent','cashflow_operating_net','operating_cost','total_assets','equity_parent')},
    'shares_total':'share','basic_eps':'CNY_yuan_per_share','roe_weighted':'percent'}

METRIC_PERIODS={name:('point_at_period_end' if name in {'total_assets','equity_parent','shares_total'} else 'flow_YTD')
                for name in METRIC_UNITS}
METRIC_SCOPES={
    'operating_revenue':{'consolidated'},'total_revenue':{'consolidated','consolidated_including_interest_income'},
    'net_profit_total':{'consolidated_including_noncontrolling_interests'},
    'net_profit_parent':{'attributable_to_parent_shareholders'},
    'cashflow_operating_net':{'consolidated','consolidated_including_finance_subsidiary'},
    'operating_cost':{'consolidated'},'total_assets':{'consolidated'},
    'equity_parent':{'attributable_to_parent_shareholders'},'shares_total':{'issuer_outstanding_shares'},
    'roe_weighted':{'issuer_reported_weighted_ROE_not_vendor_roeAvg'}}
TABLE_METRICS={
    'headline_flow':{'operating_revenue','net_profit_parent','cashflow_operating_net'},
    'headline_stock':{'total_assets','equity_parent'},
    'financial_indicators':{'basic_eps','roe_weighted'},
    'consolidated_income':{'operating_revenue','total_revenue','net_profit_total','net_profit_parent','operating_cost'},
    'consolidated_cashflow':{'cashflow_operating_net'},'share_changes':{'shares_total'}}
ROW_LABELS={
    'operating_revenue':{'营业收入','其中:营业收入'},'total_revenue':{'一、营业总收入'},
    'net_profit_total':{'五、净利润(净亏损以“－”号填列)','五、净利润(净亏损以“-”号填列)'},
    'net_profit_parent':{'归属于上市公司股东的净利润','1.归属于母公司股东的净利润(净亏损以“-”号填列)'},
    'cashflow_operating_net':{'经营活动产生的现金流量净额'},'operating_cost':{'其中:营业成本'},
    'total_assets':{'总资产'},'equity_parent':{'归属于上市公司股东的净资产'},
    'shares_total':{'三、股份总数'},'basic_eps':{'基本每股收益(元/股)'},
    'roe_weighted':{'加权平均净资产收益率(%)'}}
NUMBER_PATTERN=r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?'


def compact(text):return re.sub(r'\s+','',unicodedata.normalize('NFKC',text))


def page_numbers(text):
    result=set()
    for number in re.findall(r'[-+]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?',text):
        try:result.add(Decimal(number.replace(',','')))
        except InvalidOperation:pass
    return result


def validate_semantic_row(field,entry,pages):
    """Bind a named measure to its row, ordered columns, table and comparison period."""
    name=field['name'];schema=field.get('table_schema');label=compact(field.get('row_label',''))
    if schema not in TABLE_METRICS or name not in TABLE_METRICS[schema]:
        raise DataSourceError('Financial table/metric schema mismatch')
    labels={compact(value) for value in ROW_LABELS[name]}
    if label not in labels:raise DataSourceError('Financial row label/metric schema mismatch')
    if compact(field['source_label']) not in label:raise DataSourceError('Financial source label does not match selected row')
    allowed_scopes=METRIC_SCOPES.get(name,{f"basic_{entry['period_type']}_not_TTM",'basic_report_period_not_TTM'})
    if field.get('accounting_scope') not in allowed_scopes or field.get('period_kind')!=METRIC_PERIODS[name]:
        raise DataSourceError('Financial accounting scope or period kind mismatch')
    start=datetime.fromisoformat(entry['period_start']).date();end=datetime.fromisoformat(entry['period_end']).date()
    prior=(f'{start.year-1}-{start.month:02d}-{start.day:02d}_to_{end.year-1}-{end.month:02d}-{end.day:02d}'
           if METRIC_PERIODS[name]=='flow_YTD' else f'{start.year-1}-12-31_not_prior_year_same_period')
    if field.get('prior_basis')!=prior:raise DataSourceError('Financial comparison period mismatch')
    page=field['page'];header_page=field.get('header_evidence_page',page)
    if not 1<=header_page<=page or page-header_page>1:raise DataSourceError('Financial table header page mismatch')
    text=unicodedata.normalize('NFKC',pages[page-1]);header=compact(pages[header_page-1])
    if schema=='headline_flow':
        if not all(token in header for token in ('主要会计数据','本报告期','上年同期')):
            raise DataSourceError('Financial flow column headers missing')
        text=text.split('本报告期末',1)[0]
    elif schema=='headline_stock':
        if not all(token in header for token in ('本报告期末','上年度末')):
            raise DataSourceError('Financial stock comparison headers missing')
        text=text.split('本报告期末',1)[-1].split('(二)',1)[0]
    elif schema=='financial_indicators':
        if not all(token in header for token in ('主要财务指标','本报告期','上年同期')):
            raise DataSourceError('Financial indicator column headers missing')
        text=text.split('(二)',1)[-1].split('公司的',1)[0]
    elif schema=='share_changes':
        if not all(token in header for token in ('股份变动情况表','本次变动前','本次变动后')):
            raise DataSourceError('Share-change column headers missing')
    else:
        title='合并利润表' if schema=='consolidated_income' else '合并现金流量表'
        if not all(token in header for token in (title,f'{end.year}年半年度',f'{end.year-1}年半年度')):
            raise DataSourceError('Consolidated financial statement column headers missing')
        # A statement starting later on the header page must own the selected row.
        if header_page==page:text=text.split(title,1)[-1]
        other='母公司利润表' if schema=='consolidated_income' else '母公司现金流量表'
        text=text.split(other,1)[0]
    # PDF extraction can wrap labels across lines; numbers retain whitespace separators.
    row_pattern=r'\s*'.join(re.escape(char) for char in label)
    token=NUMBER_PATTERN+r'(?=\s|$)'
    matches=list(re.finditer(r'(?:^|(?<=\n))[ \t]*'+row_pattern+r'\s+('+token+r'(?:\s+'+token+r')*)',text))
    if len(matches)!=1:raise DataSourceError('Financial row is missing or ambiguous')
    numbers=[Decimal(value.replace(',','')) for value in re.findall(NUMBER_PATTERN,matches[0].group(1))]
    if schema=='share_changes':current_index,prior_index,count=4,0,6
    elif schema=='consolidated_income' and name in {'operating_revenue','operating_cost'}:
        current_index,prior_index,count=1,2,3  # First column is an accounting-note reference.
    else:current_index,prior_index,count=0,1,2
    # Headline tables have a third percentage column; weighted ROE has a textual change.
    if schema in {'headline_flow','headline_stock','financial_indicators'}:valid_count=len(numbers) in {2,3}
    else:valid_count=len(numbers)==count
    if not valid_count or numbers[current_index]!=Decimal(field['reported_decimal']):
        raise DataSourceError('Financial value missing from the selected current column')
    if field.get('prior_reported_decimal') is None or numbers[prior_index]!=Decimal(field['prior_reported_decimal']):
        raise DataSourceError('Financial comparison value missing from the selected prior column')
    return {'table_schema':schema,'row_label':field['row_label'],'header_evidence_page':header_page,
            'current_column_index':current_index,'prior_column_index':prior_index,'row_column_values_verified':True,
            'period_and_scope_schema_verified':True}


class IssuerFinancialProvider:
    name='primary_issuer_reports'
    def __init__(self,registry_path,document_dir,client=None):
        self.registry_path=Path(registry_path);self.document_dir=Path(document_dir)
        self.client=client or HttpClient(user_agent='Mozilla/5.0',timeout=18,retries=0)

    def fetch_evidence(self,identity,period_end):
        registry=json.loads(self.registry_path.read_text(encoding='utf-8-sig'))
        entry=registry.get('reports',{}).get(identity+'|'+period_end)
        if not entry or entry['identity']!=identity or entry['period_end']!=period_end:
            raise DataSourceError('No reviewed primary issuer/period source')
        host=urlsplit(entry['source_url']).hostname
        if host not in entry['approved_hosts']:raise DataSourceError('Unregistered primary financial host')
        body,source=self.client.get_bytes(entry['source_url'])
        if urlsplit(source).hostname not in entry['approved_hosts']:raise DataSourceError('Financial redirect leaves registered hosts')
        if not body.startswith(b'%PDF'):raise DataSourceError('Financial disclosure is not PDF bytes')
        from pypdf import PdfReader
        pages=[page.extract_text() or '' for page in PdfReader(io.BytesIO(body)).pages]
        text='\n'.join(pages);code=identity[2:]
        if (entry['company_name'] not in compact(text[:2500]) or not re.search(r'(?<!\d)'+re.escape(code)+r'(?!\d)',text[:2500])):
            raise DataSourceError('Primary financial issuer identity mismatch')
        end=datetime.fromisoformat(period_end).date();start=datetime.fromisoformat(entry['period_start']).date()
        if (end<start or entry['period_months'] not in (3,6,9,12)
                or (end.year-start.year)*12+end.month-start.month+1!=entry['period_months']):
            raise DataSourceError('Invalid reviewed financial period')
        period_phrase=f'{start.year}年{start.month}月{start.day}日至{end.year}年{end.month}月{end.day}日'
        if period_phrase not in compact(text):raise DataSourceError('Financial report period does not match registered period')
        digest=hashlib.sha256(body).hexdigest();stamp=datetime.now(timezone.utc).isoformat()
        self.document_dir.mkdir(parents=True,exist_ok=True);path=self.document_dir/(digest+'.pdf')
        if not path.exists():path.write_bytes(body)
        reviewed=digest==entry['reviewed_sha256'];fields=[];contexts=[]
        if reviewed:
            for field in entry['reviewed_fields']:
                page=field['page'];unit_page=field.get('unit_evidence_page',page)
                if not 1<=page<=len(pages) or not 1<=unit_page<=len(pages):raise DataSourceError('Financial evidence page outside PDF')
                normalized=compact(pages[page-1]);unit_text=compact(pages[unit_page-1])
                if METRIC_UNITS.get(field['name'])!=field['unit']:
                    raise DataSourceError('Financial metric/unit schema mismatch')
                if compact(field['source_label']) not in normalized:raise DataSourceError('Financial label missing from reviewed page')
                value=Decimal(field['reported_decimal'])
                if not value.is_finite() or value not in page_numbers(pages[page-1]):raise DataSourceError('Financial value missing from reviewed page')
                if field['unit']=='CNY_yuan' and ('单位:元' not in unit_text or '人民币' not in unit_text):
                    raise DataSourceError('Financial CNY/yuan evidence missing')
                if field['unit']=='share' and '单位:股' not in unit_text:raise DataSourceError('Share-count unit evidence missing')
                if field['unit']=='CNY_yuan_per_share' and '元/股' not in unit_text:raise DataSourceError('EPS unit evidence missing')
                if field['unit']=='percent' and '%' not in unit_text:raise DataSourceError('Percentage unit evidence missing')
                if field.get('prior_reported_decimal') is not None and Decimal(field['prior_reported_decimal']) not in page_numbers(pages[page-1]):
                    raise DataSourceError('Financial comparison value missing from reviewed page')
                semantic=validate_semantic_row(field,entry,pages)
                fields.append({**field,'value':float(value),'document_sha256':digest,'source_url':source,
                               'semantic_verification':semantic})
            for context in entry.get('contexts',[]):
                if compact(context['source_text']) not in compact(pages[context['page']-1]):
                    raise DataSourceError('Issuer explanation missing from reviewed page')
                contexts.append(context)
        provenance={'document_sha256':digest,'source_url':source,'local_document_path':str(path),
                    'source_origin':'designated_primary_disclosure','pages':len(pages),'review_matches_current_bytes':reviewed,
                    'publication_date_source':entry['publication_date_source'],'original_publication_time_known':False}
        doc=Observation(self.name,'issuer_financial_document',identity+'|'+period_end,stamp,
            {**provenance,'company_name':entry['company_name'],'period_start':entry['period_start'],'period_end':period_end},
            publication=entry['publication_date'],unit='original_primary_document',currency='CNY',
            source_url=source,quality='primary_document_reviewed' if reviewed else 'primary_document_needs_review')
        rows=[doc]
        if reviewed:
            rows.append(Observation(self.name,'financials_primary',identity,period_end,
                {'fields':fields,'contexts':contexts,'period_start':entry['period_start'],'period_end':period_end,
                 'period_type':entry['period_type'],'period_months':entry['period_months'],'publication_precision':entry['publication_precision'],
                 'audited':entry['audited'],'unit_state':'reviewed_fields_only','coverage':'one_issuer_and_period',
                 'provider_fields_not_globally_verified':True,'provenance':provenance},
                publication=entry['publication_date'],unit='field_specific_units_periods_and_scopes',currency='CNY',
                quality='primary_financial_fields_reviewed',source_url=source))
        return self.client.bind_rows(rows)
