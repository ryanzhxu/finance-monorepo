"use strict";

const assert = require("node:assert/strict");
const presentation = require("../decision-presentation.js");

const range = (low, high) => ({ low, high });
const plan = (action, overrides = {}) => ({
  action,
  executionIntent: presentation.actionIntent[action],
  priceLandscape: { opportunityRange: range(100, 105), reduceRange: range(115, 120), invalidation: 96, currentPrice: 110 },
  ...overrides,
});

assert.equal(presentation.executionSemantics(plan("buy")).opportunity, "recommendedBuyAddRange");
assert.equal(presentation.executionSemantics(plan("accumulate")).opportunity, "recommendedBuyAddRange");
assert.equal(presentation.executionSemantics(plan("hold")).opportunity, "potentialAddRange");
assert.equal(presentation.executionSemantics(plan("trim")).reduce, "recommendedReduceRange");
assert.equal(presentation.executionSemantics(plan("sell")).reduce, "recommendedExitRange");
assert.equal(presentation.executionSemantics(plan("avoid")).reduce, null);
assert.deepEqual(presentation.actionTone, {
  strong_buy: "strong-buy", buy: "buy", accumulate: "accumulate", hold: "hold", trim: "trim", sell: "sell", avoid: "avoid",
});

for (const [name, currentPrice, decision] of [
  ["opportunity below current", 110, plan("buy")],
  ["current inside opportunity", 103, plan("buy", { priceLandscape: { opportunityRange: range(100, 105), reduceRange: range(115, 120), invalidation: 96, currentPrice: 103 } })],
  ["opportunity above current", 95, plan("buy", { priceLandscape: { opportunityRange: range(100, 105), reduceRange: range(115, 120), invalidation: 96, currentPrice: 95 } })],
  ["bearish ordering", 100, plan("sell", { priceLandscape: { opportunityRange: range(82, 86), reduceRange: range(99, 102), invalidation: 106, currentPrice: 100 } })],
  ["hold landscape", 110, plan("hold")],
  ["avoid with no exit", 100, plan("avoid", { priceLandscape: { opportunityRange: range(85, 89), reduceRange: null, invalidation: null, currentPrice: 100 } })],
]) {
  const model = presentation.priceMapModel({ currentPrice, decision });
  assert.ok(model.points.some((point) => point.id === "current"), `${name}: current price is missing`);
  assert.ok(model.min < model.max, `${name}: usable scale is missing`);
  model.points.forEach((point) => {
    const values = point.value == null ? [point.start, point.end] : [point.position];
    values.forEach((value) => assert.ok(value >= 0 && value <= 100, `${name}: map point escaped scale`));
  });
}

const closeLabels = presentation.layoutPriceMap([
  { id: "opportunity", start: 48, end: 52 },
  { id: "current", position: 53 },
  { id: "reduce", start: 53.5, end: 55 },
  { id: "invalidation", position: 55.5 },
], 9).labels;
for (let index = 0; index < closeLabels.length; index += 1) {
  for (let compared = index + 1; compared < closeLabels.length; compared += 1) {
    const left = closeLabels[index]; const right = closeLabels[compared];
    if (Math.abs(left.anchor - right.anchor) < 9) assert.notEqual(`${left.labelSide}-${left.labelLane}`, `${right.labelSide}-${right.labelLane}`, "close Price Landscape labels require separate lanes");
  }
}
assert.ok(presentation.layoutPriceMap(closeLabels).trackHeight >= 140, "dense Price Landscape gains vertical label room");

const nearbyCurrent = presentation.layoutPriceMap([
  { id: "invalidation", position: 10 },
  { id: "opportunity", start: 32, end: 38 },
  { id: "current", position: 39 },
  { id: "reduce", start: 78, end: 84 },
]).labels;
const nearbyOpportunity = nearbyCurrent.find((point) => point.id === "opportunity");
const nearbyPrice = nearbyCurrent.find((point) => point.id === "current");
assert.notEqual(nearbyOpportunity.labelSide, nearbyPrice.labelSide, "a current price beside an opportunity range moves to the opposite label side");
assert.equal(presentation.layoutPriceMap(nearbyCurrent).trackHeight, 140, "ordinary near-price maps stay compact after side staggering");

const distance = presentation.nearestRangeDistance(110, range(100, 105));
assert.equal(distance.within, false);
assert.equal(Math.round(distance.percent * 10) / 10, -4.5);
assert.equal(presentation.nearestRangeDistance(103, range(100, 105)).percent, 0);

const profile = presentation.profileGroups({ primaryClassification: "AI Infrastructure", companyTraits: ["MegaCap", "AIInfrastructure", "MegaCap"], lifecycle: null });
assert.deepEqual(profile.traits, ["MegaCap", "AIInfrastructure"]);
assert.equal(profile.visible.lifecycle, false);
assert.equal(presentation.profileGroups({ isETF: true }).type, "etf");

const stablePresentationDecision = plan("buy");
const beforePresentation = structuredClone(stablePresentationDecision);
presentation.executionSemantics(stablePresentationDecision);
presentation.priceMapModel({ currentPrice: 103, decision: stablePresentationDecision });
presentation.profileGroups({ primaryClassification: "AI Infrastructure", companyTraits: ["MegaCap", "AIInfrastructure"] });
assert.deepEqual(stablePresentationDecision, beforePresentation, "presentation helpers must not mutate V1 decision values");

assert.equal(presentation.translateReason("OBV and volume participation are confirming accumulation.", "zh"), "OBV 与成交量参与度正在确认资金吸筹。");
assert.equal(presentation.translateReason("Price is near the opportunity range but has not entered the recommended buy/add zone.", "zh"), "当前价格接近机会区，但尚未进入推荐买入/加仓区。");
assert.equal(presentation.translateReason("Price is approaching the reduce range but has not entered the recommended reduce/exit zone.", "zh"), "当前价格接近减仓区，但尚未进入推荐减仓/退出区域。");
assert.equal(presentation.translateReason("Price position alone cannot create a Sell without bearish structural evidence.", "zh"), "仅凭价格位置、缺乏空头结构证据时，不能形成卖出建议。");
assert.equal(presentation.translateReason("Price has entered the reduce range without enough trend confirmation to justify holding full exposure.", "zh"), "价格已进入减仓区，但趋势确认不足以支持维持完整暴露。");
assert.equal(presentation.translateReason("Unmapped provider wording.", "zh"), "Unmapped provider wording.");
assert.equal(presentation.reasonList(["a", "b", "c", "d", "e", "f"], "en", 5).length, 5);
assert.match(presentation.positionGuidance("hold", "en"), /not enough evidence/i);
assert.match(presentation.positionGuidance("avoid", "zh"), /不适合/);

console.log("decision-ui.test.js: Price Landscape, execution semantics, profile presentation, and bilingual fallback assertions passed");
