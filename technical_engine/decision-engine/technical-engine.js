(function createTechnicalEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const mean = (values) => {
    const valid = values.filter(Number.isFinite);
    return valid.length ? valid.reduce((sum, value) => sum + value, 0) / valid.length : null;
  };
  const signedTanh = (value, scale = 1) => Number.isFinite(value) ? Math.tanh(value / scale) * 100 : 0;
  const availability = (feature) => feature?.availability === "available";
  const state = (value) => String(value || "").toLowerCase();
  const sign = (value) => value > 0 ? 1 : value < 0 ? -1 : 0;
  const percentileSeverity = (value, elevated, extreme) => !Number.isFinite(value) ? 0 : clamp((value - elevated) / Math.max(1, extreme - elevated), 0, 1) * 55 + (value >= extreme ? 45 : 0);
  const rounded = (value) => Number.isFinite(value) ? Math.round(value) : null;

  function groupedSeverity(values = []) {
    const weights = engine.config.risk.groupBlend;
    const ranked = values.filter(Number.isFinite).sort((left, right) => right - left);
    return clamp((ranked[0] || 0) * weights.primary + (ranked[1] || 0) * weights.secondary + (ranked[2] || 0) * weights.tertiary, 0, 100);
  }

  function horizonParts(features, horizon) {
    const config = engine.config.horizons[horizon];
    const set = features?.horizons?.[config.technicalKey] || {};
    const primary = config.primaryInterval;
    const maInterval = config.maInterval || primary;
    const early = config.earlyInterval;
    const first = (group = {}, key) => group[key] || { availability: "unavailable", interval: primary };
    const byInterval = (group = {}, interval) => Object.values(group).filter((item) => item?.interval === interval);
    return {
      config,
      set,
      primary,
      early,
      ma: (set.trend?.moving_averages ? byInterval(set.trend.moving_averages, maInterval) : []),
      earlyMa: (set.trend?.moving_averages ? byInterval(set.trend.moving_averages, early) : []),
      rsi: first(set.momentum?.rsi, `rsi_${config.rsiPeriod}_${primary}`),
      macd: first(set.momentum?.macd, `macd_${primary}`),
      earlyMacd: first(set.momentum?.macd, `macd_${early}`),
      adx: first(set.trend?.adx, `adx_14_${primary}`),
      atr: first(set.volatility?.atr, `atr_14_${primary}`),
      bands: first(set.volatility?.bollinger, `bollinger_${primary}`),
      kdj: first(set.momentum?.kdj, `kdj_9_${primary}`),
      obv: first(set.participation?.obv, `obv_${primary}`),
      relativeStrength: set.relative_strength || { availability: "unavailable" },
      volume: features?.volume || { availability: "unavailable" },
      position: features?.price_position || { availability: "unavailable" },
      fibonacci: features?.fibonacci_structure?.[config.fibonacciKey] || { status: "unavailable", retracement_levels: {}, extension_levels: {} },
      maStructure: set.trend?.ma_structure || {},
    };
  }

  function scoreSlope(value) {
    const scores = engine.config.componentScales.stateScores;
    const label = state(value);
    if (label.includes("rising") || label.includes("bullish")) return scores.rising;
    if (label.includes("falling") || label.includes("bearish")) return scores.falling;
    return 0;
  }

  function maStructureScore(maFeatures, structure, price, atr) {
    const config = engine.config.componentScales.ma;
    const usable = maFeatures.filter((item) => availability(item) && Number.isFinite(item.value));
    if (!usable.length) return { score: 0, available: false, components: { price: null, ordering: null, slopes: null, persistence: null } };
    const normalizedAtr = Number.isFinite(atr) && atr > 0 ? atr : Math.max(Math.abs(price || 0) * 0.02, 0.01);
    const priceScores = usable.map((item) => Number.isFinite(price) ? signedTanh((price - item.value) / normalizedAtr, config.priceAtrScale) : item.price_state === "above" ? 55 : item.price_state === "below" ? -55 : 0);
    const shortToLong = [...usable].sort((left, right) => Number(left.period || 0) - Number(right.period || 0));
    const orderingScores = shortToLong.slice(1).map((item, index) => signedTanh((shortToLong[index].value - item.value) / normalizedAtr, config.orderingAtrScale));
    const slopes = usable.map((item) => scoreSlope(item.slope?.state));
    const alignment = state(structure.alignment);
    const alignmentScore = alignment.includes("bullish") ? 30 : alignment.includes("bearish") ? -30 : alignment.includes("recover") ? 14 : alignment.includes("deteriorat") ? -14 : 0;
    const persistence = clamp(Math.abs(mean(slopes) || 0) * (usable.length / Math.max(1, maFeatures.length)), 0, 35) * sign((mean(priceScores) || 0) + (mean(orderingScores) || 0));
    const score = clamp(
      (mean(priceScores) || 0) * config.priceWeight
      + ((mean(orderingScores) || 0) + alignmentScore) * config.orderingWeight
      + (mean(slopes) || 0) * config.slopeWeight
      + persistence * config.persistenceWeight,
      -100,
      100,
    );
    return { score, available: true, components: { price: Math.round(mean(priceScores) || 0), ordering: Math.round(clamp((mean(orderingScores) || 0) + alignmentScore, -100, 100)), slopes: Math.round(mean(slopes) || 0), persistence: Math.round(persistence) } };
  }

  function macdStructureScore(macd, atr) {
    const config = engine.config.componentScales.macd;
    if (!availability(macd)) return { score: 0, available: false, components: {} };
    const denominator = Number.isFinite(atr) && atr > 0 ? atr : Math.max(Math.abs(macd.macd_line || 0) * 10, 1);
    const zero = macd.above_or_below_zero === "above_zero" ? 100 : macd.above_or_below_zero === "below_zero" ? -100 : 0;
    const spread = signedTanh((finite(macd.macd_line) ?? 0) - (finite(macd.signal_line) ?? 0), denominator * config.lineSignalAtrScale);
    const histogram = signedTanh(finite(macd.histogram) ?? 0, denominator * config.histogramAtrScale);
    const change = signedTanh(
      (finite(macd.histogram_change_1) ?? 0) * 0.50 + (finite(macd.histogram_change_3) ?? 0) * 0.30 + (finite(macd.histogram_change_5) ?? 0) * 0.20,
      denominator * config.histogramChangeAtrScale,
    );
    const crossover = macd.crossover_state === "bullish_cross" ? 100 : macd.crossover_state === "bearish_cross" ? -100 : 0;
    const momentumState = state(macd.state);
    const interpreted = momentumState.includes("accelerating_bullish") ? 82
      : momentumState.includes("decelerating_bullish") ? 34
        : momentumState.includes("recovering_bearish") ? -18
          : momentumState.includes("accelerating_bearish") ? -82
            : macd.improving_or_deteriorating === "improving" ? 36
              : macd.improving_or_deteriorating === "deteriorating" ? -36 : 0;
    const score = clamp(zero * config.zeroWeight + spread * config.spreadWeight + histogram * config.histogramWeight + change * config.changeWeight + crossover * config.crossoverWeight + interpreted * config.stateWeight, -100, 100);
    return { score, available: true, components: { zero: Math.round(zero), lineSignal: Math.round(spread), histogram: Math.round(histogram), histogramChange: Math.round(change), crossover: Math.round(crossover), interpreted: Math.round(interpreted) } };
  }

  function adxDirectionScore(adx) {
    const config = engine.config.componentScales.adx;
    if (!availability(adx) || !Number.isFinite(adx.adx) || !Number.isFinite(adx.plus_di) || !Number.isFinite(adx.minus_di)) return { score: 0, available: false, components: {} };
    const strength = clamp((adx.adx - config.low) / (config.fullStrength - config.low), 0, 1);
    const diSpread = clamp((adx.plus_di - adx.minus_di) / Math.max(1, adx.plus_di + adx.minus_di), -1, 1);
    const score = clamp(diSpread * strength * 100 / config.diSpreadScale, -100, 100);
    return { score, available: true, components: { adx: Math.round(adx.adx), strength: Math.round(strength * 100), diSpread: Math.round(diSpread * 100), slope: scoreSlope(adx.slope?.state) } };
  }

  function normalizeWeights(weights, modifiers = {}) {
    const adjusted = Object.fromEntries(Object.entries(weights).map(([key, value]) => [key, Math.max(0, value * (1 + (modifiers[key] || 0)))]));
    const total = Object.values(adjusted).reduce((sum, value) => sum + value, 0) || 1;
    return Object.fromEntries(Object.entries(adjusted).map(([key, value]) => [key, value / total]));
  }

  function directionalAgreement(direction, evidence) {
    if (!Number.isFinite(direction) || Math.abs(direction) < 8) return 45;
    const signedEvidence = Number.isFinite(evidence) ? evidence : 0;
    return clamp(50 + sign(direction) * signedEvidence * 0.50, 0, 100);
  }

  function relativeStrengthEvidence(rs, direction, profile) {
    if (rs.availability !== "available") return { score: 0, confirmation: 0, available: false, components: {} };
    const weights = profile.effectiveModifiers.benchmarkWeights;
    const vsSpy = finite(rs.primary?.vs_spy);
    const vsQqq = finite(rs.primary?.vs_qqq);
    const stockReturn = finite(rs.primary?.stock_return);
    const benchmarkWeight = (Number.isFinite(vsSpy) ? weights.spy : 0) + (Number.isFinite(vsQqq) ? weights.qqq : 0);
    const benchmark = benchmarkWeight > 0 ? ((Number.isFinite(vsSpy) ? vsSpy * weights.spy : 0) + (Number.isFinite(vsQqq) ? vsQqq * weights.qqq : 0)) / benchmarkWeight : null;
    const config = engine.config.componentScales.relativeStrength;
    const persistence = rs.consistency?.state === "improving" ? config.persistenceBonus : rs.consistency?.state === "deteriorating" ? -config.persistenceBonus : 0;
    const signedScore = clamp(((benchmark ?? 0) * config.benchmarkWeight + (stockReturn ?? 0) * config.stockReturnWeight) * config.returnScale + persistence, -100, 100);
    return { score: signedScore, confirmation: directionalAgreement(direction, signedScore), available: true, components: { stockReturn, vsSpy, vsQqq, benchmark, persistence, signedScore: Math.round(signedScore) } };
  }

  function participationEvidence(obv, volume, direction) {
    const valid = availability(obv) || availability(volume);
    if (!valid) return { score: 0, confirmation: 0, available: false, components: {} };
    const weights = engine.config.componentScales.participation;
    const trend = obv.trend === "rising" ? 100 : obv.trend === "falling" ? -100 : 0;
    const divergence = obv.divergence === "bullish_divergence" ? 100 : obv.divergence === "bearish_divergence" ? -100 : 0;
    const confirmation = obv.price_obv_confirmation === "confirming_uptrend" || volume.trend?.price_volume_confirmation === "bullish_confirmation" ? 100
      : obv.price_obv_confirmation === "confirming_downtrend" || volume.trend?.price_volume_confirmation === "bearish_confirmation" ? -100 : 0;
    const rvol = finite(volume.relative_volume?.displayed_rvol ?? volume.relative_volume?.rvol_20d);
    const rvolScore = !Number.isFinite(rvol) ? 0 : rvol >= 1.2 ? sign((trend + confirmation) || direction) * clamp((rvol - 1) * 70, 0, 100) : rvol < 0.7 ? -sign(direction || trend) * 30 : 0;
    const volumeTrend = volume.trend?.volume_trend === "expanding" ? sign((trend + confirmation) || direction) * 65 : volume.trend?.volume_trend === "contracting" ? -sign(direction || trend) * 45 : 0;
    const signedScore = clamp(trend * weights.obvWeight + divergence * weights.divergenceWeight + confirmation * weights.confirmationWeight + rvolScore * weights.rvolWeight + volumeTrend * weights.volumeTrendWeight, -100, 100);
    return { score: signedScore, confirmation: directionalAgreement(direction, signedScore), available: true, components: { obvTrend: trend, divergence, priceVolume: confirmation, rvol, volumeTrend, signedScore: Math.round(signedScore) } };
  }

  function rsiConfirmation(rsi, direction) {
    if (!availability(rsi) || !Number.isFinite(rsi.value)) return { score: 0, confirmation: 0, available: false, components: {} };
    const config = engine.config.componentScales.rsi;
    let level = 0;
    if (direction >= 0) level = rsi.value >= config.healthyBullish[0] && rsi.value <= config.healthyBullish[1] ? 86 : rsi.value > config.healthyBullish[1] ? 58 : rsi.value >= 45 ? 52 : 28;
    else level = rsi.value <= config.healthyBearish[1] && rsi.value >= config.healthyBearish[0] ? 86 : rsi.value < config.healthyBearish[0] ? 58 : rsi.value <= 55 ? 52 : 28;
    const slope = scoreSlope(rsi.slope?.state);
    const divergence = rsi.divergence === "bullish_divergence" ? 28 : rsi.divergence === "bearish_divergence" ? -28 : 0;
    const confirmation = clamp(level + sign(direction || 1) * slope * 0.28 + sign(direction || 1) * divergence * 0.28, 0, 100);
    return { score: sign(direction || 1) * (confirmation - 50) * 2, confirmation, available: true, components: { value: rsi.value, level, slope, divergence, confirmation: Math.round(confirmation) } };
  }

  function adxConfirmation(adxDirection, direction) {
    if (!adxDirection.available) return { confirmation: 0, available: false, components: {} };
    // DI direction is already used by Direction.  Confirmation deliberately
    // uses trend strength plus only a small alignment check, so ADX does not
    // cast a second full directional vote.
    const strength = Number(adxDirection.components.strength) || 0;
    const aligned = sign(direction) !== 0 && sign(adxDirection.score) === sign(direction);
    const value = clamp(strength * 0.72 + (aligned ? 18 : 0), 0, 100);
    return { confirmation: value, available: true, components: { ...adxDirection.components, directionAlignment: aligned ? "aligned" : "not_aligned", confirmation: Math.round(value) } };
  }

  function riskState(parts, price, primaryMa) {
    const config = engine.config.risk;
    const atrPct = finite(parts.atr.atr_pct);
    const atrPercentile = finite(parts.atr.atr_percentile_pct);
    const atrPctSeverity = percentileSeverity(atrPct, config.atrPct.mild, config.atrPct.extreme);
    const atrPercentileSeverity = percentileSeverity(atrPercentile, config.atrPercentile.elevated, config.atrPercentile.extreme);
    const volatilityRegimeSeverity = config.volatilityRegime[String(parts.atr.volatility_regime || "unavailable").toLowerCase()] || 0;
    const percentB = finite(parts.bands.percent_b);
    const bandExtension = !Number.isFinite(percentB) ? 0 : clamp(Math.max(0, Math.abs(percentB - 0.5) - 0.5) / Math.max(0.01, config.bollingerPercentB.extreme - config.bollingerPercentB.extended) * 100, 0, 100);
    const bollingerWidthSeverity = percentileSeverity(finite(parts.bands.bandwidth_percentile), config.bollingerWidthPercentile.elevated, config.bollingerWidthPercentile.extreme);
    const averageMa = mean(primaryMa.filter((item) => Number.isFinite(item.value)).map((item) => item.value));
    const atr = finite(parts.atr.value);
    const maDistance = Number.isFinite(price) && Number.isFinite(averageMa) && Number.isFinite(atr) && atr > 0 ? Math.abs(price - averageMa) / atr : null;
    const maExtension = percentileSeverity(maDistance, config.maExtensionAtr.elevated, config.maExtensionAtr.extreme);
    const rsiValue = finite(parts.rsi.value);
    const rsiExtreme = !Number.isFinite(rsiValue) ? 0 : Math.max(percentileSeverity(rsiValue, config.rsi.elevatedHigh, config.rsi.extremeHigh), percentileSeverity(100 - rsiValue, 100 - config.rsi.elevatedLow, 100 - config.rsi.extremeLow));
    const kdjValue = finite(parts.kdj.j);
    const kdjExtreme = !Number.isFinite(kdjValue) ? 0 : Math.max(percentileSeverity(kdjValue, config.kdj.elevated, config.kdj.extreme), percentileSeverity(-kdjValue, config.kdj.elevated, config.kdj.extreme));
    const oscillator = Math.max(rsiExtreme, kdjExtreme);
    const rvol = finite(parts.volume.relative_volume?.displayed_rvol ?? parts.volume.relative_volume?.rvol_20d);
    const abnormalVolume = percentileSeverity(rvol, config.rvol.elevated, config.rvol.extreme);
    // ATR percentile, volatility regime, and Bollinger width all describe the
    // same volatility episode.  ATR% supplies the absolute anchor; the other
    // observations merely corroborate it at a discounted rate.  A standalone
    // high percentile therefore cannot become an automatic extreme-risk floor.
    const relativeVolatility = Math.max(atrPercentileSeverity * 0.65, volatilityRegimeSeverity * 0.60, bollingerWidthSeverity * 0.55);
    const volatility = clamp(atrPctSeverity * 0.55 + relativeVolatility * 0.45, 0, 100);
    // Extension is similarly one group: MA distance, %B, RSI and KDJ are all
    // manifestations of price extension, rather than four independent fines.
    const extension = groupedSeverity([bandExtension, maExtension, oscillator]);
    const shock = ((volatility >= 70 || bandExtension >= 75) && abnormalVolume >= 50) ? 100 : 0;
    const eventShock = groupedSeverity([abnormalVolume * 0.65, shock]);
    const components = {
      volatility, extension, eventShock, shock,
      atrSeverity: atrPctSeverity, volatilityRegime: volatilityRegimeSeverity, bollingerWidth: bollingerWidthSeverity,
      oscillator, participation: abnormalVolume,
      volatilitySignals: {
        atrPct, atrPctSeverity, atrPercentile, atrPercentileSeverity, volatilityRegime: parts.atr.volatility_regime || "unavailable",
        volatilityRegimeSeverity, bollingerWidthPercentile: finite(parts.bands.bandwidth_percentile), bollingerWidthSeverity,
        relativeVolatility,
      },
      extensionSignals: { percentB, bollingerExtension: bandExtension, maDistance, maExtension, rsi: rsiValue, rsiExtreme, kdj: kdjValue, kdjExtreme, oscillator },
      eventShockSignals: { rvol, abnormalVolume, shock },
    };
    const risk = 100 * (1 - Object.entries(config.nonlinearImpacts).reduce((remaining, [key, impact]) => remaining * (1 - clamp(components[key], 0, 100) / 100 * impact), 1));
    const volatilityExtreme = atrPctSeverity >= 95 && atrPercentileSeverity >= 95 && volatilityRegimeSeverity >= 55;
    const extensionExtreme = extension >= 92 && (bandExtension >= 75 || maExtension >= 80) && oscillator >= 45;
    const extremeFloor = shock >= 100 ? config.extremeFloor.shock : volatilityExtreme ? config.extremeFloor.volatility : extensionExtreme ? config.extremeFloor.extension : 0;
    const score = clamp(Math.max(risk, extremeFloor), 0, 100);
    const label = config.labels.find(([limit]) => score < limit)?.[1] || "extreme";
    return {
      score, label,
      components: {
        volatility: rounded(volatility), extension: rounded(extension), eventShock: rounded(eventShock), shock: rounded(shock),
        atrSeverity: rounded(atrPctSeverity), volatilityRegime: rounded(volatilityRegimeSeverity), bollingerWidth: rounded(bollingerWidthSeverity),
        oscillator: rounded(oscillator), participation: rounded(abnormalVolume),
        volatilitySignals: Object.fromEntries(Object.entries(components.volatilitySignals).map(([key, value]) => [key, typeof value === "number" ? rounded(value) : value])),
        extensionSignals: Object.fromEntries(Object.entries(components.extensionSignals).map(([key, value]) => [key, typeof value === "number" ? rounded(value) : value])),
        eventShockSignals: Object.fromEntries(Object.entries(components.eventShockSignals).map(([key, value]) => [key, typeof value === "number" ? rounded(value) : value])),
        extremeOverride: volatilityExtreme ? "corroborated_volatility" : extensionExtreme ? "corroborated_extension" : shock >= 100 ? "volume_price_shock" : null,
      },
      atr, atrPct, atrPercentile, maDistance, rvol,
    };
  }

  function fibRole(fibonacci, kind) {
    const direction = fibonacci?.swing_direction;
    if (direction === "up_swing") return kind === "retracement" ? "support" : "reduce";
    if (direction === "down_swing") return kind === "retracement" ? "reduce" : "support";
    return "both";
  }

  function movingAverageRole(item) {
    const slope = state(item?.slope?.state);
    if (slope.includes("rising") || slope.includes("bullish")) return "support";
    if (slope.includes("falling") || slope.includes("bearish")) return "reduce";
    return "both";
  }

  function structuralLevels(parts) {
    const levels = [];
    const categories = engine.config.componentScales.opportunity.unifiedConfluence.categoryForType;
    const add = (price, type, weight, label, role = "both", sourceTimeframe = null) => {
      if (Number.isFinite(price) && price > 0) levels.push({ price, type, category: categories[type] || type, weight, label, role, sourceTimeframe });
    };
    Object.values(parts.fibonacci.retracement_levels || {}).forEach((item) => add(item?.price, "fib", engine.config.componentScales.opportunity.structuralLevelWeight.fib, `Fib retracement ${item?.label || ""}`, fibRole(parts.fibonacci, "retracement"), parts.fibonacci.source_timeframe || null));
    Object.values(parts.fibonacci.extension_levels || {}).forEach((item) => add(item?.price, "fib", engine.config.componentScales.opportunity.structuralLevelWeight.fib, `Fib extension ${item?.label || ""}`, fibRole(parts.fibonacci, "extension"), parts.fibonacci.source_timeframe || null));
    // Short 4H Fibonacci may use independently-derived Daily anchors only as
    // secondary confirmation.  They carry deliberately lower structural
    // weight and never replace the horizon's primary Fibonacci source.
    const dailyConfirmation = parts.fibonacci.secondary_confirmation || {};
    Object.values(dailyConfirmation.retracement_levels || {}).forEach((item) => add(item?.price, "daily_fib_confirmation", engine.config.componentScales.opportunity.structuralLevelWeight.daily_fib_confirmation, `Daily Fib confirmation ${item?.label || ""}`, fibRole(dailyConfirmation, "retracement"), dailyConfirmation.source_timeframe || null));
    Object.values(dailyConfirmation.extension_levels || {}).forEach((item) => add(item?.price, "daily_fib_confirmation", engine.config.componentScales.opportunity.structuralLevelWeight.daily_fib_confirmation, `Daily Fib confirmation extension ${item?.label || ""}`, fibRole(dailyConfirmation, "extension"), dailyConfirmation.source_timeframe || null));
    add(parts.fibonacci.swing_low, "swing", engine.config.componentScales.opportunity.structuralLevelWeight.swing, "Swing low", "support", parts.fibonacci.source_timeframe || null);
    add(parts.fibonacci.swing_high, "swing", engine.config.componentScales.opportunity.structuralLevelWeight.swing, "Swing high", "reduce", parts.fibonacci.source_timeframe || null);
    add(parts.position.high_52w, "price_structure", engine.config.componentScales.opportunity.structuralLevelWeight.price_structure, "52-week high", "reduce", "1d");
    add(parts.position.low_52w, "price_structure", engine.config.componentScales.opportunity.structuralLevelWeight.price_structure, "52-week low", "support", "1d");
    add(parts.position.all_time_high, "price_structure", engine.config.componentScales.opportunity.structuralLevelWeight.price_structure, "All-time high", "reduce", "1d");
    [...parts.ma, ...parts.earlyMa].forEach((item) => add(item.value, "moving_average", engine.config.componentScales.opportunity.structuralLevelWeight.moving_average, `${String(item.indicator || "MA").toUpperCase()} ${item.period} (${item.interval || ""})`, movingAverageRole(item), item.interval || null));
    add(parts.bands.lower_band, "bollinger", engine.config.componentScales.opportunity.structuralLevelWeight.bollinger, "Bollinger lower", "support", parts.primary);
    add(parts.bands.middle_band, "bollinger", engine.config.componentScales.opportunity.structuralLevelWeight.bollinger, "Bollinger middle", "both", parts.primary);
    add(parts.bands.upper_band, "bollinger", engine.config.componentScales.opportunity.structuralLevelWeight.bollinger, "Bollinger upper", "reduce", parts.primary);
    return levels.filter((level, index, all) => !all.slice(0, index).some((prior) => prior.type === level.type && prior.label === level.label && Math.abs(prior.price - level.price) < 0.000001));
  }

  function categoryEvidence(members, seedPrice) {
    const config = engine.config.componentScales.opportunity.unifiedConfluence;
    const buckets = new Map();
    members.forEach((member) => {
      const bucket = buckets.get(member.category) || [];
      bucket.push(member);
      buckets.set(member.category, bucket);
    });
    const categories = [...buckets.entries()].map(([category, entries]) => {
      const representative = [...entries].sort((left, right) => Math.abs(left.price - seedPrice) - Math.abs(right.price - seedPrice) || right.weight - left.weight)[0];
      const cap = config.categoryContributionCap[category] ?? representative.weight;
      const contribution = Math.min(cap, Math.max(config.categoryQualityFloor, representative.weight));
      return { category, entries, representative, contribution };
    });
    const contribution = categories.reduce((sum, item) => sum + item.contribution, 0);
    const crossCategoryBonus = Math.max(0, categories.length - 1) * config.crossCategoryBonus;
    const total = contribution + crossCategoryBonus;
    const centreWeight = categories.reduce((sum, item) => sum + item.contribution, 0) || 1;
    const center = categories.reduce((sum, item) => sum + item.representative.price * item.contribution, 0) / centreWeight;
    return {
      center, confluence: total, quality: total,
      independentStructures: categories.length,
      categoryBreakdown: categories.map((item) => ({
        category: item.category, levelCount: item.entries.length, contribution: item.contribution,
        representative: { price: item.representative.price, type: item.representative.type, label: item.representative.label },
      })),
    };
  }

  function clusterLevels(levels, price, atr, side) {
    if (!Number.isFinite(price) || !Number.isFinite(atr) || atr <= 0) return null;
    const config = engine.config.componentScales.opportunity;
    // Relative location decides whether a level can be considered below or
    // above current price. Its structural role is a bounded quality modifier,
    // not a hard exclusion: this keeps confirmed structure usable across a
    // breakout while preventing an opposite-role level from winning merely
    // because current price crossed it.
    const candidates = levels.filter((level) => side === "support"
      ? level.price <= price + atr * config.supportEligibilityAtr
      : level.price >= price + atr * config.reduceEligibilityAtr);
    const ranked = candidates.map((seed) => {
      const members = candidates.filter((item) => Math.abs(item.price - seed.price) <= atr * config.confluenceBandAtr);
      const evidence = categoryEvidence(members, seed.price);
      const roleWeight = members.reduce((sum, item) => sum + Math.max(0.01, item.weight), 0) || 1;
      const roleAlignment = members.reduce((sum, item) => {
        const alignment = item.role === side ? 1 : item.role === "both" ? 0.7 : 0.25;
        return sum + alignment * Math.max(0.01, item.weight);
      }, 0) / roleWeight;
      const quality = evidence.quality * (1 - config.unifiedConfluence.roleAlignmentWeight + roleAlignment * config.unifiedConfluence.roleAlignmentWeight);
      return { ...evidence, members, quality, roleAlignment, distanceAtr: Math.abs(evidence.center - price) / atr };
    }).sort((left, right) => right.quality - left.quality || left.distanceAtr - right.distanceAtr);
    const unique = [];
    ranked.forEach((candidate) => {
      if (!unique.some((prior) => Math.abs(prior.center - candidate.center) <= atr * config.clusterDedupAtr)) unique.push(candidate);
    });
    return unique.slice(0, config.clusterCandidateLimit);
  }

  function priceOpportunity(parts, price, atr) {
    const levels = structuralLevels(parts);
    const supportClusters = clusterLevels(levels, price, atr, "support") || [];
    const resistanceClusters = clusterLevels(levels, price, atr, "resistance") || [];
    const support = supportClusters[0] || null;
    const resistance = resistanceClusters[0] || null;
    const config = engine.config.componentScales.opportunity;
    const qualityReference = config.unifiedConfluence.qualityReference;
    const supportScore = support ? clamp(support.confluence / qualityReference * config.maxConfluenceScore, 0, config.maxConfluenceScore) : 0;
    const resistanceScore = resistance ? clamp(resistance.confluence / qualityReference * config.maxConfluenceScore, 0, config.maxConfluenceScore) : 0;
    const percentB = finite(parts.bands.percent_b);
    const extension = !Number.isFinite(percentB) ? 0 : percentB > 1 ? -clamp((percentB - 1) * 100, 0, config.extensionWeight) : percentB < 0 ? clamp(-percentB * 100, 0, config.extensionWeight) : 0;
    const raw = clamp(supportScore - resistanceScore + extension, -100, 100);
    return {
      score: raw,
      components: { supportConfluence: Math.round(supportScore), resistanceConfluence: Math.round(resistanceScore), bollingerExtension: Math.round(extension), selectedSupport: support ? { price: support.center, members: support.members.length, labels: support.members.slice(0, 4).map((item) => item.label) } : null, selectedResistance: resistance ? { price: resistance.center, members: resistance.members.length, labels: resistance.members.slice(0, 4).map((item) => item.label) } : null },
      executionContext: { levels, support, resistance, supportClusters, resistanceClusters, atr, structureModel: "unified_category_confluence" },
    };
  }

  function dataQuality(parts, directionComponents, confirmationComponents) {
    const coreDirection = [directionComponents.ma.available, directionComponents.macd.available, directionComponents.adx.available, directionComponents.early.available];
    const coreConfirmation = [confirmationComponents.relativeStrength.available, confirmationComponents.participation.available, confirmationComponents.rsi.available, confirmationComponents.adx.available];
    const technical = mean([...coreDirection, ...coreConfirmation].map(Boolean).map(Number)) * 100;
    const structure = parts.fibonacci.status === "available" || parts.fibonacci.status === "stale_swing" ? 100 : 45;
    const volume = availability(parts.volume) ? 100 : 0;
    return { score: Math.round(technical * 0.76 + structure * 0.14 + volume * 0.10), components: { primaryDirection: coreDirection, confirmation: coreConfirmation, fibonacci: structure, volume } };
  }

  function signalPersistence(ma, macd, adx, relativeStrength) {
    const config = engine.config.stability.noHistory;
    const candidates = [];
    if (ma.available) {
      const value = clamp(Math.abs(Number(ma.components?.persistence) || 0) / 35 * 100, 0, 100);
      candidates.push({ key: "ma", value, weight: config.ma });
    }
    if (macd.available) {
      const change = Math.abs(Number(macd.components?.histogramChange) || 0);
      const stateScore = Math.abs(Number(macd.components?.interpreted) || 0);
      // 1/3/5-bar histogram changes encode the available canonical momentum
      // persistence without retaining an extra recommendation history series.
      const value = clamp(change * 0.58 + stateScore * 0.42, 0, 100);
      candidates.push({ key: "macd", value, weight: config.macd });
    }
    if (adx.available) {
      const value = clamp(Math.abs(Number(adx.components?.strength) || 0) * 0.78 + Math.abs(Number(adx.components?.slope) || 0) * 0.22, 0, 100);
      candidates.push({ key: "adx", value, weight: config.adx });
    }
    if (relativeStrength.available) {
      const consistency = Math.abs(Number(relativeStrength.components?.persistence) || 0) * 7;
      const directional = Math.min(32, Math.abs(Number(relativeStrength.score) || 0) * 0.35);
      candidates.push({ key: "relativeStrength", value: clamp(consistency + directional, 0, 100), weight: config.relativeStrength });
    }
    const weight = candidates.reduce((sum, item) => sum + item.weight, 0);
    if (!weight) return { score: config.unavailable, available: false, components: {} };
    const raw = candidates.reduce((sum, item) => sum + item.value * item.weight, 0) / weight;
    return {
      score: Math.round(clamp(raw, config.minimum, config.maximum)), available: true,
      components: Object.fromEntries(candidates.map((item) => [item.key, Math.round(item.value)])),
    };
  }

  function rankReasons(items, polarity) {
    return items.filter((item) => item && item.score > 0).sort((left, right) => right.score - left.score).slice(0, 5).map((item) => item.text || `${polarity}: ${item.label}`);
  }

  function evaluate(features = {}, horizon = "short", price = null, profile = { effectiveModifiers: blankProfileModifiers() }) {
    const parts = horizonParts(features, horizon);
    const profileModifiers = profile.effectiveModifiers || blankProfileModifiers();
    const atr = finite(parts.atr.value);
    const ma = maStructureScore(parts.ma, parts.maStructure, price, atr);
    const macd = macdStructureScore(parts.macd, atr);
    const adx = adxDirectionScore(parts.adx);
    const earlyMa = maStructureScore(parts.earlyMa, {}, price, atr);
    const earlyMacd = macdStructureScore(parts.earlyMacd, atr);
    // Long-term MA structure already uses long Daily data.  Its small Daily
    // early-signal sleeve is MACD-only so the same MA regime is not counted twice.
    const early = horizon === "long"
      ? { score: clamp(earlyMacd.score || 0, -100, 100), available: earlyMacd.available, components: { ma: null, macd: Math.round(earlyMacd.score || 0) } }
      : { score: clamp((earlyMa.score || 0) * 0.55 + (earlyMacd.score || 0) * 0.45, -100, 100), available: earlyMa.available || earlyMacd.available, components: { ma: Math.round(earlyMa.score || 0), macd: Math.round(earlyMacd.score || 0) } };
    const directionWeights = normalizeWeights(parts.config.directionWeights, profileModifiers.directionWeights);
    const directionComponents = { ma, macd, adx, early };
    const directionScore = clamp(Object.entries(directionWeights).reduce((sum, [key, weight]) => sum + (directionComponents[key].score || 0) * weight, 0), -100, 100);

    const relativeStrength = relativeStrengthEvidence(parts.relativeStrength, directionScore, profile);
    const participation = participationEvidence(parts.obv, parts.volume, directionScore);
    const rsi = rsiConfirmation(parts.rsi, directionScore);
    const adxConfirmationState = adxConfirmation(adx, directionScore);
    const momentum = { confirmation: directionalAgreement(directionScore, earlyMacd.score || 0), available: earlyMacd.available, components: earlyMacd.components || {} };
    const confirmationComponents = { relativeStrength, participation, rsi, adx: adxConfirmationState, momentum };
    const confirmationWeights = normalizeWeights(parts.config.confirmationWeights, profileModifiers.confirmationWeights);
    const confirmationScore = clamp(Object.entries(confirmationWeights).reduce((sum, [key, weight]) => sum + (confirmationComponents[key].confirmation || 0) * weight, 0), 0, 100);
    const persistence = signalPersistence(ma, macd, adx, relativeStrength);

    const risk = riskState(parts, price, parts.ma);
    const opportunity = priceOpportunity(parts, price, atr);
    const quality = dataQuality(parts, directionComponents, confirmationComponents);
    const agreementScores = [ma.score, macd.score, adx.score, early.score].filter(Number.isFinite).map((score) => directionScore === 0 ? 50 : score === 0 ? 50 : sign(score) === sign(directionScore) ? 100 : 0);
    const signalAgreement = Math.round(mean(agreementScores) || 0);
    const supporting = rankReasons([
      ma.score > 22 ? { score: Math.abs(ma.score), text: "Primary moving-average structure is constructive." } : null,
      macd.score > 22 ? { score: Math.abs(macd.score), text: "Primary MACD structure supports the current upside direction." } : null,
      relativeStrength.score > 20 ? { score: Math.abs(relativeStrength.score), text: "Relative Strength is confirming versus the selected benchmarks." } : null,
      participation.score > 20 ? { score: Math.abs(participation.score), text: "OBV and volume participation are confirming accumulation." } : null,
      opportunity.score > 20 ? { score: Math.abs(opportunity.score), text: "Several technical structures form nearby support confluence." } : null,
    ], "supporting");
    const limiting = rankReasons([
      ma.score < -22 ? { score: Math.abs(ma.score), text: "Primary moving-average structure remains bearish." } : null,
      macd.score < -22 ? { score: Math.abs(macd.score), text: "Primary MACD structure still confirms downside momentum." } : null,
      relativeStrength.score < -20 ? { score: Math.abs(relativeStrength.score), text: "Relative Strength is lagging its relevant benchmarks." } : null,
      participation.score < -20 ? { score: Math.abs(participation.score), text: "OBV or price-volume behavior indicates distribution." } : null,
      opportunity.score < -20 ? { score: Math.abs(opportunity.score), text: "Price is extended into layered resistance rather than support." } : null,
      risk.score >= 65 ? { score: risk.score, text: "Volatility or extension risk is elevated." } : null,
    ], "limiting");
    const materialSignals = [];
    if (risk.components.shock >= engine.config.stability.material.atrShock) materialSignals.push("atr_volume_shock");
    if (directionScore <= engine.config.stability.material.majorBreakdown && (ma.score < -45 || opportunity.score < -30)) materialSignals.push("major_support_breakdown");
    if (directionScore >= engine.config.stability.material.majorBreakout && participation.score > 30) materialSignals.push("major_breakout");
    return {
      directionScore: Math.round(directionScore), directionComponents,
      confirmationScore: Math.round(confirmationScore), confirmationComponents,
      riskScore: Math.round(risk.score), riskComponents: risk.components,
      priceOpportunityScore: Math.round(opportunity.score), priceComponents: opportunity.components,
      signalAgreement,
      signalPersistence: persistence,
      dataQuality: quality,
      atr: risk.atr,
      // Keep only scalar canonical observations in the decision object.  The
      // source technical object retains its history series for the Technical
      // tab; attaching them to every decision would waste Render memory.
      raw: {
        rsi: scalarFeature(parts.rsi, ["value", "state", "slope", "divergence", "overbought_oversold"]),
        macd: scalarFeature(parts.macd, ["macd_line", "signal_line", "histogram", "histogram_change_1", "histogram_change_3", "histogram_change_5", "above_or_below_zero", "crossover_state", "improving_or_deteriorating", "state"]),
        adx: scalarFeature(parts.adx, ["adx", "plus_di", "minus_di", "slope", "trend_strength", "state"]),
        atr: scalarFeature(parts.atr, ["value", "atr_pct", "atr_percentile_pct", "atr_percentile_60", "atr_percentile_120", "atr_percentile_250", "volatility_regime", "expansion_state", "slope"]),
        bands: scalarFeature(parts.bands, ["upper_band", "middle_band", "lower_band", "percent_b", "bandwidth_pct", "bandwidth_percentile", "squeeze_state", "price_position", "state"]),
        kdj: scalarFeature(parts.kdj, ["k", "d", "j", "state", "crossover_state", "slope"]),
        obv: scalarFeature(parts.obv, ["value", "trend", "divergence", "price_obv_confirmation", "state"]),
        relativeStrength: scalarFeature(parts.relativeStrength, ["primary", "returns", "vs_spy", "vs_qqq", "consistency", "state"]),
        volume: scalarFeature(parts.volume, ["current_volume", "average_volume", "relative_volume", "trend", "availability"]),
        fibonacci: scalarFeature(parts.fibonacci, ["status", "swing_high", "swing_low", "swing_direction", "retracement_levels", "extension_levels"]),
        position: scalarFeature(parts.position, ["high_52w", "low_52w", "all_time_high", "position_52w_pct", "state", "availability"]),
        ma: parts.ma.map((item) => scalarFeature(item, ["indicator", "period", "interval", "value", "price_state", "slope", "state", "availability"])),
      },
      executionContext: opportunity.executionContext,
      supporting,
      limiting,
      materialSignals,
    };
  }

  function blankProfileModifiers() {
    return { directionWeights: {}, confirmationWeights: {}, benchmarkWeights: { spy: 0.5, qqq: 0.5 } };
  }

  function scalarFeature(feature, keys) {
    const out = {};
    keys.forEach((key) => { if (feature && Object.prototype.hasOwnProperty.call(feature, key)) out[key] = feature[key]; });
    return out;
  }

  engine.technical = Object.freeze({ evaluate, structuralLevels, clusterLevels });
}(globalThis));
