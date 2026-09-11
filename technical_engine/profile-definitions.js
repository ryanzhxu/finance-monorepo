/* Shared, reviewable profile metadata. This is classification data, not a
 * recommendation score: the Decision Engine turns the relevant traits into
 * bounded behavior modifiers in decision-engine/company-profile.js. */
(function createProfileDefinitions(root) {
  "use strict";

  const freezeProfile = (profile) => Object.freeze({
    ...profile,
    companyTraits: Object.freeze([...(profile.companyTraits || [])]),
  });
  const stock = (primaryClassification, companyTraits, lifecycle, scoringProfile) => freezeProfile({
    type: "stock", primaryClassification, companyTraits, lifecycle,
    scoringProfile, profileConfidence: 0.82, lastProfileReview: "2026-01-15T00:00:00.000Z",
  });
  const etf = (leveraged, direction, underlying, underlyingTicker = null) => Object.freeze({
    type: "etf", isETF: true, leveraged, direction, underlying, underlyingTicker,
  });

  const stocks = Object.freeze({
    NVDA: stock("AI Compute & Semiconductors", ["Semiconductor", "GPU", "AIInfrastructure", "DataCenter", "MegaCap", "HighGrowth", "CrowdedLeader"], "EstablishedLeader", "ai_infrastructure"),
    TSLA: stock("Electric Vehicles & Energy Storage", ["EV", "AutoManufacturer", "EnergyStorage", "HighGrowth", "HighVolatility", "MegaCap"], "Scaling", "high_growth_cyclical"),
    AMD: stock("AI Compute & Semiconductors", ["Semiconductor", "GPU", "AIInfrastructure", "DataCenter", "LargeCap", "HighVolatility"], "Recovery", "ai_infrastructure"),
    BABA: stock("E-Commerce & Cloud", ["Ecommerce", "Cloud", "ChinaInternet", "ConsumerPlatform", "LargeCap", "RegulatoryRisk"], "Recovery", "china_adr"),
    GOOGL: stock("Digital Advertising & Cloud", ["DigitalAds", "Cloud", "AI", "ConsumerPlatform", "MegaCap", "CashCow", "RegulatoryRisk"], "EstablishedLeader", "platform_ads"),
    AMZN: stock("E-Commerce & Cloud", ["Ecommerce", "Cloud", "AI", "ConsumerPlatform", "MegaCap", "CashCow"], "EstablishedLeader", "software_cloud"),
    AAPL: stock("Consumer Technology", ["ConsumerTechnology", "Ecosystem", "Hardware", "MegaCap", "CashCow", "MatureGrowth"], "MatureLeader", "consumer_technology"),
    CRCL: stock("Digital Asset Infrastructure", ["DigitalAssets", "PaymentsInfrastructure", "Fintech", "HighGrowth", "HighVolatility"], "Scaling", "digital_assets"),
    FFAI: stock("Electric Vehicles", ["EV", "AutoManufacturer", "Speculative", "HighVolatility", "SmallCap"], "Emerging", "speculative_growth"),
    HIMS: stock("Consumer Digital Health", ["HealthcareTechnology", "Telehealth", "ConsumerSubscription", "HighGrowth", "MidCap"], "Scaling", "healthcare_growth"),
    MPT: stock("Healthcare Real Estate", ["REIT", "HealthcareRealEstate", "Dividend", "InterestRateSensitive", "SmallCap", "HighDebtRisk"], "Recovery", "reit_dividend"),
    META: stock("Digital Advertising & Social Platforms", ["DigitalAds", "SocialMedia", "AI", "ConsumerPlatform", "MegaCap", "CashCow", "RegulatoryRisk"], "EstablishedLeader", "platform_ads"),
    MSFT: stock("Enterprise Software & Cloud", ["EnterpriseSoftware", "Cloud", "AI", "MegaCap", "CashCow", "MatureGrowth"], "MatureLeader", "software_cloud"),
    NFLX: stock("Streaming & Digital Media", ["Streaming", "DigitalMedia", "ConsumerSubscription", "MarketLeader", "LargeCap", "HighGrowth"], "EstablishedLeader", "consumer_platform"),
    PLTR: stock("Enterprise AI & Data Analytics", ["EnterpriseSoftware", "AIInfrastructure", "DataAnalytics", "HighGrowth", "MarketLeader", "HighMultiple"], "Scaling", "enterprise_ai"),
    NOW: stock("Enterprise Workflow Software", ["EnterpriseSoftware", "Cloud", "WorkflowAutomation", "HighGrowth", "LargeCap"], "EstablishedLeader", "enterprise_software"),
    SOFI: stock("Digital Financial Services", ["Fintech", "DigitalBanking", "ConsumerFinance", "HighGrowth", "MidCap"], "Scaling", "fintech"),
    TEM: stock("Healthcare AI & Diagnostics", ["HealthcareTechnology", "Diagnostics", "DataAnalytics", "AIInfrastructure", "HighGrowth", "MidCap"], "Scaling", "healthcare_growth"),
    XE: stock("Advanced Nuclear Technology", ["NuclearEnergy", "EnergyTransition", "IndustrialTechnology", "HighVolatility", "SmallCap"], "Emerging", "energy_transition"),
    ZETA: stock("Marketing Technology & Data", ["MarTech", "DigitalAds", "DataAnalytics", "HighGrowth", "MidCap"], "Scaling", "martech"),
    "300657": stock("Chinese Digital Services", ["ChinaTechnology", "DigitalServices", "HighGrowth", "MidCap"], "Scaling", "china_growth"),
    "002463": stock("Chinese Industrial Technology", ["ChinaIndustrials", "IndustrialTechnology", "Cyclical", "MidCap"], "Recovery", "china_industrial"),
    "603005": stock("Chinese Consumer Technology", ["ChinaConsumer", "ConsumerTechnology", "HighGrowth", "MidCap"], "Scaling", "china_consumer"),
    "600522": stock("Chinese Pharmaceutical Services", ["ChinaHealthcare", "HealthcareServices", "Defensive", "MidCap"], "Recovery", "china_healthcare"),
    MU: stock("Memory Semiconductors", ["Semiconductor", "MemoryStorage", "DRAMNAND", "Cyclical", "AIInfrastructure", "LargeCap"], "Recovery", "memory_cycle"),
    PDD: stock("China E-Commerce", ["Ecommerce", "ChinaInternet", "ConsumerPlatform", "HighGrowth", "LargeCap", "RegulatoryRisk"], "Scaling", "china_internet"),
    SPCX: stock("Space Technology", ["SpaceTechnology", "Aerospace", "Speculative", "HighVolatility", "SmallCap"], "Emerging", "speculative_growth"),
    GEV: stock("Grid & Electrification Equipment", ["PowerInfrastructure", "Electrification", "IndustrialTechnology", "HighGrowth", "LargeCap"], "Expansion", "industrial_growth"),
    UNH: stock("Managed Care & Health Services", ["HealthInsurance", "HealthcareServices", "Defensive", "CashCow", "MegaCap", "RegulatoryRisk"], "MatureLeader", "healthcare_defensive"),
    "002213": stock("Chinese Consumer Products", ["ChinaConsumer", "ConsumerProducts", "Defensive", "MidCap"], "MatureLeader", "china_consumer"),
    "600498": stock("Chinese Telecom Infrastructure", ["TelecomInfrastructure", "ChinaTechnology", "IndustrialTechnology", "MidCap"], "Recovery", "china_infrastructure"),
    "600460": stock("Chinese Semiconductors", ["Semiconductor", "ChinaTechnology", "Cyclical", "HighVolatility", "MidCap"], "Recovery", "china_semiconductor"),
    "600641": stock("Chinese Digital Infrastructure", ["DigitalInfrastructure", "ChinaTechnology", "TelecomInfrastructure", "MidCap"], "Recovery", "china_infrastructure"),
    CRWV: stock("AI Cloud Infrastructure", ["Cloud", "AIInfrastructure", "DataCenter", "HighGrowth", "HighVolatility"], "Scaling", "ai_infrastructure"),
  });

  const etfs = Object.freeze({
    QQQ: etf(false, "long", "Nasdaq-100", "QQQ"),
    SPMO: etf(false, "long", "S&P 500 Momentum", "SPY"),
    TQQQ: etf(true, "long", "Nasdaq-100", "QQQ"),
    SQQQ: etf(true, "inverse", "Nasdaq-100", "QQQ"),
    SOXL: etf(true, "long", "Semiconductor Sector", "SOXX"),
    SOXS: etf(true, "inverse", "Semiconductor Sector", "SOXX"),
  });

  function profileFor(ticker, metadata = {}) {
    const symbol = String(ticker || "").toUpperCase();
    if (etfs[symbol]) return etfs[symbol];
    if (stocks[symbol]) return stocks[symbol];
    const type = String(metadata.quoteType || metadata.quote_type || "").toUpperCase();
    if (type === "ETF") return etf(false, "long", metadata.longName || metadata.name || symbol, null);
    return stock(
      metadata.industry || metadata.sector || "Unclassified Equity",
      [metadata.sector || "Equity", metadata.industry || "DiversifiedBusiness", "UnreviewedProfile"],
      "EstablishedLeader",
      "generic",
    );
  }

  const api = Object.freeze({ stocks, etfs, profileFor });
  root.ProfileDefinitions = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
}(globalThis));
