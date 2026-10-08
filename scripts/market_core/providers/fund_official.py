"""Issuer-owned product facts, dated source references and explicit unresolved contract fields."""
import hashlib
import io
import re
import unicodedata
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlsplit

from ..http import DataSourceError, HttpClient
from ..models import Observation
from ..parsing import html_text


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.rows=[]
        self.current=None

    def handle_starttag(self,tag,attrs):
        if tag=="a":
            self.current={"url":dict(attrs).get("href", ""),"title":""}

    def handle_data(self,text):
        if self.current is not None: self.current["title"]+=text

    def handle_endtag(self,tag):
        if tag=="a" and self.current is not None:
            self.current["title"]=self.current["title"].strip()
            self.rows.append(self.current)
            self.current=None


class ChinaAMCFundProvider:
    name="chinaamc_official"

    def __init__(self,client=None,document_dir=None):
        self.client=client or HttpClient(user_agent="Mozilla/5.0",timeout=12,retries=1,
            min_interval_by_host={"www.chinaamc.com":0.4,"fund.chinaamc.com":0.4})
        self.document_dir=Path(document_dir) if document_dir else None

    def _document(self,announcement):
        page,source=self.client.get_text(announcement["url"])
        announcement_receipts = self.client.source_receipts()
        links=Links(); links.feed(page)
        candidates=[urljoin(source,row["url"]) for row in links.rows if urlsplit(row["url"]).path.lower().endswith(".pdf")]
        if not candidates: raise DataSourceError("Official notice has no PDF attachment")
        url=candidates[0]
        if not (urlsplit(url).hostname or "").endswith("chinaamc.com"):
            raise DataSourceError("Attachment is outside the configured issuer domain")
        data,final=self.client.get_bytes(url)
        if not data.startswith(b"%PDF"): raise DataSourceError("Attachment is not a PDF")
        from pypdf import PdfReader
        reader=PdfReader(io.BytesIO(data))
        pages=[page.extract_text() or "" for page in reader.pages]
        digest=hashlib.sha256(data).hexdigest()
        if self.document_dir:
            self.document_dir.mkdir(parents=True,exist_ok=True)
            (self.document_dir/(digest+".pdf")).write_bytes(data)
        return {"url":final,"sha256":digest,"pages":pages,"publication_date":announcement["date"],"title":announcement["title"],
                'source_receipts':announcement_receipts + self.client.source_receipts()}

    def fetch_evidence(self,code):
        if not re.fullmatch(r"\d{6}",code): raise ValueError("Exact six-digit share-class code is required")
        collected=datetime.now(timezone.utc).isoformat()
        overview_url=f"https://www.chinaamc.com/fund/{code}/"
        page,_=self.client.get_text(overview_url,encoding="gbk")
        overview_receipts = self.client.source_receipts()
        overview=html_text(page)
        name=re.search(r"([^\n]+)\n[（(]基金代码[：:]\s*"+code+r"\s*[）)]",overview)
        identity=re.search(r"基金代码[：:]\s*(\d{6})(?!\d)",overview)
        if not name or not identity or identity.group(1).strip()!=code:
            raise DataSourceError("Issuer page does not establish the requested share-class identity")
        name=name.group(1).strip()
        currency=re.search(r"交易币种：\s*([^\n]+)",overview)
        if not currency: raise DataSourceError("Issuer page currency missing")
        currency={"人民币":"CNY","美元":"USD","港币":"HKD","欧元":"EUR"}.get(currency.group(1).strip(),"unknown")
        share=re.search(r"([A-Z])(?:[（(].*[）)])?$",name)
        kind="etf_link" if "ETF联接" in name else "mixed" if "混合" in name else "bond" if "债券" in name else "money" if "货币" in name else "unknown"
        nav_date=re.search(r"净值\s*[（(]\s*(\d{4}-\d{2}-\d{2})\s*[）)]",overview)
        subscription=re.search(r"交易状态\s*([^\n]+)",overview)

        fee_url=f"https://www.chinaamc.com/fund/{code}/jijinfeilv.shtml"
        fee_html,_=self.client.get_text(fee_url,encoding="gbk")
        fee_receipts = self.client.source_receipts()
        fee_text=html_text(fee_html)
        start=fee_text.find("申购费率")
        end=fee_text.find("基金工具",start)
        fee_block=fee_text[start:end] if start>=0 and end>start else ""
        fee_rows=[]
        lines=[line.strip() for line in fee_block.splitlines() if line.strip()]
        for index,line in enumerate(lines[:-1]):
            if re.fullmatch(r"(?:\d+(?:\.\d+)?%|[\d,.]+元/笔)",lines[index+1]):
                fee_rows.append({"condition":line,"quoted_fee":lines[index+1]})
        if not fee_rows: raise DataSourceError("Issuer fee schedule schema is unrecognized")

        listing_url=f"https://fund.chinaamc.com/product/publishGgList.do?fundcode={code}"
        listings,_=self.client.get_text(listing_url)
        listing_receipts = self.client.source_receipts()
        parser=Links(); parser.feed(listings)
        notices=[]
        for row in parser.rows:
            url=urljoin(listing_url,row["url"])
            dated=re.search(r"/c/(\d{4}-\d{2}-\d{2})/",url)
            if dated: notices.append({"url":url,"date":dated.group(1),"title":row["title"]})
        notices.sort(key=lambda row:row["date"],reverse=True)
        summaries=[]
        for row in notices:
            if "产品资料概要" not in row["title"]: continue
            codes=re.findall(r"(?<!\d)\d{6}(?!\d)",row["title"])
            if name in row["title"] or (len(codes)>=2 and codes[1]==code): summaries.append(row)
        reports=[row for row in notices if "中期报告" in row["title"] or "季度报告" in row["title"]]
        prospectuses=[row for row in notices if "招募说明书" in row["title"]]
        documents={}
        for label,items in (("summary",summaries),("report",reports),("prospectus",prospectuses)):
            if items: documents[label]=self._document(items[0])
        summary_text="\n".join(documents.get("summary",{}).get("pages",[]))
        if summary_text:
            summary_code=re.search(r"下属基金代码\s*(\d{6})",summary_text)
            if summary_code and summary_code.group(1)!=code:
                raise DataSourceError("Official summary belongs to a different share class")
        report_text="\n".join(documents.get("report",{}).get("pages",[]))
        prospectus=unicodedata.normalize("NFKC","\n".join(documents.get("prospectus",{}).get("pages",[])))

        benchmark=re.search(r"本基金的标的指数为([^。\n]+)",summary_text)
        underlying="sh000300" if benchmark and benchmark.group(1).replace(" ","")=="沪深300指数" else "unknown"
        target="unknown"
        target_section=re.search(r"目标基金基本情况(.{0,1400})",report_text,re.S)
        if target_section:
            match=re.search(r"基金主代码\s*(\d{6})",target_section.group(1))
            if match: target=match.group(1)
        if target!="unknown": target=("sh" if target.startswith("5") else "sz")+target
        fee_base="unknown"
        if "目标ETF份额所对应资产净值" in summary_text.replace(" ","").replace("\n",""):
            fee_base="net_assets_excluding_held_target_ETF_assets"
        dealing={"opening_days":"每个开放日" if "每个开放日" in summary_text else "unknown",
                 "confirmation":"unknown","redemption_payment":"unknown","source_url":documents.get("prospectus",{}).get("url",listing_url)}
        for key,pattern in (("confirmation",r"T\+1日.{0,50}(?:确认|有效性)"),("redemption_payment",r"T\+[0-9]+日.{0,60}(?:支付|划往|划出|付款)")):
            match=re.search(pattern,prospectus.replace("\n",""))
            if match: dealing[key]=match.group(0)
        dealing["normal_case_only"]=True
        nav_calendar=None
        compact_prospectus=prospectus.replace(' ','').replace('\n','')
        if ('工作日:上海证券交易所和深圳证券交易所的正常交易日' in compact_prospectus
                and '不晚于每个开放日的次日' in compact_prospectus):
            nav_calendar={'verified':True,'valuation_market':'CN_CASH','publication_rule':'next_calendar_day_end',
                          'normal_case_only':True,'source':{'source_url':documents['prospectus']['url'],
                                                          'document_sha256':documents['prospectus']['sha256'],
                                                          'publication_date':documents['prospectus']['publication_date']}}
        value={"fund_name":name,"fund_type":kind,"share_class":share.group(1) if share else "unknown","currency":currency,
            "underlying_identity":underlying,"benchmark_name":benchmark.group(1) if benchmark else "unknown","target_etf":target,
            "fee_terms":{"rows":fee_rows,"charge_base":fee_base,"source_url":fee_url,"platform_discount_verified":False},
            "dealing_rules":dealing,"subscription_status":subscription.group(1).strip() if subscription else "unknown",
            "subscription_status_as_of":"unknown","subscription_status_read_at":collected,
            "page_NAV_valuation_date":nav_date.group(1) if nav_date else "unknown",
            "subscription_status_clock_not_inferred_from_NAV":True,"subscription_limits_verified":False,
            "documents":{key:{k:v for k,v in doc.items() if k!="pages"} for key,doc in documents.items()},
            'nav_calendar_contract':nav_calendar,
            "field_sources":{"identity":overview_url,"currency":overview_url,"fees":fee_url,"benchmark":documents.get("summary",{}).get("url"),"target_etf":documents.get("report",{}).get("url")}}
        product=Observation(self.name,"fund_product",code,collected,value,unit="source_grounded_product_terms",currency=currency,
            quality="issuer_source_with_explicit_field_gaps",source_url=overview_url,
            raw={"retrieved_at":collected,"as_of_means":"retrieval_time_not_uniform_term_effective_date","original_publication_time_known":False})
        observations=[product]
        product_receipts = overview_receipts + fee_receipts + listing_receipts
        for document in documents.values():
            product_receipts += document['source_receipts']
        self.client.bind_rows([product], product_receipts)
        for notice in notices:
            observations.append(Observation(self.name,"fund_announcement",code+"#"+notice["url"].rsplit("/",1)[-1],notice["date"],
                {"fund_code":code,**notice},unit="issuer_notice",source_url=notice["url"],publication=notice["date"],quality="issuer_notice_date_only"))
            self.client.bind_rows(observations[-1:], listing_receipts)
        return observations
