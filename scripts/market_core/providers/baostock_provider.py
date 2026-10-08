from __future__ import annotations

from ..http import DataSourceError
from ..models import Bar, Observation
from ..symbols import normalize_cn_symbol, is_cn_index
from ..conventions import interval_name, price_basis_name
from datetime import datetime,timezone


class BaoStockProvider:
    name = "baostock_free_history"

    @staticmethod
    def _records(result):
        if result.error_code!="0": raise DataSourceError(result.error_msg)
        records=[]
        while result.next(): records.append(dict(zip(result.fields,result.get_row_data())))
        if result.error_code!="0": raise DataSourceError("Source failed while paging: "+result.error_msg)
        return records

    def fetch_industries(self):
        try: import baostock as bs
        except ImportError as exc: raise DataSourceError("Optional dependency missing: pip install baostock") from exc
        login=bs.login()
        if getattr(login,"error_code","")!="0": raise DataSourceError("BaoStock industry login failed")
        try:
            records=self._records(bs.query_stock_industry())
            if not records: raise DataSourceError("No industry mappings returned")
            return [Observation(self.name,'industry_classification',normalize_cn_symbol(row['code'].replace('.','')),
                row['updateDate'],{'name':row.get('code_name'),'industry':row.get('industry'),
                'classification':row.get('industryClassification')},unit='taxonomy',currency='not_applicable',
                source_url='https://www.baostock.com/',quality='provider_taxonomy',raw=row) for row in records]
        finally: bs.logout()

    def fetch_financials(self,symbol,*,year,quarter):
        if quarter not in {1,2,3,4}: raise ValueError("quarter must be 1,2,3 or 4")
        identity=normalize_cn_symbol(symbol,stock_only=True)
        try: import baostock as bs
        except ImportError as exc: raise DataSourceError("Optional dependency missing: pip install baostock") from exc
        login=bs.login()
        if getattr(login,"error_code","")!="0": raise DataSourceError("BaoStock financial login failed")
        try:
            groups={}
            for kind,query in (('profit',bs.query_profit_data),('growth',bs.query_growth_data),('cashflow',bs.query_cash_flow_data)):
                for row in self._records(query(code=identity[:2]+'.'+identity[2:],year=year,quarter=quarter)):
                    if row.get('code')!=identity[:2]+'.'+identity[2:]: raise DataSourceError("Financial identity mismatch")
                    key=(row.get('statDate'),row.get('pubDate'))
                    if not all(key): raise DataSourceError("Financial reporting/publication date missing")
                    group=groups.setdefault(key,{'reports':{},'unit_state':'requires_primary_field_unit_verification',
                        'year':year,'quarter':quarter,'publication_precision':'date_only'})
                    group['reports'][kind]={field:value for field,value in row.items() if field not in {'code','pubDate','statDate'}}
            if not groups: raise DataSourceError("No dated financial statements returned")
            return [Observation(self.name,'financials',identity,stat_date,value,publication=pub_date,
                unit='provider_fields_not_silently_scaled',currency='CNY',source_url='https://www.baostock.com/',
                quality='provider_financials_units_unverified',raw={'statDate':stat_date,'pubDate':pub_date,'original_publication_time_known':False})
                for (stat_date,pub_date),value in sorted(groups.items())]
        finally: bs.logout()

    def fetch_universe(self, *, day):
        try: import baostock as bs
        except ImportError as exc: raise DataSourceError("Optional dependency missing: pip install baostock") from exc
        login=bs.login()
        if getattr(login,"error_code","")!="0": raise DataSourceError("BaoStock universe login failed")
        try:
            result=bs.query_all_stock(day=day)
            if result.error_code!="0": raise DataSourceError("BaoStock universe query failed: "+result.error_msg)
            rows=[]; source_count=0
            while result.next():
                record=dict(zip(result.fields,result.get_row_data())); source_count+=1
                identity=normalize_cn_symbol(record['code'].replace('.',''))
                a_share=identity.startswith(('sh6','sz0','sz3','bj4','bj8','bj92')) and not is_cn_index(identity)
                if not a_share: continue
                rows.append(Observation(self.name,'instrument_listing',identity,day,
                    {'name':record.get('code_name'),'scope':'mainland_A_shares','market':identity[:2],
                     'trade_status':record.get('tradeStatus'),'active_status':'supplier_day_listing'},
                    unit='instrument_metadata',currency='CNY',source_url='https://www.baostock.com/',quality='provider_day_universe',raw=record))
            if result.error_code!="0": raise DataSourceError("BaoStock universe ended with a source error")
            if not rows: raise DataSourceError("No A-share entries in the requested supplier day universe")
            rows.append(Observation(self.name,'universe_coverage','mainland_A_shares',day,
                {'scope':'BaoStock_day_A_share_filter','source_records':source_count,'received':len(rows),'status':'complete_query',
                 'full_market_coverage_verified':False,'exchange_census_reconciled':False},unit='coverage_counts',source_url='https://www.baostock.com/',quality='provider_scope_coverage'))
            return rows
        finally:
            bs.logout()

    def fetch_bars(
        self,
        symbol: str,
        *,
        start_date: str,
        end_date: str,
        frequency: str = "d",
        adjustment: str = "qfq",
    ) -> list[Bar]:
        try:
            import baostock as bs
        except ImportError as exc:
            raise DataSourceError("Optional dependency missing: pip install baostock") from exc
        normalized = normalize_cn_symbol(symbol)
        code = f"{normalized[:2]}.{normalized[2:]}"
        adjust_map = {"hfq": "1", "qfq": "2", "none": "3"}
        if adjustment not in adjust_map:
            raise ValueError("adjustment must be qfq, hfq, or none")
        login = bs.login()
        if getattr(login, "error_code", "") != "0":
            raise DataSourceError(f"BaoStock login failed: {getattr(login, 'error_msg', '')}")
        normalized_interval = interval_name(frequency)
        frequency = {"1d": "d", "1w": "w", "1mo": "m", "5m": "5", "15m": "15", "30m": "30", "60m": "60"}.get(normalized_interval)
        if frequency is None:
            raise ValueError("BaoStock supports d/w/m or 5/15/30/60-minute bars")
        fields = "date,code,open,high,low,close,volume,amount,adjustflag"
        if frequency not in {"d", "w", "m"}:
            if is_cn_index(normalized):
                raise DataSourceError("BaoStock index minute bars are not verified; use the explicit index adapter")
            fields = "date,time,code,open,high,low,close,volume,amount,adjustflag"
        try:
            result = bs.query_history_k_data_plus(
                code, fields, start_date=start_date, end_date=end_date,
                frequency=frequency, adjustflag=adjust_map[adjustment],
            )
            if result.error_code != "0":
                raise DataSourceError(f"BaoStock query failed: {result.error_msg}")
            rows: list[Bar] = []
            while result.next():
                item = dict(zip(result.fields, result.get_row_data()))
                actual_basis = {"1": "hfq", "2": "qfq", "3": "unadjusted"}.get(item.get("adjustflag"))
                if actual_basis is None:
                    raise DataSourceError("BaoStock returned no recognized adjustment flag")
                is_index = is_cn_index(normalized)
                if not is_index and actual_basis != price_basis_name(adjustment):
                    raise DataSourceError("BaoStock response adjustment differs from the requested stock basis")
                timestamp = item.get("date", "")
                if frequency not in {"d", "w", "m"} and item.get("time"):
                    raw_time = item["time"]
                    timestamp = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]}T{raw_time[8:10]}:{raw_time[10:12]}:{raw_time[12:14]}"
                rows.append(
                    Bar(
                        provider=self.name,
                        symbol=normalized,
                        interval=normalized_interval,
                        timestamp=timestamp,
                        open=float(item["open"]), high=float(item["high"]),
                        low=float(item["low"]), close=float(item["close"]),
                        volume=float(item["volume"]) if item.get("volume") else None,
                        amount=float(item["amount"]) if item.get("amount") else None,
                        volume_unit="share", amount_unit="CNY",
                        currency="CNY", price_basis=actual_basis,
                        source_url="https://www.baostock.com/helpDocsHome",
                        quality="provider_reported",
                        raw=item,
                    )
                )
            if not rows:
                raise DataSourceError(f"BaoStock returned no bars for {normalized}")
            return rows
        finally:
            bs.logout()

    def fetch_corporate_actions(self,symbol,*,start_date,end_date):
        """Source-reported factors and dividend records; retain raw unit-bearing fields."""
        from datetime import date
        identity=normalize_cn_symbol(symbol,stock_only=True)
        start,end=date.fromisoformat(start_date),date.fromisoformat(end_date)
        if start>end or (end-start).days>3660:raise ValueError('Use an ordered corporate-action window of at most ten years')
        import baostock as bs
        login=bs.login()
        if login.error_code!='0':raise DataSourceError('BaoStock corporate action login failed')
        rows=[];code=identity[:2]+'.'+identity[2:]
        try:
            for raw in self._records(bs.query_adjust_factor(code,start_date=start_date,end_date=end_date)):
                if raw.get('code')!=code:raise DataSourceError('Adjustment factor identity mismatch')
                day=raw.get('dividOperateDate','')
                if not start_date<=day<=end_date:raise DataSourceError('Adjustment factor outside cutoff')
                rows.append(Observation(self.name,'corporate_adjustment_factors',identity,day,raw,
                    unit='source_factor_fields',currency='CNY',quality='provider_reported',source_url='https://www.baostock.com/',raw=raw))
            for year in range(max(start.year,end.year-1),end.year+1):
                for raw in self._records(bs.query_dividend_data(code,year=str(year),yearType='operate')):
                    if raw.get('code')!=code:raise DataSourceError('Dividend identity mismatch')
                    day=raw.get('dividOperateDate','')
                    if not day or not start_date<=day<=end_date:continue
                    publication=raw.get('dividPlanAnnounceDate','')
                    if publication and publication>end_date:continue
                    rows.append(Observation(self.name,'corporate_dividend_record',identity,day,raw,
                        unit='original_dividend_fields_not_rescaled',currency='CNY',publication=publication,
                        quality='provider_corporate_action_requires_primary_review',source_url='https://www.baostock.com/',raw=raw))
            rows.append(Observation(self.name,'corporate_action_coverage',identity,end_date,
                {'factor_start':start_date,'factor_end':end_date,'dividend_operate_years':list(range(max(start.year,end.year-1),end.year+1)),
                 'dividend_original_units_retained':True,'dividend_total_return_not_automatically_calculated':True},
                unit='coverage',source_url='https://www.baostock.com/',quality='source_scope'))
            return rows
        finally:bs.logout()

    def fetch_daily_metrics(
        self, symbol: str, *, start_date: str, end_date: str
    ) -> list[Observation]:
        """Fetch dated valuation, turnover, trading-status and ST fields."""

        try:
            import baostock as bs
        except ImportError as exc:
            raise DataSourceError("Optional dependency missing: pip install baostock") from exc
        normalized = normalize_cn_symbol(symbol)
        if is_cn_index(normalized):
            raise DataSourceError("Stock-specific valuation/status fields do not apply to index bars")
        code = f"{normalized[:2]}.{normalized[2:]}"
        login = bs.login()
        if getattr(login, "error_code", "") != "0":
            raise DataSourceError(f"BaoStock login failed: {getattr(login, 'error_msg', '')}")
        fields = (
            "date,code,turn,pctChg,tradestatus,peTTM,psTTM,pcfNcfTTM,pbMRQ,isST"
        )

        def number(value):
            try:
                return float(value) if value not in (None, "", "-") else None
            except (TypeError, ValueError):
                return None

        try:
            result = bs.query_history_k_data_plus(
                code, fields, start_date=start_date, end_date=end_date,
                frequency="d", adjustflag="3",
            )
            if result.error_code != "0":
                raise DataSourceError(f"BaoStock metrics query failed: {result.error_msg}")
            rows: list[Observation] = []
            while result.next():
                item = dict(zip(result.fields, result.get_row_data()))
                rows.append(
                    Observation(
                        provider=self.name,
                        dataset="cn_daily_valuation_liquidity",
                        identity=normalized,
                        as_of=item.get("date", ""),
                        value={
                            "turnover_pct": number(item.get("turn")),
                            "change_pct": number(item.get("pctChg")),
                            "trade_status": item.get("tradestatus") or "unknown",
                            "pe_ttm": number(item.get("peTTM")),
                            "ps_ttm": number(item.get("psTTM")),
                            "pcf_ncf_ttm": number(item.get("pcfNcfTTM")),
                            "pb_mrq": number(item.get("pbMRQ")),
                            "is_st": item.get("isST") or "unknown",
                        },
                        unit="percent_and_multiples",
                        currency="CNY",
                        latency="end_of_day",
                        quality="provider_reported",
                        source_url="https://www.baostock.com/helpDocsHome",
                        raw=item,
                    )
                )
            if not rows:
                raise DataSourceError(f"BaoStock returned no daily metrics for {normalized}")
            return rows
        finally:
            bs.logout()
