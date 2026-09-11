import type {
  ConsolidatedAdjustment,
  ConsolidatedDecision,
  ConsolidatedHorizon,
  ConsolidatedMarketStructure,
  ConsolidatedTechnical,
  ConsolidatedTechnicalDetails,
  IndexHurdle,
  PriceRange,
} from '../api/types'
import { useI18n, type MessageKey } from '../i18n'

type FinalDecisionPanelProps = {
  decision: ConsolidatedDecision
}

const HORIZONS = [
  { key: 'short', title: 'horizonShort', window: 'horizonShortWindow' },
  { key: 'mid', title: 'horizonMid', window: 'horizonMidWindow' },
  { key: 'long', title: 'horizonLong', window: 'horizonLongWindow' },
] as const

const ACTION_TONE: Record<string, string> = {
  strong_buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  buy: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  accumulate: 'bg-emerald-50 text-emerald-800 dark:bg-emerald-500/10 dark:text-emerald-300',
  hold: 'bg-amber-100 text-amber-900 dark:bg-amber-500/20 dark:text-amber-200',
  trim: 'bg-orange-100 text-orange-900 dark:bg-orange-500/20 dark:text-orange-200',
  sell: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  avoid: 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300',
}
const NEUTRAL_TONE = 'bg-slate-200 text-slate-700 dark:bg-slate-700/50 dark:text-slate-300'

const STANCE_KEYS: Record<string, MessageKey> = {
  supportive: 'stanceSupportive',
  neutral: 'stanceNeutral',
  weak: 'stanceWeak',
  unavailable: 'stanceUnavailable',
}
const ROLE_KEYS: Record<string, MessageKey> = {
  index: 'hurdleRoleIndex',
  sector: 'hurdleRoleSector',
  industry: 'hurdleRoleIndustry',
  local_index: 'hurdleRoleLocalIndex',
}
const RESULT_KEYS: Record<string, MessageKey> = {
  beats: 'hurdleBeats',
  lags: 'hurdleLags',
  mixed: 'hurdleMixed',
  insufficient_data: 'hurdleInsufficient',
}
const RESULT_TONE: Record<string, string> = {
  beats: 'text-emerald-700 dark:text-emerald-400',
  lags: 'text-rose-700 dark:text-rose-400',
  mixed: 'text-amber-700 dark:text-amber-400',
  insufficient_data: 'text-slate-500 dark:text-slate-400',
}
const STATUS_KEYS: Record<string, MessageKey> = {
  pass: 'hurdlePass',
  fail: 'hurdleFail',
  not_applicable: 'hurdleNotApplicable',
  unavailable: 'hurdleUnavailable',
}
const STATUS_TONE: Record<string, string> = {
  pass: 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200',
  fail: 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200',
  not_applicable: NEUTRAL_TONE,
  unavailable: NEUTRAL_TONE,
}
const GUARD_KEYS: Record<string, MessageKey> = {
  clear: 'guardClear',
  fired: 'guardFired',
  unavailable: 'guardUnavailable',
}
const ACTION_KEYS: Record<string, MessageKey> = {
  strong_buy: 'actionStrongBuy',
  buy: 'actionBuy',
  accumulate: 'actionAccumulate',
  hold: 'actionHold',
  trim: 'actionTrim',
  sell: 'actionSell',
  avoid: 'actionAvoid',
}
const PRICE_STATE_KEYS: Record<string, MessageKey> = {
  IN_OPPORTUNITY_ZONE: 'priceStateInOpportunity',
  NEAR_OPPORTUNITY_ZONE: 'priceStateNearOpportunity',
  NEUTRAL_ZONE: 'priceStateNeutral',
  NEAR_REDUCE_ZONE: 'priceStateNearReduce',
  IN_REDUCE_ZONE: 'priceStateInReduce',
  BEYOND_REDUCE_ZONE: 'priceStateBeyondReduce',
  BREAKDOWN_ZONE: 'priceStateBreakdown',
  INVALID_LANDSCAPE: 'priceStateInvalidLandscape',
}
const DATA_QUALITY_KEYS: Record<string, MessageKey> = {
  available: 'available',
  unavailable: 'unavailable',
  source_unavailable: 'dataQualitySourceUnavailable',
  invalid_source_data: 'dataQualityInvalidSource',
}
// Shared vocabulary across the technical-details indicators (RSI state, MACD
// crossover, ADX bias, ATR/RVOL regime, OBV trend/divergence, relative
// strength, ...) — one flat map since the same words (bullish, neutral,
// rising, ...) recur across indicators with the same meaning. fibonacci's
// `fib_zone` is excluded on purpose: the engine composes it as free text
// ("Between 61.8% and 78.6%"), not a fixed enum, so it keeps the generic
// `readable()` fallback below.
const TECHNICAL_WORD_KEYS: Record<string, MessageKey> = {
  unavailable: 'unavailable',
  dependency_unavailable: 'unavailable',
  strong_bullish: 'technicalStrongBullish',
  bullish: 'technicalBullish',
  strong_bearish: 'technicalStrongBearish',
  bearish: 'technicalBearish',
  mixed: 'technicalMixed',
  tight: 'technicalTight',
  compressing: 'technicalCompressing',
  expanding: 'technicalExpanding',
  normal: 'technicalNormal',
  extreme_oversold: 'technicalExtremeOversold',
  oversold: 'technicalOversold',
  weak: 'technicalWeak',
  neutral: 'technicalNeutral',
  strong: 'technicalStrong',
  overbought: 'technicalOverbought',
  extreme_overbought: 'technicalExtremeOverbought',
  none: 'technicalNone',
  bullish_cross: 'technicalBullishCross',
  bearish_cross: 'technicalBearishCross',
  low: 'technicalLow',
  elevated: 'technicalElevated',
  extreme: 'technicalExtreme',
  very_low: 'technicalVeryLow',
  high: 'technicalHigh',
  squeeze: 'technicalSqueeze',
  expanded: 'technicalExpanded',
  rising: 'technicalRising',
  falling: 'technicalFalling',
  flat: 'technicalFlat',
  bearish_divergence: 'technicalBearishDivergence',
  bullish_divergence: 'technicalBullishDivergence',
  outperforming: 'technicalOutperforming',
  underperforming: 'technicalUnderperforming',
}

