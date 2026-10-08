# Local data engine

Read this before collecting structured data or interpreting a stored snapshot. The engine stores raw/provider evidence separately from local indicators. Runtime configuration/database and credentials belong outside the installed skill.

## Runtime and configuration

Core commands use Python's standard library. BaoStock and TDX connectors have optional dependencies listed in `scripts/requirements-optional.txt`; use an isolated compatible environment, not a forced global upgrade. For this machine's verified runtime, read `local-runtime.md`.

`init-config` writes a starter, not an authoritative portfolio or a complete deployed market universe. It contains benchmark/sector proxies and optional global/FRED collectors; fund and tactical lists are initially empty. Configure research lists independently of holdings.

```powershell
python scripts\market_engine.py init-config --config C:\path\market-config.json
python scripts\market_engine.py doctor --config C:\path\market-config.json --profile allocation
python scripts\market_engine.py run --config C:\path\market-config.json --profile allocation
python scripts\market_engine.py run --config C:\path\market-config.json --profile tactical
```

Use `--db C:\path\market.sqlite3` before direct subcommands. For `run`, the database path is read from config and relative paths resolve beside that config. FRED and Twelve Data keys come only from `FRED_API_KEY` and `TWELVE_DATA_API_KEY` in the executing environment. Doctor reports presence, never value. Use doctor --profile to check only the requested mode. Health/snapshot/discover/screen/evidence open existing databases read-only and do not initialize or migrate them. Exit 2 from doctor/run/evidence means incomplete or failed; missing keys and empty runs are not success.

Per-profile `history_source: "tencent"` selects the daily price/volume fallback explicitly. Otherwise BaoStock supplies historical bars and stock-specific daily metrics. Tencent history has no collected historical amount field; never attach BaoStock amount to its bars. Index history retains its actual unadjusted basis.

`history_fallback_sources: ["tencent"]` (the default) permits a failed BaoStock history request to retry through Tencent. Both source runs remain recorded; the entire selected window must match asset, currency, interval and price basis. Sources are never concatenated to complete a window. Exchange-fund price collection requests `none` adjustment and stores `unadjusted`; it does not label fund prices as adjusted stock prices or total returns. Stock valuation fields are not collected as ETF fundamentals.

Configured mainland daily collection has a per-profile `history_refresh` policy: default45 calendar days of overlap, a full requested-window refresh every168 hours, and a bounded5000-row baseline. The first successful fetch records a source/identity/basis-specific checkpoint. Subsequent raw/unadjusted fetches verify the saved baseline fingerprint, refresh the overlap and recompute indicators from the complete bounded input sequence. Expanded scope, a missing/changed baseline or a due full refresh uses the complete requested window. A failed fetch does not advance the checkpoint or substitute cached old rows as a successful new fetch. A full response omitting previously stored dates in scope is refused rather than silently accepting incomplete history.

Checkpoint reuse also validates its immutable normalized baseline archive against the stored rows and verifies each distinct original HTTP receipt and wire/decoded body. Missing or damaged archives trigger full recovery; a successfully re-received identical payload preserves damaged bytes in quarantine before restoring the baseline. Non-HTTP sources retain normalized source records without being relabeled as captured socket bytes. Report field/provenance changes separately: a changed request URL is not automatically a changed historical financial number.

An incremental response must include every previously stored date inside its requested overlap. Missing dates reject that response and permit exactly one full-window recovery attempt. Failure or persistent omissions preserve the old bars, indicators and checkpoint and record a failed run; retained old rows cannot make an incomplete new fetch appear successful. The rejected response remains archived for diagnosis.

Adjusted qfq/hfq histories continue full-window source refresh because corporate-action changes can affect older prices. Original per-row response dependencies remain attached when raw history is consolidated; the contract does not claim an atomic publisher revision or a check of all dates outside an incremental overlap. Inspect `collection_refresh_contract` in the run details for requested bounds, input length, financial/provenance changes and revision-check scope. Direct targeted commands retain their explicitly requested window rather than assuming a configured checkpoint.

