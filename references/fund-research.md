# Off-exchange fund research

Read this for off-exchange fund comparisons, ETF linkage, QDII, active funds, bonds, money-market funds or fund portfolio analysis.

## Shared market layer, separate product layer

Study the underlying market first. Off-exchange products remain a full research branch; stock/intraday development priority does not remove them. Match the fund's actual exposure before applying market conclusions:

| Product | Underlying evidence | Product evidence |
| --- | --- | --- |
| Index / ETF linkage | Exact index identity, construction, constituents, weights, valuation and relevant market history | Exact share class, target ETF, NAV, tracking difference, cash position, distribution, expenses and dealing rules |
| Active equity / mixed | Relevant market, style, sector and company evidence | Dated asset allocation/holdings, manager strategy/change, concentration and turnover; disclosures are lagged snapshots |
| QDII | Exact foreign benchmark or portfolio, local currency returns, matched FX and relevant calendars | Share-class currency, valuation date, publication lag, hedging where documented, subscription limits and confirmation/settlement rules |
| Bond | Matched curve, maturity/duration, credit spread and issuer evidence | Bond categories, credit/convertible exposure, dated holdings, duration where disclosed, liquidity and redemption terms |
| Money market | Short rates, funding conditions and cash alternatives | Published per-10,000-unit income / seven-day annualized yield where applicable, dealing rules and liquidity limits |
| FOF / multi-asset | Underlying products and asset-class drivers | Look-through weights, overlapping exposure, fees at each layer and manager allocation |

A few disclosed heavy holdings cannot reconstruct today's full active-fund portfolio. A bond fund is not generically a defensive substitute; credit, duration and convertibles have different mechanisms. Keep an explicit unknown when a field is not disclosed rather than estimating it from a fund name.

## Product contract

Use exact fund/share-class code and retain a direct source plus as-of/publication time for material fields:

- fund type and share class; trading/NAV currency;
- exact benchmark, target ETF or underlying exposure and the mapping method;
- published unit NAV, distribution/split events and the applicable return basis;
- dated holdings, asset/region/sector allocation, manager and scale/units when relevant;
- management, custody and sales-service charges, subscription charges and holding-period redemption charges;
- subscription/redemption status, limits, cutoffs, confirmation and settlement rules.

Terms in a prospectus may need the latest change notice. Sales-platform fee discounts or limits require that platform's actual terms; do not infer them from the manager's standard schedule.

`fund_product` observations support the fields `fund_type`, `share_class`, `currency`, `underlying_identity`, `fee_terms`, `dealing_rules`, and `subscription_status`. For active/mixed/bond/FOF selection, add dated `fund_holdings`. Use `import-evidence` with source-grounded JSON observations to retain official documents' facts until a verified manager-specific adapter exists. This import is storage, not automatic verification of the input's truth.

`assemble-fund-product` combines the reviewed exact-share document records with field-specific dates, SHA references and conflicts. A newer known field may replace an earlier unknown field; conflicting known fields of the same date remain unknown. Fee rates, charge bases and normal-case dealing exceptions stay separate. A dated limit notice does not establish current subscription availability without the appropriate later-notice/calendar audit.

Fee coverage includes both ongoing charges and transaction terms. `fee_coverage` separates these gaps: subscription/redemption tiers, their charge bases and calculation rules are required alongside management/custody/sales-service charges. A complete dated standard schedule does not verify a platform discount or current dealing status. Retain the application-day anchor for T+n and whether n counts working or calendar days; payment T+7 must not silently restart at confirmation T+1.

NAV collection verifies the response's own `fS_code` before storage. When a current reviewed product currency contract exists, the collector can bind its exact currency to NAV and retain that field's provenance. This binding does not approve the whole product. A revised/unreviewed identity document invalidates the old binding. A family prospectus without a share code can use an explicit same-call bridge only when the matching share summary's current SHA, exact code and legal family name all match; absent or changed bridge evidence rejects the document.

