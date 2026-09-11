(function createProfileEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const reviewCache = new Map();
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const unique = (values) => [...new Set((values || []).filter(Boolean))];
  const dateFor = (value) => value ? new Date(value) : null;
  const validDate = (date) => date && !Number.isNaN(date.getTime()) ? date : null;

  function blankModifiers() {
    return {
      directionWeights: {}, confirmationWeights: {}, riskSensitivity: 1, exhaustionSensitivity: 1,
      marketSensitivity: 1, normalAtrTolerance: 1, strongBuyOpportunity: 1, rateSensitivity: 1,
      eventSensitivity: 1, longStability: 1, confidenceScale: 1,
      actionGates: { buyDirection: 0, buyConfirmation: 0, strongBuyDirection: 0, strongBuyConfirmation: 0 },
      benchmarkWeights: { spy: 0.5, qqq: 0.5 },
    };
  }

  function capMultiplier(value, special = false) {
    const [low, high] = engine.config.profile.modifierCaps[special ? "special" : "normal"];
    return clamp(value, low, high);
  }

  function effectiveModifiers(companyTraits = [], lifecycle = null) {
    const aggregate = blankModifiers();
    const appliedModifiers = [];
    unique([...companyTraits, lifecycle]).forEach((trait) => {
      const modifier = engine.config.profile.tagModifiers[trait];
      if (!modifier) return;
      appliedModifiers.push(trait);
      Object.entries(modifier.directionWeights || {}).forEach(([key, delta]) => { aggregate.directionWeights[key] = (aggregate.directionWeights[key] || 0) + Number(delta || 0); });
      Object.entries(modifier.confirmationWeights || {}).forEach(([key, delta]) => { aggregate.confirmationWeights[key] = (aggregate.confirmationWeights[key] || 0) + Number(delta || 0); });
      ["riskSensitivity", "exhaustionSensitivity", "marketSensitivity", "normalAtrTolerance", "strongBuyOpportunity", "rateSensitivity", "eventSensitivity", "longStability"].forEach((key) => {
        if (Number.isFinite(modifier[key])) aggregate[key] += modifier[key];
      });
    });
    Object.keys(aggregate.directionWeights).forEach((key) => { aggregate.directionWeights[key] = capMultiplier(1 + aggregate.directionWeights[key]) - 1; });
    Object.keys(aggregate.confirmationWeights).forEach((key) => { aggregate.confirmationWeights[key] = capMultiplier(1 + aggregate.confirmationWeights[key]) - 1; });
    ["riskSensitivity", "exhaustionSensitivity", "marketSensitivity", "normalAtrTolerance", "strongBuyOpportunity", "rateSensitivity", "eventSensitivity", "longStability"].forEach((key) => {
      aggregate[key] = capMultiplier(aggregate[key], key === "marketSensitivity" || key === "exhaustionSensitivity");
    });
    return { modifiers: aggregate, appliedModifiers };
  }

  function cacheKey(ticker) { return String(ticker || "").toUpperCase(); }
  function cachedState(ticker) { return reviewCache.get(cacheKey(ticker)) || null; }
  function annualReviewDue(lastReview, now) {
    const prior = validDate(dateFor(lastReview));
    return !prior || now.getTime() - prior.getTime() >= engine.config.profile.review.annualReviewDays * 86400000;
  }

  // Profiles change only through an explicit annual review. Quote refreshes
  // call build() and cannot churn traits or lifecycle from short-term prices.
  function review({ ticker, profile = {}, now = new Date() } = {}) {
    const key = cacheKey(ticker);
    if (!key) return null;
    const prior = cachedState(key);
    if (prior && !annualReviewDue(prior.lastProfileReview, now)) return prior;
    const next = {
      primaryClassification: profile.primaryClassification || prior?.primaryClassification || "Unclassified Equity",
      companyTraits: unique(profile.companyTraits || prior?.companyTraits || []),
      lifecycle: profile.lifecycle || prior?.lifecycle || null,
      profileConfidence: Number.isFinite(profile.profileConfidence) ? clamp(profile.profileConfidence, 0, 1) : prior?.profileConfidence ?? 0.6,
      lastProfileReview: now.toISOString(),
      scoringProfile: profile.scoringProfile || prior?.scoringProfile || "generic",
    };
    reviewCache.set(key, next);
    while (reviewCache.size > engine.config.profile.review.cacheLimit) reviewCache.delete(reviewCache.keys().next().value);
    return next;
  }

  function build(classification = {}, ticker = "") {
    if (classification.isETF || classification.type === "etf") return engine.etfProfile.build(classification);
    const stored = cachedState(ticker);
    const primaryClassification = stored?.primaryClassification || classification.primaryClassification || classification.primary_classification || classification.category || "Unclassified Equity";
    const companyTraits = unique(stored?.companyTraits || classification.companyTraits || classification.company_traits || classification.tags || []);
    const lifecycle = stored?.lifecycle || classification.lifecycle || classification.lifecycleTag || classification.lifecycle_tag || null;
    const modifierSet = effectiveModifiers(companyTraits, lifecycle);
    return {
      type: "stock", isETF: false, primaryClassification, companyTraits, lifecycle,
      scoringProfile: stored?.scoringProfile || classification.scoringProfile || classification.scoring_profile || "generic",
      profileConfidence: Number.isFinite(stored?.profileConfidence) ? stored.profileConfidence : Number.isFinite(classification.profileConfidence) ? clamp(classification.profileConfidence, 0, 1) : 0.76,
      lastProfileReview: stored?.lastProfileReview || classification.lastProfileReview || classification.last_profile_review || null,
      effectiveModifiers: modifierSet.modifiers, appliedModifiers: modifierSet.appliedModifiers,
    };
  }

  function forHorizon(profile, horizon) { return profile?.isETF ? engine.etfProfile.forHorizon(profile, horizon) : profile; }

  engine.profile = Object.freeze({ build, review, forHorizon, clearReviews: () => reviewCache.clear(), _reviewCache: reviewCache, effectiveModifiers });
}(globalThis));
