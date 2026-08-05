import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react'

export type Locale = 'en' | 'zh-HK'

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
    switchLanguage: 'Switch to Hong Kong Cantonese',
    localeButton: '粵',
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
  'zh-HK': {
    appTitle: '市場分析工作台',
    appDescription: '集中做市場分析、實證研究、篩選同服務狀態檢查嘅工作台。',
    analyze: '分析', screener: '篩選器', research: '研究', health: '系統狀態', watchlist: '自選清單',
    add: '加入', addSymbol: '加個股票代號，開始整你嘅簡單自選清單。', symbol: '股票代號', removeSymbol: '移除 {symbol}',
    neverRun: '未做過', stale: '過咗期', justNow: '啱啱', minutesAgo: '{count} 分鐘前', hoursAgo: '{count} 個鐘前', daysAgo: '{count} 日前',
    switchLanguage: 'Switch to English', localeButton: 'EN', switchTheme: '切換去{theme}模式', light: '淺色', dark: '深色', system: '跟系統',
    screenerTitle: '按策略睇即時篩選結果', screenerDescription: '瀏覽器會按實際 POST 合約直接呼叫端點。',
    undervalued: '估值偏低', demandShock: '需求衝擊', trending: '趨勢中', run: '執行{screen}', running: '執行緊...', loadingResults: '載入緊結果...',
    runScreenHint: '執行呢個篩選器去載入結果。', universe: '股票範圍', regime: '市況', quality: '質素', score: '分數', direction: '方向',
    confidence: '信心', entryAssessment: '入場評估', dataQuality: '資料質素', actions: '操作',
    healthTitle: '服務狀態', lastChecked: '最後檢查：{time} · 每 30 秒自動更新', refresh: '重新整理', healthy: '正常', down: '未能運作', core: '核心', dataProviders: '資料供應商', checking: '檢查緊…', status: '狀態', configValid: '設定有效', cache: '快取', languageModel: '語言模型', available: '可用', unavailable: '唔可用', unreachable: '連唔到', evidence: '證據', job: '工作', analyst: '分析服務',
    researchLab: '研究室', evidenceBeforeConviction: '先睇證據，再作判斷', researchDescription: '搵出排好序嘅候選公司、催化因素、風險、入場條件、避開原因，同埋有證據支持嘅後續工作。研究結果只作決策參考，唔保證回報，亦唔係個人化資產配置建議。',
    question: '問題', universeLabel: '股票範圍', triggerContext: '觸發原因', mode: '模式', candidates: '候選數目', optionalTrigger: '可選：因為持倉太集中嘅提示，而重新檢視現有持倉。',
    upsideDiscovery: '上升機會探索', downsideRiskScan: '向下風險掃描', runResearch: '執行研究', starting: '開始緊…', cancel: '取消',
    usCommon: '喺美國上市嘅普通股', usCommonAbove10b: '市值超過 100 億美元、喺美國上市嘅普通股', sp500: '標普 500 指數成分股', nasdaq100: '納斯達克 100 指數成分股', russell1000: '羅素 1000 指數成分股', russell2000: '羅素 2000 指數成分股', dowJones: '道瓊斯工業平均指數成分股',
    noSupportedItems: '冇可支持嘅項目。', rank: '排名', decisionSupport: '決策參考', analogyComparison: '類比比較', thesis: '投資理據', catalysts: '催化因素', risks: '風險', entryConditions: '入場條件', reasonsToAvoid: '避開原因', reviewRisk: '審核風險', unknowns: '未知事項', sources: '資料來源', noSources: '冇返到資料來源。',
    privateWatchlist: '私人自選清單', loadingPrivateWatchlist: '載入緊私人自選清單...', privateWatchlistHelp: '輸入共用密碼，開啟你嘅私人股票池。', passcode: '密碼', unlockPrivateWatchlist: '開啟私人自選清單', checkingPasscode: '驗證緊密碼...', logout: '登出', sharedWatchlistDescription: '俾私人協作用嘅共享股票池；成員資格會同步，而每部裝置都可以快速分析。',
    unableToLoadPrivateWatchlist: '載入唔到私人自選清單', unableToAuthenticate: '驗證唔到身分', unableToLogout: '登出唔到', unableToUpdateWatchlist: '更新唔到共享自選清單',
    stop: '停止', added: '已加 ✓', addToWatchlist: '加入自選清單', analysisStopped: '已停止分析', requestCancelled: '請求已取消', runAgain: '再試', enterSymbol: '喺上面輸入股票代號開始。',
    signals: '訊號', showSignals: '顯示訊號', hideSignals: '收埋訊號', dimension: '範疇', note: '說明', fundamentals: '基本因素', sentiment: '市場情緒', currentPrice: '現價', idealBuyZone: '理想買入區', fibGoldenPocket: '費波那契黃金區', conservativeEntry: '保守入場價', stopLoss: '止蝕價', invalidation: '失效位', highConvictionZone: '高信心區', signalVote: '訊號票數', nextFomc: '下次 FOMC', rateCutProbability: '減息機率', resistance: '阻力位', support: '支持位', breakoutBuyLevel: '突破買入位', weight: '權重',
    fetchPriceData: '攞價格資料', computeTechnicals: '計技術指標', loadFundamentals: '載入基本因素', assembleSignals: '整合訊號', buildConfluence: '建立共識', loadingAnalysis: '載入緊分析', analyzing: '分析緊', entryStructureUnavailable: '呢個回應冇可用嘅入場結構。',
    epsSurprise: '每股盈利驚喜', peRatio: '市盈率', pePercentile: '市盈率百分位（5 年）', fcfTrend: '自由現金流趨勢', analystUpgrades: '分析師調升（30 日）', analystDowngrades: '分析師調降（30 日）', revenueGrowth: '收入按年增長', grossMargin: '毛利率', pbRatio: '市賬率', psRatio: '市銷率', evEbitda: '企業價值／EBITDA', asOfDate: '資料截止日', putCallRatio: '認沽／認購比率', ivRank: '隱含波動率排名（約）', shortInterest: '沽空比率', redditMentions: 'Reddit 提及次數', redditSentiment: 'Reddit 情緒', institutional13f: '機構 13F', freshness: '資料新鮮度',
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
  return stored === 'zh-HK' || stored === 'zh-Hant' ? 'zh-HK' : 'en'
}

function formatMessage(message: string, values?: Record<string, string | number>): string {
  return message.replace(/\{(\w+)\}/g, (_, key: string) => String(values?.[key] ?? `{${key}}`))
}

export function I18nProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(getInitialLocale)

  useEffect(() => {
    localStorage.setItem(LOCALE_STORAGE_KEY, locale)
    document.documentElement.lang = locale
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
