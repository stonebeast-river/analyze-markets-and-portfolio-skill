"""Freeze the requested product layer after the independent market-view seal."""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path

from .lineage import canonical
from .workflow import read_prepared,write_new
from .research import evidence_pack


def freeze_product_dossier(store,directory,codes):
    target,inputs,_=read_prepared(directory)
    if not (target/'market-view.json').exists() or not (target/'market-view-seal.json').exists():
        raise ValueError('Lock the independent market view before product dossier preparation')
    view=json.loads((target/'market-view.json').read_text(encoding='utf-8'))
    seal=json.loads((target/'market-view-seal.json').read_text(encoding='utf-8'))
    if hashlib.sha256(canonical(view)).hexdigest()!=seal['sha256']:raise ValueError('Independent market view changed')
    product_cutoff=datetime.now(timezone.utc).isoformat()
    products=[]
    for code in codes:
        pack=evidence_pack(store,code,question='fund',window=120,as_of=product_cutoff)
        documents=[row for row in store.get_observations('fund_document',limit=1,as_of=product_cutoff)
                   if row['value'].get('code')==code]
        audits=store.get_observations('fund_notice_audit',code,limit=1,as_of=product_cutoff)
        relationships=store.get_observations('fund_target_identity',code,limit=1,as_of=product_cutoff)
        products.append({'code':code,'evidence':pack,'documents':documents,'notice_audits':audits,
                         'target_identity_bridges':relationships})
    value={'schema_version':1,'market_cutoff':inputs['cutoff'],'product_evidence_cutoff':product_cutoff,'market_view_sha256':seal['sha256'],
           'products':products,'market_view_unchanged':True,'holdings_loaded':False,
           'scope':'requested product comparisons after independent view; incomplete contracts do not authorize action'}
    write_new(target/'product-dossier.json',value)
    digest=hashlib.sha256(canonical(value)).hexdigest();write_new(target/'product-dossier-seal.json',{'sha256':digest})
    return {'product_count':len(products),'product_dossier_sha256':digest,'market_view_unchanged':True,
            'readiness':[{ 'code':row['code'],'status':row['evidence']['status'],'missing':row['evidence']['missing']} for row in products]}
