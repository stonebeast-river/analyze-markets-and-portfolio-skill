"""Fetch analyst-selected missing original documents by exact issuer catalogue IDs."""
from datetime import datetime,timezone
import re
from .providers.cninfo_announcements import CninfoAnnouncementsProvider
from .symbols import normalize_cn_symbol
from .http import redact_error


def fetch_catalogued_documents(store,symbol,ids):
    symbol=normalize_cn_symbol(symbol,stock_only=True)
    if not isinstance(ids,list) or not 1<=len(ids)<=20 or any(not isinstance(x,str) or not re.fullmatch(r'\d+',x) for x in ids) or len(set(ids))!=len(ids):
        raise ValueError('Use one to twenty distinct numeric announcement IDs')
    provider=CninfoAnnouncementsProvider(store.path.parent/'issuer-announcements')
    provider.client.archive=store.response_vault;provider.client.retries=0;results=[]
    cutoff=datetime.now(timezone.utc).isoformat()
    for identity in ids:
        rows=store.get_observations('announcement_catalogue_entry',symbol+'|'+identity,limit=1,as_of=cutoff)
        selected=[r for r in rows if r['value'].get('symbol')==symbol and r['value'].get('announcement_id')==identity]
        if not selected:
            results.append({'announcement_id':identity,'status':'missing_exact_issuer_catalogue_entry'});continue
        began=datetime.now(timezone.utc).isoformat()
        try:
            row=provider.fetch_document(selected[-1]);count=store.upsert_observations([row])
            store.record_run(provider.name,'issuer_document_followup:'+symbol+':'+identity,began,'ok',count)
            results.append({'announcement_id':identity,'status':'original_document_received','record':row.to_dict(),
                            'economic_content_reviewed':False})
        except Exception as error:
            message=redact_error(str(error));store.record_run(provider.name,'issuer_document_followup:'+symbol+':'+identity,began,'failed',0,error=message)
            results.append({'announcement_id':identity,'status':'failed','error':message})
    return {'symbol':symbol,'documents':results,'all_material_content_reviewed':False,'personal_portfolio_used':False}
