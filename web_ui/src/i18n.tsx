import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Locale = 'en' | 'zh-Hant'

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
    switchLanguage: '切換為繁體中文',
    localeButton: '繁',
    switchTheme: 'Switch to {theme} mode',
    light: 'light', dark: 'dark', system: 'system',
    screenerTitle: 'Live screen results by strategy',
    screenerDescription: "Endpoints are called directly from the browser with the repo's actual POST contracts.",
    undervalued: 'Undervalued', demandShock: 'Demand Shock', trending: 'Trending',
    run: 'Run {screen}', running: 'Running...', loadingResults: 'Loading results...',
    runScreenHint: 'Run this screen to load results.', universe: 'Universe', regime: 'Regime', quality: 'Quality',
    score: 'Score', direction: 'Direction', confidence: 'Confidence', entryAssessment: 'Entry Assessment',
    dataQuality: 'Data Quality', actions: 'Actions',
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
    putCallRatio: 'Put/call ratio', ivRank: 'IV rank (approx)', shortInterest: 'Short interest', redditMentions: 'Reddit mentions',
    redditSentiment: 'Reddit sentiment', institutional13f: 'Institutional 13F', freshness: 'Freshness',
  },
  'zh-Hant': {
    appTitle: '市場分析主控台',
    appDescription: '專注於市場分析、實證研究、篩選與服務健康狀態的工作台。',
    analyze: '分析', screener: '篩選器', research: '研究', health: '健康狀態', watchlist: '自選清單',
    add: '加入', addSymbol: '加入股票代號以建立輕量自選清單。', symbol: '股票代號', removeSymbol: '移除 {symbol}',
    neverRun: '尚未執行', stale: '已過期', justNow: '剛剛', minutesAgo: '{count} 分鐘前', hoursAgo: '{count} 小時前', daysAgo: '{count} 天前',
    switchLanguage: 'Switch to English', localeButton: 'EN', switchTheme: '切換至{theme}模式', light: '淺色', dark: '深色', system: '系統',
    screenerTitle: '依策略顯示即時篩選結果', screenerDescription: '端點會直接由瀏覽器依照實際 POST 合約呼叫。',
    undervalued: '價值低估', demandShock: '需求衝擊', trending: '熱門趨勢', run: '執行{screen}', running: '執行中...', loadingResults: '正在載入結果...',
    runScreenHint: '執行此篩選器以載入結果。', universe: '股票池', regime: '市場狀態', quality: '品質', score: '分數', direction: '方向',
    confidence: '信心度', entryAssessment: '進場評估', dataQuality: '資料品質', actions: '操作',
    healthTitle: '服務心跳狀態', lastChecked: '最後檢查：{time} · 每 30 秒自動更新', refresh: '重新整理', healthy: '正常', down: '異常', core: '核心', dataProviders: '資料供應商', checking: '檢查中…', status: '狀態', configValid: '設定有效', cache: '快取', languageModel: '語言模型', available: '可用', unavailable: '不可用', unreachable: '無法連線', evidence: '佐證', job: '工作', analyst: '分析服務',
    researchLab: '研究實驗室', evidenceBeforeConviction: '先有證據，再談信念', researchDescription: '取得排序後的候選公司、催化因素、風險、進場條件、避開理由與可驗證的後續工作。研究結果僅供決策支援，不保證報酬，也不是個人化配置建議。',
    question: '問題', universeLabel: '股票池', triggerContext: '觸發背景', mode: '模式', candidates: '候選數量', optionalTrigger: '選填：因持倉集中度警示而進行既有持倉檢視。',
    upsideDiscovery: '上行機會探索', downsideRiskScan: '下行風險掃描', runResearch: '執行研究', starting: '啟動中…', cancel: '取消',
    usCommon: '美國上市普通股', usCommonAbove10b: '市值高於 100 億美元的美國上市普通股', sp500: '標普 500 成分股', nasdaq100: '那斯達克 100 成分股', russell1000: '羅素 1000 成分股', russell2000: '羅素 2000 成分股', dowJones: '道瓊工業平均指數成分股',
    noSupportedItems: '沒有可佐證的項目。', rank: '排名', decisionSupport: '決策支援', analogyComparison: '類比比較', thesis: '投資論點', catalysts: '催化因素', risks: '風險', entryConditions: '進場條件', reasonsToAvoid: '避開理由', reviewRisk: '審查風險', unknowns: '未知事項', sources: '來源', noSources: '沒有回傳來源。',
    privateWatchlist: '私人自選清單', loadingPrivateWatchlist: '正在載入私人自選清單...', privateWatchlistHelp: '輸入共享密碼以存取你的私人股票池。', passcode: '密碼', unlockPrivateWatchlist: '解鎖私人自選清單', checkingPasscode: '正在驗證密碼...', logout: '登出', sharedWatchlistDescription: '供私人協作使用的共享股票池；成員資格會同步，各裝置仍可快速完成分析。',
    unableToLoadPrivateWatchlist: '無法載入私人自選清單', unableToAuthenticate: '無法驗證身分', unableToLogout: '無法登出', unableToUpdateWatchlist: '無法更新共享自選清單',
    stop: '停止', added: '已加入 ✓', addToWatchlist: '加入自選清單', analysisStopped: '分析已停止', requestCancelled: '請求已取消', runAgain: '再次執行', enterSymbol: '在上方輸入股票代號以開始。',
    signals: '訊號', showSignals: '顯示訊號', hideSignals: '隱藏訊號', dimension: '面向', note: '說明', fundamentals: '基本面', sentiment: '市場情緒', currentPrice: '目前價格', idealBuyZone: '理想買入區間', fibGoldenPocket: '費波那契黃金區', conservativeEntry: '保守進場價', stopLoss: '停損價', invalidation: '失效價位', highConvictionZone: '高信心區間', signalVote: '訊號票數', nextFomc: '下次 FOMC', rateCutProbability: '降息機率', resistance: '壓力位', support: '支撐位', breakoutBuyLevel: '突破買入價位', weight: '權重',
    fetchPriceData: '取得價格資料', computeTechnicals: '計算技術指標', loadFundamentals: '載入基本面', assembleSignals: '彙整訊號', buildConfluence: '建立共識', loadingAnalysis: '正在載入分析', analyzing: '分析中', entryStructureUnavailable: '此回應沒有可用的進場結構。',
    epsSurprise: '每股盈餘意外值', peRatio: '本益比', pePercentile: '本益比分位數（5 年）', fcfTrend: '自由現金流趨勢', analystUpgrades: '分析師調升（30 日）', analystDowngrades: '分析師調降（30 日）', revenueGrowth: '營收年增率', grossMargin: '毛利率', pbRatio: '股價淨值比', psRatio: '股價營收比', evEbitda: '企業價值／EBITDA', asOfDate: '資料截至日', putCallRatio: '賣權／買權比', ivRank: '隱含波動率排名（約）', shortInterest: '放空比率', redditMentions: 'Reddit 提及量', redditSentiment: 'Reddit 情緒', institutional13f: '機構 13F', freshness: '新鮮度',
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

function getInitialLocale(): Locale {
  const stored = localStorage.getItem(LOCALE_STORAGE_KEY)
  return stored === 'zh-Hant' ? 'zh-Hant' : 'en'
}

function formatMessage(message: string, values?: Record<string, string | number>): string {
  return message.replace(/\{(\w+)\}/g, (_, key: string) => String(values?.[key] ?? `{${key}}`))
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(getInitialLocale)

  useEffect(() => {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    document.documentElement.lang = locale === 'zh-Hant' ? 'zh-Hant' : 'en'
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