const money = (value: number | null | undefined): string =>
  value == null || Number.isNaN(value) ? '—' : `$${value.toFixed(2)}`

const num = (value: number | null | undefined, digits = 2): string =>
  value == null || Number.isNaN(value) ? '—' : value.toFixed(digits)

const band = (range: PriceRange | null): string => (range ? `${money(range.low)}–${money(range.high)}` : '—')

const readable = (value: string | null | undefined): string =>
  value ? value.toLowerCase().replace(/_/g, ' ') : '—'

const actionLabel = (
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  value: string | null | undefined,
): string => {
  if (!value) return '—'
  const key = ACTION_KEYS[value]
  return key ? t(key) : readable(value)
}

const priceStateLabel = (
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  value: string | null | undefined,
): string => {
  if (!value) return '—'
  const key = PRICE_STATE_KEYS[value]
  return key ? t(key) : readable(value)
}

const dataQualityLabel = (
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  value: string | undefined,
): string => {
  if (!value) return '—'
  const key = DATA_QUALITY_KEYS[value]
  return key ? t(key) : readable(value)
}

const technicalWord = (
  t: (key: MessageKey, values?: Record<string, string | number>) => string,
  value: string | null | undefined,
): string => {
  if (!value) return '—'
  const key = TECHNICAL_WORD_KEYS[value]
  return key ? t(key) : readable(value)
}

