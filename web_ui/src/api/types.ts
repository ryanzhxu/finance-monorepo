export type Direction = 'BUY' | 'HOLD' | 'SELL'

export type FreshnessValue = string

export type FreshnessMap = Record<string, FreshnessValue>

export type Technicals = Record<string, unknown>

export interface Fundamentals {
  eps_surprise_pct?: number | null
  pe_ratio?: number | null
  pb_ratio?: number | null
  ps_ratio?: number | null
  ev_ebitda?: number | null
  pe_percentile_5y?: number | null
  revenue_growth_yoy_pct?: number | null
  fcf_trend?: string | null
  gross_margin_pct?: number | null
  analyst_upgrades_30d?: number | null
  analyst_downgrades_30d?: number | null
  freshness?: string | null
  as_of?: string | null
}

export interface Sentiment {
  put_call_ratio?: number | null
  iv_rank?: number | null
  iv_rank_approx?: number | null
  iv_rank_is_approx?: boolean
  short_interest_pct?: number | null
  institutional_net_shares_last_13f?: number | null
  institutional_13f_as_of?: string | null
  institutional_13f_freshness?: string | null
  reddit_mention_spike_24h_pct?: number | null
  reddit_positive_pct?: number | null
  freshness?: string | null
}

export interface Macro {
  days_to_next_fomc?: number | null
  next_fomc_date?: string | null
  rate_cut_probability_pct?: number | null
  rate_cut_probability_source?: string | null
  treasury_10y?: number | null
  vix?: number | null
  freshness?: string | null
}

export interface Signal {
  dimension: string
  signal: Direction
  weight: number
  note: string
}

export interface EntryBlock {
  current_price: number | null
  ideal_buy_zone: [number, number]
  aggressive_entry_price: number | null
  conservative_entry_price: number | null
  breakout_buy_level: number | null
  support_levels: number[]
  resistance_levels: number[]
  stop_loss_suggestion: number
  invalidation_level: number
  risk_reward_ratio: number | null
  is_overextended: boolean
  breakout_volume_confirmed: boolean
  entry_assessment: string
  reason: string
  data_freshness?: FreshnessMap
  data_quality_score?: number
}

export interface Recommendation {
  direction: Direction
  confidence: number
  signal_vote: Partial<Record<Direction, number>>
  weighted_score: number
  technical_target_high: number | null
  technical_target_low: number | null
  stop_loss_suggestion: number | null
  horizon: string
  review_action: string
  risk_flags: string[]
}

export interface AnalysisResponse {
  symbol: string
  company_name?: string | null
  generated_at: string
  data_freshness: FreshnessMap
  data_quality_score: number
  confidence: number
  technicals: Technicals
  fundamentals: Fundamentals
  sentiment: Sentiment
  macro: Macro
  signals: Signal[]
  entry: EntryBlock | null
  recommendation: Recommendation
  narrative: string | null
}

export interface FibonacciLevels {
  swing_high: number
  swing_low: number
  level_0: number
  level_236: number
  level_382: number
  level_500: number
  level_618: number
  level_650: number
  level_786: number
  level_1000: number
  golden_pocket_low: number
  golden_pocket_high: number
  as_of: string
  lookback_days: number
}

export interface ConfluenceZone {
  classical_zone: [number, number]
  fibonacci_golden_pocket: [number, number]
  overlap: boolean
  merged_zone_low: number | null
  merged_zone_high: number | null
  high_conviction: boolean
  divergence_note: string | null
  methods_agreeing: string[]
}

export interface EntryConfluenceResponse {
  symbol: string
  generated_at: string
  current_price: number | null
  classical: EntryBlock
  fibonacci: FibonacciLevels | null
  confluence: ConfluenceZone | null
  data_freshness: FreshnessMap
  data_quality_score: number
}

export interface AnalystHealthResponse {
  status: string
  service: string
  config_valid: boolean
  providers: Record<string, string>
  llm_available: boolean
  cache_backend: string
}

export interface ScreenerHealthResponse {
  status: string
  service: string
  config_valid: boolean
  providers: Record<string, string>
  cache_backend: string
  llm_available?: boolean
}

export interface ScreenResultItem {
  rank: number
  symbol: string
  screen_type: string
  opportunity_score: number
  valuation_score: number
  growth_score: number
  quality_score: number
  momentum_score: number
  analyst_revision_score: number
  institutional_accumulation_score: number
  insider_activity_score: number
  risk_score: number
  score_breakdown: Record<string, unknown>
  data_freshness: FreshnessMap
  data_quality_score: number
  confidence: number
  reason: string
  recommended_action: string
  risk_flags: string[]
  recommendation?: Direction | null
  entry_assessment?: string | null
  ideal_buy_zone?: [number, number] | null
  summary?: string | null
  revenue_accel_pct?: number | null
  analyst_upgrades_30d?: number | null
  margin_expansion_bps?: number | null
  components?: Record<string, unknown>
}

export interface ScreenResponse {
  screen_type: string
  generated_at: string
  universe: string
  market_regime: string
  data_quality_score: number
  confidence: number
  data_freshness: FreshnessMap
  results: ScreenResultItem[]
  notes: string[]
}

export interface BuyabilityResult {
  symbol: string
  trend_score: number
  sentiment_score: number
  technical_state: string
  fundamental_state: string
  entry_assessment?: string | null
  ideal_buy_zone?: [number, number] | null
  current_price?: number | null
  data_quality_score: number
  confidence: number
  reason: string
  risk_flags: string[]
}

export interface TrendingResultItem {
  symbol: string
  screen_type: string
  mention_count_24h: number
  mention_count_3d: number
  mention_count_5d: number
  mention_growth_3d_pct?: number | null
  mention_growth_5d_pct?: number | null
  baseline_daily_mentions_30d?: number | null
  acceleration?: number | null
  sentiment_score: number
  sentiment_change?: number | null
  pos_neu_neg_ratio: number[]
  retail_fomo_risk: number
  news_catalyst: string
  trend_quality: string
  institutional_account_participation?: number | null
  data_freshness: FreshnessMap
  data_quality_score: number
  confidence: number
  risk_flags: string[]
  reason: string
  score_breakdown: Record<string, unknown>
  buyability?: BuyabilityResult | null
}

export interface TrendingScreenResponse {
  screen_type: string
  generated_at: string
  universe: string
  market_regime: string
  data_quality_score: number
  confidence: number
  data_freshness: FreshnessMap
  results: TrendingResultItem[]
  notes: string[]
}
