import type { Recommendation } from '../api/types'
import { useI18n } from '../i18n'

type ConflictBannerProps = {
  recommendation: Recommendation
}

/**
 * Names the tension when the technical action and Ryan's other layers point
 * different ways. `conflict_detected`/`conflict_summary` are computed on
 * every recommendation, with or without an external verdict, but had no UI
 * consumer — this is the one place that reads them.
 */
export function ConflictBanner({ recommendation }: ConflictBannerProps) {
  const { t } = useI18n()
  if (!recommendation.conflict_detected || !recommendation.conflict_summary) {
    return null
  }

  return (
    <div className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 dark:border-amber-900 dark:bg-amber-950/40">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-800 dark:text-amber-300">
        {t('conflict')}
      </p>
      <p className="mt-1 text-[12px] text-amber-900 dark:text-amber-200">{recommendation.conflict_summary}</p>
    </div>
  )
}
