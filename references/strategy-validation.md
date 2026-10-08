# Strategy and backtest validation gate

Use this gate for stock selectors, chart-pattern matchers, technical indicators, factors, AI ratings, backtests, and generated trading strategies.

## Classify the claim first

- **Screen:** narrows a universe; it does not estimate expected return.
- **Explanatory model:** organizes evidence; it does not predict by itself.
- **Predictive strategy:** claims a repeatable relationship between signal and future outcome.
- **Executable strategy:** defines tradable timing, position, costs, and constraints.

Do not present a screen or similarity score as an executable strategy.

## Gate 1: formal specification

Define the universe, signal inputs, calculation time, entry and exit rules, holding period, position construction, rebalance schedule, benchmark, and parameter-selection process. If these cannot be stated before testing, the result is not reproducible.

## Gate 2: point-in-time data

Check:

- publication and availability time, especially financial statements and revised macro data;
- adjustment basis for prices and corporate actions;
- delisted, suspended, ST, newly listed, and unavailable securities;
- changing index constituents and industry classifications;
- missing-data treatment;
- survivorship, selection, and look-ahead bias;
- timezone and market-calendar alignment.

## Gate 3: executable simulation

Model the market being traded, including:

- T+1 or other settlement and trading constraints;
- limit-up, limit-down, suspension, minimum lot, and liquidity constraints;
- entry price actually available after signal calculation;
- commission, taxes, spread, slippage, tracking difference, premium or discount, and turnover;
- cash drag and unfilled orders.

## Gate 4: robustness

- Separate training, validation, and untouched test periods.
- Prefer nested or rolling walk-forward validation to selecting on the full history.
- Compare with a relevant passive benchmark and a simple credible strategy.
- Report return, volatility, drawdown, turnover, trade count, hit rate, and regime dependence.
- Test parameter sensitivity and nearby specifications.
- Account for the number of tried signals and abandoned variants.
- Investigate whether performance depends on a few securities, dates, or regimes.

## Gate 5: forward test

Freeze the rules and run a paper portfolio prospectively. Record every signal, including failures and non-tradable signals. Do not retune the strategy during the scoring window without starting a new version.

## Evidence labels

Use only:

- `unverified idea`;
- `research candidate`;
- `historically robust candidate`;
- `forward-tested candidate`.

Never call a strategy proven. A positive backtest is evidence about a historical implementation, not a promise of future returns.

## Specific warning for example-matching systems

A library built from selected successful examples can automate visual screening, but it does not establish predictive power. Require the complete population of historical signals, failed examples, an untouched test period, realistic costs, and a frozen forward test before the score can affect real-capital discussion.

## External project lessons

Borrow from `tick-stock-panel` the point-in-time treatment of financial data, realistic A-share constraints, costs and slippage, benchmark comparison, candidate isolation, and nested out-of-sample validation. Do not treat its published thresholds as universal.

Treat `a-share-quant-selector` as a screen until independent tests establish otherwise. Its similarity ranking and hand-selected successful patterns are candidate-generation features, not evidence of expected return.
