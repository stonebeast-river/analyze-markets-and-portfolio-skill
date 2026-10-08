from datetime import datetime, timezone

from ..http import DataSourceError, HttpClient
from ..models import Observation
from ..parsing import assigned_json


class FundCatalogProvider:
    name = "eastmoney_fund_catalog"

    def __init__(self, client=None):
        self.client = client or HttpClient(user_agent="Mozilla/5.0",timeout=12,retries=1)

    def fetch_universe(self):
        text, source = self.client.get_text("https://fund.eastmoney.com/js/fundcode_search.js",encoding="utf-8-sig")
        catalog = assigned_json(text,"r")
        if not isinstance(catalog,list) or not catalog: raise DataSourceError("Fund catalogue is empty")
        date = datetime.now(timezone.utc).date().isoformat()
        rows, codes = [], set()
        for record in catalog:
            if len(record)!=5 or not str(record[0]).isdigit() or len(record[0])!=6:
                raise DataSourceError("Unexpected fund catalogue schema")
            if record[0] in codes: raise DataSourceError("Duplicate fund catalogue code")
            codes.add(record[0])
            rows.append(Observation(self.name,"instrument_listing",record[0],date,
                {"name":record[2],"provider_type":record[3],"search_abbreviation":record[1],"scope":"funds","market":"CN",
                 "active_status":"unknown","share_class_verified":False},
                unit="instrument_metadata",quality="aggregator_catalogue",source_url=source,raw={"row":record}))
        rows.append(Observation(self.name,"universe_coverage","funds",date,
            {"scope":"supplier_fund_catalogue","received":len(rows),"status":"complete_payload",
             "active_investable_universe_verified":False,"full_market_coverage_verified":False},
            unit="coverage_counts",quality="provider_scope_coverage",source_url=source))
        return self.client.bind_rows(rows)
