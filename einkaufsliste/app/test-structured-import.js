const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-structured-import-"));
process.env.DATA_DIR = dir;
process.env.DATA_FILE = path.join(dir, "shopping-list.json");
process.env.BACKUP_DIR = path.join(dir, "backups");
const app = require("./server");

test.after(async () => {
  if (app.server.listening) await new Promise((resolve) => app.server.close(resolve));
  fs.rmSync(dir, { recursive: true, force: true });
});

async function request(base, pathname, method = "GET", body) {
  const response = await fetch(base + pathname, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return { status: response.status, body: await response.json() };
}

test("structured imports fail closed for a missing category instead of silently classifying and generating", async () => {
  await new Promise((resolve) => app.server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${app.server.address().port}`;
  const before = await request(base, "/api/state");
  const openBefore = before.body.entries.length;
  const response = await request(base, "/api/integration/import", "POST", {
    items: [{ name: "Butter", categoryName: "Firma", quantity: 10, unit: "Stück" }],
  });
  assert.equal(response.status, 200);
  assert.equal(response.body.results[0].status, "error");
  assert.match(response.body.results[0].error, /Kategorie.*Firma.*existiert/i);
  const after = await request(base, "/api/state");
  assert.equal(after.body.entries.length, openBefore);
});

test("structured Firma alias resolves Firma (extra Rechnung), preserves quantity and clones an existing master", async () => {
  const base = `http://127.0.0.1:${app.server.address().port}`;
  const categoryResponse = await request(base, "/api/categories", "POST", { name: "Firma (extra Rechnung)" });
  assert.equal(categoryResponse.status, 201);
  const firma = categoryResponse.body.category;
  const before = await request(base, "/api/state");
  const butter = before.body.products.find((product) => product.name === "Butter" && !product.sourceTag);
  assert.ok(butter);

  const response = await request(base, "/api/integration/import", "POST", {
    items: [{ name: "Butter", categoryName: "Firma", quantity: 10, unit: "Stück" }],
  });
  assert.equal(response.status, 200);
  assert.equal(response.body.results[0].status, "added");
  assert.equal(response.body.results[0].entry.productName, "Butter");
  assert.equal(response.body.results[0].entry.categoryId, firma.id);
  assert.deepEqual(response.body.results[0].entry.quantity, { value: 10, unit: "Stück", userEdited: true });
  assert.notEqual(response.body.results[0].entry.productId, butter.id);

  const after = await request(base, "/api/state");
  const variant = after.body.products.find((product) => product.id === response.body.results[0].entry.productId);
  assert.equal(variant.name, "Butter");
  assert.match(String(variant.sourceTag || ""), /^category:/);
  assert.notEqual(variant.imageSource, "pending");
});
