const test = require("node:test");
const assert = require("node:assert/strict");
const { alexaItemName, alexaRawNameFields, capitalizeFirst, normalizeItem, processedItemName, planTransfers } = require("./sync-logic");

test("capitalizes the first letter for Alexa to Bring transfers", () => {
  assert.equal(capitalizeFirst("milch"), "Milch");
  assert.equal(capitalizeFirst("äpfel"), "Äpfel");
});

test("normalizes case, unicode and whitespace for duplicate detection", () => {
  assert.equal(normalizeItem("  Äpfel   "), "äpfel");
  assert.equal(normalizeItem("ÄPFEL"), "äpfel");
});

test("plans new Alexa items and skips active todo duplicates", () => {
  const result = planTransfers(
    [{ id: "1", value: "Milch", completed: false }, { id: "2", value: "Äpfel", completed: false }, { id: "3", value: "Brot", completed: true }],
    [{ summary: "  milch ", status: "needs_action" }],
  );
  assert.deepEqual(result.transfers.map((x) => x.name), ["Äpfel"]);
  assert.equal(result.skipped.length, 1);
});

test("does not treat completed todo entries as active duplicates", () => {
  const result = planTransfers([{ id: "1", value: "Milch", completed: false }], [{ summary: "Milch", status: "completed" }]);
  assert.equal(result.transfers.length, 1);
});


test("push display name prefers the processed shopping-list name over Alexa raw text", () => {
  assert.equal(processedItemName({ original: "alverde rasierer sensitiv dm", productName: "Alverde Rasiergel sensitiv (DM)" }), "Alverde Rasiergel sensitiv (DM)");
  assert.equal(processedItemName({ original: "butter 3x 4 mal", productName: "Butter" }), "Butter");
});


test("keeps the exact Alexa list-name fields for diagnostics", () => {
  const item = { itemName: "Butter 10x 4 mal", value: undefined, name: null };
  assert.equal(alexaItemName(item), "Butter 10x 4 mal");
  assert.deepEqual(alexaRawNameFields(item), { itemName: "Butter 10x 4 mal" });
});

test("prefers V2 itemName over compatibility value", () => {
  assert.equal(alexaItemName({ itemName: "Butter 10x", value: "Butter 4 Stück" }), "Butter 10x");
});

test("parses compact Alexa quantities", () => {
  const { parseQuantityName } = require("./sync-logic");
  assert.deepEqual(parseQuantityName("Butter 10x"), { baseName: "Butter", quantity: 10, unit: "Stück", raw: "Butter 10x" });
  assert.deepEqual(parseQuantityName("Milch 3 Stück"), { baseName: "Milch", quantity: 3, unit: "Stück", raw: "Milch 3 Stück" });
});

test("reconstructs Firma from a direct quantity plus four-times suffix", () => {
  const { directFirmaInterpretation } = require("./sync-logic");
  assert.deepEqual(directFirmaInterpretation("Butter 10x 4 mal"), {
    name: "Butter Firma", categoryName: "Firma", quantity: 10, unit: "Stück", baseName: "Butter", reason: "direkter Firma-Fehlhörer",
  });
});

test("recognizes the actual Firma suffix before import", () => {
  const { directFirmaInterpretation, importPayloadForCandidate } = require("./sync-logic");
  const interpretation = directFirmaInterpretation("Butter 10x Firma");
  assert.deepEqual(interpretation, {
    name: "Butter Firma", categoryName: "Firma", quantity: 10, unit: "Stück", baseName: "Butter", reason: "direktes Firma-Suffix",
  });
  assert.deepEqual(importPayloadForCandidate({ interpretation }), {
    name: "Butter", categoryName: "Firma", quantity: 10, unit: "Stück",
  });
});

test("reconstructs Firma from the same Alexa item changing from 10x to 4 Stück", () => {
  const { firmaInterpretationFromHistory } = require("./sync-logic");
  const result = firmaInterpretationFromHistory([{ name: "Butter 10x", at: 1000 }], "Butter 4 Stück");
  assert.equal(result.name, "Butter Firma");
  assert.equal(result.quantity, 10);
  assert.equal(result.unit, "Stück");
});

