"""Bind reviewed issuer event facts to actual primary PDF pages, not headline sentiment."""
import hashlib,json,re
from pathlib import Path
from datetime import datetime,timezone
from .models import Observation
from .http import DataSourceError
from .conventions import parse_time,SHANGHAI
from .announcement_selection import GOVERNANCE_REVIEW_TERMS

def compact(value):return re.sub(r'\s+','',value)

def review_issuer_events(store,symbol,registry_path,*,as_of=None):
    cutoff=as_of or datetime.now(timezone.utc).isoformat();reviews=json.loads(Path(registry_path).read_text(encoding='utf-8'))['events']
    docs=[d for d in store.get_observations('issuer_announcement_document',limit=1,as_of=cutoff)
          if d['value'].get('symbol')==symbol]
    result=[]
    for document in docs:
        value=document['value'];key=symbol+'|'+value['announcement_id'];review=reviews.get(key)
        if not review:continue
        body=Path(value['local_pdf']).read_bytes()
        if hashlib.sha256(body).hexdigest()!=review['document_sha256']:
            raise DataSourceError('Event review PDF hash no longer matches '+key)
        from pypdf import PdfReader
        import io
        pages=[p.extract_text() or '' for p in PdfReader(io.BytesIO(body)).pages]
        for evidence in review['page_evidence']:
            page=evidence['page']
            if not 1<=page<=len(pages) or compact(evidence['source_text']) not in compact(pages[page-1]):
                raise DataSourceError('Reviewed issuer event source passage missing '+key)
        facts={**review,'symbol':symbol,'announcement_id':value['announcement_id'],
            'title':value['title'],'publication_date':value['publication_date'],'source_url':value['source_url'],
            'original_publication_time_known':False,'issuer_statement_and_page_review_verified':True,
            'economic_forecast_verified':False}
        row=Observation('reviewed_primary_issuer_events','issuer_event_review',key,value['publication_date'],facts,
            publication=value['publication_date'],quality='primary_event_facts_reviewed',unit='fact_specific',source_url=value['source_url'],
            source_receipts=document.get('source_receipts',[]))
        result.append(row)
    return result

def current_event_context(store,symbol,*,as_of):
    audits=store.get_observations('issuer_announcement_audit',symbol,limit=1,as_of=as_of)
    audit=max(audits,key=lambda d:d['as_of']) if audits else None
    rows=[r for r in store.get_observations('issuer_event_review',limit=1,as_of=as_of) if r['value'].get('symbol')==symbol]
    today=parse_time(as_of).astimezone(SHANGHAI).date().isoformat();contexts=[]
    for row in rows:
        value=row['value'];date=value.get('event_date');status=value.get('status')
        upcoming=bool(date and date>today and status=='scheduled' and value.get('economic_role')=='material_operating_catalyst')
        contexts.append({**value,'upcoming_material_catalyst':upcoming,'record_source_receipts':row.get('source_receipts',[])})
    reviewed_ids={r['announcement_id'] for r in contexts}
    critical=[r['value'] for r in store.get_observations('announcement_catalogue_entry',limit=1,as_of=as_of)
              if r['value'].get('symbol')==symbol and r['value']['announcement_id'] not in reviewed_ids
              and any(term in r['value']['title'] for term in GOVERNANCE_REVIEW_TERMS)]
    return {'catalogue_audit':audit['value'] if audit else None,'reviewed_events':contexts,
        'catalogue_window_complete':bool(audit and audit['value']['status']=='complete_catalogue_window'),
        'all_material_content_reviewed':False,'upcoming_material_catalysts':[r for r in contexts if r['upcoming_material_catalyst']],
        'unreviewed_critical_announcements':critical,
        'scope':'Reviewed primary facts; completed events and passed schedules do not become new demand or growth catalysts'}
