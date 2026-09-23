const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const { execFileSync } = require("node:child_process");
const { parseItemInput, quantitySignature, duplicateKey } = require("./core");

const testDataDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-tests-"));
process.env.DATA_DIR = testDataDir;
process.env.DATA_FILE = path.join(testDataDir, "shopping-list.json");
process.env.BACKUP_DIR = path.join(testDataDir, "backups");
test.after(() => fs.rmSync(testDataDir, { recursive: true, force: true }));

test("parses German quantities and keeps product name separate", () => {
  assert.deepEqual(parseItemInput("500 g Mehl"), { original: "500 g Mehl", name: "Mehl", quantity: { value: 500, unit: "g" } });
  assert.deepEqual(parseItemInput("drei Gurken"), { original: "drei Gurken", name: "Gurken", quantity: { value: 3, unit: "stück" } });
  assert.deepEqual(parseItemInput("Wasser 3 Kisten"), { original: "Wasser 3 Kisten", name: "Wasser", quantity: { value: 3, unit: "kiste" } });
  assert.deepEqual(parseItemInput("Gurken drei"), { original: "Gurken drei", name: "Gurken", quantity: { value: 3, unit: "stück" } });
  assert.deepEqual(parseItemInput("zwei mal Hähnchenfleisch"), { original: "zwei mal Hähnchenfleisch", name: "Hähnchenfleisch", quantity: { value: 2, unit: "stück" } });
  assert.deepEqual(parseItemInput("ein Kilo Schnitten"), { original: "ein Kilo Schnitten", name: "Schnitten", quantity: { value: 1, unit: "kg" } });
  assert.deepEqual(parseItemInput("Stück Parmesan"), { original: "Stück Parmesan", name: "Parmesan", quantity: { value: 1, unit: "stück" } });
});

test("keeps refill packaging separate from the product name", () => {
  assert.deepEqual(parseItemInput("Pfefferkörner Nachfüllbeutel"), { original: "Pfefferkörner Nachfüllbeutel", name: "Pfefferkörner", quantity: { value: 1, unit: "nachfüllbeutel" } });
  assert.deepEqual(parseItemInput("2 Nachfüllbeutel Pfefferkörner"), { original: "2 Nachfüllbeutel Pfefferkörner", name: "Pfefferkörner", quantity: { value: 2, unit: "nachfüllbeutel" } });
  assert.deepEqual(parseItemInput("Pfefferkörner 2 Nachfüllbeutel"), { original: "Pfefferkörner 2 Nachfüllbeutel", name: "Pfefferkörner", quantity: { value: 2, unit: "nachfüllbeutel" } });
  assert.deepEqual(parseItemInput("Müllbeutel"), { original: "Müllbeutel", name: "Müllbeutel", quantity: null });
});

test("parses spoken decimal quantities without changing the spoken original", () => {
  assert.deepEqual(parseItemInput("Gemüse eins komma sechs fünf kilo"), {
    original: "Gemüse eins komma sechs fünf kilo",
    name: "Gemüse",
    quantity: { value: 1.65, unit: "kg" },
  });
  assert.deepEqual(parseItemInput("Gemüse eins komma sieben kg").quantity, { value: 1.7, unit: "kg" });
  assert.deepEqual(parseItemInput("1,7 kg Gemüse").quantity, { value: 1.7, unit: "kg" });
});

test("recognizes equivalent metric quantities as duplicates", () => {
  assert.equal(quantitySignature({ value: 0.5, unit: "kg" }), "500g");
  assert.equal(duplicateKey("mehl", { value: 500, unit: "g" }), duplicateKey("mehl", { value: 0.5, unit: "kg" }));
  assert.notEqual(duplicateKey("mehl", { value: 300, unit: "g" }), duplicateKey("mehl", { value: 600, unit: "g" }));
});

test("keeps all lists during migration", () => {
  const { initialState, migrateState } = require("./server");
  const original = initialState();
  original.lists.push({ ...structuredClone(original.lists[0]), id: "drogerie", name: "Einkaufsliste (Drogerie)", sort: 1, categoryMode: "empty", categories: [structuredClone(original.lists[0].categories.at(-1))], products: [{ id: "product-kabelbinder", key: "kabelbinder", name: "Kabelbinder", categoryId: "other", icon: "K", aliases: ["kabelbinder"], favorite: false, useCount: 0 }], entries: [], recent: [], undo: null });
  original.activeListId = "drogerie";
  const migrated = migrateState(original);
  assert.deepEqual(migrated.lists.map((list) => list.id), ["supermarkt", "drogerie"]);
  assert.equal(migrated.activeListId, "drogerie");
  assert.equal(migrated.lists[1].products.find((product) => product.key === "kabelbinder")?.name, "Kabelbinder");
});

test("recovers only unambiguous missing quantities and preserves entry fields", () => {
  const { initialState, migrateState } = require("./server");
  const original = structuredClone(initialState());
  const sourceEntry = {
    id: "entry-gemuese",
    productId: "product-gemuese",
    productKey: "gemuse eins komma",
    name: "Gemüse eins komma",
    original: "gemüse eins komma sechs fünf kilo",
    quantity: null,
    categoryId: "produce",
    createdAt: "2026-09-07T10:23:44.214Z",
    favoriteAtCreation: false,
  };
  const validEntry = {
    id: "entry-valid",
    productId: "product-gemuese",
    productKey: "gemuse eins komma",
    name: "Gemüse eins komma",
    original: "Gemüse eins komma sieben kilo",
    quantity: { value: 2, unit: "kg", userEdited: true },
    categoryId: "produce",
    createdAt: "2026-09-07T10:24:00.000Z",
  };
  original.lists[0].categories = [structuredClone(original.lists[0].categories[0])];
  original.lists[0].products = [{ id: "product-gemuese", key: "gemuse eins komma", name: "Gemüse eins komma", categoryId: "produce", icon: "🌿", aliases: ["gemuse eins komma"], classificationSource: "manual", favorite: true, useCount: 4 }];
  original.lists[0].entries = [sourceEntry, validEntry];
  original.lists[0].recent = [structuredClone(sourceEntry)];
  original.activeListId = original.lists[0].id;
  const migrated = migrateState(original);
  const entry = migrated.entries.find((item) => item.id === sourceEntry.id);
  assert.deepEqual(entry, { ...sourceEntry, quantity: null, productDetail: "1,65 kg" });
  assert.deepEqual(migrated.entries.find((item) => item.id === validEntry.id), validEntry);
  assert.deepEqual(migrated.recent.find((item) => item.id === sourceEntry.id), { ...sourceEntry, quantity: null, productDetail: "1,65 kg" });
  assert.equal(migrated.products[0].favorite, true);
  assert.equal(migrated.products[0].useCount, 4);
});

test("omitted quantity updates cannot turn into an invalid value", () => {
  const { quantityFromRequest } = require("./server");
  assert.deepEqual(quantityFromRequest("1,7", "kg"), { value: 1.7, unit: "kg" });
  assert.equal(quantityFromRequest(undefined, "kg"), undefined);
  assert.equal(quantityFromRequest("not-a-number", "kg"), undefined);
});

test("recovers the latest valid backup instead of resetting to one list", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-recovery-"));
  const dataFile = path.join(tempDir, "shopping-list.json");
  const backupDir = path.join(tempDir, "backups");
  fs.mkdirSync(backupDir);
  fs.writeFileSync(dataFile, "{ kaputt", "utf8");
  const backup = { ...require("./server").initialState(), lists: [
    { ...require("./server").initialState().lists[0], id: "supermarkt", name: "Einkaufsliste (Supermarkt)" },
    { ...require("./server").initialState().lists[0], id: "drogerie", name: "Einkaufsliste (Drogerie)", sort: 1, categoryMode: "empty", categories: [require("./server").initialState().lists[0].categories.at(-1)], products: [], entries: [], recent: [], undo: null },
  ] };
  fs.writeFileSync(path.join(backupDir, "einkaufsliste-2099-01-01.json"), JSON.stringify(backup), "utf8");
  const node = process.execPath;
  const script = "const state=require('./server').loadState(); process.stdout.write(JSON.stringify(state.lists.map(x=>x.id)))";
  const output = execFileSync(node, ["-e", script], { cwd: __dirname, env: { ...process.env, DATA_DIR: tempDir, DATA_FILE: dataFile, BACKUP_DIR: backupDir }, encoding: "utf8" });
  assert.deepEqual(JSON.parse(output.split("\n").at(-1)), ["supermarkt", "drogerie"]);
  fs.rmSync(tempDir, { recursive: true, force: true });
});

test("creates an exact pre-migration backup before loading an older data version", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-premigration-"));
  const dataFile = path.join(tempDir, "shopping-list.json");
  const backupDir = path.join(tempDir, "backups");
  const base = structuredClone(require("./server").initialState());
  base.version = "0.3.13";
  base.lists[0].products.push({ id: "product-eigen", key: "eigen", name: "Eigenes Produkt", categoryId: "other", icon: "E", aliases: ["eigen"], favorite: false, useCount: 0 });
  base.products = base.lists[0].products;
  const raw = JSON.stringify(base, null, 3);
  fs.writeFileSync(dataFile, raw, "utf8");
  execFileSync(process.execPath, ["-e", "require('./server')"], { cwd: __dirname, env: { ...process.env, DATA_DIR: tempDir, DATA_FILE: dataFile, BACKUP_DIR: backupDir }, encoding: "utf8" });
  const backups = fs.readdirSync(backupDir).filter((name) => /^pre-migration-0\.3\.13-to-0\.3\.68-.*\.json$/.test(name));
  assert.equal(backups.length, 1);
  assert.equal(fs.readFileSync(path.join(backupDir, backups[0]), "utf8"), raw);
  assert.equal(JSON.parse(fs.readFileSync(dataFile, "utf8")).version, "0.3.13");
  fs.rmSync(tempDir, { recursive: true, force: true });
});

test("does not migrate when the pre-migration backup cannot be written", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-premigration-fail-"));
  const dataFile = path.join(tempDir, "shopping-list.json");
  const backupDir = path.join(tempDir, "blocked-backups");
  const base = structuredClone(require("./server").initialState());
  base.version = "0.3.13";
  const raw = JSON.stringify(base);
  fs.writeFileSync(dataFile, raw, "utf8");
  fs.writeFileSync(backupDir, "not a directory", "utf8");
  let failed = false;
  try {
    execFileSync(process.execPath, ["-e", "require('./server')"], { cwd: __dirname, env: { ...process.env, DATA_DIR: tempDir, DATA_FILE: dataFile, BACKUP_DIR: backupDir }, encoding: "utf8", stdio: "pipe" });
  } catch (error) {
    failed = true;
    const stderr = String(error.stderr || "");
    assert.match(stderr, /Pre-Migration-Sicherung fehlgeschlagen; Datenmigration wurde abgebrochen/);
  }
  assert.equal(failed, true);
  assert.equal(fs.readFileSync(dataFile, "utf8"), raw);
  fs.rmSync(tempDir, { recursive: true, force: true });
});

