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
  // Real Reddit data. Null from the Worker, which has no Reddit access.
  reddit_mention_spike_24h_pct?: number | null
  reddit_positive_pct?: number | null
  // Price/volume proxies. Not social data.
  volume_spike_vs_90d_avg_pct?: number | null
  price_volume_momentum_pct?: number | null
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

export type TechnicalSource = 'local' | 'external'

export interface PriceRange {
  low: number
  high: number
}

/** A technical opinion normalized for the aggregator, whoever produced it. */
export interface TechnicalVerdict {
  direction: Direction
  confidence: number
  source: TechnicalSource
  producer: string | null
  // The producer's own action and execution intent. Direction has three
  // members and decision.v1 has seven, so `avoid` and `hold` both project to
  // HOLD and can only be told apart here.
  action?: string | null
  execution_intent?: string | null
  price_state?: string | null
  opportunity_range?: PriceRange | null
  reduce_range?: PriceRange | null
  invalidation?: number | null
  reasons: string[]
  data_quality?: number | null
}

/** One horizon's independent verdict, exactly as Vincent's engine produced it. */
export interface HorizonTechnicalVerdict {
  horizon: string
  verdict: TechnicalVerdict
}

/** Ryan's non-technical layers, reported beside an external technical action. */
export interface SupportingContext {
  direction: Direction
  confidence: number
  agrees_with_action: boolean
  weighted_score: number
  fundamental_vote: Partial<Record<Direction, number>>
  sentiment_vote: Partial<Record<Direction, number>>
  macro_vote: Partial<Record<Direction, number>>
  signals: Signal[]
}

export interface Recommendation {
  direction: Direction
  confidence: number
  signal_vote: Partial<Record<Direction, number>>
  // Weighted BUY/HOLD/SELL sum behind signal_vote, one dict per category.
  // Computed on every recommendation, blended or external.
  technical_vote: Partial<Record<Direction, number>>
  fundamental_vote: Partial<Record<Direction, number>>
  sentiment_vote: Partial<Record<Direction, number>>
  macro_vote: Partial<Record<Direction, number>>
  weighted_score: number
  // True when the technical action and Ryan's other layers point different
  // ways — computed whether or not an external verdict is present.
  conflict_detected?: boolean
  conflict_summary?: string | null
  technical_target_high: number | null
  technical_target_low: number | null
  stop_loss_suggestion: number | null
  horizon: string
  review_action: string
  risk_flags: string[]
  // Which engine produced the technical vote. Optional because responses from
  // before the composite engine shipped do not carry these.
  technical_source?: TechnicalSource
  technical_producer?: string | null
  technical_price_state?: string | null
  local_technical_direction?: Direction | null
  technical_agreement?: boolean | null
  supporting_context?: SupportingContext | null
  // His engine's independent short/mid/long verdicts, unaveraged. Empty when no
  // pull is configured or every horizon failed decision.v1 validation.
  technical_by_horizon?: HorizonTechnicalVerdict[]
}

/** One compact indicator feature: unavailable, or its picked fields. */
export interface TechnicalIndicator {
  available: boolean
  value?: number | null
  state?: string | null
  macd_line?: number | null
  signal_line?: number | null
  histogram?: number | null
  crossover_state?: string | null
  k?: number | null
  d?: number | null
  j?: number | null
  adx?: number | null
  plus_di?: number | null
  minus_di?: number | null
  trend_strength?: string | null
  directional_bias?: string | null
  atr_pct?: number | null
  volatility_regime?: string | null
  upper_band?: number | null
  middle_band?: number | null
  lower_band?: number | null
  price_position?: string | null
  squeeze_state?: string | null
  trend?: string | null
  divergence?: string | null
}

