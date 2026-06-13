from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.enums import AssetType, Direction, EntryAssessment, Freshness, Horizon, MarketRegime, ScreenType, Universe

RiskFlag = str
FreshnessMap = dict[str, Freshness | str]


class PortfolioContext(BaseModel):
    held: bool = False
    quantity: float | None = None
    avg_cost: float | None = None
    position_pct: float | None = None


class AnalyzeRequest(BaseModel):
    symbol: str
    asset_type: AssetType = AssetType.STOCK
    horizon: Horizon = Horizon.TWO_TO_FOUR_WEEKS
    current_price: float | None = Field(default=None, gt=0)
    portfolio_context: PortfolioContext | None = None
    include_narrative: bool = True
    include_entry: bool = True

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol is required")
        return value


class BatchAnalyzeRequest(BaseModel):
    symbols: list[str] = Field(min_length=1, max_length=20)
    asset_type: AssetType = AssetType.STOCK
    horizon: Horizon = Horizon.TWO_TO_FOUR_WEEKS
    include_narrative: bool = False
    include_entry: bool = True

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values if value.strip()]
        if not normalized:
            raise ValueError("at least one symbol is required")
        return normalized


class EntryRequest(BaseModel):
    symbol: str
    asset_type: AssetType = AssetType.STOCK
    horizon: Horizon = Horizon.TWO_TO_FOUR_WEEKS
    current_price: float | None = Field(default=None, gt=0)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, value: str) -> str:
        value = value.strip().upper()
        if not value:
            raise ValueError("symbol is required")
        return value


class MacdBlock(BaseModel):
    macd_line: float | None = None
    signal_line: float | None = None
    histogram: float | None = None


class Technicals(BaseModel):
    rsi_14: float | None = None
    rsi_weekly: float | None = None
    macd: MacdBlock
    ma_20: float | None = None
    ma_50: float | None = None
    ma_200: float | None = None
    support_levels: list[float] = Field(default_factory=list)
    resistance_levels: list[float] = Field(default_factory=list)
    atr_14: float | None = None
    bb_upper: float | None = None
    bb_lower: float | None = None
    bb_mid: float | None = None
    volume_ratio_90d: float | None = None
    dist_from_ma20_pct: float | None = None
    dist_from_ma50_pct: float | None = None
    dist_from_ma200_pct: float | None = None
    recent_gap_pct: float | None = None
    recent_earnings_gap_pct: float | None = None
    breakout_state: str = "none"


class Fundamentals(BaseModel):
    eps_surprise_pct: float | None = None
    pe_percentile_5y: float | None = None
    analyst_upgrades_30d: int | None = None
    analyst_downgrades_30d: int | None = None
    revenue_growth_yoy_pct: float | None = None
    fcf_trend: str | None = None
    gross_margin_pct: float | None = None


class Sentiment(BaseModel):
    put_call_ratio: float | None = None
    iv_rank: float | None = None
    reddit_mention_spike_24h_pct: float | None = None
    reddit_positive_pct: float | None = None
    short_interest_pct: float | None = None
    institutional_net_shares_last_13f: float | None = None


class Macro(BaseModel):
    days_to_next_fomc: int | None = None
    rate_cut_probability_pct: float | None = None
    treasury_10y: float | None = None
    vix: float | None = None
    market_regime: MarketRegime = MarketRegime.NEUTRAL


class Signal(BaseModel):
    dimension: str
    signal: Direction
    weight: float
    note: str


class EntryBlock(BaseModel):
    current_price: float
    ideal_buy_zone: tuple[float, float]
    aggressive_entry_price: float | None = None
    conservative_entry_price: float | None = None
    breakout_buy_level: float | None = None
    support_levels: list[float]
    resistance_levels: list[float]
    stop_loss_suggestion: float
    invalidation_level: float
    risk_reward_ratio: float | None = None
    is_overextended: bool
    breakout_volume_confirmed: bool
    entry_assessment: EntryAssessment
    reason: str


