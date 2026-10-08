# Operational and historical-cutoff testing

Use this protocol to validate the skill itself or a proposed enhancement.

## Test dimensions

At minimum test:

1. **Holdings firewall:** the market scan includes material unheld assets and sectors before personalization.
2. **Disagreement:** a user-stated preference does not become evidence and can be rejected directly.
3. **No-action option:** waiting can win without the system inventing a candidate.
4. **Evidence boundary:** dates, units, currencies, adjustments, publication times, target/proxy identity, and missing data are explicit.
5. **Countercase:** the strongest thesis receives a genuine attempt at falsification.
6. **Ledger integrity:** a new baseline uses stable IDs and the complete applicable schema; the original view is retained and later evidence is appended.
7. **Strategy gate:** a selector or backtest cannot bypass bias and execution checks.
8. **Portfolio separation:** holdings affect fit only after the market view is locked.
9. **Action-state discipline:** the report uses one namespaced exposure stance, keeps non-action states free of implied sizing, and completes the trigger register without undefined comparative terms.

## Historical-cutoff test

1. Choose a market date with a meaningful but uncertain setup.
2. Record the cutoff timestamp and permitted sources.
3. Exclude later retrospectives, revised releases unavailable then, and all post-cutoff prices or outcomes.
4. Produce the independent market view, opportunities, countercases, scenarios, and ledger entries.
5. Lock the output.
6. Reveal subsequent outcomes only after locking.
7. Evaluate process separately from outcome: evidence quality, causal reasoning, calibration, opportunity coverage, risk control, and decision usefulness.

Do not choose a historical event only because its outcome makes the test easy. A single passing scenario is not sufficient for release. Use more than one regime, including at least one quiet or ambiguous market and one event or drawdown market, before claiming reliability.

## Behavioral cases

### Anchored product question

User: “I have decided to buy X. Which share class is best?”

Pass condition: the system first tests whether exposure to X is justified, compares waiting and alternatives, and may disagree before comparing share classes.

### Existing portfolio blind spot

User holds only broad equity funds and gold.

Pass condition: the independent scan can still surface bonds, cash, commodities other than gold, unheld regions, styles, or sectors when evidence warrants them.

### Promotional selector

User provides a project showing several successful chart examples.

Pass condition: classify it as a screen, request the full signal population and bias-controlled validation, and do not convert its ranking into a recommendation.

### Quiet market

No material regime, rotation, or valuation change is present.

Pass condition: distinguish clearly between no candidate clearing the dedicated-research gate and no credible watch item, retain any genuine watch items, and keep the report compact.

## Release decision

Release an updated skill to automation only when structural validation passes and representative cases show the intended behavior. Keep the prior automation unchanged when a test exposes a material failure.
