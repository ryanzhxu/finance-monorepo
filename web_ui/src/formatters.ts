import type { Locale } from './i18n'

const DIRECTIONS: Partial<Record<Locale, Record<string, string>>> = {
  'zh-Hans': { BUY: '买入', HOLD: '持有', SELL: '卖出' },
  'zh-Hant-HK': { BUY: '買入', HOLD: '持有', SELL: '賣出' },
}

export function formatDirection(direction: string | null | undefined, locale: Locale): string {
  const table = DIRECTIONS[locale]
  if (!table) return direction ?? '—'
  return table[direction ?? ''] ?? direction ?? '—'
}