## Scoped health and response retention

```powershell
python scripts\market_engine.py profile-health --config C:\path\market-config.json --profile allocation
python scripts\market_engine.py profile-health --config C:\path\market-config.json --profile tactical
```

This command opens the configured existing database read-only. It checks exactly the requested sources and streams, required history, missing scheduled sessions, currency/basis, source quality and relevant latest collection problems. Unrelated failed streams remain in database health/history without failing this profile. `recovered` means a compatible complete alternative supplied the data and the original failure remains linked; `degraded` means stored data meet the requirement but a relevant collection problem remains. `run` uses this scoped result rather than the entire database's failure history.

Incomplete supplier aggregate windows produce `partial` run records with received/expected pages and retained records. A malformed page's cache pointer is rejected while valid earlier pages and their original receiving times remain available. After a repaired page is received, a complete supplier window can return `ok`. Complete pagination still does not establish exchange-level individual orders or verified execution-clock semantics.

Daily histories use the last completed cash-market session, while quotes/minute data use the current relevant trading clock. The 2026 cash calendars cover mainland China, US cash venues, Hong Kong and Japan, plus the named EURO STOXX dissemination schedule, with timezone/early-close rules. Out-of-coverage calendars, unverified futures sessions and fund valuation/publication schedules remain explicit gaps. Recent macro collection is a source-snapshot freshness policy, not proof of its original publication time or revision vintage.

Pipeline and direct HTTP collection commands keep private raw responses beside the database in `raw-responses/`: original wire bytes, decoded bodies, safe response headers, receiving time, hashes and immutable receipt metadata. Run records link the response and later rejection receipts. BaoStock/TDX normalized source records remain in their receipt archive; this HTTP archive does not claim to capture their socket packets.

New HTTP-derived quotes, bars and observations also carry `source_receipts` on each normalized record (SQLite schema 5). Parsers attach the responses actually consumed: FRED binds metadata and numeric data together, paginated records keep their own page and required date metadata, and family-document bridges include the exact-share summary dependency. Writes verify receipt metadata and both archived byte streams before freezing normalized data or committing rows. Cache hits retain the original receipt and receiving time. These links describe response dependencies; they do not create an additional independent financial evidence type.

```powershell
python scripts\market_engine.py --db C:\runtime\market.sqlite3 source-trace sh000300 --kind quote --provider tencent_web_quote --limit 3
python scripts\market_engine.py --db C:\runtime\market.sqlite3 source-trace DGS2 --kind observation --dataset macro_series --provider fred_public_csv --limit 3
```

`source-trace` is a bounded, read-only audit. A verified result checks explicit row links and archived bytes. Missing links on older/imported/TCP records remain `normalized_receipt_only`; schema migration does not infer historical HTTP links. Modified or missing archives report invalid references. Exit 0 means all requested returned rows have verified response links; partial, invalid and missing traces return 2. Byte integrity alone does not independently reparse the financial fields or establish source freshness; use the relevant provider and data contract for that check.

Tencent supplier aggregates retain the provider's record clocks. `clock_audit` reports records and amounts after the mainland cash close, without deleting them or claiming the clock is execution time. Complete supplier pagination does not establish continuous-session execution coverage. Explain any clock or aggregate-versus-quote amount discrepancy before using intraday-window claims.

The 2026-10-06 refresh of the actual sh600519 supplier window linked all4136 records plus the summary to61 actual responses. Previous frozen reports retain their historical missing-link statement; a later byte-identical download is not proof of an earlier receiving time. The source date remained2026-09-30 and this holiday refresh did not count as a new live trading-session acceptance day.

`collection_transport.cache_ttl_by_host` enables bounded GET reuse (default: 300 seconds for FRED and the fund fallback host; quotes/minute hosts have no cache TTL). A hit preserves the original receiving time. Raw/metadata corruption causes a refetch; damaged payloads are retained in quarantine. Failed parsing or contracts invalidate the cache pointer. Expired cache never substitutes for a failed live request. A known request credential echoed in a response prevents raw-payload writing; request keys and authorization values are not written in metadata. Transport cache age does not establish market-observation freshness.

