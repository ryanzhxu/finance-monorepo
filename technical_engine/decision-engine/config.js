(function configureDecisionEngine(root) {
  "use strict";

  const engine = root.DecisionEngine || (root.DecisionEngine = {});
  const freeze = (value) => Object.freeze(value);

  engine.config = freeze({
    version: "decision-engine-v1",
    actions: freeze(["strong_buy", "buy", "accumulate", "hold", "trim", "sell", "avoid"]),
    actionLabels: freeze({
      strong_buy: freeze({ en: "Strong Buy", zh: "强力买入" }),
      buy: freeze({ en: "Buy", zh: "买入" }),
      accumulate: freeze({ en: "Accumulate", zh: "逐步加仓" }),
      hold: freeze({ en: "Hold", zh: "持有" }),
      trim: freeze({ en: "Trim", zh: "减仓" }),
      sell: freeze({ en: "Sell", zh: "卖出" }),
      avoid: freeze({ en: "Avoid", zh: "回避" }),
    }),
    horizons: freeze({
      short: freeze({
        label: "1–30 days", technicalKey: "short", fibonacciKey: "short_term", primaryInterval: "4h", earlyInterval: "1h", rsiPeriod: 6,
        directionWeights: freeze({ ma: 0.40, macd: 0.30, adx: 0.15, early: 0.15 }),
        confirmationWeights: freeze({ relativeStrength: 0.30, participation: 0.30, rsi: 0.20, adx: 0.10, momentum: 0.10 }),
        marketSensitivity: 1.0, rangeAtrWidth: 0.65, structuralDistanceAtr: 2.2,
      }),
      mid: freeze({
        label: "1–6 months", technicalKey: "medium", fibonacciKey: "mid_term", primaryInterval: "1d", earlyInterval: "4h", rsiPeriod: 14,
        directionWeights: freeze({ ma: 0.45, macd: 0.30, adx: 0.15, early: 0.10 }),
        confirmationWeights: freeze({ relativeStrength: 0.35, participation: 0.30, rsi: 0.20, adx: 0.10, momentum: 0.05 }),
        marketSensitivity: 0.70, rangeAtrWidth: 0.85, structuralDistanceAtr: 2.8,
      }),
      long: freeze({
        label: "> 6 months", technicalKey: "long", fibonacciKey: "long_term", primaryInterval: "1w", maInterval: "1d", earlyInterval: "1d", rsiPeriod: 21,
        directionWeights: freeze({ ma: 0.50, macd: 0.30, adx: 0.15, early: 0.05 }),
        confirmationWeights: freeze({ relativeStrength: 0.40, participation: 0.30, rsi: 0.20, adx: 0.10, momentum: 0.00 }),
        marketSensitivity: 0.40, rangeAtrWidth: 0.70, structuralDistanceAtr: 3.5,
      }),
    }),
    componentScales: freeze({
      stateScores: freeze({ bullish: 58, bearish: -58, recovering: 28, deteriorating: -28, rising: 32, falling: -32, neutral: 0 }),
      ma: freeze({ priceAtrScale: 1.8, orderingAtrScale: 0.8, priceWeight: 0.36, orderingWeight: 0.40, slopeWeight: 0.20, persistenceWeight: 0.04 }),
      macd: freeze({ lineSignalAtrScale: 0.14, histogramAtrScale: 0.07, histogramChangeAtrScale: 0.045, zeroWeight: 0.24, spreadWeight: 0.27, histogramWeight: 0.20, changeWeight: 0.17, crossoverWeight: 0.07, stateWeight: 0.05 }),
      adx: freeze({ low: 15, fullStrength: 42, diSpreadScale: 0.55 }),
      relativeStrength: freeze({ benchmarkWeight: 0.65, stockReturnWeight: 0.35, returnScale: 4.2, persistenceBonus: 10 }),
      participation: freeze({ obvWeight: 0.38, divergenceWeight: 0.22, confirmationWeight: 0.18, rvolWeight: 0.12, volumeTrendWeight: 0.10 }),
      rsi: freeze({ healthyBullish: freeze([52, 70]), healthyBearish: freeze([30, 48]), extremeHigh: 78, extremeLow: 22 }),
      opportunity: freeze({
        confluenceBandAtr: 0.72, supportEligibilityAtr: 0.05, reduceEligibilityAtr: 0.25, clusterDedupAtr: 0.32, clusterCandidateLimit: 8,
        structuralLevelWeight: freeze({ fib: 0.65, moving_average: 0.80, swing: 1.0, price_structure: 1.10, bollinger: 0.65, daily_fib_confirmation: 0.25 }),
        // The Price Structure Engine is one category-aware confluence model.
        // More levels from one category improve localisation, but they must
        // not be treated as independent proof of a zone.
        unifiedConfluence: freeze({
          categoryForType: freeze({ fib: "fibonacci", daily_fib_confirmation: "fibonacci", swing: "swing", price_structure: "historical", moving_average: "moving_average", bollinger: "bollinger" }),
          categoryContributionCap: freeze({ fibonacci: 0.85, swing: 1.0, historical: 1.10, moving_average: 0.82, bollinger: 0.65 }),
          crossCategoryBonus: 0.30,
          categoryQualityFloor: 0.15,
          qualityReference: 3.2,
          pairQualityReference: 6.4,
          roleAlignmentWeight: 0.45,
        }),
        maxConfluenceScore: 62, extensionWeight: 24,
      }),
    }),
    risk: freeze({
      atrPct: freeze({ mild: 2.0, elevated: 4.0, high: 7.0, extreme: 11.0 }),
      atrPercentile: freeze({ elevated: 70, extreme: 92 }),
      volatilityRegime: freeze({ low: 0, normal: 0, elevated: 55, high: 75, extreme: 90, unavailable: 0 }),
      bollingerPercentB: freeze({ extended: 1.0, extreme: 1.25 }),
      bollingerWidthPercentile: freeze({ elevated: 75, extreme: 95 }),
      maExtensionAtr: freeze({ elevated: 2.0, extreme: 3.8 }),
      rsi: freeze({ elevatedHigh: 74, elevatedLow: 26, extremeHigh: 84, extremeLow: 16 }),
      kdj: freeze({ elevated: 90, extreme: 105 }),
      rvol: freeze({ elevated: 1.8, extreme: 3.2 }),
      // Correlated observations are combined inside their own group before the
      // groups are accumulated.  This prevents ATR%, ATR percentile, regime,
      // and Bollinger width from treating one volatility episode as four risks.
      groupBlend: freeze({ primary: 0.65, secondary: 0.25, tertiary: 0.10 }),
      nonlinearImpacts: freeze({ volatility: 0.34, extension: 0.30, eventShock: 0.25 }),
      extremeFloor: freeze({ volatility: 84, extension: 74, shock: 88 }),
      labels: freeze([[30, "normal"], [50, "mild"], [70, "elevated"], [85, "high"], [101, "extreme"]]),
    }),
    exhaustion: freeze({
      highRsi: 72, lowRsi: 28, extremeRsi: 82, extremeLowRsi: 18,
      highKdj: 88, lowKdj: 12, extensionPercentB: 1.05, downsidePercentB: -0.05,
      trendWithoutDeteriorationCap: 28, marketContrarianMax: 14,
      contrarianEdgeWeight: 0.28,
    }),
    market: freeze({
      vix: freeze({ cautious: 21, riskOff: 28, shock: 35, spike5d: 6, spike20d: 10 }),
      yields: freeze({ restrictive: 4.5, severe: 5.0, rising5dBps: 18, rising20dBps: 35 }),
      regimes: freeze({ risk_on: freeze({ riskAdd: 0, confidencePenalty: 0 }), normal: freeze({ riskAdd: 0, confidencePenalty: 0 }), cautious: freeze({ riskAdd: 10, confidencePenalty: 6 }), risk_off: freeze({ riskAdd: 22, confidencePenalty: 13 }), shock: freeze({ riskAdd: 38, confidencePenalty: 24 }) }),
      maxRiskAdd: freeze({ short: 32, mid: 24, long: 18 }),
      earnings: freeze({ nearDays: 7, immediateDays: 2, nearRiskAdd: 12, immediateRiskAdd: 20, confidencePenalty: 10 }),
      fearGreed: freeze({ extremeGreed: 80, extremeFear: 20 }),
    }),
    edge: freeze({ directionTrustFloor: 0.46, directionTrustConfirmationWeight: 0.54, priceOpportunityWeight: 0.20, riskPenaltyMax: 0.52, riskPenaltyStart: 32, riskPenaltyPower: 1.65 }),
    actionPolicy: freeze({
      minimumDataQuality: 38,
      territories: freeze({ strongBuy: 80, buy: 55, accumulate: 25, holdFloor: -20, trim: -25, sell: -55 }),
      gates: freeze({ strongBuy: freeze({ direction: 62, confirmation: 76, priceOpportunity: 24, riskMaximum: 42, bullishExhaustionMaximum: 28, confidence: 78 }), buy: freeze({ direction: 30, confirmation: 57, riskMaximum: 64 }), accumulate: freeze({ riskMaximum: 76 }), sell: freeze({ direction: -55, confirmation: 58 }), bearishContrarianAccumulate: freeze({ exhaustion: 58, priceOpportunity: 36, dataQuality: 55 }), neutralAvoidRisk: 84, extremeRisk: 88, confidenceMinimum: freeze({ strong_buy: 78, buy: 48, accumulate: 38 }) }),
    }),
    execution: freeze({
      invalidationAtrBuffer: 0.55,
      actionableRangeToleranceAtr: 0.28, staleRangeDistanceAtr: 2.5,
      // These are width and distance safety rails, not fixed-price ranges.
      // Centre still comes only from structural confluence; ATR determines the
      // unconstrained width before the horizon-specific normalisation below.
      maxHalfWidthPct: freeze({ short: 0.035, mid: 0.045, long: 0.060 }),
      maxEntryCenterDistanceAtr: freeze({ short: 1.15, mid: 1.45, long: 1.70 }),
      maxEntryCenterDistancePct: freeze({ short: 0.035, mid: 0.055, long: 0.070 }),
      confluenceWidthMultiplier: freeze({ weak: 0.72, strong: 0.94 }),
      minimumConfluenceForFormalEntry: 14,
      landscape: freeze({
        neutralBufferAtr: freeze({ short: 0.42, mid: 0.62, long: 0.86 }),
        minimumHalfWidthAtr: freeze({ short: 0.22, mid: 0.28, long: 0.34 }),
        weakQualityPenalty: 9,
        invalidQualityPenalty: 24,
        minimumPairQuality: 0.85,
        // Structural clusters remain the only zone centres.  These inputs
        // merely select between existing clusters as trend/risk conditions
        // evolve; they never shift a centre by a fixed percentage or ATR.
        contextualSelection: freeze({
          minimumReduceDistanceAtr: freeze({ short: 0.70, mid: 0.95, long: 1.20 }),
          bullishTrendLiftAtr: freeze({ short: 1.10, mid: 1.45, long: 1.85 }),
          prematureReducePenalty: 0.72,
          supportDistancePenalty: 0.13,
          reduceDistancePenalty: 0.05,
          bearishPressureProximityBonus: 0.16,
        }),
      }),
      priceState: freeze({
        nearOpportunityAtr: freeze({ short: 1.15, mid: 1.45, long: 1.70 }),
        nearReduceAtr: freeze({ short: 0.85, mid: 1.15, long: 1.45 }),
        // Near-zone tolerance must never consume the entire deliberate
        // Neutral buffer between two actionable zones.
        neutralBufferNearShare: 0.42,
        minimumNearAtr: 0.15,
      }),
      actionFamily: freeze({
        // A confirmed breakdown is a separate Price State.  The threshold is
        // deliberately stricter than an ordinary bearish direction so that
        // routine weakness cannot erase a still-valid opportunity zone.
        breakdownDirection: -68,
        breakdownConfirmation: 52,
        sellDirection: -45,
        sellConfirmation: 55,
        sellRisk: 60,
        sellBullishExhaustion: -56,
      }),
    }),
    stability: freeze({
      cacheLimit: 300, materialEdgeDelta: 26,
      stayBands: freeze({ strong_buy: freeze([68, 101]), buy: freeze([35, 101]), accumulate: freeze([6, 101]), hold: freeze([-30, 34]), trim: freeze([-64, -8]), sell: freeze([-101, -35]), avoid: freeze([-101, 30]) }),
      material: freeze({ atrShock: 82, majorBreakdown: -68, majorBreakout: 68 }),
      noHistory: freeze({ ma: 0.36, macd: 0.30, adx: 0.18, relativeStrength: 0.16, minimum: 42, maximum: 76, unavailable: 45 }),
    }),
    confidence: freeze({
      weights: freeze({ agreement: 0.35, actionStrength: 0.25, stability: 0.20, dataQuality: 0.10, profileConfidence: 0.10 }),
      penalties: freeze({ marketConflict: 18, exhaustionConflict: 16, eventUncertainty: 12, internalConflict: 18, priceConflict: 14, invalidLandscape: 18 }),
    }),
    profile: freeze({
      review: freeze({ annualReviewDays: 365, cacheLimit: 300 }),
      modifierCaps: freeze({ normal: freeze([0.85, 1.15]), special: freeze([0.80, 1.20]) }),
      lifecycleTagNames: freeze(["Emerging", "Scaling", "HighGrowth", "EstablishedLeader", "MatureLeader", "Downcycle", "Bottoming", "Recovery", "Expansion", "Peak/Crowded"]),
      tagModifiers: freeze({
        MegaCap: freeze({ directionWeights: freeze({ early: -0.08 }), riskSensitivity: -0.05, marketSensitivity: -0.05 }),
        HighGrowth: freeze({ directionWeights: freeze({ macd: 0.06 }), confirmationWeights: freeze({ relativeStrength: 0.08 }), exhaustionSensitivity: 0.10, riskSensitivity: 0.05 }),
        HighBeta: freeze({ riskSensitivity: 0.10, marketSensitivity: 0.12, normalAtrTolerance: 0.10 }),
        HighVolatility: freeze({ riskSensitivity: 0.08, marketSensitivity: 0.10, normalAtrTolerance: 0.08 }),
        MarketLeader: freeze({ directionWeights: freeze({ ma: 0.05 }), confirmationWeights: freeze({ relativeStrength: 0.05 }), strongBuyOpportunity: 0.08 }),
        EstablishedLeader: freeze({ directionWeights: freeze({ ma: 0.05 }), strongBuyOpportunity: 0.10, marketSensitivity: -0.04 }),
        CrowdedLeader: freeze({ exhaustionSensitivity: 0.18, riskSensitivity: 0.05 }),
        Cyclical: freeze({ confirmationWeights: freeze({ participation: 0.07, relativeStrength: 0.04 }), exhaustionSensitivity: 0.12 }),
        MemoryStorage: freeze({ confirmationWeights: freeze({ participation: 0.08, relativeStrength: 0.05 }), exhaustionSensitivity: 0.15 }),
        InterestRateSensitive: freeze({ rateSensitivity: 0.18, marketSensitivity: 0.08 }),
        REIT: freeze({ rateSensitivity: 0.18, marketSensitivity: 0.08 }),
        CashCow: freeze({ riskSensitivity: -0.05, marketSensitivity: -0.04, longStability: 0.08 }),
        RegulatoryRisk: freeze({ eventSensitivity: 0.12, marketSensitivity: 0.06 }),
      }),
    }),
    etf: freeze({
      leveraged: freeze({
        modifierDelta: freeze({ riskSensitivity: 0.12, exhaustionSensitivity: 0.10, marketSensitivity: 0.16, normalAtrTolerance: 0.10 }),
        gates: freeze({ buyDirection: 4, buyConfirmation: 3, strongBuyDirection: 8, strongBuyConfirmation: 6 }),
        confidenceScale: freeze({ short: 0.98, mid: 0.92, long: 0.86 }),
      }),
      inverse: freeze({ underlyingConfirmationImpact: 14, underlyingConflictImpact: 16 }),
    }),
  });
}(globalThis));
