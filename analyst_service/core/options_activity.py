from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from shared.enums import Freshness


class OptionType(StrEnum):
    CALL = "call"
    PUT = "put"


class OptionsContextStatus(StrEnum):
    AVAILABLE = "available"
    CONTRADICTORY = "contradictory"
    UNKNOWN = "unknown"


class OptionsContextSignal(StrEnum):
    CALL_DOMINANCE = "call_dominance"
    PUT_DOMINANCE = "put_dominance"
    NEUTRAL = "neutral"
    UNKNOWN = "unknown"


class OptionQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    option_type: OptionType
    expiry: date
    strike: float = Field(gt=0)
    volume: int = Field(ge=0)
    open_interest: int = Field(ge=0)
    bid: float | None = Field(default=None, ge=0)
    ask: float | None = Field(default=None, ge=0)
    implied_volatility: float | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_quote(self) -> OptionQuote:
        if self.bid is not None and self.ask is not None and self.ask < self.bid:
            raise ValueError("option ask must not be below bid")
        return self


class OptionsSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    observed_at: datetime
    retrieved_at: datetime
    freshness: Freshness
    source: str = Field(min_length=1)
    adjustment_mode: Literal["unadjusted", "split_adjusted", "unknown"]
    point_in_time_certified: bool = False
    quotes: tuple[OptionQuote, ...] = ()

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("symbol is required")
        return normalized


class OptionsActivityPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    stale_freshness: tuple[Freshness, ...] = (Freshness.STALE, Freshness.MISSING)
    unusual_volume_to_open_interest: float = Field(default=1.5, gt=0)
    max_relative_bid_ask_spread: float = Field(default=0.25, ge=0)
    call_dominance_ratio: float = Field(default=1.5, gt=1)
    max_signal_weight: float = Field(default=0.25, ge=0, le=0.25)


class OptionsActivityResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str
    status: OptionsContextStatus
    observed_at: datetime
    source: str
    call_volume: int | None = None
    put_volume: int | None = None
    call_open_interest: int | None = None
    put_open_interest: int | None = None
    call_put_volume_ratio: float | None = None
    call_put_open_interest_ratio: float | None = None
    implied_volatility_percentile: float | None = Field(default=None, ge=0, le=100)
    signal: OptionsContextSignal = OptionsContextSignal.UNKNOWN
    signal_weight: float = Field(default=0, ge=0, le=0.25)
    risk_flags: tuple[str, ...] = ()
    unknowns: tuple[str, ...] = ()
    reason: str


class OptionsActivityProvider(Protocol):
    """Provider boundary; implementations must return a normalized snapshot."""

    def snapshot(self, symbol: str, observed_at: datetime) -> OptionsSnapshot | None:
        ...