## Targeted commands

For the three complete research requests, start with `research-stock`, `research-fund`, or `research-opportunities`; read their workflow references for the final judgment. The evidence commands below are components, not final research reports. `research-opportunities --config <config> --output-dir <new-directory>` resolves the database relative to the configuration file; an explicit different `--db` is refused. Use `--refresh-global` for live overseas proxy collection or `--as-of <timezone-aware-cutoff>` for a frozen read-only sample, separately.

`fund-lookthrough-graph <exact-root-share>` reads reviewed linked funds/ETFs recursively. It freezes no new personal inputs, preserves each layer's source/date and unresolved weight, and lists fees/derivative review separately. It is a disclosure-snapshot calculation, not today's fund holdings or a proof of complete investment diligence. The relevant fund workflow continues source collection for missing material children.

```powershell
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-quote sh000300 sh510300 sh600519
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-bars sh600519 --start 2026-06-01 --end 2026-09-30 --source baostock --adjustment qfq
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-bars sh600519 --start 2026-06-01 --end 2026-09-30 --source tencent --adjustment qfq
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-daily-metrics sh600519 --start 2026-09-28 --end 2026-09-30
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-intraday sh600519 --interval 5m --count 240
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-ticks sh600519 --date 2026-09-30 --lot-size 100
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-cn-flow sh600519 --interval 1d
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-board --type industry --period today
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-fund-nav 000051 --currency CNY
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-fred DGS2 DGS10 DFII10 DTWEXBGS DEXCHUS
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-global QQQ SPY GLD --interval 1day
```

Identifiers/dates here are examples, not the user's holdings. Supply `--currency` for NAV only after verifying the exact share class's currency; otherwise leave `unknown`. NAV collection also retains cumulative NAV, distribution text where supplied, and limited profile basics. It does not extract complete fees/holdings/dealing rules or construct total return.

The TDX adapter calls `tdxpy` with explicit exchange and index/stock routing, using a bounded endpoint list instead of mootdx's home-config/best-IP side effects. `MARKET_TDX_HOST` and optional `MARKET_TDX_PORT` can name an already-known server. It returns at most 800 bars or one bounded transaction page. Historical transactions use the historical API. Units/coverage still require verification; explicit lot-size arithmetic is an assumption, not proof of full-day big-order coverage.

## Discovery and questions

`fetch-primary-financials <symbol> --period-end YYYY-MM-DD --registry <reviewed-source-file> --document-dir <runtime-dir>` retrieves a registered primary PDF and binds reviewed fields to its current byte hash, actual issuer/period, original page and unit evidence. `financials_primary` is a separate source from raw vendor `financials`; the latter is not globally promoted. It retains six-month/year-to-date versus TTM, consolidated versus parent profit, revenue including interest versus ordinary revenue, and point-in-time balance versus period flow. `financials_field_audit` records issuer/period-specific numerical comparisons and remaining unknowns.

A numerical match is scoped to the observed field and report period. Do not rename a vendor field merely from its API label, equate a raw average ROE with reported weighted ROE, use a year-end asset comparison as prior-year same-date growth, or label half-year EPS as TTM. Preserve primary management explanations when cash-flow changes include financial subsidiaries or other components outside the main operating business. A complete issuer field record supplies evidence; it does not by itself establish improvement or a qualified opportunity. Date-only publications remain excluded from strict historical-cutoff proof.

`sector-price-scan --config <config>` compares the ten configured mainland sector-index proxies and eleven US sector-ETF proxies against their named regional benchmark over 1/5/20/60 matching benchmark observations. It retains one symbol/interval per series, source/currency/basis, real start/end dates and input fingerprints. Missing dates are not replaced by a longer intersection window. When the original benchmark-defined endpoints exist but intermediate dates are missing, `endpoint_windows_with_gaps` separately retains those endpoint price returns with the missing dates; it does not establish a complete path, volatility, volume or indicator window. This is a bounded price-proxy panel; Hong Kong sector windows, historical constituent breadth and non-price confirmation remain separate requirements. Configured allocation preparation freezes these inputs and registers/recomputes the 21 comparisons as price evidence.