/** A compact, read-only subset of Vincent's canonical technical features for one horizon. */
export interface ConsolidatedTechnicalDetails {
  moving_averages: { alignment: string; compression_state: string }
  rsi: TechnicalIndicator
  macd: TechnicalIndicator
  kdj: TechnicalIndicator
  adx: TechnicalIndicator
  atr: TechnicalIndicator
  bollinger: TechnicalIndicator
  obv: TechnicalIndicator
  relative_strength: { state: string; vs_spy: number | null; vs_qqq: number | null } | null
  fibonacci: {
    availability: string
    direction: string | null
    fib_zone: string
    nearest_fib_level: number | null
    distance_to_nearest_fib_pct: number | null
  } | null
}

/** Symbol-level technical context that does not vary by horizon. */
export interface ConsolidatedMarketStructure {
  relative_volume: { state: string; displayed_rvol: number | null }
  fifty_two_week: {
    high: number | null
    low: number | null
    position_pct: number | null
    distance_to_high_pct: number | null
    distance_to_low_pct: number | null
  } | null
}

/** Vincent's engine output for one horizon, as the consolidated pipeline reports it. */
export interface ConsolidatedTechnical {
  available: boolean
  action: string | null
  // Vincent's own 0-100 scale.
  confidence: number | null
  price_state: string
  execution_intent: string | null
  opportunity_range: PriceRange | null
  reduce_range: PriceRange | null
  invalidation: number | null
  current_price: number | null
  reasons: string[]
  data_quality: number | null
  technical_details: ConsolidatedTechnicalDetails | null
}

export type FundamentalStance = 'supportive' | 'neutral' | 'weak' | 'unavailable'

export interface ConsolidatedAdjustment {
  layer: 'technical' | 'fundamentals' | 'index_hurdle'
  from: string | null
  to: string | null
  reason: 'technical_unavailable' | 'fundamentals_weak' | 'index_hurdle_failed' | 'index_hurdle_unavailable'
  detail: string | null
}

export interface ConsolidatedHorizon {
  technical: ConsolidatedTechnical | null
  fundamentals: { stance: FundamentalStance; applied: boolean }
  final_action: string | null
  adjustments: ConsolidatedAdjustment[]
}

export interface HurdleBenchmarkRow {
  symbol: string
  role: 'index' | 'sector' | 'industry' | 'local_index'
  label: string
  rel_12_1_pct: number | null
  rel_6m_pct: number | null
  ratio_above_200d: boolean | null
  evidence_true: number
  evidence_known: number
  sessions: number
  result: 'beats' | 'lags' | 'mixed' | 'insufficient_data'
}

export interface IndexHurdle {
  status: 'pass' | 'fail' | 'not_applicable' | 'unavailable'
  benchmarks: HurdleBenchmarkRow[]
  lagging: string[]
  earnings_guard: {
    status: 'clear' | 'fired' | 'unavailable'
    eps_surprise_pct: number | null
    analysts_deteriorating: boolean | null
  }
}

/** Technical (Vincent) → fundamentals (Ryan) → index hurdle, per horizon. */
export interface ConsolidatedDecision {
  version: string
  producer: string | null
  generated_at: string
  current_price: number | null
  horizons: Record<'short' | 'mid' | 'long', ConsolidatedHorizon>
  index_hurdle: IndexHurdle | null
  fundamentals: { stance: FundamentalStance; vote: Partial<Record<Direction, number>>; signal_count: number } | null
  data_quality: { daily?: string; four_hour?: string; one_hour?: string; market?: number } | null
  market_structure: ConsolidatedMarketStructure | null
  // Short, no-stack reasons the technical engine and/or index hurdle could
  // not run (e.g. a subrequest budget error), null when both succeeded.
  errors: { technical?: string; index_hurdle?: string } | null
  // The next earnings date already fed into Vincent's engine as risk input;
  // near reuses his own near-earnings window. Null when the quote has no date.
  earnings: { date: string; days_to_earnings: number; near: boolean } | null
}

/** One `/decisions` board row: a successful consolidated decision or a per-symbol failure. */
export interface DecisionRowOk {
  symbol: string
  company_name?: string | null
  current_price: number | null
  consolidated_decision: ConsolidatedDecision
  error?: undefined
}

export interface DecisionRowError {
  symbol: string
  error: { code: string; message: string; status?: number }
}

