(function createEtfProfileEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

  function blankModifiers() {
    return {
      directionWeights: {}, confirmationWeights: {}, riskSensitivity: 1, exhaustionSensitivity: 1,
      marketSensitivity: 1, normalAtrTolerance: 1, strongBuyOpportunity: 1, rateSensitivity: 1,
      eventSensitivity: 1, longStability: 1, confidenceScale: 1,
      actionGates: { buyDirection: 0, buyConfirmation: 0, strongBuyDirection: 0, strongBuyConfirmation: 0 },
      benchmarkWeights: { spy: 0.5, qqq: 0.5 },
    };
  }

  function build(classification = {}) {
    const source = classification.etfProfile || classification.etf_profile || classification;
    const leveraged = Boolean(source.leveraged);
    const direction = source.direction === "inverse" ? "inverse" : "long";
    const modifiers = blankModifiers();
    const appliedModifiers = [];
    if (leveraged) {
      const rule = engine.config.etf.leveraged;
      Object.entries(rule.modifierDelta).forEach(([key, delta]) => { modifiers[key] += delta; });
      modifiers.actionGates = { ...rule.gates };
      modifiers.confidenceScale = rule.confidenceScale;
      appliedModifiers.push("LeveragedETF");
    }
    if (direction === "inverse") appliedModifiers.push("InverseETF");
    return {
      type: "etf", isETF: true, leveraged, direction,
      underlying: source.underlying || null, underlyingTicker: source.underlyingTicker || source.underlying_ticker || null,
      primaryClassification: null, companyTraits: [], lifecycle: null,
      profileConfidence: 0.84, lastProfileReview: null,
      effectiveModifiers: modifiers, appliedModifiers,
    };
  }

  function forHorizon(profile, horizon) {
    if (!profile?.leveraged) return profile;
    const scale = profile.effectiveModifiers?.confidenceScale?.[horizon] || 1;
    return { ...profile, effectiveModifiers: { ...profile.effectiveModifiers, confidenceScale: scale } };
  }

  // The underlying is only a bounded confirmation context. Its direction is
  // inverted for inverse funds; the fund's own technical structure remains the
  // Direction source and can never be replaced by the underlying alone.
  function underlyingContext({ profile, ownDirection, underlyingDirection } = {}) {
    if (!profile?.isETF || profile.direction !== "inverse" || !Number.isFinite(underlyingDirection)) {
      return { available: false, adjustment: 0, alignment: "unavailable" };
    }
    const desired = -underlyingDirection;
    const aligned = Math.abs(ownDirection || 0) >= 8 && Math.sign(ownDirection) === Math.sign(desired);
    const opposite = Math.abs(ownDirection || 0) >= 8 && Math.sign(ownDirection) !== Math.sign(desired);
    const magnitude = clamp(Math.abs(underlyingDirection) / 100, 0, 1);
    const adjustment = aligned
      ? engine.config.etf.inverse.underlyingConfirmationImpact * magnitude
      : opposite ? -engine.config.etf.inverse.underlyingConflictImpact * magnitude : 0;
    return { available: true, underlyingDirection: Math.round(underlyingDirection), invertedDirection: Math.round(desired), adjustment: Math.round(adjustment), alignment: aligned ? "supporting" : opposite ? "limiting" : "neutral" };
  }

  engine.etfProfile = Object.freeze({ blankModifiers, build, forHorizon, underlyingContext });
}(globalThis));
