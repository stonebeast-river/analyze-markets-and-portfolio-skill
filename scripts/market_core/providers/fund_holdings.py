"""Discover and parse issuer-hosted ChinaAMC interim/annual equity holdings reports."""
import io,re,hashlib
from pathlib import Path
from datetime import datetime,timezone
from urllib.parse import urljoin,urlsplit
from ..http import HttpClient,DataSourceError
from ..models import Observation
from ..fund_holdings import parse_equity_report
from .fund_official import Links


class ChinaAMCHoldingsProvider:
    name='chinaamc_disclosed_holdings'

    def __init__(self,document_dir,client=None):
        self.document_dir=Path(document_dir)
        self.client=client or HttpClient(timeout=15,retries=0,user_agent='Mozilla/5.0')

    def fetch_evidence(self,code,*,as_of=None):
        if not re.fullmatch(r'\d{6}',code):raise ValueError('Exact six-digit fund share code required')
        cutoff=(as_of or datetime.now(timezone.utc).isoformat())[:10]
        url=f'https://www.chinaamc.com/product/publishGgList.do?fundcode={code}'
        text,listing=self.client.get_text(url);refs=self.client.source_receipts();parser=Links();parser.feed(text)
        candidates=[];other_reports=[]
        for row in parser.rows:
            source=urljoin(listing,row['url']);dated=re.search(r'/c/(\d{4}-\d{2}-\d{2})/',source)
            title=re.sub(r'\s+','',row['title'])
            report=re.fullmatch(r'(.+基金)(\d{4})年(?:中期|年度)报告',title)
            if report and dated and dated.group(1)<=cutoff:
                candidates.append({'source':source,'publication_date':dated.group(1),'title':title,'name':report.group(1)})
            elif dated and dated.group(1)<=cutoff and '季度报告' in title:
                other_reports.append({'source':source,'publication_date':dated.group(1),'title':title})
        if not candidates:raise DataSourceError('No supported dated report in returned issuer listing; not proof of no holdings disclosure')
        newest=max(x['publication_date'] for x in candidates);selected=[x for x in candidates if x['publication_date']==newest]
        selected={x['source']:x for x in selected}
        if len(selected)!=1:raise DataSourceError('Latest returned report identity is ambiguous')
        selected=next(iter(selected.values()))
        for source in (listing,selected['source']):self._host(source)
        text,page=self.client.get_text(selected['source']);self._host(page);refs+=self.client.source_receipts()
        parser=Links();parser.feed(text)
        pdfs=list(dict.fromkeys(urljoin(page,x['url']) for x in parser.rows if urlsplit(x['url']).path.lower().endswith('.pdf')))
        if len(pdfs)!=1:raise DataSourceError('Issuer report attachment not unique')
        self._host(pdfs[0]);data,source=self.client.get_bytes(pdfs[0]);self._host(source);refs+=self.client.source_receipts()
        if not data.startswith(b'%PDF'):raise DataSourceError('Issuer report did not return PDF bytes')
        from pypdf import PdfReader
        pages=[p.extract_text() or '' for p in PdfReader(io.BytesIO(data)).pages]
        digest=hashlib.sha256(data).hexdigest()
        try:
            value=parse_equity_report(pages,fund_code=code,expected_name=selected['name'],publication_date=selected['publication_date'],source_url=source,document_sha256=digest)
        except ValueError as error:
            if self.client.archive and self.client.last_response_receipt:
                self.client.archive.reject(self.client.last_response_receipt,str(error))
            raise DataSourceError(str(error)) from error
        self.document_dir.mkdir(parents=True,exist_ok=True);path=self.document_dir/(digest+'.pdf')
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise DataSourceError('Existing immutable holdings PDF is corrupt')
        if not path.exists():path.write_bytes(data)
        value.update({'local_pdf':str(path.resolve()),'retrieved_at':datetime.now(timezone.utc).isoformat(),
            'issuer_report_selection':{'listing_url':listing,'report_page':page,'title':selected['title'],
                'scope':'newest supported annual/interim report in returned issuer listing',
                'newer_unparsed_quarterly_reports':[x for x in other_reports if x['publication_date']>selected['publication_date']],
                'full_listing_pagination_verified':False,'superseding_notice_audit_verified':False,'historical_PIT_verified':False}})
        row=Observation(self.name,'fund_holdings',code,value['report_date'],value,unit='CNY_values_and_net_asset_fractions',
            currency='CNY',publication=value['publication_date'],quality='primary_report_parsed_with_explicit_reconciliation',source_url=source)
        return self.client.bind_rows([row],refs)

    @staticmethod
    def _host(url):
        host=urlsplit(url).hostname or ''
        if not (url.startswith('https://') and (host=='chinaamc.com' or host.endswith('.chinaamc.com'))):
            raise DataSourceError('Holdings source leaves approved issuer domain')
