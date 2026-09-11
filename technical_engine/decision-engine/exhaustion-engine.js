(function createExhaustionEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
  const finite = (value) => value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;
  const label = (score) => score <= -62 ? "bullish_exhaustion" : score <= -24 ? "bullish_extension" : score >= 62 ? "bearish_exhaustion" : score >= 24 ? "bearish_extension" : "neutral";
  const boolLabel = (value, expected) => String(value || "").toLowerCase().includes(expected);

  function scaledHigh(value, start, extreme) {
    return !Number.isFinite(value) ? 0 : clamp((value - start) / Math.max(1, extreme - start), 0, 1) * 100;
  }

  function scaledLow(value, start, extreme) {
    return !Number.isFinite(value) ? 0 : clamp((start - value) / Math.max(1, start - extreme), 0, 1) * 100;
  }

  function evaluate({ technical = {}, market = {}, profile = {} } = {}) {
    const config = engine.config.exhaustion;
    const raw = technical.raw || {};
    const rsi = finite(raw.rsi?.value);
    const kdj = finite(raw.kdj?.j);
    const percentB = finite(raw.bands?.percent_b);
    const maDistance = finite(technical.riskComponents?.extension) || 0;
    const rs = finite(technical.confirmationComponents?.relativeStrength?.score) || 0;
    const participation = finite(technical.confirmationComponents?.participation?.score) || 0;
    const histogramChange = (finite(raw.macd?.histogram_change_1) || 0) * 0.5
      + (finite(raw.macd?.histogram_change_3) || 0) * 0.3
      + (finite(raw.macd?.histogram_change_5) || 0) * 0.2;
    const macdImproving = boolLabel(raw.macd?.improving_or_deteriorating, "improv") || boolLabel(raw.macd?.state, "recover") || raw.macd?.crossover_state === "bullish_cross";
    const macdDeteriorating = boolLabel(raw.macd?.improving_or_deteriorating, "deterior") || boolLabel(raw.macd?.state, "decelerating_bullish") || raw.macd?.crossover_state === "bearish_cross";
    const obvBullishDivergence = raw.obv?.divergence === "bullish_divergence";
    const obvBearishDivergence = raw.obv?.divergence === "bearish_divergence";
    const rvol = finite(raw.volume?.relative_volume?.displayed_rvol ?? raw.volume?.relative_volume?.rvol_20d);
    const volumeClimax = Number.isFinite(rvol) ? scaledHigh(rvol, engine.config.risk.rvol.elevated, engine.config.risk.rvol.extreme) : 0;

    // Extreme alone is not contrarian evidence.  The second half is marginal
    // deterioration/repair: a still-accelerating, well-participated trend is
    // intentionally capped well below an exhaustion action gate.
    const bullishExtreme = clamp(
      scaledHigh(rsi, config.highRsi, config.extremeRsi) * 0.30
      + scaledHigh(kdj, config.highKdj, 110) * 0.17
      + scaledHigh(percentB, config.extensionPercentB, 1.35) * 0.20
      + scaledHigh(maDistance, 42, 90) * 0.18
      + scaledHigh(rs, 48, 90) * 0.15,
      0, 100,
    );
    const bullishDeterioration = clamp(
      (histogramChange < 0 ? scaledHigh(-histogramChange, 0.01, 0.35) : 0) * 0.28
      + (macdDeteriorating ? 28 : 0)
      + (obvBearishDivergence ? 24 : 0)
      + (participation < -20 ? 18 : 0)
      + (rs > 25 && raw.relativeStrength?.consistency?.state === "deteriorating" ? 16 : 0)
      + (volumeClimax > 50 && participation < 20 ? 14 : 0),
      0, 100,
    );
    let bullishExhaustion = bullishExtreme * 0.55 + bullishDeterioration * 0.45;
    if (bullishDeterioration < 22 && participation > 22 && (macdImproving || histogramChange > 0)) {
      bullishExhaustion = Math.min(bullishExhaustion, config.trendWithoutDeteriorationCap);
    }

    const bearishExtreme = clamp(
      scaledLow(rsi, config.lowRsi, config.extremeLowRsi) * 0.30
      + scaledLow(kdj, config.lowKdj, -10) * 0.17
      + scaledLow(percentB, config.downsidePercentB, -0.35) * 0.20
      + scaledHigh(maDistance, 42, 90) * 0.18
      + scaledHigh(-rs, 48, 90) * 0.15,
      0, 100,
    );
    const bearishRepair = clamp(
      (histogramChange > 0 ? scaledHigh(histogramChange, 0.01, 0.35) : 0) * 0.28
      + (macdImproving ? 28 : 0)
      + (obvBullishDivergence ? 24 : 0)
      + (participation > 15 ? 18 : 0)
      + (rs < -25 && raw.relativeStrength?.consistency?.state !== "deteriorating" ? 16 : 0)
      + (volumeClimax > 50 && participation > -10 ? 14 : 0),
      0, 100,
    );
    let bearishExhaustion = bearishExtreme * 0.55 + bearishRepair * 0.45;
    if (bearishRepair < 22 && participation < -22 && !macdImproving) {
      bearishExhaustion = Math.min(bearishExhaustion, config.trendWithoutDeteriorationCap);
    }

    const fearGreedValue = finite(market.fearGreed?.value ?? market.fearGreed?.score);
    const marketContrarian = !Number.isFinite(fearGreedValue) ? 0
      : fearGreedValue >= engine.config.market.fearGreed.extremeGreed ? -config.marketContrarianMax
        : fearGreedValue <= engine.config.market.fearGreed.extremeFear ? config.marketContrarianMax : 0;
    const sensitivity = profile.effectiveModifiers?.exhaustionSensitivity || 1;
    const score = clamp((bearishExhaustion - bullishExhaustion + marketContrarian) * sensitivity, -100, 100);
    const supporting = [];
    const limiting = [];
    if (score >= 28) supporting.push("Downside exhaustion is developing while repair evidence is appearing.");
    if (score <= -28) limiting.push("Upside is extended and marginal momentum/participation is weakening.");
    return {
      score: Math.round(score), label: label(score), supporting, limiting,
      components: {
        bullishExtreme: Math.round(bullishExtreme), bullishDeterioration: Math.round(bullishDeterioration),
        bearishExtreme: Math.round(bearishExtreme), bearishRepair: Math.round(bearishRepair),
        marketContrarian, sensitivity,
        bullishEvidence: {
          rsiExtreme: Math.round(scaledHigh(rsi, config.highRsi, config.extremeRsi)), kdjExtreme: Math.round(scaledHigh(kdj, config.highKdj, 110)),
          bollingerExtension: Math.round(scaledHigh(percentB, config.extensionPercentB, 1.35)), maExtension: Math.round(scaledHigh(maDistance, 42, 90)), relativeStrengthExtreme: Math.round(scaledHigh(rs, 48, 90)),
          histogramDeterioration: Math.round(histogramChange < 0 ? scaledHigh(-histogramChange, 0.01, 0.35) : 0), macdDeteriorating, obvBearishDivergence, participationWeak: participation < -20,
        },
        bearishEvidence: {
          rsiExtreme: Math.round(scaledLow(rsi, config.lowRsi, config.extremeLowRsi)), kdjExtreme: Math.round(scaledLow(kdj, config.lowKdj, -10)),
          bollingerExtension: Math.round(scaledLow(percentB, config.downsidePercentB, -0.35)), maExtension: Math.round(scaledHigh(maDistance, 42, 90)), relativeStrengthExtreme: Math.round(scaledHigh(-rs, 48, 90)),
          histogramRepair: Math.round(histogramChange > 0 ? scaledHigh(histogramChange, 0.01, 0.35) : 0), macdImproving, obvBullishDivergence, participationImproving: participation > 15,
        },
      },
    };
  }

  engine.exhaustion = Object.freeze({ evaluate });
}(globalThis));
