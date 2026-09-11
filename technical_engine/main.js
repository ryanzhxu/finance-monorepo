"use strict";

const API_BASE = window.location.protocol === "file:" ? "http://127.0.0.1:4173" : window.location.origin;
const API_URL = `${API_BASE}/api/market-data`;
const WATCHLIST_API_URL = `${API_BASE}/api/watchlist`;
const SYMBOL_SEARCH_API_URL = `${API_BASE}/api/symbol-search`;
const LANGUAGE_CACHE_KEY = "stock-dashboard-language-v2";
const SNAPSHOT_CACHE_KEY = "stock-dashboard-market-cache-v11-decision-engine";
const WATCHLIST_CACHE_KEY = "stock-dashboard-watchlist-v2";
const LAST_REFRESH_CACHE_KEY = "stock-dashboard-last-refresh-v1";
const REFRESH_MS = 60 * 60 * 1000;
const EASTERN_REFRESH_FORMATTER = new Intl.DateTimeFormat("en-CA", {
  timeZone: "America/New_York",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  hourCycle: "h23",
});

const DEFAULT_WATCHLIST = ["NVDA", "TSLA", "AMD", "BABA", "GOOGL", "AMZN", "AAPL", "META", "MSFT", "QQQ"];
const I18N = {
  en: {
    appTitle: "Stock Decision Dashboard", stocks: "Stocks", search: "Search symbol or name", add: "Add selected", refresh: "Refresh now", refreshing: "Refreshing…", lastRefresh: "Last refresh",
    shared: "Shared Watchlist: everyone viewing this Dashboard sees the same stock list.", syncFailed: "Shared list sync failed. Showing cached data.",
    all: "All", ticker: "Ticker", type: "Stock type", dayMove: "Day move", short: "Short", mid: "Mid", long: "Long",
    aiDecision: "AI Decision", technical: "Technical", market: "Market Data", price: "Price", updated: "Updated", unavailable: "—",
    recommendation: "Action", confidence: "Confidence", invalidation: "Invalidation", currentPrice: "Current Price",
    recommendationConfidence: "Recommendation Confidence", confidenceHelp: "Recommendation Confidence measures the consistency and stability of support for this action. It is not a probability of future price appreciation.",
    recommendedBuyAddRange: "Recommended Buy / Add Range", potentialAddRange: "Potential Add Range", reevaluationRange: "Re-evaluation Range", potentialReduceRange: "Potential Reduce Range", recommendedReduceRange: "Recommended Reduce Range", recommendedExitRange: "Recommended Exit Range", riskInvalidation: "Risk / Invalidation", avoidNoEntry: "Avoid / No Entry", currentPrice: "Current Price", withinRange: "Currently in this range", distanceToRange: "Distance",
    finalDecision: "Final Decision", decisionCardHint: "Select a horizon card to view its price map, decision drivers, and execution plan.", decisionPriceMap: "Price Landscape", whyThisDecision: "Why This Decision", executionPlan: "Execution Plan", positionGuidance: "Position Guidance", marketRiskRegime: "Market Risk Regime", marketImpact: "Impact on this stock", companyModel: "Company Model", primaryClassification: "Primary Classification", companyTraits: "Company Traits", lifecycle: "Lifecycle", profileConfidence: "Profile Confidence", lastReview: "Last Profile Review", appliedModifiers: "Applied Modifiers", etfProfile: "ETF Profile", leveraged: "Leveraged", direction: "Direction", underlying: "Underlying", yes: "Yes", no: "No", longDirection: "Long", inverseDirection: "Inverse", noDecision: "Insufficient data to generate a recommendation for this horizon.",
    shortHorizon: "1–30 Days", midHorizon: "1–6 Months", longHorizon: ">6 Months", support: "Supporting evidence", limiting: "Limiting evidence", regime: "Regime", earningsProximity: "Earnings proximity", nextEarnings: "Next Earnings", daysAgo: "days ago", days: "days", supportive: "Supportive", neutral: "Neutral", restrictive: "Restrictive", shockSensitive: "Shock-sensitive",
    technicalOverview: "Technical Overview", fibonacciStructure: "Fibonacci Structure", fibonacciDescription: "Confirmed swing anchors and retracement / extension levels. Technical display data only.", historicalVolume: "52-Week / Historical Position and Volume", advancedSwingMetadata: "Advanced Swing Metadata", retracement: "Retracement", extension: "Extension", level: "Level", distance: "Distance", swingHigh: "Swing High", swingLow: "Swing Low", swingRange: "Swing Range", currentPosition: "Current Position", nearestBelow: "Nearest Below", nearestAbove: "Nearest Above", sourceTimeframe: "Source timeframe", lookbackBars: "Lookback bars", fallbackUsed: "Fallback used", fallbackReason: "Fallback reason", technicalUnavailable: "Technical data is currently unavailable.",
    trendSummary: "Trend", momentumSummary: "Momentum", volatilitySummary: "Volatility", relativeStrengthSummary: "Relative Strength", participationSummary: "Participation", marketStatus: "Market Status", current: "Current", change5d: "5D Change", change20d: "20D Change", expanded: "Expanded", collapsed: "Collapsed", primaryInterval: "Primary interval", supportingIntervals: "Supporting intervals shown where available.",
    supporting: "Supporting evidence", limiting: "Limiting evidence", marketState: "Market state",
    technicalData: "Canonical Technical Data", dataStatus: "Data status", trend: "Trend", momentum: "Momentum", volatility: "Volatility", participation: "Participation",
    close: "Close", remove: "Remove", risk: "Risk", opportunity: "Price opportunity", confirmation: "Confirmation", direction: "Direction",
    noData: "Waiting for market data. No action is shown until the technical feature set is available.",
  },
  zh: {
    appTitle: "股票决策仪表盘", stocks: "股票", search: "搜索代码或名称", add: "添加所选", refresh: "立即刷新", refreshing: "刷新中…", lastRefresh: "上次刷新",
    shared: "共享自选列表：所有查看此仪表盘的用户看到相同的股票列表。", syncFailed: "共享列表同步失败，正在显示缓存数据。",
    all: "全部", ticker: "代码", type: "股票类型", dayMove: "当日涨跌", short: "短期", mid: "中期", long: "长期",
    aiDecision: "AI 决策", technical: "技术面", market: "市场数据", price: "价格", updated: "更新时间", unavailable: "—",
    recommendation: "操作", confidence: "置信度", invalidation: "失效价", currentPrice: "当前价格",
    recommendationConfidence: "推荐可信度", confidenceHelp: "推荐可信度表示当前数据对该操作建议的支持一致性和稳定程度，不代表未来上涨概率。", recommendedBuyAddRange: "推荐买入／加仓区", potentialAddRange: "潜在加仓区", reevaluationRange: "重新评估区", potentialReduceRange: "潜在减仓区", recommendedReduceRange: "推荐减仓区", recommendedExitRange: "推荐退出区", riskInvalidation: "风险／失效位", avoidNoEntry: "回避／不建立新仓", currentPrice: "当前价格", withinRange: "当前位于区间内", distanceToRange: "距离",
    finalDecision: "最终决策", decisionCardHint: "点击周期卡片查看对应的价格图、决策原因和执行计划。", decisionPriceMap: "价格区间图", whyThisDecision: "为什么是这个决策", executionPlan: "执行计划", positionGuidance: "仓位指引", marketRiskRegime: "市场风险环境", marketImpact: "对该股票的影响", companyModel: "公司模型", primaryClassification: "主要分类", companyTraits: "公司特征标签", lifecycle: "生命周期", profileConfidence: "画像可信度", lastReview: "最近画像复核", appliedModifiers: "已应用修饰器", etfProfile: "ETF 画像", leveraged: "杠杆", direction: "方向", underlying: "标的", yes: "是", no: "否", longDirection: "做多", inverseDirection: "反向", noDecision: "数据不足，暂无法生成该周期推荐。", shortHorizon: "1–30 天", midHorizon: "1–6 个月", longHorizon: ">6 个月", support: "支持当前推荐", limiting: "限制当前推荐", regime: "风险环境", earningsProximity: "财报临近", nextEarnings: "下一次财报", daysAgo: "天前", days: "天", supportive: "支持", neutral: "中性", restrictive: "限制", shockSensitive: "对冲击敏感",
    technicalOverview: "技术概览", fibonacciStructure: "斐波那契结构", fibonacciDescription: "已确认的摆动锚点与回撤／扩展水平；仅作技术数据展示。", historicalVolume: "52 周／历史位置与成交量", advancedSwingMetadata: "高级摆动元数据", retracement: "回撤", extension: "扩展", level: "级别", distance: "距离", swingHigh: "摆动高点", swingLow: "摆动低点", swingRange: "摆动区间", currentPosition: "当前位置", nearestBelow: "最近下方水平", nearestAbove: "最近上方水平", sourceTimeframe: "来源周期", lookbackBars: "回看 K 线数", fallbackUsed: "已使用回退", fallbackReason: "回退原因", primaryClassification: "主要分类", technicalUnavailable: "技术数据暂不可用。", trendSummary: "趋势", momentumSummary: "动量", volatilitySummary: "波动", relativeStrengthSummary: "相对强弱", participationSummary: "参与度", marketStatus: "市场状态", current: "当前", change5d: "5 日变化", change20d: "20 日变化", expanded: "展开", collapsed: "收起", primaryInterval: "主周期", supportingIntervals: "支持周期会在可用时显示。",
    supporting: "支持证据", limiting: "限制因素", marketState: "市场状态",
    technicalData: "标准化技术数据", dataStatus: "数据状态", trend: "趋势", momentum: "动量", volatility: "波动", participation: "参与度",
    close: "关闭", remove: "移除", risk: "风险", opportunity: "价格机会", confirmation: "确认度", direction: "方向",
    noData: "正在等待市场数据；技术特征可用前不显示操作建议。",
  },
};

const state = {
  language: localStorage.getItem(LANGUAGE_CACHE_KEY) === "zh" ? "zh" : "en",
  watchlist: [],
  rows: [],
  snapshot: null,
  selectedTicker: null,
  modalOpen: false,
  activeTab: "summary",
  decisionHorizon: "short",
  technicalHorizon: "short",
  fibonacciHorizon: "short",
  technicalSections: { fibonacci: false, foundation: false },
  sort: { key: "ticker", direction: "asc" },
  marketFilter: "all",
  selectedCandidate: null,
  refreshing: false,
  refreshPhase: "idle",
  refreshPromise: null,
  refreshGeneration: 0,
  lastRefreshAt: localStorage.getItem(LAST_REFRESH_CACHE_KEY) || null,
  lastAppliedAt: null,
};