test("creates an exact safety backup before restore operations", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-prerestore-"));
  const dataFile = path.join(tempDir, "shopping-list.json");
  const backupDir = path.join(tempDir, "backups");
  const base = structuredClone(require("./server").initialState());
  const raw = JSON.stringify(base, null, 4);
  fs.writeFileSync(dataFile, raw, "utf8");
  const script = "const s=require('./server'); process.stdout.write(s.createRestoreSafetyBackup())";
  const output = execFileSync(process.execPath, ["-e", script], { cwd: __dirname, env: { ...process.env, DATA_DIR: tempDir, DATA_FILE: dataFile, BACKUP_DIR: backupDir }, encoding: "utf8" });
  const target = output.trim().split("\n").at(-1);
  assert.match(path.basename(target), /^pre-restore-.*\.json$/);
  assert.equal(fs.readFileSync(target, "utf8"), raw);
  fs.rmSync(tempDir, { recursive: true, force: true });
});


test("maps the reviewed product icons independently of stale categories", () => {
  const { imageKeyForProduct } = require("./image-assets");
  const cases = [
    ["Banane", "produce", "banana"],
    ["Tomate", "produce", "tomato"],
    ["Gurke", "produce", "cucumber"],
    ["Ruccola", "produce", "rucola"],
    ["Kartoffel", "produce", "potato"],
    ["Gemüse eins komma sechs", "milk_uncooled", "produce"],
    ["Heidelbeeren", "produce", "blueberries"],
    ["Knusperbrot", "bakery_fitness", "knusperbrot"],
    ["Müsliriegel", "bakery_fitness", "muesli_bar_new"],
    ["Toastkäse", "bakery_fitness", "toast_cheese"],
    ["Schmand", "milk", "schmand_cup"],
    ["Saure Sahne", "milk", "soured_cream_cup"],
    ["Geriebener Käse", "cheese", "grated_cheese_bowl"],
    ["Gefrierbeutel", "household", "freezer_bags2"],
    ["Gefrorene Heidelbeere", "milk_uncooled", "frozen_berries2"],
    ["Flammkuchenboden", "ready_chilled", "flammkuchen_dough"],
    ["Rohen Schinken", "category-9e5324ea-b065-497e-998c-8dfe50939e97", "raw_ham"],
    ["Hähnchen", "meat", "chicken_fillets"],
    ["Eiswürfel", "ice_cream", "ice_cubes"],
    ["Bunte Nudeln (Meyerhof)", "pasta_rice", "colored_pasta"],
    ["Cola 4er", "oils_sauces", "cola_bottle"],
    ["Viererträger Cola Zero", "oils_sauces", "cola_bottle"],
    ["Feigen", "milk_uncooled", "figs"],
  ];
  for (const [name, categoryId, expected] of cases) assert.equal(imageKeyForProduct(name, categoryId), expected, `${name} -> ${expected}`);
});



test("every product in the complete built-in article stem resolves to a local fixed asset", () => {
  const { initialState } = require("./server");
  const { imageKeyForProduct } = require("./image-assets");
  const products = initialState().lists[0].products;
  assert.ok(products.length >= 450, `expected complete article stem, got ${products.length}`);
  for (const product of products) {
    const imageKey = imageKeyForProduct(product.name, product.categoryId);
    const file = path.join(__dirname, "assets", "product-images", `${imageKey}.webp`);
    assert.equal(fs.existsSync(file), true, `${product.name} -> ${imageKey}.webp missing`);
    assert.equal(product.imageSource ?? "catalog", "catalog", `${product.name} must not trigger Gemini`);
  }
});

test("existing custom products remain local while only truly new unknown products become pending", () => {
  const { initialState, migrateState, addEntry } = require("./server");
  const existing = structuredClone(initialState());
  existing.version = "0.3.20";
  existing.lists[0].products.push({ id: "product-custom-existing", key: "mein bestandsartikel", name: "Mein Bestandsartikel", categoryId: "other", icon: "📦", aliases: ["mein bestandsartikel"], favorite: true, useCount: 7 });
  existing.products = existing.lists[0].products;
  const migrated = migrateState(existing);
  const retained = migrated.lists[0].products.find((product) => product.id === "product-custom-existing");
  assert.equal(retained.imageSource, "catalog");
  assert.equal(retained.favorite, true);
  assert.equal(retained.useCount, 7);

  // Use the module's isolated test state for a brand-new name that is not in the catalog.
  const result = addEntry("Unbekannte Spezialflasche XQZ 987");
  assert.equal(result.createdProduct, true);
  const created = result.entry;
  assert.equal(created.imageSource, "pending");
});


test("visual inference separates previously colliding article families", () => {
  const { inferVisual } = require("./visual");
  const signature = (name, categoryId) => {
    const v = inferVisual(name, categoryId);
    return `${v.visualBase}|${v.visualMotif}|${v.visualLabel}`;
  };
  assert.notEqual(signature("Honig", "bakery_fitness"), signature("Marmelade", "bakery_fitness"));
  assert.notEqual(signature("Wraps", "bakery_fitness"), signature("Vollkornbrot", "bakery_fitness"));
  assert.notEqual(signature("Heidelbeeren", "produce"), signature("TK-Heidelbeeren", "frozen"));
  assert.notEqual(signature("Sojasauce hell", "oils_sauces"), signature("Sojasauce dunkel", "oils_sauces"));
  assert.notEqual(signature("Penne", "pasta_rice"), signature("Fusilli", "pasta_rice"));
  assert.notEqual(signature("Gnocchi", "ready_chilled"), signature("Tortellini", "ready_chilled"));
});

test("reviewed bakery and baking articles receive distinct local visual labels", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Honig", "bakery_fitness", { base: "jar", label: "HONIG" }],
    ["Haferflocken", "bakery_fitness", { base: "bag", label: "HAFER" }],
    ["Fladenbrot", "bakery_fitness", { base: "loose", label: "FLADEN" }],
    ["Hotdog-Brötchen", "bakery_fitness", { base: "loose", label: "HOTDOG" }],
    ["Knäckebrot", "bakery_fitness", { base: "box", label: "KNÄCKE" }],
    ["Knusperbrot", "bakery_fitness", { base: "box", label: "KNUSPER" }],
    ["Laugenbrezeln", "bakery_fitness", { base: "loose", label: "LAUGENBREZ." }],
    ["Toast Vollkorn", "bakery_fitness", { base: "loose", label: "VK TOAST" }],
    ["Toastkäse", "bakery_fitness", { base: "tray", label: "TOASTKÄSE" }],
    ["Wraps", "bakery_fitness", { base: "loose", label: "WRAPS" }],
    ["Tortilla-Wraps", "bakery_fitness", { base: "loose", label: "TORTILLA" }],
    ["Dinkelmehl Type 630", "baking", { base: "bag", label: "DINKEL 630" }],
    ["Roggenmehl Type 1150", "baking", { base: "bag", label: "ROGGEN" }],
    ["Hartweizengrieß", "baking", { base: "bag", label: "HARTWEIZEN" }],
    ["Natron", "baking", { base: "bag", label: "NATRON" }],
    ["Puderzucker", "baking", { base: "bag", label: "PUDER" }],
  ];
  for (const [name, categoryId, expected] of cases) {
    const actual = inferVisual(name, categoryId);
    assert.equal(actual.visualBase, expected.base, `${name} base`);
    assert.equal(actual.visualLabel, expected.label, `${name} label`);
  }
});

test("visual inference distinguishes fresh fruit and berry variants", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Heidelbeeren", "produce", "HEIDEL"],
    ["Himbeeren", "produce", "HIMBEER"],
    ["Erdbeeren", "produce", "ERDBEER"],
    ["Brombeeren", "produce", "BROMBEER"],
    ["Johannisbeeren", "produce", "JOHANNIS"],
    ["Stachelbeeren", "produce", "STACHEL"],
    ["Orange", "produce", "ORANGE"],
    ["Zitrone", "produce", "ZITRONE"],
    ["Limette", "produce", "LIMETTE"],
    ["Mandarinen", "produce", "MANDARINE"],
    ["Clementinen", "produce", "CLEMENTINE"],
    ["Mango", "produce", "MANGO"],
    ["Ananas", "produce", "ANANAS"],
    ["Kiwi", "produce", "KIWI"],
    ["Pfirsiche", "produce", "PFIRSICH"],
  ];
  for (const [name, categoryId, label] of cases) assert.equal(inferVisual(name, categoryId).visualLabel, label, name);
});

test("visual inference assigns clearer packaging to sauces sweets and chilled products", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Sojasauce", "oils_sauces", "bottle"],
    ["Balsamico", "oils_sauces", "bottle"],
    ["Sweet-Chili-Sauce", "oils_sauces", "squeeze"],
    ["Sriracha", "oils_sauces", "squeeze"],
    ["BBQ-Sauce", "oils_sauces", "squeeze"],
    ["Schokolade", "sweets", "bar"],
    ["Prinzenrolle", "sweets", "box"],
    ["Gummibärchen", "sweets", "box"],
    ["Gnocchi", "ready_chilled", "tray"],
    ["Fertigpizza", "ready_chilled", "tray"],
    ["Steak", "meat", "tray"],
  ];
  for (const [name, categoryId, base] of cases) assert.equal(inferVisual(name, categoryId).visualBase, base, name);
});

test("the complete article stem now has broad visual coverage and low collision hotspots", () => {
  const { initialState } = require("./server");
  const products = initialState().lists[0].products;
  const counts = new Map();
  for (const product of products) {
    const sig = `${product.categoryId}|${product.visualBase}|${product.visualMotif}|${product.visualLabel}`;
    counts.set(sig, (counts.get(sig) || 0) + 1);
    assert.ok(product.visualBase, `${product.name} missing visualBase`);
    assert.ok(product.visualMotif, `${product.name} missing visualMotif`);
  }
  const collisions = [...counts.values()].filter((count) => count > 1);
  const maxCollision = collisions.length ? Math.max(...collisions) : 1;
  assert.ok(products.length >= 450, `expected full article stem, got ${products.length}`);
  assert.ok(maxCollision <= 4, `visual collision hotspot too large: ${maxCollision}`);
});

test("every catalog-extra image mapping resolves to a local asset", () => {
  const { imageKeyForProduct } = require("./image-assets");
  const catalog = require("./catalog-extra");
  for (const product of catalog) {
    const imageKey = imageKeyForProduct(product.name, product.categoryId);
    const file = path.join(__dirname, "assets", "product-images", `${imageKey}.webp`);
    assert.equal(fs.existsSync(file), true, `${product.name} -> ${imageKey}.webp missing`);
  }
});


test("moves legacy automatic cleaning products out of household but preserves manual choices", () => {
  const { initialState, migrateState } = require("./server");
  const old = structuredClone(initialState());
  old.version = "0.3.27";
  const auto = old.products.find((p) => p.name === "Allzweckreiniger");
  auto.categoryId = "household"; auto.classificationSource = "gemini";
  const manual = old.products.find((p) => p.name === "Spülschwamm");
  manual.categoryId = "household"; manual.classificationSource = "manual";
  const entry = { id: "legacy-cleaner-entry", productId: auto.id, productKey: auto.key, name: auto.name, original: auto.name, quantity: null, categoryId: "household", createdAt: new Date().toISOString() };
  old.entries = [entry]; old.lists[0].entries = [entry]; old.lists[0].products = old.products;
  const migrated = migrateState(old);
  assert.equal(migrated.products.find((p) => p.id === auto.id).categoryId, "drugstore");
  assert.equal(migrated.entries.find((e) => e.id === entry.id).categoryId, "drugstore");
  assert.equal(migrated.products.find((p) => p.id === manual.id).categoryId, "household");
});