test("does not infer Firma from a standalone 4 Stück item without history", () => {
  const { firmaInterpretationFromHistory } = require("./sync-logic");
  assert.equal(firmaInterpretationFromHistory([], "Butter 4 Stück"), null);
});

test("waits for three stable polls and keeps transition history before import", () => {
  const { updateAlexaCandidates, importPayloadForCandidate } = require("./sync-logic");
  const memory = new Map();
  let state = updateAlexaCandidates(memory, [{ itemId: "abc", itemName: "Butter 10x", itemStatus: "ACTIVE" }], 0, { minStableMs: 10000, minStablePolls: 3 });
  assert.equal(state.ready.length, 0);
  state = updateAlexaCandidates(memory, [{ itemId: "abc", itemName: "Butter 10x", itemStatus: "ACTIVE" }], 5000, { minStableMs: 10000, minStablePolls: 3 });
  assert.equal(state.ready.length, 0);
  state = updateAlexaCandidates(memory, [{ itemId: "abc", itemName: "Butter 4 Stück", itemStatus: "ACTIVE" }], 10000, { minStableMs: 10000, minStablePolls: 3 });
  assert.equal(state.ready.length, 0);
  assert.equal(state.waiting[0].interpretation.quantity, 10);
  state = updateAlexaCandidates(memory, [{ itemId: "abc", itemName: "Butter 4 Stück", itemStatus: "ACTIVE" }], 15000, { minStableMs: 10000, minStablePolls: 3 });
  assert.equal(state.ready.length, 0);
  state = updateAlexaCandidates(memory, [{ itemId: "abc", itemName: "Butter 4 Stück", itemStatus: "ACTIVE" }], 20000, { minStableMs: 10000, minStablePolls: 3 });
  assert.equal(state.ready.length, 1);
  assert.deepEqual(importPayloadForCandidate(state.ready[0]), { name: "Butter", categoryName: "Firma", quantity: 10, unit: "Stück" });
});

test("parses all explicit special targets before import and preserves quantities", () => {
  const { directSpecialTargetInterpretation, importPayloadForCandidate } = require("./sync-logic");
  const cases = [
    ["Bananen 15x Firma", { name: "Bananen", categoryName: "Firma", quantity: 15, unit: "Stück" }],
    ["Butter 5x REWE", { name: "Butter", categoryName: "REWE", quantity: 5, unit: "Stück" }],
    ["Shampoo 2x DM", { name: "Shampoo", categoryName: "DM", quantity: 2, unit: "Stück" }],
    ["Deo 3 Stück Rossmann", { name: "Deo", categoryName: "Rossmann", quantity: 3, unit: "Stück" }],
    ["Seife 4x Müller", { name: "Seife", categoryName: "Müller", quantity: 4, unit: "Stück" }],
  ];
  for (const [raw, expected] of cases) {
    const interpretation = directSpecialTargetInterpretation(raw);
    assert.ok(interpretation, raw);
    assert.deepEqual(importPayloadForCandidate({ interpretation }), expected, raw);
  }
});

test("normal quantities are structured before shopping-list import", () => {
  const { importPayloadForCandidate } = require("./sync-logic");
  assert.deepEqual(importPayloadForCandidate({ rawName: "Gurke 10x" }), {
    name: "Gurke", quantity: 10, unit: "Stück",
  });
});

test("Firma without a quantity still becomes a structured special target", () => {
  const { directSpecialTargetInterpretation, importPayloadForCandidate } = require("./sync-logic");
  const interpretation = directSpecialTargetInterpretation("Gurke Firma");
  assert.equal(interpretation.baseName, "Gurke");
  assert.equal(interpretation.categoryName, "Firma");
  assert.deepEqual(importPayloadForCandidate({ interpretation }), {
    name: "Gurke", categoryName: "Firma", quantity: null, unit: null,
  });
});