```powershell
python scripts\market_engine.py --db C:\path\market.sqlite3 fetch-universe --scope stocks --max-pages 10 --page-size 100
python scripts\market_engine.py --db C:\path\market.sqlite3 discover
python scripts\market_engine.py --db C:\path\market.sqlite3 screen --price-basis qfq --provider baostock_free_history
python scripts\market_engine.py --db C:\path\market.sqlite3 evidence sh600519 --question trend --provider baostock_free_history --price-basis qfq
python scripts\market_engine.py --db C:\path\market.sqlite3 evidence 000051 --question fund --window 120
python scripts\market_engine.py --db C:\path\market.sqlite3 import-evidence C:\path\verified-evidence.json
```

Enumeration records the provider filter, reported total, received count, limits and failure. A completed vendor filter is not proof of full-market coverage. `discover` uses imported listings and collected data, never a portfolio. Enumeration does not automatically fetch every instrument's historical data.

`screen` requires at least 61 observations and a specified/verified price basis and currency. It examines absolute price moves, relative moves on matching benchmark dates/currency/basis, and volume expansion. Thresholds are emitted with results. States are `needs_investigation`, `insufficient_evidence`, `no_significant_signal`. These are questions for investigation, not investment stances or predictions. One-day anomalies require checking distributions/corporate actions and a competing explanation.

`evidence` reads bounded histories for `trend`, `flow`, `valuation`, `fund`, or `allocation`, reports the missing minimum inputs and prevents mixing providers/bases/currencies in one trend. Its result is data sufficiency for the named question, not an opportunity promotion. Apply the decision/opportunity framework afterwards. Flow requires matching price sessions; valuation requires financial evidence; fund selection requires product metadata and underlying evidence, with dated holdings for active/mixed/bond/FOF products.

For historical evaluation, use `--as-of` plus `--point-in-time`. The latter excludes observations without established original publication availability, including date-only publication records and the current bar/quote schemas. Observation-date filtering alone cannot establish a blind historical test. FRED vintage revisions retain distinct identities.

Source-grounded imports are JSON arrays of Observation fields. Allowed datasets: `fund_product`, `fund_holdings`, `fund_distributions`, `financials`, `announcement`, `instrument_listing`, `macro_series`. Each needs `identity`, `as_of`, `value` and a direct HTTPS `source_url`; retain publication, unit, currency and revision when known. Read `fund-research.md` for the fund contract. Imported facts still need source verification.

## Health, snapshots and accountability

```powershell
python scripts\market_engine.py --db C:\path\market.sqlite3 health
python scripts\market_engine.py --db C:\path\market.sqlite3 snapshot
python scripts\market_engine.py --db C:\path\market.sqlite3 compute sh600519 --interval 1d --provider baostock_free_history --price-basis qfq
python scripts\market_engine.py ledger-add --file C:\path\theses.jsonl --entry C:\path\thesis-entry.json
```

Snapshots include full stored bid/ask levels, latest bars and indicators separately per adjustment identity, and latest observations per provider/dataset/identity/revision. Read histories through `evidence` instead of letting a long fund series crowd out slow macro observations.

Mainland quote health is evaluated at read time against the bundled official 2026 exchange calendar and trading windows. Earlier closes remain current during holidays; an old stored quote becomes stale after the next relevant session. Outside calendar coverage, report unknown and refresh the official calendar. This is not a global-market or fund-valuation calendar. Other datasets retain their source times and need task-specific freshness checks.

Schema v4 migration preserves bars and variants transactionally. Old indicators without reliable adjustment identity are retained as `legacy_unknown` / `legacy_basis_unverified`, requiring recomputation before use. Returns use `period` names and window units; minute bars never masquerade as days. MACD waits for 34 observations. Price-only NAV indicators are not total-return indicators.

