from __future__ import annotations

from typing import Sequence

from .models import Observation


def summarize_transactions(
    rows: Sequence[Observation],
    *,
    lot_size: float = 100.0,
    large_notional: float = 200_000.0,
    super_large_notional: float = 1_000_000.0,
) -> Observation:
    """Build a reproducible order-size summary from provider-classified ticks."""

    if not rows:
        raise ValueError("transaction rows are required")
    if lot_size <= 0 or large_notional <= 0 or super_large_notional <= large_notional:
        raise ValueError("lot size and order-size thresholds are invalid")
    totals = {
        "coverage": "input_records_only_not_full_session",
        "lot_size_assumption": lot_size,
        "lot_size_verified": all(row.raw.get("lot_size_verified", False) for row in rows),
        "buy_notional": 0.0,
        "sell_notional": 0.0,
        "neutral_notional": 0.0,
        "buy_volume": 0.0,
        "sell_volume": 0.0,
        "neutral_volume": 0.0,
        "large_buy_notional": 0.0,
        "large_sell_notional": 0.0,
        "large_buy_volume": 0.0,
        "large_sell_volume": 0.0,
        "super_large_buy_notional": 0.0,
        "super_large_sell_notional": 0.0,
        "super_large_buy_volume": 0.0,
        "super_large_sell_volume": 0.0,
    }
    usable = 0
    for row in rows:
        value = row.value if isinstance(row.value, dict) else {}
        try:
            price = float(value["price"])
            volume = float(value["volume"])
        except (KeyError, TypeError, ValueError):
            continue
        if price <= 0 or volume <= 0:
            continue
        usable += 1
        notional = price * volume * lot_size
        direction = str(value.get("direction", "unknown"))
        side = "buy" if direction == "provider_buy" else "sell" if direction == "provider_sell" else "neutral"
        totals[f"{side}_notional"] += notional
        totals[f"{side}_volume"] += volume
        if side != "neutral" and notional >= large_notional:
            totals[f"large_{side}_notional"] += notional
            totals[f"large_{side}_volume"] += volume
        if side != "neutral" and notional >= super_large_notional:
            totals[f"super_large_{side}_notional"] += notional
            totals[f"super_large_{side}_volume"] += volume

    if usable == 0:
        raise ValueError("transaction rows contained no usable price-volume pairs")
    totals.update(
        {
            "net_active_notional": totals["buy_notional"] - totals["sell_notional"],
            "large_net_notional": totals["large_buy_notional"] - totals["large_sell_notional"],
            "super_large_net_notional": (
                totals["super_large_buy_notional"] - totals["super_large_sell_notional"]
            ),
            "usable_tick_count": usable,
            "lot_size_assumption": lot_size,
            "large_notional_threshold": large_notional,
            "super_large_notional_threshold": super_large_notional,
        }
    )
    latest = max(rows, key=lambda row: row.as_of)
    latest_value = latest.value if isinstance(latest.value, dict) else {}
    symbol = str(latest_value.get("symbol") or latest.identity.split("#", 1)[0])
    return Observation(
        provider="local_engine",
        dataset="tick_order_size_summary",
        identity=symbol,
        as_of=latest.as_of,
        value=totals,
        unit="CNY_and_provider_native_lot",
        currency="CNY",
        latency=latest.latency,
        quality="locally_derived_from_provider_trade_direction",
        source_url=latest.source_url,
        raw={
            "input_provider": latest.provider,
            "input_dataset": latest.dataset,
            "warning": "direction is provider-classified and does not identify beneficial owners",
        },
    )