test("category descriptions and Gemini cost tracking migrate safely", () => {
  const { initialState, migrateState, page } = require("./server");
  const old = structuredClone(initialState());
  old.version = "0.3.27";
  for (const list of old.lists) for (const category of list.categories) delete category.description;
  delete old.geminiImageUsage;
  const migrated = migrateState(old);
  assert.match(migrated.categories.find((c) => c.id === "household").description, /Alufolie|Verpackungsartikel/);
  assert.match(migrated.categories.find((c) => c.id === "drugstore").description, /Putz- und Reinigungsmittel/);
  assert.equal(migrated.geminiImageUsage.totalImages, 0);
  const html = page();
  assert.match(html, /trackingVersion\|\|'0\.3\.29'|GEMINI_COST_TRACKING_SINCE/);
  assert.match(html, /Artikelstamm bearbeiten/);
  assert.match(html, /Kategorie-Icon erzeugen/);
  const editStart = html.indexOf("function openEdit");
  const editEnd = html.indexOf("async function saveEdit", editStart);
  const editSource = html.slice(editStart, editEnd);
  assert.doesNotMatch(editSource, />Löschen</);
});

test("all release version declarations are synchronized", () => {
  const serverSource = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const config = fs.readFileSync(path.join(__dirname, "..", "config.yaml"), "utf8");
  const dockerfile = fs.readFileSync(path.join(__dirname, "..", "Dockerfile"), "utf8");
  const pkg = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "package.json"), "utf8"));
  const sw = fs.readFileSync(path.join(__dirname, "assets", "sw.js"), "utf8");
  const manifest = fs.readFileSync(path.join(__dirname, "assets", "manifest.webmanifest"), "utf8");
  assert.match(serverSource, /const VERSION = "0\.3\.68"/);
  assert.match(config, /^version: 0\.3\.68$/m);
  assert.match(dockerfile, /^ARG BUILD_VERSION=0\.3\.68$/m);
  assert.equal(pkg.version, "0.3.68");
  assert.match(sw, /shell-0\.3\.68/);
  assert.match(manifest, /\?v=0\.3\.68/);
});

test("Ingress keeps API and backup requests inside the app path", () => {
  const serverSource = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  assert.match(serverSource, /new URL\(raw\.replace\(\/\^\\\/\+\//);
  assert.match(serverSource, /document\.baseURI/);
  assert.match(serverSource, /new URL\('api\/backup',document\.baseURI\)/);
  assert.doesNotMatch(serverSource, /raw\.startsWith\('\/'\)\?raw:'\/'\+raw,window\.location\.origin/);
});

test("Home Assistant app metadata keeps the stable slug and direct browser address", () => {
  const config = fs.readFileSync(path.join(__dirname, "..", "config.yaml"), "utf8");
  assert.match(config, /^slug: eigene_einkaufsliste$/m);
  assert.match(config, /^\s+8156\/tcp: 8156$/m);
  assert.match(config, /^webui: "http:\/\/\[HOST\]:\[PORT:8156\]\/"$/m);
  assert.doesNotMatch(config, /^ingress: true$/m);
  assert.match(config, /^image: ghcr\.io\/parrrrd\/home-assistant-webapps\/einkaufsliste$/m);
});

test("Dockerfile uses the current generic Home Assistant multiarch base and packaged CalDAV dependencies", () => {
  const dockerfile = fs.readFileSync(path.join(__dirname, "..", "Dockerfile"), "utf8");
  assert.match(dockerfile, /FROM ghcr\.io\/home-assistant\/base:3\.24-2026\.06\.1/);
  assert.match(dockerfile, /apk add --no-cache apache2-utils nodejs py3-bcrypt radicale/);
  assert.doesNotMatch(dockerfile, /pip3? install|requirements\.txt|Pillow/i);
});

test("every built-in article has a unique visual signature", () => {
  const { initialState } = require("./server");
  const products = initialState().lists[0].products;
  const seen = new Map();
  for (const product of products) {
    const signature = `${product.categoryId}|${product.visualBase}|${product.visualMotif}|${product.visualLabel}`;
    assert.equal(seen.has(signature), false, `${product.name} duplicates ${seen.get(signature)} with ${signature}`);
    seen.set(signature, product.name);
  }
  assert.equal(seen.size, products.length);
});

test("all built-in article ids keys and normalized names are unique", () => {
  const { initialState } = require("./server");
  const products = initialState().lists[0].products;
  const { normalizeText } = require("./core");
  for (const field of ["id", "key"]) {
    const values = products.map((product) => product[field]);
    assert.equal(new Set(values).size, values.length, `duplicate ${field}`);
  }
  const normalizedNames = products.map((product) => normalizeText(product.name));
  assert.equal(new Set(normalizedNames).size, normalizedNames.length, "duplicate product name");
});

test("every built-in article points to an existing category", () => {
  const { initialState } = require("./server");
  const state = initialState();
  const categoryIds = new Set(state.lists[0].categories.map((category) => category.id));
  for (const product of state.lists[0].products) assert.equal(categoryIds.has(product.categoryId), true, `${product.name}: ${product.categoryId}`);
});

test("all built-in articles remain local and carry no generated image path", () => {
  const { initialState } = require("./server");
  for (const product of initialState().lists[0].products) {
    assert.equal(product.imageSource, "catalog", product.name);
    assert.equal(Boolean(product.generatedImage), false, `${product.name} unexpectedly generated`);
  }
});

test("fresh and frozen equivalents are visually distinct", () => {
  const { inferVisual } = require("./visual");
  const pairs = [
    ["Heidelbeeren", "produce", "TK-Heidelbeeren", "frozen"],
    ["Himbeeren", "produce", "TK-Himbeeren", "frozen"],
    ["Erdbeeren", "produce", "TK-Erdbeeren", "frozen"],
    ["Kirschen", "produce", "TK-Kirschen", "frozen"],
    ["Mango", "produce", "TK-Mango", "frozen"],
    ["Brokkoli", "produce", "TK-Brokkoli", "frozen"],
    ["Blumenkohl", "produce", "TK-Blumenkohl", "frozen"],
    ["Spinat", "produce", "TK-Spinat", "frozen"],
  ];
  const sig = (name, category) => { const v=inferVisual(name, category); return `${v.visualBase}|${v.visualMotif}|${v.visualLabel}`; };
  for (const [fresh, freshCat, frozen, frozenCat] of pairs) assert.notEqual(sig(fresh,freshCat), sig(frozen,frozenCat), `${fresh} vs ${frozen}`);
});

test("all frozen catalog products use frozen bag packaging except no exceptions", () => {
  const { initialState } = require("./server");
  for (const product of initialState().lists[0].products.filter((p) => p.categoryId === "frozen")) assert.equal(product.visualBase, "frozen_bag", product.name);
});

test("all produce catalog products remain loose and never look packaged", () => {
  const { initialState } = require("./server");
  for (const product of initialState().lists[0].products.filter((p) => p.categoryId === "produce")) assert.equal(product.visualBase, "loose", product.name);
});

test("cheese packaging differentiates grated soft and fresh products", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Gouda gerieben", "bag"], ["Mozzarella gerieben", "bag"], ["Camembert", "tray"], ["Brie", "tray"],
    ["Frischkäse", "cup"], ["Körniger Frischkäse", "cup"], ["Mozzarella", "pouch"], ["Parmesan", "tray"]
  ];
  for (const [name, base] of cases) assert.equal(inferVisual(name,"cheese").visualBase, base, name);
});

test("household packaging is plausible for bags rolls tabs and cloths", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Gefrierbeutel 1 l", "box"], ["Müllbeutel 60 l", "box"], ["Küchenrolle", "roll"],
    ["Spülmaschinentabs", "box"], ["Spülschwamm", "bundle"], ["Mikrofasertücher", "bundle"], ["Waschmittel", "bottle"]
  ];
  for (const [name, base] of cases) assert.equal(inferVisual(name,"household").visualBase, base, name);
});

test("drugstore packaging is plausible for paper hygiene and dental products", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Toilettenpapier", "roll"], ["Taschentücher", "box"], ["Tampons", "box"], ["Windeln", "bag"],
    ["Zahnpasta", "tube"], ["Zahnbürste", "box"], ["Shampoo", "bottle"]
  ];
  for (const [name, base] of cases) assert.equal(inferVisual(name,"drugstore").visualBase, base, name);
});

test("drink packaging distinguishes coffee tea juice and bottles", () => {
  const { inferVisual } = require("./visual");
  const cases = [["Kaffee","bag"],["Tee","box"],["Apfelsaft","carton"],["Apfelschorle","carton"],["Wasser","bottle"],["Cola","bottle"]];
  for (const [name, base] of cases) assert.equal(inferVisual(name,"drinks").visualBase, base, name);
});

test("Gemini Interactions request uses the currently documented minimal image request", async () => {
  const { requestGeminiProductImage } = require("./server");
  const originalFetch = global.fetch;
  let captured;
  global.fetch = async (url, options) => {
    captured = { url, options };
    return { ok: true, status: 200, json: async () => ({ output_image: { data: "ZmFrZQ==" }, usage: { total_input_tokens: 9, total_output_tokens: 1120, total_thought_tokens: 4, output_tokens_by_modality: [{ modality: "image", tokens: 1120 }] } }) };
  };
  try {
    const result = await requestGeminiProductImage("test-key", "make icon");
    assert.equal(result.data, "ZmFrZQ==");
    assert.equal(result.apiUsage.inputTokens, 9);
    assert.equal(result.apiUsage.imageOutputTokens, 1120);
    assert.equal(result.apiUsage.thoughtTokens, 4);
    assert.equal(captured.url, "https://generativelanguage.googleapis.com/v1beta/interactions");
    const body = JSON.parse(captured.options.body);
    assert.deepEqual(body, { model: "gemini-3.1-flash-image", input: [{ type: "text", text: "make icon" }] });
    assert.equal(captured.options.headers["x-goog-api-key"], "test-key");
    assert.equal("response_format" in body, false);
    assert.equal("generationConfig" in body, false);
  } finally { global.fetch = originalFetch; }
});

test("Gemini GenerateContent fallback uses v1 and image-only response modalities", async () => {
  const { requestGeminiProductImage } = require("./server");
  const originalFetch = global.fetch;
  const calls=[];
  global.fetch = async (url, options) => {
    calls.push({url,options});
    if (calls.length===1) return { ok:false, status:400, text:async()=>"primary fail" };
    return { ok:true, status:200, json:async()=>({ candidates:[{ content:{ parts:[{ inlineData:{ data:"aW1hZ2U=" } }] } }], usageMetadata:{promptTokenCount:11,candidatesTokenCount:1120,thoughtsTokenCount:3,totalTokenCount:1134,candidatesTokensDetails:[{modality:"IMAGE",tokenCount:1120}]} }) };
  };
  try {
    const result=await requestGeminiProductImage("key","prompt");
    assert.equal(result.data,"aW1hZ2U=");
    assert.equal(result.apiUsage.inputTokens,11);
    assert.equal(result.apiUsage.imageOutputTokens,1120);
    assert.equal(result.apiUsage.thoughtTokens,3);
    assert.equal(calls[1].url,"https://generativelanguage.googleapis.com/v1/models/gemini-3.1-flash-image:generateContent");
    const body=JSON.parse(calls[1].options.body);
    assert.deepEqual(body.generationConfig,{responseModalities:["IMAGE"]});
    assert.equal(JSON.stringify(body).includes("response_format"),false);
    assert.equal(JSON.stringify(body).includes("mime_type"),false);
  } finally { global.fetch=originalFetch; }
});

