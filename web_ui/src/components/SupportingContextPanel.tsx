import type { Recommendation } from '../api/types'
import { formatDirection } from '../formatters'
import { useI18n } from '../i18n'

type SupportingContextPanelProps = {
  recommendation: Recommendation
}

/**
 * Shows Ryan's non-technical layers beside Vincent's technical action.
 *
 * Vincent's engine forbids fundamental, valuation, options and news data from
 * entering a recommendation, so these never move his call. Rendering them as a
 * separate block — with an explicit agree/disagree line — is what lets both
 * views exist without one quietly overriding the other.
 */
export function SupportingContextPanel({ recommendation }: SupportingContextPanelProps) {
  const { locale } = useI18n()
  const context = recommendation.supporting_context
  if (!context) {
    return null
  }

  const agrees = context.agrees_with_action
  const tone = agrees
    ? 'border-emerald-200 bg-emerald-50 dark:border-emerald-900 dark:bg-emerald-950/40'
    : 'border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/40'
  const headline = agrees
    ? 'Supporting analysis agrees'
    : 'Supporting analysis disagrees'

  return (
    <div className={`mt-4 rounded-lg border px-4 py-3 ${tone}`}>
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
          {headline}
        </p>
        <p className="text-sm font-medium text-slate-900 dark:text-slate-100">
          {formatDirection(context.direction, locale)} · {(context.confidence * 100).toFixed(0)}% support
        </p>
      </div>

      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">
        Fundamentals, sentiment and macro, scored separately. These never change the
        technical action above.
      </p>

      <ul className="mt-2 space-y-1">
        {context.signals.map((signal) => (
          <li
            key={signal.dimension}
            className="flex items-center justify-between gap-3 text-[12px] text-slate-700 dark:text-slate-300"
          >
            <span className="truncate">{signal.dimension}</span>
            <span className="shrink-0 tabular-nums">
              {formatDirection(signal.signal, locale)} · {signal.note}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