const $ = (selector) => document.querySelector(selector);
const t = (key) => I18N[state.language][key] || I18N.en[key] || key;
const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
const escapeHtml = (value) => String(value ?? "").replace(/[&<>'"]/g, (character) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character]);
const normalizeTicker = (value) => String(value || "").trim().toUpperCase().replace(/\s+/g, "");
const uniqueTickers = (values) => [...new Set(values.map(normalizeTicker).filter(Boolean))];
const actionTone = (action) => window.DecisionPresentation?.actionTone?.[action] || "hold";

function formatPrice(value, currency = "USD") {
  return Number.isFinite(value) ? new Intl.NumberFormat(state.language === "zh" ? "zh-CN" : "en-US", { style: "currency", currency, maximumFractionDigits: value < 10 ? 3 : 2 }).format(value) : t("unavailable");
}

function formatPct(value, decimals = 1) {
  return Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${value.toFixed(decimals)}%` : t("unavailable");
}

function formatRange(range, currency) {
  return Number.isFinite(range?.low) && Number.isFinite(range?.high) ? `${formatPrice(range.low, currency)} – ${formatPrice(range.high, currency)}` : t("unavailable");
}

function formatDate(value) {
  if (!value) return t("unavailable");
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? t("unavailable") : date.toLocaleString(state.language === "zh" ? "zh-CN" : "en-US", { dateStyle: "medium", timeStyle: "short" });
}

function formatRefreshTime(value) {
  const date = new Date(value);
  if (!value || Number.isNaN(date.getTime())) return t("unavailable");
  const parts = Object.fromEntries(
    EASTERN_REFRESH_FORMATTER.formatToParts(date)
      .filter((part) => part.type !== "literal")
      .map((part) => [part.type, part.value]),
  );
  // The IANA time zone keeps this display correct for both EST and EDT. "ET"
  // deliberately avoids claiming a fixed UTC offset during daylight saving.
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ET`;
}

function snapshotRefreshTime(snapshot) {
  const status = snapshot?.refresh_status || {};
  // Prefer the server's dashboard-wide data freshness. It remains truthful
  // when a successful force refresh applies an allowed cache fallback.
  return status.last_dashboard_refresh
    || status.last_successful_cache_update_at
    || status.last_any_successful_ticker_refresh_at
    || snapshot?.updatedAt
    || snapshot?.fetchedAt
    || null;
}

function persistLastRefresh(value) {
  if (!value) return;
  try { localStorage.setItem(LAST_REFRESH_CACHE_KEY, value); } catch { /* storage is optional */ }
}

function hasUsableSnapshot(snapshot) {
  if (snapshot?.success === true) return true;
  return Object.values(snapshot?.quotes || {}).some((quote) => Number.isFinite(Number(quote?.price)));
}

function afterBrowserPaint() {
  // Two frames ensure the render triggered by applySnapshot has been committed
  // before the loading state is cleared. This is not a time-based delay.
  return new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
}

function profileFor(ticker, quote = {}) {
  const defined = window.ProfileDefinitions?.profileFor?.(ticker, quote.metadata || quote) || {};
  const upstream = quote.metadata?.classification || quote.classification || {};
  if (defined.isETF || defined.type === "etf") return { ...defined };
  return {
    ...defined,
    primaryClassification: upstream.primaryClassification || upstream.primary_classification || defined.primaryClassification || quote.metadata?.industry || quote.metadata?.sector || "Unclassified Equity",
    companyTraits: [...new Set([...(defined.companyTraits || []), ...(upstream.companyTraits || upstream.company_traits || [])])],
    lifecycle: upstream.lifecycle || defined.lifecycle || null,
    scoringProfile: upstream.scoringProfile || upstream.scoring_profile || defined.scoringProfile || "generic",
  };
}

function returnPct(closes, lookback) {
  const values = (Array.isArray(closes) ? closes : []).map(finite).filter((value) => value != null);
  const latest = values.at(-1);
  const base = values.at(-1 - lookback);
  return Number.isFinite(latest) && Number.isFinite(base) && base !== 0 ? (latest / base - 1) * 100 : null;
}

function marketCore(marketContext = {}) {
  return marketContext.market_engine || marketContext.market_context || marketContext || {};
}

function buildRelativeStrength(quote = {}, marketContext = {}) {
  const closes = quote.history?.closes || quote.history?.daily?.closes || [];
  const core = marketCore(marketContext);
  // API snapshots normally include `marketContext.market_context.equity_trend`.
  // Cached/flattened snapshots expose the same canonical benchmarks as
  // `spy_trend` / `qqq_trend`; accept both shapes so valid Relative Strength
  // never becomes unavailable merely because the payload was persisted.
  const equityTrend = core.equity_trend || { spy: core.spy_trend, qqq: core.qqq_trend };
  const stockReturn = (lookback) => returnPct(closes, lookback);
  const vsBenchmark = (benchmark, lookback) => {
    const stock = stockReturn(lookback);
    const benchmarkReturn = finite(benchmark?.[`change_${lookback}d_pct`]);
    return stock != null && benchmarkReturn != null ? stock - benchmarkReturn : null;
  };
  return Object.fromEntries([20, 60, 120].flatMap((lookback) => [
    [`stock_return_${lookback}d`, stockReturn(lookback)],
    [`stock_vs_spy_${lookback}d`, vsBenchmark(equityTrend.spy, lookback)],
    [`stock_vs_qqq_${lookback}d`, vsBenchmark(equityTrend.qqq, lookback)],
  ]));
}

function buildFeatures(quote, price, marketContext) {
  if (!window.CanonicalTechnicalFeatures) return null;
  return window.CanonicalTechnicalFeatures.buildTechnicalFeatures({
    history: quote?.history || {},
    currentPrice: price,
    relativeStrength: buildRelativeStrength(quote, marketContext),
    fibonacciStructure: quote?.technical?.fibonacci_structure || {},
    shareBase: quote?.metadata?.sharesOutstanding || null,
  });
}

function buildRow(ticker, quote = {}, marketContext = {}, decisionContext = {}) {
  const price = finite(quote.price);
  const historyCount = (quote.history?.closes || []).filter((value) => Number.isFinite(value)).length;
  const features = buildFeatures(quote, price, marketContext);
  const classification = profileFor(ticker, quote);
  const ready = Boolean(price != null && historyCount >= 2 && features?.availability !== "unavailable");
  const decision = ready && !decisionContext.deferDecision && window.DecisionEngine?.decide
    ? window.DecisionEngine.decide({ ticker, price, technicalFeatures: features, marketContext, classification, metadata: quote.metadata || {}, language: state.language, underlyingTechnicalFeatures: decisionContext.underlyingTechnicalFeatures || null, underlyingPrice: decisionContext.underlyingPrice ?? null })
    : null;
  return {
    ticker,
    quote,
    price,
    changePercent: finite(quote.changePercent),
    currency: quote.currency || quote.metadata?.currency || "USD",
    companyName: quote.longName || quote.shortName || quote.metadata?.longName || ticker,
    exchange: quote.exchangeName || quote.metadata?.exchange || "",
    updatedAt: quote.updatedAt || quote.last_successful_update || null,
    classification,
    technicalFeatures: features,
    decision,
    ready,
    noData: !ready,
  };
}

function decisionFor(row, horizon) {
  return row.decision?.horizons?.[horizon] || null;
}

function actionChip(row, horizon) {
  const decision = decisionFor(row, horizon);
  const label = row.ready && decision ? decision.actionLabel : t("unavailable");
  return `<span class="stock-mini-chip ${actionTone(decision?.action)}"><b>${t(horizon)}</b><span>${escapeHtml(label)}</span></span>`;
}

function sortRows(rows) {
  const multiplier = state.sort.direction === "asc" ? 1 : -1;
  return [...rows].sort((left, right) => {
    if (state.sort.key === "change") return ((left.changePercent ?? -Infinity) - (right.changePercent ?? -Infinity)) * multiplier;
    if (state.sort.key === "type") return String(left.classification.category).localeCompare(String(right.classification.category)) * multiplier;
    return left.ticker.localeCompare(right.ticker) * multiplier;
  });
}

function matchesFilter(row) {
  const tags = new Set(row.classification.tags || []);
  if (state.marketFilter === "all" || state.marketFilter === "us") return true;
  if (state.marketFilter === "megaCap") return tags.has("MegaCap");
  if (state.marketFilter === "growth") return tags.has("Growth") || tags.has("HighGrowth");
  if (state.marketFilter === "speculative") return tags.has("Speculative") || tags.has("HighVolatility");
  if (state.marketFilter === "dividend") return tags.has("Dividend");
  if (state.marketFilter === "value") return tags.has("Value") || tags.has("CashCow");
  return true;
}

function renderStockList() {
  const list = $("#stockList");
  if (!list) return;
  const rows = sortRows(state.rows.filter(matchesFilter));
  list.innerHTML = rows.map((row) => `
    <article class="stock-item${row.ticker === state.selectedTicker ? " active" : ""}" data-open-ticker="${escapeHtml(row.ticker)}" role="button" tabindex="0">
      <div class="stock-item-header">
        <div class="stock-copy">
          <div class="stock-symbol-row"><strong class="stock-symbol">${escapeHtml(row.ticker)}</strong><span class="stock-profile-pill">${escapeHtml(row.classification.category)}</span></div>
          <div class="stock-company">${escapeHtml(row.companyName)}</div>
          <div class="stock-price-row"><strong>${formatPrice(row.price, row.currency)}</strong><span class="stock-day-move ${row.changePercent >= 0 ? "buy" : "sell"}">${t("dayMove")} ${formatPct(row.changePercent)}</span></div>
        </div>
        <button class="stock-remove-btn" type="button" data-remove-ticker="${escapeHtml(row.ticker)}" aria-label="${t("remove")} ${escapeHtml(row.ticker)}"><span class="stock-remove-icon" aria-hidden="true">×</span></button>
      </div>
      <div class="stock-item-body"><div class="stock-horizon-inline">${actionChip(row, "short")}${actionChip(row, "mid")}${actionChip(row, "long")}</div></div>
    </article>
  `).join("") || `<p class="empty-state">${t("noData")}</p>`;
}

function indicatorValue(feature, key, formatter = (value) => value) {
  return Number.isFinite(feature?.[key]) ? formatter(feature[key]) : t("unavailable");
}

function decisionBullets(items, tone) {
  const translated = window.DecisionPresentation?.reasonList?.(items, state.language, 5) || (items || []).slice(0, 5);
  return translated.length
    ? translated.map((item) => `<div class="decision-bullet ${tone}">${tone === "positive" ? "✓" : "⚠"} ${escapeHtml(item)}</div>`).join("")
    : `<div class="decision-bullet muted">${t("unavailable")}</div>`;
}

function horizonLabel(horizon) {
  return { short: t("shortHorizon"), mid: t("midHorizon"), long: t("longHorizon") }[horizon] || t("unavailable");
}

function executionFields(row, decision) {
  if (!decision) return `<p class="decision-no-data">${t("noDecision")}</p>`;
  const presentation = window.DecisionPresentation?.executionSemantics?.(decision) || { intent: decision.executionIntent || "hold" };
  const landscape = decision.priceLandscape || {};
  const field = (label, value) => value ? `<div class="decision-execution-field"><span>${escapeHtml(t(label))}</span><strong>${value}</strong></div>` : "";
  const current = Number.isFinite(landscape.currentPrice) ? landscape.currentPrice : row.price;
  const common = `${field("currentPrice", Number.isFinite(current) ? formatPrice(current, row.currency) : "")}`;
  if (presentation.intent === "avoid") return `<p class="decision-no-data execution-avoid-note">${t("avoidNoEntry")}</p>${field(presentation.opportunity, validPriceRange(landscape.opportunityRange) ? formatRange(landscape.opportunityRange, row.currency) : "")}${common}`;
  return `${field(presentation.opportunity, validPriceRange(landscape.opportunityRange) ? formatRange(landscape.opportunityRange, row.currency) : "")}${common}${field(presentation.reduce, validPriceRange(landscape.reduceRange) ? formatRange(landscape.reduceRange, row.currency) : "")}${field(presentation.invalidation, Number.isFinite(landscape.invalidation) ? formatPrice(landscape.invalidation, row.currency) : "")}`;
}

function validPriceRange(range) {
  return Number.isFinite(range?.low) && Number.isFinite(range?.high);
}

function horizonCoreCard(row, horizon) {
  const decision = decisionFor(row, horizon);
  const active = horizon === state.decisionHorizon ? " is-active" : "";
  if (!decision) return `<article class="decision-core-card${active}" data-decision-horizon="${horizon}" role="button" tabindex="0" aria-pressed="${horizon === state.decisionHorizon}"><span>${t(horizon)} · ${horizonLabel(horizon)}</span><strong>${t("unavailable")}</strong><p class="decision-no-data">${t("noDecision")}</p></article>`;
  return `
    <article class="decision-core-card ${actionTone(decision.action)}${active}" data-decision-horizon="${horizon}" role="button" tabindex="0" aria-pressed="${horizon === state.decisionHorizon}">
      <span>${t(horizon)} · ${horizonLabel(horizon)}</span>
      <strong>${escapeHtml(decision.actionLabel)}</strong>
      <div class="decision-confidence"><span>${t("recommendationConfidence")} <button type="button" class="decision-confidence-help" title="${escapeHtml(t("confidenceHelp"))}" aria-label="${escapeHtml(t("confidenceHelp"))}">i</button></span><b>${escapeHtml(decision.confidence)} / 100</b></div>
      <div class="decision-card-execution">${executionFields(row, decision)}</div>
    </article>
  `;
}

function technicalLine(label, value, note = "") {
  return `<div class="detail-line-row"><div><div class="detail-line-label">${escapeHtml(label)}</div>${note ? `<div class="detail-line-note">${escapeHtml(note)}</div>` : ""}</div><div class="detail-line-side"><strong>${escapeHtml(value)}</strong></div></div>`;
}

function technicalState(value) {
  if (!value || value === "unavailable") return t("unavailable");
  return String(value).replace(/_/g, " ");
}

function technicalNumber(value, digits = 2, { signed = true } = {}) {
  if (!Number.isFinite(value)) return t("unavailable");
  return `${signed && value > 0 ? "+" : ""}${Number(value).toFixed(digits)}`;
}

function technicalAvailability(feature = {}) {
  if (feature?.availability === "available") return "";
  const reason = feature?.unavailable_reason || feature?.reason;
  const available = feature?.available_observations ?? feature?.available_bars;
  const required = feature?.required_observations ?? feature?.required_bars;
  const detail = Number.isFinite(available) && Number.isFinite(required) ? ` (${available}/${required})` : "";
  return reason ? `${technicalState(reason)}${detail}` : "";
}

function technicalCard(title, stateLabel, detail, rows = [], details = [], availability = null) {
  const availabilityNote = technicalAvailability(availability);
  return `<article class="decision-list-card technical-indicator-card"><div class="decision-list-title">${escapeHtml(title)}</div><div class="technical-indicator-state">${escapeHtml(technicalState(stateLabel))}</div>${detail ? `<div class="detail-line-note">${escapeHtml(detail)}</div>` : ""}${availabilityNote ? `<div class="detail-line-note">${escapeHtml(availabilityNote)}</div>` : ""}<div class="detail-line-list">${rows.join("") || technicalLine(title, t("unavailable"))}</div>${details.length ? `<div class="detail-disclosure"><div class="detail-line-list">${details.join("")}</div></div>` : ""}</article>`;
}

function compactNumber(value) {
  if (!Number.isFinite(value)) return t("unavailable");
  return new Intl.NumberFormat(state.language === "zh" ? "zh-CN" : "en-US", { notation: "compact", maximumFractionDigits: 2 }).format(value);
}

function primaryTechnicalFeature(group = {}, key, interval) {
  return group?.[key] || Object.values(group).find((item) => item?.interval === interval) || {};
}

function primaryIntervalFor(horizon) {
  return horizon === "short" ? "4h" : horizon === "mid" ? "1d" : "1w";
}

function primaryRsiPeriodFor(horizon) {
  return horizon === "short" ? 6 : horizon === "mid" ? 14 : 21;
}

function rvolValue(value) {
  return Number.isFinite(value) ? Number(value).toFixed(2) : t("unavailable");
}

function percentValue(value, digits = 1) {
  return Number.isFinite(value) ? `${Number(value).toFixed(digits)}%` : t("unavailable");
}

function technicalBlock(row, horizon) {
  const featureSet = row.technicalFeatures?.horizons?.[window.DecisionEngine.config.horizons[horizon].technicalKey] || {};
  const interval = primaryIntervalFor(horizon);
  const rsiPeriod = primaryRsiPeriodFor(horizon);
  const rsi = primaryTechnicalFeature(featureSet.momentum?.rsi, `rsi_${rsiPeriod}_${interval}`, interval);
  const macd = primaryTechnicalFeature(featureSet.momentum?.macd, `macd_${interval}`, interval);
  const adx = primaryTechnicalFeature(featureSet.trend?.adx, `adx_14_${interval}`, interval);
  const atr = primaryTechnicalFeature(featureSet.volatility?.atr, `atr_14_${interval}`, interval);
  const bands = primaryTechnicalFeature(featureSet.volatility?.bollinger, `bollinger_${interval}`, interval);
  const kdj = primaryTechnicalFeature(featureSet.momentum?.kdj, `kdj_9_${interval}`, interval);
  const obv = primaryTechnicalFeature(featureSet.participation?.obv, `obv_${interval}`, interval);
  const movingAverages = Object.values(featureSet.trend?.moving_averages || {})
    .sort((left, right) => `${left.interval}-${left.indicator}-${left.period}`.localeCompare(`${right.interval}-${right.indicator}-${right.period}`));
  const rsiFeatures = Object.values(featureSet.momentum?.rsi || {})
    .sort((left, right) => `${left.interval}-${left.period}`.localeCompare(`${right.interval}-${right.period}`));
  const macdFeatures = Object.values(featureSet.momentum?.macd || {})
    .sort((left, right) => String(left.interval).localeCompare(String(right.interval)));
  const rs = featureSet.relative_strength || {};
  const maRows = movingAverages.map((item) => technicalLine(
    `${String(item.indicator || "MA").toUpperCase()} ${item.period} · ${item.interval}`,
    formatPrice(item.value, row.currency),
    item.availability === "available" ? `${technicalState(item.price_state)} · ${technicalState(item.slope?.state)}` : technicalAvailability(item) || t("unavailable"),
  ));
  const rsiRows = rsiFeatures.map((item) => technicalLine(
    `${String(item.interval || "").toUpperCase()} RSI ${item.period ?? "—"}`,
    indicatorValue(item, "value", (value) => value.toFixed(1)),
    technicalState(item.state),
  ));
  const secondaryMacdRows = macdFeatures.filter((item) => item !== macd).map((item) => technicalLine(
    `${String(item.interval || "").toUpperCase()} MACD / Signal / Histogram`,
    `${technicalNumber(item.macd_line, 3)} / ${technicalNumber(item.signal_line, 3)} / ${technicalNumber(item.histogram, 3)}`,
    `${technicalState(item.state)} · ${technicalState(item.crossover_state)}`,
  ));
  const overview = [
    [t("trendSummary"), technicalState(featureSet.trend?.ma_structure?.alignment)],
    [t("momentumSummary"), technicalState(macd.state)],
    [t("volatilitySummary"), technicalState(atr.volatility_regime)],
    [t("relativeStrengthSummary"), technicalState(rs.state)],
    [t("participationSummary"), technicalState(obv.trend)],
  ];
  return `
    <section class="detail-section-card technical-horizon-section">
      <div class="detail-section-head"><h3>${t(horizon)} · ${horizonLabel(horizon)}</h3></div>
      <div class="detail-line-note">${t("dataStatus")}: ${escapeHtml(technicalState(featureSet.availability))} · ${interval.toUpperCase()} ${t("primaryInterval")} · ${t("supportingIntervals")}</div>
      <div class="technical-overview-strip">${overview.map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>
      <div class="technical-family-grid">
        ${technicalCard("Moving averages", featureSet.trend?.ma_structure?.alignment, "Each value names its MA type, period and candle interval.", maRows, [technicalLine("Alignment", technicalState(featureSet.trend?.ma_structure?.alignment)), technicalLine("Compression / expansion", technicalState(featureSet.trend?.ma_structure?.compression_state))])}
        ${technicalCard("RSI", rsi.state, `${interval.toUpperCase()} · primary RSI ${rsi.period || rsiPeriod}`, rsiRows, [technicalLine("Primary slope", technicalState(rsi.slope?.state), technicalAvailability(rsi.slope)), technicalLine("Primary divergence", technicalState(rsi.divergence))], rsi)}
        ${technicalCard("MACD", macd.state, `${interval.toUpperCase()} · MACD ${macd.period || "12/26/9"}`, [technicalLine("MACD line", technicalNumber(macd.macd_line, 3)), technicalLine("Signal line", technicalNumber(macd.signal_line, 3)), technicalLine("Histogram", technicalNumber(macd.histogram, 3))], [technicalLine("Histogram 1-bar Δ", technicalNumber(macd.histogram_change_1, 3)), technicalLine("Histogram 3-bar Δ", technicalNumber(macd.histogram_change_3, 3)), technicalLine("Histogram 5-bar Δ", technicalNumber(macd.histogram_change_5, 3)), technicalLine("Zero line", technicalState(macd.above_or_below_zero)), technicalLine("Improving / deteriorating", technicalState(macd.improving_or_deteriorating)), technicalLine("Crossover", technicalState(macd.crossover_state)), technicalLine("Histogram slope", technicalState(macd.histogram_slope?.state), technicalAvailability(macd.histogram_slope)), ...secondaryMacdRows], macd)}
        ${technicalCard("ADX / DI", adx.trend_strength, `${interval.toUpperCase()} · ADX ${adx.period || 14}`, [technicalLine("ADX", indicatorValue(adx, "adx", (value) => value.toFixed(1))), technicalLine("+DI / −DI", `${indicatorValue(adx, "plus_di", (value) => value.toFixed(1))} / ${indicatorValue(adx, "minus_di", (value) => value.toFixed(1))}`)], [technicalLine("Trend strength", technicalState(adx.trend_strength)), technicalLine("Directional bias", technicalState(adx.directional_bias)), technicalLine("ADX slope", technicalState(adx.slope?.state), technicalAvailability(adx.slope))], adx)}
        ${technicalCard("ATR", atr.volatility_regime, `${interval.toUpperCase()} · ATR ${atr.period || 14}`, [technicalLine("Raw ATR", indicatorValue(atr, "value", (value) => formatPrice(value, row.currency))), technicalLine("ATR %", indicatorValue(atr, "atr_pct", (value) => percentValue(value, 2)))], [technicalLine("ATR percentile", indicatorValue(atr, "atr_percentile_pct", (value) => percentValue(value, 1)), technicalAvailability(atr.atr_percentile)), technicalLine("60 / 120 / 250-bar percentile", `${percentValue(atr.atr_percentile_60)} / ${percentValue(atr.atr_percentile_120)} / ${percentValue(atr.atr_percentile_250)}`), technicalLine("Volatility regime", technicalState(atr.volatility_regime), technicalAvailability(atr.volatility_regime_availability)), technicalLine("Expanding / contracting", technicalState(atr.expansion_state)), technicalLine("ATR slope", technicalState(atr.slope?.state), technicalAvailability(atr.slope))], atr)}
        ${technicalCard("Bollinger", bands.squeeze_state, `${interval.toUpperCase()} · BB ${bands.period || 20}`, [technicalLine("%B", indicatorValue(bands, "percent_b", (value) => value.toFixed(2))), technicalLine("Bandwidth", indicatorValue(bands, "bandwidth_pct", (value) => percentValue(value, 2))), technicalLine("Upper / middle / lower", `${formatPrice(bands.upper_band, row.currency)} / ${formatPrice(bands.middle_band, row.currency)} / ${formatPrice(bands.lower_band, row.currency)}`)], [technicalLine("Bandwidth percentile", indicatorValue(bands, "bandwidth_percentile", (value) => percentValue(value, 1)), technicalAvailability(bands.bandwidth_percentile_availability)), technicalLine("Squeeze / expanded state", technicalState(bands.squeeze_state), technicalAvailability(bands.squeeze_state_availability)), technicalLine("Price position", technicalState(bands.price_position))], bands)}
        ${Object.keys(featureSet.momentum?.kdj || {}).length ? technicalCard("KDJ", kdj.crossover_state, `${interval.toUpperCase()} · KDJ ${kdj.period || 9}`, [technicalLine("K / D / J", `${indicatorValue(kdj, "k", (value) => value.toFixed(1))} / ${indicatorValue(kdj, "d", (value) => value.toFixed(1))} / ${indicatorValue(kdj, "j", (value) => value.toFixed(1))}`)], [technicalLine("Crossover", technicalState(kdj.crossover_state)), technicalLine("Direction", technicalState(kdj.direction)), technicalLine("K / D / J slope", `${technicalState(kdj.k_slope?.state)} / ${technicalState(kdj.d_slope?.state)} / ${technicalState(kdj.j_slope?.state)}`), technicalLine("Overbought / oversold", `${kdj.overbought ? "overbought" : "—"} / ${kdj.oversold ? "oversold" : "—"}`)], kdj) : ""}
        ${technicalCard("Relative Strength", rs.state, `1D · ${rs.primary_lookback_days || t("unavailable")}D primary lookback`, [technicalLine("Stock return", formatPct(rs.primary?.stock_return)), technicalLine("vs SPY", formatPct(rs.primary?.vs_spy)), technicalLine("vs QQQ", formatPct(rs.primary?.vs_qqq))], [technicalLine("Stock return · 20 / 60 / 120D", `${formatPct(rs.returns?.stock_20d)} / ${formatPct(rs.returns?.stock_60d)} / ${formatPct(rs.returns?.stock_120d)}`), technicalLine("vs SPY · 20 / 60 / 120D", `${formatPct(rs.vs_spy?.d20)} / ${formatPct(rs.vs_spy?.d60)} / ${formatPct(rs.vs_spy?.d120)}`), technicalLine("vs QQQ · 20 / 60 / 120D", `${formatPct(rs.vs_qqq?.d20)} / ${formatPct(rs.vs_qqq?.d60)} / ${formatPct(rs.vs_qqq?.d120)}`), technicalLine("Consistency", technicalState(rs.consistency?.state || rs.consistency_state))], rs)}
        ${technicalCard("OBV", obv.trend, `${interval.toUpperCase()} OBV`, [technicalLine("Raw OBV", compactNumber(obv.raw_value)), technicalLine("Trend", technicalState(obv.trend)), technicalLine("Divergence", technicalState(obv.divergence)), technicalLine("Price-volume confirmation", technicalState(obv.price_obv_confirmation))], [technicalLine("OBV slope", technicalState(obv.slope?.state), technicalAvailability(obv.slope))], obv)}
      </div>
    </section>
  `;
}

function technicalTabSelector(attribute, selected, className = "technical-horizon-tabs") {
  return `<div class="${className}" role="tablist">${["short", "mid", "long"].map((horizon) => `<button type="button" class="${horizon === selected ? "active" : ""}" data-${attribute}="${horizon}">${t(horizon)} · ${horizonLabel(horizon)}</button>`).join("")}</div>`;
}

function technicalAccordion(id, title, description, content, expanded) {
  return `<section class="technical-accordion${expanded ? " is-expanded" : ""}"><button type="button" class="technical-accordion-toggle" data-technical-toggle="${id}" aria-expanded="${expanded}"><span><b>${escapeHtml(title)}</b>${description ? `<small>${escapeHtml(description)}</small>` : ""}</span><span class="technical-accordion-state">${expanded ? t("collapsed") : t("expanded")}</span></button><div class="technical-accordion-body"${expanded ? "" : " hidden"}>${content}</div></section>`;
}

function fibonacciLevelTable(levels, row, type) {
  const rows = Object.values(levels || {}).filter((level) => level?.valid_for_display).map((level) => `<tr><td>${escapeHtml(level.label || t("unavailable"))}</td><td>${formatPrice(level.price, row.currency)}</td><td>${Math.abs(level.distance_from_current_pct ?? Infinity) <= 0.1 ? t("currentPosition") : `${formatPct(level.distance_from_current_pct)} ${state.language === "zh" ? "相对当前" : "from current"}`}</td></tr>`).join("");
  return `<div class="fibonacci-level-group"><h4>${escapeHtml(type)}</h4><div class="fibonacci-table-scroll"><table class="fibonacci-level-table"><thead><tr><th>${t("level")}</th><th>${t("price")}</th><th>${t("distance")}</th></tr></thead><tbody>${rows || `<tr><td colspan="3">${t("technicalUnavailable")}</td></tr>`}</tbody></table></div></div>`;
}

function fibonacciHorizonCard(row, title, fib) {
  if (!fib || !["available", "stale_swing"].includes(fib.status)) {
    return technicalCard(title, fib?.status === "no_valid_swing" ? "No valid swing identified" : "Insufficient Fibonacci data", fib?.explanation || "", []);
  }
  const direction = fib.swing_direction === "up_swing" ? "Up swing" : "Down swing";
  const source = String(fib.source_timeframe || "—").toUpperCase();
  const fallback = fib.fallback_used ? `${t("yes")}${fib.fallback_reason ? ` · ${fib.fallback_reason}` : ""}` : t("no");
  return `<article class="technical-indicator-card fibonacci-card"><div class="decision-list-title">${escapeHtml(title)}</div><div class="technical-indicator-state">${escapeHtml(direction)}</div><div class="detail-line-note">${escapeHtml(`${source} · ${fib.data_window || "—"} · ${fib.pivot_method || "—"}`)}</div><div class="fibonacci-summary-grid">${[
    [t("swingHigh"), `${fib.swing_high_date || "—"} · ${formatPrice(fib.swing_high, row.currency)}`],
    [t("swingLow"), `${fib.swing_low_date || "—"} · ${formatPrice(fib.swing_low, row.currency)}`],
    [t("swingRange"), `${formatPrice(fib.swing_range, row.currency)} · ${percentValue(fib.swing_range_pct)}`],
    [t("currentPosition"), fib.current_position_label || t("unavailable")],
    [t("nearestBelow"), fib.nearest_level_below ? `${fib.nearest_level_below.label} · ${formatPrice(fib.nearest_level_below.price, row.currency)}` : t("unavailable")],
    [t("nearestAbove"), fib.nearest_level_above ? `${fib.nearest_level_above.label} · ${formatPrice(fib.nearest_level_above.price, row.currency)}` : t("unavailable")],
  ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("")}</div>${fibonacciLevelTable(fib.retracement_levels, row, t("retracement"))}${fibonacciLevelTable(fib.extension_levels, row, t("extension"))}<details class="technical-advanced"><summary>${t("advancedSwingMetadata")}</summary><div class="detail-line-list">${technicalLine(t("sourceTimeframe"), source)}${technicalLine(t("lookbackBars"), `${fib.lookback_bars ?? t("unavailable")} / ${fib.source_bar_count ?? t("unavailable")}`)}${technicalLine(t("fallbackUsed"), fallback)}${fib.fallback_used && fib.fallback_reason ? technicalLine(t("fallbackReason"), fib.fallback_reason) : ""}${technicalLine("Anchor start", `${fib.swing_start_date || "—"} · ${formatPrice(fib.swing_direction === "up_swing" ? fib.swing_low : fib.swing_high, row.currency)}`)}${technicalLine("Anchor end", `${fib.swing_end_date || "—"} · ${formatPrice(fib.swing_direction === "up_swing" ? fib.swing_high : fib.swing_low, row.currency)}`)}${technicalLine("Pivot confirmation", fib.pivot_confirmation || fib.pivot_method || t("unavailable"))}${technicalLine("Pivot count · high / low", `${fib.pivot_high_count ?? t("unavailable")} / ${fib.pivot_low_count ?? t("unavailable")}`)}${technicalLine("Bars since swing end", Number.isFinite(fib.bars_since_swing_end) ? String(fib.bars_since_swing_end) : t("unavailable"))}</div></details></article>`;
}

function renderFibonacciStructure(row) {
  const structure = row.technicalFeatures?.fibonacci_structure || {};
  const key = state.fibonacciHorizon === "short" ? "short_term" : state.fibonacciHorizon === "mid" ? "mid_term" : "long_term";
  const title = `${t(state.fibonacciHorizon)} ${t("fibonacciStructure")}`;
  const content = `<div class="technical-accordion-content">${technicalTabSelector("fibonacci-horizon", state.fibonacciHorizon, "fibonacci-horizon-tabs")}${fibonacciHorizonCard(row, title, structure[key])}</div>`;
  return technicalAccordion("fibonacci", t("fibonacciStructure"), t("fibonacciDescription"), content, state.technicalSections.fibonacci);
}

function renderTechnicalFoundation(row) {
  const position = row.technicalFeatures?.price_position || {};
  const volume = row.technicalFeatures?.volume || {};
  const averages = volume.moving_average_volume || {};
  const rvol = volume.relative_volume || {};
  const obv = volume.obv || {};
  const turnover = volume.turnover || {};
  const shortObv = row.technicalFeatures?.horizons?.short?.participation?.obv?.obv_4h || {};
  const midObv = row.technicalFeatures?.horizons?.medium?.participation?.obv?.obv_1d || {};
  const longObv = row.technicalFeatures?.horizons?.long?.participation?.obv?.obv_1w || {};
  const content = `<div class="technical-family-grid">${technicalCard("52-Week and history", position.availability, "Daily OHLCV history", [technicalLine("52W high / distance", `${formatPrice(position.high_52w, row.currency)} / ${formatPct(position.distance_to_52w_high_pct)}`, position.high_52w_date || ""), technicalLine("52W low / distance", `${formatPrice(position.low_52w, row.currency)} / ${formatPct(position.distance_to_52w_low_pct)}`, position.low_52w_date || ""), technicalLine("52W position", percentValue(position.position_52w_pct)), technicalLine("All-time high / distance", `${formatPrice(position.all_time_high, row.currency)} / ${formatPct(position.distance_to_ath_pct)}`, position.all_time_high_date || "")], [technicalLine("History coverage", position.all_time_history_coverage || t("unavailable")), technicalLine("History bars / start", `${position.all_time_history_bar_count ?? t("unavailable")} / ${position.all_time_history_start || t("unavailable")}`)], position)}${technicalCard("Volume / RVOL / OBV", rvol.state || volume.availability, "1D current volume, moving averages, RVOL and OBV context", [technicalLine("Current volume", compactNumber(volume.current_volume)), technicalLine("Average volume", `5D ${compactNumber(averages.avg_5d)} · 20D ${compactNumber(averages.avg_20d)} · 60D ${compactNumber(averages.avg_60d)}`), technicalLine("Relative volume", `RVOL5 ${rvolValue(rvol.rvol_5d)} · RVOL20 ${rvolValue(rvol.rvol_20d)} · RVOL60 ${rvolValue(rvol.rvol_60d)}`), technicalLine("OBV raw / trend", `${compactNumber(obv.raw_value)} / ${technicalState(obv.trend)}`)], [technicalLine("Average volume · 120D / 250D", `${compactNumber(averages.avg_120d)} / ${compactNumber(averages.avg_250d)}`), technicalLine("Turnover · current / 5D / 20D / 60D", `${percentValue(turnover.turnover_current)} / ${percentValue(turnover.turnover_5d_avg)} / ${percentValue(turnover.turnover_20d_avg)} / ${percentValue(turnover.turnover_60d_avg)}`), technicalLine("OBV trend · 5D / 20D / 60D", `${technicalState(obv.trends?.d5?.trend)} / ${technicalState(obv.trends?.d20?.trend)} / ${technicalState(obv.trends?.d60?.trend)}`), technicalLine("OBV divergence", technicalState(obv.divergence || obv.trends?.d20?.divergence)), technicalLine("Price-volume confirmation", technicalState(obv.price_obv_confirmation || obv.trends?.d20?.price_obv_confirmation)), technicalLine("Volume structure", `${technicalState(volume.trend?.volume_trend)} · ${technicalState(volume.accumulation_distribution)}`), technicalLine("Horizon OBV · 4H / 1D / 1W", `${technicalState(shortObv.trend)} / ${technicalState(midObv.trend)} / ${technicalState(longObv.trend)}`)], volume)}</div>`;
  return technicalAccordion("foundation", t("historicalVolume"), "", content, state.technicalSections.foundation);
}

function renderTechnicalPanel(row) {
  if (!row.technicalFeatures) return `<section class="detail-tab-section"><p>${t("noData")}</p></section>`;
  return `<section class="detail-tab-section technical-tab-panel">${renderFibonacciStructure(row)}${renderTechnicalFoundation(row)}<section class="technical-overview-section"><div class="detail-section-head"><h3>${t("technicalOverview")}</h3></div>${technicalTabSelector("technical-horizon", state.technicalHorizon)}${technicalBlock(row, state.technicalHorizon)}</section></section>`;
}

function marketLine(label, value, note = "") {
  return `<div class="detail-line-row"><div><div class="detail-line-label">${escapeHtml(label)}</div>${note ? `<div class="detail-line-note">${escapeHtml(note)}</div>` : ""}</div><div class="detail-line-side"><strong>${escapeHtml(value)}</strong></div></div>`;
}

function renderMarketPanel(row) {
  const market = state.snapshot?.marketContext || state.snapshot?.market_context || {};
  const engine = marketCore(market);
  const earnings = decisionFor(row, "short")?.market?.earnings || {};
  const priceTrend = (item) => item?.value == null ? t("unavailable") : `${formatPrice(item.value)} · ${item.trend || t("unavailable")}`;
  const vixChange = (value) => Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}` : t("unavailable");
  const indexHistory = (item) => `5D ${formatPct(item?.change_5d_pct)} · 20D ${formatPct(item?.change_20d_pct)} · 60D ${formatPct(item?.change_60d_pct)} · 120D ${formatPct(item?.change_120d_pct)}`;
  return `
    <section class="detail-tab-section market-tab-panel">
      <section class="detail-section-card market-status-card"><div class="detail-section-head"><h3>${t("marketStatus")}</h3></div><div class="market-status-primary"><div><span>${t("regime")}</span><strong>${escapeHtml(engine.regime || engine.summary || t("unavailable"))}</strong></div><div><span>${t("earningsProximity")}</span><strong>${escapeHtml(earnings.date ? `${formatDate(earnings.date)}${Number.isFinite(earnings.daysToEarnings) ? ` · ${earnings.daysToEarnings}d` : ""}` : t("unavailable"))}</strong></div></div></section>
      <div class="market-compact-grid">
        <section class="detail-section-card market-compact-card"><div class="detail-section-head"><h3>VIX</h3></div><div class="detail-line-list">${marketLine(t("current"), Number.isFinite(finite(engine.vix?.value)) ? finite(engine.vix.value).toFixed(2) : t("unavailable"), engine.vix?.impact || "")}${marketLine(t("change5d"), vixChange(engine.vix?.change_5d))}${marketLine(t("change20d"), vixChange(engine.vix?.change_20d))}${marketLine(t("trend"), engine.vix?.trend || t("unavailable"))}</div></section>
        <section class="detail-section-card market-compact-card"><div class="detail-section-head"><h3>SPY / QQQ</h3></div><div class="detail-line-list">${marketLine("SPY", priceTrend(engine.equity_trend?.spy), indexHistory(engine.equity_trend?.spy))}${marketLine("QQQ", priceTrend(engine.equity_trend?.qqq), indexHistory(engine.equity_trend?.qqq))}</div></section>
        <section class="detail-section-card market-compact-card"><div class="detail-section-head"><h3>Fear &amp; Greed / US 10Y Yield</h3></div><div class="detail-line-list">${marketLine("Fear & Greed", engine.fear_greed?.label || engine.fearGreed?.label || t("unavailable"), engine.fear_greed?.value == null ? "" : `${Math.round(engine.fear_greed.value)}/100`)}${marketLine("US 10Y Yield", engine.ten_year_yield?.value == null ? t("unavailable") : `${Number(engine.ten_year_yield.value).toFixed(2)}%`, `5D ${engine.ten_year_yield?.change_5d_bps ?? t("unavailable")} bps · 20D ${engine.ten_year_yield?.change_20d_bps ?? t("unavailable")} bps`)}</div></section>
      </div>
    </section>
  `;
}

function profileFromRow(row) {
  return decisionFor(row, "short")?.profile || {
    type: row.classification?.isETF ? "etf" : "stock", isETF: Boolean(row.classification?.isETF),
    primaryClassification: row.classification?.primaryClassification || null,
    companyTraits: row.classification?.companyTraits || [], lifecycle: row.classification?.lifecycle || null,
    profileConfidence: row.classification?.profileConfidence ?? null, lastProfileReview: row.classification?.lastProfileReview || null,
    appliedModifiers: [], effectiveModifiers: {},
  };
}

function tagPills(tags, className = "") {
  const values = [...new Set((Array.isArray(tags) ? tags : []).filter(Boolean))];
  return values.map((tag) => `<span class="profile-tag ${className}">${escapeHtml(tag)}</span>`).join("");
}

function renderProfileHeader(row) {
  const profile = profileFromRow(row);
  const groups = window.DecisionPresentation?.profileGroups?.(profile) || { traits: profile.companyTraits || [], lifecycle: profile.lifecycle || null, visible: {} };
  const confidence = Number.isFinite(profile.profileConfidence) ? `${Math.round(profile.profileConfidence * 100)}%` : "";
  const profileMeta = profile.isETF ? [] : [
    profile.lifecycle ? `<span>${t("lifecycle")}: <b>${escapeHtml(profile.lifecycle)}</b></span>` : "",
    confidence ? `<span>${t("profileConfidence")}: <b>${confidence}</b></span>` : "",
    profile.lastProfileReview ? `<span>${t("lastReview")}: <b>${formatDate(profile.lastProfileReview)}</b></span>` : "",
  ].filter(Boolean).join("");
  const stockGroups = groups.visible?.traits ? `<div class="profile-tag-group"><span>${t("companyTraits")}</span><div>${tagPills(groups.traits)}</div></div>` : "";
  const etfMeta = profile.isETF ? `<div class="profile-tag-group"><span>${t("etfProfile")}</span><div class="profile-fact-row"><b>${t("leveraged")}</b><span>${profile.leveraged ? t("yes") : t("no")}</span><b>${t("direction")}</b><span>${profile.direction === "inverse" ? t("inverseDirection") : t("longDirection")}</span>${profile.underlying ? `<b>${t("underlying")}</b><span>${escapeHtml(profile.underlying)}</span>` : ""}</div></div>` : "";
  return `<section class="decision-hero"><div class="decision-hero-main"><div class="decision-code">${escapeHtml(row.ticker)}</div><div class="decision-company">${escapeHtml(row.companyName)}</div><div class="detail-consensus-mini"><span>${t("price")} ${formatPrice(row.price, row.currency)}</span><span class="daily-change ${row.changePercent >= 0 ? "positive" : "negative"}">${t("dayMove")} ${formatPct(row.changePercent)}</span></div>${profile.primaryClassification ? `<div class="primary-classification"><span>${t("primaryClassification")}</span><b>${escapeHtml(profile.primaryClassification)}</b></div>` : ""}</div>${stockGroups || etfMeta || profileMeta ? `<div class="decision-profile-header">${stockGroups}${etfMeta}${profileMeta ? `<div class="profile-review-line">${profileMeta}</div>` : ""}</div>` : ""}</section>`;
}

function renderDecisionPriceMap(row, horizon) {
  const decision = decisionFor(row, horizon);
  const model = window.DecisionPresentation?.priceMapModel?.({ currentPrice: row.price, decision }) || { points: [] };
  const pointMarkup = (point) => (point.id === "opportunity" || point.id === "reduce"
    ? `<span class="price-map-range ${point.id}" style="left:${point.start}%;width:${Math.max(1.2, point.end - point.start)}%"></span>`
    : `<span class="price-map-marker ${point.id}" style="left:${point.position}%"><b>${point.id === "current" ? "▲" : "│"}</b></span>`);
  const labelValue = (point) => point.id === "opportunity" || point.id === "reduce" ? formatRange({ low: point.low, high: point.high }, row.currency) : formatPrice(point.value, row.currency);
  const distance = (point) => point.distance ? point.distance.within ? t("withinRange") : `${t("distanceToRange")} ${formatPct(point.distance.percent)}` : "";
  const labelMarkup = (point) => `<span class="price-map-label ${point.id} ${point.labelSide} lane-${point.labelLane}" style="left:${point.labelPosition}%"><i>${escapeHtml(t(point.labelKey))}</i><b>${escapeHtml(labelValue(point))}</b>${distance(point) ? `<small>${escapeHtml(distance(point))}</small>` : ""}</span>`;
  if (!decision || !model.points?.length) return `<section class="detail-section-card"><div class="detail-section-head"><h3>${t("decisionPriceMap")}</h3></div><p class="decision-no-data">${t("noDecision")}</p></section>`;
  const key = (model.legend || []).map((point) => `<span><i class="price-map-key ${point.id}"></i>${escapeHtml(t(point.labelKey))}</span>`).join("");
  return `<section class="detail-section-card decision-price-map"><div class="detail-section-head"><h3>${t("decisionPriceMap")}</h3><span>${t(horizon)} · ${horizonLabel(horizon)}</span></div><div class="price-map-track" style="--price-map-height:${model.trackHeight || 140}px">${model.points.map(pointMarkup).join("")}<div class="price-map-axis"></div>${model.labels.map(labelMarkup).join("")}</div><div class="price-map-key-row">${key}</div></section>`;
}

function renderWhyThisDecision(row, horizon) {
  const decision = decisionFor(row, horizon);
  return `<section class="detail-section-card"><div class="detail-section-head"><h3>${t("whyThisDecision")}</h3><span>${t(horizon)} · ${horizonLabel(horizon)}</span></div>${decision ? `<div class="decision-summary-grid decision-reason-grid"><div class="decision-list-card"><div class="decision-list-title">${t("support")}</div><div class="decision-bullets">${decisionBullets(decision.reasons?.supporting, "positive")}</div></div><div class="decision-list-card"><div class="decision-list-title">${t("limiting")}</div><div class="decision-bullets">${decisionBullets(decision.reasons?.limiting, "warning")}</div></div></div>` : `<p class="decision-no-data">${t("noDecision")}</p>`}</section>`;
}

function renderExecutionPlan(row, horizon) {
  const decision = decisionFor(row, horizon);
  if (!decision) return `<section class="detail-section-card"><div class="detail-section-head"><h3>${t("executionPlan")}</h3></div><p class="decision-no-data">${t("noDecision")}</p></section>`;
  const guidance = window.DecisionPresentation?.positionGuidance?.(decision.action, state.language) || "";
  return `<section class="detail-section-card"><div class="detail-section-head"><h3>${t("executionPlan")}</h3><span>${t(horizon)} · ${horizonLabel(horizon)}</span></div><div class="execution-plan-grid"><article class="execution-plan-action ${actionTone(decision.action)}"><span>${t("recommendation")}</span><strong>${escapeHtml(decision.actionLabel)}</strong><p>${escapeHtml(guidance)}</p></article><article class="execution-plan-fields">${executionFields(row, decision)}</article></div></section>`;
}

function marketImpact(decision) {
  const modifiers = decision?.market?.horizonModifiers || {};
  if (modifiers.shock) return t("shockSensitive");
  if ((modifiers.riskAdd || 0) >= 4) return t("restrictive");
  if ((modifiers.riskAdd || 0) < 0) return t("supportive");
  return t("neutral");
}

function earningsText(earnings = {}) {
  if (Number.isFinite(earnings.daysToEarnings)) {
    if (earnings.daysToEarnings >= 0) return `${t("nextEarnings")} ${earnings.daysToEarnings} ${t("days")}`;
    return `${t("nextEarnings")} ${Math.abs(earnings.daysToEarnings)} ${t("daysAgo")}`;
  }
  return earnings.date ? formatDate(earnings.date) : t("unavailable");
}

function renderMarketRiskRegime(row) {
  const decision = decisionFor(row, "short");
  const market = decision?.market || {};
  const vix = market.vix || {};
  const indexMetric = (index) => index?.trend || t("unavailable");
  const vixDelta = (value) => Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${Number(value).toFixed(2)}` : t("unavailable");
  const yieldText = market.yield?.value == null ? t("unavailable") : `${Number(market.yield.value).toFixed(2)}% · ${market.yield.label || t("unavailable")}`;
  return `<section class="detail-section-card"><div class="detail-section-head"><h3>${t("marketRiskRegime")}</h3></div>${decision ? `<div class="market-regime-grid"><article><span>${t("regime")}</span><strong>${escapeHtml(market.label || t("unavailable"))}</strong></article><article><span>${t("marketImpact")}</span><strong>${marketImpact(decision)}</strong></article><article><span>SPY</span><strong>${escapeHtml(indexMetric(market.spy))}</strong></article><article><span>QQQ</span><strong>${escapeHtml(indexMetric(market.qqq))}</strong></article><article><span>VIX</span><strong>${Number.isFinite(vix.value) ? `${vix.value.toFixed(2)} · 5D ${vixDelta(vix.change5d)} · 20D ${vixDelta(vix.change20d)}` : t("unavailable")}</strong></article><article><span>Fear &amp; Greed</span><strong>${escapeHtml(market.fearGreed?.label || t("unavailable"))}${Number.isFinite(market.fearGreed?.value) ? ` · ${Math.round(market.fearGreed.value)}/100` : ""}</strong></article><article><span>US 10Y</span><strong>${escapeHtml(yieldText)}</strong></article><article><span>${t("earningsProximity")}</span><strong>${escapeHtml(earningsText(market.earnings))}</strong></article></div>` : `<p class="decision-no-data">${t("noDecision")}</p>`}</section>`;
}

function modifierDescription(tag) {
  const descriptions = {
    MegaCap: { en: "Lower fast-noise sensitivity; market sensitivity reduced.", zh: "降低短周期噪声敏感度，并降低市场敏感度。" }, HighGrowth: { en: "Momentum and Relative Strength sensitivity increased.", zh: "提高动量与相对强弱的敏感度。" }, HighBeta: { en: "Normal volatility tolerance and market-shock sensitivity increased.", zh: "提高正常波动容忍度与市场冲击敏感度。" }, HighVolatility: { en: "Normal volatility tolerance and market-shock sensitivity increased.", zh: "提高正常波动容忍度与市场冲击敏感度。" }, MarketLeader: { en: "Trend persistence matters more; Strong Buy needs better price opportunity.", zh: "趋势延续性更重要，强力买入需要更好的价格机会。" }, EstablishedLeader: { en: "Trend persistence matters more; Strong Buy needs better price opportunity.", zh: "趋势延续性更重要，强力买入需要更好的价格机会。" }, CrowdedLeader: { en: "Bullish-exhaustion sensitivity increased.", zh: "提高多头衰竭敏感度。" }, Cyclical: { en: "Participation, Relative Strength inflection, and contrarian exhaustion matter more.", zh: "更重视参与度、相对强弱拐点与反向衰竭。" }, MemoryStorage: { en: "Participation, Relative Strength inflection, and contrarian exhaustion matter more.", zh: "更重视参与度、相对强弱拐点与反向衰竭。" }, InterestRateSensitive: { en: "US 10Y sensitivity increased.", zh: "提高对美国 10 年期利率的敏感度。" }, REIT: { en: "US 10Y sensitivity increased.", zh: "提高对美国 10 年期利率的敏感度。" }, CashCow: { en: "Ordinary pullback tolerance and long-horizon stability increased.", zh: "提高普通回撤容忍度与长期决策稳定性。" }, RegulatoryRisk: { en: "Event and market-shock sensitivity increased.", zh: "提高事件与市场冲击敏感度。" },
  };
  const etfDescriptions = {
    LeveragedETF: { en: "Raises volatility, exhaustion, and market-shock sensitivity; formal action gates are stricter.", zh: "提高波动、衰竭和市场冲击敏感度，并收紧正式操作门槛。" },
    InverseETF: { en: "Uses the underlying index as bounded inverted confirmation while retaining the ETF's own technical direction.", zh: "将标的指数作为有限的反向确认，同时保留 ETF 自身技术方向。" },
  };
  return descriptions[tag]?.[state.language] || etfDescriptions[tag]?.[state.language] || "";
}

function renderCompanyModel(row) {
  const profile = decisionFor(row, "short")?.profile || profileFromRow(row);
  const groups = window.DecisionPresentation?.profileGroups?.(profile) || { traits: profile.companyTraits || [], lifecycle: profile.lifecycle || null, visible: {} };
  const applied = (profile.appliedModifiers || []).map((tag) => ({ tag, description: modifierDescription(tag) })).filter((item) => item.description).map((item) => `<li><b>${escapeHtml(item.tag)}</b><span>${escapeHtml(item.description)}</span></li>`);
  const confidence = Number.isFinite(profile.profileConfidence) ? `${Math.round(profile.profileConfidence * 100)}%` : "";
  const contents = profile.isETF
    ? `<div class="company-model-grid"><div class="profile-tag-group"><span>${t("etfProfile")}</span><div class="profile-fact-row"><b>${t("leveraged")}</b><span>${profile.leveraged ? t("yes") : t("no")}</span><b>${t("direction")}</b><span>${profile.direction === "inverse" ? t("inverseDirection") : t("longDirection")}</span>${profile.underlying ? `<b>${t("underlying")}</b><span>${escapeHtml(profile.underlying)}</span>` : ""}</div></div></div>`
    : `<div class="company-model-grid">${profile.primaryClassification ? `<div class="profile-tag-group"><span>${t("primaryClassification")}</span><div><b>${escapeHtml(profile.primaryClassification)}</b></div></div>` : ""}${groups.visible?.traits ? `<div class="profile-tag-group"><span>${t("companyTraits")}</span><div>${tagPills(groups.traits)}</div></div>` : ""}${groups.visible?.lifecycle ? `<div class="profile-tag-group"><span>${t("lifecycle")}</span><div>${tagPills([groups.lifecycle])}</div></div>` : ""}${profile.lastProfileReview || confidence ? `<div class="profile-tag-group"><span>${t("lastReview")}</span><div class="profile-fact-row">${profile.lastProfileReview ? `<span>${formatDate(profile.lastProfileReview)}</span>` : ""}${confidence ? `<b>${t("profileConfidence")}</b><span>${confidence}</span>` : ""}</div></div>` : ""}</div>`;
  return `<section class="detail-section-card"><div class="detail-section-head"><h3>${profile.isETF ? t("etfProfile") : t("companyModel")}</h3></div>${contents}${applied.length ? `<div class="modifier-list"><div class="decision-list-title">${t("appliedModifiers")}</div><ul>${applied.join("")}</ul></div>` : ""}</section>`;
}

function renderDecisionPanel(row) {
  const horizon = decisionFor(row, state.decisionHorizon) ? state.decisionHorizon : "short";
  return `<section class="detail-tab-section"><section class="detail-section-card decision-final-cards"><div class="detail-section-head"><h3>${t("finalDecision")}</h3></div><p class="decision-card-hint">${t("decisionCardHint")}</p><div class="decision-core-grid">${horizonCoreCard(row, "short")}${horizonCoreCard(row, "mid")}${horizonCoreCard(row, "long")}</div></section>${renderDecisionPriceMap(row, horizon)}${renderWhyThisDecision(row, horizon)}${renderExecutionPlan(row, horizon)}${renderMarketRiskRegime(row)}${renderCompanyModel(row)}</section>`;
}

function renderDetailModal() {
  const modal = $("#detailModal");
  const row = state.rows.find((item) => item.ticker === state.selectedTicker) || state.rows[0];
  if (!modal || !row) return;
  modal.hidden = !state.modalOpen;
  document.body.classList.toggle("modal-open", state.modalOpen);
  if (!state.modalOpen) return;
  const tabPanels = {
    summary: renderDecisionPanel(row),
    technical: renderTechnicalPanel(row),
    market: renderMarketPanel(row),
  };
  $(".detail-sheet").innerHTML = `
    <button class="detail-close" type="button" aria-label="${t("close")}">×</button>
    <div class="detail-sheet-header detail-sheet-header-dark"><div class="detail-sheet-stamp">${t("updated")} ${formatDate(row.updatedAt || state.snapshot?.updatedAt)}</div></div>
    ${renderProfileHeader(row)}
    <nav class="detail-tabs" role="tablist">${["summary", "technical", "market"].map((tab) => `<button class="detail-tab${state.activeTab === tab ? " active" : ""}" type="button" data-detail-tab="${tab}">${t(tab === "summary" ? "aiDecision" : tab)}</button>`).join("")}</nav>
    <div class="detail-tab-panel">${tabPanels[state.activeTab]}</div>
  `;
}

function applyLanguage() {
  $("#appTitle").textContent = t("appTitle");
  $("#stocksTitle").textContent = t("stocks");
  $("#sharedWatchlistHint").textContent = t("shared");
  $("#tickerInputLabel").textContent = t("search");
  $("#tickerInput").placeholder = t("search");
  $("#addStockButton").textContent = t("add");
  const manualRefresh = $("#manualRefreshButton");
  manualRefresh.textContent = state.refreshing ? t("refreshing") : t("refresh");
  manualRefresh.disabled = state.refreshing;
  manualRefresh.setAttribute("aria-busy", String(state.refreshing));
  $("#lastRefreshLabel").textContent = `${t("lastRefresh")}: ${formatRefreshTime(state.lastRefreshAt)}`;
  $("#sortTickerLabel").textContent = t("ticker");
  $("#sortTypeLabel").textContent = t("type");
  $("#sortChangeLabel").textContent = t("dayMove");
  document.querySelectorAll(".lang-btn").forEach((button) => button.classList.toggle("active", button.dataset.lang === state.language));
}

function render() {
  applyLanguage();
  renderStockList();
  renderDetailModal();
  document.querySelectorAll(".sort-btn").forEach((button) => {
    const active = button.dataset.sortKey === state.sort.key;
    button.classList.toggle("active", active);
    const indicator = button.querySelector(".sort-indicator");
    if (indicator) indicator.textContent = active ? (state.sort.direction === "asc" ? "↑" : "↓") : "↕";
  });
  document.querySelectorAll(".filter-btn").forEach((button) => button.classList.toggle("active", button.dataset.marketFilter === state.marketFilter));
}

function persistSnapshot(snapshot) {
  try { localStorage.setItem(SNAPSHOT_CACHE_KEY, JSON.stringify(snapshot)); } catch { /* storage is optional */ }
}

function persistWatchlist() {
  try { localStorage.setItem(WATCHLIST_CACHE_KEY, JSON.stringify(state.watchlist)); } catch { /* storage is optional */ }
}

function applySnapshot(snapshot, { persist = true, renderSnapshot = true } = {}) {
  state.snapshot = snapshot;
  const market = snapshot?.marketContext || snapshot?.market_context || {};
  const quotes = snapshot?.quotes || {};
  // A dashboard refresh intentionally rebuilds canonical technical features
  // and all three stateless Price Landscapes from this snapshot.  No prior
  // decision, range, or selected cluster is passed into DecisionEngine.
  const baseRows = state.watchlist.map((ticker) => buildRow(ticker, quotes[ticker] || {}, market, { deferDecision: true }));
  const rowsByTicker = Object.fromEntries(baseRows.map((row) => [row.ticker, row]));
  state.rows = baseRows.map((row) => {
    const underlying = row.classification?.isETF ? rowsByTicker[row.classification.underlyingTicker] : null;
    const decision = row.ready && window.DecisionEngine?.decide
      ? window.DecisionEngine.decide({
        ticker: row.ticker, price: row.price, technicalFeatures: row.technicalFeatures, marketContext: market,
        classification: row.classification, metadata: row.quote.metadata || {}, language: state.language,
        underlyingTechnicalFeatures: underlying?.technicalFeatures || null, underlyingPrice: underlying?.price ?? null,
      }) : null;
    return { ...row, decision };
  });
  if (!state.selectedTicker || !state.rows.some((row) => row.ticker === state.selectedTicker)) state.selectedTicker = state.rows[0]?.ticker || null;
  if (persist) persistSnapshot(snapshot);
  if (renderSnapshot) render();
}

async function loadWatchlist() {
  let cached = [];
  try { cached = JSON.parse(localStorage.getItem(WATCHLIST_CACHE_KEY) || "[]"); } catch { cached = []; }
  state.watchlist = uniqueTickers(cached.length ? cached : DEFAULT_WATCHLIST);
  try {
    const response = await fetch(WATCHLIST_API_URL);
    if (!response.ok) throw new Error(`watchlist request failed (${response.status})`);
    const payload = await response.json();
    const remote = (payload.items || payload.watchlist || []).map((item) => typeof item === "string" ? item : item.ticker);
    if (remote.length) state.watchlist = uniqueTickers(remote);
    persistWatchlist();
  } catch {
    $("#watchlistSyncWarning").hidden = false;
  }
}

function refreshUsesLiveData(source) {
  return source === "manual" || source === "auto";
}

async function runFullRefresh({ source = "initial" } = {}) {
  if (!state.watchlist.length) return null;
  // Manual and scheduled refreshes intentionally share this exact transaction
  // and in-flight promise. This prevents a slower earlier HTTP response from
  // overwriting a newer applied snapshot or starting duplicate live refreshes.
  if (state.refreshPromise) return state.refreshPromise;
  const refreshId = ++state.refreshGeneration;
  state.refreshing = true;
  state.refreshPhase = "refreshing_data";
  render();
  const refreshWork = (async () => {
    let applied = false;
    try {
      const params = new URLSearchParams({ tickers: state.watchlist.join(",") });
      // Both user-triggered and hourly automatic refreshes request the same
      // force-live server path. Initial cache hydration and watchlist edits can
      // still use this full pipeline without forcing a provider refresh.
      if (refreshUsesLiveData(source)) {
        params.set("force", "true");
        // A live Dashboard refresh is a server-side watchlist transaction.
        // It must not be limited to the first small provider-safe batch: the
        // endpoint refreshes every requested ticker, then returns one coherent
        // cache snapshot for the existing client-side decision calculation.
        params.set("full_refresh", "true");
      }
      const response = await fetch(`${API_URL}?${params.toString()}`);
      if (!response.ok) throw new Error(`market request failed (${response.status})`);
      const snapshot = await response.json();
      if (!hasUsableSnapshot(snapshot)) throw new Error("market request returned no usable dashboard snapshot");
      if (refreshId !== state.refreshGeneration) return null;

      state.refreshPhase = "recalculating";
      // This synchronous step rebuilds canonical Technical features and every
      // Short/Mid/Long final Decision from the newly returned snapshot.
      applySnapshot(snapshot, { renderSnapshot: false });
      if (refreshId !== state.refreshGeneration) return null;

      state.refreshPhase = "rendering";
      render();
      await afterBrowserPaint();
      if (refreshId !== state.refreshGeneration) return null;

      // Last Refresh is updated only after this exact snapshot's decision and
      // DOM have been applied. It remains the provider/cache freshness rather
      // than the button-click or merely HTTP-completion time.
      const refreshTime = snapshotRefreshTime(snapshot);
      if (refreshTime) {
        state.lastRefreshAt = refreshTime;
        persistLastRefresh(refreshTime);
      }
      state.lastAppliedAt = new Date().toISOString();
      applied = true;
      return snapshot;
    } catch (error) {
      console.error("Market refresh failed", error);
      if (!state.snapshot) {
        state.refreshPhase = "recalculating";
        applySnapshot({ quotes: {}, marketContext: {} }, { persist: false, renderSnapshot: false });
        state.refreshPhase = "rendering";
        render();
        await afterBrowserPaint();
      }
      return null;
    } finally {
      if (refreshId === state.refreshGeneration) {
        state.refreshing = false;
        state.refreshPhase = applied ? "complete" : "idle";
        render();
        await afterBrowserPaint();
        state.refreshPhase = "idle";
        state.refreshPromise = null;
      }
    }
  })();
  state.refreshPromise = refreshWork;
  return refreshWork;
}

async function addTicker(ticker) {
  const normalized = normalizeTicker(ticker);
  if (!normalized) return;
  try {
    const response = await fetch(WATCHLIST_API_URL, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ticker: normalized, market_type: "US" }) });
    if (!response.ok) throw new Error(`watchlist add failed (${response.status})`);
    const payload = await response.json();
    state.watchlist = uniqueTickers((payload.items || []).map((item) => typeof item === "string" ? item : item.ticker));
  } catch {
    state.watchlist = uniqueTickers([...state.watchlist, normalized]);
    $("#watchlistSyncWarning").hidden = false;
  }
  persistWatchlist();
  await runFullRefresh({ source: "watchlist" });
}