`ledger-add` validates the schema in `thesis-ledger.md` and appends JSONL records. An update cannot change the original thesis, horizon, benchmark, cutoff, confirmation or invalidation. Add new evidence/status/outcome instead.

## Validation and release

```powershell
python scripts\validate.py --temp-root C:\path\test-scratch
```

Structural/code/fixture tests, current interface probes, continuous-session stability and research behavior are distinct checks. See `validation-status.md`. Before changing a recurring task, observe at least five consecutive trading sessions, session-specific refresh, missing-source downgrade and failure/recovery. Install updated instructions/helpers without claiming this release gate has passed.

## Reviewed financial rows and issuer dealing tables

Primary financial fields now bind the exact table row, ordered current/prior columns, table-header page, accounting scope and comparison period. An unreviewed semantic row cannot enter the financial evidence gate solely because its label and amount coexist on a page. `evidence --question valuation` exposes `financial_coverage`: usable primary fields, numeric vendor alignments and remaining unverified or noncomparable fields. H1 statements do not clear a TTM denominator reconciliation gap.

Independent market preparation excludes product terms and raw fund NAV from its macro/financial evidence register. Derived NAV metrics remain market_price evidence and require verified currency and price basis; product research enters its separate dossier after the independent market view is locked.

`fetch-huaan-dealing 040046 000217` reads the dated official XLS via its landing page. Both source responses are bound to each observation. The source update date, exact body code cell, business legend and merged-cell anchors are preserved in `fund_dealing_snapshot`; assembled products retain this dated evidence without approving current subscription or platform terms. See [fund-research.md](fund-research.md) for its configured profile and interpretation.

## Focused stock data and forecast stage

`research-stock <ticker-or-exact-stored-name> --output-dir <new-directory>` performs targeted public quote, daily history/valuation, minute, vendor-flow and recent-financial collection, using separately recorded fallback/failure results. Registered primary reports are fetched where available. It freezes daily inputs and source bytes, renders candles/BOLL/EMA/MACD/volume, compares a matched broad benchmark and retains primary financial coverage/countercases. Absolute review levels use unadjusted prices; expected daily history ends at the completed mainland session. Future observation/publication rows are excluded at the shared evidence cutoff.

The separate price analogue model uses matured, nonoverlapping training windows and chronological expanding evaluation. It reports historical analogue return distributions and withholds probability unless its declared baseline/calibration gate passes. Current-vintage price-only evaluation is not dividend-reinvested strategy performance or historical-publication-vintage certification. Existing indicator calculators and old frozen research packages are not rewritten by this separate component.

`verify-stock-research --directory <stock-run>` checks artifact seals/frozen source bytes and replays curves/context/forecast from frozen daily inputs without accessing a database. For newer packages it also replays the conditional opinion and any included paper execution, reporting those scopes separately; older packages retain their original scope. A changed numerical calculator reports its version boundary. This replay verifies calculations from the frozen evidence, not the external truth or completeness of financial/event due diligence.

Chart conditions carry the exact symbol/provider/basis/currency, numeric comparisons, window, baseline and next review time. Prior-baseline or future/uncompleted bars cannot satisfy them, and a passed chart condition never authorizes a trade. Broader fundamental/event due diligence, tested cost/execution, actual risk-budget sizing, fund look-through and autonomous named-opportunity decisions remain further stages.

## Primary announcement helper and conditional decision aids

The public CNINFO catalogue adapter validates issuer code/org identity, requested dates, stable totals, complete pages, unique IDs and approved PDF hosts. Its POST form is a read-only query and uses a body-specific cache identity. Catalogue entries and unreviewed documents do not count as reviewed economic effects. `issuer_events.py` binds selected fact reviews to actual PDF hashes/passages; this review registry is extensible, and current issuer-specific examples are QA inputs rather than the skill scope.

