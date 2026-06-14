from enum import Enum


class Direction(str, Enum):
    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class EntryAssessment(str, Enum):
    BUY_NOW = "buy_now"
    WAIT_FOR_PULLBACK = "wait_for_pullback"
    WAIT_FOR_BREAKOUT = "wait_for_breakout_confirmation"
    AVOID = "avoid"
    SHORT_TERM_TRADE_ONLY = "short_term_trade_only"
    LONG_TERM_CANDIDATE = "long_term_investment_candidate"


class TrendQuality(str, Enum):
    HIGH_QUALITY = "high_quality_trend"
    NEWS_DRIVEN = "news_driven_trend"
    EARNINGS_DRIVEN = "earnings_driven_trend"
    MEME_FOMO = "meme_fomo_trend"
    PUMP_RISK = "likely_pump_risk"
    OVEREXTENDED = "too_late_overextended"
    EARLY_ACCUMULATION = "early_accumulation"


class Freshness(str, Enum):
    LIVE = "live"
    DELAYED = "delayed"
    LAST_CLOSE = "last_close"
    QUARTERLY = "quarterly"
    STALE = "stale"
    MISSING = "missing"
    ESTIMATED = "estimated"


class ScreenType(str, Enum):
    UNDERVALUED = "undervalued"
    TRENDING = "trending"
    OPPORTUNITIES = "opportunities"
    WATCHLIST = "watchlist"
    CUSTOM = "custom"


class Universe(str, Enum):
    SP500 = "SP500"
    NASDAQ100 = "NASDAQ100"
    DOW = "DOW"
    RUSSELL1000 = "RUSSELL1000"
    RUSSELL2000 = "RUSSELL2000"
    WATCHLIST = "WATCHLIST"
    CUSTOM = "CUSTOM"


class MarketRegime(str, Enum):
    RISK_ON = "risk_on"
    NEUTRAL = "neutral"
    RISK_OFF = "risk_off"


class TrendSource(str, Enum):
    REDDIT = "reddit"
    STOCKTWITS = "stocktwits"
    NEWS = "news"
    YAHOO_TRENDING = "yahoo_trending"


class TechnicalState(str, Enum):
    OVERSOLD = "oversold"
    NEUTRAL = "neutral"
    EXTENDED = "extended"
    OVEREXTENDED = "overextended"
    BREAKOUT = "breakout"


class FundamentalState(str, Enum):
    STRONG = "strong"
    MIXED = "mixed"
    WEAK = "weak"


class AssetType(str, Enum):
    STOCK = "STOCK"


class Horizon(str, Enum):
    ONE_DAY = "1D"
    ONE_WEEK = "1W"
    TWO_TO_FOUR_WEEKS = "2-4W"
    THREE_TO_SIX_MONTHS = "3-6M"
