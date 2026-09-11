import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

// Simplified and Traditional Chinese are different vocabularies, not one glyph
// set converted into another. 質素/质量, 市賬率/市净率 and 快取/缓存 are genuinely
// different words, so each locale below is written and maintained by hand with
// English as the source of truth. Neither is derived from the other, and no
// character converter is used on either.
//
// zh-Hant-HK is FORMAL written Hong Kong Chinese (書面語) — Mandarin-style
// grammar (這/沒有/很/嗎) with Hong Kong vocabulary. It is deliberately not
// Cantonese: the previous zh-HK locale was genuine written Cantonese (嘅/唔/
// 喺/冇/咗) and was removed, not converted.
export type Locale = 'en' | 'zh-Hans' | 'zh-Hant-HK'

export const LOCALES: readonly Locale[] = ['en', 'zh-Hans', 'zh-Hant-HK'] as const

/** Cycle through the locales, so one button serves all three. */
export function cycleLocale(current: Locale): Locale {
  const index = LOCALES.indexOf(current)
  return LOCALES[(index + 1) % LOCALES.length]
}

const messages = {
  en: {
    appTitle: 'Market Analysis Console',
    appDescription: 'A focused console for market analysis, grounded research, screening, and service health checks.',
    analyze: 'Analyze',
    screener: 'Screener',
    research: 'Research',
    health: 'Health',
    watchlist: 'Watchlist',
    add: 'Add',
    addSymbol: 'Add a symbol to start a lightweight watchlist.',
    symbol: 'Symbol',
    removeSymbol: 'Remove {symbol}',
    neverRun: 'never run',
    stale: 'stale',
    justNow: 'just now',
    minutesAgo: '{count}m ago',
    hoursAgo: '{count}h ago',
    daysAgo: '{count}d ago',
    switchLanguage: 'Switch to Simplified Chinese',
    localeButton: '简',
    switchTheme: 'Switch to {theme} mode',
    light: 'light', dark: 'dark', system: 'system',
    screenerTitle: 'Live screen results by strategy',
    screenerDescription: "Endpoints are called directly from the browser with the repo's actual POST contracts.",
    undervalued: 'Undervalued', demandShock: 'Demand Shock', trending: 'Trending',
    run: 'Run {screen}', running: 'Running...', loadingResults: 'Loading results...',
    runScreenHint: 'Run this screen to load results.', universe: 'Universe', regime: 'Regime', quality: 'Quality',
    score: 'Score', direction: 'Direction', confidence: 'Confidence', entryAssessment: 'Entry Assessment',
    dataQuality: 'Data Quality', actions: 'Actions', screenerHeldByHurdle: 'Held — index hurdle',
    healthTitle: 'Service heartbeat', lastChecked: 'Last checked: {time} · auto-refresh 30s', refresh: 'Refresh',
    healthy: 'Healthy', down: 'Down', core: 'Core', dataProviders: 'Data providers', checking: 'Checking…', status: 'Status', configValid: 'Config valid', cache: 'Cache', languageModel: 'LLM', available: 'available', unavailable: 'unavailable', unreachable: 'unreachable', evidence: 'Evidence', job: 'Job',
    analyst: 'Analyst',
    researchLab: 'Research lab', evidenceBeforeConviction: 'Evidence before conviction',
    researchDescription: 'Ask for ranked candidates, catalysts, risks, entry conditions, reasons to avoid, and evidence-backed follow-up work. Research output is decision support, not guaranteed returns or personalized allocation advice.',
    question: 'Question', universeLabel: 'Universe', triggerContext: 'Trigger context', mode: 'Mode', candidates: 'Candidates',
    optionalTrigger: 'Optional: Existing holding review triggered by a concentration alert.',
    upsideDiscovery: 'Upside discovery', downsideRiskScan: 'Downside risk scan', runResearch: 'Run research', starting: 'Starting…', cancel: 'Cancel',
    usCommon: 'US-listed common stocks', usCommonAbove10b: 'US-listed common stocks above $10B market cap', sp500: 'S&P 500 constituents', nasdaq100: 'Nasdaq-100 constituents', russell1000: 'Russell 1000 constituents', russell2000: 'Russell 2000 constituents', dowJones: 'Dow Jones Industrial Average constituents',
    noSupportedItems: 'No supported items returned.', rank: 'Rank', decisionSupport: 'Decision support', analogyComparison: 'Analogy comparison', thesis: 'Thesis', catalysts: 'Catalysts', risks: 'Risks', entryConditions: 'Entry conditions', reasonsToAvoid: 'Reasons to avoid', reviewRisk: 'Review risk', unknowns: 'Unknowns', sources: 'Sources', noSources: 'No sources returned.',
    privateWatchlist: 'Private watchlist', loadingPrivateWatchlist: 'Loading private watchlist...',
    privateWatchlistHelp: 'Enter the shared passcode to access your private stock pool.', passcode: 'Passcode',
    unlockPrivateWatchlist: 'Unlock private watchlist', checkingPasscode: 'Checking passcode...', logout: 'Log out',
    sharedWatchlistDescription: 'Shared symbol pool for private collaboration. Membership is shared, analysis stays fast per device.',
    unableToLoadPrivateWatchlist: 'Unable to load private watchlist', unableToAuthenticate: 'Unable to authenticate', unableToLogout: 'Unable to log out', unableToUpdateWatchlist: 'Unable to update shared watchlist',
    stop: 'Stop', added: 'Added ✓', addToWatchlist: 'Add to Watchlist', analysisStopped: 'Analysis stopped',
    requestCancelled: 'request cancelled', runAgain: 'Run again', enterSymbol: 'Enter a symbol above to begin.',
    signals: 'Signals', showSignals: 'Show signals', hideSignals: 'Hide signals', dimension: 'Dimension', note: 'Note',
    fundamentals: 'Fundamentals', sentiment: 'Sentiment', currentPrice: 'Current price', idealBuyZone: 'Ideal buy zone',
    fibGoldenPocket: 'Fib golden pocket', conservativeEntry: 'Conservative entry', stopLoss: 'Stop loss', invalidation: 'Invalidation',
    highConvictionZone: 'High conviction zone', signalVote: 'Signal vote', nextFomc: 'Next FOMC', rateCutProbability: 'Rate cut probability', resistance: 'Resistance', support: 'Support', breakoutBuyLevel: 'Breakout buy level', weight: 'Weight',
    fetchPriceData: 'Fetch price data', computeTechnicals: 'Compute technicals', loadFundamentals: 'Load fundamentals',
    assembleSignals: 'Assemble signals', buildConfluence: 'Build confluence', loadingAnalysis: 'Loading analysis', analyzing: 'analyzing',
    entryStructureUnavailable: 'Entry structure unavailable for this response.',
    epsSurprise: 'EPS surprise', peRatio: 'P/E ratio', pePercentile: 'P/E percentile (5y)', fcfTrend: 'FCF trend',
    analystUpgrades: 'Analyst upgrades (30d)', analystDowngrades: 'Analyst downgrades (30d)', revenueGrowth: 'Revenue growth YoY',
    grossMargin: 'Gross margin', pbRatio: 'P/B ratio', psRatio: 'P/S ratio', evEbitda: 'EV/EBITDA', asOfDate: 'As-of date',
    putCallRatio: 'Put/call ratio', ivRank: 'IV rank (approx)', shortInterest: 'Short interest', redditMentions: 'Reddit mentions', volumeSpike: 'Volume vs 90d avg', priceVolumeMomentum: 'Price/volume momentum',
    redditSentiment: 'Reddit sentiment', institutional13f: 'Institutional 13F', freshness: 'Freshness',
    conflict: 'Conflict', categoryVotes: 'Category votes', categoryVotesHint: 'Weighted buy / hold / sell behind the recommendation, by category.',
    technical: 'Technical', fundamental: 'Fundamental', macro: 'Macro',
    supportingAnalysisAgrees: 'Supporting analysis agrees', supportingAnalysisDisagrees: 'Supporting analysis disagrees', percentSupport: '{percent}% support',
    supportingContextHint: 'Fundamentals, sentiment and macro, scored separately. These never change the technical action above.',
    technicalByHorizon: 'Technical by horizon', technicalByHorizonHint: 'Independent per horizon and never averaged — there is deliberately no overall action.',
    noPriceLandscape: 'No usable price landscape — the engine declined to emit bands.', opportunity: 'Opportunity', reduce: 'Reduce',
    percentConfidence: '{percent}% confidence', data: 'data',
    priceStateInOpportunity: 'In opportunity zone', priceStateNearOpportunity: 'Near opportunity zone', priceStateNeutral: 'Neutral zone', priceStateNearReduce: 'Near reduce zone', priceStateInReduce: 'In reduce zone', priceStateBeyondReduce: 'Beyond reduce zone', priceStateBreakdown: 'Breakdown', priceStateInvalidLandscape: 'Invalid landscape',
    dataQualitySourceUnavailable: 'Source unavailable', dataQualityInvalidSource: 'Invalid source data',
    technicalDetails: 'Technical details', movingAverages: 'Moving averages', relativeStrength: 'Relative strength', fibonacci: 'Fibonacci',
    marketStructure: 'Market structure', relativeVolume: 'Relative volume', fiftyTwoWeekRange: '52-week range', distanceToHigh: 'from high', distanceToLow: 'from low',
    finalDecision: 'Final decision', finalDecisionHint: "Vincent's technical action leads. Ryan's fundamentals can only lower a mid or long buy. A buy must also beat every benchmark below.",
    consolidatedInputs: 'Inputs · 4H {fourHour} · 1H {oneHour} · market {market}%', technicalAction: 'Technical', finalAction: 'Final',
    consolidatedDecisionUnavailable: 'Unavailable — could not load market data ({reason})',
    actionStrongBuy: 'Strong Buy', actionBuy: 'Buy', actionAccumulate: 'Accumulate', actionHold: 'Hold', actionTrim: 'Trim', actionSell: 'Sell', actionAvoid: 'Avoid',
    reasonFundamentalsWeak: 'Weak fundamentals lowered it one step', reasonIndexHurdleFailed: 'Not expected to beat {benchmarks}',
    reasonIndexHurdleUnavailable: 'Index hurdle unavailable, so the buy is held', reasonTechnicalUnavailable: 'Technical engine unavailable for this horizon',
    reasonEarningsGuard: 'Negative EPS surprise and analysts turning bearish',
    fundamentalsStance: 'Fundamentals {stance}', stanceSupportive: 'supportive', stanceNeutral: 'neutral', stanceWeak: 'weak', stanceUnavailable: 'unavailable', fundamentalsNotApplied: 'not applied to short',
    indexHurdle: 'Index hurdle', indexHurdleHint: 'Next 12 months. A buy must show evidence that it beats every benchmark. These are historical relative returns, not a forecast.',
    hurdlePass: 'Pass', hurdleFail: 'Fail', hurdleNotApplicable: 'Not applicable (index fund)', hurdleUnavailable: 'Unavailable',
    hurdleBenchmark: 'Benchmark', hurdleRole: 'Type', hurdleRel121: '12-1M rel.', hurdleRel6m: '6M rel.', hurdleTrend: 'Ratio > 200D', hurdleResult: 'Result', hurdleChecks: 'Checks',
    hurdleRuleExplanation: 'A benchmark counts as beaten when at least 2 of 3 checks pass: 12-1 month relative return, 6-month relative return, and the ratio above its 200-day average. The stock must beat every benchmark.',
    hurdleRoleIndex: 'Index', hurdleRoleSector: 'Sector', hurdleRoleIndustry: 'Industry', hurdleRoleLocalIndex: 'Local index',
    hurdleBeats: 'beats', hurdleLags: 'lags', hurdleMixed: 'mixed', hurdleInsufficient: 'no data',
    earningsGuardLabel: 'Earnings guard', guardClear: 'clear', guardFired: 'fired', guardUnavailable: 'no data',
    horizonShort: 'Short', horizonMid: 'Mid', horizonLong: 'Long', horizonShortWindow: '1–30 days', horizonMidWindow: '1–6 months', horizonLongWindow: '> 6 months',
    decisionBoard: 'Decision Board',
    decisionBoardEmpty: 'No symbols to show.', decisionBoardLoading: 'Loading…', decisionBoardRowError: 'Could not load {symbol}: {message}',
    technicalRejectedTitle: 'The external technical verdict violated decision.v1, so the local technicals were used instead.',
    technicalRejected: 'external technical rejected', localTechnicalsTitle: 'No external technical verdict was supplied, so the local technicals were used.',
    localTechnicals: 'local technicals', bothEnginesAgree: 'both engines agree', enginesDisagree: 'engines disagree — local said {direction}',
    noLocalToCompare: 'no local technical to compare', technicalSuppliedBy: 'Technical layer supplied by {producer}', technicalsLabel: 'technicals', unknownDirection: 'unknown',
    trackRecord: 'Track Record',
    trackRecordTitle: 'What we said, and whether it worked',
    trackRecordDescription: 'Past calls scored against realized prices. Coverage loads free; scoring calls a price provider once per symbol.',
    coverageRecords: 'Records', coverageSymbols: 'Symbols', coverageRange: 'Range',
    noTrackRecord: 'No calls recorded yet. Analyses are scored here once they are old enough to evaluate.',
    symbolTimeline: 'Symbol timeline', loadTimeline: 'Load', noCallsForSymbol: 'No stored calls for {symbol}.',
    priceAtCall: 'Price at call', targetWindow: 'Target window', hit: 'Hit', when: 'Date', skippedLabel: 'not scored',
    performance: 'Performance', loadPerformance: 'Load report', hitRate: 'Hit rate', evaluatedCount: 'Evaluated', decisionCount: 'Directional calls',
    avgForwardReturn: 'Avg forward return', avgVsBenchmark: 'Avg vs benchmark', advisoryLabel: 'Advisory',
    byDirection: 'By direction', byConfidence: 'By confidence', byEntryAssessment: 'By entry timing',
  },
  // Simplified Chinese, mainland vocabulary: 数据 / 质量 / 缓存 / 刷新 / 市净率 /
  // 卖空 / 斐波那契. Mainland UI writing translates technical terms rather than
  // leaving them in English, unlike the Hong Kong locale below.
  'zh-Hans': {
    appTitle: '市场分析控制台',
    appDescription: '一个专注于市场分析、实证研究、筛选和服务状态检查的控制台。',
    analyze: '分析', screener: '筛选器', research: '研究', health: '服务状态', watchlist: '自选列表',
    add: '添加', addSymbol: '添加一个股票代码，建立轻量自选列表。', symbol: '股票代码', removeSymbol: '移除 {symbol}',
    neverRun: '从未运行', stale: '已过期', justNow: '刚刚', minutesAgo: '{count} 分钟前', hoursAgo: '{count} 小时前', daysAgo: '{count} 天前',
    switchLanguage: '切换到繁體中文（香港）', localeButton: '繁', switchTheme: '切换到{theme}模式', light: '浅色', dark: '深色', system: '跟随系统',
    screenerTitle: '按策略查看实时筛选结果', screenerDescription: '浏览器按仓库实际的 POST 合约直接调用接口。',
    undervalued: '估值偏低', demandShock: '需求冲击', trending: '趋势中', run: '运行{screen}', running: '运行中...', loadingResults: '正在加载结果...',
    runScreenHint: '运行这个筛选器以加载结果。', universe: '股票范围', regime: '市场状态', quality: '质量', score: '评分', direction: '方向',
    confidence: '置信度', entryAssessment: '入场评估', dataQuality: '数据质量', actions: '操作', screenerHeldByHurdle: '持有 — 未过指数门槛',
    healthTitle: '服务心跳', lastChecked: '最后检查：{time} · 每 30 秒自动刷新', refresh: '刷新', healthy: '正常', down: '不可用', core: '核心', dataProviders: '数据源', checking: '检查中…', status: '状态', configValid: '配置有效', cache: '缓存', languageModel: '大语言模型', available: '可用', unavailable: '不可用', unreachable: '无法连接', evidence: '证据', job: '任务', analyst: '分析服务',
    researchLab: '研究室', evidenceBeforeConviction: '先看证据，再下判断', researchDescription: '获取排序后的候选公司、催化因素、风险、入场条件、回避理由，以及有证据支持的后续工作。研究结果仅作决策参考，不保证回报，也不是个性化的资产配置建议。',
    question: '问题', universeLabel: '股票范围', triggerContext: '触发背景', mode: '模式', candidates: '候选数量', optionalTrigger: '可选：因持仓过于集中的提示而重新审视现有持仓。',
    upsideDiscovery: '上行机会发现', downsideRiskScan: '下行风险扫描', runResearch: '运行研究', starting: '启动中…', cancel: '取消',
    usCommon: '美国上市普通股', usCommonAbove10b: '市值超过 100 亿美元的美国上市普通股', sp500: '标普 500 指数成分股', nasdaq100: '纳斯达克 100 指数成分股', russell1000: '罗素 1000 指数成分股', russell2000: '罗素 2000 指数成分股', dowJones: '道琼斯工业平均指数成分股',
    noSupportedItems: '没有返回受支持的条目。', rank: '排名', decisionSupport: '决策参考', analogyComparison: '类比对照', thesis: '投资逻辑', catalysts: '催化因素', risks: '风险', entryConditions: '入场条件', reasonsToAvoid: '回避理由', reviewRisk: '复核风险', unknowns: '未知项', sources: '资料来源', noSources: '没有返回资料来源。',
    privateWatchlist: '私人自选列表', loadingPrivateWatchlist: '正在加载私人自选列表...', privateWatchlistHelp: '输入共享密码以访问你的私人股票池。', passcode: '密码', unlockPrivateWatchlist: '解锁私人自选列表', checkingPasscode: '正在验证密码...', logout: '退出登录', sharedWatchlistDescription: '用于私人协作的共享股票池；成员资格共享，各设备的分析依然保持快速。',
    unableToLoadPrivateWatchlist: '无法加载私人自选列表', unableToAuthenticate: '无法验证身份', unableToLogout: '无法退出登录', unableToUpdateWatchlist: '无法更新共享自选列表',
    stop: '停止', added: '已添加 ✓', addToWatchlist: '加入自选列表', analysisStopped: '分析已停止', requestCancelled: '请求已取消', runAgain: '重新运行', enterSymbol: '在上方输入股票代码开始。',
    signals: '信号', showSignals: '显示信号', hideSignals: '隐藏信号', dimension: '维度', note: '说明', fundamentals: '基本面', sentiment: '市场情绪', currentPrice: '现价', idealBuyZone: '理想买入区间', fibGoldenPocket: '斐波那契黄金区间', conservativeEntry: '保守入场价', stopLoss: '止损价', invalidation: '失效位', highConvictionZone: '高确信区间', signalVote: '信号投票', nextFomc: '下次 FOMC', rateCutProbability: '降息概率', resistance: '阻力位', support: '支撑位', breakoutBuyLevel: '突破买入位', weight: '权重',
    fetchPriceData: '获取价格数据', computeTechnicals: '计算技术指标', loadFundamentals: '加载基本面', assembleSignals: '汇总信号', buildConfluence: '构建共振区间', loadingAnalysis: '正在加载分析', analyzing: '分析中', entryStructureUnavailable: '本次响应没有可用的入场结构。',
    epsSurprise: '每股收益超预期', peRatio: '市盈率', pePercentile: '市盈率百分位（5 年）', fcfTrend: '自由现金流趋势', analystUpgrades: '分析师上调（30 天）', analystDowngrades: '分析师下调（30 天）', revenueGrowth: '营收同比增长', grossMargin: '毛利率', pbRatio: '市净率', psRatio: '市销率', evEbitda: '企业价值／EBITDA', asOfDate: '数据截止日', putCallRatio: '看跌／看涨期权比率', ivRank: '隐含波动率分位（约）', shortInterest: '卖空比例', redditMentions: 'Reddit 提及次数', redditSentiment: 'Reddit 情绪', volumeSpike: '成交量对比 90 日均值', priceVolumeMomentum: '价量动能', institutional13f: '机构 13F', freshness: '数据新鲜度',
    conflict: '冲突', categoryVotes: '分类投票', categoryVotesHint: '推荐结果背后按分类加权的买入／持有／卖出票数。',
    technical: '技术面', fundamental: '基本面', macro: '宏观面',
    supportingAnalysisAgrees: '辅助分析一致', supportingAnalysisDisagrees: '辅助分析分歧', percentSupport: '{percent}% 支持',
    supportingContextHint: '基本面、市场情绪与宏观面分别评分，均不会改变上方的技术面操作。',
    technicalByHorizon: '各时间跨度技术面', technicalByHorizonHint: '每个时间跨度独立给出，从不取平均——刻意不给出总体操作。',
    noPriceLandscape: '没有可用的价格区间——引擎未给出区间。', opportunity: '机会区', reduce: '减仓区',
    percentConfidence: '{percent}% 置信度', data: '数据',
    priceStateInOpportunity: '机会区内', priceStateNearOpportunity: '接近机会区', priceStateNeutral: '中性区', priceStateNearReduce: '接近减仓区', priceStateInReduce: '减仓区内', priceStateBeyondReduce: '超出减仓区', priceStateBreakdown: '破位', priceStateInvalidLandscape: '区间失效',
    dataQualitySourceUnavailable: '数据源不可用', dataQualityInvalidSource: '数据源无效',
    technicalDetails: '技术细节', movingAverages: '均线', relativeStrength: '相对强度', fibonacci: '斐波那契',
    marketStructure: '市场结构', relativeVolume: '相对成交量', fiftyTwoWeekRange: '52 周区间', distanceToHigh: '距高点', distanceToLow: '距低点',
    finalDecision: '最终决策', finalDecisionHint: '以 Vincent 的技术面操作为主。Ryan 的基本面只能下调中线或长线的买入。买入还必须跑赢下方每一个基准。',
    consolidatedInputs: '输入 · 4 小时 {fourHour} · 1 小时 {oneHour} · 市场 {market}%', technicalAction: '技术面', finalAction: '最终',
    consolidatedDecisionUnavailable: '无法使用 — 无法加载市场数据（{reason}）',
    actionStrongBuy: '强力买入', actionBuy: '买入', actionAccumulate: '逐步加仓', actionHold: '持有', actionTrim: '减仓', actionSell: '卖出', actionAvoid: '回避',
    reasonFundamentalsWeak: '基本面偏弱，下调一级', reasonIndexHurdleFailed: '预计跑不赢 {benchmarks}',
    reasonIndexHurdleUnavailable: '指数门槛无法计算，买入改为持有', reasonTechnicalUnavailable: '该时间跨度的技术引擎不可用',
    reasonEarningsGuard: '每股收益低于预期，且分析师转向看空',
    fundamentalsStance: '基本面 {stance}', stanceSupportive: '支持', stanceNeutral: '中性', stanceWeak: '偏弱', stanceUnavailable: '不可用', fundamentalsNotApplied: '不适用于短线',
    indexHurdle: '指数门槛', indexHurdleHint: '未来 12 个月。买入必须有证据显示能跑赢每一个基准。以下为历史相对回报，不是预测。',
    hurdlePass: '通过', hurdleFail: '未通过', hurdleNotApplicable: '不适用（指数基金）', hurdleUnavailable: '不可用',
    hurdleBenchmark: '基准', hurdleRole: '类别', hurdleRel121: '12-1 个月相对', hurdleRel6m: '6 个月相对', hurdleTrend: '比值高于 200 日均线', hurdleResult: '结果', hurdleChecks: '通过项',
    hurdleRuleExplanation: '一个基准被视为跑赢，需满足以下 3 项中至少 2 项：12-1 个月相对回报、6 个月相对回报、比值高于其 200 日均线。股票必须跑赢每一个基准。',
    hurdleRoleIndex: '指数', hurdleRoleSector: '行业', hurdleRoleIndustry: '细分行业', hurdleRoleLocalIndex: '本地指数',
    hurdleBeats: '跑赢', hurdleLags: '落后', hurdleMixed: '好坏参半', hurdleInsufficient: '数据不足',
    earningsGuardLabel: '盈利警示', guardClear: '无', guardFired: '已触发', guardUnavailable: '数据不足',
    horizonShort: '短线', horizonMid: '中线', horizonLong: '长线', horizonShortWindow: '1–30 天', horizonMidWindow: '1–6 个月', horizonLongWindow: '> 6 个月',
    decisionBoard: '决策看板',
    decisionBoardEmpty: '暂无可显示的代码。', decisionBoardLoading: '加载中…', decisionBoardRowError: '无法加载 {symbol}：{message}',
    technicalRejectedTitle: '外部技术裁决不符合 decision.v1，因此改用本地技术指标。',
    technicalRejected: '外部技术裁决被拒', localTechnicalsTitle: '未提供外部技术裁决，因此使用本地技术指标。',
    localTechnicals: '本地技术指标', bothEnginesAgree: '两个引擎一致', enginesDisagree: '引擎分歧——本地判定为 {direction}',
    noLocalToCompare: '没有本地技术判定可供比较', technicalSuppliedBy: '技术层由 {producer} 提供', technicalsLabel: '技术面', unknownDirection: '未知',
    trackRecord: '业绩记录',
    trackRecordTitle: '我们说过什么，结果如何',
    trackRecordDescription: '过往判断按实际价格评分。覆盖情况免费加载；评分时每个标的调用一次价格数据源。',
    coverageRecords: '记录数', coverageSymbols: '股票数', coverageRange: '时间范围',
    noTrackRecord: '暂无记录。分析在足够久之后才会在此评分。',
    symbolTimeline: '标的历史', loadTimeline: '加载', noCallsForSymbol: '没有 {symbol} 的记录。',
    priceAtCall: '判断时价格', targetWindow: '目标窗口', hit: '命中', when: '日期', skippedLabel: '未评分',
    performance: '整体表现', loadPerformance: '加载报告', hitRate: '命中率', evaluatedCount: '已评分', decisionCount: '方向性判断',
    avgForwardReturn: '平均后续回报', avgVsBenchmark: '相对基准平均', advisoryLabel: '提示',
    byDirection: '按方向', byConfidence: '按置信度', byEntryAssessment: '按入场时机',
  },
  // Formal written Hong Kong Chinese (書面語): Mandarin-style grammar with Hong
  // Kong vocabulary (資料 / 質素 / 快取 / 市賬率 / 沽空 / 費波那契), and English
  // technical terms kept in English as Hong Kong professional writing does.
  'zh-Hant-HK': {
    appTitle: '市場分析工作台',
    appDescription: '一個專注於市場分析、實證研究、篩選及服務狀態檢查的工作台。',
    analyze: '分析', screener: '篩選器', research: '研究', health: '服務狀態', watchlist: '自選清單',
    add: '加入', addSymbol: '加入一個股票代號，建立輕量的自選清單。', symbol: '股票代號', removeSymbol: '移除 {symbol}',
    neverRun: '從未執行', stale: '已過期', justNow: '剛剛', minutesAgo: '{count} 分鐘前', hoursAgo: '{count} 小時前', daysAgo: '{count} 日前',
    switchLanguage: 'Switch to English', localeButton: 'EN', switchTheme: '切換至{theme}模式', light: '淺色', dark: '深色', system: '跟隨系統',
    screenerTitle: '按策略查看即時篩選結果', screenerDescription: '瀏覽器會按此倉庫實際的 POST 合約直接呼叫端點。',
    undervalued: '估值偏低', demandShock: '需求衝擊', trending: '趨勢中', run: '執行{screen}', running: '執行中...', loadingResults: '正在載入結果...',
    runScreenHint: '執行這個篩選器以載入結果。', universe: '股票範圍', regime: '市況', quality: '質素', score: '分數', direction: '方向',
    confidence: '信心度', entryAssessment: '入場評估', dataQuality: '資料質素', actions: '操作', screenerHeldByHurdle: '持有 — 未達指數門檻',
    healthTitle: '服務狀態', lastChecked: '最後檢查：{time} · 每 30 秒自動更新', refresh: '重新整理', healthy: '正常', down: '無法運作', core: '核心', dataProviders: '資料供應商', checking: '檢查中…', status: '狀態', configValid: '設定有效', cache: '快取', languageModel: 'LLM', available: '可用', unavailable: '不可用', unreachable: '無法連接', evidence: '證據', job: '工作', analyst: '分析服務',
    researchLab: '研究室', evidenceBeforeConviction: '先看證據，再作判斷', researchDescription: '取得排序後的候選公司、催化因素、風險、入場條件、迴避理由，以及有證據支持的後續工作。研究結果只作決策參考，不保證回報，亦不是個人化的資產配置建議。',
    question: '問題', universeLabel: '股票範圍', triggerContext: '觸發背景', mode: '模式', candidates: '候選數目', optionalTrigger: '可選：因持倉過於集中的提示而重新檢視現有持倉。',
    upsideDiscovery: '上行機會發掘', downsideRiskScan: '下行風險掃描', runResearch: '執行研究', starting: '啟動中…', cancel: '取消',
    usCommon: '美國上市普通股', usCommonAbove10b: '市值超過 100 億美元的美國上市普通股', sp500: '標普 500 指數成分股', nasdaq100: '納斯達克 100 指數成分股', russell1000: '羅素 1000 指數成分股', russell2000: '羅素 2000 指數成分股', dowJones: '道瓊斯工業平均指數成分股',
    noSupportedItems: '沒有返回受支援的項目。', rank: '排名', decisionSupport: '決策參考', analogyComparison: '類比對照', thesis: '投資理據', catalysts: '催化因素', risks: '風險', entryConditions: '入場條件', reasonsToAvoid: '迴避理由', reviewRisk: '覆核風險', unknowns: '未知事項', sources: '資料來源', noSources: '沒有返回資料來源。',
    privateWatchlist: '私人自選清單', loadingPrivateWatchlist: '正在載入私人自選清單...', privateWatchlistHelp: '輸入共用密碼以存取你的私人股票池。', passcode: '密碼', unlockPrivateWatchlist: '解鎖私人自選清單', checkingPasscode: '正在驗證密碼...', logout: '登出', sharedWatchlistDescription: '供私人協作使用的共用股票池；成員資格會共用，而每部裝置的分析依然保持快速。',
    unableToLoadPrivateWatchlist: '無法載入私人自選清單', unableToAuthenticate: '無法驗證身分', unableToLogout: '無法登出', unableToUpdateWatchlist: '無法更新共用自選清單',
    stop: '停止', added: '已加入 ✓', addToWatchlist: '加入自選清單', analysisStopped: '分析已停止', requestCancelled: '請求已取消', runAgain: '重新執行', enterSymbol: '在上方輸入股票代號開始。',
    signals: '訊號', showSignals: '顯示訊號', hideSignals: '隱藏訊號', dimension: '範疇', note: '說明', fundamentals: '基本因素', sentiment: '市場情緒', currentPrice: '現價', idealBuyZone: '理想買入區間', fibGoldenPocket: '費波那契黃金區間', conservativeEntry: '保守入場價', stopLoss: '止蝕價', invalidation: '失效位', highConvictionZone: '高信心區間', signalVote: '訊號投票', nextFomc: '下次 FOMC', rateCutProbability: '減息機率', resistance: '阻力位', support: '支持位', breakoutBuyLevel: '突破買入位', weight: '權重',
    fetchPriceData: '取得價格資料', computeTechnicals: '計算技術指標', loadFundamentals: '載入基本因素', assembleSignals: '整合訊號', buildConfluence: '建立共振區間', loadingAnalysis: '正在載入分析', analyzing: '分析中', entryStructureUnavailable: '這次回應沒有可用的入場結構。',
    epsSurprise: '每股盈利驚喜', peRatio: '市盈率', pePercentile: '市盈率百分位（5 年）', fcfTrend: '自由現金流趨勢', analystUpgrades: '分析師調升（30 日）', analystDowngrades: '分析師調降（30 日）', revenueGrowth: '收入按年增長', grossMargin: '毛利率', pbRatio: '市賬率', psRatio: '市銷率', evEbitda: '企業價值／EBITDA', asOfDate: '資料截止日', putCallRatio: '認沽／認購比率', ivRank: '隱含波動率排名（約）', shortInterest: '沽空比率', redditMentions: 'Reddit 提及次數', redditSentiment: 'Reddit 情緒', volumeSpike: '成交量對比 90 日平均', priceVolumeMomentum: '價量動能', institutional13f: '機構 13F', freshness: '資料新鮮度',
    conflict: '衝突', categoryVotes: '分類投票', categoryVotesHint: '建議結果背後按分類加權的買入／持有／賣出票數。',
    technical: '技術面', fundamental: '基本因素', macro: '宏觀面',
    supportingAnalysisAgrees: '輔助分析一致', supportingAnalysisDisagrees: '輔助分析分歧', percentSupport: '{percent}% 支持',
    supportingContextHint: '基本因素、市場情緒與宏觀面分別評分，均不會改變上方的技術面操作。',
    technicalByHorizon: '各時間跨度技術面', technicalByHorizonHint: '每個時間跨度獨立給出，從不取平均——刻意不給出總體操作。',
    noPriceLandscape: '沒有可用的價格區間——引擎未給出區間。', opportunity: '機會區', reduce: '減倉區',
    percentConfidence: '{percent}% 信心度', data: '資料',
    priceStateInOpportunity: '機會區內', priceStateNearOpportunity: '接近機會區', priceStateNeutral: '中性區', priceStateNearReduce: '接近減倉區', priceStateInReduce: '減倉區內', priceStateBeyondReduce: '超出減倉區', priceStateBreakdown: '破位', priceStateInvalidLandscape: '區間失效',
    dataQualitySourceUnavailable: '資料來源不可用', dataQualityInvalidSource: '資料來源無效',
    technicalDetails: '技術細節', movingAverages: '均線', relativeStrength: '相對強度', fibonacci: '費波那契',
    marketStructure: '市場結構', relativeVolume: '相對成交量', fiftyTwoWeekRange: '52 週區間', distanceToHigh: '距高點', distanceToLow: '距低點',
    finalDecision: '最終決策', finalDecisionHint: '以 Vincent 的技術面操作為主。Ryan 的基本因素只能調低中線或長線的買入。買入亦必須跑贏下方每一個基準。',
    consolidatedInputs: '輸入 · 4 小時 {fourHour} · 1 小時 {oneHour} · 市場 {market}%', technicalAction: '技術面', finalAction: '最終',
    consolidatedDecisionUnavailable: '未能載入 — 未能載入市場數據（{reason}）',
    actionStrongBuy: '強烈買入', actionBuy: '買入', actionAccumulate: '分批吸納', actionHold: '持有', actionTrim: '減持', actionSell: '沽出', actionAvoid: '迴避',
    reasonFundamentalsWeak: '基本因素偏弱，調低一級', reasonIndexHurdleFailed: '預計跑不贏 {benchmarks}',
    reasonIndexHurdleUnavailable: '無法計算指數門檻，買入改為持有', reasonTechnicalUnavailable: '此時間跨度的技術引擎不可用',
    reasonEarningsGuard: '每股盈利遜於預期，而且分析師轉為看淡',
    fundamentalsStance: '基本因素 {stance}', stanceSupportive: '支持', stanceNeutral: '中性', stanceWeak: '偏弱', stanceUnavailable: '不可用', fundamentalsNotApplied: '不適用於短線',
    indexHurdle: '指數門檻', indexHurdleHint: '未來 12 個月。買入必須有證據顯示能跑贏每一個基準。以下為歷史相對回報，並非預測。',
    hurdlePass: '通過', hurdleFail: '未通過', hurdleNotApplicable: '不適用（指數基金）', hurdleUnavailable: '不可用',
    hurdleBenchmark: '基準', hurdleRole: '類別', hurdleRel121: '12-1 個月相對', hurdleRel6m: '6 個月相對', hurdleTrend: '比率高於 200 日線', hurdleResult: '結果', hurdleChecks: '通過項',
    hurdleRuleExplanation: '一個基準被視為跑贏，需符合以下 3 項中至少 2 項：12-1 個月相對回報、6 個月相對回報、比率高於其 200 日線。股票必須跑贏每一個基準。',
    hurdleRoleIndex: '指數', hurdleRoleSector: '行業', hurdleRoleIndustry: '細分行業', hurdleRoleLocalIndex: '本地指數',
    hurdleBeats: '跑贏', hurdleLags: '落後', hurdleMixed: '好壞參半', hurdleInsufficient: '資料不足',
    earningsGuardLabel: '盈利警示', guardClear: '無', guardFired: '已觸發', guardUnavailable: '資料不足',
    horizonShort: '短線', horizonMid: '中線', horizonLong: '長線', horizonShortWindow: '1–30 日', horizonMidWindow: '1–6 個月', horizonLongWindow: '> 6 個月',
    decisionBoard: '決策看板',
    decisionBoardEmpty: '暫無可顯示的代碼。', decisionBoardLoading: '載入中…', decisionBoardRowError: '無法載入 {symbol}：{message}',
    technicalRejectedTitle: '外部技術裁決不符合 decision.v1，因此改用本地技術指標。',
    technicalRejected: '外部技術裁決被拒', localTechnicalsTitle: '未提供外部技術裁決，因此使用本地技術指標。',
    localTechnicals: '本地技術指標', bothEnginesAgree: '兩個引擎一致', enginesDisagree: '引擎分歧——本地判定為 {direction}',
    noLocalToCompare: '沒有本地技術判定可供比較', technicalSuppliedBy: '技術層由 {producer} 提供', technicalsLabel: '技術面', unknownDirection: '未知',
    trackRecord: '往績記錄',
    trackRecordTitle: '我們說過什麼，結果如何',
    trackRecordDescription: '過往判斷按實際價格評分。覆蓋範圍免費載入；評分時每隻股票呼叫一次價格資料來源。',
    coverageRecords: '記錄數', coverageSymbols: '股票數', coverageRange: '時間範圍',
    noTrackRecord: '暫無記錄。分析在足夠久之後才會在此評分。',
    symbolTimeline: '股票歷史', loadTimeline: '載入', noCallsForSymbol: '沒有 {symbol} 的記錄。',
    priceAtCall: '判斷時價格', targetWindow: '目標窗口', hit: '命中', when: '日期', skippedLabel: '未評分',
    performance: '整體表現', loadPerformance: '載入報告', hitRate: '命中率', evaluatedCount: '已評分', decisionCount: '方向性判斷',
    avgForwardReturn: '平均後續回報', avgVsBenchmark: '相對基準平均', advisoryLabel: '提示',
    byDirection: '按方向', byConfidence: '按信心度', byEntryAssessment: '按入場時機',
  },
} as const

