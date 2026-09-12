(function createStabilityEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const cache = new Map();
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));

  function evaluate({ ticker, horizon, candidateAction, allowedActions = null, actionFamily = null, edge, confidence, materialChangeReasons = [], profile = {}, technical = {} } = {}) {
    const key = `${String(ticker || "").toUpperCase()}:${horizon}`;
    const previous = cache.get(key);
    const config = engine.config.stability;
    const edgeDelta = previous ? Math.abs((previous.previousEdge || 0) - edge) : null;
    const material = Boolean(materialChangeReasons.length) || (Number.isFinite(edgeDelta) && edgeDelta >= config.materialEdgeDelta);
    const allowed = Array.isArray(allowedActions) && allowedActions.length ? allowedActions : [candidateAction];
    const permittedCandidate = allowed.includes(candidateAction) ? candidateAction : allowed[0];
    let finalAction = permittedCandidate;
    let heldPrevious = false;
    const previousAllowed = Boolean(previous && allowed.includes(previous.previousAction));
    const familyBoundaryOverride = Boolean(previous && !previousAllowed);
    // Hysteresis can only smooth variants within the current Price State's
    // family (Buy/Accumulate, or Trim/Sell). A prior action is never allowed
    // to leak through a confirmed Opportunity/Neutral/Reduce boundary.
    if (previous && previousAllowed && !material && previous.previousAction !== permittedCandidate) {
      const stayBand = config.stayBands[previous.previousAction];
      const longStability = horizon === "long" ? (profile.effectiveModifiers?.longStability || 1) : 1;
      const pad = horizon === "long" ? 8 * longStability : horizon === "mid" ? 4 : 0;
      if (stayBand && edge >= stayBand[0] - pad && edge <= stayBand[1] + pad) {
        finalAction = previous.previousAction;
        heldPrevious = true;
      }
    }
    const changed = Boolean(previous && previous.previousAction !== finalAction);
    // A process restart intentionally loses the bounded hysteresis cache.  In
    // that case, canonical MA/MACD/ADX/RS persistence is the main stability
    // evidence; absence of a previous decision is neither a free perfect score
    // nor an automatic instability penalty.
    const firstObservation = Number.isFinite(technical.signalPersistence?.score)
      ? technical.signalPersistence.score : engine.config.stability.noHistory.unavailable;
    const score = !previous ? firstObservation
      : material ? 30 : heldPrevious ? 88 : changed ? 48 : clamp(86 - Math.min(25, Math.abs(edgeDelta || 0) * 0.45), 55, 92);
    const next = {
      previousAction: finalAction, actionFamily, previousEdge: edge, previousConfidence: confidence,
      lastMaterialChange: material || changed ? new Date().toISOString() : previous?.lastMaterialChange || new Date().toISOString(),
    };
    cache.set(key, next);
    while (cache.size > config.cacheLimit) cache.delete(cache.keys().next().value);
    return { finalAction, allowedActions: allowed, actionFamily, heldPrevious, familyBoundaryOverride, material, materialChangeReasons, score: Math.round(score), firstObservation: !previous, persistence: technical.signalPersistence || null, previous: previous ? { previousAction: previous.previousAction, actionFamily: previous.actionFamily || null, previousEdge: previous.previousEdge, previousConfidence: previous.previousConfidence, lastMaterialChange: previous.lastMaterialChange } : null, lastMaterialChange: next.lastMaterialChange };
  }

  function commit({ ticker, horizon, action, actionFamily = null, edge = 0, confidence = 0, materialChange = false } = {}) {
    const key = `${String(ticker || "").toUpperCase()}:${horizon}`;
    if (!key || !action) return;
    const previous = cache.get(key);
    cache.set(key, {
      previousAction: action,
      actionFamily,
      previousEdge: edge,
      previousConfidence: confidence,
      lastMaterialChange: materialChange ? new Date().toISOString() : previous?.lastMaterialChange || new Date().toISOString(),
    });
    while (cache.size > engine.config.stability.cacheLimit) cache.delete(cache.keys().next().value);
  }

  engine.stability = Object.freeze({ evaluate, commit, clear: () => cache.clear(), _cache: cache });
}(globalThis));
