import type { Locale } from './i18n'

export function formatDirection(direction: string | null | undefined, locale: Locale): string {
  if (locale !== 'zh-HK') return direction ?? '—'
  return ({ BUY: '買入', HOLD: '持有', SELL: '賣出' } as Record<string, string>)[direction ?? ''] ?? direction ?? '—'
}
