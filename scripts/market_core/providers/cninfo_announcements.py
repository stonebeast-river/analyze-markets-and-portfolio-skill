"""Primary CNINFO issuer catalogue with bounded complete pagination and document bytes."""
import hashlib,io,json,math,re
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urljoin,urlsplit
from ..http import HttpClient,DataSourceError
from ..http import redact_error
from ..models import Observation
from ..symbols import normalize_cn_symbol
from ..conventions import SHANGHAI

class CninfoAnnouncementsProvider:
    name='cninfo_primary_announcements'
    def __init__(self,document_dir,client=None):
        self.document_dir=Path(document_dir)
        self.client=client or HttpClient(user_agent='Mozilla/5.0',timeout=18,retries=0)

    def fetch_catalogue(self,symbol,*,start_date,end_date,max_pages=10):
        identity=normalize_cn_symbol(symbol,stock_only=True);code=identity[2:]
        plate={'sh':'sse','sz':'szse','bj':'bjse'}.get(identity[:2])
        if not plate or not 1<=max_pages<=100 or start_date>end_date:raise ValueError('Invalid issuer/date/page scope')
        page_url=f'https://www.cninfo.com.cn/new/disclosure/stock?plate={plate}&stockCode={code}'
        text,page_source=self.client.get_text(page_url)
        if urlsplit(page_source).hostname!='www.cninfo.com.cn':raise DataSourceError('Issuer page redirect outside primary host')
        if not re.search(r'var\s+stockCode\s*=\s*["\']'+re.escape(code)+r'["\']',text):raise DataSourceError('Primary page stock identity mismatch')
        org=re.search(r'var\s+orgId\s*=\s*["\']([^"\']+)',text)
        if not org:raise DataSourceError('Primary issuer organization identity missing')
        orgid=org.group(1);identity_refs=self.client.source_receipts();refs=list(identity_refs)
        rows=[];ids=set();total=None;expected_pages=None;received_pages=0;failure=''
        for page in range(1,max_pages+1):
            form={'stock':code+','+orgid,'tabName':'fulltext','pageSize':'30','pageNum':str(page),'column':plate,
                  'category':'','plate':'','seDate':start_date+'~'+end_date,'searchkey':'','secid':'',
                  'sortName':'','sortType':'','isHLtitle':'true'}
            try:
                payload,source=self.client.post_form_json('https://www.cninfo.com.cn/new/hisAnnouncement/query',form,headers={'Referer':page_url})
                if urlsplit(source).hostname!='www.cninfo.com.cn':raise DataSourceError('Catalogue redirect outside primary host')
                page_refs=self.client.source_receipts();items=payload.get('announcements') or []
                reported=payload.get('totalAnnouncement')
                if type(reported)!=int or reported<0 or not isinstance(items,list):raise DataSourceError('Invalid primary catalogue count')
                if total is None:total=reported;expected_pages=max(1,math.ceil(total/30))
                elif reported!=total:raise DataSourceError('Catalogue changed count during pagination')
                pending=[];page_ids=set()
                for item in items:
                    if item.get('secCode')!=code or item.get('orgId')!=orgid:raise DataSourceError('Cross-issuer announcement row')
                    aid=str(item.get('announcementId',''))
                    if not aid.isdigit() or aid in ids or aid in page_ids:raise DataSourceError('Missing/duplicate announcement identity')
                    stamp=item.get('announcementTime')
                    if type(stamp) not in (int,float):raise DataSourceError('Missing announcement timestamp field')
                    date=datetime.fromtimestamp(stamp/1000,timezone.utc).astimezone(SHANGHAI).date().isoformat()
                    if not start_date<=date<=end_date:raise DataSourceError('Announcement outside requested publication dates')
                    pdf=urljoin('https://static.cninfo.com.cn/',item.get('adjunctUrl',''))
                    if urlsplit(pdf).hostname!='static.cninfo.com.cn' or urlsplit(pdf).scheme!='https' or not urlsplit(pdf).path.lower().endswith('.pdf'):
                        raise DataSourceError('Unregistered announcement document URL')
                    title=re.sub('<[^>]*>','',str(item.get('announcementTitle','')))
                    value={'symbol':identity,'issuer_code':code,'issuer_name':item.get('secName'),'org_id':orgid,
                        'announcement_id':aid,'title':title,'publication_date':date,'provider_timestamp_milliseconds':stamp,
                        'original_publication_time_known':False,'publication_precision':'date_only',
                        'document_url':pdf,'catalogue_page':page,'content_reviewed':False,
                        'economic_effect_verified':False,'query_form':form}
                    row=Observation(self.name,'announcement_catalogue_entry',identity+'|'+aid,date,value,
                        publication=date,unit='primary_disclosure_catalogue',quality='primary_catalogue_only',source_url=pdf,raw=item)
                    self.client.bind_rows([row],[*identity_refs,*page_refs]);pending.append(row);page_ids.add(aid)
                expected_count=min(30,max(0,total-(page-1)*30))
                if len(items)!=expected_count:raise DataSourceError('Primary catalogue page has missing rows')
                ids.update(page_ids);rows.extend(pending);refs.extend(page_refs);received_pages+=1
                if page>=expected_pages:break
            except Exception as error:
                failure=redact_error(str(error))
                if self.client.archive and self.client.last_response_receipt and self.client.last_response_receipt.get('status') in {'http_ok','cache_hit'}:
                    self.client.archive.reject(self.client.last_response_receipt,'Primary announcement page failed identity/coverage validation')
                break
        complete=not failure and received_pages==expected_pages and len(rows)==total
        audit={'symbol':identity,'start_date':start_date,'end_date':end_date,'org_id':orgid,
            'expected_records':total,'received_records':len(rows),'expected_pages':expected_pages,'received_pages':received_pages,
            'status':'complete_catalogue_window' if complete else 'partial_catalogue_window','error':failure,
            'latest_publication_date':max((r.as_of for r in rows),default=None),
            'scope':'Exact issuer fulltext announcements in requested date range; excludes other channels and content validation',
            'content_review_complete':False,'original_publication_times_verified':False}
        summary=Observation(self.name,'issuer_announcement_audit',identity,datetime.now(timezone.utc).isoformat(),audit,
            unit='bounded_primary_catalogue_coverage',quality='primary_catalogue_audit',source_url=page_url)
        self.client.bind_rows([summary],refs)
        return rows,summary

    def fetch_document(self,catalogue_row):
        value=catalogue_row.value if hasattr(catalogue_row,'value') else catalogue_row['value']
        url=value['document_url'];body,source=self.client.get_bytes(url)
        if urlsplit(source).hostname not in {'static.cninfo.com.cn','dataclouds.cninfo.com.cn'} or not body.startswith(b'%PDF'):
            raise DataSourceError('Primary announcement document host/format mismatch')
        from pypdf import PdfReader
        pages=[p.extract_text() or '' for p in PdfReader(io.BytesIO(body)).pages]
        head=re.sub(r'\s+','', '\n'.join(pages)[:6000]);code=value['issuer_code']
        issuer_name=re.sub(r'\s+','',value.get('issuer_name',''))
        if not issuer_name or not re.search(r'(?<!\d)'+re.escape(code)+r'(?!\d)',head) or issuer_name not in head:
            raise DataSourceError('Document issuer code/name missing')
        digest=hashlib.sha256(body).hexdigest();self.document_dir.mkdir(parents=True,exist_ok=True)
        path=self.document_dir/(digest+'.pdf')
        if path.exists() and path.read_bytes()!=body:raise DataSourceError('Archived document filename/content mismatch')
        if not path.exists():path.write_bytes(body)
        text_path=self.document_dir/(digest+'.txt')
        if not text_path.exists():text_path.write_text('\n\n'.join(f'PAGE {i+1}\n{t}' for i,t in enumerate(pages)),encoding='utf-8')
        record={**value,'document_sha256':digest,'source_url':source,'local_pdf':str(path),'local_text':str(text_path),
                'pages':len(pages),'content_reviewed':False,'economic_effect_verified':False}
        row=Observation(self.name,'issuer_announcement_document',value['symbol']+'|'+value['announcement_id'],value['publication_date'],record,
            publication=value['publication_date'],unit='original_primary_document',quality='primary_document_content_unreviewed',source_url=source)
        previous=catalogue_row.source_receipts if hasattr(catalogue_row,'source_receipts') else catalogue_row.get('source_receipts',[])
        return self.client.bind_rows([row],[*previous,*self.client.source_receipts()])[0]