def evaluate_options_activity(
    snapshot: OptionsSnapshot,
    *,
    historical_implied_volatility: tuple[float, ...] = (),
    policy: OptionsActivityPolicy | None = None,
) -> OptionsActivityResult:
    thresholds = policy or OptionsActivityPolicy()
    risk_flags: set[str] = set()
    unknowns: set[str] = set()

    if snapshot.freshness in thresholds.stale_freshness:
        return _unknown_result(snapshot, "Options data is stale or missing.", {"options_data_stale"})
    if not snapshot.quotes:
        return _unknown_result(snapshot, "No option quotes were provided.", {"options_quotes_missing"})

    calls = tuple(quote for quote in snapshot.quotes if quote.option_type == OptionType.CALL)
    puts = tuple(quote for quote in snapshot.quotes if quote.option_type == OptionType.PUT)
    call_volume = sum(quote.volume for quote in calls)
    put_volume = sum(quote.volume for quote in puts)
    call_open_interest = sum(quote.open_interest for quote in calls)
    put_open_interest = sum(quote.open_interest for quote in puts)
    if not calls or not puts:
        unknowns.add("one_sided_option_chain")

    volume_ratio = _ratio(call_volume, put_volume)
    open_interest_ratio = _ratio(call_open_interest, put_open_interest)
    if volume_ratio is None:
        unknowns.add("put_volume_zero")
    if open_interest_ratio is None:
        unknowns.add("put_open_interest_zero")

    current_iv = [quote.implied_volatility for quote in snapshot.quotes if quote.implied_volatility is not None]
    iv_percentile = _percentile(current_iv, historical_implied_volatility)
    if iv_percentile is None:
        unknowns.add("iv_history_unavailable")

    if any(_is_illiquid(quote, thresholds.max_relative_bid_ask_spread) for quote in snapshot.quotes):
        risk_flags.add("options_liquidity")
    if any(
        quote.volume > 0
        and (
            quote.open_interest == 0
            or quote.volume / quote.open_interest >= thresholds.unusual_volume_to_open_interest
        )
        for quote in snapshot.quotes
    ):
        risk_flags.add("unusual_options_activity")
    if not snapshot.point_in_time_certified:
        unknowns.add("point_in_time_not_certified")

    volume_signal = _dominance(volume_ratio, thresholds.call_dominance_ratio)
    open_interest_signal = _dominance(open_interest_ratio, thresholds.call_dominance_ratio)
    contradictory = (
        volume_signal is not None
        and open_interest_signal is not None
        and volume_signal != open_interest_signal
    )
    if contradictory:
        return OptionsActivityResult(
            symbol=snapshot.symbol,
            status=OptionsContextStatus.CONTRADICTORY,
            observed_at=snapshot.observed_at,
            source=snapshot.source,
            call_volume=call_volume,
            put_volume=put_volume,
            call_open_interest=call_open_interest,
            put_open_interest=put_open_interest,
            call_put_volume_ratio=volume_ratio,
            call_put_open_interest_ratio=open_interest_ratio,
            implied_volatility_percentile=iv_percentile,
            risk_flags=tuple(sorted(risk_flags)),
            unknowns=tuple(sorted((*unknowns, "contradictory_activity"))),
            reason="Volume and open-interest dominance disagree; no directional context is emitted.",
        )

    signal = volume_signal or open_interest_signal or OptionsContextSignal.NEUTRAL
    signal_weight = 0 if unknowns else thresholds.max_signal_weight
    return OptionsActivityResult(
        symbol=snapshot.symbol,
        status=OptionsContextStatus.AVAILABLE,
        observed_at=snapshot.observed_at,
        source=snapshot.source,
        call_volume=call_volume,
        put_volume=put_volume,
        call_open_interest=call_open_interest,
        put_open_interest=put_open_interest,
        call_put_volume_ratio=volume_ratio,
        call_put_open_interest_ratio=open_interest_ratio,
        implied_volatility_percentile=iv_percentile,
        signal=signal if signal_weight else OptionsContextSignal.UNKNOWN,
        signal_weight=signal_weight,
        risk_flags=tuple(sorted(risk_flags)),
        unknowns=tuple(sorted(unknowns)),
        reason="Options activity is informational context only and remains within the configured low-weight cap.",
    )


def _unknown_result(snapshot: OptionsSnapshot, reason: str, unknowns: set[str]) -> OptionsActivityResult:
    return OptionsActivityResult(
        symbol=snapshot.symbol,
        status=OptionsContextStatus.UNKNOWN,
        observed_at=snapshot.observed_at,
        source=snapshot.source,
        unknowns=tuple(sorted(unknowns)),
        reason=reason,
    )


def _ratio(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator / denominator, 4)


def _dominance(ratio: float | None, threshold: float) -> OptionsContextSignal | None:
    if ratio is None:
        return None
    if ratio >= threshold:
        return OptionsContextSignal.CALL_DOMINANCE
    if ratio <= 1 / threshold:
        return OptionsContextSignal.PUT_DOMINANCE
    return None


def _percentile(current: list[float], historical: tuple[float, ...]) -> float | None:
    if not current or not historical:
        return None
    current_value = sum(current) / len(current)
    return round(sum(value <= current_value for value in historical) / len(historical) * 100, 4)


def _is_illiquid(quote: OptionQuote, max_relative_spread: float) -> bool:
    if quote.bid is None or quote.ask is None:
        return False
    midpoint = (quote.bid + quote.ask) / 2
    return midpoint == 0 or (quote.ask - quote.bid) / midpoint > max_relative_spread
