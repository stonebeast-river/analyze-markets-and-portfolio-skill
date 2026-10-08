"""Immutable issuer documents and review-bound facts for heterogeneous fund websites."""
import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime,timezone
from pathlib import Path
from urllib.parse import urlsplit

from ..http import DataSourceError,HttpClient
from ..models import Observation


class FundDocumentProvider:
    name='issuer_fund_documents'

    def __init__(self,registry_path,document_dir,client=None):
        self.registry_path=Path(registry_path)
        self.document_dir=Path(document_dir)
        self.client=client or HttpClient(user_agent='Mozilla/5.0',timeout=15,retries=1)

    def fetch_evidence(self,code):
        registry=json.loads(self.registry_path.read_text(encoding='utf-8-sig'))
        entry=registry.get('funds',{}).get(code)
        if entry is None:raise DataSourceError('No reviewed issuer source registry for the requested share class')
        from pypdf import PdfReader
        date=datetime.now(timezone.utc).isoformat();observations=[];matched_documents={}
        for item in entry['documents']:
            host=urlsplit(item['url']).hostname or ''
            origin=item.get('source_origin','issuer_host')
            if origin not in {'issuer_host','distributor_disclosure_copy'}:
                raise DataSourceError('Document source origin is not registered')
            allowed=entry.get('disclosure_copy_hosts',[]) if origin=='distributor_disclosure_copy' else entry['issuer_document_hosts']
            if host not in allowed:raise DataSourceError('Document host is outside the reviewed source registry')
            data,source=self.client.get_bytes(item['url'])
            if (urlsplit(source).hostname or '') not in allowed:
                raise DataSourceError('Document redirect leaves the reviewed source registry')
            source_receipts = self.client.source_receipts()
            if not data.startswith(b'%PDF'):raise DataSourceError('Issuer attachment did not return PDF data')
            digest=hashlib.sha256(data).hexdigest()
            self.document_dir.mkdir(parents=True,exist_ok=True)
            path=self.document_dir/(digest+'.pdf')
            if not path.exists():path.write_bytes(data)
            pages=[page.extract_text() or '' for page in PdfReader(io.BytesIO(data)).pages]
            normalized=unicodedata.normalize('NFKC','\n'.join(pages))
            identity_seen=bool(re.search(r'(?<!\d)'+re.escape(code)+r'(?!\d)',normalized))
            review=item.get('reviewed_facts') or {}
            expected_share=review.get('facts',{}).get('share_class')
            if item['kind']=='summary':
                own_code=re.search(r'下属基金代码\s*(\d{6})(?!\d)',normalized[:2000])
                if own_code and own_code.group(1)!=code:
                    raise DataSourceError('Summary own subordinate share code differs from requested code')
                currency_title=re.search(r'(?:人民币|美元|港元|港币)\s*([A-Z])(?=[)）\s]|基金|份额)',normalized[:250])
                title_share=currency_title or re.search(r'([A-Z])\s*类\s*份额',normalized[:600])
                if expected_share and title_share and title_share.group(1)!=expected_share:
                    raise DataSourceError('Summary title belongs to a different share class')
                if origin=='distributor_disclosure_copy' and (not title_share or not re.search(
                        r'基金代码\s*'+re.escape(title_share.group(1))+r'\s*'+re.escape(code)+r'(?!\d)',normalized)):
                    raise DataSourceError('Disclosure copy lacks exact class-specific code identity')
            bridge_verified=False
            if item.get('require_share_code',True) and not identity_seen:
                bridge=item.get('identity_bridge') or {}
                prior=matched_documents.get(bridge.get('sha256'))
                phrase=unicodedata.normalize('NFKC',bridge.get('fund_family_name',''))
                compact=lambda text:re.sub(r'\s+','',text)
                bridge_verified=bool(prior and prior['exact_share_code_seen'] and prior['review_verified']
                    and bridge.get('share_code')==code and phrase and compact(phrase) in compact(normalized)
                    and compact(phrase) in compact(prior['text']))
                if not bridge_verified:
                    raise DataSourceError('Issuer document lacks exact share code and a verified same-call family bridge')
            verified=review.get('sha256')==digest
            if bridge_verified:
                source_receipts += prior['source_receipts']
            matched_documents[digest]={'text':normalized,'exact_share_code_seen':identity_seen,'review_verified':verified,
                                       'source_receipts':source_receipts,'source_origin':origin,'source_url':source}
            topics={}
            for topic in ('业绩比较基准','管理费','托管费','销售服务费','申购','赎回'):
                contexts=[]
                for index,text in enumerate(pages):
                    if topic not in text:continue
                    for match in list(re.finditer(re.escape(topic),text))[:2]:
                        excerpt=text[max(0,match.start()-70):match.end()+230]
                        contexts.append({'page':index+1,'text':excerpt})
                    if len(contexts)>=5:break
                topics[topic]=contexts[:5]
            value={'code':code,'name':entry['name'],'manager':entry['manager'],'kind':item['kind'],
                   'publication_date':item['publication_date'],'sha256':digest,'pages':len(pages),
                   'source_url':source,'source_registry_verified_at':entry['registry_verified_at'],
                   'registry_currentness':'explicit_dated_registry_not_a_claim_of_latest_available',
                   'facts_verified_against_current_bytes':verified,
                   'identity_method':'exact_code_in_document' if identity_seen else 'same_call_SHA_bound_exact_share_summary',
                   'identity_bridge_verified':bridge_verified,
                   'source_origin':origin,'issuer_origin_verified':origin=='issuer_host',
                   'identity_basis_issuer_origin_verified':origin=='issuer_host' and
                       (not bridge_verified or prior['source_origin']=='issuer_host'),
                   'identity_dependencies':([{'sha256':item['identity_bridge']['sha256'],
                       'source_origin':prior['source_origin'],'source_url':prior['source_url']}]
                       if bridge_verified else []),
                   'reviewed_facts':review.get('facts',{}) if verified else {},'review_topics':topics,
                   'reviewed_field_evidence':review.get('field_evidence',{}) if verified else {},
                   'review_required':not verified}
            observations.append(Observation(self.name,'fund_document',code+'#'+item['kind'],date,value,
                unit='issuer_document_and_review_state',publication=item['publication_date'],
                quality=('disclosure_copy_reviewed_bytes' if verified and origin=='distributor_disclosure_copy'
                         else 'issuer_document_verified_bytes' if verified else 'issuer_document_needs_fact_review'),source_url=source,
                raw={'local_document_sha256':digest,'original_publication_precision':'date_only'}))
            self.client.bind_rows(observations[-1:], source_receipts)
        return observations