test("Gemini image price uses actual modality token counts", () => {
  const { normalizeImageApiUsage, calculateGeminiImageCostUsd } = require("./server");
  const usage = normalizeImageApiUsage({usage:{total_input_tokens:100,total_output_tokens:1120,total_thought_tokens:20,output_tokens_by_modality:[{modality:"image",tokens:1120}]}}, "interactions");
  assert.deepEqual(usage, {source:"interactions",inputTokens:100,imageOutputTokens:1120,textOutputTokens:0,thoughtTokens:20,totalTokens:0});
  assert.equal(Number(calculateGeminiImageCostUsd(usage).toFixed(5)), 0.06731);
});

test("article list hides favorite and master-data shortcut buttons while editor stays reachable", () => {
  const html = require("./server").page();
  const start = html.indexOf("function card(e)");
  const end = html.indexOf("function showSnack", start);
  const cardSource = html.slice(start, end);
  assert.doesNotMatch(cardSource, /toggleFavorite|Artikelstamm bearbeiten|catalog-link/);
  assert.match(html, /Artikelstamm bearbeiten/);
});

test("master-data editor uses one optional icon hint instead of visual selectors", () => {
  const html = require("./server").page();
  const start = html.indexOf("function editCatalogProduct");
  const end = html.indexOf("async function moveCategory", start);
  const source = html.slice(start, end);
  assert.match(source, /Icon-Hinweis \(optional\)/);
  assert.match(source, /Bearbeitet/);
  assert.match(source, /Unbearbeitet/);
  assert.doesNotMatch(source, /Produktart \/ Verpackung|Motiv \/ Inhalt|Text auf dem Icon/);
  assert.doesNotMatch(source, /US-\$|Je Erstellung|≈/);
  const autoStart = html.indexOf("async function autoReclassifyProduct");
  const autoEnd = html.indexOf("function editCatalogProduct", autoStart);
  const autoSource = html.slice(autoStart, autoEnd);
  assert.match(autoSource, /displayName/);
  assert.match(autoSource, /categoryId/);
  assert.doesNotMatch(autoSource, /visual-base|visual-motif|visual-label/);
});

test("legacy estimated Gemini totals restart exact accounting at 0.3.29", () => {
  const { initialState, migrateState } = require("./server");
  const old = structuredClone(initialState());
  old.version = "0.3.28";
  old.geminiImageUsage = {totalImages:3,totalCostUsd:0.201,daily:{},lastGeneration:{costUsd:0.067},trackingSince:"2026-09-10T00:00:00Z"};
  const migrated = migrateState(old);
  assert.equal(migrated.geminiImageUsage.accountingVersion, 2);
  assert.equal(migrated.geminiImageUsage.totalImages, 0);
  assert.equal(migrated.geminiImageUsage.totalCostEur, 0);
  assert.equal(migrated.geminiImageUsage.previousEstimatedImages, 3);
});

test("generated image type detection accepts JPEG PNG and WebP", () => {
  const { detectGeneratedImageExtension } = require("./server");
  assert.equal(detectGeneratedImageExtension(Buffer.from([0xff,0xd8,0xff,0xdb])), ".jpg");
  assert.equal(detectGeneratedImageExtension(Buffer.from([0x89,0x50,0x4e,0x47])), ".png");
  assert.equal(detectGeneratedImageExtension(Buffer.from([0x52,0x49,0x46,0x46])), ".webp");
});