async function removeTicker(ticker) {
  try { await fetch(`${WATCHLIST_API_URL}/${encodeURIComponent(ticker)}`, { method: "DELETE" }); } catch { $("#watchlistSyncWarning").hidden = false; }
  state.watchlist = state.watchlist.filter((item) => item !== ticker);
  state.rows = state.rows.filter((item) => item.ticker !== ticker);
  persistWatchlist();
  render();
}

async function searchSymbols(query) {
  const menu = $("#symbolSearchMenu");
  const normalized = String(query || "").trim();
  if (normalized.length < 1) { menu.hidden = true; return; }
  try {
    const response = await fetch(`${SYMBOL_SEARCH_API_URL}?q=${encodeURIComponent(normalized)}&limit=8`);
    const payload = await response.json();
    const candidates = payload.candidates || [];
    menu.innerHTML = candidates.map((candidate) => `<button type="button" data-symbol="${escapeHtml(candidate.ticker || candidate.symbol)}"><strong>${escapeHtml(candidate.ticker || candidate.symbol)}</strong><span>${escapeHtml(candidate.name || "")}</span></button>`).join("");
    menu.hidden = !candidates.length;
  } catch { menu.hidden = true; }
}

function bindEvents() {
  $("#watchlistForm").addEventListener("submit", (event) => { event.preventDefault(); addTicker(state.selectedCandidate || $("#tickerInput").value); });
  $("#tickerInput").addEventListener("input", (event) => { state.selectedCandidate = null; $("#addStockButton").disabled = !event.target.value.trim(); searchSymbols(event.target.value); });
  $("#symbolSearchMenu").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-symbol]");
    if (!button) return;
    state.selectedCandidate = button.dataset.symbol;
    $("#tickerInput").value = state.selectedCandidate;
    $("#symbolSearchMenu").hidden = true;
    $("#addStockButton").disabled = false;
  });
  $("#manualRefreshButton").addEventListener("click", () => runFullRefresh({ source: "manual" }));
  $("#stockList").addEventListener("click", (event) => {
    const remove = event.target.closest("[data-remove-ticker]");
    if (remove) { event.stopPropagation(); removeTicker(remove.dataset.removeTicker); return; }
    const card = event.target.closest("[data-open-ticker]");
    if (card) { state.selectedTicker = card.dataset.openTicker; state.modalOpen = true; state.activeTab = "summary"; state.decisionHorizon = "short"; state.technicalHorizon = "short"; state.fibonacciHorizon = "short"; state.technicalSections = { fibonacci: false, foundation: false }; render(); }
  });
  document.querySelectorAll(".sort-btn").forEach((button) => button.addEventListener("click", () => {
    const key = button.dataset.sortKey;
    state.sort = state.sort.key === key ? { key, direction: state.sort.direction === "asc" ? "desc" : "asc" } : { key, direction: "asc" };
    render();
  }));
  document.querySelectorAll(".filter-btn").forEach((button) => button.addEventListener("click", () => { state.marketFilter = button.dataset.marketFilter || "all"; render(); }));
  document.querySelectorAll(".lang-btn").forEach((button) => button.addEventListener("click", () => { state.language = button.dataset.lang === "zh" ? "zh" : "en"; localStorage.setItem(LANGUAGE_CACHE_KEY, state.language); if (state.snapshot) applySnapshot(state.snapshot, { persist: false }); else render(); }));
  $("#detailModal").addEventListener("click", (event) => {
    if (event.target.closest(".detail-close") || event.target.matches(".detail-backdrop")) { state.modalOpen = false; render(); return; }
    const tab = event.target.closest("[data-detail-tab]");
    if (tab) { state.activeTab = tab.dataset.detailTab; renderDetailModal(); }
    const horizon = event.target.closest("[data-decision-horizon]");
    if (horizon) { state.decisionHorizon = horizon.dataset.decisionHorizon; renderDetailModal(); return; }
    const technicalHorizon = event.target.closest("[data-technical-horizon]");
    if (technicalHorizon) { state.technicalHorizon = technicalHorizon.dataset.technicalHorizon; renderDetailModal(); return; }
    const fibonacciHorizon = event.target.closest("[data-fibonacci-horizon]");
    if (fibonacciHorizon) { state.fibonacciHorizon = fibonacciHorizon.dataset.fibonacciHorizon; renderDetailModal(); return; }
    const technicalToggle = event.target.closest("[data-technical-toggle]");
    if (technicalToggle) { const section = technicalToggle.dataset.technicalToggle; state.technicalSections = { ...state.technicalSections, [section]: !state.technicalSections[section] }; renderDetailModal(); }
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && state.modalOpen) { state.modalOpen = false; render(); return; }
    if ((event.key === "Enter" || event.key === " ") && event.target?.matches?.("[data-decision-horizon]")) {
      event.preventDefault(); state.decisionHorizon = event.target.dataset.decisionHorizon; renderDetailModal();
    }
  });
}

