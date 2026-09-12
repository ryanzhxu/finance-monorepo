(function createConfidenceEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

  function calculate({ action, edge = 0, technical = {}, marketModifiers = {}, exhaustion = {}, profile = {}, stability = null, finalDecision = null, landscapeQuality = null } = {}) {
    const config = engine.config.confidence;
    const agreement = clamp(technical.signalAgreement || 0, 0, 100);
    const actionStrength = clamp(Math.abs(edge), 0, 100);
    const stabilityScore = stability?.score
      ?? technical.signalPersistence?.score
      ?? engine.config.stability.noHistory.unavailable;
    const dataQuality = clamp(technical.dataQuality?.score || 0, 0, 100);
    const profileConfidence = clamp((profile.profileConfidence || 0) * 100, 0, 100);
    const components = {
      signalAgreement: Math.round(agreement), actionStrength: Math.round(actionStrength),
      decisionStability: Math.round(stabilityScore), dataQuality: Math.round(dataQuality),
      profileConfidence: Math.round(profileConfidence),
    };
    const base = Object.entries(config.weights).reduce((sum, [key, weight]) => {
      const componentKey = key === "agreement" ? "signalAgreement" : key === "stability" ? "decisionStability" : key;
      return sum + (components[componentKey] || 0) * weight;
    }, 0);
    const penalties = {};
    const direction = technical.directionScore || 0;
    if ((marketModifiers.regime === "risk_off" || marketModifiers.regime === "shock") && direction > 30) penalties.marketConflict = config.penalties.marketConflict * (marketModifiers.regime === "shock" ? 1 : 0.55);
    if ((exhaustion.score || 0) <= -42 && edge > 25) penalties.exhaustionConflict = config.penalties.exhaustionConflict * clamp(Math.abs(exhaustion.score) / 100, 0.35, 1);
    if ((exhaustion.score || 0) >= 42 && edge < -25) penalties.exhaustionConflict = config.penalties.exhaustionConflict * clamp(Math.abs(exhaustion.score) / 100, 0.35, 1);
    if ((marketModifiers.confidencePenalty || 0) > 0) penalties.eventUncertainty = Math.min(config.penalties.eventUncertainty, marketModifiers.confidencePenalty);
    const majorConflict = Math.abs(direction) >= 42 && technical.confirmationScore <= 42;
    if (majorConflict) penalties.internalConflict = config.penalties.internalConflict * 0.72;
    // The final action always matches its Price State family. Confidence can
    // still be low when a powerful directional signal is constrained by a
    // neutral price location, which is genuine execution tension—not a UI
    // reconciliation exception.
    const priceState = finalDecision?.priceState || null;
    if (["NEAR_OPPORTUNITY_ZONE", "NEUTRAL_ZONE", "NEAR_REDUCE_ZONE"].includes(priceState) && Math.abs(direction) >= 42) {
      penalties.priceStateTension = config.penalties.priceConflict * clamp((Math.abs(direction) - 38) / 62, 0.2, 1);
    }
    if (["IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE"].includes(priceState) && direction >= 42 && action === "trim") {
      penalties.priceStateTension = Math.max(penalties.priceStateTension || 0, config.penalties.priceConflict * 0.45);
    }
    if (landscapeQuality?.state === "invalid") penalties.invalidLandscape = config.penalties.invalidLandscape;
    const penalty = Object.values(penalties).reduce((sum, value) => sum + value, 0);
    const preProfileScale = clamp(Math.round(base - penalty), 0, 100);
    const confidenceScale = Number.isFinite(profile.effectiveModifiers?.confidenceScale) ? profile.effectiveModifiers.confidenceScale : 1;
    const confidence = clamp(Math.round(preProfileScale * confidenceScale), 0, 100);
    return { score: confidence, components, penalties: Object.fromEntries(Object.entries(penalties).map(([key, value]) => [key, Math.round(value)])), base: Math.round(base), preProfileScale, confidenceScale, action, priceState, actionFamily: finalDecision?.actionFamily || null, landscapeQuality: landscapeQuality?.state || null };
  }

  engine.confidence = Object.freeze({ calculate });
}(globalThis));
