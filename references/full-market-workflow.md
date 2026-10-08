# Full market report workflow

Use for complete daily or weekly reports. Preserve the three reading layers and apply the report template. This workflow is not required for a focused question.

## Research workflow

### 1. Set the evidence boundary

- State the analysis cutoff time and timezone.
- For current markets, browse and verify time-sensitive facts.
- Use this source order for material claims: official releases and filings; exchanges and index providers; established market-data vendors; reputable financial reporting for context. Use aggregators only when better sources are unavailable, disclose the fallback, and avoid links that are inaccessible or silently overwritten with current data.
- For historical-cutoff analysis, use only information whose original publication or update time is at or before the cutoff. Do not use later retrospectives, revised releases that were unavailable then, or post-cutoff market outcomes, even when they describe an earlier event.
- Cite each material factual claim near the claim.
- Distinguish confirmed fact, market interpretation, model inference, and unknown.
- Do not invent a price, return, flow, valuation, holding, forecast, or source.
- When a prior report is available, retrieve its core thesis, scenarios, watch items, and invalidation conditions before analyzing the new day.

### 2. Analyze the market independently

Cover the material market universe before reading the portfolio through it:

- global macro: growth, inflation, employment, policy, fiscal conditions, liquidity;
- equities: mainland China, Hong Kong, United States, and other regions only when material;
- rates and credit: sovereign yields, real yields, curve changes, risk spreads when available;
- currencies: dollar, renminbi, and other material crosses;
- commodities: gold, oil, and other commodities when they change the market story;
- industries and themes: market breadth, relative performance, earnings changes, valuation, policy, flows, and important catalysts;
- earnings, valuation, positioning, flows, sentiment, and major event risks.

Do not create a mechanical asset checklist full of trivia. Prioritize what changed, what matters, and what explains multiple assets at once.

### 3. Build causal explanations

For every major conclusion, use this chain:

`event or data -> changed expectation -> transmission channel -> affected asset or segment -> horizon -> evidence that would invalidate the view`

- Test at least one competing explanation for an important market move.
- Do not infer causation from simultaneous price movements alone.
- Separate a one-day catalyst from a medium-term regime change.
- Explain conflicting signals rather than forcing a single narrative.

### 4. Validate the prior view

- State what the previous report expected, what has since happened, and which evidence strengthened, weakened, or invalidated that view.
- Distinguish a forecast that was wrong from one whose trigger has not occurred yet.
- Carry forward unresolved watch items instead of silently replacing yesterday's narrative.
- If no reliable prior report is available, say so and establish today's report as the baseline.

### 5. Scan sectors and discover opportunities

- Scan the full relevant industry universe for breadth, relative strength, leadership changes, earnings revisions, valuation shifts, policy or commodity exposure, and unusual but reliable flow or volume signals.
- For mainland China, Hong Kong, and the United States, always produce one compact market-level sector summary showing named strengthening and weakening groups, multi-horizon evidence, breadth, and rotation confidence. A broad label such as `China reopening`, `A-shares`, or `US growth` is not a substitute for named industries or themes. If no meaningful divergence exists, say so; if evidence is unavailable, name the missing evidence rather than silently omitting the market.
- Inspect one day, one week, and one-to-three-month relative behavior when reliable data permit. Treat a single session as a catalyst observation, not a rotation signal, unless another independent evidence type confirms it.
- Deep-dive only sectors with a material policy, earnings, funding, valuation, supply-chain, or price change, or those becoming a market-leading theme.
- Distinguish durable rotation from a one-day rebound, short covering, or low-liquidity noise.
- Identify opportunities even when the user holds none of them. In the daily report, keep each opportunity compact: state its opportunity type, thesis, supporting evidence, confidence, catalyst, horizon, key risk, confirmation and invalidation conditions, credible alternative, reason to wait when applicable, a high-level investable path, and whether it merits dedicated follow-up.
- Compare opportunities with credible alternatives and the cost of waiting. Do not turn a sector leaderboard into a recommendation.
- Do not run a full index, ETF, or mutual-fund comparison inside the daily report. When the user chooses to investigate an opportunity, expand it on demand into index and product due diligence using `sector-opportunity-framework.md`.
- During on-demand due diligence, compare verified investable options and observation or entry conditions, but leave research continuation and any actual execution decision to the user.
- Keep sector opportunity discovery separate from the personalized holding assessment.

