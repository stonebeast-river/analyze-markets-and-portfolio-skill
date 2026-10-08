"""Qualitative product mapping after market and product seals; no invented market weights."""
import hashlib,json
from pathlib import Path

from .lineage import canonical
from .workflow import write_new


def read_portfolio_mapping(directory):
    """Rebuild the qualitative projection from its linked sealed sources."""
    root=Path(directory).resolve()
    market=json.loads((root/'market-view.json').read_text(encoding='utf-8'))
    market_seal=json.loads((root/'market-view-seal.json').read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(market)).hexdigest()!=market_seal['sha256']:raise ValueError('Market view changed')
    dossier=json.loads((root/'product-dossier.json').read_text(encoding='utf-8'))
    dossier_seal=json.loads((root/'product-dossier-seal.json').read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(dossier)).hexdigest()!=dossier_seal['sha256']:raise ValueError('Product dossier changed')
    private=json.loads((root/'portfolio-inputs.private.json').read_text(encoding='utf-8'))
    if private['market_view_sha256']!=market_seal['sha256'] or dossier['market_view_sha256']!=market_seal['sha256']:
        raise ValueError('Portfolio/product layer belongs to another market view')
    products={item['code']:item for item in dossier['products']};mapped=[]
    for position in private['portfolio']['positions']:
        code=position.get('code');item=products.get(code)
        rows=item['evidence']['observations'] if item else []
        product=next((row['value'] for row in reversed(rows) if row['dataset']=='fund_product'),{})
        mapped.append({'code':code,'name':product.get('fund_name','unverified exact-share product'),
                       'share_class':product.get('share_class','unknown'),'currency':product.get('currency','unknown'),
                       'underlying_identity':product.get('underlying_identity','unknown'),
                       'target_etf':product.get('target_etf','unknown'),
                       'product_readiness':item['evidence']['status'] if item else 'missing',
                       'contract_missing':item['evidence']['missing'] if item else ['exact_share_product_evidence'],
                       'amount_basis':position.get('amount_basis','unspecified_user_reported_amount'),
                       'current_market_value_verified':False,'market_weight':None})
    groups={}
    for item in mapped:
        identity=item['underlying_identity']
        if identity!='unknown':groups.setdefault(identity,[]).append(item['code'])
    value={'market_view_sha256':market_seal['sha256'],'product_dossier_sha256':dossier_seal['sha256'],
           'positions':mapped,'same_underlying_groups':groups,'cross_index_overlap':'requires dated constituent/portfolio weights',
           'market_view_unchanged':True,'quantitative_weights_verified':False,'trade_execution':False,
           'interpretation':'Authoritative identities mapped to verified product fields; original reported amounts are not converted to current market values'}
    return value


def map_portfolio(directory):
    root=Path(directory).resolve()
    value=read_portfolio_mapping(root)
    mapped=value['positions']
    write_new(root/'portfolio-mapping.private.json',value)
    return {'positions_mapped':len(mapped),'complete_product_contracts':sum(row['product_readiness']=='ready_for_research' for row in mapped),
            'market_view_unchanged':True,'quantitative_weights_verified':False,'private_amounts_printed':False}
