"""Assemble reviewed exact-share terms without hiding conflicts or currentness gaps."""
from datetime import datetime,timezone

from .models import Observation


def known(value):
    if isinstance(value,(dict,list,tuple,set)) and not value:return False
    return value is not None and value!='' and value!='unknown'


def assemble_product(store,code,*,as_of=None):
    cutoff=as_of or datetime.now(timezone.utc).isoformat()
    documents=[row for row in store.get_observations('fund_document',as_of=cutoff,limit=1)
               if row['value'].get('code')==code]
    if not documents:raise ValueError('No exact-share document records exist')
    fields={};sources={};conflicts={};unreviewed=[]
    documents.sort(key=lambda row:(row['value']['publication_date'],row['as_of']))
    for row in documents:
        doc=row['value']
        if not doc.get('facts_verified_against_current_bytes'):
            unreviewed.append({'kind':doc['kind'],'sha256':doc['sha256']});continue
        source={'document_kind':doc['kind'],'document_sha256':doc['sha256'],'publication_date':doc['publication_date'],
                'source_url':doc['source_url'],'retrieved_at':row['as_of'],
                'source_origin':doc.get('source_origin','legacy_source_policy'),
                'issuer_origin_verified':doc.get('issuer_origin_verified',False),
                'identity_basis_issuer_origin_verified':doc.get('identity_basis_issuer_origin_verified',False),
                'identity_dependencies':doc.get('identity_dependencies',[])}
        for field,value in doc.get('reviewed_facts',{}).items():
            if not known(value):continue
            evidence_key={'confirmation_normal_case':'confirmation','redemption_payment_normal_case':'payment',
                          'nav_publication_normal_case':'nav_publication','sales_service_charge_base':'sales_service_base'}.get(field,field)
            evidence=doc.get('reviewed_field_evidence',{}).get(evidence_key)
            if field in fields and fields[field]!=value and sources[field]['publication_date']==source['publication_date']:
                conflicts.setdefault(field,[]).extend([{'value':fields[field],'source':sources[field]},{'value':value,'source':source}])
            fields[field]=value;sources[field]={**source,**({'page_evidence':evidence} if evidence else {})}
    for field in conflicts:fields[field]='unknown'
    relationships=store.get_observations('fund_target_identity',code,limit=1,as_of=cutoff)
    for relationship in relationships:
        value=relationship['value']
        if relationship['quality']=='exact_name_code_bridge_verified' and value.get('exact_family_name_match'):
            if value.get('target_name_from_feeder_document')==fields.get('target_etf_name'):
                fields['target_etf']=value['target_etf']
                sources['target_etf']={'source_url':value['source_url'],
                                       'source_page_sha256':value.get('source_page_sha256',value.get('issuer_page_sha256')),
                                       'source_origin':value.get('source_origin','issuer_page_name_code_bridge'),
                                       'feeder_field_source':value['feeder_field_source'],'retrieved_at':relationship['as_of']}
    for relationship in store.get_observations('fund_underlying_identity',code,limit=1,as_of=cutoff):
        value=relationship['value'];name=value.get('index_name')
        if (relationship['quality']=='exact_index_identity_verified' and value.get('exact_index_name_match')
                and name and name in fields.get('benchmark_name','')):
            fields['underlying_identity']=value['underlying_identity']
            sources['underlying_identity']={'source_url':value['source_url'],'source_pdf_sha256':value['source_pdf_sha256'],
                'evidence_page':value.get('name_evidence_page'),'reference_kind':value['reference_kind'],
                'market_series_available':value.get('market_series_available',False),
                'benchmark_return_variant_independently_matched':value.get('benchmark_return_variant_independently_matched',False),
                'retrieved_at':relationship['as_of']}
    fees={field:value for field,value in fields.items() if any(token in field for token in ('fee_','charge_base','expense_'))}
    fee_gaps=[]
    for prefix in ('management','custody'):
        if not known(fees.get(prefix+'_fee_annual_fraction')):fee_gaps.append(prefix+'_fee')
        if not known(fees.get(prefix+'_charge_base')):fee_gaps.append(prefix+'_charge_base')
    if fees.get('sales_service_fee_annual_fraction',0)>0 and not known(fees.get('sales_service_charge_base')):
        fee_gaps.append('sales_service_charge_base')
    if not known(fees.get('sales_service_fee_annual_fraction')):
        fee_gaps.append('sales_service_fee')
    ongoing_gaps=list(fee_gaps)
    transaction_gaps=[]
    for field in ('subscription_fee_tiers','subscription_charge_base','subscription_fee_calculation',
                  'redemption_fee_tiers','redemption_charge_base','redemption_fee_calculation'):
        if not known(fees.get(field)):transaction_gaps.append(field)
    fee_gaps.extend(transaction_gaps)
    dealing={'opening_days':fields.get('opening_days','unknown'),
             'confirmation':fields.get('confirmation_normal_case','unknown'),
             'redemption_payment':fields.get('redemption_payment_normal_case','unknown'),
             'nav_publication':fields.get('nav_publication_normal_case','unknown'),
             'exceptions':fields.get('dealing_exceptions','unknown'),'normal_case_only':True}
    value={'fund_code':code,'fund_name':documents[-1]['value']['name'],
           'fund_type':fields.get('fund_type','unknown'),'share_class':fields.get('share_class','unknown'),
           'currency':fields.get('currency','unknown'),'underlying_identity':fields.get('underlying_identity','unknown'),
           'target_etf':fields.get('target_etf','unknown'),'target_etf_name':fields.get('target_etf_name','unknown'),
           'benchmark_name':fields.get('benchmark_name','unknown'),'fee_terms':fees,'fee_contract_missing':fee_gaps,
           'fee_coverage':{'ongoing_contract_missing':ongoing_gaps,'transaction_contract_missing':transaction_gaps,
                           'platform_discount_verified':False,
                           'scope':'dated standard ongoing and transaction terms; current platform discounts are separate'},
           'dealing_rules':dealing,'subscription_status':'unknown',
           'dated_subscription_limit':{key:fields[key] for key in ('effective_from','single_account_same_share_class_daily_total_limit',
                                     'covered_transactions','scope','currentness') if key in fields},
           'subscription_currentness_verified':False,'field_sources':sources,'field_conflicts':conflicts,
           'unreviewed_documents':unreviewed,'source_documents':[{'kind':row['value']['kind'],'sha256':row['value']['sha256'],
                                         'publication_date':row['value']['publication_date']} for row in documents],
           'assembly_as_of':cutoff,'currentness':'field-specific dated documents; latest superseding-notice audit is separate',
           'fields_verified':{field:known(fields.get(field)) and field not in conflicts for field in ('currency','share_class','fund_type')},
           'selection_ready':False}
    nav_contract=fields.get('nav_calendar_contract')
    if isinstance(nav_contract,dict) and nav_contract.get('verified'):
        value['nav_calendar_contract']={**nav_contract,'source':sources['nav_calendar_contract']}
    snapshots=store.get_observations('fund_dealing_snapshot',code,limit=1,as_of=cutoff)
    if snapshots:
        latest=snapshots[-1]
        value['dated_manager_dealing_snapshot']={**latest['value'],'source_url':latest['source_url'],
                                               'source_receipts':latest.get('source_receipts',[])}
    if any(doc['kind']=='summary' for doc in unreviewed):
        value['fields_verified']['currency']=False;value['fields_verified']['share_class']=False
    source=next((ref['source_url'] for ref in sources.values()),documents[-1]['source_url'])
    return Observation('issuer_assembled_terms','fund_product',code,cutoff,value,unit='reviewed_field_specific_product_terms',
                       currency=value['currency'],quality='issuer_terms_with_explicit_contract_gaps',source_url=source,
                       raw={'source_document_hashes':[row['value']['sha256'] for row in documents]})


