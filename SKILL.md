---
name: analyze-markets-and-portfolio
description: Research stocks, ETFs and off-exchange funds, assess market direction, develop entry and add-position plans, and discover concrete investment candidates independently. Use for security questions, fund look-through, market opportunity scans and strategy evaluation; collect and verify the data needed for the decision.
---

# Market and Fund Research

Improve the user's investment decisions with independent research, constructive alternatives and evidence that can be revisited. Respond in the user's language and make a clear judgment at the strength supported by the facts. Keep necessary scientific qualifications; omit generic disclaimers and repetitive risk prose.

## Choose the scope

- **Stock/fund analysis or autonomous opportunity discovery:** read [investment-outcomes.md](references/investment-outcomes.md) for the requested functional outcomes. Collect the data proactively, complete material follow-up research and reach a concrete, horizon-specific conclusion. Autonomous discovery includes due diligence on named securities/products and timing plans; a list of sector leads alone does not finish it.
- **One stock and its entry/addition decision:** read [stock-research-workflow.md](references/stock-research-workflow.md). Use scripts for collection, curves and repeatable calculations; form the final independent research judgment from the full evidence rather than copying a fixed model/rule output.

- **Complete allocation/tactical chain:** read [research-workflow.md](references/research-workflow.md) to freeze independent evidence, lock the market view and load private holdings afterwards.

- **Focused market or investment question:** read [decision-protocol.md](references/decision-protocol.md) when comparing an action, alternatives, the existing plan and waiting. Answer the question without expanding it into a full report.
- **One fund and its allocation/addition decision:** read [fund-research-workflow.md](references/fund-research-workflow.md), then the relevant product mechanics in [fund-research.md](references/fund-research.md). `research-fund` assembles supported evidence; continue the independent underlying/product research to a complete report and exact-share action plan.
- **Structured collection, indicators, discovery or data diagnosis:** read [data-engine.md](references/data-engine.md) and [provider-registry.md](references/provider-registry.md). Check [validation-status.md](references/validation-status.md) for the dated test boundary, and [local-runtime.md](references/local-runtime.md) for this machine's isolated interpreter. Verify the live state needed for this request.
- **Complete daily/weekly report:** read [full-market-workflow.md](references/full-market-workflow.md) and [report-template.md](references/report-template.md). Keep independent market research and the personalized appendix separate; vary depth with materiality.
- **No candidate supplied / proactive opportunity discovery:** read [autonomous-research-workflow.md](references/autonomous-research-workflow.md). Continue from a market/sector scan to named securities and exact fund shares within the same request. Use [sector-opportunity-framework.md](references/sector-opportunity-framework.md) for evidence gates and [transmission-map.md](references/transmission-map.md) for material cross-asset channels.
- **Prior-view review:** read [thesis-ledger.md](references/thesis-ledger.md). **Backtest or systematic-strategy claims:** read [strategy-validation.md](references/strategy-validation.md). **Historical-cutoff evaluation:** read [operational-test-protocol.md](references/operational-test-protocol.md).
- **Requested automation changes:** read [automation-instructions.md](references/automation-instructions.md), inspect the actual existing task and preserve its identity, schedule, enabled state, holdings and notification requirements.

## Market first, holdings last

Discover and form market theses independently of holdings, preferences and the user's proposed trade. For a focused question, establish the independent security/product conclusion before adapting it to the user's position. For a full portfolio report using the packaged engine, lock the market view and candidate states before loading the authoritative portfolio. Then map exposure, concentration, overlap, currency and product constraints. Holdings already present in context do not define the discovery universe. Never infer positions or share classes from examples, memory or a starter configuration.

The research universe includes equities, regions, styles, rates/credit, FX, commodities and investable products. A configured watchlist or collected subset is not a full-market scan. Report the requested scope, actual coverage and missing areas. Collection of every tick is not necessary for broad discovery; collect deeper histories only for shortlisted questions.

## Complete the user's research request

Tools produce evidence and calculations; the skill must connect them to a clear investment judgment. A catalogue of data, a technical chart, an announcement download, a screen result or a script's rule-based opinion is an intermediate result. Finish the relevant stock/fund/discovery workflow and explain the strongest countercase before presenting the action plan.

Use the bundled collector for supported data and repeatable calculations. Use current official pages, filings and available public sources for material evidence it does not yet collect. A missing adapter is a reason to choose another retrieval route, not to stop at an empty field. Keep source failure separate from a field that is not disclosed. Avoid repeated identical failed requests; use a materially different source or narrow the affected claim.

For KDJ, RSI, estimated cost distributions, adjustment/dividend data and source priorities, read [technical-and-source-extensions.md](references/technical-and-source-extensions.md). Use these measurements where they change the timing or price discussion; they do not add universal all-indicator entry gates.

