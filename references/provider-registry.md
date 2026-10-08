# Provider registry

Choose one canonical provider per metric, retain explicit alternatives and never merge their values silently. Interface code, current response, schema correctness and continuous-session stability are separate facts. Check `validation-status.md` for dated local results.

| Provider | Implemented coverage | Prerequisite and boundary |
| --- | --- | --- |
| Tencent quote | Mainland stock/index/ETF price snapshot, volume/amount, turnover, PE/PB/cap where supplied, vendor volume ratio, classified inner/outer volume, five-level book | Public undocumented interface; retain vendor units/unknown latency. Index zero books are unavailable. Read-time CN freshness uses the official covered calendar |
| BaoStock | Historical OHLCV/amount, chosen adjustment basis; stock daily turnover/valuation/status | Optional package. Daily/weekly/monthly fields omit minute `time`; stock valuation fields are not requested for indices. Live sample quality is not full coverage |
| Reviewed primary issuer reports | Registered exact issuer/period PDF fields with original SHA, page, currency/unit, accounting scope, flow/point period and reported comparison | Fixed dated registry is not an automatic latest-report discovery or a blanket vendor-unit approval. Changed bytes retain only an unreviewed document. Date-only announcement metadata does not prove historical publication time |
| Tencent daily history | Daily OHLC/volume fallback; qfq/hfq/raw variant explicitly requested | Public undocumented interface. Historical amount is missing. Missing adjusted history fails instead of substituting raw. Index series remain unadjusted |
| Eastmoney daily price/turnover | Matched completed OHLC, volume/amount and turnover for one domestic stock/basis | Input for the named local chip estimate; not downloaded vendor CYQ. Retains HTTP receipts; shares the Eastmoney failure/source family |
| BaoStock corporate actions | Dated adjustment factors and original-unit dividend fields | Factors use the requested window; dividend operate-years are bounded to latest two. Review primary notice/unit/tax scope before cash-return use |
| Tencent public intraday | Stock/index/exchange-fund minute bars and dated supplier transaction aggregates | Separate source identity and immutable HTTP receipts. Stock aggregate pagination covers the supplier window, not exchange Level-2 or individual orders; minute amount remains absent |
| TDX via tdxpy | Explicit market/index routing, bounded minute/daily bars, historical/current transaction API | Optional package/working TCP endpoint. At most 800 observations per request; one transaction page is not a full day. Native-volume assumptions require verification |
| Eastmoney board/flow | Industry/concept/region breadth and vendor order-size flows; stock 1m/1d flow | Shared undocumented interface/failure surface. Preserve supplier definitions; main/large net is not a beneficial-owner or institution identity |
| Eastmoney universe | Bounded stock/ETF listing and provider-filter coverage | Retain totals, pages, limits and failures. Completed provider-filter enumeration is not full-market research coverage |
| Eastmoney fund page | Unit and cumulative NAV, provider distribution text, limited name/code metadata | Aggregator fallback. Currency is unknown until verified for that share class. Cumulative NAV is not reinvested total return. No original publication time is invented |
| FRED | Configured macro/rates/FX observations, metadata and optional vintage identity | Registered key; series-specific units and release/revision lags. Default five series are not a complete macro scan |
| FRED public CSV | Keyless official graph CSV with page units/frequency and explicit FX fixing direction | Different identity from API/vintage results; dates are observation periods, original publication/vintage remains unknown |
| Twelve Data | Configured authorized global OHLCV, including selected ETF proxies | Registered key and current symbol entitlement. Free-tier limits do not grant every index, exchange or commodity |
| Yahoo public chart | Keyless configured global bars, separate adjusted-close series and corporate events | Supplier currency/timezone/basis retained; covered cash venues use the cutoff's own completion calendar, not a later response's current-day metadata. Unfinished daily bars, future events and invalid OHLC are refused. Unsupported instrument/session calendars retain completion_unverified. Futures are not spot data |
| Fund catalogue | Data-only share-class/product catalogue | Catalogue membership does not establish current purchase status or investability |
| Issuer fund documents | Direct ChinaAMC adapter and reviewed heterogeneous issuer-PDF registry | Exact share identity and SHA-bound reviewed facts; latest notices, normal-case exceptions and publication dates remain separate; unresolved codes do not pass by family-name inference |
| Huaan issuer dealing table | Dynamic official landing-page XLS link, declared update date, exact registered share rows and reported subscription/redemption/conversion state | Optional xlrd. Retains original body columns, reversed headings and merged-cell anchors. A dated table does not establish later-notice completeness, platform terms, cross-share aggregation or today's opening calendar |
| Source-grounded import | Official product terms/holdings/distributions, financial/event observations, listings or macro | Direct source and dates required. Manual import retains facts; it does not verify them automatically |

Official releases, exchanges, index providers, fund managers and company filings remain the primary evidence supplement. Use dated web research for facts not yet covered by structured adapters, and retain decision-relevant facts with their source contracts.

## Source ownership

- Tencent owns its live snapshot; BaoStock owns its historical bars/amount/daily metrics when used. The configured Tencent history fallback has a separate name and complete window; its source is shown when used. Never concatenate its bars or fill its absent amounts with BaoStock data.
- Preserve each provider's volume unit and trading-direction method. A local ratio may cancel a consistent volume unit; a notional calculation requires a verified unit conversion.
- The ten configured sector-index proxies can restore a price/volume rotation view when board endpoints fail. They do not restore vendor sector fund flow or constituent-wide breadth.
- QQQ/SPY/GLD and similar instruments are proxies with product costs and their own price basis. Match the actual target benchmark/exposure instead of relabeling them as the index or spot asset.
- Shared Eastmoney wrappers or several descriptions of one event are one data lineage/evidence cluster.

## Not implemented as exact vendor fields

Proprietary BBD/DDX/DDY/DDZ or capital-game algorithms, beneficial-owner identity, exchange-grade Level-2 order reconstruction, full-market tick archives and trained return predictions are absent. A reproducible threshold-based transaction summary is a named alternative measurement, not a synthetic copy of those fields.

AKShare/Tushare/other libraries are possible future adapters, not assumed independent evidence or universally free permissions. Audit the actual source/module/license and required fields before adding one.

## Official technical sources

`chinabond_public_yield_curve`读取[中债公开收益率曲线](https://yield.chinabond.com.cn/cbweb-cbrc-web/cbrc/showCbrc)：当前显示日的国债、AAA商业银行债和AAA短融/中票三个独立曲线，单位是各期限的年化收益率百分数。保留空期限、来源日期和实际HTTP回执；页面日期与表头冲突、单位/期限列改变或身份缺失时拒绝。日终17:30是公布安排，不能补成每个历史点已验证的原始发布时间；该接口没有实现历史vintage或基金收益。

- [BaoStock platform](https://www.baostock.com/) and the installed package's current API implementation
- [mootdx upstream](https://github.com/mootdx/mootdx); use the actual installed tdxpy signatures for the protocol adapter. The old mootdx.com documentation domain no longer served its documentation at this check
- [FRED key requirements](https://fred.stlouisfed.org/docs/api/api_key.html)
- [Twelve Data documentation](https://twelvedata.com/docs) and [current free-tier permissions](https://twelvedata.com/pricing)
- [2026 mainland exchange calendar](https://www.sse.com.cn/disclosure/dealinstruc/closed/c/c_20251222_10802510.shtml)