def verified_nav_currency(store,code,*,as_of=None):
    """Return a field contract, not a guessed currency or complete-product approval."""
    as_of=as_of or datetime.now(timezone.utc).isoformat()
    products=store.get_observations('fund_product',code,limit=1,as_of=as_of)
    candidates=[]
    for row in products:
        value=row['value'];currency=value.get('currency')
        if currency not in {'CNY','USD','HKD','EUR','JPY','GBP'}:continue
        if row['provider']=='issuer_assembled_terms':
            if not value.get('fields_verified',{}).get('currency'):continue
            source=value.get('field_sources',{}).get('currency')
            current_docs=[doc['value'] for doc in store.get_observations('fund_document',as_of=as_of,limit=1)
                          if doc['value'].get('code')==code]
            if not source or not any(doc['sha256']==source.get('document_sha256') and doc.get('facts_verified_against_current_bytes') for doc in current_docs):continue
        elif row['provider']=='chinaamc_official':
            source={'source_url':value.get('field_sources',{}).get('currency'),'retrieved_at':row['as_of']}
            if not source['source_url']:continue
        else:continue
        candidates.append({'currency':currency,'source':source,'product_provider':row['provider']})
    if len({item['currency'] for item in candidates})!=1:return {'currency':'unknown','verified':False}
    return {**candidates[-1],'verified':True}