A legally disclosed distributor copy can supply reviewed original-document fields when explicitly registered as `distributor_disclosure_copy`. It uses a separate approved-host list, retains that origin, and verifies the summary's class-specific code and title. A C summary containing a family A code does not establish the requested A share. `issuer_origin_verified` describes the document host; `identity_basis_issuer_origin_verified` and `identity_dependencies` separately describe the share-identity bridge. An issuer-hosted family prospectus does not erase a distributor-copy identity dependency. Preserve these distinctions near the resulting claims.

Keep publisher index identities separate from exchange tickers and derivative return variants. For example, the reviewed 012552 documents plus primary exchange/index files map its target to sz159310 and its named index to CSI:H30007; H20007 is the distinct full-return derivative. This identity bridge alone does not provide an index price series, current constituents or an independently matched fund benchmark-return series. Do not strip an opaque publisher prefix into an unrelated stock code or substitute the target ETF's market price for its index/NAV.

After locking the independent market view, `freeze-product-dossier --directory <run> <codes>` creates a separately sealed product layer. It retains its own later evidence cutoff and the unchanged market-view digest; product facts are not retroactively inserted into the original market view. The dossier includes incomplete product evidence, issuer documents, target-code relationships and bounded notice audits. Private holdings can be loaded afterwards.

Fund NAV currentness uses a reviewed valuation/publication contract. Do not apply an exchange quote clock to NAV: an older valuation may remain within its declared announcement window. The current direct 000051 source supports mainland trading-day valuation and its next-calendar-day disclosure clause; joint foreign/futures calendars for QDII products require their own verified contract. Normal-case rules retain disclosed exception handling.

`fetch-huaan-dealing <codes>` follows the official landing page's current XLS link and declared update date, then stores `fund_dealing_snapshot` rows for registered exact shares. The update date comes from the source text, not the older article URL or article timestamp. Keep the source's reversed name/code headings and actual body cells explicit. Merged business cells retain their anchor and covered share codes; sharing a displayed quota does not establish whether the manager aggregates those share classes when enforcing it. Product assembly and the fund evidence package retain the dated snapshot while current subscription, channel and holiday-calendar verification remain separate.

For configured collection, enable provider `huaan_dealing` and set the allocation profile's `huaan_fund_codes`. This adapter needs optional `xlrd`. The current development runtime has measured standalone collection; the main production profile has not yet enabled this additional source or accepted its health policy.

## NAV and dates

- Distinguish NAV valuation date from disclosure time. The engine's Eastmoney fallback converts its midnight timestamp in Asia/Shanghai; it does not invent the original publication time.
- The fallback's six-digit identifier does not prove currency or fund type. Supply a verified currency or keep `unknown`; never label every NAV CNY.
- Unit-NAV returns exclude a reinvestment reconstruction. Cash distributions or splits can cause mechanical price changes. Preserve distribution notices and verify their amount/type before computing total return.
- Cumulative NAV is retained as a separate series, not labeled reinvested total return. A provider's distribution text remains unparsed evidence until checked.
- QDII analysis aligns valuation dates, foreign sessions and FX. Do not compare the displayed latest NAV with a later live overseas price as though both describe one session.
- Ordinary off-exchange fund units have no stock-like continuous five-level order book. Study volume/book/vendor trade classifications on the underlying instruments or exchange-traded products; study NAV, units and disclosed flows on the fund.

A missing mapping or fee/dealing field can defer choosing a wrapper while market research continues. Missing underlying evidence blocks the exposure thesis itself. For product comparisons, state what the same holding horizon and actual fee schedule imply, rather than universally preferring A or C shares.

## Primary-source examples

- [ETF linkage investment and fee structure](https://www.efunds.com.cn/Mobile/fund/016357.shtml)
- [Dated fund holdings and disclosure lag](https://aim-share.efunds.com.cn/eda/h5/itcenter/general/dist/quarter/index.html?tstamp=2026070310)
- [QDII calendars, FX and dealing mechanics](https://edu.gffunds.com.cn/lcxt/zdjptzjhl/tzjhl1/202504/t20250418_413106.shtml)

These illustrate mechanisms; refresh the actual target product's documents before using its terms.
