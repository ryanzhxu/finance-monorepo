(function createMarketEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const lower = (value) => String(value || "").toLowerCase();

  function resolveContext(source = {}) {
    return source.market_context || source.market_engine || source || {};
  }

  function indexScore(index = {}) {
    const changes = [5, 20, 60, 120].map((days) => finite(index[`change_${days}d_pct`]));
    const weights = [0.18, 0.30, 0.30, 0.22];
    const available = changes.filter(Number.isFinite);
    const numeric = available.length
      ? changes.reduce((sum, value, indexPosition) => sum + (Number.isFinite(value) ? Math.tanh(value / 5) * 100 * weights[indexPosition] : 0), 0) / weights.reduce((sum, weight, indexPosition) => sum + (Number.isFinite(changes[indexPosition]) ? weight : 0), 0)
      : null;
    const trend = lower(index.trend);
    const interpreted = trend === "rising" ? 30 : trend === "falling" ? -30 : 0;
    return { score: Number.isFinite(numeric) ? clamp(numeric * 0.78 + interpreted * 0.22, -100, 100) : interpreted, available: available.length > 0 || Boolean(trend), changes, trend: index.trend || "unavailable" };
  }

  function yieldStance(yieldData = {}) {
    const value = finite(yieldData.value);
    const change5 = finite(yieldData.change_5d_bps);
    const change20 = finite(yieldData.change_20d_bps);
    const config = engine.config.market.yields;
    if (!Number.isFinite(value) && !Number.isFinite(change5) && !Number.isFinite(change20)) return { label: "unavailable", riskAdd: 0, available: false, value, change5, change20 };
    if (value >= config.severe || change20 >= config.rising20dBps * 1.35) return { label: "severe", riskAdd: 12, available: true, value, change5, change20 };
    if (value >= config.restrictive || change5 >= config.rising5dBps || change20 >= config.rising20dBps) return { label: "restrictive", riskAdd: 6, available: true, value, change5, change20 };
    if (lower(yieldData.trend) === "falling") return { label: "supportive", riskAdd: -2, available: true, value, change5, change20 };
    return { label: "neutral", riskAdd: 0, available: true, value, change5, change20 };
  }

  function earnings(metadata = {}) {
    const configured = finite(metadata.daysToEarnings ?? metadata.days_to_earnings);
    const date = metadata.earningsDate || metadata.earnings_date || metadata.next_earnings_date || null;
    const inferred = date ? Math.ceil((new Date(date).getTime() - Date.now()) / 86400000) : null;
    const daysToEarnings = Number.isFinite(configured) ? configured : inferred;
    const config = engine.config.market.earnings;
    const immediate = Number.isFinite(daysToEarnings) && daysToEarnings >= 0 && daysToEarnings <= config.immediateDays;
    const near = Number.isFinite(daysToEarnings) && daysToEarnings >= 0 && daysToEarnings <= config.nearDays;
    return { date, daysToEarnings, immediate, near, riskAdd: immediate ? config.immediateRiskAdd : near ? config.nearRiskAdd : 0, confidencePenalty: near ? config.confidencePenalty : 0 };
  }

  function evaluate(marketContext = {}, metadata = {}) {
    const context = resolveContext(marketContext);
    const vixData = context.vix || {};
    const vix = finite(vixData.value ?? vixData.current_value);
    const vix5 = finite(vixData.change_5d ?? vixData.change_5d_pct);
    const vix20 = finite(vixData.change_20d ?? vixData.change_20d_pct);
    const spy = indexScore(context.equity_trend?.spy || context.spy_trend || {});
    const qqq = indexScore(context.equity_trend?.qqq || context.qqq_trend || {});
    const synchronizedBreakdown = spy.score <= -34 && qqq.score <= -34;
    const synchronizedStrength = spy.score >= 24 && qqq.score >= 24;
    const vixConfig = engine.config.market.vix;
    const vixShock = vix >= vixConfig.shock || vix5 >= vixConfig.spike5d * 1.5 || vix20 >= vixConfig.spike20d * 1.35;
    const vixRiskOff = vix >= vixConfig.riskOff || vix5 >= vixConfig.spike5d || vix20 >= vixConfig.spike20d;
    const vixCautious = vix >= vixConfig.cautious || lower(vixData.trend) === "rising";
    let regime = "normal";
    if (vixShock || (synchronizedBreakdown && vixRiskOff)) regime = "shock";
    else if (synchronizedBreakdown || vixRiskOff) regime = "risk_off";
    else if (vixCautious || (spy.score < -10 && qqq.score < -10)) regime = "cautious";
    else if (synchronizedStrength && Number.isFinite(vix) && vix < vixConfig.cautious) regime = "risk_on";
    const yieldData = yieldStance(context.ten_year_yield || context.tenYearYield || {});
    const fearGreed = context.fear_greed || context.fearGreed || {};
    const fearGreedValue = finite(fearGreed.value ?? fearGreed.score);
    const earningsRisk = earnings(metadata);
    const regimeConfig = engine.config.market.regimes[regime];
    const reasons = [];
    if (regime === "shock") reasons.push("Systemic volatility or synchronized index breakdown creates a market shock.");
    else if (regime === "risk_off") reasons.push("SPY/QQQ trend or volatility backdrop is risk-off.");
    else if (regime === "cautious") reasons.push("Market volatility or broad trend calls for more cautious execution.");
    if (yieldData.label === "restrictive" || yieldData.label === "severe") reasons.push("10Y yield backdrop is restrictive for rate-sensitive risk.");
    if (earningsRisk.near) reasons.push("Earnings proximity raises event uncertainty.");
    return {
      regime, label: regime.replace(/_/g, "-").replace(/(^|-)([a-z])/g, (_, separator, char) => `${separator}${char.toUpperCase()}`),
      riskAddBase: regimeConfig.riskAdd, confidencePenaltyBase: regimeConfig.confidencePenalty,
      vix: { value: vix, change5d: vix5, change20d: vix20, trend: vixData.trend || "unavailable", shock: vixShock },
      spy, qqq, synchronizedBreakdown, synchronizedStrength, yield: yieldData,
      fearGreed: { value: fearGreedValue, label: fearGreed.label || "unavailable", trend: fearGreed.trend || "unavailable" },
      earnings: earningsRisk, reasons,
      dataQuality: Math.round(([Number.isFinite(vix), spy.available, qqq.available, yieldData.available, Number.isFinite(fearGreedValue)].filter(Boolean).length / 5) * 100),
    };
  }

  // Market adjusts risk and confidence only.  It deliberately never contributes
  // a directional vote; a Risk-On market cannot turn a weak stock into a Buy.
  function forHorizon(market = {}, horizon = "short", profile = {}) {
    const baseSensitivity = engine.config.horizons[horizon]?.marketSensitivity ?? 1;
    const modifier = profile.effectiveModifiers?.marketSensitivity || 1;
    const rateSensitivity = profile.effectiveModifiers?.rateSensitivity || 1;
    const eventSensitivity = profile.effectiveModifiers?.eventSensitivity || 1;
    const uncappedRiskAdd = (market.riskAddBase || 0) * baseSensitivity * modifier
      + (market.yield?.riskAdd || 0) * rateSensitivity * baseSensitivity
      + (market.earnings?.riskAdd || 0) * eventSensitivity;
    const riskAdd = clamp(uncappedRiskAdd, -4, engine.config.market.maxRiskAdd[horizon] ?? 24);
    return {
      regime: market.regime || "normal", sensitivity: baseSensitivity * modifier,
      riskAdd: Math.round(riskAdd), uncappedRiskAdd: Math.round(uncappedRiskAdd), marketRiskCap: engine.config.market.maxRiskAdd[horizon] ?? 24,
      confidencePenalty: Math.round((market.confidencePenaltyBase || 0) * baseSensitivity * modifier + (market.earnings?.confidencePenalty || 0) * eventSensitivity),
      shock: market.regime === "shock", reasons: market.reasons || [],
    };
  }

  engine.market = Object.freeze({ evaluate, forHorizon });
}(globalThis));
