import type { Recommendation } from '../api/types'
import { useI18n } from '../i18n'

type TechnicalSourceBadgeProps = {
  recommendation: Recommendation
}

/**
 * Shows who produced the technical vote, and whether the two engines agree.
 *
 * Vincent's condition for acting on a recommendation (2026-07-10) was that he
 * has to believe it, and that two independent engines reaching the same call is
 * what makes it believable. This surfaces that, rather than leaving it buried in
 * the response body.
 */
export function TechnicalSourceBadge({ recommendation }: TechnicalSourceBadgeProps) {
  const { t } = useI18n()
  const source = recommendation.technical_source
  const rejected = recommendation.risk_flags.includes('external_technical_rejected')

  // Responses from before the composite engine shipped carry no source at all.
  if (!source && !rejected) {
    return null
  }

  if (rejected) {
    return (
      <span
        title={t('technicalRejectedTitle')}
        className="rounded-full bg-amber-100 px-3 py-1 text-sm font-semibold text-amber-900 dark:bg-amber-500/20 dark:text-amber-200"
      >
        {t('technicalRejected')}
      </span>
    )
  }

  if (source === 'local') {
    return (
      <span
        title={t('localTechnicalsTitle')}
        className="rounded-full bg-slate-200 px-3 py-1 text-sm font-medium text-slate-700 dark:bg-slate-800 dark:text-slate-300"
      >
        {t('localTechnicals')}
      </span>
    )
  }

  const agreement = recommendation.technical_agreement
  const producer = recommendation.technical_producer ?? 'external engine'
  const priceState = recommendation.technical_price_state

  const agreementTone =
    agreement === true
      ? 'bg-emerald-100 text-emerald-900 dark:bg-emerald-500/20 dark:text-emerald-200'
      : agreement === false
        ? 'bg-rose-100 text-rose-900 dark:bg-rose-500/20 dark:text-rose-200'
        : 'bg-slate-200 text-slate-700 dark:bg-slate-800 dark:text-slate-300'

  // `producer` and `direction`/`price_state` are engine-emitted vocabulary, left
  // untranslated on the same boundary the other panels draw. Only the client
  // chrome around them is localized.
  const agreementLabel =
    agreement === true
      ? t('bothEnginesAgree')
      : agreement === false
        ? t('enginesDisagree', { direction: recommendation.local_technical_direction ?? t('unknownDirection') })
        : t('noLocalToCompare')

  return (
    <span className="flex flex-wrap items-center gap-2">
      <span
        title={t('technicalSuppliedBy', { producer })}
        className="rounded-full bg-indigo-100 px-3 py-1 text-sm font-medium text-indigo-900 dark:bg-indigo-500/20 dark:text-indigo-200"
      >
        {t('technicalsLabel')}: {producer}
        {priceState ? ` · ${priceState.toLowerCase().replace(/_/g, ' ')}` : ''}
      </span>
      <span className={`rounded-full px-3 py-1 text-sm font-semibold ${agreementTone}`}>
        {agreementLabel}
      </span>
    </span>
  )
}