export type MessageKey = keyof typeof messages.en

type I18nValue = {
  locale: Locale
  setLocale: (locale: Locale) => void
  t: (key: MessageKey, values?: Record<string, string | number>) => string
}

const I18nContext = createContext<I18nValue | null>(null)
const LOCALE_STORAGE_KEY = 'finance-monorepo.locale'

/** BCP-47 value for <html lang>. zh-Hans has no region; zh-Hant-HK carries one. */
const HTML_LANG: Record<Locale, string> = {
  en: 'en',
  'zh-Hans': 'zh-Hans',
  'zh-Hant-HK': 'zh-Hant-HK',
}

function detectLocale(): Locale {
  const candidates = typeof navigator === 'undefined' ? [] : navigator.languages ?? [navigator.language]
  for (const raw of candidates) {
    const tag = String(raw ?? '').toLowerCase()
    if (!tag.startsWith('zh') && !tag.startsWith('yue')) continue
    // Script subtag wins over region, since zh-Hans-HK is a real combination.
    if (tag.includes('hans')) return 'zh-Hans'
    if (tag.includes('hant')) return 'zh-Hant-HK'
    // Cantonese speakers get the formal Traditional locale: the colloquial
    // Cantonese locale was removed, and Traditional is the closer fit.
    if (tag.startsWith('yue') || /\b(hk|mo|tw)\b/.test(tag)) return 'zh-Hant-HK'
    return 'zh-Hans'
  }
  return 'en'
}

