# KDJ, RSI and cost structure

KDJ(9,3,3) is calculated from one verified OHLC series, using a full nine-bar RSV window, recursive weights 1/3, K/D seed 50 and flat-window RSV 50. The J line is not clipped to 0–100. RSI14 uses Wilder smoothing and is already calculated from stock closes and published fund NAV. Stock charts show KDJ and RSI; the latest values and parameters appear in `technical_context` and frozen `curves.json`. NAV alone has no daily traded high/low: use RSI for the fund and KDJ for its appropriate traded underlying, without relabeling that underlying as the fund.

Domestic `research-stock` also attempts estimated cost-distribution research. To run it separately:

```powershell
python scripts/market_engine.py --db <external-database> research-chips sh600276 --output-dir <new-directory>
python scripts/market_engine.py verify-chips --directory <that-directory>
```

The input adapter collects completed-day front-adjusted OHLC and turnover from Eastmoney, with exact instrument/basis/date checks and HTTP receipts. BaoStock front-adjusted bars plus its own daily turnover are the fallback. One provider's prices and another provider's turnover are not silently combined. `--no-collect` uses an existing complete matched series. A missing turnover value is not zero; incomplete series report a scoped gap and do not interrupt independent stock research.

The local model uses a triangular density within each day's high/low range and decays existing mass by min(turnover/100, 1). It uses at most 240 matched days, at least 60. The first day seeds the unknown earlier inventory; the residual `unknown_initial_weight_fraction` measures how much of that assumed inventory survives. A large residual makes exact peak/cost interpretations sensitive to the starting assumption. Price bins are bounded and normalized. Turnover above 100% is recorded and capped for the inventory-replacement model, not changed in raw data.

The output contains a distribution chart, estimated mean/median cost, fraction below current close, 70%/90% central cost regions, concentration and dominant peak. Mean and median are separate. Concentration is (upper−lower)/(upper+lower); it is not the share of real investors. This is an explicitly named local estimate, not a downloaded vendor CYQ value or institution-cost record. Preserve its provider, currency, date and adjustment basis. Compare its price levels with traded prices only after checking basis alignment. Latest-position front-adjusted history is not a historical point-in-time vintage.

Use cost clusters to discuss nearby supply/demand and alternative entry routes together with volume, business and valuation. A concentrated distribution, KDJ cross or RSI threshold does not independently establish accumulation or require buying. Report the material interpretation once; final direction and action remain independent research judgments.

# Necessary source priorities

1. **Corporate actions and return basis:** BaoStock now exposes `fetch-cn-corporate-actions <stock> --start YYYY-MM-DD --end YYYY-MM-DD`. It retains adjustment factors and original-unit dividend records, declaration/record/ex/payment dates and coverage. Dividend data cover the last two operate-years within the requested window; factors cover the declared window. Provider dividend fields require primary notice/unit review before use in cash-flow or total-return calculations. A distribution-induced raw-price gap is not automatically a business deterioration or trend break. Do not count adjusted price gains plus the same dividend twice.
2. **Latest financials and upcoming events:** when company earnings or an event drives the thesis, compare the most recent available statutory report with the period already stored. Follow original filings/IR and exchange disclosures for earnings dates, results, shareholder events, unlocking and other material catalysts. Announced dates are facts; estimates have an explicit source/status. Existing registered PDFs and vendor fields do not establish universal latest-report coverage.
3. **ETF price versus NAV:** for exchange ETF selection, check recent NAV/IOPV and its time, bid/ask liquidity, premium/discount, tracking and wrapper terms when those change the choice. Do not compare unlike-date QDII NAV and a live quote as a verified same-time premium. A reliable matching source can be researched on demand; no universal IOPV adapter is claimed.
4. **Macro/industry facts:** use official rates, credit, currency and releases already available, plus the industry's concrete demand/order/inventory/pricing data. Collect only those that can change this thesis, from their original publications.

Stable exchange Level-2/ticks, exact beneficial owners and all funds' undisclosed current positions remain outside the verified free-source coverage. Their absence limits the corresponding microstructure claims, not every investment action. Adding more wrappers over the same Eastmoney source does not create independent evidence.

Sources: [AKShare public source documentation](https://akshare.akfamily.xyz/data/stock/stock.html) describes daily OHLC/turnover and its own separate CYQ implementation; [BaoStock](https://www.baostock.com/) supplies the implemented adjustment/dividend query contracts. The local chip model is independently specified above and makes no numerical-equivalence claim with either vendor software.
