# Full-market data layer

Use this reference when gathering current or historical market data, designing a connector, or deciding whether an external data project belongs in the system.

The packaged implementation is documented in [data-engine.md](data-engine.md), and its metric ownership and fallbacks are defined in [provider-registry.md](provider-registry.md). Treat those files as the executable source registry rather than an optional example.

## Evidence classes

Do not collapse unlike measurements into a generic “fund flow” or “technical” bucket:

- **Raw/provider-reported:** price, OHLC, volume, amount, published NAV, filings, and displayed book levels.
- **Locally derived:** MACD, KDJ, RSI, ATR, close-volume ratio, intraday volume ratio, breadth, and displayed-book imbalance calculated from retained inputs.
- **Model-estimated:** the named daily-range/turnover-decay cost distribution, with price basis, source window and residual initial-inventory assumptions. Keep it separate from provider CYQ and actual holder positions.
- **Provider-derived:** inner/outer classifications, order-size buckets, BBD/DDE-like fields, vendor volume ratio, and “main force” labels.
- **Interpretive:** accumulation, distribution, crowding, panic, support, resistance, and investability judgments.

Only the last class is an analytical conclusion. Provider-derived flow fields may describe vendor-classified activity but do not identify the beneficial owner or prove that institutions transferred capital.

## Holdings firewall

The discovery layer must cover the investable universe independently of the user's portfolio. A holding may affect the final fit assessment, but it must not determine which markets, industries, assets, or risks are scanned.

Use four logically separate stages:

1. **Market discovery:** macro, cross-asset, regional, sector, factor, valuation, earnings, flow, and event data.
2. **Thesis formation:** what changed, the causal channel, competing explanations, horizon, and invalidation.
3. **Investable mapping:** asset, index, ETF, fund, QDII, bond, commodity vehicle, or stock when appropriate.
4. **Portfolio overlay:** authoritative holdings, cash needs, overlap, concentration, currency, correlation, liquidity, and recurring plans.

Lock stages 1-3 before stage 4.

## Minimum market universe

Inspect the following when material. Coverage means checking the universe; it does not require printing every observation.

- **Global macro:** growth, inflation, employment, central banks, fiscal policy, credit impulse, liquidity, and major event risk.
- **Equities:** mainland China, Hong Kong, the United States, and other regions when they affect the global story.
- **Industries and themes:** breadth, relative performance, earnings revisions, valuation, policy, supply chain, flows, volume, positioning, and catalysts.
- **Rates and credit:** sovereign curves, real yields, policy expectations, credit spreads, and funding stress.
- **FX:** dollar, renminbi, and material crosses.
- **Commodities:** gold, oil, copper, and other commodities that change inflation, growth, or sector conclusions.
- **Styles and factors:** large/small, value/growth, cyclical/defensive, quality, duration, and concentration when relevant.
- **Investable products:** index methodology, stocks, ETFs, off-exchange funds, QDII, bonds, cash products, and commodity vehicles.

## Three-depth scan

### Level 1: broad daily scan

Detect changes in regime, cross-asset confirmation or contradiction, regional leadership, sector breadth, earnings direction, valuation, and major catalysts.

### Level 2: trigger screen

Escalate a market, industry, asset, or theme when at least one material change is supported or challenged by another independent evidence type. Examples include a policy with funded implementation, earnings revisions with broad participation, a sustained relative move, a valuation regime change, or a commodity or rate shock with a clear transmission path.

For this gate, `independent` means a different evidence-generating process, not a second article describing the same event or a second price series reacting to the same shock. Retain a claim-level evidence register and identify which item is asset-specific. A generic risk-off headline plus the asset's same-session price move is one event cluster, not two confirmations.

If only one event cluster is available, if a required comparison window is missing, or if the observation cannot satisfy the data contract below, do not promote the candidate. Mark the exact gap and use `not yet`; do not preserve the promotion by merely lowering confidence.

### Level 3: dedicated due diligence

Research only the few candidates that survive the trigger screen. Include counterevidence, alternatives, implementation choices, and reasons to wait.

## Data contract

For every material observation retain, when applicable:

| Field | Requirement |
| --- | --- |
| identity | instrument, index, series, market, or company |
| value | exact value or qualitative observation |
| as-of | observation date and market session |
| publication | original release time and timezone |
| revision | original, revised, preliminary, or unknown |
| unit | percentage, basis points, currency, volume, ratio, etc. |
| currency | source and reporting currency |
| price basis | unadjusted, split-adjusted, total return, qfq/hfq, or unknown |
| source | direct page or dataset and provider class |
| latency | real time, delayed, end-of-day, valuation lag, or unknown |
| quality | confirmed, conflicting, incomplete, stale, or unavailable |

Never join series with incompatible currencies, adjustment bases, calendars, classifications, or timestamps without an explicit mapping.

For each material thesis or opportunity, assign short evidence IDs and retain the applicable contract fields above in a source appendix or evidence ledger. Cite those IDs next to the claims they support. A qualitative field may be `unknown`, but an unknown field cannot support a directional claim that depends on it.

## Target-evidence identity gate

Before an observation can support a thesis or opportunity, verify that it matches the proposed exposure:

- exact asset, index, sector, or instrument identity;
- maturity, duration, credit quality, and seniority when relevant;
- price return versus total return and the adjustment basis;
- source currency versus investor return currency;
- observation session, calendar, and point-in-time availability.

Do not silently use a related broad or composite index for a narrower target, a 10-year yield for short-duration carry, an international commodity price for a domestic fund, or an equity price move for earnings improvement. A proxy is usable only when labeled `proxy`, the mapping is explained, and the conclusion remains valid under plausible proxy error. If the proxy is central to the thesis or status gate, mark the required evidence unavailable and use `not yet`.

## Source hierarchy and conflict handling

1. Official releases, filings, and statistical agencies.
2. Exchanges, central banks, regulators, and index providers.
3. Established market-data vendors.
4. Reputable financial reporting for context.
5. Aggregators or undocumented interfaces only as disclosed fallbacks.

A live blog, rolling coverage page, or generic news hub is not a stable citation for a material value unless the exact item has a durable permalink or anchor. Otherwise locate the underlying dataset or another stable dated page; if neither is available, mark the observation unavailable for thesis promotion.

For a material conflict, preserve both observations, identify the likely reason, and lower confidence. Do not pick the value that best supports the preferred thesis. If the conflict cannot be resolved, mark the conclusion unknown.

## Connector evaluation

Before admitting a connector, check:

- provenance and legal or access constraints;
- endpoint stability and authentication requirements;
- timestamp, calendar, unit, currency, and adjustment semantics;
- point-in-time availability and revision history;
- rate limits, fallback independence, and fail-closed behavior;
- test coverage, maintenance activity, and reproducibility;
- secret handling, file writes, downloads, and executable behavior.

One canonical source should own each metric, with explicit fallbacks. Installing several overlapping connectors without a source-of-truth policy increases inconsistency rather than coverage.

## External project lessons

`a-stock-data` is useful as an optional A-share adapter because it documents fallback routes, rate limits, adjustment pitfalls, and source-specific caveats. It is not the complete data layer: it is A-share-heavy, several endpoints are unofficial, and its large embedded-code skill should be isolated and audited before execution.

`global-stock-data` may complement overseas single-security research, but the research universe must not depend on whether a connector is installed. Official and established sources remain the evidence standard.
