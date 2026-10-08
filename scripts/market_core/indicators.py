from __future__ import annotations

from math import isfinite
from typing import Iterable, Sequence

from .models import Bar, IndicatorValue, Observation, Quote
from .conventions import interval_name, price_basis_name
from .lineage import prefix_lineages


def ema(values: Sequence[float], period: int) -> list[float]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not values:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def macd(
    closes: Sequence[float], fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[list[float], list[float], list[float]]:
    if fast >= slow:
        raise ValueError("fast period must be smaller than slow period")
    fast_line = ema(closes, fast)
    slow_line = ema(closes, slow)
    dif = [a - b for a, b in zip(fast_line, slow_line)]
    dea = ema(dif, signal)
    histogram = [2.0 * (a - b) for a, b in zip(dif, dea)]
    return dif, dea, histogram


def rsi(closes: Sequence[float], period: int = 14) -> list[float | None]:
    if period <= 0:
        raise ValueError("period must be positive")
    if not closes:
        return []
    result: list[float | None] = [None] * len(closes)
    if len(closes) <= period:
        return result
    gains: list[float] = []
    losses: list[float] = []
    for previous, current in zip(closes, closes[1:]):
        change = current - previous
        gains.append(max(change, 0.0))
        losses.append(max(-change, 0.0))
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period
    result[period] = 50.0 if avg_loss == avg_gain == 0 else 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    for index in range(period + 1, len(closes)):
        avg_gain = ((period - 1) * avg_gain + gains[index - 1]) / period
        avg_loss = ((period - 1) * avg_loss + losses[index - 1]) / period
        result[index] = 50.0 if avg_loss == avg_gain == 0 else 100.0 if avg_loss == 0 else 100.0 - 100.0 / (1 + avg_gain / avg_loss)
    return result


def kdj(bars: Sequence[Bar], period: int = 9, k_smoothing: int = 3, d_smoothing: int = 3):
    """Full-window RSV; recursive SMA weights 1/m, initial K=D=50, flat RSV=50."""
    if any(type(p) is not int or p <= 0 for p in (period, k_smoothing, d_smoothing)):
        raise ValueError('KDJ periods must be positive integers')
    output = [[None] * len(bars) for _ in range(3)]
    k = d = 50.0
    for i, bar in enumerate(bars):
        if not all(isfinite(v) for v in (bar.high, bar.low, bar.close)) or not bar.low <= bar.close <= bar.high:
            raise ValueError('KDJ requires finite valid high/low/close')
        if i + 1 < period:
            continue
        window = bars[i + 1 - period:i + 1]
        high, low = max(b.high for b in window), min(b.low for b in window)
        rsv = 50.0 if high == low else 100 * (bar.close - low) / (high - low)
        k += (rsv - k) / k_smoothing
        d += (k - d) / d_smoothing
        output[0][i], output[1][i], output[2][i] = k, d, 3 * k - 2 * d
    return tuple(output)


def atr(bars: Sequence[Bar], period: int = 14) -> list[float | None]:
    if not bars:
        return []
    true_ranges: list[float] = []
    for index, row in enumerate(bars):
        if index == 0:
            true_ranges.append(row.high - row.low)
        else:
            previous_close = bars[index - 1].close
            true_ranges.append(
                max(row.high - row.low, abs(row.high - previous_close), abs(row.low - previous_close))
            )
    result: list[float | None] = [None] * len(bars)
    if len(bars) < period:
        return result
    current = sum(true_ranges[:period]) / period
    result[period - 1] = current
    for index in range(period, len(bars)):
        current = ((period - 1) * current + true_ranges[index]) / period
        result[index] = current
    return result


def close_volume_ratio(volumes: Sequence[float | None], lookback: int = 5) -> list[float | None]:
    result: list[float | None] = [None] * len(volumes)
    for index in range(lookback, len(volumes)):
        history = [float(v) for v in volumes[index - lookback:index] if v is not None and v > 0]
        current = volumes[index]
        if len(history) == lookback and current is not None:
            average = sum(history) / lookback
            result[index] = float(current) / average if average else None
    return result


def trailing_return(closes: Sequence[float], periods: int) -> list[float | None]:
    if periods <= 0:
        raise ValueError("periods must be positive")
    result: list[float | None] = [None] * len(closes)
    for index in range(periods, len(closes)):
        base = float(closes[index - periods])
        result[index] = (float(closes[index]) / base - 1.0) if base else None
    return result


def intraday_volume_ratio(
    current_cumulative_volume: float,
    elapsed_trading_minutes: int,
    previous_daily_volumes: Sequence[float],
    *,
    full_session_minutes: int = 240,
    lookback: int = 5,
) -> float | None:
    """Compare today's average volume/minute with the prior full-day average/minute."""

    history = [float(v) for v in previous_daily_volumes[-lookback:] if v > 0]
    if elapsed_trading_minutes <= 0 or len(history) != lookback:
        return None
    current_rate = current_cumulative_volume / elapsed_trading_minutes
    historical_rate = (sum(history) / lookback) / full_session_minutes
    return current_rate / historical_rate if historical_rate else None


def order_book_imbalance(quote: Quote) -> float | None:
    bid = sum(float(level.get("volume", 0.0)) for level in quote.bid_book)
    ask = sum(float(level.get("volume", 0.0)) for level in quote.ask_book)
    total = bid + ask
    return (bid - ask) / total if total else None


def inner_outer_ratio(quote: Quote) -> float | None:
    if quote.inner_volume is None or quote.outer_volume is None or quote.inner_volume == 0:
        return None
    return quote.outer_volume / quote.inner_volume


def breadth(changes: Iterable[float | None]) -> dict[str, float | int | None]:
    clean = [float(value) for value in changes if value is not None and isfinite(float(value))]
    if not clean:
        return {"advancers": 0, "decliners": 0, "unchanged": 0, "advance_ratio": None}
    advancers = sum(value > 0 for value in clean)
    decliners = sum(value < 0 for value in clean)
    unchanged = len(clean) - advancers - decliners
    denominator = advancers + decliners
    return {
        "advancers": advancers,
        "decliners": decliners,
        "unchanged": unchanged,
        "advance_ratio": advancers / denominator if denominator else None,
    }


def indicator_rows(bars: Sequence[Bar]) -> list[IndicatorValue]:
    if not bars:
        return []
    closes = [row.close for row in bars]
    dif, dea, histogram = macd(closes)
    rsi_values = rsi(closes)
    atr_values = atr(bars)
    k_values, d_values, j_values = kdj(bars)
    volume_ratios = close_volume_ratio([row.volume for row in bars])
    returns = {period: trailing_return(closes, period) for period in (1, 5, 20, 60)}
    provider = bars[-1].provider
    interval = interval_name(bars[-1].interval)
    lineages=prefix_lineages(bars,'bars')
    rows: list[IndicatorValue] = []
    for index, bar in enumerate(bars):
        items = (
            ("macd_dif", dif[index] if index >= 33 else None, {"fast": 12, "slow": 26, "signal": 9, "minimum_bars": 34}),
            ("macd_dea", dea[index] if index >= 33 else None, {"fast": 12, "slow": 26, "signal": 9, "minimum_bars": 34}),
            ("macd_histogram", histogram[index] if index >= 33 else None, {"fast": 12, "slow": 26, "signal": 9, "minimum_bars": 34}),
            ("rsi", rsi_values[index], {"period": 14}),
            ("kdj_k", k_values[index], {"period": 9, "k_smoothing": 3, "d_smoothing": 3, "seed": 50, "flat_rsv": 50}),
            ("kdj_d", d_values[index], {"period": 9, "k_smoothing": 3, "d_smoothing": 3, "seed": 50, "flat_rsv": 50}),
            ("kdj_j", j_values[index], {"period": 9, "k_smoothing": 3, "d_smoothing": 3, "seed": 50, "flat_rsv": 50}),
            ("atr", atr_values[index], {"period": 14}),
            ("close_volume_ratio", volume_ratios[index], {"lookback": 5}),
            ("return_1period", returns[1][index], {"periods": 1, "window_unit": "bars"}),
            ("return_5period", returns[5][index], {"periods": 5, "window_unit": "bars"}),
            ("return_20period", returns[20][index], {"periods": 20, "window_unit": "bars"}),
            ("return_60period", returns[60][index], {"periods": 60, "window_unit": "bars"}),
        )
        for name, value, parameters in items:
            rows.append(
                IndicatorValue(
                    symbol=bar.symbol,
                    interval=interval,
                    timestamp=bar.timestamp,
                    name=name,
                    value=value,
                    parameters={**parameters,'input_lineage':lineages[index]},
                    input_provider=provider,
                    price_basis=price_basis_name(bar.price_basis),
                    currency=bar.currency,
                    unit="ratio" if name.startswith("return_") or name == "close_volume_ratio" else "oscillator_unbounded" if name == "kdj_j" else "0_to_100" if name in {"rsi", "kdj_k", "kdj_d"} else "price",
                )
            )
    return rows


def indicator_rows_grouped(bars: Sequence[Bar]) -> list[IndicatorValue]:
    """Calculate each symbol/provider/interval independently."""

    groups: dict[tuple[str, str, str, str], list[Bar]] = {}
    for row in bars:
        groups.setdefault((row.provider, row.symbol, interval_name(row.interval), price_basis_name(row.price_basis)), []).append(row)
    output: list[IndicatorValue] = []
    for rows in groups.values():
        rows.sort(key=lambda item: item.timestamp)
        output.extend(indicator_rows(rows))
    return output


def series_indicator_rows(
    observations: Sequence[Observation], *, interval: str = "1d", limit: int = 500
) -> list[IndicatorValue]:
    """Calculate price-only indicators from a single numeric observation series."""

    usable: list[tuple[Observation, float]] = []
    for row in observations:
        try:
            usable.append((row, float(row.value)))
        except (TypeError, ValueError):
            continue
    usable = sorted(usable, key=lambda item: item[0].as_of)[-limit:]
    if not usable:
        return []
    identities={(row.provider,row.dataset,row.identity,row.revision,row.price_basis,row.currency) for row,_ in usable}
    if len(identities)!=1:raise ValueError('Published-series indicators require one provider/identity/revision/basis/currency')
    lineages=prefix_lineages([row for row,_ in usable],'observations')
    closes = [value for _, value in usable]
    dif, dea, histogram = macd(closes)
    rsi_values = rsi(closes)
    returns = {period: trailing_return(closes, period) for period in (1, 5, 20, 60)}
    rows: list[IndicatorValue] = []
    for index, (observation, _) in enumerate(usable):
        items = (
            ("macd_dif", dif[index] if index >= 33 else None, {"fast": 12, "slow": 26, "signal": 9, "minimum_observations": 34}),
            ("macd_dea", dea[index] if index >= 33 else None, {"fast": 12, "slow": 26, "signal": 9, "minimum_observations": 34}),
            ("macd_histogram", histogram[index] if index >= 33 else None, {"fast": 12, "slow": 26, "signal": 9, "minimum_observations": 34}),
            ("rsi", rsi_values[index], {"period": 14}),
            ("return_1period", returns[1][index], {"periods": 1, "window_unit": "published_observations"}),
            ("return_5period", returns[5][index], {"periods": 5, "window_unit": "published_observations"}),
            ("return_20period", returns[20][index], {"periods": 20, "window_unit": "published_observations"}),
            ("return_60period", returns[60][index], {"periods": 60, "window_unit": "published_observations"}),
        )
        for name, value, parameters in items:
            rows.append(
                IndicatorValue(
                    symbol=observation.identity,
                    interval=interval,
                    timestamp=observation.as_of,
                    name=name,
                    value=value,
                    parameters={**parameters,'input_lineage':lineages[index]},
                    input_provider=observation.provider,
                    quality="locally_derived_from_published_series",
                    price_basis=observation.price_basis,
                    currency=observation.currency,
                    unit="ratio" if name.startswith("return_") else "0_to_100" if name == "rsi" else "NAV_per_share",
                )
            )
    return rows


def quote_indicator_rows(quotes: Sequence[Quote]) -> list[IndicatorValue]:
    rows: list[IndicatorValue] = []
    for quote in quotes:
        lineage=prefix_lineages([quote],'quotes')[0]
        derived = (
            ("order_book_imbalance_5", order_book_imbalance(quote), {}, "locally_derived"),
            ("outer_inner_volume_ratio", inner_outer_ratio(quote), {}, "locally_derived_from_provider_classification"),
            ("volume_ratio_vendor", quote.volume_ratio_vendor, {}, "vendor_derived"),
            (
                "change_from_previous_close",
                (quote.last / quote.previous_close - 1.0)
                if quote.last is not None and quote.previous_close
                else None,
                {},
                "locally_derived",
            ),
        )
        for name, value, parameters, quality in derived:
            rows.append(
                IndicatorValue(
                    symbol=quote.symbol,
                    interval="snapshot",
                    timestamp=quote.as_of,
                    name=name,
                    value=value,
                    parameters={**parameters,'input_lineage':lineage},
                    input_provider=quote.provider,
                    quality=quality,
                    price_basis="unadjusted",
                    unit="ratio",
                    currency=quote.currency,
                )
            )
    return rows