test("catalog UI uses local baseline and processed photos instead of SVG", () => {
  const source = fs.readFileSync(path.join(__dirname,"server.js"),"utf8");
  const start = source.lastIndexOf("function productIcon(e){");
  const end = source.indexOf("function categorySceneV2", start);
  const productIconSource = source.slice(start,end);
  assert.match(productIconSource,/product-images\//);
  assert.match(productIconSource,/processedIcon/);
  assert.doesNotMatch(productIconSource,/productVisualSvgV3/);
});

test("service worker keeps image cache across releases and image requests stay network-first", () => {
  const sw=fs.readFileSync(path.join(__dirname,"assets","sw.js"),"utf8");
  assert.match(sw,/eigene-einkaufsliste-shell-0\.3\.68/);
  assert.match(sw,/eigene-einkaufsliste-images-v1/);
  assert.match(sw,/product-images|category-images/);
  assert.match(sw,/fetch\(request, \{ cache: "no-cache" \}\)/);
  assert.match(sw,/name\.startsWith\("eigene-einkaufsliste-shell-"\)/);
  assert.match(sw,/oldCache\.keys\(\)/);
  assert.match(sw,/imageCache\.put\(imageCacheKey/);
  assert.doesNotMatch(sw,/name\.startsWith\("eigene-einkaufsliste-images-/);
});


test("semantic edge cases use the intended motif and packaging", () => {
  const { inferVisual } = require("./visual");
  const cases = [
    ["Knoblauch","produce","loose","garlic"], ["Granatapfel","produce","loose","fruit"], ["Zucchini","produce","loose","cucumber"],
    ["Hefe","bakery_fitness","box","baking"], ["Buttermilch","milk","carton","milk"], ["Butter gesalzen","ready_chilled","box","butter"],
    ["Nutella","sweets","jar","spread"], ["Schokoriegel","sweets","bar","chocolate"], ["Kinder Riegel","sweets","bar","chocolate"],
    ["Vegane Mayo","vegetarian","jar","sauce"], ["Vegane Sahne","vegetarian","carton","milk"], ["Vegane Crème fraîche","vegetarian","cup","yogurt"],
    ["Topfreiniger","drugstore","bottle","bodycare"], ["Eingelegte Gurken","canned","can","cucumber"]
  ];
  for (const [name,cat,base,motif] of cases) {
    const v=inferVisual(name,cat); assert.equal(v.visualBase,base,`${name} base`); assert.equal(v.visualMotif,motif,`${name} motif`);
  }
});

test("all catalog visual labels are present and bounded", () => {
  const { initialState } = require("./server");
  for (const p of initialState().lists[0].products) {
    assert.ok(String(p.visualLabel||"").trim().length>0, `${p.name} blank visualLabel`);
    assert.ok(String(p.visualLabel).length<=18, `${p.name} visualLabel too long`);
  }
});

test("category image files exist for every category", () => {
  const { initialState } = require("./server");
  const { categoryImageKey } = require("./image-assets");
  for (const c of initialState().lists[0].categories) {
    const key=categoryImageKey(c); const file=path.join(__dirname,"assets","category-images",`${key}.webp`);
    assert.equal(fs.existsSync(file),true,`${c.name} -> ${key}.webp missing`);
    assert.ok(fs.statSync(file).size>500,`${c.name} category image suspiciously small`);
  }
});

test("all product fallback assets are valid nonempty webp files", () => {
  const dir=path.join(__dirname,"assets","product-images");
  const files=fs.readdirSync(dir).filter((name)=>name.endsWith('.webp'));
  assert.ok(files.length>=250,`expected product asset library, got ${files.length}`);
  for(const name of files){assert.match(name,/^[a-zA-Z0-9_-]+\.webp$/); assert.ok(fs.statSync(path.join(dir,name)).size>100,`${name} too small`);}
});

test("service run scripts start the app and a newly supervised CalDAV service without runtime installs", () => {
  const run=fs.readFileSync(path.join(__dirname,"..","rootfs","etc","services.d","eigene-einkaufsliste","run"),"utf8");
  assert.match(run,/^#!\/usr\/bin\/with-contenv bashio/m);
  assert.match(run,/exec node \/app\/server\.js/);
  assert.doesNotMatch(run,/ha apps update|rebuild|apk add/);
  const caldavRun=fs.readFileSync(path.join(__dirname,"..","rootfs","etc","services.d","einkaufsliste-caldav","run"),"utf8");
  assert.match(caldavRun,/exec sleep infinity/);
  const caldavV2Run=fs.readFileSync(path.join(__dirname,"..","rootfs","etc","services.d","einkaufsliste-caldav-v2","run"),"utf8");
  assert.match(caldavV2Run,/exec radicale --config \/etc\/radicale\/config/);
  assert.match(caldavV2Run,/htpasswd -B -i -c/);
  assert.doesNotMatch(caldavRun,/curl|wget|apk add|pip install/);
});

test("Gemini option remains a password field and sync token remains configured", () => {
  const config=fs.readFileSync(path.join(__dirname,"..","config.yaml"),"utf8");
  assert.match(config,/gemini_api_key:\s*""/);
  assert.match(config,/gemini_api_key:\s*password/);
  assert.match(config,/sync_token:\s*str/);
});

test("Gemini request source contains none of the rejected response-format fields", () => {
  const source=fs.readFileSync(path.join(__dirname,"server.js"),"utf8");
  const start=source.indexOf("async function requestGeminiProductImage");
  const end=source.indexOf("async function generateProductImage",start);
  const fn=source.slice(start,end);
  assert.doesNotMatch(fn,/mime_type\s*:\s*["']image\/png/i);
  assert.doesNotMatch(fn,/response_format\s*:/i);
  assert.doesNotMatch(fn,/aspect_ratio\s*:/i);
  assert.match(fn,/v1beta\/interactions/);
  assert.match(source,/const GEMINI_IMAGE_MODEL = "gemini-3\.1-flash-image"/);
  assert.match(fn,/v1\/models\/\$\{GEMINI_IMAGE_MODEL\}:generateContent/);
});

test("generated image route explicitly supports JPEG PNG and WebP", () => {
  const source=fs.readFileSync(path.join(__dirname,"server.js"),"utf8");
  const start=source.indexOf('url.pathname.startsWith("/generated-product-images/")');
  const route=source.slice(start,start+1100);
  assert.match(route,/png\|jpg\|jpeg\|webp/);
  assert.match(route,/image\/jpeg/);
  assert.match(route,/image\/png/);
  assert.match(route,/image\/webp/);
});

test("catalog includes distinct fresh and frozen blueberry product records", () => {
  const { initialState }=require("./server");
  const products=initialState().lists[0].products;
  const fresh=products.find((p)=>p.name==='Heidelbeeren');
  const frozen=products.find((p)=>p.name==='TK-Heidelbeeren');
  assert.ok(fresh); assert.ok(frozen);
  assert.notEqual(fresh.id,frozen.id); assert.notEqual(fresh.categoryId,frozen.categoryId);
  assert.notDeepEqual([fresh.visualBase,fresh.visualMotif,fresh.visualLabel],[frozen.visualBase,frozen.visualMotif,frozen.visualLabel]);
});

test("manually selected visual fields survive migration", () => {
  const { initialState,migrateState }=require("./server");
  const state=structuredClone(initialState());
  const p=state.lists[0].products[0];
  p.visualBase='jar'; p.visualMotif='spread'; p.visualLabel='MEIN ICON'; p.visualSource='manual';
  state.products=state.lists[0].products;
  const migrated=migrateState(state); const result=migrated.lists[0].products.find((x)=>x.id===p.id);
  assert.equal(result.visualBase,'jar'); assert.equal(result.visualMotif,'spread'); assert.equal(result.visualLabel,'MEIN ICON'); assert.equal(result.visualSource,'manual');
});

test("migration preserves the critical 1.65 kg measurement as product detail", () => {
  const { initialState,migrateState }=require("./server");
  const state=structuredClone(initialState());
  const entry={id:'critical-gemuese',productId:'product-gemuese',productKey:'gemuse eins komma',name:'Gemüse',original:'Gemüse eins komma sechs fünf kilo',quantity:{value:1.65,unit:'kg'},categoryId:'produce',createdAt:'2026-09-09T00:00:00Z'};
  state.lists[0].entries=[entry]; state.entries=state.lists[0].entries;
  const migrated=migrateState(state); const result=migrated.lists[0].entries.find((x)=>x.id==='critical-gemuese');
  assert.equal(result.quantity,null);
  assert.equal(result.productDetail,'1,65 kg');
});

test("page source exposes visible Gemini progress retry and error states", () => {
  const { page }=require("./server"); const html=page();
  assert.match(html,/Gemini erzeugt/); assert.match(html,/Erneut versuchen/); assert.match(html,/Gemini-Bildfehler/); assert.match(html,/Icon neu erstellen/);
});

test("reviewed common article names are now part of the built-in article stem", () => {
  const { initialState } = require("./server");
  const names = new Set(initialState().lists[0].products.map((product) => product.name));
  for (const name of ["Gemüse", "Rucola", "Honig", "Toastkäse", "Knusperbrot", "Müsliriegel", "Flammkuchenboden", "Roher Schinken", "Gefrierbeutel", "Geriebener Käse"]) {
    assert.equal(names.has(name), true, `${name} missing in built-in article stem`);
  }
});

test("adding reviewed generic names stays local and never falls back to pending Gemini icons", () => {
  const { addEntry } = require("./server");
  const cases = [
    ["Gemüse 1,65 kg", "Gemüse", "produce", null, "1,65 kg"],
    ["Honig", "Honig", "bakery_fitness", null, ""],
    ["Toastkäse", "Toastkäse", "cheese", null, ""],
    ["Rucola", "Rucola", "produce", null, ""],
  ];
  for (const [input, expectedName, expectedCategoryId, expectedQuantity, expectedDetail] of cases) {
    const result = addEntry(input);
    assert.equal(result.createdProduct, false, `${input} unexpectedly created a new product`);
    assert.equal(result.entry.productName, expectedName, input);
    assert.equal(result.entry.categoryId, expectedCategoryId, input);
    assert.equal(result.entry.imageSource, "catalog", input);
    assert.deepEqual(result.entry.quantity || null, expectedQuantity, input);
    assert.equal(result.entry.productDetail || "", expectedDetail, input);
  }
});

test("deleted built-in article tombstones survive migration and prevent automatic re-seeding", () => {
  const { initialState, migrateState } = require("./server");
  const original = structuredClone(initialState());
  const list = original.lists[0];
  list.products = list.products.filter((product) => product.key !== "honig");
  list.deletedProductKeys = ["honig"];
  original.products = list.products;
  original.deletedProductKeys = ["honig"];
  const migrated = migrateState(original);
  assert.equal(migrated.lists[0].products.some((product) => product.key === "honig"), false);
  assert.deepEqual(migrated.lists[0].deletedProductKeys, ["honig"]);
});

test("catalog management exposes an explicit product delete action and persistent DELETE API", () => {
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  assert.match(source, /deleteCatalogProduct\(event,/);
  assert.match(source, /req\.method === "DELETE"/);
  assert.match(source, /Artikel aus dem Artikelstamm löschen/);
  assert.match(source, /deletedProductKeys/);
});

test("background polling avoids unconditional full renders and catalog category icons reserve layout space", () => {
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const refreshStart = source.indexOf("async function backgroundRefresh()");
  const refreshEnd = source.indexOf("async function refresh", refreshStart + 10) > refreshStart ? source.indexOf("async function refresh", refreshStart + 10) : source.indexOf("async function watchGemini", refreshStart);
  const refreshSource = source.slice(refreshStart, refreshEnd > refreshStart ? refreshEnd : refreshStart + 1600);
  assert.match(refreshSource, /visibleStateSignature/);
  assert.match(refreshSource, /if\(needsPaint\)render\(\)/);
  assert.doesNotMatch(refreshSource, /appState=materialized;await saveLocalState\(\);render\(\)/);
  assert.match(source, /\.catalog-category>\.cat-choice \.cat-icon\{width:48px;height:48px;min-width:48px;flex:0 0 48px;overflow:hidden/);
  assert.match(source, /\.catalog-category>\.cat-choice \.category-photo\{width:44px;height:44px/);
});


test("optional default quantities are normalized and explicit quantities win", () => {
  const { normalizeDefaultQuantity, effectiveQuantityForProduct } = require("./server");
  assert.deepEqual(normalizeDefaultQuantity({ value: "2,5", unit: "Packung" }), { value: 2.5, unit: "Packung" });
  assert.equal(normalizeDefaultQuantity(null), null);
  assert.equal(normalizeDefaultQuantity({ value: 0, unit: "Stück" }), null);
  const product = { defaultQuantity: { value: 1, unit: "Nachfüllbeutel" } };
  assert.deepEqual(effectiveQuantityForProduct(null, product), { value: 1, unit: "Nachfüllbeutel" });
  assert.deepEqual(effectiveQuantityForProduct({ value: 3, unit: "Packung" }, product), { value: 3, unit: "Packung" });
});

test("migration preserves valid default quantities and drops invalid ones", () => {
  const { initialState, migrateState } = require("./server");
  const original = structuredClone(initialState());
  original.lists[0].products[0].defaultQuantity = { value: "1,5", unit: "kg" };
  original.lists[0].products[1].defaultQuantity = { value: 0, unit: "Stück" };
  original.products = original.lists[0].products;
  const migrated = migrateState(original);
  assert.deepEqual(migrated.lists[0].products[0].defaultQuantity, { value: 1.5, unit: "kg" });
  assert.equal(migrated.lists[0].products[1].defaultQuantity, null);
});

test("compact spacing variants resolve locally and are safe only when unique", () => {
  const { compactProductKey } = require("./server");
  assert.equal(compactProductKey("Pfeffer Körner"), compactProductKey("Pfefferkörner"));
  assert.equal(compactProductKey("Eis-Würfel"), compactProductKey("Eiswürfel"));
});

test("confirmed category learning accepts exact examples immediately but keeps generic terms conservative", () => {
  const { learnedCategoryForName } = require("./server");
  const list = {
    categories: [{ id: "household" }, { id: "drugstore" }, { id: "other" }],
    learningExamples: [
      { productName: "Alufolie extra stark", normalized: "alufolie extra stark", terms: ["alufolie", "extra stark"], toCategoryId: "household", count: 1 },
      { productName: "Küchen Reiniger", normalized: "kuchen reiniger", terms: ["kuchen", "reiniger", "kuchen reiniger"], toCategoryId: "drugstore", count: 1 },
    ],
  };
  assert.equal(learnedCategoryForName("Alufolie extra stark", list)?.categoryId, "household");
  assert.equal(learnedCategoryForName("Küchen Reiniger Spray", list)?.categoryId, "drugstore");
  assert.equal(learnedCategoryForName("Universal Reiniger", list), null);
});

test("Gemini classification is only the fallback for truly unknown automatic products", () => {
  const { needsGeminiClassification } = require("./server");
  const list = { categories: [{ id: "produce" }, { id: "other" }] };
  assert.equal(needsGeminiClassification({ classificationSource: "automatic", categoryId: "other", imageSource: "pending" }, list), true);
  assert.equal(needsGeminiClassification({ classificationSource: "rule", categoryId: "produce", imageSource: "pending" }, list), false);
  assert.equal(needsGeminiClassification({ classificationSource: "learned", categoryId: "produce", imageSource: "pending" }, list), false);
  assert.equal(needsGeminiClassification({ classificationSource: "manual", categoryId: "produce", imageSource: "gemini" }, list), false);
  assert.equal(needsGeminiClassification({ classificationSource: "automatic", categoryId: "produce", imageSource: "catalog" }, list), false);
});

test("article editor exposes optional standard quantity and protects processed icons from repeat generation", () => {
  const { page } = require("./server");
  const html = page();
  assert.match(html, /Standardmenge \(optional\)/);
  assert.match(html, /Standardeinheit/);
  assert.doesNotMatch(html, /Eine ausdrücklich gesprochene Menge hat immer Vorrang/);
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const start = source.indexOf("function upgradeIconOnUse");
  const end = source.indexOf("function activeList", start);
  assert.match(source.slice(start, end), /iconEditState\(product\) === "processed"/);
});


test("settings show Gemini usage including last generated article or category", () => {
  const { page } = require("./server");
  const html = page();
  assert.match(html, /function manageLists\(\).*geminiCostHtml\(\)/s);
  assert.match(html, /Zuletzt erstellt/);
  assert.match(html, /last\.kind==='category'\?'Kategorie':'Artikel'/);
  assert.match(html, /Letzte Erstellung:/);
  assert.match(html, /Heute:/);
  assert.match(html, /Gesamt seit/);
});

test("article and category editors expose local icon upload without replacing Gemini actions", () => {
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const html = require("./server").page();
  assert.match(html, />Eigenes Icon</);
  assert.match(source, /\/api\/products\/[^\n]+upload-image/);
  assert.match(source, /\/api\/categories\/[^\n]+upload-image/);
  assert.match(html, /Icon neu erstellen/);
  assert.match(html, /Kategorie-Icon erzeugen/);
});


test("legacy Zip-Tiefkühlbeutel migrates to household with a preserved 1 Liter product detail", () => {
  const { initialState, migrateState } = require("./server");
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.33";
  const list = legacy.lists[0];
  const product = { id: "product-zip-bag", key: "zip tiefkuhlbeutel", name: "Zip tiefkühlbeutel", categoryId: "frozen", icon: "❄️", aliases: ["zip tiefkuhlbeutel"], favorite: false, useCount: 1, classificationSource: "automatic", imageSource: "pending" };
  const entry = { id: "entry-zip-bag", productId: product.id, productKey: product.key, name: product.name, original: "Zip tiefkühlbeutel ein Liter", quantity: { value: 1, unit: "l" }, categoryId: "frozen", createdAt: "2026-09-12T11:00:00Z" };
  list.products.push(product); list.entries.push(entry); legacy.products=list.products; legacy.entries=list.entries;
  const migrated = migrateState(legacy);
  const migratedProduct = migrated.lists[0].products.find((item) => item.id === product.id);
  const migratedEntry = migrated.lists[0].entries.find((item) => item.id === entry.id);
  assert.equal(migratedProduct.name, "Zip-Tiefkühlbeutel");
  assert.equal(migratedProduct.categoryId, "household");
  assert.equal(migratedEntry.name, "Zip-Tiefkühlbeutel");
  assert.equal(migratedEntry.categoryId, "household");
  assert.equal(migratedEntry.quantity, null);
  assert.equal(migratedEntry.productDetail, "1 Liter");
  assert.equal(migratedEntry.original, "Zip tiefkühlbeutel ein Liter");
});

test("automatic metric measurements become product details while purchase counts stay quantities", () => {
  const { prepareParsedProductDetail } = require("./server");
  const one = prepareParsedProductDetail(parseItemInput("Zip Tiefkühlbeutel ein Liter"));
  assert.equal(one.name, "Zip-Tiefkühlbeutel");
  assert.equal(one.productDetail, "1 Liter");
  assert.equal(one.quantity, null);
  const two = prepareParsedProductDetail(parseItemInput("2 Packungen Zip Tiefkühlbeutel ein Liter"));
  assert.equal(two.name, "Zip-Tiefkühlbeutel");
  assert.deepEqual(two.quantity, { value: 2, unit: "packung" });
  assert.equal(two.productDetail, "1 Liter");
  const three = prepareParsedProductDetail(parseItemInput("500 g Hackfleisch"));
  assert.equal(three.name, "Hackfleisch");
  assert.equal(three.productDetail, "500 g");
  assert.equal(three.quantity, null);
});

test("same article stays a duplicate even when product detail differs", () => {
  const { addEntry } = require("./server");
  const first = addEntry("Zip Tiefkühlbeutel ein Liter", { allowDuplicate: false });
  assert.equal(first.duplicate, false);
  assert.equal(first.entry.productName, "Zip-Tiefkühlbeutel");
  assert.equal(first.entry.productDetail, "1 Liter");
  const duplicate = addEntry("Zip Tiefkühlbeutel 1 Liter");
  assert.equal(duplicate.duplicate, true);
  const otherSize = addEntry("Zip Tiefkühlbeutel 3 Liter");
  assert.equal(otherSize.duplicate, true);
});

test("shopping editor exposes product size separately from quantity and note", () => {
  const html = require("./server").page();
  assert.match(html, /Produktgröße \/ Variante \(optional\)/);
  assert.match(html, /id="edit-product-detail"/);
  assert.match(html, /class="product-detail"/);
  assert.match(html, /productDetail/);
});

test("Meyerhof names are cleaned and existing tagged products migrate into the Meyerhof category", () => {
  const { initialState, migrateState, stripMeyerhofTag } = require("./server");
  assert.deepEqual(stripMeyerhofTag("Gouda Meyerhof"), { tagged: true, rawName: "Gouda Meyerhof", name: "Gouda" });
  assert.deepEqual(stripMeyerhofTag("Bunte Nudeln (Meyerhof)"), { tagged: true, rawName: "Bunte Nudeln (Meyerhof)", name: "Bunte Nudeln" });
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.32";
  const list = legacy.lists[0];
  list.categories.push({ id: "meyerhof-user", name: "Meyerhof", icon: "📦", sort: 99, description: "Produkte vom Meyerhof" });
  list.products.push({ id: "product-meyerhof-gouda", key: "gouda meyerhof", name: "Gouda Meyerhof", categoryId: "cheese", icon: "🧀", aliases: ["gouda meyerhof"], favorite: false, useCount: 1, classificationSource: "automatic", imageSource: "pending" });
  list.entries.push({ id: "entry-meyerhof-gouda", productId: "product-meyerhof-gouda", productKey: "gouda meyerhof", name: "Gouda Meyerhof", original: "Gouda Meyerhof", quantity: null, categoryId: "cheese", createdAt: new Date().toISOString() });
  legacy.categories = list.categories; legacy.products = list.products; legacy.entries = list.entries;
  const migrated = migrateState(legacy);
  const category = migrated.lists[0].categories.find(c => c.id === "meyerhof-user");
  const product = migrated.lists[0].products.find(p => p.id === "product-meyerhof-gouda");
  const entry = migrated.lists[0].entries.find(e => e.id === "entry-meyerhof-gouda");
  assert.equal(category.imageSource, "catalog");
  assert.equal(category.meyerhofIconVersion, 1);
  assert.equal(product.name, "Gouda");
  assert.equal(product.categoryId, "meyerhof-user");
  assert.equal(product.sourceTag, "meyerhof");
  assert.equal(entry.name, "Gouda");
  assert.equal(entry.categoryId, "meyerhof-user");
});

test("legacy quantity-text hacks migrate into the dedicated entry note field", () => {
  const { migrateEntryNote } = require("./server");
  const migrated = migrateEntryNote({ id: "x", quantity: { value: 1, unit: "Vor dem nächsten Flammkuchen" } });
  assert.equal(migrated.quantity, null);
  assert.equal(migrated.note, "Vor dem nächsten Flammkuchen");
  const realQuantity = migrateEntryNote({ id: "y", quantity: { value: 1, unit: "Nachfüllbeutel" } });
  assert.deepEqual(realQuantity.quantity, { value: 1, unit: "Nachfüllbeutel" });
  assert.equal(realQuantity.note, undefined);
});

test("shopping rows expose a dedicated one-tap check target, keep long press editing and a dedicated note field", () => {
  const { page } = require("./server");
  const html = page();
  const cardStart = html.indexOf("function card(e)");
  const cardEnd = html.indexOf("function showSnack", cardStart);
  const cardSource = html.slice(cardStart, cardEnd);
  assert.match(cardSource, /class="check"/);
  assert.match(cardSource, /onclick="checkItem\(event/);
  assert.match(cardSource, /onpointerdown="event\.stopPropagation\(\)"/);
  assert.doesNotMatch(cardSource, /onclick="cardClick/);
  const clickStart = html.indexOf("function cardClick");
  const clickEnd = html.indexOf("function createCategory", clickStart);
  const clickSource = html.slice(clickStart, clickEnd);
  assert.match(clickSource, /checkItem\(ev,id\)/);
  assert.doesNotMatch(clickSource, /deleteItem\(id\)/);
  assert.match(html, /setTimeout\(\(\)=>\{if\(gestureMoved.*openEdit\(id\).*\},800\)/s);
  assert.match(html, /function gestureMove\(ev,id\).*Math\.hypot\(dx,dy\)>10.*holdEnd\(\)/s);
  assert.match(html, /Notiz \(optional\)/);
  assert.match(html, /id="edit-note"/);
  assert.match(html, /entry-note/);
});

test("Meyerhof ships with its own local category icon asset", () => {
  const image = path.join(__dirname, "assets", "category-images", "meyerhof.webp");
  assert.ok(fs.existsSync(image));
  assert.ok(fs.statSync(image).size > 1000);
  const { categoryImageKey } = require("./image-assets");
  assert.equal(categoryImageKey({ name: "Meyerhof" }), "meyerhof");
  assert.equal(categoryImageKey({ name: "Meyerhof Belm" }), "meyerhof");
});

test("new-product processing continues to image generation even when classification throws", () => {
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const start = source.indexOf("async function processCreatedProduct");
  const end = source.indexOf("function importAllowed", start);
  const body = source.slice(start, end);
  assert.match(body, /catch \(error\)[\s\S]*Bildverarbeitung wird trotzdem fortgesetzt/);
  assert.match(body, /await ensureProductImageOnUse\(product, list\)/);
  assert.match(source, /async function resumePendingProductImages\(\)[\s\S]*product\.imageSource !== "pending"[\s\S]*generateProductImage\(product, list\)/);
  const importStart = source.indexOf('if (pathname === "/api/import"');
  const importEnd = source.indexOf('if (pathname === \"/api/products\"', importStart);
  const importRoute = source.slice(importStart, importEnd);
  assert.match(importRoute, /void processCreatedProduct\(added, targetListId\)/);
  assert.match(importRoute, /processCreatedProduct\(added, targetListId\)/);
});

test("DM Rossmann and Müller Alexa suffixes normalize into the shared retailer category without losing the store", () => {
  const { initialState, extractRetailerTag, prepareParsedForList } = require("./server");
  assert.deepEqual(extractRetailerTag("Starkes deo D. M."), { tagged: true, rawName: "Starkes deo D. M.", baseName: "Starkes Deo", name: "Starkes Deo (DM)", storeLabel: "DM" });
  assert.deepEqual(extractRetailerTag("Shampoo Rossmann"), { tagged: true, rawName: "Shampoo Rossmann", baseName: "Shampoo", name: "Shampoo (Rossmann)", storeLabel: "Rossmann" });
  assert.deepEqual(extractRetailerTag("Handseife Mueller"), { tagged: true, rawName: "Handseife Mueller", baseName: "Handseife", name: "Handseife (Müller)", storeLabel: "Müller" });
  const list = structuredClone(initialState().lists[0]);
  list.categories.push({ id: "retailer-user", name: "DM/Rossmann/Müller", icon: "📦", sort: 99 });
  const prepared = prepareParsedForList(parseItemInput("Starkes deo d m"), list);
  assert.equal(prepared.parsed.name, "Starkes Deo (DM)");
  assert.equal(prepared.forcedCategoryId, "retailer-user");
  assert.equal(prepared.sourceTag, "retailer:dm");
});

test("legacy automatic DM Alexa article migrates to the shared retailer category and retries its missing icon", () => {
  const { initialState, migrateState } = require("./server");
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.34";
  const list = legacy.lists[0];
  list.categories.push({ id: "retailer-user", name: "DM/Rossmann/Müller", icon: "📦", sort: 99, description: "Artikel für diese drei Läden" });
  const product = { id: "product-starkes-deo-dm", key: "starkes deo d m", name: "Starkes deo d. m.", categoryId: "baking", icon: "🌾", aliases: ["starkes deo d m"], favorite: false, useCount: 1, classificationSource: "automatic", imageSource: "pending", iconEditStatus: "unprocessed" };
  const entry = { id: "entry-starkes-deo-dm", productId: product.id, productKey: product.key, name: product.name, original: "Starkes deo D. M.", quantity: null, categoryId: "baking", createdAt: "2026-09-12T11:54:00Z" };
  list.products.push(product); list.entries.push(entry); legacy.products = list.products; legacy.entries = list.entries;
  const migrated = migrateState(legacy);
  const migratedProduct = migrated.lists[0].products.find((item) => item.id === product.id);
  const migratedEntry = migrated.lists[0].entries.find((item) => item.id === entry.id);
  assert.equal(migratedProduct.name, "Starkes Deo (DM)");
  assert.equal(migratedProduct.categoryId, "retailer-user");
  assert.equal(migratedProduct.sourceTag, "retailer:dm");
  assert.equal(migratedProduct.classificationSource, "rule");
  assert.equal(migratedProduct.imageSource, "pending");
  assert.equal(migratedEntry.name, "Starkes Deo (DM)");
  assert.equal(migratedEntry.categoryId, "retailer-user");
  assert.equal(migratedEntry.original, "Starkes deo D. M.");
});

test("Alexa integration import runs the full new-product pipeline instead of classification only", () => {
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const start = source.indexOf('if (pathname === "/api/integration/import"');
  const end = source.indexOf('if (pathname === "/api/offline-sync"', start);
  const route = source.slice(start, end);
  assert.match(route, /void processCreatedProduct\(result, target\.id\)/);
  assert.match(route, /processCreatedProduct\(result, target\.id\)/);
  assert.doesNotMatch(route, /void classifyResult\(result, target\.id\)/);
});

test("REWE names are cleaned, routed into an automatic REWE category and kept separate from ordinary products", () => {
  const { initialState, stripReweTag, prepareParsedForList } = require("./server");
  assert.deepEqual(stripReweTag("Gouda REWE"), { tagged: true, rawName: "Gouda REWE", name: "Gouda" });
  assert.deepEqual(stripReweTag("REWE Milch"), { tagged: true, rawName: "REWE Milch", name: "Milch" });
  assert.deepEqual(stripReweTag("Brot (REWE)"), { tagged: true, rawName: "Brot (REWE)", name: "Brot" });
  const list = structuredClone(initialState().lists[0]);
  assert.equal(list.categories.some((category) => category.name === "REWE"), false);
  const prepared = prepareParsedForList(parseItemInput("Gouda REWE"), list);
  const category = list.categories.find((item) => item.name === "REWE");
  assert.ok(category);
  assert.equal(prepared.parsed.name, "Gouda");
  assert.equal(prepared.lookupName, "Gouda REWE");
  assert.equal(prepared.keyName, "Gouda REWE");
  assert.equal(prepared.forcedCategoryId, category.id);
  assert.equal(prepared.sourceTag, "rewe");
});

test("legacy automatic REWE articles migrate into REWE while the original Alexa wording stays recoverable", () => {
  const { initialState, migrateState } = require("./server");
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.34";
  const list = legacy.lists[0];
  const product = { id: "product-gouda-rewe", key: "gouda rewe", name: "Gouda REWE", categoryId: "cheese", icon: "🧀", aliases: ["gouda rewe"], favorite: false, useCount: 1, classificationSource: "automatic", imageSource: "catalog", imageKey: "gouda_wheel" };
  const entry = { id: "entry-gouda-rewe", productId: product.id, productKey: product.key, name: product.name, original: "Gouda REWE", quantity: null, categoryId: "cheese", createdAt: "2026-09-12T15:00:00Z" };
  list.products.push(product); list.entries.push(entry); legacy.products = list.products; legacy.entries = list.entries;
  const migrated = migrateState(legacy);
  const migratedList = migrated.lists[0];
  const category = migratedList.categories.find((item) => item.name === "REWE");
  const migratedProduct = migratedList.products.find((item) => item.id === product.id);
  const migratedEntry = migratedList.entries.find((item) => item.id === entry.id);
  assert.ok(category);
  assert.equal(category.reweIconVersion, 1);
  assert.equal(migratedProduct.name, "Gouda");
  assert.equal(migratedProduct.key, "gouda rewe");
  assert.equal(migratedProduct.categoryId, category.id);
  assert.equal(migratedProduct.sourceTag, "rewe");
  assert.equal(migratedProduct.classificationSource, "rule");
  assert.ok(migratedProduct.aliases.includes("gouda rewe"));
  assert.equal(migratedEntry.name, "Gouda");
  assert.equal(migratedEntry.categoryId, category.id);
  assert.equal(migratedEntry.original, "Gouda REWE");
});

test("REWE ships with its own local category icon and edited REWE entries keep their store-specific product", () => {
  const { categoryImageKey } = require("./image-assets");
  const image = path.join(__dirname, "assets", "category-images", "rewe.webp");
  assert.equal(fs.existsSync(image), true);
  assert.equal(fs.statSync(image).size > 1000, true);
  assert.equal(categoryImageKey({ name: "REWE" }), "rewe");
  const source = fs.readFileSync(path.join(__dirname, "server.js"), "utf8");
  const start = source.indexOf('if (pathname.startsWith("/api/items/") && req.method === "PATCH")');
  const end = source.indexOf('if (pathname === "/api/import"', start);
  const route = source.slice(start, end);
  assert.match(route, /previousProduct\?\.sourceTag === "rewe"/);
  assert.match(route, /isReweCategoryName\(requestedCategory\?\.name\)/);
  assert.match(route, /sameStoreSpecificProduct/);
});


test("store-specific products only reuse images from already processed source articles", () => {
  const { repairStoreSpecificImageReuse } = require("./server");
  const imageDir = path.join(testDataDir, "product-images");
  fs.mkdirSync(imageDir, { recursive: true });
  const unprocessedSource = { id: "product-tofu", key: "tofu", name: "Tofu", categoryId: "vegetarian", aliases: ["tofu"], imageSource: "catalog", iconEditStatus: "unprocessed" };
  const storeProduct = { id: "product-tofu-rewe", key: "tofu rewe", name: "Tofu", categoryId: "rewe", aliases: ["tofu rewe"], sourceTag: "rewe", imageSource: "catalog", imageKey: "tofu", iconEditStatus: "unprocessed" };
  const list = { products: [unprocessedSource, storeProduct], categories: [{ id: "rewe", name: "REWE" }] };
  assert.equal(repairStoreSpecificImageReuse(list), true);
  assert.equal(storeProduct.imageSource, "pending");
  assert.equal(storeProduct.imageInheritedFromName, undefined);

  const sourceFile = path.join(imageDir, "product-tofu-test.png");
  fs.writeFileSync(sourceFile, Buffer.from("processed-image"));
  unprocessedSource.generatedImage = "generated-product-images/product-tofu-test.png";
  unprocessedSource.imageSource = "gemini";
  unprocessedSource.iconEditStatus = "processed";
  storeProduct.imageSource = "catalog";
  storeProduct.iconEditStatus = "unprocessed";
  assert.equal(repairStoreSpecificImageReuse(list), true);
  assert.equal(storeProduct.imageSource, "inherited");
  assert.equal(storeProduct.iconEditStatus, "processed");
  assert.equal(storeProduct.imageInheritedFromProductId, "product-tofu");
  assert.equal(storeProduct.imageInheritedFromName, "Tofu");
  const inheritedFile = path.join(testDataDir, storeProduct.generatedImage.replace(/^generated-product-images\//, "product-images/"));
  assert.equal(fs.existsSync(inheritedFile), true);
  assert.notEqual(inheritedFile, sourceFile);
});

test("processed product images are reused across category variants without another AI run", () => {
  const { repairStoreSpecificImageReuse, needsGeminiClassification } = require("./server");
  const imageDir = path.join(testDataDir, "product-images");
  fs.mkdirSync(imageDir, { recursive: true });
  const sourceFile = path.join(imageDir, "product-sahne-firma-a.png");
  fs.writeFileSync(sourceFile, Buffer.from("processed-category-image"));
  const source = { id: "product-sahne-a", key: "sahne category a", name: "Sahne", categoryId: "cat-a", aliases: ["sahne"], sourceTag: "category:cat-a", generatedImage: "generated-product-images/product-sahne-firma-a.png", imageSource: "gemini", iconEditStatus: "processed", visualBase: "carton", visualMotif: "milk" };
  const target = { id: "product-sahne-b", key: "sahne category b", name: "Sahne", categoryId: "cat-b", aliases: ["sahne"], sourceTag: "category:cat-b", imageSource: "pending", iconEditStatus: "unprocessed" };
  const list = { products: [source, target], categories: [{ id: "cat-a", name: "Privat" }, { id: "cat-b", name: "Firma" }] };
  assert.equal(repairStoreSpecificImageReuse(list), true);
  assert.equal(target.imageSource, "inherited");
  assert.equal(target.iconEditStatus, "processed");
  assert.equal(target.imageInheritedFromProductId, source.id);
  assert.equal(needsGeminiClassification(target, list, true), false);
});

test("retailer image inheritance keeps the clean base article name", () => {
  const { extractRetailerTag, prepareParsedForList, initialState } = require("./server");
  const tagged = extractRetailerTag("Spülmaschinentabs Rossmann");
  assert.equal(tagged.baseName, "Spülmaschinentabs");
  const list = structuredClone(initialState().lists[0]);
  list.categories.push({ id: "retailer", name: "DM/Rossmann/Müller", sort: 99 });
  const prepared = prepareParsedForList(parseItemInput("Spülmaschinentabs Rossmann"), list);
  assert.equal(prepared.inheritFromName, "Spülmaschinentabs");
  assert.equal(prepared.parsed.name, "Spülmaschinentabs (Rossmann)");
});

test("article catalog includes direct search and inherited-image provenance", () => {
  const { page } = require("./server");
  const html = page();
  assert.match(html, /id="catalog-search"/);
  assert.match(html, /placeholder="Artikel suchen …"/);
  assert.match(html, /oninput="renderCatalogCategories\(\)"/);
  assert.match(html, /Bild übernommen aus/);
  assert.match(html, /Übernommen von/);
});

test("mobile chrome is compact and double-tap browser zoom is disabled without removing card double-tap", () => {
  const { page } = require("./server");
  const html = page();
  assert.match(html, /touch-action:manipulation/);
  assert.match(html, /\.content-head\{padding:calc\(0px \+ env\(safe-area-inset-top\)\) 4px 1px/);
  assert.match(html, /\.nav\{padding-bottom:calc\(4px \+ env\(safe-area-inset-bottom\)\)\}/);
  const clickStart = html.indexOf("function cardClick");
  const clickEnd = html.indexOf("function createCategory", clickStart);
  assert.match(html.slice(clickStart, clickEnd), /checkItem\(ev,id\)/);
});


test("category management is mobile-safe and settings expose current-list search", () => {
  const { page } = require("./server");
  const html = page();
  assert.match(html, /category-row-actions/);
  assert.match(html, /grid-template-columns:44px minmax\(0,1fr\)/);
  assert.match(html, /overflow-x:hidden/);
  assert.match(html, /Liste durchsuchen/);
  assert.match(html, /function searchCurrentList\(\)/);
  assert.match(html, /function jumpToListEntry\(/);
});

test("shopping list visually separates quantity size note and shop categories", () => {
  const { page } = require("./server");
  const html = page();
  assert.match(html, /class="shop-badge">Einkaufsort/);
  assert.match(html, /\.qty\{background:#e5f1e8/);
  assert.match(html, /\.product-detail\{padding:4px 8px/);
  assert.match(html, /\.entry-note\{background:#f4efe7/);
  assert.match(html, /long-category/);
});


test("offline boot does not wait for service worker and mobile nav uses stable svg layout", () => {
  const source = fs.readFileSync(path.join(__dirname,"server.js"),"utf8");
  assert.match(source,/void registerOfflineWorker\(\);const offlineInit=initOfflineStorage\(\);/);
  assert.doesNotMatch(source,/await initOfflineStorage\(\);const cached=/);
  assert.match(source,/offline-images-ready/);
  assert.match(source,/class="nav-icon"/);
  assert.match(source,/height:calc\(62px \+ env\(safe-area-inset-bottom\)\)/);
  assert.doesNotMatch(source,/Offline-Speicher wird vorbereitet/);
  assert.match(source,/document\.baseURI/);
  assert.match(source,/IndexedDB reagiert nicht/);
});

test("new products use Gemini despite generic word rules but keep protected rules", () => {
  const { needsGeminiClassification } = require("./server");
  const list = { categories: [{ id: "produce" }, { id: "sweets" }, { id: "household" }, { id: "other" }] };
  assert.equal(needsGeminiClassification({ classificationSource: "rule", categoryId: "produce", imageSource: "pending", name: "Birnenkekse" }, list, true), true);
  assert.equal(needsGeminiClassification({ classificationSource: "learned", categoryId: "sweets", imageSource: "pending", name: "Birnenkekse" }, list, true), false);
  assert.equal(needsGeminiClassification({ classificationSource: "rule", categoryId: "household", imageSource: "pending", name: "Zip-Tiefkühlbeutel" }, list, true), false);
  assert.equal(needsGeminiClassification({ classificationSource: "rule", categoryId: "produce", imageSource: "pending", name: "Gouda", sourceTag: "rewe" }, list, true), false);
});

test("shopping gestures guard against Safari zoom and accidental long press while scrolling", () => {
  const html = require("./server").page();
  assert.match(html, /\.card\{touch-action:manipulation/);
  assert.match(html, /ondblclick="event\.preventDefault\(\);return false"/);
  assert.match(html, /class="check"[^>]+onpointerdown="event\.stopPropagation\(\)"/);
  assert.match(html, /onpointermove="gestureMove\(event/);
  assert.match(html, /Math\.hypot\(dx,dy\)>10\)\{gestureMoved=true;holdEnd\(\)\}/);
  assert.match(html, /openEdit\(id\)\},800\)/);
  assert.match(html, /\.add input,\.sheet input,\.sheet select,\.sheet textarea\{font-size:16px\}/);
  assert.match(html, />Zuletzt<\/span>/);
  assert.match(html, /Zuletzt durchsuchen/);
  assert.doesNotMatch(html, /Favoriten/);
  assert.doesNotMatch(html, /Artikel wiederherstellen/);
  assert.doesNotMatch(html, /showSnack\([^\n]*,true\)/);
});

test("editors are compact, category-first and use clear status colors", () => {
  const html = require("./server").page();
  const edit = html.slice(html.indexOf("function openEdit"), html.indexOf("function currentEntryEditorBody"));
  assert.ok(edit.indexOf("<label>Kategorie</label>") < edit.indexOf("<label>Name</label>"));
  assert.match(edit, /saveEditAndOpenMaster/);
  assert.doesNotMatch(edit, /Hier änderst du den aktuellen Einkaufslisteneintrag/);
  assert.doesNotMatch(edit, /Nur die tatsächliche Einkaufsmenge/);
  assert.doesNotMatch(edit, /Beschreibt die Größe oder Variante/);
  assert.doesNotMatch(edit, /Freier Hinweis nur für diesen Einkaufslisteneintrag/);
  assert.match(html, /catalog-status '\+statusClass/);
  assert.match(html, /iconEditStatus==='processed'\?'Bearbeitet':'Unbearbeitet'/);
  assert.match(html, /\.catalog-status\.unprocessed\{background:#fde7e7/);
  assert.match(html, /\.catalog-status\.processed[^}]*background:#e4f1e8/);
  assert.match(html, /title="Speichern" aria-label="Speichern"/);
});

test("connection status wording is only Online or Offline with queued-change count", () => {
  const html = require("./server").page();
  const start = html.indexOf("function updateOfflineStatus");
  const end = html.indexOf("async function persistOfflineView", start);
  const source = html.slice(start, end);
  assert.match(source, /text='Online'/);
  assert.match(source, /text='Offline'/);
  assert.match(source, /offene Änderung/);
  assert.doesNotMatch(source, /Offline bereit|Synchronisiert|Synchronisiere/);
  assert.match(html, /\.offline-status\.offline\{background:#fde8e8/);
  assert.match(html, /\.offline-status\.online\{background:#e6f1ea/);
});

test("0.3.44 migration repairs legacy Alexa Firma products such as Hafermilch 1x Firma", () => {
  const { initialState, migrateState } = require("./server");
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.44";
  const list = legacy.lists[0];
  const firma = { id: "firma-user", name: "Firma", icon: "🏢", sort: 99, description: "Firmenartikel" };
  list.categories.push(firma);
  const malformed = {
    id: "product-hafermilch-firma-legacy",
    key: "hafermilch 1x firma",
    name: "Hafermilch 1x Firma",
    categoryId: "milk",
    icon: "🥛",
    aliases: ["hafermilch 1x firma"],
    favorite: false,
    useCount: 1,
    classificationSource: "automatic",
    imageSource: "catalog",
  };
  const entry = {
    id: "entry-hafermilch-firma-legacy",
    productId: malformed.id,
    productKey: malformed.key,
    name: malformed.name,
    original: malformed.name,
    quantity: null,
    categoryId: "milk",
    createdAt: "2026-09-16T16:00:00Z",
  };
  list.products.push(malformed);
  list.entries.push(entry);
  legacy.products = list.products;
  legacy.entries = list.entries;
  legacy.categories = list.categories;

  const migrated = migrateState(legacy);
  const migratedList = migrated.lists[0];
  const removedMalformed = migratedList.products.find((item) => item.id === malformed.id);
  const ordinary = migratedList.products.find((item) => item.name === "Hafermilch" && !item.sourceTag);
  const firmaVariant = migratedList.products.find((item) => item.name === "Hafermilch" && item.categoryId === firma.id && /^category:/.test(String(item.sourceTag || "")));
  const migratedEntry = migratedList.entries.find((item) => item.id === entry.id);
  assert.equal(removedMalformed, undefined);
  assert.ok(ordinary);
  assert.ok(firmaVariant);
  assert.notEqual(firmaVariant.id, ordinary.id);
  assert.equal(migratedEntry.productId, firmaVariant.id);
  assert.equal(migratedEntry.name, "Hafermilch");
  assert.equal(migratedEntry.categoryId, firma.id);
  assert.deepEqual(migratedEntry.quantity, { value: 1, unit: "stück" });
});


test("0.3.51 starts migration with inherited product images before server initialization", () => {
  const tempDir = fs.mkdtempSync(path.join(os.tmpdir(), "einkaufsliste-start-migration-image-"));
  const dataFile = path.join(tempDir, "shopping-list.json");
  const backupDir = path.join(tempDir, "backups");
  const productImageDir = path.join(tempDir, "product-images");
  fs.mkdirSync(productImageDir, { recursive: true });

  const { initialState } = require("./server");
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.48";
  const list = legacy.lists[0];
  const firma = { id: "firma-start-test", name: "Firma (extra Rechnung)", icon: "🏢", sort: 99, description: "Firmenartikel" };
  list.categories.push(firma);
  const butter = list.products.find((item) => item.name === "Butter" && !item.sourceTag);
  assert.ok(butter);
  const sourceFile = "butter-existing.webp";
  fs.writeFileSync(path.join(productImageDir, sourceFile), Buffer.from([0x52,0x49,0x46,0x46,0x00,0x00,0x00,0x00,0x57,0x45,0x42,0x50]));
  butter.generatedImage = `generated-product-images/${sourceFile}`;
  butter.imageSource = "upload";
  butter.iconEditStatus = "processed";
  butter.isCustomImage = true;

  const malformed = {
    id: "product-butter-start-corrupt", key: "butter 10x firma", name: "Butter 10x Firma",
    categoryId: "milk", icon: "🧈", aliases: ["butter 10x firma"], favorite: false, useCount: 1,
    classificationSource: "automatic", imageSource: "pending", iconEditStatus: "unprocessed",
  };
  list.products.push(malformed);
  list.entries.push({
    id: "entry-butter-start-corrupt", productId: malformed.id, productKey: malformed.key, name: malformed.name,
    original: malformed.name, quantity: null, categoryId: "milk", createdAt: "2026-09-16T20:00:00Z",
  });
  legacy.products = list.products; legacy.entries = list.entries; legacy.categories = list.categories;
  fs.writeFileSync(dataFile, JSON.stringify(legacy), "utf8");

  const script = `const s=require('./server').loadState(); const l=s.lists[0]; const p=l.products.find(x=>x.categoryId==='firma-start-test'&&x.name==='Butter'); process.stdout.write(JSON.stringify({version:s.version,name:p?.name,generatedImage:p?.generatedImage,exists:p?.generatedImage?require('node:fs').existsSync(require('node:path').join(process.env.DATA_DIR,p.generatedImage.replace(/^generated-product-images\\//,'product-images/'))):false}));`;
  const output = execFileSync(process.execPath, ["-e", script], { cwd: __dirname, env: { ...process.env, DATA_DIR: tempDir, DATA_FILE: dataFile, BACKUP_DIR: backupDir }, encoding: "utf8" });
  const result = JSON.parse(output.split("\n").at(-1));
  assert.equal(result.version, "0.3.68");
  assert.equal(result.name, "Butter");
  assert.match(result.generatedImage || "", /^generated-product-images\//);
  assert.equal(result.exists, true);
  fs.rmSync(tempDir, { recursive: true, force: true });
});

test("0.3.51 migration also repairs the specific manual-looking Butter 10x Firma corruption", () => {
  const { initialState, migrateState } = require("./server");
  const legacy = structuredClone(initialState());
  legacy.version = "0.3.46";
  const list = legacy.lists[0];
  const firma = { id: "firma-user-0347", name: "Firma", icon: "🏢", sort: 99, description: "Firmenartikel" };
  list.categories.push(firma);
  const malformed = {
    id: "product-butter-10x-firma-legacy",
    key: "butter 10x firma",
    name: "Butter 10x Firma",
    categoryId: "milk",
    icon: "🥛",
    aliases: ["butter 10x firma"],
    favorite: false,
    useCount: 1,
    classificationSource: "manual",
    imageSource: "gemini",
    iconEditStatus: "processed",
  };
  const entry = {
    id: "entry-butter-10x-firma-legacy",
    productId: malformed.id,
    productKey: malformed.key,
    name: malformed.name,
    original: malformed.name,
    quantity: null,
    categoryId: "milk",
    createdAt: "2026-09-16T18:00:00Z",
  };
  list.products.push(malformed);
  list.entries.push(entry);
  legacy.products = list.products;
  legacy.entries = list.entries;
  legacy.categories = list.categories;

  const migrated = migrateState(legacy);
  const migratedList = migrated.lists[0];
  const removedMalformed = migratedList.products.find((item) => item.id === malformed.id);
  const ordinary = migratedList.products.find((item) => item.name === "Butter" && !item.sourceTag);
  const firmaVariant = migratedList.products.find((item) => item.name === "Butter" && item.categoryId === firma.id && /^category:/.test(String(item.sourceTag || "")));
  const migratedEntry = migratedList.entries.find((item) => item.id === entry.id);
  assert.equal(removedMalformed, undefined);
  assert.ok(ordinary);
  assert.equal(ordinary.categoryId, "milk");
  assert.ok(firmaVariant);
  assert.notEqual(firmaVariant.id, ordinary.id);
  assert.equal(migratedEntry.productId, firmaVariant.id);
  assert.equal(migratedEntry.name, "Butter");
  assert.equal(migratedEntry.categoryId, firma.id);
  assert.deepEqual(migratedEntry.quantity, { value: 10, unit: "stück" });
});
