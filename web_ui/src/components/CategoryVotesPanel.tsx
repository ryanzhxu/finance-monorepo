import type { Direction, Recommendation } from '../api/types'
import { formatDirection } from '../formatters'
import { useI18n } from '../i18n'

type CategoryVotesPanelProps = {
  recommendation: Recommendation
}

const DIRECTIONS: Direction[] = ['BUY', 'HOLD', 'SELL']

const directionTone: Record<Direction, string> = {
  BUY: 'text-green-700 dark:text-green-400',
  HOLD: 'text-amber-700 dark:text-amber-400',
  SELL: 'text-red-700 dark:text-red-400',
}

const CATEGORIES: { key: keyof Pick<Recommendation, 'technical_vote' | 'fundamental_vote' | 'sentiment_vote' | 'macro_vote'>; label: string }[] = [
  { key: 'technical_vote', label: 'Technical' },
  { key: 'fundamental_vote', label: 'Fundamental' },
  { key: 'sentiment_vote', label: 'Sentiment' },
  { key: 'macro_vote', label: 'Macro' },
]

function dominantDirection(vote: Partial<Record<Direction, number>>): Direction {
  return DIRECTIONS.reduce((best, direction) => ((vote[direction] ?? 0) > (vote[best] ?? 0) ? direction : best), 'HOLD')
}

/**
 * Shows the weighted vote behind `weighted_score`, one card per category.
 *
 * `technical_vote`/`fundamental_vote`/`sentiment_vote`/`macro_vote` are
 * computed on every recommendation, blended or external, but had no UI
 * consumer — this is the explainable breakdown item 5 asks for.
 */
export function CategoryVotesPanel({ recommendation }: CategoryVotesPanelProps) {
  const { locale } = useI18n()

  return (
    <div className="mt-4 rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 dark:border-slate-800 dark:bg-slate-900/40">
      <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-slate-600 dark:text-slate-300">
        Category votes
      </p>
      <p className="mt-1 text-[12px] text-slate-600 dark:text-slate-400">
        Weighted BUY / HOLD / SELL behind the recommendation, by category.
      </p>

      <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-4">
        {CATEGORIES.map(({ key, label }) => {
          const vote = recommendation[key]
          const dominant = dominantDirection(vote)
          return (
            <div
              key={key}
              className="rounded-md border border-slate-200 bg-white px-3 py-2 dark:border-slate-800 dark:bg-[#0d0f14]"
            >
              <div className="flex items-baseline justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-[0.18em] text-slate-500 dark:text-slate-400">
                  {label}
                </span>
                <span className={`text-sm font-medium ${directionTone[dominant]}`}>
                  {formatDirection(dominant, locale)}
                </span>
              </div>
              <p className="mt-1 text-[12px] tabular-nums text-slate-600 dark:text-slate-400">
                {DIRECTIONS.map((direction) => `${direction[0]} ${(vote[direction] ?? 0).toFixed(2)}`).join(' · ')}
              </p>
            </div>
          )
        })}
      </div>
    </div>
  )
}