const signedPct = (value: number | null): string =>
  value == null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(1)}%`

function useReason() {
  const { t } = useI18n()
  return (adjustment: ConsolidatedAdjustment, hurdle: IndexHurdle | null): string => {
    switch (adjustment.reason) {
      case 'fundamentals_weak':
        return t('reasonFundamentalsWeak')
      case 'index_hurdle_failed':
        return hurdle?.lagging?.length
          ? t('reasonIndexHurdleFailed', { benchmarks: hurdle.lagging.join(', ') })
          : t('reasonEarningsGuard')
      case 'index_hurdle_unavailable':
        return t('reasonIndexHurdleUnavailable')
      case 'technical_unavailable':
        return t('reasonTechnicalUnavailable')
      default:
        return adjustment.reason
    }
  }
}

// Percent-position geometry for the price landscape bar. Mirrors the min/max
// and padding math in technical_engine/decision-presentation.js's
// `priceMapModel` (read, not imported — that file also carries English/Chinese
// reason text this panel does not use), so the bar lines up with the numbers
// already shown below it.
type PriceLandscapeGeometry = {
  opportunity: { start: number; end: number } | null
  reduce: { start: number; end: number } | null
  invalidationPos: number | null
  currentPos: number | null
}

function priceLandscapeGeometry(technical: ConsolidatedTechnical): PriceLandscapeGeometry | null {
  const current = technical.current_price
  const values: number[] = []
  if (technical.opportunity_range) values.push(technical.opportunity_range.low, technical.opportunity_range.high)
  if (technical.reduce_range) values.push(technical.reduce_range.low, technical.reduce_range.high)
  if (technical.invalidation != null) values.push(technical.invalidation)
  if (current != null) values.push(current)
  if (!values.length) return null

  let min = Math.min(...values)
  let max = Math.max(...values)
  const padding = Math.max(Math.abs(current || max || 1) * 0.025, (max - min) * 0.12, 0.01)
  min -= padding
  max += padding
  const position = (value: number) => Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100))
  const rangePos = (range: PriceRange | null) =>
    range ? { start: position(Math.min(range.low, range.high)), end: position(Math.max(range.low, range.high)) } : null

  return {
    opportunity: rangePos(technical.opportunity_range),
    reduce: rangePos(technical.reduce_range),
    invalidationPos: technical.invalidation != null ? position(technical.invalidation) : null,
    currentPos: current != null ? position(current) : null,
  }
}

function PriceLandscapeBar({ technical }: { technical: ConsolidatedTechnical }) {
  const { t } = useI18n()
  const geometry = priceLandscapeGeometry(technical)
  if (!geometry) return null
  const { opportunity, reduce, invalidationPos, currentPos } = geometry

  return (
    <div className="relative mt-2 h-4 w-full" aria-hidden="true">
      <div className="absolute inset-x-0 top-1/2 h-px -translate-y-1/2 bg-slate-300 dark:bg-slate-700" />
      {opportunity ? (
        <div
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-emerald-400/80 dark:bg-emerald-500/60"
          style={{ left: `${opportunity.start}%`, width: `${Math.max(1.5, opportunity.end - opportunity.start)}%` }}
          title={`${t('opportunity')} ${band(technical.opportunity_range)}`}
        />
      ) : null}
      {reduce ? (
        <div
          className="absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-orange-400/80 dark:bg-orange-500/60"
          style={{ left: `${reduce.start}%`, width: `${Math.max(1.5, reduce.end - reduce.start)}%` }}
          title={`${t('reduce')} ${band(technical.reduce_range)}`}
        />
      ) : null}
      {invalidationPos != null ? (
        <div
          className="absolute top-0 bottom-0 w-px bg-amber-500 dark:bg-amber-400"
          style={{ left: `${invalidationPos}%` }}
          title={`${t('invalidation')} ${money(technical.invalidation)}`}
        />
      ) : null}
      {currentPos != null ? (
        <div
          className="absolute -top-0.5 -translate-x-1/2 text-[9px] leading-none text-slate-700 dark:text-slate-200"
          style={{ left: `${currentPos}%` }}
          title={`${t('currentPrice')} ${money(technical.current_price)}`}
        >
          ▲
        </div>
      ) : null}
    </div>
  )
}

// A compact, read-only rendering of Vincent's canonical technical features for
// one horizon (technical-engine.js's `technicalDetails`). Indicator names
// (RSI, MACD, KDJ, ADX, ATR, OBV) are standard technical-analysis
// abbreviations, kept as-is across locales like a ticker symbol. Enum values
// the engine emits (state, crossover_state, squeeze_state, ...) are localized
// via `technicalWord()` (TECHNICAL_WORD_KEYS above), falling back to
// `readable()` for a value with no dedicated label yet.
function TechnicalDetailsSection({ details }: { details: ConsolidatedTechnicalDetails }) {
  const { t } = useI18n()
  const rows: Array<{ label: string; value: string }> = [
    {
      label: t('movingAverages'),
      value: `${technicalWord(t, details.moving_averages.alignment)} · ${technicalWord(t, details.moving_averages.compression_state)}`,
    },
  ]
  if (details.rsi.available) rows.push({ label: 'RSI', value: `${num(details.rsi.value, 1)} · ${technicalWord(t, details.rsi.state)}` })
  if (details.macd.available)
    rows.push({
      label: 'MACD',
      value: `${num(details.macd.macd_line)} / ${num(details.macd.signal_line)} / ${num(details.macd.histogram)} · ${technicalWord(t, details.macd.crossover_state)}`,
    })
  if (details.kdj.available)
    rows.push({ label: 'KDJ', value: `K ${num(details.kdj.k, 0)} · D ${num(details.kdj.d, 0)} · J ${num(details.kdj.j, 0)}` })
  if (details.adx.available)
    rows.push({
      label: 'ADX',
      value: `${num(details.adx.adx, 0)} · +DI ${num(details.adx.plus_di, 0)} · -DI ${num(details.adx.minus_di, 0)} · ${technicalWord(t, details.adx.directional_bias)}`,
    })
  if (details.atr.available)
    rows.push({ label: 'ATR', value: `${num(details.atr.value)} · ${num(details.atr.atr_pct, 1)}% · ${technicalWord(t, details.atr.volatility_regime)}` })
  if (details.bollinger.available)
    rows.push({
      label: 'Bollinger',
      value: `${money(details.bollinger.lower_band)}–${money(details.bollinger.upper_band)} · ${technicalWord(t, details.bollinger.squeeze_state)}`,
    })
  if (details.obv.available) rows.push({ label: 'OBV', value: `${technicalWord(t, details.obv.trend)} · ${technicalWord(t, details.obv.divergence)}` })
  if (details.relative_strength)
    rows.push({
      label: t('relativeStrength'),
      value: `${technicalWord(t, details.relative_strength.state)} · SPY ${signedPct(details.relative_strength.vs_spy)} · QQQ ${signedPct(details.relative_strength.vs_qqq)}`,
    })
  if (details.fibonacci)
    rows.push({
      label: t('fibonacci'),
      value: `${readable(details.fibonacci.fib_zone)} · ${signedPct(details.fibonacci.distance_to_nearest_fib_pct)}`,
    })

  return (
    <details className="mt-2 text-[11px] text-slate-600 dark:text-slate-400">
      <summary className="cursor-pointer select-none font-medium text-slate-700 dark:text-slate-300">
        {t('technicalDetails')}
      </summary>
      <dl className="mt-1.5 space-y-1">
        {rows.map((row) => (
          <div key={row.label} className="flex justify-between gap-2">
            <dt className="text-slate-500 dark:text-slate-400">{row.label}</dt>
            <dd className="text-right tabular-nums text-slate-700 dark:text-slate-300">{row.value}</dd>
          </div>
        ))}
      </dl>
    </details>
  )
}

// Symbol-level context (not per-horizon): relative volume and 52-week
// structure, from technical-engine.js's `marketStructureDetails`.
function MarketStructureSection({ structure }: { structure: ConsolidatedMarketStructure }) {
  const { t } = useI18n()
  const week = structure.fifty_two_week

  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
        {t('marketStructure')}
      </p>
      <dl className="mt-1.5 space-y-1 text-[11px]">
        <div className="flex justify-between gap-2">
          <dt className="text-slate-500 dark:text-slate-400">{t('relativeVolume')}</dt>
          <dd className="tabular-nums text-slate-700 dark:text-slate-300">
            {technicalWord(t, structure.relative_volume.state)}
            {structure.relative_volume.displayed_rvol != null ? ` · ${num(structure.relative_volume.displayed_rvol, 2)}x` : ''}
          </dd>
        </div>
        {week ? (
          <div className="flex justify-between gap-2">
            <dt className="text-slate-500 dark:text-slate-400">{t('fiftyTwoWeekRange')}</dt>
            <dd className="tabular-nums text-slate-700 dark:text-slate-300">
              {money(week.low)}–{money(week.high)}
              {week.distance_to_high_pct != null ? ` · ${signedPct(week.distance_to_high_pct)} ${t('distanceToHigh')}` : ''}
              {week.distance_to_low_pct != null ? ` · ${signedPct(week.distance_to_low_pct)} ${t('distanceToLow')}` : ''}
            </dd>
          </div>
        ) : null}
      </dl>
    </div>
  )
}

function HorizonColumn({
  entry,
  titleKey,
  windowKey,
  hurdle,
}: {
  entry: ConsolidatedHorizon
  titleKey: MessageKey
  windowKey: MessageKey
  hurdle: IndexHurdle | null
}) {
  const { t } = useI18n()
  const reason = useReason()
  const technical = entry.technical
  const finalAction = entry.final_action
  const changed = technical?.action != null && finalAction !== technical.action

  return (
    <div className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-[11px] font-semibold text-slate-700 dark:text-slate-200">{t(titleKey)}</span>
        <span className="text-[10px] text-slate-500 dark:text-slate-400">{t(windowKey)}</span>
      </div>

      <div className="mt-1.5">
        <span
          className={`rounded px-2 py-0.5 text-[13px] font-semibold ${finalAction ? (ACTION_TONE[finalAction] ?? NEUTRAL_TONE) : NEUTRAL_TONE}`}
        >
          {finalAction ? actionLabel(t, finalAction) : t('unavailable')}
        </span>
      </div>

      {changed ? (
        <p className="mt-1.5 text-[11px] text-slate-600 dark:text-slate-400">
          {t('technicalAction')} <span className="line-through">{actionLabel(t, technical!.action)}</span> → {t('finalAction')}{' '}
          {actionLabel(t, finalAction)}
        </p>
      ) : null}
      {entry.adjustments.map((adjustment) => (
        <p key={`${adjustment.layer}-${adjustment.reason}`} className="text-[11px] text-amber-700 dark:text-amber-400">
          {reason(adjustment, hurdle)}
        </p>
      ))}

      {technical?.available ? (
        <>
          <p className="mt-1.5 text-[11px] text-slate-600 dark:text-slate-400">
            {technical.confidence != null ? t('percentConfidence', { percent: Math.round(technical.confidence) }) : ''}
            {technical.data_quality != null ? ` · ${t('data')} ${technical.data_quality}` : ''}
          </p>
          <p className="text-[11px] text-slate-500 dark:text-slate-400">{priceStateLabel(t, technical.price_state)}</p>
          {technical.price_state === 'INVALID_LANDSCAPE' ? (
            <p className="mt-2 text-[11px] italic text-slate-500 dark:text-slate-400">{t('noPriceLandscape')}</p>
          ) : (
            <>
              <PriceLandscapeBar technical={technical} />
              <dl className="mt-2 space-y-1 text-[11px]">
                <div className="flex justify-between gap-2">
                  <dt className="text-emerald-700 dark:text-emerald-400">{t('opportunity')}</dt>
                  <dd className="tabular-nums text-slate-700 dark:text-slate-300">{band(technical.opportunity_range)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-orange-700 dark:text-orange-400">{t('reduce')}</dt>
                  <dd className="tabular-nums text-slate-700 dark:text-slate-300">{band(technical.reduce_range)}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-slate-500 dark:text-slate-400">{t('invalidation')}</dt>
                  <dd className="tabular-nums text-slate-700 dark:text-slate-300">{money(technical.invalidation)}</dd>
                </div>
              </dl>
            </>
          )}
          {technical.reasons?.length ? (
            <div className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
              <p>{technical.reasons[0]}</p>
              {technical.reasons.length > 1 ? (
                <details className="mt-1">
                  <summary className="cursor-pointer select-none text-slate-600 dark:text-slate-300">
                    {t('moreReasons', { count: technical.reasons.length - 1 })}
                  </summary>
                  <ul className="mt-1 list-disc space-y-0.5 pl-4">
                    {technical.reasons.slice(1).map((r) => (
                      <li key={r}>{r}</li>
                    ))}
                  </ul>
                </details>
              ) : null}
            </div>
          ) : null}
          {technical.technical_details ? <TechnicalDetailsSection details={technical.technical_details} /> : null}
        </>
      ) : null}

      <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
        {t('fundamentalsStance', { stance: t(STANCE_KEYS[entry.fundamentals.stance] ?? 'stanceUnavailable') })}
        {entry.fundamentals.applied ? '' : ` · ${t('fundamentalsNotApplied')}`}
      </p>
    </div>
  )
}

function HurdleTable({ hurdle }: { hurdle: IndexHurdle | null }) {
  const { t } = useI18n()
  const status = hurdle?.status ?? 'unavailable'

  return (
    <div className="mt-3 rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
          {t('indexHurdle')}
        </p>
        <span className={`rounded px-2 py-0.5 text-[11px] font-semibold ${STATUS_TONE[status] ?? NEUTRAL_TONE}`}>
          {t(STATUS_KEYS[status] ?? 'hurdleUnavailable')}
        </span>
      </div>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">{t('indexHurdleHint')}</p>

      {hurdle?.benchmarks?.length ? (
        <div className="mt-2 overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-[11px]">
            <thead className="text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-2 font-medium">{t('hurdleBenchmark')}</th>
                <th className="py-1 pr-2 font-medium">{t('hurdleRole')}</th>
                <th className="py-1 pr-2 text-right font-medium">{t('hurdleRel121')}</th>
                <th className="py-1 pr-2 text-right font-medium">{t('hurdleRel6m')}</th>
                <th className="py-1 pr-2 text-center font-medium">{t('hurdleTrend')}</th>
                <th className="py-1 pr-2 text-center font-medium">{t('hurdleChecks')}</th>
                <th className="py-1 font-medium">{t('hurdleResult')}</th>
              </tr>
            </thead>
            <tbody className="text-slate-700 dark:text-slate-300">
              {hurdle.benchmarks.map((row) => (
                <tr key={row.symbol} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1 pr-2 font-semibold" title={row.label}>
                    {row.symbol}
                  </td>
                  <td className="py-1 pr-2">
                    {t(ROLE_KEYS[row.role] ?? 'hurdleRoleIndex')}
                    <span className="text-slate-400"> · {row.label}</span>
                  </td>
                  <td className="py-1 pr-2 text-right tabular-nums">{signedPct(row.rel_12_1_pct)}</td>
                  <td className="py-1 pr-2 text-right tabular-nums">{signedPct(row.rel_6m_pct)}</td>
                  <td className="py-1 pr-2 text-center">
                    {row.ratio_above_200d == null ? '—' : row.ratio_above_200d ? '✓' : '✗'}
                  </td>
                  <td className="py-1 pr-2 text-center tabular-nums">
                    {row.evidence_true}/{row.evidence_known}
                  </td>
                  <td className={`py-1 font-semibold ${RESULT_TONE[row.result] ?? ''}`}>
                    {t(RESULT_KEYS[row.result] ?? 'hurdleInsufficient')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}

      {hurdle?.benchmarks?.length ? (
        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">{t('hurdleRuleExplanation')}</p>
      ) : null}

      {hurdle ? (
        <p className="mt-2 text-[11px] text-slate-500 dark:text-slate-400">
          {t('earningsGuardLabel')} · {t(GUARD_KEYS[hurdle.earnings_guard?.status] ?? 'guardUnavailable')}
        </p>
      ) : null}
    </div>
  )
}

/**
 * The consolidated decision: Vincent's technical action per horizon, lowered
 * only by weak fundamentals (mid and long) and capped at hold when the stock is
 * not expected to beat every benchmark. Horizons stay independent; his own
 * action is shown whenever the final one differs.
 */
export function FinalDecisionPanel({ decision }: FinalDecisionPanelProps) {
  const { t } = useI18n()
  const quality = decision.data_quality

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/40">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
          {t('finalDecision')}
        </p>
        {decision.producer ? <p className="text-[11px] text-slate-500 dark:text-slate-400">{decision.producer}</p> : null}
      </div>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">{t('finalDecisionHint')}</p>
      {decision.errors ? (
        <p className="mt-1 text-[11px] font-medium text-rose-700 dark:text-rose-400">
          {t('consolidatedDecisionUnavailable', {
            reason: decision.errors.technical ?? decision.errors.index_hurdle ?? '',
          })}
        </p>
      ) : null}
      {quality ? (
        <p className="mt-1 text-[11px] text-slate-500 dark:text-slate-400">
          {t('consolidatedInputs', {
            fourHour: dataQualityLabel(t, quality.four_hour),
            oneHour: dataQualityLabel(t, quality.one_hour),
            market: quality.market ?? '—',
          })}
        </p>
      ) : null}

      <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-3">
        {HORIZONS.map(({ key, title, window }) => (
          <HorizonColumn
            key={key}
            entry={decision.horizons[key]}
            titleKey={title}
            windowKey={window}
            hurdle={decision.index_hurdle}
          />
        ))}
      </div>

      <HurdleTable hurdle={decision.index_hurdle} />
      {decision.market_structure ? <MarketStructureSection structure={decision.market_structure} /> : null}
    </div>
  )
}
