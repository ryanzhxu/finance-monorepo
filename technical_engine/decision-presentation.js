/* Lightweight, testable presentation helpers for the Decision UI. */
(function createDecisionPresentation(root) {
  "use strict";

  const finite = (value) => Number.isFinite(Number(value)) ? Number(value) : null;
  const validRange = (range) => finite(range?.low) != null && finite(range?.high) != null;
  const actionIntent = Object.freeze({ strong_buy: "enter", buy: "enter", accumulate: "add", hold: "hold", trim: "reduce", sell: "exit", avoid: "avoid" });
  const actionTone = Object.freeze({ strong_buy: "strong-buy", buy: "buy", accumulate: "accumulate", hold: "hold", trim: "trim", sell: "sell", avoid: "avoid" });
  const REASONS = Object.freeze({
    obv_participation_improving: { en: "OBV participation is improving.", zh: "OBV 参与度正在改善。" },
    obv_participation_weakening: { en: "OBV participation is weakening.", zh: "OBV 参与度正在走弱。" },
    moving_average_structure_bearish: { en: "Moving-average structure is bearish.", zh: "均线结构偏空。" },
    moving_average_structure_bullish: { en: "Moving-average structure is bullish.", zh: "均线结构偏多。" },
    relative_strength_improving: { en: "Relative strength is improving.", zh: "相对强弱正在改善。" },
    relative_strength_deteriorating: { en: "Relative strength is deteriorating.", zh: "相对强弱正在恶化。" },
    bearish_exhaustion_developing: { en: "Downside exhaustion is developing.", zh: "下行衰竭迹象正在形成。" },
    bullish_exhaustion_developing: { en: "Upside exhaustion is developing.", zh: "上行衰竭迹象正在形成。" },
    market_regime_cautious: { en: "Market regime is cautious.", zh: "市场风险环境偏谨慎。" },
    market_regime_risk_off: { en: "Market regime is risk-off.", zh: "市场处于风险规避状态。" },
    price_below_major_trend: { en: "Price remains below major trend structure.", zh: "价格仍低于主要趋势结构。" },
    primary_moving_average_structure_is_constructive: { en: "Primary moving-average structure is constructive.", zh: "主要均线结构具有建设性。" },
    primary_macd_structure_supports_the_current_upside_direction: { en: "Primary MACD structure supports the current upside direction.", zh: "主要 MACD 结构支持当前上行方向。" },
    relative_strength_is_confirming_versus_the_selected_benchmarks: { en: "Relative Strength is confirming versus the selected benchmarks.", zh: "相对强弱正在确认并跑赢所选基准。" },
    obv_and_volume_participation_are_confirming_accumulation: { en: "OBV and volume participation are confirming accumulation.", zh: "OBV 与成交量参与度正在确认资金吸筹。" },
    several_technical_structures_form_nearby_support_confluence: { en: "Several technical structures form nearby support confluence.", zh: "多个技术结构在附近形成支撑共振。" },
    primary_moving_average_structure_remains_bearish: { en: "Primary moving-average structure remains bearish.", zh: "主要均线结构仍然偏空。" },
    primary_macd_structure_still_confirms_downside_momentum: { en: "Primary MACD structure still confirms downside momentum.", zh: "主要 MACD 结构仍在确认下行动量。" },
    relative_strength_is_lagging_its_relevant_benchmarks: { en: "Relative Strength is lagging its relevant benchmarks.", zh: "相对强弱落后于相关基准。" },
    obv_or_price_volume_behavior_indicates_distribution: { en: "OBV or price-volume behavior indicates distribution.", zh: "OBV 或量价行为显示派发迹象。" },
    price_is_extended_into_layered_resistance_rather_than_support: { en: "Price is extended into layered resistance rather than support.", zh: "价格延伸至多层阻力，而非支撑区域。" },
    volatility_or_extension_risk_is_elevated: { en: "Volatility or extension risk is elevated.", zh: "波动或价格延伸风险偏高。" },
    downside_exhaustion_is_developing_while_repair_evidence_is_appearing: { en: "Downside exhaustion is developing while repair evidence is appearing.", zh: "下行衰竭正在形成，同时出现修复证据。" },
    upside_is_extended_and_marginal_momentum_participation_is_weakening: { en: "Upside is extended and marginal momentum/participation is weakening.", zh: "上行已延伸，边际动量与参与度正在走弱。" },
    systemic_volatility_or_synchronized_index_breakdown_creates_a_market_shock: { en: "Systemic volatility or synchronized index breakdown creates a market shock.", zh: "系统性波动或指数同步破位形成市场冲击。" },
    spy_qqq_trend_or_volatility_backdrop_is_risk_off: { en: "SPY/QQQ trend or volatility backdrop is risk-off.", zh: "SPY／QQQ 趋势或波动背景处于风险规避状态。" },
    market_volatility_or_broad_trend_calls_for_more_cautious_execution: { en: "Market volatility or broad trend calls for more cautious execution.", zh: "市场波动或整体趋势要求更谨慎执行。" },
    "10y_yield_backdrop_is_restrictive_for_rate_sensitive_risk": { en: "10Y yield backdrop is restrictive for rate-sensitive risk.", zh: "10 年期收益率环境限制利率敏感型风险。" },
    earnings_proximity_raises_event_uncertainty: { en: "Earnings proximity raises event uncertainty.", zh: "财报临近提高事件不确定性。" },
    inverse_underlying_direction_supports_the_etf_technical_setup: { en: "Inverse underlying direction supports the ETF technical setup.", zh: "标的指数方向正在支持该反向 ETF 的技术结构。" },
    underlying_direction_conflicts_with_the_inverse_etf_technical_setup: { en: "Underlying direction conflicts with the inverse ETF technical setup.", zh: "标的指数方向与该反向 ETF 的技术结构冲突。" },
    price_landscape_quality_is_insufficient_for_a_precise_execution_recommendation: { en: "Price landscape quality is insufficient for a precise execution recommendation.", zh: "价格区间结构质量不足，无法形成精确的执行建议。" },
    price_is_near_the_opportunity_range_but_has_not_entered_the_recommended_buy_add_zone: { en: "Price is near the opportunity range but has not entered the recommended buy/add zone.", zh: "当前价格接近机会区，但尚未进入推荐买入/加仓区。" },
    price_is_approaching_the_reduce_range_but_has_not_entered_the_recommended_reduce_exit_zone: { en: "Price is approaching the reduce range but has not entered the recommended reduce/exit zone.", zh: "当前价格接近减仓区，但尚未进入推荐减仓/退出区域。" },
    current_price_is_away_from_the_higher_quality_opportunity_range: { en: "Current price is away from the higher-quality opportunity range.", zh: "当前价格已远离质量更高的机会区。" },
    trend_and_confirmation_remain_strong_despite_price_entering_the_reduce_range: { en: "Trend and confirmation remain strong despite price entering the reduce range.", zh: "价格已进入减仓区，但趋势与确认信号仍然强劲。" },
    price_has_entered_the_reduce_range_so_additional_exposure_is_not_favored: { en: "Price has entered the reduce range, so additional exposure is not favored.", zh: "价格已进入减仓区，因此不宜进一步增加暴露。" },
    price_has_entered_the_reduce_range_without_enough_trend_confirmation_to_justify_holding_full_exposure: { en: "Price has entered the reduce range without enough trend confirmation to justify holding full exposure.", zh: "价格已进入减仓区，但趋势确认不足以支持维持完整暴露。" },
    price_position_alone_cannot_create_a_sell_without_bearish_structural_evidence: { en: "Price position alone cannot create a Sell without bearish structural evidence.", zh: "仅凭价格位置、缺乏空头结构证据时，不能形成卖出建议。" },
    bearish_structure_has_broken_down_the_exit_range_is_anchored_near_the_executable_current_area: { en: "Bearish structure has broken down; the exit range is anchored near the executable current area.", zh: "空头结构已破位，退出区已锚定在当前可执行价格附近。" },
  });

  function normalizeReason(reason) {
    if (reason && typeof reason === "object") return { code: String(reason.code || ""), text: String(reason.text || reason.label || ""), params: reason.params || {} };
    const text = String(reason || "");
    return { code: text.toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, ""), text, params: {} };
  }
  function translateReason(reason, language = "en") {
    const value = normalizeReason(reason);
    return REASONS[value.code]?.[language === "zh" ? "zh" : "en"] || value.text || value.code || "—";
  }
  function reasonList(items, language = "en", maximum = 5) { return (Array.isArray(items) ? items : []).slice(0, maximum).map((item) => translateReason(item, language)); }

  function executionSemantics(decision = {}) {
    const intent = decision.executionIntent || actionIntent[decision.action] || "hold";
    const labels = {
      enter: { opportunity: "recommendedBuyAddRange", reduce: "potentialReduceRange", invalidation: "riskInvalidation" },
      add: { opportunity: "recommendedBuyAddRange", reduce: "potentialReduceRange", invalidation: "riskInvalidation" },
      hold: { opportunity: "potentialAddRange", reduce: "potentialReduceRange", invalidation: "riskInvalidation" },
      reduce: { opportunity: "reevaluationRange", reduce: "recommendedReduceRange", invalidation: "riskInvalidation" },
      exit: { opportunity: "reevaluationRange", reduce: "recommendedExitRange", invalidation: "riskInvalidation" },
      avoid: { opportunity: "reevaluationRange", reduce: null, invalidation: null },
    };
    return { intent, ...(labels[intent] || labels.hold) };
  }

  function profileGroups(profile = {}) {
    if (profile.isETF) return { type: "etf", traits: [], lifecycle: null, visible: { traits: false, lifecycle: false } };
    const primary = String(profile.primaryClassification || "").toLowerCase();
    const traits = [...new Set((profile.companyTraits || []).filter(Boolean))].filter((trait) => String(trait).toLowerCase() !== primary);
    return { type: "stock", traits, lifecycle: profile.lifecycle || null, visible: { traits: traits.length > 0, lifecycle: Boolean(profile.lifecycle) } };
  }

  const labelAnchor = (point) => Number.isFinite(point.start) && Number.isFinite(point.end) ? (point.start + point.end) / 2 : point.position;
  function layoutPriceMap(points = [], minimumGap = 16) {
    const preferredSide = { opportunity: "top", current: "top", reduce: "bottom", invalidation: "bottom" };
    const lanes = { top: [], bottom: [] };
    const labels = [...points].map((point) => ({ ...point, anchor: labelAnchor(point) })).filter((point) => Number.isFinite(point.anchor)).sort((a, b) => a.anchor - b.anchor).map((point) => {
      const desired = preferredSide[point.id] || "top";
      const alternate = desired === "top" ? "bottom" : "top";
      let slot = null;
      // Reuse a compatible lane before adding a new one. The gap represents
      // the real label footprint rather than just the marker width, so labels
      // on the same visual row cannot collide when price levels are close.
      const desiredLane = lanes[desired].findIndex((last) => point.anchor - last >= minimumGap);
      if (desiredLane >= 0) slot = { side: desired, lane: desiredLane };
      // Preserve the normal visual hierarchy: a label with an unused preferred
      // side (for example, Opportunity on top) claims that side before it
      // considers reusing an opposite-side lane.
      if (!slot && lanes[desired].length === 0) slot = { side: desired, lane: 0 };
      const alternateLane = lanes[alternate].findIndex((last) => point.anchor - last >= minimumGap);
      if (!slot && alternateLane >= 0) slot = { side: alternate, lane: alternateLane };
      if (!slot) {
        // If the preferred side is already occupied by a nearby label, first
        // use the opposite side. This is the common current-price / range
        // collision and keeps the normal map compact instead of stacking both
        // labels on a too-tight top lane.
        const desiredBlocked = lanes[desired].length > 0;
        if (desiredBlocked && lanes[alternate].length < 2) {
          slot = { side: alternate, lane: lanes[alternate].length };
        } else if (lanes[desired].length < 2) {
          slot = { side: desired, lane: lanes[desired].length };
        } else if (lanes[alternate].length < 2) {
          slot = { side: alternate, lane: lanes[alternate].length };
        }
      }
      // There are at most four labels and four two-sided lanes. This fallback
      // only protects malformed callers that pass more points; it preserves a
      // deterministic, readable location instead of throwing during render.
      if (!slot) {
        const side = lanes.top.length <= lanes.bottom.length ? "top" : "bottom";
        slot = { side, lane: Math.max(0, lanes[side].length - 1) };
      }
      lanes[slot.side][slot.lane] = point.anchor;
      return { ...point, labelSide: slot.side, labelLane: slot.lane + 1, labelPosition: Math.max(5, Math.min(95, point.anchor)) };
    });
    const topLanes = Math.max(0, ...labels.filter((point) => point.labelSide === "top").map((point) => point.labelLane));
    const bottomLanes = Math.max(0, ...labels.filter((point) => point.labelSide === "bottom").map((point) => point.labelLane));
    // Lane two uses a full label-height offset, not the old 22px increment.
    // Only dense maps grow taller; ordinary four-point maps remain compact.
    const hasSecondLane = topLanes > 1 || bottomLanes > 1;
    return { labels, topLanes, bottomLanes, trackHeight: hasSecondLane ? 220 : 140 };
  }

  function nearestRangeDistance(current, range) {
    if (!Number.isFinite(current) || !validRange(range)) return null;
    if (current >= range.low && current <= range.high) return { within: true, percent: 0 };
    const edge = current < range.low ? range.low : range.high;
    return { within: false, percent: (edge - current) / current * 100 };
  }

  function priceMapModel({ currentPrice, decision = {} } = {}) {
    const landscape = decision.priceLandscape || {};
    const current = finite(landscape.currentPrice) ?? finite(currentPrice);
    const execution = executionSemantics(decision);
    const points = [];
    if (validRange(landscape.opportunityRange)) points.push({ id: "opportunity", low: finite(landscape.opportunityRange.low), high: finite(landscape.opportunityRange.high), labelKey: execution.opportunity, distance: nearestRangeDistance(current, landscape.opportunityRange) });
    if (validRange(landscape.reduceRange)) points.push({ id: "reduce", low: finite(landscape.reduceRange.low), high: finite(landscape.reduceRange.high), labelKey: execution.reduce, distance: nearestRangeDistance(current, landscape.reduceRange) });
    const invalidation = finite(landscape.invalidation);
    if (invalidation != null) points.push({ id: "invalidation", value: invalidation, labelKey: execution.invalidation || "riskInvalidation", distance: current == null ? null : { within: false, percent: (invalidation - current) / current * 100 } });
    if (current != null) points.push({ id: "current", value: current, labelKey: "currentPrice", distance: null });
    const values = points.flatMap((point) => point.value != null ? [point.value] : [point.low, point.high]).filter(Number.isFinite);
    if (!values.length) return { execution, points: [], labels: [], legend: [], min: null, max: null, position: () => null };
    let min = Math.min(...values); let max = Math.max(...values);
    const padding = Math.max(Math.abs(current || max || 1) * 0.025, (max - min) * 0.12, 0.01);
    min -= padding; max += padding;
    const position = (value) => Math.max(0, Math.min(100, ((value - min) / (max - min)) * 100));
    const laidOut = layoutPriceMap(points.map((point) => point.value != null ? { ...point, position: position(point.value) } : { ...point, start: position(Math.min(point.low, point.high)), end: position(Math.max(point.low, point.high)) }));
    const seen = new Set();
    const legend = laidOut.labels.filter((point) => { if (seen.has(point.id)) return false; seen.add(point.id); return true; }).map((point) => ({ id: point.id, labelKey: point.labelKey }));
    return { execution, min, max, points: laidOut.labels, labels: laidOut.labels, legend, topLanes: laidOut.topLanes, bottomLanes: laidOut.bottomLanes, trackHeight: laidOut.trackHeight, position };
  }

  function positionGuidance(action, language = "en") {
    const messages = {
      strong_buy: { en: "High-conviction conditions and favorable execution support a more active allocation.", zh: "高一致性信号与有利执行条件支持更积极的仓位配置。" },
      buy: { en: "Current conditions support a normal entry.", zh: "当前条件支持正常介入。" },
      accumulate: { en: "Add exposure in stages rather than establishing a full position at once.", zh: "适合分批增加暴露，而非一次性建立完整仓位。" },
      hold: { en: "There is not enough evidence to add or reduce exposure now.", zh: "当前没有足够证据增加或减少风险暴露。" },
      trim: { en: "Risk/reward has deteriorated; consider reducing part of the exposure.", zh: "当前风险收益恶化，可考虑减少部分暴露。" },
      sell: { en: "The structure supports materially reducing risk exposure.", zh: "当前结构支持明显降低风险暴露。" },
      avoid: { en: "Current conditions do not support establishing a new position.", zh: "当前条件不适合建立新仓位。" },
    };
    return messages[action]?.[language === "zh" ? "zh" : "en"] || messages.hold[language === "zh" ? "zh" : "en"];
  }

  const api = Object.freeze({ actionIntent, actionTone, executionSemantics, normalizeReason, translateReason, reasonList, profileGroups, layoutPriceMap, nearestRangeDistance, priceMapModel, positionGuidance });
  root.DecisionPresentation = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
}(globalThis));
