"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const root = path.join(__dirname, "..");
const main = fs.readFileSync(path.join(root, "main.js"), "utf8");
const html = fs.readFileSync(path.join(root, "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "styles.css"), "utf8");
const marketEngine = fs.readFileSync(path.join(root, "decision-engine", "market-engine.js"), "utf8");
const executionEngine = fs.readFileSync(path.join(root, "decision-engine", "execution-engine.js"), "utf8");
const technicalEngine = fs.readFileSync(path.join(root, "decision-engine", "technical-engine.js"), "utf8");
const presentation = require(path.join(root, "decision-presentation.js"));

assert.match(main, /function buildRelativeStrength\(/);
assert.match(main, /function actionChip\(/);
assert.match(main, /A dashboard refresh intentionally rebuilds canonical technical features/);
assert.match(main, /window\.DecisionEngine\?\.decide/);
assert.doesNotMatch(main, /previousLandscape|previousCluster|clusterSwitching/);
assert.match(main, /state\.refreshPhase = "refreshing_data"/);
assert.match(main, /state\.refreshPromise/);
assert.match(main, /refreshGeneration/);
assert.match(main, /afterBrowserPaint\(\)/);
assert.match(main, /async function runFullRefresh\(\{ source = "initial" \} = \{\}\)/);
assert.match(main, /function refreshUsesLiveData\(source\)/);
assert.match(main, /source === "manual" \|\| source === "auto"/);
assert.match(main, /if \(refreshUsesLiveData\(source\)\) \{[\s\S]*?params\.set\("force", "true"\);[\s\S]*?params\.set\("full_refresh", "true"\);/);
assert.match(main, /full_refresh/, "Manual and Auto must request the server-side all-ticker refresh transaction");
assert.match(main, /runFullRefresh\(\{ source: "manual" \}\)/);
assert.match(main, /setInterval\(\(\) => runFullRefresh\(\{ source: "auto" \}\), REFRESH_MS\)/);
assert.doesNotMatch(main, /async function refreshMarket/);
assert.match(main, /if \(state\.refreshPromise\) return state\.refreshPromise/);
assert.match(main, /const refreshTime = snapshotRefreshTime\(snapshot\)/);
assert.match(main, /LAST_REFRESH_CACHE_KEY/);
assert.match(main, /persistLastRefresh\(refreshTime\)/);
assert.match(main, /t\("refreshing"\)/);
assert.match(main, /lastRefreshLabel/);
assert.match(html, /id="lastRefreshLabel"/);
assert.match(main, /timeZone: "America\/New_York"/);
assert.match(main, /hourCycle: "h23"/);
assert.match(main, /\$\{parts\.year\}-\$\{parts\.month\}-\$\{parts\.day\} \$\{parts\.hour\}:\$\{parts\.minute\} ET/);
assert.doesNotMatch(main, /refreshHistory|snapshotHistory|refreshRuns\.push/);

function easternRefreshTimeForTest(value) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", {
    timeZone: "America/New_York",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).formatToParts(new Date(value)).filter((part) => part.type !== "literal").map((part) => [part.type, part.value]));
  return `${parts.year}-${parts.month}-${parts.day} ${parts.hour}:${parts.minute} ET`;
}

assert.equal(easternRefreshTimeForTest("2026-08-17T21:15:00Z"), "2026-08-17 17:15 ET", "EDT uses America/New_York rather than a fixed EST offset");
assert.equal(easternRefreshTimeForTest("2026-01-17T22:15:00Z"), "2026-01-17 17:15 ET", "EST uses America/New_York rather than browser-local time");

const refreshStart = main.indexOf("async function runFullRefresh");
const snapshotApply = main.indexOf("applySnapshot(snapshot, { renderSnapshot: false })", refreshStart);
const paintWait = main.indexOf("await afterBrowserPaint();", snapshotApply);
const lastRefreshCommit = main.indexOf("state.lastRefreshAt = refreshTime", paintWait);
const refreshFailure = main.indexOf("} catch (error)", lastRefreshCommit);
assert.ok(snapshotApply > refreshStart && paintWait > snapshotApply && lastRefreshCommit > paintWait, "Last Refresh commits only after snapshot application and browser paint");
assert.ok(refreshFailure > lastRefreshCommit, "A failed refresh cannot commit a new Last Refresh timestamp");
assert.match(executionEngine, /NEAR_OPPORTUNITY_ZONE", "NEUTRAL_ZONE", "NEAR_REDUCE_ZONE"/);
assert.match(executionEngine, /state === "IN_OPPORTUNITY_ZONE"/);
assert.match(executionEngine, /\["IN_REDUCE_ZONE", "BEYOND_REDUCE_ZONE"\]/);
for (const action of ["strong_buy", "buy", "accumulate", "hold", "trim", "sell", "avoid"]) assert.ok(presentation.actionTone[action], `Homepage action tone missing: ${action}`);
assert.match(main, /decision\.actionLabel/);
assert.match(main, /row\.ready && decision \? decision\.actionLabel : t\("unavailable"\)/);
assert.match(main, /stock_vs_spy_\$\{lookback\}d/);
assert.match(main, /stock_vs_qqq_\$\{lookback\}d/);
assert.match(main, /EMA 9|item\.indicator/);
assert.match(main, /change_5d/);
assert.match(main, /change_20d/);
assert.match(main, /renderFibonacciStructure/);
assert.match(main, /Fibonacci Structure/);
assert.match(main, /Volume \/ RVOL \/ OBV/);
for (const renderedTechnicalField of [
  "Histogram 1-bar",
  "Histogram 3-bar",
  "Histogram 5-bar",
  "Zero line",
  "ADX / DI",
  "ATR percentile",
  "Bandwidth percentile",
  "K / D / J slope",
  "Relative Strength",
  "vs QQQ · 20 / 60 / 120D",
  "Horizon OBV · 4H / 1D / 1W",
]) assert.match(main, new RegExp(renderedTechnicalField.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Technical render field is missing: ${renderedTechnicalField}`);
assert.match(main, /fibonacciLevelTable/);
assert.match(main, /fib\.retracement_levels/);
assert.match(main, /fib\.extension_levels/);
assert.match(main, /sourceTimeframe/);
assert.match(main, /lookbackBars/);
assert.match(main, /fallbackUsed/);
assert.match(main, /technical-accordion/);
assert.match(main, /data-technical-horizon/);
assert.match(main, /data-fibonacci-horizon/);
assert.match(main, /data-technical-toggle/);
for (const presentationClass of ["stock-item-body", "decision-hero", "decision-core-grid", "detail-section-card", "decision-price-map", "company-model-grid"]) {
  assert.match(main, new RegExp(presentationClass), `restored presentation structure is missing: ${presentationClass}`);
}
assert.match(marketEngine, /source\.market_context/);
assert.doesNotMatch(marketEngine, /directionAdjustment/);
assert.match(executionEngine, /Stateless by contract/);
assert.doesNotMatch(executionEngine, /previousLandscape|previousCluster|clusterSwitchingMargin|_landscapeCache/);
assert.match(technicalEngine, /unified_category_confluence/);
assert.match(technicalEngine, /categoryContributionCap/);
assert.equal(html.includes("Action Score"), false);
assert.match(main, /executionIntent/);
assert.match(main, /priceLandscape/);
assert.match(main, /recommendedBuyAddRange/);
assert.match(main, /potentialReduceRange/);
assert.match(main, /execution-avoid-note/);
assert.doesNotMatch(main, /noExecutionPlan/);
assert.match(main, /recommendationConfidence/);
assert.match(main, /decisionHorizon/);
assert.match(main, /data-decision-horizon/);
assert.match(main, /renderDecisionPriceMap/);
assert.match(main, /renderCompanyModel/);
assert.match(main, /window\.__decisionDebug/);
assert.match(main, /decisionCardHint/);
assert.doesNotMatch(main, /Action Score|baseline score|final score|Top 3/);
assert.doesNotMatch(main, /decision\.confidence}%/);
assert.match(html, /profile-definitions\.js/);
assert.match(html, /etf-profile\.js/);
assert.match(html, /decision-presentation\.js/);
assert.match(html, /price-landscape-v1/);
for (const token of ["--action-strong-buy", "--action-buy", "--action-accumulate", "--action-hold", "--action-trim", "--action-sell", "--action-avoid", "--space-xs", "--radius-lg"]) assert.match(css, new RegExp(token), `UI token is missing: ${token}`);
assert.match(css, /price-map-label\.top\.lane-1/);
assert.match(css, /price-map-label\.bottom\.lane-2/);
assert.match(css, /decision-core-card\.is-active/);
assert.match(css, /technical-family-grid/);
assert.match(css, /fibonacci-level-table/);
assert.match(css, /market-compact-grid/);
assert.doesNotMatch(presentation.priceMapModel.toString(), /fetch\(/, "presentation does not add API requests");

console.log("dashboard-regression.test.js: dashboard data and score-removal assertions passed");
