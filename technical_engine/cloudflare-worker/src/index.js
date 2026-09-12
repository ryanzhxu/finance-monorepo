// decision.v1 at the edge.
//
// Serves this repository's production Decision Engine from a Cloudflare Worker,
// so a consumer can read a decision over HTTP without running the browser
// bundle or the Flask server.
//
// The engine is imported for side effects only. Every module here attaches its
// API to `globalThis` (`root.DecisionEngine`, `root.CanonicalTechnicalFeatures`,
// `root.ProfileDefinitions`), so the same files the Dashboard loads run
// unmodified at the edge. Nothing in this file scores, thresholds, or computes a
// price level — per AGENTS.md that is the engine's job alone, and this Worker
// only fetches inputs and reshapes the output.
//
// KNOWN LIMIT: the short horizon needs native 4h and 1h bars. Yahoo's chart API
// exposes 1h but no native 4h, and this engine deliberately refuses to
// synthesize one (see validate_native_four_hour_history_frame in server.py), so
// short currently reports INVALID_LANDSCAPE while mid and long are fully
// supported. That is reported honestly rather than filled with a resampled
// approximation.

import "../../technical-features.js";
import "../../profile-definitions.js";
import "../../decision-engine/feature-inputs.js";
import "../../decision-engine/config.js";
import "../../decision-engine/technical-engine.js";
import "../../decision-engine/exhaustion-engine.js";
import "../../decision-engine/market-engine.js";
import "../../decision-engine/etf-profile.js";
import "../../decision-engine/company-profile.js";
import "../../decision-engine/execution-engine.js";
import "../../decision-engine/confidence-engine.js";
import "../../decision-engine/stability-engine.js";
import "../../decision-engine/decision-engine.js";

const CONTRACT_VERSION = "decision.v1";
const PRODUCER = "vincent-stock-decision-dashboard";
const HORIZONS = ["short", "mid", "long"];
const BENCHMARKS = ["SPY", "QQQ"];
const MAX_TICKERS = 10;
const CHART_HOST = "https://query1.finance.yahoo.com";
// Market context changes slowly; a decision does not. Cache the benchmark legs
// longer than the per-ticker bars.
const TICKER_TTL_SECONDS = 300;
const BENCHMARK_TTL_SECONDS = 900;

const engine = () => globalThis.DecisionEngine;
const features = () => globalThis.CanonicalTechnicalFeatures;
const profiles = () => globalThis.ProfileDefinitions;
const inputs = () => globalThis.DecisionFeatureInputs;

const finite = (value) =>
  value == null || value === "" ? null : Number.isFinite(Number(value)) ? Number(value) : null;

function json(body, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": "application/json; charset=utf-8",
      // The consumer is a different origin (the finance-monorepo Worker and its
      // Pages frontend), and this endpoint exposes no credentials.
      "access-control-allow-origin": "*",
      "access-control-allow-methods": "GET, OPTIONS",
      "cache-control": "no-store",
    },
  });
}

async function fetchChart(symbol, { interval = "1d", range = "2y", ttl }) {
  const url = `${CHART_HOST}/v8/finance/chart/${encodeURIComponent(symbol)}?interval=${interval}&range=${range}&includePrePost=false`;
  const response = await fetch(url, {
    headers: { "user-agent": "Mozilla/5.0 (compatible; decision-v1-worker)" },
    cf: { cacheTtl: ttl, cacheEverything: true },
  });
  if (!response.ok) throw new Error(`HTTP ${response.status} from Yahoo chart for ${symbol}`);
  const payload = await response.json();
  const result = payload?.chart?.result?.[0];
  if (!result) throw new Error(`no chart result for ${symbol}`);
  return result;
}