function getInitialLocale(): Locale {
  let stored: string | null = null
  try {
    stored = localStorage.getItem(LOCALE_STORAGE_KEY)
  } catch {
    // Private browsing or blocked storage: fall through to detection.
  }
  if (stored === 'zh-Hans' || stored === 'zh-Hant-HK' || stored === 'en') return stored
  // Migrate anyone left on the removed Cantonese locale, and the older bare
  // zh-Hant value, onto formal Traditional rather than resetting them to English.
  if (stored === 'zh-HK' || stored === 'zh-Hant' || stored === 'yue-Hant-HK') return 'zh-Hant-HK'
  if (stored === 'zh-CN') return 'zh-Hans'
  return detectLocale()
}

function formatMessage(message: string, values?: Record<string, string | number>): string {
  return message.replace(/\{(\w+)\}/g, (_, key: string) => String(values?.[key] ?? `{${key}}`))
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(getInitialLocale)

  useEffect(() => {
    try {
      localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    } catch {
      // Storage can be unavailable; the app still works for this session.
    }
    document.documentElement.lang = HTML_LANG[locale]
  }, [locale])

  const value = useMemo<I18nValue>(() => ({
    locale,
    setLocale,
    t: (key, values) => formatMessage(messages[locale][key], values),
  }), [locale])

  return <I18nContext.Provider value={value}>{children}</I18nContext.Provider>
}

// This hook is intentionally colocated with its provider; it does not affect Fast Refresh behavior.
// eslint-disable-next-line react-refresh/only-export-components
export function useI18n(): I18nValue {
  const value = useContext(I18nContext)
  if (!value) {
    throw new Error('useI18n must be used inside I18nProvider')
  }
  return value
}