### 6. Define regime, scenarios, and watch items

- Summarize the current combination of growth, inflation, liquidity, policy, and risk appetite.
- Give a base case plus material upside and downside alternatives when uncertainty warrants it.
- Attach observable triggers and invalidation conditions to scenarios.
- Identify opportunities, risks, and upcoming data or events across the market, including areas the user does not currently hold.
- Avoid precise probability or target-price claims unless a reproducible method and sufficient data support them.

### 7. Add the portfolio-impact appendix

Only after completing the independent report:

- Obtain holdings from the current request, the configured automation, or a portfolio ledger the user has explicitly designated as authoritative. Do not treat general conversational memory, inferred history, or example holdings as authoritative, and do not guess missing positions.
- When portfolio impact is requested but no authoritative holdings are available, ask the user to provide their own holdings before producing the personalized appendix. Request at least the product name or identifier and exact share class; invite, but do not require, current weight or amount, currency, and recurring-investment plan. If the user declines, still provide the complete independent market report and mark the personalized appendix unavailable.
- Resolve each holding's underlying index or strategy, geography, sector, currency, rate sensitivity, commodity exposure, and product-specific frictions.
- Map direct effects, indirect effects, and offsets from the market conclusions.
- Separate short-term price effects, medium-term earnings or policy effects, and long-term thesis effects.
- Analyze portfolio interactions: concentration, hidden overlap, currency exposure, correlation shifts, diversification, and recurring-investment risk.
- State whether the original investment thesis or only the near-term price environment changed.
- Use restrained outcomes such as `plan unchanged`, `watch closely`, or `review threshold reached`. Do not turn daily noise into a buy/sell instruction.

If reliable portfolio data are unavailable, still deliver the complete market report and mark the personalized appendix as incomplete. Never shrink the market report to compensate.

### 8. Validate before delivery

- Check dates, units, currencies, fund share classes, trading sessions, and data lags.
- Recalculate streaks, new-high or new-low claims, and cumulative returns from the dated underlying price series. Never treat consecutive positive candles, a cumulative gain, or a secondary-source phrase as proof of consecutive close-to-close gains.
- For QDII and overseas-linked funds, account for valuation-day mismatch and FX translation.
- For gold-linked products, distinguish international gold, renminbi gold, exchange rate, domestic premium or discount, and product fees.
- Red-team the strongest conclusion and disclose the most important counterevidence.
- Remove generic news summaries that do not change the market interpretation.
- Make the conclusion proportional to evidence quality.

## Daily-report behavior

- Lead with the market's central question, not a holdings update.
- Use the three reading layers: one-minute view, complete market research, and personalized appendix.
- In the one-minute view, name the three most important developments and whether the prior thesis changed.
- Explain why assets moved and whether the explanation is durable.
- Report no material change when that is the honest conclusion.
- Keep the full-market report useful to a reader with no portfolio.
- Put all personalized material under a visibly separate heading near the end.
- Scan all relevant sectors daily, but expand only material rotation and opportunity candidates.
- Keep routine days compact: do not repeat the same fact in the dashboard, narrative, causal table, and watchlist. On quiet days, explicitly report no material regime or rotation change and shorten the deep dives. Expand only sections affected by a genuinely material event.

## Boundaries

- Support research and decision discipline; do not claim guaranteed returns or privileged predictive power.
- Do not execute trades or alter recurring investments unless the user separately and explicitly requests that action.
- Never interpret an opportunity flag, candidate index, or product shortlist as authorization to invest. The user decides whether to investigate further and whether to execute.
- Do not let promotional language, analyst targets, social sentiment, or a single technical indicator override primary evidence.