// Shape Yahoo's columnar chart response into the bar object
// technical-features.js normalizes. Rows with any missing OHLC value are
// dropped rather than interpolated — a fabricated bar is worse than a short
// history, because every downstream indicator would silently trust it.
function barsFrom(result) {
  const timestamps = result?.timestamp || [];
  const quote = result?.indicators?.quote?.[0] || {};
  const adjclose = result?.indicators?.adjclose?.[0]?.adjclose || null;
  const out = { timestamps: [], opens: [], highs: [], lows: [], closes: [], volumes: [] };
  for (let index = 0; index < timestamps.length; index += 1) {
    const open = finite(quote.open?.[index]);
    const high = finite(quote.high?.[index]);
    const low = finite(quote.low?.[index]);
    const close = finite(adjclose ? adjclose[index] : quote.close?.[index]);
    if (open == null || high == null || low == null || close == null) continue;
    out.timestamps.push(new Date(timestamps[index] * 1000).toISOString().slice(0, 10));
    out.opens.push(open);
    out.highs.push(high);
    out.lows.push(low);
    out.closes.push(close);
    out.volumes.push(finite(quote.volume?.[index]) ?? 0);
  }
  const available = out.closes.length > 0;
  return { ...out, availability: available ? "available" : "unavailable", available, lookback: "2y" };
}

function changePct(closes, lookback) {
  const latest = closes.at(-1);
  const base = closes.at(-1 - lookback);
  return Number.isFinite(latest) && Number.isFinite(base) && base !== 0
    ? (latest / base - 1) * 100
    : null;
}

async function benchmarkTrend(symbol) {
  const bars = barsFrom(await fetchChart(symbol, { ttl: BENCHMARK_TTL_SECONDS }));
  return Object.fromEntries(
    [20, 60, 120].map((days) => [`change_${days}d_pct`, changePct(bars.closes, days)]),
  );
}

async function marketContext() {
  const [spy, qqq] = await Promise.all(BENCHMARKS.map((symbol) => benchmarkTrend(symbol).catch(() => ({}))));
  return { market_context: { regime: "normal", equity_trend: { spy, qqq } } };
}

async function quoteFor(symbol) {
  const result = await fetchChart(symbol, { ttl: TICKER_TTL_SECONDS });
  const daily = barsFrom(result);
  const meta = result?.meta || {};
  return {
    ticker: symbol,
    price: finite(meta.regularMarketPrice) ?? daily.closes.at(-1) ?? null,
    quote_status: daily.available ? "available" : "unavailable",
    history: { ...daily, intervals: { "1d": daily }, daily_history_metadata: { lookback: "2y" } },
    metadata: {
      quoteType: meta.instrumentType || "EQUITY",
      sharesOutstanding: null,
      currency: meta.currency || null,
      exchangeName: meta.fullExchangeName || meta.exchangeName || null,
    },
    technical: { fibonacci_structure: {} },
  };
}

function band(range) {
  const low = finite(range?.low);
  const high = finite(range?.high);
  return low != null && high != null ? { low, high } : null;
}

function horizonPayload(decision, horizon, quote) {
  const value = decision?.horizons?.[horizon];
  if (!value) {
    return {
      action: "avoid",
      confidence: 0,
      priceState: "INVALID_LANDSCAPE",
      executionIntent: "avoid",
      opportunityRange: null,
      reduceRange: null,
      invalidation: null,
      currentPrice: finite(quote?.price),
      reasons: ["Horizon unavailable"],
      dataQuality: null,
    };
  }
  const landscape = value.priceLandscape || {};
  const priceState = value.debug?.priceState || "INVALID_LANDSCAPE";
  const usable = priceState !== "INVALID_LANDSCAPE";
  return {
    action: value.action,
    // The engine's own 0-100 scale, which is decision.v1's scale. Consumers
    // working in 0.0-1.0 divide on their side.
    confidence: finite(value.confidence),
    priceState,
    executionIntent: value.executionIntent || null,
    opportunityRange: usable ? band(landscape.opportunityRange) : null,
    reduceRange: usable ? band(landscape.reduceRange) : null,
    invalidation: usable ? finite(landscape.invalidation) : null,
    currentPrice: finite(landscape.currentPrice ?? quote?.price),
    reasons: (value.reasons?.supporting || []).slice(0, 5),
    dataQuality: finite(value.debug?.dataQuality?.score),
  };
}