class Recommendation(BaseModel):
    direction: Direction
    confidence: float = Field(ge=0.0, le=1.0)
    signal_vote: dict[Direction, int]
    weighted_score: float
    technical_target_high: float | None = None
    technical_target_low: float | None = None
    stop_loss_suggestion: float | None = None
    horizon: Horizon
    review_action: str
    risk_flags: list[RiskFlag] = Field(default_factory=list)


class AnalyzeResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    symbol: str
    generated_at: datetime
    data_freshness: FreshnessMap
    data_quality_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    technicals: Technicals
    fundamentals: Fundamentals
    sentiment: Sentiment
    macro: Macro
    signals: list[Signal]
    entry: EntryBlock | None = None
    recommendation: Recommendation
    narrative: str | None = None


class HealthResponse(BaseModel):
    status: str
    service: str
    config_valid: bool
    providers: dict[str, str]
    llm_available: bool
    cache_backend: str


class ScreenRequest(BaseModel):
    universe: Universe = Universe.SP500
    limit: int = Field(default=25, ge=1, le=100)
    horizon: Horizon = Horizon.TWO_TO_FOUR_WEEKS
    include_analysis: bool = True
    include_narrative: bool = False
    tickers: list[str] | None = None
    filters_override: dict[str, Any] | None = None

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, values: list[str] | None) -> list[str] | None:
        if values is None:
            return None
        normalized = sorted({value.strip().upper() for value in values if value.strip()})
        return normalized or None


class ScreenResultItem(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    rank: int
    symbol: str
    screen_type: ScreenType
    opportunity_score: float = Field(ge=0.0, le=100.0)
    valuation_score: float = Field(ge=0.0, le=100.0)
    growth_score: float = Field(ge=0.0, le=100.0)
    quality_score: float = Field(ge=0.0, le=100.0)
    momentum_score: float = Field(ge=0.0, le=100.0)
    analyst_revision_score: float = Field(ge=0.0, le=100.0)
    institutional_accumulation_score: float = Field(ge=0.0, le=100.0)
    insider_activity_score: float = Field(ge=0.0, le=100.0)
    risk_score: float = Field(ge=0.0, le=100.0)
    score_breakdown: dict[str, Any]
    data_freshness: FreshnessMap
    data_quality_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    recommended_action: str
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    recommendation: Direction | None = None
    entry_assessment: EntryAssessment | None = None
    ideal_buy_zone: tuple[float, float] | None = None
    summary: str | None = None


class ScreenResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    screen_type: ScreenType
    generated_at: datetime
    universe: Universe
    market_regime: MarketRegime
    data_quality_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    data_freshness: FreshnessMap
    results: list[ScreenResultItem]
    notes: list[str] = Field(default_factory=list)


class RegimeResponse(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    market_regime: MarketRegime
    generated_at: datetime
    data_freshness: FreshnessMap
    data_quality_score: int = Field(ge=0, le=100)
    confidence: float = Field(ge=0.0, le=1.0)
    sector_leaders: list[str] = Field(default_factory=list)
    sector_laggards: list[str] = Field(default_factory=list)
    reason: str


class RecommendationLogRecord(BaseModel):
    symbol: str
    timestamp: datetime
    direction: Direction
    confidence: float
    entry: EntryBlock | None
    scores: dict[str, Any]
    risk_flags: list[RiskFlag]
    regime: MarketRegime
    data_quality_score: int


class ScreenLogRecord(BaseModel):
    screen_type: ScreenType
    timestamp: datetime
    symbol: str
    rank: int
    opportunity_score: float
    recommendation: Direction | None
    confidence: float
    entry_assessment: EntryAssessment | None
    ideal_buy_zone: tuple[float, float] | None
    scores: dict[str, Any]
    risk_flags: list[RiskFlag]
    regime: MarketRegime
    data_quality_score: int
