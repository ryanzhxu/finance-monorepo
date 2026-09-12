(function createDecisionEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const localized = (action, language) => engine.config.actionLabels[action]?.[language] || engine.config.actionLabels[action]?.en || engine.config.actionLabels.hold.en;
  const unique = (values) => [...new Set(values.filter(Boolean))];

  function directionLabel(score) {
    return score >= 65 ? "Strong Bullish" : score >= 25 ? "Bullish" : score <= -65 ? "Strong Bearish" : score <= -25 ? "Bearish" : "Neutral";
  }

  function confirmationLabel(score) {
    return score >= 75 ? "Strong" : score >= 50 ? "Moderate" : "Weak";
  }

  function opportunityLabel(score) {
    return score >= 34 ? "Favorable" : score <= -34 ? "Extended" : "Fair";
  }

  function riskLabel(score) {
    return engine.config.risk.labels.find(([limit]) => score < limit)?.[1] || "extreme";
  }

  function adjustedRisk(technical, marketModifiers, profile) {
    const profileModifiers = profile.effectiveModifiers || {};
    const volatility = technical.riskComponents?.volatility || 0;
    const normalAtrTolerance = profileModifiers.normalAtrTolerance || 1;
    // A high-beta/static volatility profile can soften normal volatility only;
    // it does not erase independently corroborated extreme-risk overrides.
    const toleranceOffset = volatility * Math.max(0, 1 - 1 / normalAtrTolerance) * 0.62;
    const baseRisk = Math.max(0, (technical.riskScore || 0) - toleranceOffset);
    const profileRisk = baseRisk * (profileModifiers.riskSensitivity || 1);
    const components = technical.riskComponents || {};
    const extremeFloor = components.extremeOverride ? technical.riskScore || 0 : 0;
    const marketRiskAdd = marketModifiers.riskAdd || 0;
    return {
      score: clamp(Math.max(profileRisk, extremeFloor) + marketRiskAdd, 0, 100),
      baseRisk, profileRisk, toleranceOffset, marketRiskAdd, extremeFloor,
    };
  }

  function opportunityEdge(technical, exhaustion, risk) {
    const config = engine.config.edge;
    const direction = technical.directionScore || 0;
    const confirmation = technical.confirmationScore || 0;
    const directional = (direction / 100) * (config.directionTrustFloor + (confirmation / 100) * config.directionTrustConfirmationWeight);
    const price = (technical.priceOpportunityScore || 0) / 100 * config.priceOpportunityWeight;
    // Exhaustion is deliberately nonlinear only around meaningful extremes.
    const exhaustionMagnitude = Math.max(0, Math.abs(exhaustion.score || 0) - 22) / 78;
    const contrarian = Math.sign(exhaustion.score || 0) * exhaustionMagnitude * engine.config.exhaustion.contrarianEdgeWeight;
    const raw = directional + price + contrarian;
    const excessRisk = clamp(((risk - config.riskPenaltyStart) / Math.max(1, 100 - config.riskPenaltyStart)), 0, 1);
    const riskPenalty = raw > 0 ? (excessRisk ** config.riskPenaltyPower) * config.riskPenaltyMax : 0;
    return {
      directional: directional * 100, price: price * 100, contrarian: contrarian * 100,
      rawEdge: clamp(raw * 100, -100, 100), adjustedEdge: clamp((raw - riskPenalty) * 100, -100, 100), riskPenalty: riskPenalty * 100,
    };
  }

  function applyLandscapeQuality(technical, landscape) {
    const penalty = Number(landscape?.landscapeQuality?.penalty || 0);
    if (!penalty) return technical;
    return {
      ...technical,
      priceOpportunityScore: clamp((technical.priceOpportunityScore || 0) - penalty, -100, 100),
      priceComponents: { ...technical.priceComponents, landscapeQuality: landscape.landscapeQuality },
    };
  }

  function applyConfidenceGate(action, confidence, actionFamily) {
    const minimum = engine.config.actionPolicy.gates.confidenceMinimum;
    if (action === "strong_buy" && confidence < minimum.strong_buy) return "buy";
    if (action === "buy" && confidence < minimum.buy) return "accumulate";
    // Confidence can soften the intensity of an opportunity action, but it
    // may not cross the Price State boundary into Hold/Trim/Sell.
    void actionFamily;
    return action;
  }

  function reasons(technical, exhaustion, marketModifiers, underlyingContext = null, finalDecision = null) {
    const etfReason = underlyingContext?.alignment === "supporting" ? "Inverse underlying direction supports the ETF technical setup."
      : underlyingContext?.alignment === "limiting" ? "Underlying direction conflicts with the inverse ETF technical setup." : null;
    return {
      supporting: unique([...technical.supporting, ...exhaustion.supporting, ...(finalDecision?.reasons?.supporting || []), ...(etfReason && underlyingContext.alignment === "supporting" ? [etfReason] : [])]).slice(0, 5),
      limiting: unique([...technical.limiting, ...exhaustion.limiting, ...(finalDecision?.reasons?.limiting || []), ...(marketModifiers.reasons || []), ...(etfReason && underlyingContext.alignment === "limiting" ? [etfReason] : [])]).slice(0, 5),
    };
  }

  function underlyingDirection({ technicalFeatures, horizon, price, profile }) {
    if (!profile?.isETF || profile.direction !== "inverse" || !technicalFeatures || !Number.isFinite(price)) return null;
    const neutralProfile = { effectiveModifiers: { directionWeights: {}, confirmationWeights: {}, benchmarkWeights: { spy: 0.5, qqq: 0.5 } } };
    const value = engine.technical.evaluate(technicalFeatures, horizon, price, neutralProfile);
    return Number.isFinite(value.directionScore) ? value.directionScore : null;
  }

  function decideHorizon({ ticker, horizon, price, technicalFeatures, market, profile, metadata, underlyingTechnicalFeatures, underlyingPrice, language = "en" }) {
    const horizonProfile = engine.profile.forHorizon(profile, horizon);
    let technical = engine.technical.evaluate(technicalFeatures, horizon, price, horizonProfile);
    const underlying = engine.etfProfile.underlyingContext({
      profile: horizonProfile,
      ownDirection: technical.directionScore,
      underlyingDirection: underlyingDirection({ technicalFeatures: underlyingTechnicalFeatures, horizon, price: underlyingPrice, profile: horizonProfile }),
    });
    if (underlying.available && underlying.adjustment) {
      technical = {
        ...technical,
        confirmationScore: clamp(technical.confirmationScore + underlying.adjustment, 0, 100),
        confirmationComponents: { ...technical.confirmationComponents, inverseUnderlying: underlying },
        signalAgreement: clamp(technical.signalAgreement + underlying.adjustment * 0.35, 0, 100),
      };
    }
    const marketModifiers = engine.market.forHorizon(market, horizon, horizonProfile);
    const exhaustion = engine.exhaustion.evaluate({ technical, market, profile: horizonProfile, horizon });
    const riskAdjustment = adjustedRisk(technical, marketModifiers, horizonProfile);
    const risk = Math.round(riskAdjustment.score);
    // Structural clusters are selected with the already-computed Technical,
    // Market and Profile context. The resulting Price State is therefore a
    // core final-decision input, not a post-hoc execution decoration.
    const rawLandscape = engine.execution.buildLandscape({
      price, horizon, technical,
      context: { risk, exhaustionScore: exhaustion.score, marketModifiers, profile: horizonProfile },
    });
    technical = applyLandscapeQuality(technical, rawLandscape);
    const edgeBeforeMarket = opportunityEdge(technical, exhaustion, riskAdjustment.profileRisk);
    const edge = opportunityEdge(technical, exhaustion, risk);
    const familyDecision = engine.execution.decisionForPriceState({
      landscape: rawLandscape, technical, exhaustionScore: exhaustion.score, risk,
      edge: edge.adjustedEdge, marketModifiers, profile: horizonProfile,
    });
    const actionBeforeStability = familyDecision.action;
    // This value is stability input only. The displayed confidence is always
    // recalculated below after joint decision, hysteresis, and any confidence
    // gate have determined the final action.
    const stabilityInputConfidence = engine.confidence.calculate({ action: actionBeforeStability, edge: edge.adjustedEdge, technical, marketModifiers, exhaustion, profile: horizonProfile, finalDecision: familyDecision, landscapeQuality: rawLandscape.landscapeQuality });
    const materialChangeReasons = unique([
      ...technical.materialSignals,
      ...(marketModifiers.shock ? ["market_shock"] : []),
    ]);
    const stability = engine.stability.evaluate({
      ticker, horizon, candidateAction: actionBeforeStability,
      allowedActions: engine.execution.ACTION_FAMILIES[familyDecision.actionFamily], actionFamily: familyDecision.actionFamily,
      edge: edge.adjustedEdge, confidence: stabilityInputConfidence.score, materialChangeReasons, profile: horizonProfile, technical,
    });
    let finalAction = stability.finalAction;
    let confidence = engine.confidence.calculate({ action: finalAction, edge: edge.adjustedEdge, technical, marketModifiers, exhaustion, profile: horizonProfile, stability, finalDecision: familyDecision, landscapeQuality: rawLandscape.landscapeQuality });
    const confidenceGated = applyConfidenceGate(finalAction, confidence.score, familyDecision.actionFamily);
    if (confidenceGated !== finalAction) {
      finalAction = confidenceGated;
      confidence = engine.confidence.calculate({ action: finalAction, edge: edge.adjustedEdge, technical, marketModifiers, exhaustion, profile: horizonProfile, stability, finalDecision: familyDecision, landscapeQuality: rawLandscape.landscapeQuality });
    }
    if (finalAction !== stability.finalAction) engine.stability.commit({ ticker, horizon, action: finalAction, actionFamily: familyDecision.actionFamily, edge: edge.adjustedEdge, confidence: confidence.score, materialChange: Boolean(materialChangeReasons.length) });
    const execution = engine.execution.build({ price, horizon, action: finalAction, technical, landscape: rawLandscape, context: { risk, exhaustionScore: exhaustion.score, marketModifiers, profile: horizonProfile } });
    const guardrails = unique([...(rawLandscape.debug?.guardrails || []), ...(familyDecision.guardrails || []), ...(execution.debug?.guardrails || [])]);
    return {
      horizon,
      action: finalAction,
      actionLabel: localized(finalAction, language),
      confidence: confidence.score,
      executionIntent: execution.executionIntent,
      priceLandscape: execution.priceLandscape,
      states: {
        direction: { score: technical.directionScore, label: directionLabel(technical.directionScore) },
        confirmation: { score: technical.confirmationScore, label: confirmationLabel(technical.confirmationScore) },
        risk: { score: risk, label: riskLabel(risk) },
        priceOpportunity: { score: technical.priceOpportunityScore, label: opportunityLabel(technical.priceOpportunityScore) },
        exhaustion: { score: exhaustion.score, label: exhaustion.label },
      },
      market: { ...market, horizonModifiers: marketModifiers },
      profile: horizonProfile,
      reasons: reasons(technical, exhaustion, marketModifiers, underlying, familyDecision),
      debug: {
        directionScore: technical.directionScore, directionComponents: technical.directionComponents,
        confirmationScore: technical.confirmationScore, confirmationComponents: technical.confirmationComponents,
        riskScore: risk, riskComponents: { ...technical.riskComponents, marketRisk: marketModifiers.riskAdd, riskAdjustment: Object.fromEntries(Object.entries(riskAdjustment).map(([key, value]) => [key, Number.isFinite(value) ? Math.round(value * 100) / 100 : value])) },
        priceOpportunityScore: technical.priceOpportunityScore, priceComponents: technical.priceComponents,
        exhaustionScore: exhaustion.score, exhaustionComponents: exhaustion.components,
        marketRegime: market.regime, marketModifiers,
        appliedTraits: horizonProfile.companyTraits || [], appliedModifiers: horizonProfile.appliedModifiers || [], effectiveProfileModifiers: horizonProfile.effectiveModifiers,
        etfUnderlying: underlying,
        rawEdge: Math.round(edge.rawEdge), adjustedEdge: Math.round(edge.adjustedEdge), edgeBeforeMarket: Math.round(edgeBeforeMarket.adjustedEdge), edgeAfterMarket: Math.round(edge.adjustedEdge), directionalOpportunity: Math.round(edge.directional), priceOpportunityContribution: Math.round(edge.price), contrarianContribution: Math.round(edge.contrarian), riskPenalty: Math.round(edge.riskPenalty),
        candidateAction: familyDecision.action, actionBeforeStability, finalAction,
        priceState: rawLandscape.priceState, actionFamily: familyDecision.actionFamily, landscapeQuality: rawLandscape.landscapeQuality, finalDecision: familyDecision,
        stability, guardrails, materialChangeReasons,
        confidenceComponents: confidence, priceLandscapeInputs: execution.debug?.priceLandscapeInputs || {}, invalidationInputs: execution.debug?.invalidationInputs || {},
        dataQuality: technical.dataQuality,
      },
    };
  }

  function decide(input = {}) {
    const profile = engine.profile.build(input.classification || {}, input.ticker);
    const market = engine.market.evaluate(input.marketContext || {}, input.metadata || {});
    const horizons = Object.fromEntries(["short", "mid", "long"].map((horizon) => [horizon, decideHorizon({ ...input, horizon, market, profile })]));
    return { version: engine.config.version, ticker: input.ticker, horizons, generatedAt: new Date().toISOString() };
  }

  engine.decide = decide;
  engine.actionLabel = localized;
}(globalThis));