function decide(ticker, quote, market) {
  const decision = engine().decide({
    ticker,
    price: finite(quote.price),
    technicalFeatures: features().buildTechnicalFeatures(inputs().featureInputs(quote, market)),
    marketContext: market,
    classification: profiles().profileFor(ticker, quote.metadata || quote),
    metadata: quote.metadata || {},
    language: "en",
    underlyingTechnicalFeatures: null,
    underlyingPrice: null,
  });
  return {
    contractVersion: CONTRACT_VERSION,
    producer: PRODUCER,
    ticker,
    generatedAt: new Date().toISOString(),
    currentPrice: finite(quote.price),
    horizons: Object.fromEntries(HORIZONS.map((horizon) => [horizon, horizonPayload(decision, horizon, quote)])),
  };
}

async function decisionsFor(symbols) {
  const market = await marketContext();
  const decisions = {};
  const errors = {};
  await Promise.all(
    symbols.map(async (symbol) => {
      try {
        decisions[symbol] = decide(symbol, await quoteFor(symbol), market);
      } catch (error) {
        // One bad ticker must not fail the request. The caller sees which
        // failed and why, instead of an opaque 500.
        errors[symbol] = String(error?.message || error).slice(0, 300);
      }
    }),
  );
  return { decisions, errors };
}

const normalize = (value) => String(value || "").trim().toUpperCase();

// The consumer's horizon vocabulary is not this engine's. finance-monorepo's
// Horizon enum is 1D / 1W / 2-4W / 3-6M; this engine's is short / mid / long.
// Map both so neither side has to translate.
const HORIZON_ALIASES = {
  short: "short", mid: "mid", medium: "mid", long: "long",
  "1d": "short", "1w": "short", "2-4w": "mid", "3-6m": "long",
};

export default {
  async fetch(request) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";

    if (request.method === "OPTIONS") return json({}, 204);
    if (request.method !== "GET") return json({ success: false, error: "GET only" }, 405);

    if (path === "/" || path === "/health") {
      return json({
        success: true,
        status: "ok",
        service: "decision-v1-worker",
        contractVersion: CONTRACT_VERSION,
        producer: PRODUCER,
        horizons: { mid: "supported", long: "supported", short: "unavailable: needs native 4h bars" },
      });
    }

    if (path === "/api/decisions") {
      const symbols = [...new Set((url.searchParams.get("tickers") || "").split(",").map(normalize).filter(Boolean))];
      if (!symbols.length) return json({ success: false, error: "tickers is required" }, 400);
      if (symbols.length > MAX_TICKERS) return json({ success: false, error: `at most ${MAX_TICKERS} tickers` }, 400);
      return json(await decisionsFor(symbols));
    }

    const match = path.match(/^\/api\/decision\/(.+)$/);
    if (match) {
      const symbol = normalize(decodeURIComponent(match[1]));
      if (!symbol) return json({ success: false, error: "ticker is required" }, 400);
      const { decisions, errors } = await decisionsFor([symbol]);
      const decision = decisions[symbol];
      if (!decision) return json({ success: false, error: errors[symbol] || `no decision for ${symbol}` }, 502);

      // `?horizon=` returns ONE flattened horizon: a single decision.v1 object
      // with the envelope fields folded in. That is the shape a decision.v1
      // consumer validates, and short/mid/long stay independent because the
      // consumer asks for each one separately. Without the parameter the full
      // three-horizon envelope is returned instead.
      const requested = String(url.searchParams.get("horizon") || "").trim().toLowerCase();
      if (requested) {
        const horizon = HORIZON_ALIASES[requested];
        if (!horizon) {
          return json({ success: false, error: `unknown horizon: ${requested}` }, 400);
        }
        return json({
          contractVersion: decision.contractVersion,
          producer: decision.producer,
          ticker: decision.ticker,
          horizon,
          generatedAt: decision.generatedAt,
          ...decision.horizons[horizon],
        });
      }
      return json(decision);
    }

    return json({ success: false, error: `not found: ${path}` }, 404);
  },
};
