from __future__ import annotations

from typing import Any

from shared.enums import Direction
from shared.models import Fundamentals, Macro, Sentiment, Signal, Technicals


def _weight(weights: dict[str, float], key: str) -> float:
    return float(weights[key])


def generate_signals(
    technicals: Technicals,
    fundamentals: Fundamentals,
    sentiment: Sentiment,
    macro: Macro,
    weights: dict[str, float],
    thresholds: dict[str, Any],
) -> list[Signal]:
    signal_thresholds = thresholds["signals"]
    signals: list[Signal] = []

    if technicals.rsi_14 is not None:
        if technicals.rsi_14 < signal_thresholds["rsi_buy_below"]:
            direction = Direction.BUY
            note = f"RSI {technicals.rsi_14:.0f} is approaching oversold"
        elif technicals.rsi_14 > signal_thresholds["rsi_sell_above"]:
            direction = Direction.SELL
            note = f"RSI {technicals.rsi_14:.0f} is overbought"
        else:
            direction = Direction.HOLD
            note = f"RSI {technicals.rsi_14:.0f} is neutral"
        signals.append(Signal(dimension="RSI(14)", signal=direction, weight=_weight(weights, "RSI_14"), note=note))

    if technicals.macd.histogram is not None:
        direction = Direction.BUY if technicals.macd.histogram > 0 else Direction.SELL if technicals.macd.histogram < 0 else Direction.HOLD
        signals.append(Signal(dimension="MACD", signal=direction, weight=_weight(weights, "MACD"), note=f"MACD histogram {technicals.macd.histogram:.2f}"))

    if technicals.ma_50 is not None and technicals.ma_200 is not None:
        direction = Direction.BUY if technicals.ma_50 >= technicals.ma_200 else Direction.SELL
        signals.append(Signal(dimension="MA 50/200", signal=direction, weight=_weight(weights, "MA_50_200"), note="Golden cross in effect" if direction == Direction.BUY else "50D average below 200D"))

    if technicals.bb_mid is not None and technicals.bb_upper is not None and technicals.bb_lower is not None:
        direction = Direction.HOLD
        note = "Price near Bollinger mid-band"
        signals.append(Signal(dimension="Bollinger Bands", signal=direction, weight=_weight(weights, "Bollinger_Bands"), note=note))

    if technicals.volume_ratio_90d is not None:
        direction = Direction.BUY if technicals.volume_ratio_90d >= signal_thresholds["volume_buy_above"] else Direction.HOLD
        signals.append(Signal(dimension="Volume", signal=direction, weight=_weight(weights, "Volume"), note=f"Volume ratio {technicals.volume_ratio_90d:.2f} vs 90D average"))

    if technicals.rsi_weekly is not None:
        direction = Direction.BUY if technicals.rsi_weekly >= signal_thresholds["weekly_rsi_buy_above"] else Direction.HOLD
        signals.append(Signal(dimension="RSI Weekly", signal=direction, weight=_weight(weights, "RSI_Weekly"), note=f"Weekly RSI {technicals.rsi_weekly:.0f}"))

    if technicals.support_levels and technicals.resistance_levels:
        signals.append(Signal(dimension="Support/Resistance", signal=Direction.HOLD, weight=_weight(weights, "Support_Resistance"), note=f"Range ${technicals.support_levels[0]:.2f}-${technicals.resistance_levels[0]:.2f}"))

    if fundamentals.eps_surprise_pct is not None:
        if fundamentals.eps_surprise_pct >= signal_thresholds["eps_buy_above"]:
            direction = Direction.BUY
        elif fundamentals.eps_surprise_pct <= signal_thresholds["eps_sell_below"]:
            direction = Direction.SELL
        else:
            direction = Direction.HOLD
        signals.append(Signal(dimension="EPS Surprise", signal=direction, weight=_weight(weights, "EPS_Surprise"), note=f"EPS surprise {fundamentals.eps_surprise_pct:.1f}%"))

    if fundamentals.pe_percentile_5y is not None:
        if fundamentals.pe_percentile_5y > signal_thresholds["pe_sell_above"]:
            direction = Direction.SELL
        elif fundamentals.pe_percentile_5y < signal_thresholds["pe_buy_below"]:
            direction = Direction.BUY
        else:
            direction = Direction.HOLD
        signals.append(Signal(dimension="PE Percentile", signal=direction, weight=_weight(weights, "PE_Percentile"), note=f"{fundamentals.pe_percentile_5y:.0f}th percentile"))

    if fundamentals.analyst_upgrades_30d is not None and fundamentals.analyst_downgrades_30d is not None:
        net = fundamentals.analyst_upgrades_30d - fundamentals.analyst_downgrades_30d
        direction = Direction.BUY if net > signal_thresholds["analyst_net_buy_above"] else Direction.SELL if net < 0 else Direction.HOLD
        signals.append(Signal(dimension="Analyst Ratings", signal=direction, weight=_weight(weights, "Analyst_Ratings"), note=f"Net revisions {net} over 30D"))

    if sentiment.put_call_ratio is not None:
        if sentiment.put_call_ratio < signal_thresholds["put_call_buy_below"]:
            direction = Direction.BUY
        elif sentiment.put_call_ratio > signal_thresholds["put_call_sell_above"]:
            direction = Direction.SELL
        else:
            direction = Direction.HOLD
        signals.append(Signal(dimension="Put/Call Ratio", signal=direction, weight=_weight(weights, "Put_Call_Ratio"), note=f"Put/call {sentiment.put_call_ratio:.2f}"))

    if sentiment.iv_rank is not None:
        direction = Direction.HOLD if sentiment.iv_rank < signal_thresholds["iv_hold_below"] else Direction.SELL
        signals.append(Signal(dimension="IV Rank", signal=direction, weight=_weight(weights, "IV_Rank"), note=f"IV rank {sentiment.iv_rank:.0f}"))

    if sentiment.short_interest_pct is not None:
        direction = Direction.SELL if sentiment.short_interest_pct > signal_thresholds["short_interest_sell_above"] else Direction.HOLD
        signals.append(Signal(dimension="Short Interest", signal=direction, weight=_weight(weights, "Short_Interest"), note=f"Short interest {sentiment.short_interest_pct:.1f}%"))

    if sentiment.institutional_net_shares_last_13f is not None:
        direction = Direction.BUY if sentiment.institutional_net_shares_last_13f > 0 else Direction.SELL if sentiment.institutional_net_shares_last_13f < 0 else Direction.HOLD
        signals.append(Signal(dimension="Institutional 13F", signal=direction, weight=_weight(weights, "Institutional_13F"), note=f"Net shares {sentiment.institutional_net_shares_last_13f:.0f}"))

    if macro.days_to_next_fomc is not None:
        direction = Direction.HOLD
        signals.append(Signal(dimension="Macro (FOMC)", signal=direction, weight=_weight(weights, "FOMC_Proximity"), note=f"{macro.days_to_next_fomc} days to next FOMC"))

    return signals
