# Market report template

Use the sections below as a stable structure. Vary depth according to how much changed; do not pad quiet days.

Use a depth budget rather than repeating evidence. The dashboard states the change, the analysis explains it, and the causal section tests only the two or three most important theses. On routine days, keep sector deep dives and opportunity candidates to the few items with material evidence. Event days may be longer, but unaffected sections should remain compact.

Use a single-home rule for evidence: state a material fact in detail once, assign it an evidence or thesis ID, and refer to that ID later instead of repeating the same explanation. Completeness means covering the decision, not restating every fact in every section.

The one-minute view is the canonical home for its three headline observations. In later sections, cite their evidence IDs and add analysis without repeating the same exact levels or releases.

Complete sections 1-8 and lock the market theses and opportunity matrix before reading or using holdings. If holdings are already present in context, ignore them as a research filter until section 9. Do not rewrite the independent conclusions to make the portfolio look better or to validate a user-stated preference.

## 1. One-minute view

- Analysis cutoff and timezone
- Exactly three most important developments, each with the changed expectation and cross-asset implication
- Three to five sentences answering: what drove markets, whether the market regime changed, and whether the prior thesis strengthened, weakened, or failed
- Overall evidence confidence: high, medium, or low, with a short reason
- Material data-health warning, if any: stale session, conflicting source, missing market window, incompatible adjustment basis, or publication lag

This section must stand alone for a reader who stops after one minute.

## 2. Previous-view verification

When a reliable prior report exists, summarize:

| Prior thesis or watch item | New evidence | Status | What changes now |
| --- | --- | --- | --- |

Use `strengthened`, `unchanged`, `weakened`, `invalidated`, or `not yet testable`. If no prior report exists, state that today's report becomes the baseline.

Use the append-only thesis ledger when available. Preserve the original thesis, horizon, benchmark, and invalidation conditions instead of paraphrasing them with hindsight.

When today's report establishes the baseline, create complete ledger entries for only the one to three material theses using every applicable field in the thesis-ledger schema. The visible summary table is a projection of that record, not a substitute for it. If durable state is unavailable, include the entries in a separate artifact or compact ledger appendix rather than omitting their stable IDs and test fields.

Always retain this as a visible section. Do not hide the baseline statement inside the one-minute view.

## 3. Market dashboard

Summarize only material moves and levels in a compact table:

| Area | What changed | Main driver | Signal |
| --- | --- | --- | --- |
| Macro and policy |  |  |  |
| China and Hong Kong equities |  |  |  |
| US equities |  |  |  |
| Rates and credit |  |  |  |
| FX |  |  |  |
| Gold and commodities |  |  |  |
| Styles and factors |  |  |  |
| Sector breadth and rotation |  |  |  |

Do not fill a row when no reliable or material observation exists.

Immediately after the dashboard, add a compact data-health line: profiles run, latest usable session, failed or unconfigured core datasets, and whether any affected conclusion was downgraded. Do not dump the raw health JSON into the report.

When tactical evidence is decision-relevant, add one compact microstructure table rather than scattering indicators across the narrative:

| Exposure | Price / horizon | Volume and amount | Turnover / volume ratio | Breadth | MACD / RSI / ATR | Book / inner-outer | Vendor flow | Interpretation and countercase |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |

Populate only fields supported by the correct session and target identity. Label locally calculated indicators and provider-derived fields. An indicator cluster can justify monitoring or change tactical timing; it cannot by itself promote an opportunity or override contrary fundamental, valuation, policy, or portfolio-risk evidence.

## 4. Complete market analysis

### Central market narrative

Identify the one or two forces that explain the largest share of cross-asset behavior.

### Macro, policy, and liquidity

Explain new data and policy against prior expectations, not in isolation.

### Regional equity markets

Cover mainland China, Hong Kong, and the United States. Add other regions only when they materially affect the global picture.

### Rates, currencies, and commodities

Explain how nominal yields, real yields, the dollar, the renminbi, oil, and gold confirm or contradict the equity story.

### Earnings, valuation, flows, and sentiment

Use these as distinct evidence types. Do not treat sentiment as fundamentals or price momentum as valuation.

## 5. Sector rotation and opportunity discovery

### Breadth and leadership scan

Summarize the full relevant sector universe without reproducing a raw leaderboard:

| Market | Named strengthening groups | Named weakening groups | 1D / 1W / 1-3M evidence | Breadth / fundamentals / flows | Rotation state and confidence |
| --- | --- | --- | --- | --- | --- |

Include one row each for mainland China, Hong Kong, and the United States, even when the conclusion is `no material divergence` or `insufficient evidence`. Use actual industry or theme names rather than a regional index or macro label. Judge rotation quality from multiple evidence types: relative performance across more than one session, breadth, earnings revisions, valuation, policy or supply-chain catalysts, and reliable flow or volume data. Mark evidence gaps.

### Material sector deep dives

Deep-dive only sectors or themes with a material change. For each, explain:

- what changed and over what horizon;
- fundamental, policy, valuation, positioning, and technical-flow evidence;
- whether the move is early, broadening, mature, crowded, or failing;
- the strongest countercase and invalidation signal.

### Opportunity matrix

Include opportunities whether held or not:

| Opportunity | Type | Why now | Evidence and confidence | Catalyst and horizon | Main risk | Confirmation / invalidation | Alternative / why wait | Investable path | Follow-up? |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |

Use one opportunity type: `fundamental improvement`, `policy or liquidity transmission`, `valuation mean reversion with catalyst`, or `defensive or diversification value`. Rate confidence `high`, `medium`, or `low`. An opportunity is a research candidate, not automatically a buy recommendation. Use exactly `worth dedicated research`, `watch`, or `not yet` for the intermediate research state. Complete material follow-up into named stocks, ETFs or precise fund shares, with the relevant comparisons and timing conditions. State the final recommendation separately after due diligence; a category-only path does not finish an autonomous discovery request. Compare the opportunity with plausible alternatives and say when waiting for confirmation is preferable.

Apply the evidence gate and status definitions in the sector-opportunity framework. Populate every table cell; use `unknown` rather than omitting a confirmation, invalidation, or alternative. Keep each row to one coherent exposure and mechanism.

Include cross-asset opportunities, not only equity sectors. Bonds, cash, currencies, commodities, styles, regions, and volatility or defensive exposures may qualify when supported by evidence. If nothing reaches `worth dedicated research`, write `no opportunity cleared the dedicated-research gate; N watch items remain`. If nothing reaches even `watch`, write `no qualified opportunity or watch item`. Do not manufacture novelty.

## 6. Causal chains and countercases

For each major thesis, show:

- observed event or data;
- expectation that changed;
- transmission channel;
- affected assets and expected horizon;
- competing explanation;
- invalidation evidence.

For the strongest thesis, add a short adversarial ruling:

- best evidence-based case for it;
- strongest attempt to disprove it;
- risk-manager judgment;
- why the preferred conclusion beats the best alternative and waiting, or why it does not.

When the user proposes a trade or asks which product to buy, also include the decision-protocol comparison table and trigger register. State exactly one `Exposure stance:`. A non-action stance may discuss the cost of waiting but must not include fallback sizing or implementation language.

## 7. Regime and forward scenarios

Describe the current growth-inflation-liquidity-policy-risk combination. Provide:

| Scenario | Conditions | Cross-asset implications | Confirmation or invalidation |
| --- | --- | --- | --- |
| Base |  |  |  |
| Upside |  |  |  |
| Downside |  |  |  |

Use qualitative scenarios when numerical probabilities would be false precision.

## 8. Cross-market risks and watchlist

- Risks that could break the base case
- Upcoming events and the observations that matter at each event
- Unresolved sector opportunities or rotation signals to verify in the next report

For each decision-relevant trigger, include the metric or event, source, direction or threshold, observation window, and next review point. Use numbers only when a defensible baseline exists; otherwise use a specific event-based rule.

## 9. Personalized appendix: impact on current holdings

Begin this section only after the independent report is complete.

State that the independent market view and opportunity matrix were locked before personalization. The appendix may change portfolio fit or urgency, but it may not erase unheld opportunities or rewrite the market conclusion.

Use only holdings supplied in the current request, configured in the active task, or loaded from a portfolio ledger the user explicitly designated as authoritative. Do not populate this section from general conversational memory or examples. If portfolio impact is requested and no authoritative holdings are available, ask the user for product names or identifiers and exact share classes before producing this section; current weights or amounts, currency, and recurring-investment plans are helpful but optional.

### Holding-level mapping

| Holding | Relevant market conclusion | Direct or indirect channel | Short / medium / long-term effect | Thesis changed? | Confidence |
| --- | --- | --- | --- | --- | --- |

### Portfolio-level implications

- concentration and overlap;
- currency and geographic exposure;
- correlations and diversification;
- recurring-investment sensitivity;
- risks not visible from single-holding analysis.

### Decision discipline

Choose one conclusion and explain it:

- `Plan unchanged`: no thesis or risk-threshold change.
- `Watch closely`: a relevant condition is developing but not confirmed.
- `Review threshold reached`: a predefined thesis, allocation, liquidity, or risk condition requires a deliberate review.

Do not recommend reacting solely to a one-day move or a news headline.

Prefix this separate namespace with `Portfolio status:`. It describes portfolio review urgency and does not replace or loosen the previously locked `Exposure stance:`.

## 10. Sources and uncertainty

Link primary and authoritative sources near supported claims. Prefer official releases and filings, then exchanges and index providers, established market-data vendors, and reputable financial reporting. Use accessible, stable links where practical. For a historical cutoff, reject later retrospectives and revised information unavailable at the cutoff. Explain only material gaps that change a conclusion or its implementation, once beside the affected claim. End with the chosen action and next decision point; leave software/test-coverage disclaimers in the validation appendix unless requested.

For streaks, new highs or lows, rankings, and cumulative-return claims, cite or reconstruct the dated underlying series and state the exact window and comparison basis. Distinguish close-above-open candles from close-to-close gains.

## Finalization checks

Before delivery:

- reapply the opportunity-type core-evidence and target-identity gates to every candidate;
- verify that each Markdown table row has the same cell count as its header and write `unknown` for required missing content;
- verify the trigger register has no undefined comparative term or empty required cell;
- persist complete baseline ledger entries when a baseline was created;
- replace repeated headline values outside the one-minute view with evidence IDs.