`stock_decision.py` and `stock_execution.py` are supporting rule/scenario aids. They demonstrate multiple conditional action branches, source-matched financial inputs, major-risk vetoes and delayed paper fills with declared costs/lots/cash entitlements. They do not replace the skill analysis or certify predictive/strategy advantage. Follow [stock-research-workflow.md](stock-research-workflow.md) for the complete human research task.

`research-stock` accepts `--position-state unknown|unheld|held` and an optional positive finite `--risk-budget-cny` from user-confirmed inputs. Without these it does not invent a position or personal budget. The helper records a conditional analytical opinion; full security and portfolio judgment follows the workflow. Fund and unguided requests follow [fund-research-workflow.md](fund-research-workflow.md) and [autonomous-research-workflow.md](autonomous-research-workflow.md), using official-source research where no adapter exists.

## Disclosed fund holdings and NAV charts

`fetch-fund-holdings <code> --look-through` uses the ChinaAMC issuer listing and supported annual/interim domestic-equity layout, stores `fund_holdings`, and follows the exact disclosed target ETF. It preserves report/publication/receipt dates, the shared fund-family portfolio scope, original pages, total-assets versus net-assets denominators and full-stock/industry reconciliation. Different report-table totals remain different. The returned listing is a bounded source window, not a verified complete historical announcement audit. Unsupported formats or managers require other official-source retrieval.

`fund-lookthrough <code> --as-of <cutoff>` opens the database read-only and computes the stored feeder/ETF disclosure estimate. Direct and indirect holdings of the same security combine with both source paths; weights are not rescaled. Keep partial detail, residual assets, report dates and economic FX unknowns. `chart-fund-nav <code> --output-dir <new-directory>` likewise reads the database only and creates a sealed standalone NAV/BOLL/MACD/drawdown artifact. It requests up to 20,000 observations per source, verifies exact-share currency and requires at least60 observations. Neither command forms the final investment opinion; complete the fund workflow.

The look-through result also retains source-table differences and a same-date share-count/value bridge where disclosed. `cross_layer_value_bridge` shows unresolved differences and a quantity-basis sensitivity, using the actual displayed NAV precision. Futures contracts are a separate overlay with source pages and signed quantities; a missing section yields an unknown total plus any known subtotal, not zero exposure. These disclosure snapshots do not reconstruct today's positions, and complete stock rows do not certify complete economic FX or derivatives coverage.

## One-fund research assembly

`research-fund <exact-code-or-stored-exact-name> --output-dir <new-directory>` proactively collects supported primary product sources, same-share NAV, dated holdings and target ETF, issuer business flags, and mainland underlying history/CSI valuation where identity is established. It freezes a new evidence package and includes matched-date price comparisons, reviewed A/C forward-cost scenarios, issuer-reported period return differences and country-matched macro already available in the store. Unsupported formats/managers or missing relevant macro/FX data remain concrete official-source research tasks for the skill; a successful script run is not final report acceptance.

`--holding-fee-age-days` is a comparison scenario, separate from `--horizon` NAV observations and the actual fee-age starting event. Platform A discounts remain scenarios until verified. Year-tier ambiguity, fixed-amount charges, leap-year day counts, ETF-excluded common charge bases and full-class-NAV service fees are retained. Fee loader checks the registered PDF/identity bridge/pages plus named rates, amount bands and redemption clauses; unchanged text cannot approve edited numeric terms. Current known replacement prospectuses defer the old fee contract.

`fetch-chinaamc-business <codes>` stores the observed source response with its page update label separately. An old update date, a dash in restriction text or an open flag cannot establish current opening-day/channel eligibility or an unlimited quota. The primary product adapter no longer copies a NAV valuation date into a business-status timestamp.

CSI `peg` is the official UI's rolling PE/PETTM field; raw fields are retained. Published history is a current vintage, not a certified historical vintage. Percentiles use the same source/window and transparent sample counts. Do not select a favorable one-year window while suppressing conflicting three/five/ten-year evidence, or call a percentile an optimal entry level. Fund-versus-underlying price-return differences are not policy-benchmark tracking error; the issuer's dated period comparison is another, explicitly scoped measure.
