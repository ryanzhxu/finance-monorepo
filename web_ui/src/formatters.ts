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

const ENTRY_ASSESSMENTS: Record<Locale, Record<string, string>> = {
  en: {
    buy_now: 'Buy now',
    wait_for_pullback: 'Wait for pullback',
    wait_for_breakout_confirmation: 'Wait for breakout confirmation',
    avoid: 'Avoid',
    short_term_trade_only: 'Short-term trade only',
    long_term_investment_candidate: 'Long-term candidate',
  },
  'zh-Hans': {
    buy_now: '立即买入',
    wait_for_pullback: '等待回调',
    wait_for_breakout_confirmation: '等待突破确认',
    avoid: '回避',
    short_term_trade_only: '仅适合短线交易',
    long_term_investment_candidate: '长线候选',
  },
  'zh-Hant-HK': {
    buy_now: '立即買入',
    wait_for_pullback: '等待回調',
    wait_for_breakout_confirmation: '等待突破確認',
    avoid: '迴避',
    short_term_trade_only: '僅適合短線交易',
    long_term_investment_candidate: '長線候選',
  },
}

export function formatEntryAssessment(assessment: string | null | undefined, locale: Locale): string {
  if (!assessment) return '—'
  return ENTRY_ASSESSMENTS[locale]?.[assessment] ?? assessment
}

const RESEARCH_STAGES: Record<Locale, Record<string, string>> = {
  en: {
    queued: 'Queued',
    discovering: 'Discovering',
    verifying: 'Verifying',
    reviewing: 'Reviewing',
    calculating: 'Calculating',
    completed: 'Completed',
    failed: 'Failed',
    cancelled: 'Cancelled',
  },
  'zh-Hans': {
    queued: '排队中',
    discovering: '发现候选中',
    verifying: '核实证据中',
    reviewing: '审核中',
    calculating: '计算中',
    completed: '已完成',
    failed: '失败',
    cancelled: '已取消',
  },
  'zh-Hant-HK': {
    queued: '排隊中',
    discovering: '發現候選中',
    verifying: '核實證據中',
    reviewing: '審核中',
    calculating: '計算中',
    completed: '已完成',
    failed: '失敗',
    cancelled: '已取消',
  },
}

export function formatResearchStage(stage: string | null | undefined, locale: Locale): string {
  if (!stage) return '—'
  return RESEARCH_STAGES[locale]?.[stage] ?? stage.replaceAll('_', ' ')
}

const REVIEW_VERDICTS: Record<Locale, Record<string, string>> = {
  en: {
    supported: 'Supported',
    needs_more_evidence: 'Needs more evidence',
    reject: 'Reject',
  },
  'zh-Hans': {
    supported: '证据支持',
    needs_more_evidence: '证据不足',
    reject: '不成立',
  },
  'zh-Hant-HK': {
    supported: '證據支持',
    needs_more_evidence: '證據不足',
    reject: '不成立',
  },
}

export function formatReviewVerdict(verdict: string | null | undefined, locale: Locale): string {
  if (!verdict) return '—'
  return REVIEW_VERDICTS[locale]?.[verdict] ?? verdict.replaceAll('_', ' ')
}
