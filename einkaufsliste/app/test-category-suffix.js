const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const dir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-category-suffix-"));
process.env.DATA_DIR = dir;
process.env.DATA_FILE = path.join(dir, "shopping-list.json");
process.env.BACKUP_DIR = path.join(dir, "backups");

const app = require("./server");

test.after(async () => {
  if (app.server.listening) await new Promise((resolve) => app.server.close(resolve));
  fs.rmSync(dir, { recursive: true, force: true });
});

async function request(base, pathname, method = "GET", body, allowError = false) {
  const response = await fetch(base + pathname, {
    method,
    headers: body === undefined ? undefined : { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json();
  if (!allowError && !response.ok) throw new Error(`${response.status}: ${payload.error || JSON.stringify(payload)}`);
  return { status: response.status, body: payload };
}

test("special targets clone existing master products, preserve quantity and never create quantity/category names", async () => {
  await new Promise((resolve) => app.server.listen(0, "127.0.0.1", resolve));
  const base = `http://127.0.0.1:${app.server.address().port}`;

  const firma = (await request(base, "/api/categories", "POST", { name: "Firma (extra Rechnung)" })).body.category;
  const retailer = (await request(base, "/api/categories", "POST", { name: "DM/Rossmann/Müller" })).body.category;

  const before = (await request(base, "/api/state")).body;
  const masterButter = before.products.find((product) => product.name === "Butter" && !product.sourceTag);
  const masterBanana = before.products.find((product) => product.name === "Banane" && !product.sourceTag);
  assert.ok(masterButter);
  assert.ok(masterBanana);

  const companyBanana = (await request(base, "/api/items", "POST", { input: "Bananen 15x Firma" })).body;
  assert.equal(companyBanana.entry.productName, "Banane");
  assert.notEqual(companyBanana.entry.productId, masterBanana.id);
  assert.deepEqual(companyBanana.entry.quantity, { value: 15, unit: "stück" });
  assert.equal(companyBanana.entry.categoryId, firma.id);
  assert.equal(companyBanana.createdProduct, true);
  assert.equal(companyBanana.clonedProduct, true);

  const companyButter = (await request(base, "/api/items", "POST", { input: "Butter 10x Firma" })).body;
  assert.equal(companyButter.entry.productName, "Butter");
  assert.notEqual(companyButter.entry.productId, masterButter.id);
  assert.deepEqual(companyButter.entry.quantity, { value: 10, unit: "stück" });
  assert.equal(companyButter.entry.categoryId, firma.id);
  assert.equal(companyButter.clonedProduct, true);

  const stateAfterVariants = (await request(base, "/api/state")).body;
  const butterProducts = stateAfterVariants.products.filter((product) => product.name === "Butter");
  assert.equal(butterProducts.length, 2, "Butter muss normal und als Firma-Variante existieren");
  const normalButter = butterProducts.find((product) => product.id === masterButter.id);
  const firmaButter = butterProducts.find((product) => product.id === companyButter.entry.productId);
  assert.equal(normalButter.categoryId, "milk");
  assert.equal(firmaButter.categoryId, firma.id);
  assert.match(String(firmaButter.sourceTag), /^category:/);
  assert.notEqual(firmaButter.imageSource, "pending", "Klon darf keinen neuen Bildjob starten");
  assert.equal(firmaButter.imageGenerationVersion, undefined);

  const malformedNames = stateAfterVariants.products.filter((product) => /(?:\d+\s*x|firma)/i.test(product.name) && [companyButter.entry.productId, companyBanana.entry.productId].includes(product.id));
  assert.equal(malformedNames.length, 0, "Menge/Firma dürfen nie im Stammartikelnamen bleiben");

  const duplicateFirma = await request(base, "/api/integration/import", "POST", {
    items: [{ name: "Butter", categoryName: "Firma", quantity: 3, unit: "Stück" }],
  });
  assert.equal(duplicateFirma.body.results[0].status, "duplicate");
  assert.equal(duplicateFirma.body.results[0].entry.productId, firmaButter.id);

  const ordinaryButter = (await request(base, "/api/items", "POST", { input: "Butter vier mal" })).body;
  assert.equal(ordinaryButter.entry.productId, masterButter.id);
  assert.deepEqual(ordinaryButter.entry.quantity, { value: 4, unit: "stück" });
  assert.equal(ordinaryButter.entry.categoryId, "milk");

  const dm = (await request(base, "/api/items", "POST", { input: "Butter 2x DM" })).body;
  assert.equal(dm.entry.productName, "Butter (DM)");
  assert.deepEqual(dm.entry.quantity, { value: 2, unit: "stück" });
  assert.equal(dm.entry.categoryId, retailer.id);
  assert.equal(dm.clonedProduct, true);
  const dmProduct = (await request(base, "/api/state")).body.products.find((product) => product.id === dm.entry.productId);
  assert.equal(dmProduct.sourceTag, "retailer:dm");
  assert.notEqual(dmProduct.imageSource, "pending");

  const rewe = (await request(base, "/api/items", "POST", { input: "Butter 5x REWE" })).body;
  assert.equal(rewe.entry.productName, "Butter");
  assert.deepEqual(rewe.entry.quantity, { value: 5, unit: "stück" });
  assert.equal(rewe.clonedProduct, true);
  const reweProduct = (await request(base, "/api/state")).body.products.find((product) => product.id === rewe.entry.productId);
  assert.equal(reweProduct.sourceTag, "rewe");
  assert.notEqual(reweProduct.imageSource, "pending");
});

test("duplicates are based on the article within the same target, ignoring quantity, note and detail", async () => {
  const base = `http://127.0.0.1:${app.server.address().port}`;
  const firstChicken = await request(base, "/api/items", "POST", { input: "Hähnchen", productDetail: "Geschnetzeltes", note: "Test" });
  assert.equal(firstChicken.status, 201);
  const secondChicken = await request(base, "/api/items", "POST", { input: "Hähnchen" }, true);
  assert.equal(secondChicken.status, 409);
  assert.equal(secondChicken.body.duplicate, true);
  assert.equal(secondChicken.body.entry.productId, firstChicken.body.entry.productId);

  const firstBroccoli = await request(base, "/api/integration/import", "POST", { items: [{ name: "Brokkoli" }] });
  assert.equal(firstBroccoli.body.results[0].status, "added");
  const secondBroccoli = await request(base, "/api/integration/import", "POST", { items: [{ name: "Brokkoli", quantity: 10, unit: "Stück", note: "anders" }] });
  assert.equal(secondBroccoli.body.results[0].status, "duplicate");
  assert.equal(secondBroccoli.body.results[0].entry.productId, firstBroccoli.body.results[0].entry.productId);
});
