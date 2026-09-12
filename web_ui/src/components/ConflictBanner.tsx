import type { Recommendation } from '../api/types'
import { useI18n } from '../i18n'
import { formatDirection } from '../formatters'

type ConflictBannerProps = {
  recommendation: Recommendation
}

/**
 * Names the tension when the technical action and Ryan's other layers point
 * different ways. `conflict_detected` is computed on every recommendation,
 * with or without an external verdict, but had no UI consumer — this is the
 * one place that reads it. The sentence itself is built here from structured
 * fields, through the i18n system — `conflict_summary` is an English-only
 * fact string for the backend's LLM narrative prompt and must never be
 * rendered directly, or it leaks English into a localized screen.
 */
export function ConflictBanner({ recommendation }: ConflictBannerProps) {
  const { t, locale } = useI18n()
  if (!recommendation.conflict_detected) {
    return null
  }

  const summary = recommendation.supporting_context
    ? t('conflictSummaryExternal', {
        technicalDirection: formatDirection(recommendation.direction, locale),
        fundamentalDirection: formatDirection(recommendation.supporting_context.direction, locale),
      })
    : recommendation.conflict_technical_direction && recommendation.conflict_fundamental_direction
      ? t('conflictSummaryBlended', {
          technicalDirection: formatDirection(recommendation.conflict_technical_direction, locale),
          technicalSupporters: recommendation.conflict_technical_supporters ?? 0,
          technicalTotal: recommendation.conflict_technical_total ?? 0,
          fundamentalDirection: formatDirection(recommendation.conflict_fundamental_direction, locale),
          fundamentalSupporters: recommendation.conflict_fundamental_supporters ?? 0,
          fundamentalTotal: recommendation.conflict_fundamental_total ?? 0,
        })
      : null

  if (!summary) {
    return null
  }

  return (
    <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-900 dark:bg-amber-950/40">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800 dark:text-amber-300">
        {t('conflict')}
      </p>
      <p className="mt-1 text-[12px] text-amber-900 dark:text-amber-200">{summary}</p>
    </div>
  )
}
