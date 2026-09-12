(function createExecutionEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const roundPrice = (value) => Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
  const round = (value) => Number.isFinite(value) ? Math.round(value * 100) / 100 : null;
  const range = (low, high) => Number.isFinite(low) && Number.isFinite(high)
    ? { low: roundPrice(Math.min(low, high)), high: roundPrice(Math.max(low, high)) } : null;
  const positiveAction = (action) => ["strong_buy", "buy", "accumulate"].includes(action);
  const executionIntent = (action) => ({ strong_buy: "enter", buy: "enter", accumulate: "add", hold: "hold", trim: "reduce", sell: "exit", avoid: "avoid" }[action] || "avoid");

  // Granular states are kept for debug/presentation, but each resolves to one
  // user-facing Action Family. No later reconciliation may cross that family.
  const PRICE_STATES = Object.freeze([
    "IN_OPPORTUNITY_ZONE", "NEAR_OPPORTUNITY_ZONE", "NEUTRAL_ZONE", "NEAR_REDUCE_ZONE",
    "IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE", "BREAKDOWN_ZONE", "INVALID_LANDSCAPE",
  ]);
  const ACTION_FAMILIES = Object.freeze({
    opportunity: Object.freeze(["strong_buy", "buy", "accumulate"]),
    neutral: Object.freeze(["hold"]),
    reduce: Object.freeze(["trim", "sell"]),
    defensive: Object.freeze(["sell", "avoid"]),
    unavailable: Object.freeze(["avoid"]),
  });

  function actionFamilyForState(state) {
    // A Near state is analysis context only. It may affect confidence and
    // reasons, but it never permits an early entry or reduction action.
    // Exact range membership remains the sole normal Action-Family boundary.
    if (state === "IN_OPPORTUNITY_ZONE") return "opportunity";
    if (["NEAR_OPPORTUNITY_ZONE", "NEUTRAL_ZONE", "NEAR_REDUCE_ZONE"].includes(state)) return "neutral";
    if (["IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE"].includes(state)) return "reduce";
    if (state === "BREAKDOWN_ZONE") return "defensive";
    return "unavailable";
  }

  function nearestLevel(levels, center, side) {
    const candidates = (levels || []).filter((level) => Number.isFinite(level.price)
      && (side === "above" ? level.price > center : level.price < center));
    return candidates.sort((left, right) => Math.abs(left.price - center) - Math.abs(right.price - center))[0] || null;
  }

  function rangeDistance(price, value) {
    if (!value || !Number.isFinite(price)) return { available: false, within: false, edge: null, distancePct: null };
    if (price >= value.low && price <= value.high) return { available: true, within: true, edge: price, distancePct: 0 };
    const edge = price < value.low ? value.low : value.high;
    return { available: true, within: false, edge, distancePct: (edge - price) / price * 100 };
  }

  function confluenceWidth({ price, atr, horizon, confluence }) {
    const config = engine.config.execution;
    const structureConfig = engine.config.componentScales.opportunity.unifiedConfluence;
    const score = clamp((confluence?.confluence || confluence?.quality || 0) / structureConfig.qualityReference * engine.config.componentScales.opportunity.maxConfluenceScore, 0, engine.config.componentScales.opportunity.maxConfluenceScore);
    const ratio = score / Math.max(1, engine.config.componentScales.opportunity.maxConfluenceScore);
    const multiplier = config.confluenceWidthMultiplier.weak
      + (config.confluenceWidthMultiplier.strong - config.confluenceWidthMultiplier.weak) * ratio;
    const baseWidth = Math.max(atr * engine.config.horizons[horizon].rangeAtrWidth, price * 0.0025);
    const width = Math.min(baseWidth * multiplier, price * config.maxHalfWidthPct[horizon]);
    return { score: round(score), quality: round(confluence?.quality ?? confluence?.confluence ?? 0), multiplier: round(multiplier), baseWidth: roundPrice(baseWidth), width: roundPrice(width) };
  }

  function landscapeRange({ center, price, atr, horizon, confluence, halfWidth = null }) {
    if (!Number.isFinite(center)) return null;
    const width = confluenceWidth({ price, atr, horizon, confluence });
    const resolvedWidth = Number.isFinite(halfWidth) ? halfWidth : width.width;
    return {
      range: range(center - resolvedWidth, center + resolvedWidth),
      inputs: { center: roundPrice(center), ...width, width: roundPrice(resolvedWidth), members: confluence?.members?.length || 0, independentStructures: confluence?.independentStructures || 0, categories: (confluence?.categoryBreakdown || []).map((item) => item.category) },
    };
  }

  function compactCluster(cluster) {
    return cluster ? {
      center: roundPrice(cluster.center), confluence: round(cluster.confluence), quality: round(cluster.quality), roleAlignment: round(cluster.roleAlignment), distanceAtr: round(cluster.distanceAtr),
      members: (cluster.members || []).slice(0, 5).map((member) => ({ price: roundPrice(member.price), type: member.type, category: member.category || member.type, label: member.label })),
      categoryBreakdown: (cluster.categoryBreakdown || []).map((item) => ({ category: item.category, levelCount: item.levelCount, contribution: round(item.contribution), representative: { ...item.representative, price: roundPrice(item.representative?.price) } })),
    } : null;
  }

  function clustersFor(context, key, fallback) {
    const listed = Array.isArray(context?.[key]) ? context[key].filter((item) => Number.isFinite(item?.center)) : [];
    if (listed.length) return listed;
    return Number.isFinite(fallback?.center) ? [fallback] : [];
  }

  function bufferFor({ horizon, atr, support, resistance }) {
    const base = atr * engine.config.execution.landscape.neutralBufferAtr[horizon];
    const quality = clamp(((support?.quality || support?.confluence || 0) + (resistance?.quality || resistance?.confluence || 0)) / engine.config.componentScales.opportunity.unifiedConfluence.pairQualityReference, 0, 1);
    return base * (1.08 - quality * 0.20);
  }

  function contextualPressure({ technical = {}, risk = 0, exhaustionScore = 0, marketModifiers = {}, profile = {} } = {}) {
    const direction = technical.directionScore || 0;
    const confirmation = technical.confirmationScore || 0;
    const profileModifiers = profile.effectiveModifiers || {};
    const marketPressure = clamp((marketModifiers.riskAdd || 0) / 32, 0, 1) * (profileModifiers.marketSensitivity || 1);
    const bullishTrend = clamp((Math.max(0, direction) / 100) * 0.62 + (confirmation / 100) * 0.28 - (risk / 100) * 0.22 - (Math.max(0, -exhaustionScore) / 100) * 0.28 - marketPressure * 0.16, 0, 1);
    const bearishPressure = clamp((Math.max(0, -direction) / 100) * 0.52 + (risk / 100) * 0.22 + (Math.max(0, -exhaustionScore) / 100) * 0.18 + marketPressure * 0.18, 0, 1);
    return { bullishTrend: round(bullishTrend), bearishPressure: round(bearishPressure), marketPressure: round(marketPressure) };
  }

  function pairCandidates({ supportClusters, resistanceClusters, price, atr, horizon, context }) {
    const pairs = [];
    const policy = engine.config.execution.landscape.contextualSelection;
    const pressure = contextualPressure(context);
    const requiredReduceDistance = policy.minimumReduceDistanceAtr[horizon] + pressure.bullishTrend * policy.bullishTrendLiftAtr[horizon];
    supportClusters.forEach((support) => resistanceClusters.forEach((resistance) => {
      if (!(support.center < resistance.center)) return;
      const opportunity = landscapeRange({ center: support.center, price, atr, horizon, confluence: support });
      const reduce = landscapeRange({ center: resistance.center, price, atr, horizon, confluence: resistance });
      if (!opportunity?.range || !reduce?.range) return;
      const buffer = bufferFor({ horizon, atr, support, resistance });
      const separation = reduce.range.low - opportunity.range.high;
      const quality = (support.quality || support.confluence || 0) + (resistance.quality || resistance.confluence || 0);
      const supportDistanceAtr = Math.abs(price - support.center) / atr;
      const reduceDistanceAtr = Math.abs(resistance.center - price) / atr;
      // Strong trend selection prefers a further *existing* resistance cluster
      // over a stale nearby one; no synthetic centre is introduced.
      const prematureReduce = Math.max(0, requiredReduceDistance - Math.max(0, reduceDistanceAtr));
      const rank = quality
        - supportDistanceAtr * policy.supportDistancePenalty
        - reduceDistanceAtr * policy.reduceDistancePenalty
        - prematureReduce * policy.prematureReducePenalty
        + pressure.bearishPressure * Math.max(0, 1.5 - Math.max(0, reduceDistanceAtr)) * policy.bearishPressureProximityBonus;
      pairs.push({
        support, resistance, opportunity, reduce, buffer, separation, quality, rank,
        contextual: { ...pressure, requiredReduceDistance: round(requiredReduceDistance), supportDistanceAtr: round(supportDistanceAtr), reduceDistanceAtr: round(reduceDistanceAtr), prematureReduce: round(prematureReduce) },
        valid: separation + 0.000001 >= buffer,
      });
    }));
    return pairs.sort((left, right) => Number(right.valid) - Number(left.valid) || right.rank - left.rank);
  }

  function compressPair(pair, { price, atr, horizon }) {
    if (!pair || pair.resistance.center <= pair.support.center) return null;
    const buffer = bufferFor({ horizon, atr, support: pair.support, resistance: pair.resistance });
    const available = pair.resistance.center - pair.support.center - buffer;
    const minimum = atr * engine.config.execution.landscape.minimumHalfWidthAtr[horizon] * 2;
    if (!(available >= minimum)) return null;
    const targetHalfTotal = Math.min(available, pair.opportunity.inputs.width + pair.reduce.inputs.width);
    const proportion = pair.opportunity.inputs.width / Math.max(0.000001, pair.opportunity.inputs.width + pair.reduce.inputs.width);
    const opportunity = landscapeRange({ center: pair.support.center, price, atr, horizon, confluence: pair.support, halfWidth: targetHalfTotal * proportion });
    const reduce = landscapeRange({ center: pair.resistance.center, price, atr, horizon, confluence: pair.resistance, halfWidth: targetHalfTotal * (1 - proportion) });
    const separation = reduce.range.low - opportunity.range.high;
    return separation + 0.000001 >= buffer ? { ...pair, opportunity, reduce, buffer, separation, valid: true, rebuilt: "compressed_to_preserve_neutral_buffer" } : null;
  }

  function confirmedBreakdown(technical = {}) {
    const policy = engine.config.execution.actionFamily;
    const material = technical.materialSignals || [];
    return material.includes("major_support_breakdown")
      || ((technical.directionScore || 0) <= policy.breakdownDirection && (technical.confirmationScore || 0) >= policy.breakdownConfirmation);
  }

  function preliminaryInvalidation({ technical, opportunityRange, atr }) {
    const levels = technical.executionContext?.levels || [];
    const reference = opportunityRange?.low;
    const level = Number.isFinite(reference) ? nearestLevel(levels, reference, "below") : null;
    const base = level?.price ?? reference;
    return Number.isFinite(base) ? roundPrice(base - atr * engine.config.execution.invalidationAtrBuffer) : null;
  }

  function priceStateFor({ price, horizon, atr, opportunityRange, reduceRange, neutralBuffer = null, invalidation = null, breakdown = false }) {
    if (!Number.isFinite(price) || !Number.isFinite(atr) || atr <= 0 || !opportunityRange || !reduceRange || !(opportunityRange.high < reduceRange.low)) return "INVALID_LANDSCAPE";
    if (breakdown || (Number.isFinite(invalidation) && price <= invalidation)) return "BREAKDOWN_ZONE";
    if (price >= opportunityRange.low && price <= opportunityRange.high) return "IN_OPPORTUNITY_ZONE";
    if (price >= reduceRange.low && price <= reduceRange.high) return "IN_REDUCE_ZONE";
    if (price > reduceRange.high) return "BEYOND_REDUCE_ZONE";
    const opportunity = rangeDistance(price, opportunityRange);
    const reduce = rangeDistance(price, reduceRange);
    const stateConfig = engine.config.execution.priceState;
    const opportunityDistance = opportunity.available ? Math.abs(opportunity.edge - price) : Infinity;
    const reduceDistance = reduce.available ? Math.abs(reduce.edge - price) : Infinity;
    const neutralCap = Number.isFinite(neutralBuffer)
      ? Math.max(atr * stateConfig.minimumNearAtr, neutralBuffer * stateConfig.neutralBufferNearShare)
      : Infinity;
    const nearOpportunity = opportunityDistance <= Math.min(atr * stateConfig.nearOpportunityAtr[horizon], neutralCap);
    const nearReduce = reduceDistance <= Math.min(atr * stateConfig.nearReduceAtr[horizon], neutralCap);
    if (nearOpportunity && nearReduce) return reduceDistance < opportunityDistance ? "NEAR_REDUCE_ZONE" : "NEAR_OPPORTUNITY_ZONE";
    if (nearOpportunity) return "NEAR_OPPORTUNITY_ZONE";
    if (nearReduce) return "NEAR_REDUCE_ZONE";
    return "NEUTRAL_ZONE";
  }

  function buildLandscape({ price, horizon, technical = {}, context = {} } = {}) {
    // Stateless by contract: every call receives the current canonical
    // structure, builds fresh candidates, and retains no prior range/cluster.
    // Action stability is intentionally handled elsewhere and only after this
    // current Price State has been selected.
    const raw = technical.executionContext || {};
    const atr = Number(technical.atr ?? raw.atr);
    const invalid = (reason) => ({
      priceLandscape: { opportunityRange: null, reduceRange: null, invalidation: null, currentPrice: roundPrice(price) },
      priceState: "INVALID_LANDSCAPE", actionFamily: "unavailable",
      landscapeQuality: { state: "invalid", score: 0, penalty: engine.config.execution.landscape.invalidQualityPenalty, reason },
      debug: { priceLandscapeInputs: { reason, candidateCounts: { opportunity: 0, reduce: 0 } }, guardrails: ["invalid_price_landscape"] },
    });
    if (!Number.isFinite(price) || !Number.isFinite(atr) || atr <= 0 || !engine.config.horizons[horizon]) return invalid("price_or_atr_unavailable");

    const supportClusters = clustersFor(raw, "supportClusters", raw.support);
    let resistanceClusters = clustersFor(raw, "resistanceClusters", raw.resistance);
    const breakdown = confirmedBreakdown(technical);
    if (breakdown) {
      // A confirmed break does not wait for a distant rebound: current price is
      // the sole executable exit anchor, while the support cluster stays real.
      resistanceClusters = [{
        center: price, confluence: Math.max(raw.resistance?.confluence || 0, 1.4), quality: Math.max(raw.resistance?.quality || raw.resistance?.confluence || 0, 1.4),
        members: raw.resistance?.members || [], independentStructures: raw.resistance?.independentStructures || 1, distanceAtr: 0,
      }];
    }
    const pairs = pairCandidates({ supportClusters, resistanceClusters, price, atr, horizon, context: { ...context, technical } });
    let selected = pairs.find((pair) => pair.valid) || null;
    if (!selected) {
      for (const pair of pairs) {
        selected = compressPair(pair, { price, atr, horizon });
        if (selected) break;
      }
    }
    if (!selected || selected.quality < engine.config.execution.landscape.minimumPairQuality) return invalid("no_independent_support_resistance_pair");

    const invalidation = preliminaryInvalidation({ technical, opportunityRange: selected.opportunity.range, atr });
    const priceState = priceStateFor({ price, horizon, atr, opportunityRange: selected.opportunity.range, reduceRange: selected.reduce.range, neutralBuffer: selected.buffer, invalidation, breakdown });
    const qualityState = selected.rebuilt ? "rebuilt" : selected.quality >= 2.1 ? "high" : "low";
    const qualityPenalty = qualityState === "low" ? engine.config.execution.landscape.weakQualityPenalty : 0;
    return {
      priceLandscape: { opportunityRange: selected.opportunity.range, reduceRange: selected.reduce.range, invalidation, currentPrice: roundPrice(price) },
      priceState, actionFamily: actionFamilyForState(priceState),
      landscapeQuality: { state: qualityState, score: round(selected.quality), penalty: qualityPenalty, neutralBuffer: roundPrice(selected.buffer), separation: roundPrice(selected.separation), rebuilt: selected.rebuilt || null },
      debug: {
        priceLandscapeInputs: {
          structureModel: raw.structureModel || "unified_category_confluence",
          opportunity: selected.opportunity.inputs, reduce: selected.reduce.inputs,
          neutralBuffer: roundPrice(selected.buffer), separation: roundPrice(selected.separation), rebuilt: selected.rebuilt || null,
          breakdownExitAnchor: breakdown, preliminaryInvalidation: invalidation, contextualSelection: selected.contextual,
          selectedSupport: compactCluster(selected.support), selectedReduce: compactCluster(selected.resistance),
          // Candidate clusters are temporary work for this calculation. Keep
          // only bounded counts plus the selected provenance in the final
          // decision debug object; audits can recompute the full candidates.
          candidateCounts: { opportunity: supportClusters.length, reduce: resistanceClusters.length },
        },
        guardrails: selected.rebuilt ? ["landscape_rebuilt_for_neutral_buffer"] : [],
      },
    };
  }

  function bearishEvidence({ technical = {}, risk = 0, exhaustionScore = 0 } = {}) {
    const policy = engine.config.execution.actionFamily;
    const direction = technical.directionScore || 0;
    const confirmation = technical.confirmationScore || 0;
    return confirmedBreakdown(technical)
      || (direction <= policy.sellDirection && confirmation >= policy.sellConfirmation)
      || (direction <= -25 && confirmation >= policy.sellConfirmation && risk >= policy.sellRisk && exhaustionScore <= policy.sellBullishExhaustion);
  }

  function decisionForPriceState({ landscape, technical = {}, exhaustionScore = 0, risk = 0, edge = 0, marketModifiers = {}, profile = {} } = {}) {
    const priceState = landscape?.priceState || "INVALID_LANDSCAPE";
    const actionFamily = actionFamilyForState(priceState);
    const policy = engine.config.actionPolicy;
    const gates = policy.gates;
    const direction = technical.directionScore || 0;
    const confirmation = technical.confirmationScore || 0;
    const opportunity = technical.priceOpportunityScore || 0;
    const dataQuality = technical.dataQuality?.score || 0;
    const profileGates = profile.effectiveModifiers?.actionGates || {};
    const breakdown = confirmedBreakdown(technical) || priceState === "BREAKDOWN_ZONE";
    const reasons = { supporting: [], limiting: [] };
    const guardrails = [];
    let action = "avoid";

    if (actionFamily === "opportunity") {
      const opportunityGate = gates.strongBuy.priceOpportunity * (profile.effectiveModifiers?.strongBuyOpportunity || 1);
      const strongBuy = dataQuality >= policy.minimumDataQuality
        && edge >= policy.territories.strongBuy
        && direction >= gates.strongBuy.direction + (profileGates.strongBuyDirection || 0)
        && confirmation >= gates.strongBuy.confirmation + (profileGates.strongBuyConfirmation || 0)
        && opportunity >= opportunityGate && risk <= gates.strongBuy.riskMaximum
        && exhaustionScore > -gates.strongBuy.bullishExhaustionMaximum && marketModifiers.regime !== "shock";
      const buy = dataQuality >= policy.minimumDataQuality
        && edge >= policy.territories.buy
        && direction >= gates.buy.direction + (profileGates.buyDirection || 0)
        && confirmation >= gates.buy.confirmation + (profileGates.buyConfirmation || 0)
        && risk <= gates.buy.riskMaximum && exhaustionScore > -55;
      action = strongBuy ? "strong_buy" : buy ? "buy" : "accumulate";
      if (marketModifiers.regime === "shock" && edge >= policy.territories.strongBuy) guardrails.push("market_shock_blocks_strong_buy");
      if (action === "accumulate" && dataQuality < policy.minimumDataQuality) reasons.limiting.push("Technical evidence is incomplete, so the opportunity zone supports only a cautious add posture.");
      if (action === "accumulate" && direction <= -25 && exhaustionScore >= gates.bearishContrarianAccumulate.exhaustion) reasons.supporting.push("Downside exhaustion is developing at a valid opportunity zone.");
    } else if (actionFamily === "neutral") {
      action = "hold";
      if (priceState === "NEAR_OPPORTUNITY_ZONE") reasons.limiting.push("Price is near the opportunity range but has not entered the recommended buy/add zone.");
      else if (priceState === "NEAR_REDUCE_ZONE") reasons.limiting.push("Price is approaching the reduce range but has not entered the recommended reduce/exit zone.");
      else if (direction >= 25) reasons.supporting.push("Trend remains constructive, but current price is between the opportunity and reduce zones.");
      else if (direction <= -25) reasons.limiting.push("Trend is weak, but price has not entered a reduce zone or confirmed a breakdown.");
      else reasons.limiting.push("Current price is in the neutral space between actionable price zones.");
    } else if (actionFamily === "reduce") {
      action = bearishEvidence({ technical, risk, exhaustionScore }) ? "sell" : "trim";
      if (action === "trim") reasons.limiting.push("Current price has reached the reduce zone; reduce exposure rather than add.");
      else reasons.limiting.push("Bearish deterioration is confirmed while current price is in the executable reduce zone.");
    } else if (actionFamily === "defensive") {
      action = dataQuality >= policy.minimumDataQuality && (breakdown || bearishEvidence({ technical, risk, exhaustionScore })) ? "sell" : "avoid";
      reasons.limiting.push(action === "sell"
        ? "A confirmed breakdown has invalidated the prior opportunity structure; exit is anchored near the current executable area."
        : "The opportunity structure is invalid and evidence is insufficient for a precise exit recommendation.");
    } else {
      action = "avoid";
      reasons.limiting.push("Price landscape quality is insufficient for an actionable recommendation.");
      guardrails.push("invalid_price_landscape");
    }
    return { action, priceState, actionFamily, breakdown, bearishEvidence: bearishEvidence({ technical, risk, exhaustionScore }), reasons, guardrails };
  }

  function invalidationFor({ action, technical, landscape }) {
    if (action === "avoid") return { value: null, inputs: {} };
    const ranges = landscape?.priceLandscape || {};
    const levels = technical.executionContext?.levels || [];
    const atr = Number(technical.atr);
    if (!Number.isFinite(atr) || atr <= 0) return { value: null, inputs: {} };
    const positive = positiveAction(action) || action === "hold";
    if (positive && Number.isFinite(ranges.invalidation)) return { value: ranges.invalidation, inputs: { source: "opportunity_structure", atrBuffer: roundPrice(atr * engine.config.execution.invalidationAtrBuffer) } };
    const reference = ranges.reduceRange?.high;
    const level = Number.isFinite(reference) ? nearestLevel(levels, reference, "above") : null;
    const base = level?.price ?? reference ?? null;
    const value = Number.isFinite(base) ? roundPrice(base + atr * engine.config.execution.invalidationAtrBuffer) : null;
    return { value, inputs: { source: "reduce_recovery_structure", level: level ? { price: roundPrice(level.price), label: level.label } : null, atrBuffer: roundPrice(atr * engine.config.execution.invalidationAtrBuffer) } };
  }

  function build({ price, horizon, action = "avoid", technical = {}, landscape = null, context = {} } = {}) {
    const base = landscape || buildLandscape({ price, horizon, technical, context });
    const invalidation = invalidationFor({ action, technical, landscape: base });
    return {
      priceLandscape: { ...base.priceLandscape, invalidation: invalidation.value, currentPrice: roundPrice(price) },
      executionIntent: executionIntent(action), priceState: base.priceState, actionFamily: base.actionFamily,
      landscapeQuality: base.landscapeQuality,
      debug: { ...base.debug, invalidationInputs: invalidation.inputs, guardrails: [...(base.debug?.guardrails || [])] },
    };
  }

  engine.execution = Object.freeze({
    buildLandscape, build, decisionForPriceState, executionIntent, rangeDistance, priceStateFor, actionFamilyForState,
    PRICE_STATES, ACTION_FAMILIES, confirmedBreakdown,
  });
}(globalThis));