When developing or testing this skill, use a bounded representative sample tied to a specific acceptance question. Stop collecting sample documents when that question is resolved and return to reusable instructions/tools. Historical sample codes, holdings and thresholds are test inputs, not defaults for future research.

## Data and interpretation

Use the relevant configured collection profile and read `health`, `snapshot` and the question-specific `evidence` package before interpreting structured numbers. If a profile is not configured, inspect existing data and collect the targeted fields that are feasible; continue official-source research while explicitly retaining numerical gaps. Do not require unrelated collectors for a focused question or replace a failed field with an undated snippet.

Keep raw/provider-reported values, local calculations, vendor-derived classifications and analytical interpretation distinct. Preserve identity, source, observation and publication time, timezone, units, currency, session, adjustment basis and revision. Calendar age alone does not establish staleness; use the relevant exchange/valuation calendar and read-time policy. An observation-date cutoff alone is not a point-in-time test.

MACD, volume ratio, inner/outer volume, displayed-book imbalance and vendor flows can support directional and timing judgments. They do not by themselves prove earnings improvement, institutional identity or a calibrated return probability. Retain the provider's BBD/DDE/flow definitions. An index with zero book fields has no usable order book. Never merge providers, currencies or adjustment variants into one series. Return windows on minute bars mean bars, not days.

For any material missing, conflicting, stale or unmatched core evidence, downgrade the affected conclusion. A proxy ETF is not its index, an ETF's traded price is not its NAV, cumulative NAV is not a dividend-reinvested total-return series, and a long yield is not short-duration evidence. Preserve a valid underlying-market judgment when only wrapper details are missing, while deferring product selection.

## Judgment and discovery

Challenge unsupported proposals plainly. Compare the user's proposal, a credible alternative, the existing plan and waiting when relevant. Explain the changed expectation, transmission channel, horizon, strongest countercase and invalidation condition; simultaneous moves are not causal proof.

The executable `screen` prioritizes questions, with `needs_investigation`, `insufficient_evidence` or `no_significant_signal`. It does not produce a probability or investment stance. Obtain the evidence needed for the actual thesis and apply the decision protocol; a fact-qualification gate for one opportunity type is not a universal requirement that every catalyst has already happened. Two descriptions of one event or two same-event price moves are one evidence cluster. Multiple roles of one LLM are not independent evidence or a separate trained quantitative model.

Use `worth dedicated research`, `watch` or `not yet` only after the framework's evidence gate. A non-action state must not end with an unsupported small-buy suggestion. Triggers need a source, metric/event, direction or threshold, observation window and review point. A quiet market may have no qualified candidate.

These are intermediate research states. After completing the relevant due diligence and portfolio review, give the final recommendation: build, add, hold, reduce, exit or wait, with its conditions and reasoning. Keep the preliminary research state and final action plan distinct. When personal amounts are absent, state the independent market decision and the sizing inputs or clearly labeled budget scenario needed to turn it into a personal plan.

## Decide under uncertainty

Lead with a preferred current action and a horizon-specific direction. Investment judgment is an inference from available evidence; it need not wait for proof of future returns or agreement among every indicator. Compare acting now, entering before a catalyst, waiting for price confirmation and an alternative when relevant. A credible early thesis may support a staged entry before trend confirmation; explain its expected recognition mechanism, price/valuation tradeoff and invalidation. Do not convert a confirmation setup or the bundled script's default into a universal purchase gate.

Hard restrictions concern unreliable core data, a false instrument/claim, an unresolved material risk that could overturn the thesis, or an infeasible implementation. Ordinary uncertainty, an unproven model edge, missing noncore flow/book fields and an event not yet realized affect confidence, sizing or the affected claim; they do not automatically require waiting. Waiting is a substantive decision only when its expected benefit exceeds its opportunity cost, with a named reason and reassessment point.

User-facing research gives the judgment, evidence and execution plan. Keep engineering acceptance, test coverage, model-validation status and repeated “cannot prove” language in supporting records unless the user asks or the fact changes this investment decision. Mention each material limitation once near its affected claim. Distinguish observed fact, management expectation and your own forecast naturally, without appending generic defensive conclusions.

## Accountability and release

Preserve original theses, horizons, benchmarks and conditions. Append dated reviews and outcomes; do not rewrite prior claims using hindsight. Use authoritative holdings only after the market view is locked. Report material evidence near the claim and distinguish verified collection from code availability.

The collector uses free public sources and optional free registered APIs. Keys belong in the executing process environment, never in shared config, logs, reports or source. Runtime databases/configuration live outside the installed skill. Validate the edited skill's entrypoint, references, changed tools and representative request behavior before delivering it. Separately, a recurring collector needs representative target-machine checks and at least five consecutive trading sessions before its operational release. That operational gate does not turn a skill-editing request into automation deployment. Updating this skill alone does not authorize changing an existing automation or executing transactions.