export type DecisionRow = DecisionRowOk | DecisionRowError

export interface DecisionsResponse {
  results: DecisionRow[]
  max_symbols: number
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
  // Present only when the Worker runs the consolidated pipeline (QA today).
  consolidated_decision?: ConsolidatedDecision | null
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
  index_hurdle?: IndexHurdle | null
  held_by_index_hurdle?: boolean
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
  recommendation?: Direction | null
  index_hurdle?: IndexHurdle | null
  held_by_index_hurdle?: boolean
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

export interface SharedSpaceSessionResponse {
  authenticated: boolean
  slug: string
  display_name: string | null
  session_token?: string | null
}

export interface SharedWatchlistResponse {
  slug: string
  display_name: string
  symbols: string[]
}

export interface ResearchPoint {
  statement: string
  evidence_ids: string[]
}

export interface ResearchEvidence {
  id: string
  title?: string
  url: string
  evidence_type?: string
  excerpt?: string
}

export interface ResearchDecisionSupport {
  contract_version: string
  candidate_rank: number
  symbol: string
  analogy_comparison: ResearchPoint | null
  thesis: string
  catalysts: ResearchPoint[]
  risks: ResearchPoint[]
  entry_conditions: ResearchPoint[]
  reasons_to_avoid: ResearchPoint[]
  evidence: ResearchEvidence[]
  unknowns: string[]
  review_verdict: string
  review_risk_summary: string
  entry_assessment: string
}

export interface ResearchCandidate {
  rank: number
  symbol: string
  company_name: string
  thesis: string
  demand_driver: string
  evidence_ids: string[]
  disqualifiers: string[]
  decision_support: ResearchDecisionSupport
  forecast: number | null
  forecast_status: string
}

export interface ResearchJobResult {
  model_status: string
  model_version: string | null
  results: ResearchCandidate[]
}

export type ResearchJobStatus = 'queued' | 'discovering' | 'verifying' | 'reviewing' | 'calculating' | 'completed' | 'failed' | 'cancelled'

export interface ResearchJobState {
  id: string
  status: ResearchJobStatus
  progress: number
  current_stage: string
  candidate_progress: { completed: number; total: number }
  elapsed_seconds: number
  estimated_usage_usd: number
  input: {
    question: string
    mode: 'upside_discovery' | 'downside_risk_scan'
    universe: string
    max_candidates: number
    capital: number | null
    risk_profile: string | null
    estimated_usage_usd: number
  }
  result: ResearchJobResult | null
  error: string | null
}

export interface ResearchJobRequest {
  question: string
  mode: 'upside_discovery' | 'downside_risk_scan'
  universe: string
  max_candidates: number
  capital?: number
  risk_profile?: string
}

// Track record — past calls scored against realized prices. Mirrors the
// TrackRecord* pydantic models in shared/shared/models.py.
export interface TrackRecordCoverage {
  record_count: number
  distinct_symbols: number
  earliest?: string | null
  latest?: string | null
}

export interface TrackRecordEntry {
  symbol: string
  generated_at: string
  direction: string
  confidence: number
  entry_assessment?: string | null
  price_at_call?: number | null
  target_window: string
  forward_returns: Record<string, number>
  benchmark_relative_returns: Record<string, number>
  max_drawdown?: number | null
  hit?: boolean | null
  skipped_reason?: string | null
}

export interface TrackRecordTimeline {
  symbol: string
  generated_at: string
  entries: TrackRecordEntry[]
}

export interface PerformanceBucket {
  label: string
  evaluated_count: number
  decision_count: number
  hit_rate?: number | null
  average_forward_return?: number | null
}

export interface TrackRecordPerformance {
  generated_at: string
  evaluated_count: number
  decision_count: number
  hit_rate?: number | null
  average_forward_return?: number | null
  average_benchmark_relative_return?: number | null
  by_direction: PerformanceBucket[]
  by_confidence: PerformanceBucket[]
  by_entry_assessment: PerformanceBucket[]
  advisory: string[]
}