async function start() {
  bindEvents();
  await loadWatchlist();
  try {
    const cached = JSON.parse(localStorage.getItem(SNAPSHOT_CACHE_KEY) || "null");
    if (cached?.quotes) {
      applySnapshot(cached, { persist: false });
      const cachedRefreshTime = snapshotRefreshTime(cached);
      if (cachedRefreshTime) {
        state.lastRefreshAt = cachedRefreshTime;
        persistLastRefresh(cachedRefreshTime);
      }
      state.lastAppliedAt = new Date().toISOString();
    }
  } catch { /* cache is optional */ }
  render();
  runFullRefresh({ source: "initial" });
  setInterval(() => runFullRefresh({ source: "auto" }), REFRESH_MS);
}

// Deliberately computes a compact view on demand; no debug payload is retained
// beyond the current row/decision already needed by the UI.
window.__decisionDebug = (ticker) => {
  const row = state.rows.find((item) => item.ticker === normalizeTicker(ticker));
  if (!row?.decision) return null;
  return Object.fromEntries(["short", "mid", "long"].map((horizon) => {
    const decision = decisionFor(row, horizon);
    return [horizon, {
      action: decision?.action, confidence: decision?.confidence, executionIntent: decision?.executionIntent,
      states: decision?.states, market: decision?.market?.horizonModifiers,
      priceLandscape: decision?.priceLandscape,
      reasons: decision?.reasons, guardrails: decision?.debug?.guardrails,
    }];
  }));
};

start();
