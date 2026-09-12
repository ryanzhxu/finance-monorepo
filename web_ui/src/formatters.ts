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

// Keyed by both the human-readable dimension text this repo's signals.py
// emits ("EPS Surprise") and the raw signal_weights.yaml-style key a signal
// can also arrive as ("EPS_Surprise", "Technical_External") — the deployed
// API has been observed returning the underscore form, so both must resolve
// to the same translation.
const DIMENSIONS: Partial<Record<Locale, Record<string, string>>> = {
  en: {
    RSI_14: 'RSI(14)',
    MA_50_200: 'MA 50/200',
    Bollinger_Bands: 'Bollinger Bands',
    RSI_Weekly: 'RSI Weekly',
    Support_Resistance: 'Support/Resistance',
    EPS_Surprise: 'EPS Surprise',
    PE_Percentile: 'PE Percentile',
    Analyst_Ratings: 'Analyst Ratings',
    Put_Call_Ratio: 'Put/Call Ratio',
    IV_Rank: 'IV Rank',
    Short_Interest: 'Short Interest',
    Institutional_13F: 'Institutional 13F',
    News_Sentiment: 'News Sentiment',
    FOMC_Proximity: 'Macro (FOMC)',
    Technical_External: 'Technical (external)',
  },
  'zh-Hans': {
    'RSI(14)': 'RSI(14)', RSI_14: 'RSI(14)',
    MACD: 'MACD',
    'MA 50/200': 'MA 50/200', MA_50_200: 'MA 50/200',
    'Bollinger Bands': '布林带', Bollinger_Bands: '布林带',
    Volume: '成交量',
    'RSI Weekly': '周线 RSI', RSI_Weekly: '周线 RSI',
    'Support/Resistance': '支撑/阻力', Support_Resistance: '支撑/阻力',
    'EPS Surprise': '每股收益超预期', EPS_Surprise: '每股收益超预期',
    'PE Percentile': '市盈率分位', PE_Percentile: '市盈率分位',
    'Analyst Ratings': '分析师评级', Analyst_Ratings: '分析师评级',
    'Put/Call Ratio': '看跌／看涨期权比率', Put_Call_Ratio: '看跌／看涨期权比率',
    'IV Rank': '隐含波动率分位', IV_Rank: '隐含波动率分位',
    'Short Interest': '卖空比例', Short_Interest: '卖空比例',
    'Institutional 13F': '机构 13F', Institutional_13F: '机构 13F',
    'News Sentiment': '新闻情绪', News_Sentiment: '新闻情绪',
    'Macro (FOMC)': '宏观（FOMC）', FOMC_Proximity: '宏观（FOMC）',
    'Technical (external)': '技术面（外部）', Technical_External: '技术面（外部）',
  },
  'zh-Hant-HK': {
    'RSI(14)': 'RSI(14)', RSI_14: 'RSI(14)',
    MACD: 'MACD',
    'MA 50/200': 'MA 50/200', MA_50_200: 'MA 50/200',
    'Bollinger Bands': '布林通道', Bollinger_Bands: '布林通道',
    Volume: '成交量',
    'RSI Weekly': '週線 RSI', RSI_Weekly: '週線 RSI',
    'Support/Resistance': '支持/阻力', Support_Resistance: '支持/阻力',
    'EPS Surprise': '每股盈利驚喜', EPS_Surprise: '每股盈利驚喜',
    'PE Percentile': '市盈率百分位', PE_Percentile: '市盈率百分位',
    'Analyst Ratings': '分析師評級', Analyst_Ratings: '分析師評級',
    'Put/Call Ratio': '認沽／認購比率', Put_Call_Ratio: '認沽／認購比率',
    'IV Rank': '隱含波動率排名', IV_Rank: '隱含波動率排名',
    'Short Interest': '沽空比率', Short_Interest: '沽空比率',
    'Institutional 13F': '機構 13F', Institutional_13F: '機構 13F',
    'News Sentiment': '新聞情緒', News_Sentiment: '新聞情緒',
    'Macro (FOMC)': '宏觀（FOMC）', FOMC_Proximity: '宏觀（FOMC）',
    'Technical (external)': '技術面（外部）', Technical_External: '技術面（外部）',
  },
}

export function formatDimension(dimension: string | null | undefined, locale: Locale): string {
  const table = DIMENSIONS[locale]
  if (!table) return dimension ?? '—'
  return table[dimension ?? ''] ?? dimension ?? '—'
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
