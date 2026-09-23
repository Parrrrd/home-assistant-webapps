const http = require("node:http");
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const { normalizeText, firstUpper, parseItemInput, duplicateKey } = require("./core");
const { VISUAL_BASES, VISUAL_MOTIFS, BASE_IDS, MOTIF_IDS, inferVisual, sanitizeVisual, categoryVisualKind } = require("./visual");
const { imageKeyForProduct, categoryImageKey } = require("./image-assets");
const { createAppleRemindersSync } = require("./apple-reminders-sync");
const { createLocalCaldavSync } = require("./local-caldav-sync");
const extraCatalogProducts = require("./catalog-extra");
const processedIcons = require("./processed-icons.json");

const PORT = Number(process.env.PORT || 8156);
const DATA_DIR = process.env.DATA_DIR || "/data";
const DATA_FILE = process.env.DATA_FILE || path.join(DATA_DIR, "shopping-list.json");
const BACKUP_DIR = process.env.BACKUP_DIR || path.join(DATA_DIR, "backups");
const GENERATED_IMAGE_DIR = path.join(DATA_DIR, "product-images");
const GENERATED_CATEGORY_IMAGE_DIR = path.join(DATA_DIR, "category-images");
const DAILY_BACKUP_INTERVAL_MS = 24 * 60 * 60 * 1000;
const VERSION = "0.3.61";
const UNDO_TTL_MS = 30000;
const GEMINI_IMAGE_MODEL = "gemini-3.1-flash-image";
const GEMINI_IMAGE_INPUT_USD_PER_M = 0.50;
const GEMINI_IMAGE_TEXT_OUTPUT_USD_PER_M = 3.00;
const GEMINI_IMAGE_OUTPUT_USD_PER_M = 60.00;
const GEMINI_COST_ACCOUNTING_VERSION = 2;
const GEMINI_COST_TRACKING_SINCE = "0.3.29";

const CATEGORY_DESCRIPTIONS = {
  produce: "Frisches Obst, Gemüse, Salate, Kräuter und andere lose Frischware.",
  vegetarian: "Vegetarische und vegane Ersatzprodukte, Tofu, Hummus, Falafel und ähnliche fleischfreie Produkte.",
  bakery_fitness: "Brot, Brötchen, Toast, Backwaren sowie Fitness- und Proteinprodukte wie Riegel oder Haferflocken.",
  baking: "Mehl, Zucker, Backpulver, Gewürz- und Backzutaten, Nüsse und Zutaten zum Kochen oder Backen.",
  milk: "Gekühlte Milchprodukte wie Joghurt, Quark, Sahne, Frischmilch und ähnliche Kühlware.",
  canned: "Konserven, Dosen, Gläser und haltbare Lebensmittel wie Dosentomaten, Bohnen oder Thunfisch.",
  pasta_rice: "Nudeln, Reis, Couscous, Kartoffel- und Getreidebeilagen sowie vergleichbare trockene Beilagen.",
  oils_sauces: "Speiseöle, Essig, Ketchup, Senf, Mayonnaise, Pesto, Saucen und Dressings.",
  cheese: "Käse und käseähnliche gekühlte Produkte wie Gouda, Feta, Mozzarella oder Frischkäse.",
  household: "Haushaltsverbrauchs- und Verpackungsartikel wie Alufolie, Frischhaltefolie, Backpapier, Müll- und Gefrierbeutel sowie kleine Haushalts- oder Elektroartikel. Keine Putz-, Wasch- oder Körperpflegemittel.",
  milk_uncooled: "Ungekühlte Milch- und Milchersatzprodukte, H-Milch, Kondensmilch, Kaffeesahne und Eier.",
  ready_chilled: "Gekühlte Fertigprodukte wie Gnocchi, Tortellini, Maultaschen, frische Pizza und ähnliche Convenience-Produkte.",
  frozen: "Tiefgekühlte Lebensmittel außer Speiseeis, zum Beispiel TK-Gemüse, Pommes, Fischstäbchen oder TK-Pizza.",
  meat: "Fleisch, Wurst, Aufschnitt, Geflügel und andere SB-Fleischprodukte.",
  drinks: "Alkoholfreie und alkoholische Getränke, Wasser, Säfte, Kaffee, Tee und Getränkekisten oder -flaschen.",
  sweets: "Süßwaren, Schokolade, Kekse, Chips, Bonbons, Brotaufstriche und Snacks.",
  drugstore: "Putz- und Reinigungsmittel, Waschmittel, Spülmittel sowie Hygiene-, Pflege- und Drogerieartikel. Keine Folien, Beutel oder sonstigen Verpackungsartikel.",
  ice_cream: "Speiseeis, Sorbet, Wassereis, Eiswürfel und andere TK-Eis-Produkte.",
  other: "Artikel, die keiner der beschriebenen Kategorien eindeutig zugeordnet werden können.",
};

const categorySeed = [
  ["produce", "Obst und Gemüse", "🥒"], ["vegetarian", "Vegetarische Produkte", "🌱"],
  ["bakery_fitness", "Backwaren / Fitness-Produkte", "🍞"], ["baking", "Backzutaten", "🌾"],
  ["milk", "Milchprodukte", "🥛"], ["canned", "Konserven", "🥫"], ["pasta_rice", "Nudeln, Reis & Beilagen", "🍚"], ["oils_sauces", "Öle und Saucen", "🫒"],
  ["cheese", "Käseprodukte", "🧀"], ["household", "Haushalt-Produkte", "🧽"],
  ["milk_uncooled", "Milchprodukte (ungekühlt)", "🥚"], ["ready_chilled", "Fertigprodukte (gekühlt)", "🍽️"],
  ["frozen", "TK-Produkte", "❄️"], ["meat", "Fleisch/Wurst (SB)", "🥩"], ["drinks", "Getränke", "🥤"],
  ["sweets", "Süßwaren", "🍫"], ["drugstore", "Drogerie", "🧴"], ["ice_cream", "TK-Eis", "🍦"],
  ["other", "Sonstiges", "📦"],
].map(([id, name, icon], index) => ({ id, name, icon, description: CATEGORY_DESCRIPTIONS[id] || "", sort: index }));

const catalogExtras = [
  ["apfel", "Apfel", "produce", "🍎", ["apfel", "äpfel"]], ["birne", "Birne", "produce", "🍐", ["birne", "birnen"]],
  ["orange", "Orange", "produce", "🍊", ["orange", "orangen"]], ["zitrone", "Zitrone", "produce", "🍋", ["zitrone", "zitronen"]],
  ["erdbeeren", "Erdbeeren", "produce", "🍓", ["erdbeere", "erdbeeren"]], ["trauben", "Trauben", "produce", "🍇", ["traube", "trauben"]],
  ["kirschen", "Kirschen", "produce", "🍒", ["kirsche", "kirschen"]], ["avocado", "Avocado", "produce", "🥑", ["avocado"]],
  ["paprika", "Paprika", "produce", "🫑", ["paprika"]], ["zucchini", "Zucchini", "produce", "🥒", ["zucchini"]],
  ["brokkoli", "Brokkoli", "produce", "🥦", ["brokkoli"]], ["salat", "Salat", "produce", "🥬", ["salat"]],
  ["zwiebeln", "Zwiebeln", "produce", "🧅", ["zwiebel", "zwiebeln"]], ["knoblauch", "Knoblauch", "produce", "🧄", ["knoblauch"]],
  ["möhren", "Möhren", "produce", "🥕", ["möhre", "möhren", "karotte", "karotten"]], ["champignons", "Champignons", "produce", "🍄", ["champignon", "champignons"]],
  ["tofu", "Tofu", "vegetarian", "🌱", ["tofu"]], ["hummus", "Hummus", "vegetarian", "🫘", ["hummus"]],
  ["vegetarische-bratwurst", "Vegetarische Bratwurst", "vegetarian", "🌱", ["vegetarische bratwurst", "vegane bratwurst", "veggie bratwurst"]],
  ["vegetarische-schnitzel", "Vegetarische Schnitzel", "vegetarian", "🌱", ["vegetarisches schnitzel", "vegetarische schnitzel", "vegane schnitzel"]],
  ["vegetarische-salami", "Vegetarische Salami", "vegetarian", "🌱", ["vegetarische salami", "vegane salami"]],
  ["vegetarische-wuerstchen", "Vegetarische Würstchen", "vegetarian", "🌱", ["vegetarische würstchen", "vegane würstchen", "veggie würstchen"]],
  ["veganes-hack", "Veganes Hack", "vegetarian", "🌱", ["veganes hack", "veggie hack"]],
  ["falafel", "Falafel", "vegetarian", "🧆", ["falafel"]], ["linsen", "Linsen", "vegetarian", "🫘", ["linse", "linsen"]],
  ["toast", "Toast", "bakery_fitness", "🍞", ["toast"]], ["broetchen", "Brötchen", "bakery_fitness", "🥖", ["brötchen", "broetchen"]],
  ["baguette", "Baguette", "bakery_fitness", "🥖", ["baguette"]], ["croissant", "Croissant", "bakery_fitness", "🥐", ["croissant"]],
  ["proteinriegel", "Proteinriegel", "bakery_fitness", "💪", ["proteinriegel"]], ["backpulver", "Backpulver", "baking", "🧁", ["backpulver"]],
  ["vanillezucker", "Vanillezucker", "baking", "🧁", ["vanillezucker"]], ["kakao", "Kakao", "baking", "🍫", ["kakao"]],
  ["speisestaerke", "Speisestärke", "baking", "🫙", ["speisestärke", "speisestaerke"]], ["puderzucker", "Puderzucker", "baking", "🍚", ["puderzucker"]],
  ["joghurt", "Joghurt", "milk", "🥣", ["joghurt", "jogurt"]], ["skyr", "Skyr", "milk", "🥣", ["skyr"]],
  ["quark", "Quark", "milk", "🥣", ["quark"]], ["creme-fraiche", "Crème fraîche", "milk", "🥛", ["crème fraîche", "creme fraiche"]],
  ["dosentomaten", "Dosentomaten", "canned", "🥫", ["dosentomaten"]], ["tomatenmark", "Tomatenmark", "canned", "🍅", ["tomatenmark"]],
  ["mais-konserve", "Mais", "canned", "🌽", ["mais", "mais dose"]], ["bohnen-dose", "Bohnen", "canned", "🥫", ["bohnen", "bohnen dose"]],
  ["erbsen-dose", "Erbsen", "canned", "🫛", ["erbsen", "erbsen dose"]], ["thunfisch", "Thunfisch", "canned", "🐟", ["thunfisch"]],
  ["ravioli", "Ravioli", "canned", "🥫", ["ravioli"]], ["ketchup", "Ketchup", "oils_sauces", "🍅", ["ketchup"]],
  ["mayonnaise", "Mayonnaise", "oils_sauces", "🫙", ["mayonnaise", "mayo"]], ["senf", "Senf", "oils_sauces", "🟡", ["senf"]],
  ["pesto", "Pesto", "oils_sauces", "🌿", ["pesto"]], ["olivenoel", "Olivenöl", "oils_sauces", "🫒", ["olivenöl", "olivenoel"]],
  ["essig", "Essig", "oils_sauces", "🫙", ["essig"]], ["sojasauce", "Sojasauce", "oils_sauces", "🫙", ["sojasauce", "sojasoße"]],
  ["gouda", "Gouda", "cheese", "🧀", ["gouda"]], ["mozzarella", "Mozzarella", "cheese", "🧀", ["mozzarella"]],
  ["parmesan", "Parmesan", "cheese", "🧀", ["parmesan"]], ["feta", "Feta", "cheese", "🧀", ["feta"]],
  ["frischkaese", "Frischkäse", "cheese", "🧀", ["frischkäse", "frischkaese"]], ["muellbeutel", "Müllbeutel", "household", "🗑️", ["müllbeutel", "muellbeutel"]],
  ["alufolie", "Alufolie", "household", "🥡", ["alufolie"]], ["backpapier", "Backpapier", "household", "📄", ["backpapier"]],
  ["kuechenrolle", "Küchenrolle", "household", "🧻", ["küchenrolle", "kuechenrolle"]], ["allzweckreiniger", "Allzweckreiniger", "drugstore", "🧴", ["allzweckreiniger", "putzmittel", "reiniger"]],
  ["spuelschwamm", "Spülschwamm", "drugstore", "🧽", ["spülschwamm", "spuelschwamm"]], ["h-milch", "H-Milch", "milk_uncooled", "🥛", ["h-milch", "h milch"]],
  ["kondensmilch", "Kondensmilch", "milk_uncooled", "🥛", ["kondensmilch"]], ["kaffeesahne", "Kaffeesahne", "milk_uncooled", "☕", ["kaffeesahne"]],
  ["gnocchi", "Gnocchi", "ready_chilled", "🥔", ["gnocchi"]], ["tortellini", "Tortellini", "ready_chilled", "🍝", ["tortellini"]],
  ["maultaschen", "Maultaschen", "ready_chilled", "🍽️", ["maultaschen"]], ["fertigpizza", "Fertigpizza", "ready_chilled", "🍕", ["fertigpizza"]],
  ["pommes", "Pommes", "frozen", "🍟", ["pommes"]], ["fischstaebchen", "Fischstäbchen", "frozen", "🐟", ["fischstäbchen", "fischstaebchen"]],
  ["tk-gemuese", "TK-Gemüse", "frozen", "🥦", ["tk gemüse", "tk gemuese", "tiefkühlgemüse"]], ["tk-pizza", "TK-Pizza", "frozen", "🍕", ["tk pizza", "tk-pizza"]],
  ["spinat", "Spinat", "frozen", "🥬", ["spinat"]], ["schinken", "Schinken", "meat", "🥩", ["schinken"]],
  ["salami", "Salami", "meat", "🥩", ["salami"]], ["wurst", "Wurst", "meat", "🌭", ["wurst"]],
  ["hackfleisch", "Hackfleisch", "meat", "🥩", ["hackfleisch"]], ["haehnchen", "Hähnchen", "meat", "🍗", ["hähnchen", "haehnchen", "hühnchen"]],
  ["steak", "Steak", "meat", "🥩", ["steak"]], ["bacon", "Bacon", "meat", "🥓", ["bacon"]], ["saft", "Saft", "drinks", "🧃", ["saft"]],
  ["cola", "Cola", "drinks", "🥤", ["cola"]], ["limonade", "Limonade", "drinks", "🥤", ["limonade", "limo"]],
  ["bier", "Bier", "drinks", "🍺", ["bier"]], ["tee", "Tee", "drinks", "🍵", ["tee"]], ["energy", "Energy-Drink", "drinks", "⚡", ["energy", "energydrink"]],
  ["schokolade", "Schokolade", "sweets", "🍫", ["schokolade"]], ["gummibaerchen", "Gummibärchen", "sweets", "🍬", ["gummibärchen", "gummibaerchen"]],
  ["kekse", "Kekse", "sweets", "🍪", ["keks", "kekse"]], ["chips", "Chips", "sweets", "🥔", ["chips"]], ["bonbons", "Bonbons", "sweets", "🍬", ["bonbon", "bonbons"]],
  ["shampoo", "Shampoo", "drugstore", "🧴", ["shampoo"]], ["duschgel", "Duschgel", "drugstore", "🚿", ["duschgel"]],
  ["zahnpasta", "Zahnpasta", "drugstore", "🪥", ["zahnpasta"]], ["zahnbuerste", "Zahnbürste", "drugstore", "🪥", ["zahnbürste", "zahnbuerste"]],
  ["deo", "Deo", "drugstore", "🧴", ["deo"]], ["rasierer", "Rasierer", "drugstore", "🪒", ["rasierer"]],
  ["taschentuecher", "Taschentücher", "drugstore", "🤧", ["taschentücher", "taschentuecher"]], ["windeln", "Windeln", "drugstore", "👶", ["windeln"]],
  ["eiscreme", "Eiscreme", "ice_cream", "🍦", ["eiscreme"]], ["magnum", "Magnum", "ice_cream", "🍦", ["magnum"]], ["sorbet", "Sorbet", "ice_cream", "🍧", ["sorbet"]],
  ["eiswuerfel", "Eiswürfel", "ice_cream", "🧊", ["eiswürfel", "eiswuerfel"]], ["aufschnitt", "Aufschnitt", "meat", "🥩", ["aufschnitt"]],
  ["vegetarischer-aufschnitt", "Vegetarischer Aufschnitt", "vegetarian", "🌱", ["vegetarischer aufschnitt", "vegetarischen aufschnitt"]],
  ["haferflocken", "Haferflocken", "bakery_fitness", "🥣", ["haferflocken"]], ["hafermilch", "Hafermilch", "milk_uncooled", "🥛", ["hafermilch"]], ["mandelmilch", "Mandelmilch", "milk_uncooled", "🥛", ["mandelmilch"]],
  ["eingelegte-gurken", "Eingelegte Gurken", "canned", "🥒", ["eingelegte gurken"]], ["wuerstchen", "Würstchen", "meat", "🌭", ["würstchen", "wuerstchen"]],
  ["stevia", "Stevia", "baking", "🍃", ["stevia"]], ["apfelschorle", "Apfelschorle", "drinks", "🧃", ["apfelschorle"]],
  ["mundspuelung", "Mundspülung", "drugstore", "🦷", ["mundspülung", "mundspuelung"]], ["haehnchenfleisch", "Hähnchenfleisch", "meat", "🍗", ["hähnchenfleisch", "haehnchenfleisch"]],
  ["heidelbeeren", "Heidelbeeren", "produce", "🫐", ["heidelbeere", "heidelbeeren"]], ["leberwurst", "Leberwurst", "meat", "🥩", ["leberwurst"]],
  ["tofu-natur", "Tofu natur", "vegetarian", "🌱", ["tofu natur"]], ["kochsahne", "Kochsahne", "milk", "🥛", ["kochsahne"]],
  ["tomatenpesto", "Tomatenpesto", "oils_sauces", "🍅", ["tomatenpesto"]], ["apfelsaft", "Apfelsaft", "drinks", "🧃", ["apfelsaft"]],
  ["flammkuchenboden", "Flammkuchenboden", "bakery_fitness", "🍞", ["flammkuchenboden", "flammkuchenteig"]], ["roher-schinken", "Roher Schinken", "meat", "🥩", ["roher schinken", "serrano schinken", "parmaschinken", "prosciutto"]],
  ["gefrierbeutel", "Gefrierbeutel", "household", "🧊", ["gefrierbeutel"]], ["intimseife", "Intimseife", "drugstore", "🧼", ["intimseife"]], ["krustenschinken", "Krustenschinken", "meat", "🥩", ["krustenschinken"]],
  ["tampons", "Tampons", "drugstore", "🩸", ["tampon", "tampons"]], ["sonnenfinsternisbrillen", "Sonnenfinsternisbrillen", "other", "🕶️", ["sonnenfinsternisbrillen"]],
];

const catalogSeed = [
  ["mehl", "Mehl", "baking", "🌾", ["mehl", "weizenmehl", "mehl 405", "mehl 550"]],
  ["hefe", "Hefe", "bakery_fitness", "🧈", ["hefe", "trockenhefe"]],
  ["gurke", "Gurke", "produce", "🥒", ["gurke", "gurken"]],
  ["milch", "Milch", "milk", "🥛", ["milch", "vollmilch"]],
  ["butter", "Butter", "milk", "🧈", ["butter"]],
  ["eier", "Eier", "milk", "🥚", ["ei", "eier"]],
  ["tomate", "Tomate", "produce", "🍅", ["tomate", "tomaten"]],
  ["kartoffel", "Kartoffel", "produce", "🥔", ["kartoffel", "kartoffeln"]],
  ["banane", "Banane", "produce", "🍌", ["banane", "bananen"]],
  ["gemuese", "Gemüse", "produce", "🥬", ["gemüse", "gemuese", "gemüse eins komma", "gemuese eins komma"]],
  ["rucola", "Rucola", "produce", "🥬", ["rucola", "ruccola"]],
  ["nudeln", "Nudeln", "pasta_rice", "🍝", ["nudel", "nudeln"]],
  ["reis", "Reis", "pasta_rice", "🍚", ["reis"]],
  ["zucker", "Zucker", "baking", "🫙", ["zucker"]],
  ["wasser", "Wasser", "drinks", "💧", ["wasser"]],
  ["kaffee", "Kaffee", "drinks", "☕", ["kaffee"]],
  ["spuelmaschinensalz", "Spülmaschinensalz", "household", "🧂", ["spülmaschinensalz", "spuelmaschinensalz"]],
  ["spuelmittel", "Spülmittel", "household", "🧽", ["spülmittel", "spuelmittel"]],
  ["waschmittel", "Waschmittel", "household", "🧴", ["waschmittel"]],
  ["toilettenpapier", "Toilettenpapier", "drugstore", "🧻", ["toilettenpapier"]],
  ["brot", "Brot", "bakery_fitness", "🍞", ["brot"]],
  ["honig", "Honig", "bakery_fitness", "🍯", ["honig"]],
  ["muesliriegel", "Müsliriegel", "bakery_fitness", "🥣", ["müsliriegel", "musliriegel", "muesliriegel"]],
  ["knusperbrot", "Knusperbrot", "bakery_fitness", "🍞", ["knusperbrot"]],
  ["nutella", "Nutella", "sweets", "🍫", ["nutella", "schokocreme"]],
  ["sahne", "Sahne", "milk", "🥛", ["sahne"]],
  ["kaese", "Käse", "cheese", "🧀", ["käse", "kaese"]],
  ["toastkaese", "Toastkäse", "cheese", "🧀", ["toastkäse", "toastkaese"]],
  ["geriebener-kaese", "Geriebener Käse", "cheese", "🧀", ["geriebener käse", "geriebener kaese"]],
  ...catalogExtras,
].map(([key, name, categoryId, icon, aliases]) => ({ id: `product-${key}`, key, name, categoryId, icon, aliases, ...inferVisual(name, categoryId) }));

for (const extra of extraCatalogProducts) {
  if (!catalogSeed.some((item) => item.key === extra.key || normalizeText(item.name) === normalizeText(extra.name))) catalogSeed.push(extra);
}

// Jeder mitgelieferte Stammartikel besitzt ab Werk ein lokales Bild.
// Diese Artikel lösen niemals eine Gemini-Bildgenerierung aus.
for (const product of catalogSeed) {
  product.imageKey = imageKeyForProduct(product.name, product.categoryId);
  product.imageSource = "catalog";
}

const productRules = [
  ["produce", "🍎", ["apfel", "äpfel", "birne", "orange", "zitrone", "limette", "erdbeere", "erdbeeren", "himbeere", "himbeeren", "blaubeere", "blaubeeren", "kirsche", "kirschen", "trauben", "mango", "ananas", "avocado", "paprika", "zucchini", "aubergine", "brokkoli", "blumenkohl", "salat", "zwiebel", "zwiebeln", "knoblauch", "möhre", "möhren", "karotte", "karotten", "champignon", "champignons", "mais"]],
  ["vegetarian", "🌱", ["tofu", "tempeh", "hummus", "falafel", "linsen", "kichererbsen", "haferdrink", "sojadrink", "veggie", "vegetarisch", "vegan", "vegetarische bratwurst", "vegetarische schnitzel", "vegetarische salami", "vegetarische würstchen", "veganes hack"]],
  ["milk_uncooled", "🥛", ["hafermilch", "mandelmilch", "sojamilch"]],
  ["bakery_fitness", "🍞", ["brot", "brötchen", "toast", "baguette", "croissant", "brezel", "knäckebrot", "knäckebrote", "proteinriegel", "müsliriegel"]],
  ["baking", "🧁", ["backpulver", "vanillezucker", "vanille", "kakao", "speisestärke", "stärke", "mandeln", "haselnüsse", "kokosraspeln", "puderzucker"]],
  ["milk", "🥛", ["joghurt", "jogurt", "skyr", "quark", "sahne", "creme fraiche", "crème fraîche", "pudding", "milchreis"]],
  ["canned", "🥫", ["dosentomaten", "passierte tomaten", "tomatenmark", "thunfisch", "bohnen", "erbsen", "ravioli", "konserve", "konserven"]],
  ["oils_sauces", "🫙", ["ketchup", "mayonnaise", "mayo", "senf", "pesto", "barbecue", "grillsauce", "soße", "sauce", "öl", "olivenöl", "essig"]],
  ["cheese", "🧀", ["gouda", "mozzarella", "parmesan", "feta", "frischkäse", "camembert", "käse"]],
  ["household", "📦", ["müllbeutel", "gefrierbeutel", "alufolie", "frischhaltefolie", "backpapier", "küchenrolle", "batterien", "batterie", "leuchtmittel", "glühbirne", "gluehbirne"]],
  ["milk_uncooled", "🥚", ["h-milch", "kondensmilch", "kaffeesahne", "eier", "ei"]],
  ["ready_chilled", "🍽️", ["gnocchi", "maultaschen", "tortellini", "frische pizza", "fertiggericht", "fertigpizza"]],
  ["frozen", "❄️", ["pommes", "fischstäbchen", "tk gemüse", "tiefkühlgemüse", "tk pizza", "spinat"]],
  ["meat", "🥩", ["schinken", "salami", "wurst", "hackfleisch", "fleisch", "hähnchen", "hühnchen", "steak", "bacon", "bratwurst"]],
  ["drinks", "🥤", ["wasser", "saft", "orangensaft", "apfelsaft", "cola", "limonade", "limo", "bier", "wein", "tee", "kaffee", "energy"]],
  ["sweets", "🍫", ["nutella", "schokolade", "gummibärchen", "bonbons", "kekse", "chips", "snack", "müsliriegel"]],
  ["drugstore", "🧴", ["shampoo", "duschgel", "zahnpasta", "zahnbürste", "deo", "rasierer", "waschmittel", "spülmittel", "spuelmittel", "spülschwamm", "spuelschwamm", "schwamm", "allzweckreiniger", "putzmittel", "reiniger", "spülmaschinensalz", "spuelmaschinensalz", "toilettenpapier", "taschentücher", "windeln"]],
  ["ice_cream", "🍦", ["eis", "eiscreme", "magnum", "sorbet"]],
].flatMap(([categoryId, icon, terms]) => terms.map((term) => ({ categoryId, icon, term: normalizeText(term) })));

const DEFAULT_LIST_ID = "supermarkt";
const DEFAULT_LIST_NAME = "Einkaufsliste (Supermarkt)";
const DEFAULT_LIST_COLOR = "#ef5d61";
function validColor(value) { const color = String(value || "").trim().toLowerCase(); return /^#[0-9a-f]{6}$/.test(color) ? color : null; }

function clone(value) { return JSON.parse(JSON.stringify(value)); }

function listRecord(id, name, color, data) {
  return { id, name: name || DEFAULT_LIST_NAME, color: color || DEFAULT_LIST_COLOR, sort: 0,
    categories: data.categories, products: data.products, entries: data.entries, recent: data.recent, undo: data.undo || null,
    learningExamples: Array.isArray(data.learningExamples) ? data.learningExamples : [],
    deletedProductKeys: Array.isArray(data.deletedProductKeys) ? [...new Set(data.deletedProductKeys.filter(Boolean))] : [] };
}

function emptyGeminiImageUsage() {
  return { accountingVersion: GEMINI_COST_ACCOUNTING_VERSION, totalImages: 0, totalCostEur: 0, daily: {}, lastGeneration: null, trackingSince: new Date().toISOString(), fxCache: null };
}
function normalizeGeminiImageUsage(value) {
  if (!value || typeof value !== "object" || Number(value.accountingVersion || 0) !== GEMINI_COST_ACCOUNTING_VERSION) {
    const fresh = emptyGeminiImageUsage();
    if (value && typeof value === "object") {
      fresh.previousEstimatedImages = Number(value.totalImages || 0);
      fresh.previousEstimatedCostUsd = Number(value.totalCostUsd || 0);
      fresh.previousTrackingSince = value.trackingSince || null;
    }
    return fresh;
  }
  const usage = clone(value);
  usage.accountingVersion = GEMINI_COST_ACCOUNTING_VERSION;
  usage.totalImages = Number(usage.totalImages || 0);
  usage.totalCostEur = Number(usage.totalCostEur || 0);
  usage.daily = usage.daily && typeof usage.daily === "object" ? usage.daily : {};
  usage.lastGeneration = usage.lastGeneration || null;
  usage.trackingSince = usage.trackingSince || new Date().toISOString();
  usage.fxCache = usage.fxCache && typeof usage.fxCache === "object" ? usage.fxCache : null;
  return usage;
}
function usageDateKey(date = new Date()) {
  try { return new Intl.DateTimeFormat("sv-SE", { timeZone: process.env.TZ || "Europe/Berlin", year: "numeric", month: "2-digit", day: "2-digit" }).format(date); }
  catch { return date.toISOString().slice(0, 10); }
}
function modalityTokens(details, modality) {
  if (!Array.isArray(details)) return 0;
  return details.filter((item) => String(item?.modality || "").toLowerCase() === modality).reduce((sum, item) => sum + Number(item?.tokens ?? item?.tokenCount ?? 0), 0);
}
function normalizeImageApiUsage(payload, mode = "interactions") {
  if (!payload || typeof payload !== "object") return null;
  if (mode === "interactions") {
    const u = payload.usage;
    if (!u || typeof u !== "object") return null;
    const inputTokens = Number(u.total_input_tokens ?? u.totalInputTokens ?? 0);
    let imageOutputTokens = modalityTokens(u.output_tokens_by_modality ?? u.outputTokensByModality, "image");
    let textOutputTokens = modalityTokens(u.output_tokens_by_modality ?? u.outputTokensByModality, "text");
    const totalOutputTokens = Number(u.total_output_tokens ?? u.totalOutputTokens ?? 0);
    if (!imageOutputTokens && !textOutputTokens && totalOutputTokens) imageOutputTokens = totalOutputTokens;
    const thoughtTokens = Number(u.total_thought_tokens ?? u.totalThoughtTokens ?? 0);
    return { source: "interactions", inputTokens, imageOutputTokens, textOutputTokens, thoughtTokens, totalTokens: Number(u.total_tokens ?? u.totalTokens ?? 0) };
  }
  const u = payload.usageMetadata;
  if (!u || typeof u !== "object") return null;
  const inputTokens = Number(u.promptTokenCount || 0);
  let imageOutputTokens = modalityTokens(u.candidatesTokensDetails, "image");
  let textOutputTokens = modalityTokens(u.candidatesTokensDetails, "text");
  const candidateTokens = Number(u.candidatesTokenCount || 0);
  if (!imageOutputTokens && !textOutputTokens && candidateTokens) imageOutputTokens = candidateTokens;
  return { source: "generateContent", inputTokens, imageOutputTokens, textOutputTokens, thoughtTokens: Number(u.thoughtsTokenCount || 0), totalTokens: Number(u.totalTokenCount || 0) };
}
function calculateGeminiImageCostUsd(apiUsage) {
  if (!apiUsage) return null;
  const input = Number(apiUsage.inputTokens || 0) * GEMINI_IMAGE_INPUT_USD_PER_M / 1_000_000;
  const image = Number(apiUsage.imageOutputTokens || 0) * GEMINI_IMAGE_OUTPUT_USD_PER_M / 1_000_000;
  const textAndThinking = (Number(apiUsage.textOutputTokens || 0) + Number(apiUsage.thoughtTokens || 0)) * GEMINI_IMAGE_TEXT_OUTPUT_USD_PER_M / 1_000_000;
  const total = input + image + textAndThinking;
  return Number.isFinite(total) && total > 0 ? total : null;
}
async function eurPerUsdAtGeneration() {
  state.geminiImageUsage = normalizeGeminiImageUsage(state.geminiImageUsage);
  const cached = state.geminiImageUsage.fxCache;
  if (cached?.eurPerUsd && cached?.fetchedAt && Date.now() - Date.parse(cached.fetchedAt) < 12 * 60 * 60 * 1000) return cached;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    let response;
    try { response = await fetch("https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml", { signal: controller.signal, headers: { accept: "application/xml,text/xml" } }); }
    finally { clearTimeout(timeout); }
    if (!response.ok) throw new Error(`ECB HTTP ${response.status}`);
    const xml = await response.text();
    const usd = xml.match(/currency=['"]USD['"]\s+rate=['"]([0-9.]+)['"]/i);
    const date = xml.match(/time=['"](\d{4}-\d{2}-\d{2})['"]/i);
    const usdPerEur = Number(usd?.[1] || 0);
    if (!(usdPerEur > 0)) throw new Error("USD-Referenzkurs fehlt");
    const result = { eurPerUsd: 1 / usdPerEur, usdPerEur, source: "ECB", rateDate: date?.[1] || null, fetchedAt: new Date().toISOString() };
    state.geminiImageUsage.fxCache = result;
    return result;
  } catch (error) {
    if (cached?.eurPerUsd) return cached;
    console.warn(`Gemini-Kosten: EUR-Umrechnung nicht verfügbar: ${error.message}`);
    return null;
  }
}
async function recordGeminiImageUsage(kind, itemName, apiUsage, date = new Date()) {
  state.geminiImageUsage = normalizeGeminiImageUsage(state.geminiImageUsage);
  const costUsd = calculateGeminiImageCostUsd(apiUsage);
  const fx = costUsd ? await eurPerUsdAtGeneration() : null;
  const costEur = costUsd && fx?.eurPerUsd ? costUsd * Number(fx.eurPerUsd) : null;
  const day = usageDateKey(date);
  const daily = state.geminiImageUsage.daily[day] || { images: 0, pricedImages: 0, costEur: 0 };
  daily.images = Number(daily.images || 0) + 1;
  if (costEur !== null) {
    daily.pricedImages = Number(daily.pricedImages || 0) + 1;
    daily.costEur = Number((Number(daily.costEur || 0) + costEur).toFixed(8));
  }
  state.geminiImageUsage.daily[day] = daily;
  state.geminiImageUsage.totalImages += 1;
  if (costEur !== null) state.geminiImageUsage.totalCostEur = Number((state.geminiImageUsage.totalCostEur + costEur).toFixed(8));
  state.geminiImageUsage.lastGeneration = {
    kind, itemName: String(itemName || ""), costEur: costEur === null ? null : Number(costEur.toFixed(8)), costUsd: costUsd === null ? null : Number(costUsd.toFixed(8)),
    fx: fx ? { eurPerUsd: Number(fx.eurPerUsd), source: fx.source, rateDate: fx.rateDate || null } : null, apiUsage: apiUsage || null, createdAt: date.toISOString()
  };
}
function publicGeminiImageUsage() {
  const usage = normalizeGeminiImageUsage(state.geminiImageUsage);
  const today = usage.daily[usageDateKey()] || { images: 0, pricedImages: 0, costEur: 0 };
  return { model: GEMINI_IMAGE_MODEL, todayImages: Number(today.images || 0), todayPricedImages: Number(today.pricedImages || 0), todayCostEur: Number(today.costEur || 0), totalImages: usage.totalImages, totalCostEur: usage.totalCostEur, lastGeneration: usage.lastGeneration, trackingSince: usage.trackingSince, trackingVersion: GEMINI_COST_TRACKING_SINCE };
}

function initialState() {
  const categories = clone(categorySeed); const products = clone(catalogSeed);
  const data = { categories, products, entries: [], recent: [], undo: null, learningExamples: [] };
  const list = listRecord(DEFAULT_LIST_ID, DEFAULT_LIST_NAME, DEFAULT_LIST_COLOR, clone(data));
  return { version: VERSION, lists: [list], activeListId: DEFAULT_LIST_ID, syncListId: DEFAULT_LIST_ID,
    categories, products, entries: [], recent: [], undo: null, learningExamples: [], deletedProductKeys: [], geminiImageUsage: emptyGeminiImageUsage(), updatedAt: new Date().toISOString() };
}

function ruleForName(name) {
  const key = normalizeText(name);
  return productRules.find((rule) => key === rule.term || key.includes(rule.term) || rule.term.includes(key));
}

function categoryIcon(categoryId) {
  return categorySeed.find((category) => category.id === categoryId)?.icon || "📦";
}

function isFallbackIcon(product) {
  const first = firstUpper(product.name || product.key).charAt(0);
  return !product.icon || product.icon === "?" || product.icon === first;
}

function improveProduct(product, categories = categorySeed) {
  if (!product.categoryId) product.categoryId = "other";
  if (!product.icon) product.icon = categoryIcon(product.categoryId);
  const inferred = inferVisual(product.name || product.key, product.categoryId);
  const visual = sanitizeVisual(product, inferred);
  // Automatische Darstellungen bleiben ableitbar und können mit dem Renderer
  // verbessert werden. Manuelle und Gemini-Entscheidungen werden nie ersetzt.
  const refreshAutomatic = !product.visualSource || product.visualSource === "automatic";
  if (refreshAutomatic) {
    product.visualBase = inferred.visualBase;
    product.visualMotif = inferred.visualMotif;
    product.visualLabel = inferred.visualLabel;
  } else {
    if (!product.visualBase) product.visualBase = visual.visualBase;
    if (!product.visualMotif) product.visualMotif = visual.visualMotif;
    if (product.visualLabel === undefined) product.visualLabel = visual.visualLabel;
  }
  if (!product.visualSource) product.visualSource = "automatic";
  // Stammbilder werden bei einer App-Version neu aus der aktuellen Zuordnung abgeleitet.
  // So erhalten bestehende Produkte verbesserte lokale Icons, ohne Gemini erneut aufzurufen.
  if (!product.imageKey || product.imageSource === "catalog") {
    product.imageKey = imageKeyForProduct(product.name || product.key, product.categoryId);
  }
  // Alles, was bereits vor 0.3.19 im Artikelstamm vorhanden war, wird als Bestand behandelt.
  // Nur Produkte, die ab 0.3.19 neu angelegt werden, starten mit imageSource=pending.
  if (!product.imageSource) product.imageSource = "catalog";
  return product;
}

const legacyCategoryMap = { grain: "baking", produce: "produce", milk: "milk", drinks: "drinks", household: "household", other: "other" };
const CLEANING_PRODUCT_PATTERN = /(^| )(putzmittel|allzweckreiniger|reiniger|spulmittel|spuelmittel|spulschwamm|spuelschwamm|schwamm|waschmittel|spulmaschinensalz|spuelmaschinensalz)( |$)/;
const FREEZER_BAG_PATTERN = /(^| )(?:zip )?(?:tiefkuhlbeutel|tiefkuehlbeutel|gefrierbeutel)( |$)/;
function shouldMoveHouseholdCleaningToDrugstore(product) {
  if (!product || product.categoryId !== "household" || product.classificationSource === "manual") return false;
  const text = normalizeText([product.name, product.key, ...(product.aliases || [])].filter(Boolean).join(" "));
  return CLEANING_PRODUCT_PATTERN.test(text);
}

function hasStoredQuantity(quantity) {
  return Boolean(quantity && Number.isFinite(Number(quantity.value)) && String(quantity.unit || "").trim());
}

function recoverMissingQuantity(entry) {
  if (!entry || hasStoredQuantity(entry.quantity) || entry.productDetail || typeof entry.original !== "string") return entry;
  try {
    const recovered = parseItemInput(entry.original).quantity;
    return recovered ? { ...entry, quantity: recovered } : entry;
  } catch {
    return entry;
  }
}

const PRODUCT_DETAIL_UNITS = new Set(["kg", "g", "mg", "l", "ml"]);
function normalizedMeasurementUnit(value) {
  const unit = normalizeText(value);
  return unit === "kilo" ? "kg" : unit === "liter" ? "l" : unit;
}
function isProductDetailMeasurement(quantity) {
  return Boolean(quantity && Number.isFinite(Number(quantity.value)) && PRODUCT_DETAIL_UNITS.has(normalizedMeasurementUnit(quantity.unit)));
}
function formatDecimalDe(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return String(value || "");
  return (Number.isInteger(numeric) ? String(numeric) : String(numeric)).replace(".", ",");
}
function formatProductDetailMeasurement(quantity) {
  if (!isProductDetailMeasurement(quantity)) return "";
  const value = Number(quantity.value);
  const unit = normalizedMeasurementUnit(quantity.unit);
  const amount = formatDecimalDe(value);
  if (unit === "l") return `${amount} Liter`;
  return `${amount} ${unit}`;
}
function normalizeProductDetail(value) { return String(value || "").trim().replace(/\s+/g, " "); }
function friendlyProductName(value) {
  let text = String(value || "").trim().replace(/\s+/g, " ");
  if (!text) return "";
  // Häufige Alexa-Schreibweisen und eindeutig bekannte Bezeichnungen lokal glätten.
  // Semantische Korrekturen bleiben bewusst eng, damit keine echten Produkte umbenannt werden.
  text = text.replace(/\balverde\s+rasierer\s+sensitiv\b/ig, "Alverde Rasiergel sensitiv");
  text = text.replace(/\brasier\s*gel\b/ig, "Rasiergel");
  text = text.replace(/\bzip[\s-]+tiefk(?:ü|ue)hlbeutel\b/ig, "Zip-Tiefkühlbeutel");
  text = text.replace(/\bzip[\s-]+gefrierbeutel\b/ig, "Zip-Gefrierbeutel");
  const replacements = [
    [/\balverde\b/ig, "Alverde"], [/\bdm\b/ig, "DM"], [/\brossmann\b/ig, "Rossmann"],
    [/\b(?:müller|mueller|muller)\b/ig, "Müller"], [/\brasiergel\b/ig, "Rasiergel"],
    [/\bshampoo\b/ig, "Shampoo"], [/\bdeo\b/ig, "Deo"],
  ];
  for (const [pattern, replacement] of replacements) text = text.replace(pattern, replacement);
  return firstUpper(text);
}

function productKeyForCategory(name, categoryId, products = state?.products || [], ignoreId = "", forceScoped = false) {
  const base = normalizeText(name) || "artikel";
  const sameNameElsewhere = (products || []).some((product) => product?.id !== ignoreId && normalizeText(product?.name) === base && product?.categoryId !== categoryId);
  if (!forceScoped && !sameNameElsewhere) return base;
  const scope = normalizeText(categoryId || "other").replace(/\s+/g, "-") || "other";
  return `${base} category ${scope}`;
}

function categorySuffixMatch(value, list) {
  const raw = String(value || "").trim().replace(/\s+/g, " ");
  const category = firmaCategoryForList(list);
  if (!category) return null;
  const match = /^(.*?)\s+firma\s*$/i.exec(raw);
  if (!match || !match[1]?.trim()) return null;
  const baseName = friendlyProductName(match[1].trim());
  return baseName ? { category, baseName, alias: "firma", wordCount: 1 } : null;
}
function prepareParsedProductDetail(parsed) {
  if (!parsed) return parsed;
  let next = { ...parsed, name: friendlyProductName(parsed.name) };
  if (!next.productDetail && isProductDetailMeasurement(next.quantity) && !next.quantity?.userEdited) {
    next.productDetail = formatProductDetailMeasurement(next.quantity);
    next.quantity = null;
  }
  if (!next.productDetail && next.name) {
    try {
      const nested = parseItemInput(next.name);
      if (nested && nested.name && normalizeText(nested.name) !== normalizeText(next.name) && isProductDetailMeasurement(nested.quantity)) {
        next.name = friendlyProductName(nested.name);
        next.productDetail = formatProductDetailMeasurement(nested.quantity);
      }
    } catch {}
  }
  return next;
}
function migrateEntryProductDetail(entry) {
  if (!entry || entry.productDetail || !isProductDetailMeasurement(entry.quantity) || entry.quantity?.userEdited) return entry;
  return { ...entry, productDetail: formatProductDetailMeasurement(entry.quantity), quantity: null };
}
function entryDuplicateKey(productKey, quantity, productDetail = "") {
  return `${duplicateKey(productKey, quantity)}|detail:${normalizeText(productDetail) || "none"}`;
}

function normalizeDefaultQuantity(value) {
  if (!value || typeof value !== "object") return null;
  const numeric = Number(String(value.value ?? "").replace(",", "."));
  if (!Number.isFinite(numeric) || numeric <= 0) return null;
  const unit = String(value.unit || "Stück").trim() || "Stück";
  return { value: numeric, unit };
}

function effectiveQuantityForProduct(explicitQuantity, product) {
  if (hasStoredQuantity(explicitQuantity)) return { ...explicitQuantity };
  const standard = normalizeDefaultQuantity(product?.defaultQuantity);
  return standard ? { ...standard } : null;
}

const MEYERHOF_MARKER = /\b(?:meyer|meier|maier|mayer)\s*[- ]?\s*hof(?:\s+belm)?\b/i;
const REWE_MARKER = /\bREWE(?:\s*[- ]?\s*Markt)?\b/i;
function isMeyerhofCategoryName(value) {
  const compact = normalizeText(value).replace(/\s+/g, "");
  return ["meyerhof", "meyerhofbelm", "meierhof", "meierhofbelm", "maierhof", "maierhofbelm", "mayerhof", "mayerhofbelm"].includes(compact);
}
function meyerhofCategoryForList(list) {
  return (list?.categories || []).find((category) => isMeyerhofCategoryName(category?.name)) || null;
}
function isReweCategoryName(value) {
  const compact = normalizeText(value).replace(/\s+/g, "");
  return ["rewe", "rewemarkt"].includes(compact);
}
function reweCategoryForList(list) {
  return (list?.categories || []).find((category) => isReweCategoryName(category?.name)) || null;
}
function ensureReweCategoryForList(list) {
  if (!list) return null;
  if (!Array.isArray(list.categories)) list.categories = [];
  const existing = reweCategoryForList(list);
  if (existing) return existing;
  const usedIds = new Set(list.categories.map((category) => String(category.id || "")));
  let id = "rewe";
  let suffix = 2;
  while (usedIds.has(id)) id = `rewe-${suffix++}`;
  const sort = list.categories.reduce((max, category) => Math.max(max, Number(category.sort) || 0), -1) + 1;
  const category = {
    id, name: "REWE", icon: "🛒",
    description: "Produkte, die ausdrücklich bei REWE gekauft werden sollen.",
    sort, reweIconVersion: 1, imageSource: "catalog",
  };
  list.categories.push(category);
  return category;
}
function isRetailerCategoryName(value) {
  const text = normalizeText(value);
  return /(^| )dm( |$)/.test(text) && /(^| )rossmann( |$)/.test(text) && /(^| )(muller|mueller)( |$)/.test(text);
}
function retailerCategoryForList(list) {
  return (list?.categories || []).find((category) => isRetailerCategoryName(category?.name)) || null;
}
function extractRetailerTag(value) {
  const raw = String(value || "").trim().replace(/\s+/g, " ").trim();
  const found = [];
  const patterns = [
    { label: "DM", regex: /\(?\s*\bd\s*\.?\s*m\b\s*\.?\s*\)?/ig },
    { label: "Rossmann", regex: /\(?\s*\brossmann\b\s*\)?/ig },
    { label: "Müller", regex: /\(?\s*\b(?:müller|mueller|muller)\b\s*\)?/ig },
  ];
  let cleaned = raw;
  for (const item of patterns) {
    if (item.regex.test(cleaned)) found.push(item.label);
    item.regex.lastIndex = 0;
    cleaned = cleaned.replace(item.regex, " ");
  }
  const labels = [...new Set(found)];
  if (!labels.length) return { tagged: false, rawName: firstUpper(raw), name: firstUpper(raw), storeLabel: "" };
  cleaned = cleaned.replace(/\s{2,}/g, " ").replace(/^[\s,;:()\-–—]+|[\s,;:()\-–—]+$/g, "").trim();
  let baseName = firstUpper(cleaned || raw);
  baseName = baseName.replace(/\bdeo\b/ig, "Deo");
  const storeLabel = labels.join("/");
  return { tagged: true, rawName: firstUpper(raw), baseName, name: `${baseName} (${storeLabel})`, storeLabel };
}
function stripMeyerhofTag(value) {
  const raw = String(value || "").trim().replace(/\s+/g, " ").trim();
  if (!MEYERHOF_MARKER.test(raw)) return { tagged: false, rawName: firstUpper(raw), name: firstUpper(raw) };
  const parenthesized = /\(\s*(?:meyer|meier|maier|mayer)\s*[- ]?\s*hof(?:\s+belm)?\s*\)/ig;
  const marker = /\b(?:meyer|meier|maier|mayer)\s*[- ]?\s*hof(?:\s+belm)?\b/ig;
  const cleaned = raw.replace(parenthesized, " ").replace(marker, " ").replace(/\s{2,}/g, " ").replace(/^[\s,;:()\-–—]+|[\s,;:()\-–—]+$/g, "").trim();
  return { tagged: true, rawName: firstUpper(raw), name: firstUpper(cleaned || raw) };
}
function stripReweTag(value) {
  const raw = String(value || "").trim().replace(/\s+/g, " ").trim();
  if (!REWE_MARKER.test(raw)) return { tagged: false, rawName: firstUpper(raw), name: firstUpper(raw) };
  const parenthesized = /\(\s*REWE(?:\s*[- ]?\s*Markt)?\s*\)/ig;
  const marker = /\bREWE(?:\s*[- ]?\s*Markt)?\b/ig;
  const cleaned = raw.replace(parenthesized, " ").replace(marker, " ").replace(/\s{2,}/g, " ").replace(/^[\s,;:()\-–—]+|[\s,;:()\-–—]+$/g, "").trim();
  return { tagged: true, rawName: firstUpper(raw), name: firstUpper(cleaned || raw) };
}
function isFirmaCategoryName(value) {
  const text = normalizeText(value);
  return text === "firma" || text.startsWith("firma ");
}
function firmaCategoryForList(list) {
  return (list?.categories || []).find((category) => isFirmaCategoryName(category?.name)) || null;
}
function parseSpecialTargetInput(input, list) {
  if (typeof input !== "string") return null;
  const raw = String(input || "").trim().replace(/\s+/g, " ");
  if (!raw) return null;

  const firmaCategory = firmaCategoryForList(list);
  if (firmaCategory) {
    const suffixes = [
      { regex: /\s+firma\s*$/i, requireQuantity: false },
      { regex: /\s+vier\s+mal\s*$/i, requireQuantity: true },
      { regex: /\s+viermal\s*$/i, requireQuantity: true },
      { regex: /\s+vier\s+ma\s*$/i, requireQuantity: true },
      { regex: /\s+4\s+mal\s*$/i, requireQuantity: true },
      { regex: /\s+4mal\s*$/i, requireQuantity: true },
      { regex: /\s+4\s+ma\s*$/i, requireQuantity: true },
    ];
    for (const suffix of suffixes) {
      if (!suffix.regex.test(raw)) continue;
      const base = raw.replace(suffix.regex, "").trim();
      if (!base) continue;
      let parsed;
      try { parsed = prepareParsedProductDetail(parseItemInput(base)); }
      catch { continue; }
      if (suffix.requireQuantity && !hasStoredQuantity(parsed.quantity)) continue;
      const cleanName = friendlyProductName(parsed.name || base);
      if (!cleanName) continue;
      return {
        parsed: { ...parsed, original: raw, name: cleanName },
        lookupName: cleanName,
        keyName: `${cleanName} category ${firmaCategory.id}`,
        forcedCategoryId: firmaCategory.id,
        entryCategoryId: firmaCategory.id,
        sourceTag: `category:${firmaCategory.id}`,
        inheritFromName: cleanName,
        explicitCategorySuffix: true,
        spokenCategoryAlias: suffix.requireQuantity,
        targetKind: "firma",
      };
    }
  }

  const rewe = stripReweTag(raw);
  if (rewe.tagged) {
    const category = ensureReweCategoryForList(list);
    if (category) {
      const parsed = prepareParsedProductDetail(parseItemInput(rewe.name));
      const cleanName = friendlyProductName(parsed.name || rewe.name);
      return {
        parsed: { ...parsed, original: raw, name: cleanName },
        lookupName: cleanName,
        keyName: `${cleanName} rewe`,
        forcedCategoryId: category.id,
        entryCategoryId: category.id,
        sourceTag: "rewe",
        inheritFromName: cleanName,
        explicitCategorySuffix: true,
        targetKind: "rewe",
      };
    }
  }

  const retailer = extractRetailerTag(raw);
  const retailerCategory = retailer.tagged ? retailerCategoryForList(list) : null;
  if (retailerCategory) {
    const parsedBase = prepareParsedProductDetail(parseItemInput(retailer.baseName || retailer.name));
    const cleanBase = friendlyProductName(parsedBase.name || retailer.baseName || retailer.name);
    const displayName = `${cleanBase} (${retailer.storeLabel})`;
    return {
      parsed: { ...parsedBase, original: raw, name: displayName },
      lookupName: displayName,
      keyName: displayName,
      forcedCategoryId: retailerCategory.id,
      entryCategoryId: retailerCategory.id,
      sourceTag: `retailer:${normalizeText(retailer.storeLabel).replace(/\s+/g, "-")}`,
      inheritFromName: cleanBase,
      explicitCategorySuffix: true,
      targetKind: "retailer",
      storeLabel: retailer.storeLabel,
    };
  }

  const meyerhof = stripMeyerhofTag(raw);
  const meyerhofCategory = meyerhof.tagged ? meyerhofCategoryForList(list) : null;
  if (meyerhofCategory) {
    const parsed = prepareParsedProductDetail(parseItemInput(meyerhof.name));
    const cleanName = friendlyProductName(parsed.name || meyerhof.name);
    return {
      parsed: { ...parsed, original: raw, name: cleanName },
      lookupName: cleanName,
      keyName: `${cleanName} meyerhof`,
      forcedCategoryId: meyerhofCategory.id,
      entryCategoryId: meyerhofCategory.id,
      sourceTag: "meyerhof",
      inheritFromName: cleanName,
      explicitCategorySuffix: true,
      targetKind: "meyerhof",
    };
  }
  return null;
}

function parseSpokenFirmaInput(input, list) {
  const special = parseSpecialTargetInput(input, list);
  return special?.targetKind === "firma" ? special : null;
}

function explicitCategorySpecial(parsed, list, categoryId, options = {}) {
  parsed = prepareParsedProductDetail(parsed);
  const category = (list?.categories || []).find((item) => item.id === categoryId);
  if (!category) return null;
  const cleanBase = friendlyProductName(options.inheritFromName || parsed?.name || "");
  if (!cleanBase) return null;

  let sourceTag = String(options.sourceTag || "");
  let targetKind = String(options.targetKind || "");
  let displayName = friendlyProductName(parsed?.name || cleanBase);
  let keyName = `${displayName} category ${category.id}`;

  if (!sourceTag && isFirmaCategoryName(category.name)) {
    sourceTag = `category:${category.id}`;
    targetKind = "firma";
    displayName = cleanBase;
    keyName = `${cleanBase} category ${category.id}`;
  } else if (!sourceTag && isReweCategoryName(category.name)) {
    sourceTag = "rewe";
    targetKind = "rewe";
    displayName = cleanBase;
    keyName = `${cleanBase} rewe`;
  } else if (!sourceTag && isMeyerhofCategoryName(category.name)) {
    sourceTag = "meyerhof";
    targetKind = "meyerhof";
    displayName = cleanBase;
    keyName = `${cleanBase} meyerhof`;
  } else if (isRetailerCategoryName(category.name)) {
    const storeLabel = String(options.storeLabel || "").trim();
    if (storeLabel) {
      sourceTag = sourceTag || `retailer:${normalizeText(storeLabel).replace(/\s+/g, "-")}`;
      targetKind = "retailer";
      displayName = `${cleanBase} (${storeLabel})`;
      keyName = displayName;
    }
  }
  if (!sourceTag) sourceTag = `category:${category.id}`;

  return {
    parsed: { ...parsed, name: displayName },
    lookupName: displayName,
    keyName,
    forcedCategoryId: category.id,
    entryCategoryId: category.id,
    sourceTag,
    inheritFromName: cleanBase,
    explicitCategorySuffix: true,
    targetKind: targetKind || "category",
    ...(options.storeLabel ? { storeLabel: options.storeLabel } : {}),
  };
}

function resolveRequestedSpecialCategory(list, requestedId = "", requestedName = "") {
  const idValue = String(requestedId || "").trim();
  const nameValue = normalizeText(requestedName || "");
  if (idValue) {
    const category = (list?.categories || []).find((item) => item.id === idValue) || null;
    return category ? { category, targetKind: "category", sourceTag: "", storeLabel: "" } : null;
  }
  if (!nameValue) return null;
  if (nameValue === "firma") {
    const category = firmaCategoryForList(list);
    return category ? { category, targetKind: "firma", sourceTag: `category:${category.id}`, storeLabel: "" } : null;
  }
  if (nameValue === "rewe" || nameValue === "rewe markt") {
    const category = ensureReweCategoryForList(list);
    return category ? { category, targetKind: "rewe", sourceTag: "rewe", storeLabel: "" } : null;
  }
  const retailerLabel = ({ dm: "DM", rossmann: "Rossmann", muller: "Müller", mueller: "Müller" })[nameValue];
  if (retailerLabel) {
    const category = retailerCategoryForList(list);
    return category ? { category, targetKind: "retailer", sourceTag: `retailer:${normalizeText(retailerLabel).replace(/\s+/g, "-")}`, storeLabel: retailerLabel } : null;
  }
  if (isMeyerhofCategoryName(nameValue)) {
    const category = meyerhofCategoryForList(list);
    return category ? { category, targetKind: "meyerhof", sourceTag: "meyerhof", storeLabel: "" } : null;
  }
  const category = (list?.categories || []).find((item) => normalizeText(item.name) === nameValue) || null;
  return category ? { category, targetKind: "category", sourceTag: "", storeLabel: "" } : null;
}

function prepareParsedForList(parsed, list) {
  parsed = prepareParsedProductDetail(parsed);
  const meyerhof = stripMeyerhofTag(parsed?.name || "");
  const meyerhofCategory = meyerhof.tagged ? meyerhofCategoryForList(list) : null;
  if (meyerhofCategory) return {
    parsed: { ...parsed, name: meyerhof.name },
    lookupName: meyerhof.rawName,
    keyName: meyerhof.rawName,
    forcedCategoryId: meyerhofCategory.id,
    sourceTag: "meyerhof",
    inheritFromName: meyerhof.name,
  };
  const rewe = stripReweTag(parsed?.name || "");
  if (rewe.tagged) {
    const reweCategory = ensureReweCategoryForList(list);
    if (reweCategory) return {
      parsed: { ...parsed, name: rewe.name },
      lookupName: rewe.rawName,
      keyName: rewe.rawName,
      forcedCategoryId: reweCategory.id,
      sourceTag: "rewe",
      inheritFromName: rewe.name,
    };
  }
  const retailer = extractRetailerTag(parsed?.name || "");
  const retailerCategory = retailer.tagged ? retailerCategoryForList(list) : null;
  if (retailerCategory) return {
    parsed: { ...parsed, name: friendlyProductName(retailer.name) },
    lookupName: retailer.rawName,
    keyName: retailer.name,
    forcedCategoryId: retailerCategory.id,
    sourceTag: `retailer:${normalizeText(retailer.storeLabel).replace(/\s+/g, "-")}`,
    inheritFromName: friendlyProductName(retailer.baseName || retailer.name.replace(/\s*\([^)]*\)\s*$/, "")),
  };
  const categorySuffix = categorySuffixMatch(parsed?.name || "", list);
  if (categorySuffix) return {
    parsed: { ...parsed, name: categorySuffix.baseName },
    lookupName: categorySuffix.baseName,
    keyName: `${categorySuffix.baseName} category ${categorySuffix.category.id}`,
    forcedCategoryId: categorySuffix.category.id,
    entryCategoryId: categorySuffix.category.id,
    preferExistingMaster: true,
    sourceTag: `category:${categorySuffix.category.id}`,
    inheritFromName: categorySuffix.baseName,
    explicitCategorySuffix: true,
  };
  return { parsed: { ...parsed, name: friendlyProductName(parsed?.name || "") }, lookupName: friendlyProductName(parsed?.name || ""), forcedCategoryId: "", sourceTag: "" };
}
const KNOWN_QUANTITY_UNITS = new Set(["stuck","stueck","kg","g","mg","l","ml","kiste","karton","packung","paket","flasche","dose","bund","beutel","nachfullbeutel","nachfuellbeutel","tute","tuete","rolle"]);
function looksLikeEntryNoteUnit(unit) {
  const normalized = normalizeText(unit);
  if (!normalized || KNOWN_QUANTITY_UNITS.has(normalized.replace(/ü/g, "u"))) return false;
  return /^(vor|nach|beim|bevor|wenn|zum|zur|fur)\b/.test(normalized) || normalized.split(" ").length >= 3 || normalized.length >= 24;
}
function migrateEntryNote(entry) {
  if (!entry || !entry.quantity || entry.note) return entry;
  const unit = String(entry.quantity.unit || "").trim();
  if (Number(entry.quantity.value) !== 1 || !looksLikeEntryNoteUnit(unit)) return entry;
  return { ...entry, quantity: null, note: firstUpper(unit) };
}

function migrateCollection(loaded, includeCatalog = true, preserveCategories = false) {
  const base = initialState();
  const oldCategories = Array.isArray(loaded?.categories) ? loaded.categories : [];
  const custom = oldCategories.filter((category) => !base.categories.some((seed) => seed.id === category.id) && !["grain", "produce", "milk", "drinks", "household", "other"].includes(category.id));
  const categories = preserveCategories
    ? (oldCategories.length ? oldCategories.map((category) => ({ ...category, id: legacyCategoryMap[category.id] || category.id })) : [clone(base.categories.find((category) => category.id === "other"))])
    : (oldCategories.length ? [...oldCategories.map((category) => ({ ...category, id: legacyCategoryMap[category.id] || category.id })), ...base.categories.filter((seed) => !oldCategories.some((category) => (legacyCategoryMap[category.id] || category.id) === seed.id))] : clone(base.categories));
  if (preserveCategories && !categories.some((category) => category.id === "other")) categories.push(clone(base.categories.find((category) => category.id === "other")));
  for (const category of custom) if (!categories.some((item) => item.id === category.id)) categories.push({ ...category, sort: categories.length });
  const reweTaggedInLoadedData = [
    ...(Array.isArray(loaded?.products) ? loaded.products : []),
    ...(Array.isArray(loaded?.entries) ? loaded.entries : []),
    ...(Array.isArray(loaded?.recent) ? loaded.recent : []),
  ].some((item) => {
    const values = [item?.name, item?.key, item?.original, ...(Array.isArray(item?.aliases) ? item.aliases : [])].filter(Boolean);
    return values.some((value) => stripReweTag(value).tagged);
  });
  if (reweTaggedInLoadedData && !reweCategoryForList({ categories })) ensureReweCategoryForList({ categories });
  categories.forEach((category, index) => {
    category.sort = Number.isFinite(Number(category.sort)) ? Number(category.sort) : index;
    const seed = base.categories.find((item) => item.id === category.id);
    if (category.description === undefined || category.description === null || !String(category.description).trim()) category.description = seed?.description || "";
    if (isMeyerhofCategoryName(category.name) && Number(category.meyerhofIconVersion || 0) < 1) {
      category.meyerhofIconVersion = 1;
      category.imageSource = "catalog";
      delete category.generatedImage;
      delete category.imageGeneratedAt;
      delete category.imageRevision;
      delete category.imageError;
    }
    if (isReweCategoryName(category.name) && Number(category.reweIconVersion || 0) < 1) {
      category.reweIconVersion = 1;
      category.imageSource = "catalog";
      delete category.generatedImage;
      delete category.imageGeneratedAt;
      delete category.imageRevision;
      delete category.imageError;
    }
  });
  const meyerhofCategory = meyerhofCategoryForList({ categories });
  const reweCategory = reweCategoryForList({ categories });
  const retailerCategory = retailerCategoryForList({ categories });
  const loadedProducts = Array.isArray(loaded?.products) ? loaded.products.map((product) => ({ ...product, categoryId: legacyCategoryMap[product.categoryId] || product.categoryId })) : [];
  const deletedProductKeys = Array.isArray(loaded?.deletedProductKeys) ? [...new Set(loaded.deletedProductKeys.map(normalizeText).filter(Boolean))] : [];
  let products = [...loadedProducts, ...(includeCatalog ? base.products : []).filter((seed) => !deletedProductKeys.includes(normalizeText(seed.key)) && !loadedProducts.some((product) => product.id === seed.id || product.key === seed.key))];

  // 0.3.51: Frühere fehlerhafte Firma-Imports wie „Butter 10x Firma“ oder
  // „Bananen 15x Firma“ werden auf eine echte Zielvariante bereinigt. Der
  // vorhandene Grundartikel bleibt in seiner normalen Kategorie erhalten; die
  // Firma-Variante erhält dessen Bild/Stammdaten ohne neuen KI-Lauf.
  const firmaCategory = firmaCategoryForList({ categories });
  const firmaRepairs = new Map();
  if (firmaCategory) {
    const targetSourceTag = `category:${firmaCategory.id}`;
    for (const product of [...products]) {
      if (!product) continue;
      const rawFirmaName = String(product.name || product.key || "");
      const strongCorruptFirma = /\b(?:\d+(?:[.,]\d+)?|ein|eine|eins|zwei|drei|vier|fünf|fuenf|sechs|sieben|acht|neun|zehn)\s*(?:x|mal|stück|stueck|stk)\s+firma\s*$/i.test(rawFirmaName);
      const spokenFirma = parseSpokenFirmaInput(rawFirmaName, { categories });
      if (!spokenFirma) continue;
      if (product.classificationSource === "manual" && !strongCorruptFirma) continue;
      const incomingBase = spokenFirma.inheritFromName || spokenFirma.parsed?.name || "";
      const baseKey = normalizeText(incomingBase);
      if (!baseKey) continue;

      const baseProduct = products.find((other) => other !== product && !other?._removeAfterFirmaRepair && !other?.sourceTag && productSearchKeys(other).includes(baseKey));
      let targetProduct = products.find((other) => other !== product && !other?._removeAfterFirmaRepair && other.categoryId === firmaCategory.id && other.sourceTag === targetSourceTag && productSearchKeys(other).includes(baseKey));

      if (!targetProduct && baseProduct) {
        const canonicalName = baseProduct.name || incomingBase;
        const visual = inferVisual(canonicalName, firmaCategory.id);
        targetProduct = {
          id: id("product"),
          key: productKeyForCategory(canonicalName, firmaCategory.id, products, "", true),
          name: canonicalName,
          categoryId: firmaCategory.id,
          icon: baseProduct.icon || categoryIcon(firmaCategory.id),
          aliases: [...new Set([...(Array.isArray(baseProduct.aliases) ? baseProduct.aliases : []), normalizeText(baseProduct.name), baseKey].filter(Boolean))],
          favorite: false,
          useCount: 0,
          defaultQuantity: normalizeDefaultQuantity(baseProduct.defaultQuantity),
          classificationSource: "inherited",
          sourceTag: targetSourceTag,
          ...visual,
          imageKey: baseProduct.imageKey || imageKeyForProduct(canonicalName, baseProduct.categoryId),
          imageSource: "catalog",
          clonedFromProductId: baseProduct.id,
        };
        targetProduct.visualBase = baseProduct.visualBase || targetProduct.visualBase;
        targetProduct.visualMotif = baseProduct.visualMotif || targetProduct.visualMotif;
        targetProduct.visualLabel = baseProduct.visualLabel ?? targetProduct.visualLabel ?? "";
        targetProduct.visualSource = baseProduct.visualSource || targetProduct.visualSource || "automatic";
        if (!copyProcessedImageToProduct(baseProduct, targetProduct)) {
          const generated = productGeneratedImageFile(baseProduct);
          if (generated) {
            targetProduct.generatedImage = baseProduct.generatedImage;
            targetProduct.imageSource = "inherited";
            targetProduct.iconEditStatus = "processed";
            targetProduct.imageGeneratedAt = baseProduct.imageGeneratedAt || new Date().toISOString();
            targetProduct.imageRevision = baseProduct.imageRevision || Date.now();
            targetProduct.isCustomImage = true;
          } else {
            targetProduct.imageSource = baseProduct.imageSource && !["pending", "error"].includes(baseProduct.imageSource) ? baseProduct.imageSource : "catalog";
            targetProduct.iconEditStatus = iconEditState(baseProduct) === "processed" ? "processed" : "unprocessed";
          }
        }
        delete targetProduct.imageGenerationVersion;
        delete targetProduct.imageRequestedManually;
        products.push(targetProduct);
      }

      if (!targetProduct) {
        // Falls kein Grundartikel vorhanden ist, wird der alte Datensatz selbst nur
        // bereinigt. Sein vorhandenes Bild bleibt erhalten; es wird kein neuer Lauf
        // allein durch die Migration gestartet.
        const oldName = product.name || product.key;
        product.aliases = [...new Set([...(Array.isArray(product.aliases) ? product.aliases : []), normalizeText(oldName), baseKey].filter(Boolean))];
        product.name = incomingBase;
        product.categoryId = firmaCategory.id;
        product.sourceTag = targetSourceTag;
        product.classificationSource = product.classificationSource === "manual" ? "manual" : "rule";
        product.key = productKeyForCategory(incomingBase, firmaCategory.id, products, product.id, true);
        delete product.imageGenerationVersion;
        targetProduct = product;
      } else if (targetProduct !== product) {
        targetProduct.aliases = [...new Set([...(Array.isArray(targetProduct.aliases) ? targetProduct.aliases : []), normalizeText(product.name || product.key), ...(Array.isArray(product.aliases) ? product.aliases : [])].filter(Boolean))];
        targetProduct.useCount = Number(targetProduct.useCount || 0) + Number(product.useCount || 0);
        product._removeAfterFirmaRepair = true;
      }

      firmaRepairs.set(product.id, {
        targetId: targetProduct.id,
        recoveredQuantity: spokenFirma.parsed.quantity || null,
        entryCategoryId: firmaCategory.id,
      });
    }
    if ([...firmaRepairs.values()].length) products = products.filter((product) => !product?._removeAfterFirmaRepair);
  }

  for (const product of products) {
    const previousFriendlyName = product.name || product.key;
    const cleanedFriendlyName = friendlyProductName(previousFriendlyName);
    if (cleanedFriendlyName && cleanedFriendlyName !== previousFriendlyName) {
      product.aliases = [...new Set([...(Array.isArray(product.aliases) ? product.aliases : []), normalizeText(previousFriendlyName)].filter(Boolean))];
      product.name = cleanedFriendlyName;
      product.key = normalizeText(cleanedFriendlyName) || product.key;
    }
    if (meyerhofCategory) {
      const tagged = stripMeyerhofTag(product.name || product.key);
      if (tagged.tagged) {
        const oldName = product.name || tagged.rawName;
        product.aliases = [...new Set([...(Array.isArray(product.aliases) ? product.aliases : []), normalizeText(oldName), normalizeText(tagged.rawName)].filter(Boolean))];
        product.name = tagged.name;
        product.categoryId = meyerhofCategory.id;
        product.sourceTag = "meyerhof";
        if (product.classificationSource !== "manual") product.classificationSource = "rule";
      } else if (product.categoryId === meyerhofCategory.id) {
        product.sourceTag = product.sourceTag || "meyerhof";
      }
    }
    if (reweCategory && product.sourceTag !== "meyerhof") {
      let tagged = stripReweTag(product.name || product.key);
      if (!tagged.tagged) {
        for (const alias of (Array.isArray(product.aliases) ? product.aliases : [])) {
          tagged = stripReweTag(alias);
          if (tagged.tagged) break;
        }
      }
      if (tagged.tagged && product.classificationSource !== "manual") {
        const oldName = product.name || tagged.rawName;
        product.aliases = [...new Set([...(Array.isArray(product.aliases) ? product.aliases : []), normalizeText(oldName), normalizeText(tagged.rawName), normalizeText(tagged.name)].filter(Boolean))];
        product.name = tagged.name;
        // Der interne Schlüssel behält REWE, damit z. B. normaler Gouda und REWE-Gouda getrennte Stammartikel bleiben.
        product.key = normalizeText(tagged.rawName) || product.key;
        product.categoryId = reweCategory.id;
        product.sourceTag = "rewe";
        product.classificationSource = "rule";
      } else if (product.categoryId === reweCategory.id && product.sourceTag === "rewe") {
        product.sourceTag = "rewe";
      }
    }
    if (retailerCategory && product.sourceTag !== "meyerhof" && product.sourceTag !== "rewe" && product.classificationSource !== "manual") {
      let tagged = extractRetailerTag(product.name || product.key);
      if (!tagged.tagged) {
        for (const alias of (Array.isArray(product.aliases) ? product.aliases : [])) {
          tagged = extractRetailerTag(alias);
          if (tagged.tagged) break;
        }
      }
      if (tagged.tagged) {
        const oldName = product.name || tagged.rawName;
        product.aliases = [...new Set([...(Array.isArray(product.aliases) ? product.aliases : []), normalizeText(oldName), normalizeText(tagged.rawName), normalizeText(tagged.name)].filter(Boolean))];
        product.name = tagged.name;
        product.key = normalizeText(tagged.name) || product.key;
        product.categoryId = retailerCategory.id;
        product.sourceTag = `retailer:${normalizeText(tagged.storeLabel).replace(/\s+/g, "-")}`;
        product.classificationSource = "rule";
        if (!product.generatedImage && !["gemini", "upload"].includes(product.imageSource)) {
          product.imageSource = "pending";
          product.iconEditStatus = "unprocessed";
          product.imageGenerationVersion = VERSION;
          delete product.imageError;
        }
      } else if (product.categoryId === retailerCategory.id && /^retailer:/.test(String(product.sourceTag || ""))) {
        product.sourceTag = product.sourceTag;
      }
    }
    const catalog = base.products.find((item) => item.id === product.id || item.key === product.key);
    if (catalog && (!product.categoryId || ["grain"].includes(product.categoryId))) product.categoryId = catalog.categoryId;
    if (["reis", "nudeln"].includes(product.key) && product.categoryId === "vegetarian" && product.classificationSource !== "manual") product.categoryId = "pasta_rice";
    if (shouldMoveHouseholdCleaningToDrugstore(product) && categories.some((category) => category.id === "drugstore")) product.categoryId = "drugstore";
    if (FREEZER_BAG_PATTERN.test(normalizeText(product.name || product.key)) && product.classificationSource !== "manual" && categories.some((category) => category.id === "household")) { product.categoryId = "household"; if (product.classificationSource !== "manual") product.classificationSource = "rule"; }
    if (product.iconEditStatus === "processing") product.iconEditStatus = "unprocessed";
    improveProduct(product, categories);
    product.iconHint = String(product.iconHint || "").trim();
    product.defaultQuantity = normalizeDefaultQuantity(product.defaultQuantity);
    product.aliases = [...new Set((Array.isArray(product.aliases) ? product.aliases : []).map(normalizeText).filter(Boolean))];
    const canonicalAlias = normalizeText(product.name || product.key);
    if (canonicalAlias && !product.aliases.includes(canonicalAlias)) product.aliases.push(canonicalAlias);
    product.favorite = Boolean(product.favorite); product.useCount = Number(product.useCount || 0);
  }
  const entries = Array.isArray(loaded?.entries) ? loaded.entries.map((entry) => {
    let migrated = migrateEntryProductDetail(migrateEntryNote(recoverMissingQuantity({ ...entry, categoryId: legacyCategoryMap[entry.categoryId] || entry.categoryId })));
    const firmaRepair = firmaRepairs.get(migrated.productId);
    if (firmaRepair) {
      const targetProduct = products.find((item) => item.id === firmaRepair.targetId);
      if (targetProduct) {
        migrated = { ...migrated, productId: targetProduct.id, productKey: targetProduct.key, name: targetProduct.name, categoryId: firmaRepair.entryCategoryId || targetProduct.categoryId };
        if (!hasStoredQuantity(migrated.quantity) && hasStoredQuantity(firmaRepair.recoveredQuantity)) migrated.quantity = { ...firmaRepair.recoveredQuantity };
      }
    }
    const product = products.find((item) => item.id === migrated.productId || item.key === migrated.productKey);
    if (product && ["reis", "nudeln"].includes(product.key) && migrated.categoryId === "vegetarian") migrated.categoryId = "pasta_rice";
    if (product && product.categoryId === "drugstore" && migrated.categoryId === "household" && product.classificationSource !== "manual" && CLEANING_PRODUCT_PATTERN.test(normalizeText([product.name, product.key, ...(product.aliases || [])].filter(Boolean).join(" ")))) migrated.categoryId = "drugstore";
    if (product && product.categoryId === "household" && FREEZER_BAG_PATTERN.test(normalizeText(product.name || product.key)) && migrated.categoryId !== "household" && product.classificationSource !== "manual") migrated.categoryId = "household";
    if (product) migrated = { ...migrated, name: product.name, productKey: product.key };
    if (["meyerhof", "rewe"].includes(product?.sourceTag) || /^retailer:/.test(String(product?.sourceTag || ""))) migrated = { ...migrated, categoryId: product.categoryId };
    return migrated;
  }) : [];
  const recent = Array.isArray(loaded?.recent) ? loaded.recent.map((entry) => {
    let migrated = migrateEntryProductDetail(migrateEntryNote(recoverMissingQuantity(entry)));
    const firmaRepair = firmaRepairs.get(migrated.productId);
    if (firmaRepair) {
      const targetProduct = products.find((item) => item.id === firmaRepair.targetId);
      if (targetProduct) {
        migrated = { ...migrated, productId: targetProduct.id, productKey: targetProduct.key, name: targetProduct.name, categoryId: firmaRepair.entryCategoryId || targetProduct.categoryId };
        if (!hasStoredQuantity(migrated.quantity) && hasStoredQuantity(firmaRepair.recoveredQuantity)) migrated.quantity = { ...firmaRepair.recoveredQuantity };
      }
    }
    const product = products.find((item) => item.id === migrated.productId || item.key === migrated.productKey);
    if (product) migrated = { ...migrated, name: product.name, productKey: product.key };
    if (["meyerhof", "rewe"].includes(product?.sourceTag) || /^retailer:/.test(String(product?.sourceTag || ""))) migrated = { ...migrated, categoryId: product.categoryId };
    return migrated;
  }) : [];
  return { categories, products, entries, recent, undo: loaded?.undo || null, learningExamples: Array.isArray(loaded?.learningExamples) ? loaded.learningExamples.slice(-80) : [], deletedProductKeys };
}

function migrateState(loaded) {
  const base = initialState();
  const retryLegacyImageErrors = Boolean(loaded?.version) && String(loaded.version) !== VERSION;
  let lists;
  if (Array.isArray(loaded?.lists) && loaded.lists.length) {
    lists = loaded.lists.map((raw, index) => {
      const data = migrateCollection(raw, raw.id === DEFAULT_LIST_ID, true);
      const standardCategoryIds = categorySeed.map((category) => category.id).join(",");
      const loadedCategoryIds = data.categories.slice().sort((a, b) => a.sort - b.sort).map((category) => category.id).join(",");
      const looksLikeEmptyPre021List = raw.id !== DEFAULT_LIST_ID && !raw.categoryMode && loadedCategoryIds === standardCategoryIds && (raw.products || []).length <= 1 && (raw.entries || []).length <= 1;
      if (looksLikeEmptyPre021List) {
        data.categories = [clone(categorySeed.find((category) => category.id === "other"))];
        for (const product of data.products) { product.categoryId = "other"; product.icon = categoryIcon("other"); }
        for (const entry of data.entries) entry.categoryId = "other";
      }
      return { id: raw.id || id("list"), name: raw.name || `Einkaufsliste ${index + 1}`, color: validColor(raw.color) || DEFAULT_LIST_COLOR, sort: Number(raw.sort ?? index), categoryMode: raw.categoryMode || (looksLikeEmptyPre021List ? "empty" : "copied"), ...data };
    });
  } else {
    const data = migrateCollection(loaded, true);
    lists = [listRecord(DEFAULT_LIST_ID, loaded?.listName || DEFAULT_LIST_NAME, DEFAULT_LIST_COLOR, data)];
  }
  lists.sort((a, b) => a.sort - b.sort).forEach((list, index) => { list.sort = index; });
  if (retryLegacyImageErrors) {
    for (const list of lists) for (const product of list.products || []) {
      if (!product || product.generatedImage || !["pending", "error"].includes(product.imageSource)) continue;
      product.imageKey = imageKeyForProduct(product.name || product.key, product.categoryId);
      const normalizedName = normalizeText(product.name || product.key);
      const retailerPending = /^retailer:/.test(String(product.sourceTag || "")) && !product.generatedImage;
      const legacyUnknown = product.imageKey === "misc" || /^flaschen?$/.test(normalizedName);
      if (retailerPending || legacyUnknown) {
        product.imageSource = "pending";
        product.imageGenerationVersion = VERSION;
        delete product.imageError;
      } else {
        product.imageSource = "catalog";
        delete product.imageError;
        delete product.imageGenerationVersion;
      }
    }
  }
  const activeListId = lists.some((list) => list.id === loaded?.activeListId) ? loaded.activeListId : lists[0].id;
  const active = lists.find((list) => list.id === activeListId) || lists[0];
  const syncListId = lists.some((list) => list.id === loaded?.syncListId) ? loaded.syncListId : activeListId;
  const remindersSync = loaded?.remindersSync && typeof loaded.remindersSync === "object" ? loaded.remindersSync : {};
  remindersSync.importedIds = remindersSync.importedIds && typeof remindersSync.importedIds === "object" ? remindersSync.importedIds : {};
  return { ...base, ...loaded, version: VERSION, lists, activeListId, syncListId, remindersSync,
    categories: active.categories, products: active.products, entries: active.entries, recent: active.recent, undo: active.undo || null,
    learningExamples: active.learningExamples || [], deletedProductKeys: active.deletedProductKeys || [], geminiImageUsage: normalizeGeminiImageUsage(loaded?.geminiImageUsage) };
}

function latestValidBackup() {
  if (!fs.existsSync(BACKUP_DIR)) return null;
  const candidates = fs.readdirSync(BACKUP_DIR)
    .filter((name) => /^einkaufsliste-\d{4}-\d{2}-\d{2}\.json$/.test(name))
    .map((name) => {
      const file = path.join(BACKUP_DIR, name);
      try { return { file, mtime: fs.statSync(file).mtimeMs }; } catch { return null; }
    })
    .filter(Boolean)
    .sort((a, b) => b.mtime - a.mtime);
  for (const candidate of candidates) {
    try {
      return { file: candidate.file, data: JSON.parse(fs.readFileSync(candidate.file, "utf8")) };
    } catch { /* nächstes Backup prüfen */ }
  }
  return null;
}

function safeFileToken(value) {
  return String(value || "unknown").trim().replace(/[^a-zA-Z0-9._-]+/g, "-").replace(/^-+|-+$/g, "") || "unknown";
}

function backupTimestamp(date = new Date()) {
  return date.toISOString().replace(/:/g, "-");
}

function rawHash(raw) {
  return crypto.createHash("sha256").update(raw).digest("hex").slice(0, 12);
}

function createPreMigrationBackup(raw, loaded) {
  const fromVersion = safeFileToken(loaded?.version || "unknown");
  const toVersion = safeFileToken(VERSION);
  const hash = rawHash(raw);
  fs.mkdirSync(BACKUP_DIR, { recursive: true });
  const target = path.join(BACKUP_DIR, `pre-migration-${fromVersion}-to-${toVersion}-${hash}.json`);
  if (!fs.existsSync(target)) fs.writeFileSync(target, raw, { mode: 0o600 });
  return target;
}

function createRestoreSafetyBackup() {
  fs.mkdirSync(BACKUP_DIR, { recursive: true });
  saveActiveList();
  const raw = fs.existsSync(DATA_FILE) ? fs.readFileSync(DATA_FILE, "utf8") : JSON.stringify(backupPayload(), null, 2);
  const target = path.join(BACKUP_DIR, `pre-restore-${backupTimestamp()}-${rawHash(raw)}.json`);
  fs.writeFileSync(target, raw, { mode: 0o600, flag: "wx" });
  return target;
}

function latestBackupFile(pattern) {
  if (!fs.existsSync(BACKUP_DIR)) return null;
  return fs.readdirSync(BACKUP_DIR)
    .filter((name) => pattern.test(name))
    .map((name) => {
      const file = path.join(BACKUP_DIR, name);
      try { const stat = fs.statSync(file); return { name, modifiedAt: stat.mtime.toISOString(), mtime: stat.mtimeMs }; } catch { return null; }
    })
    .filter(Boolean)
    .sort((a, b) => b.mtime - a.mtime)[0] || null;
}

function backupStatus() {
  return {
    daily: latestBackupFile(/^einkaufsliste-\d{4}-\d{2}-\d{2}\.json$/),
    preMigration: latestBackupFile(/^pre-migration-.*\.json$/),
    preRestore: latestBackupFile(/^pre-restore-.*\.json$/),
  };
}

function loadState() {
  const dataExists = fs.existsSync(DATA_FILE);
  if (dataExists) {
    let raw;
    let loaded;
    try {
      raw = fs.readFileSync(DATA_FILE, "utf8");
      loaded = JSON.parse(raw);
    } catch (error) {
      const backup = latestValidBackup();
      if (backup) {
        console.error(`Datenbestand konnte nicht geladen werden; verwende Backup ${path.basename(backup.file)}: ${error.message}`);
        return migrateState(backup.data);
      }
      throw new Error(`Datenbestand ${DATA_FILE} konnte nicht geladen werden: ${error.message}`);
    }

    if (String(loaded?.version || "") !== VERSION) {
      try {
        const backupFile = createPreMigrationBackup(raw, loaded);
        console.log(`Pre-Migration-Sicherung erstellt: ${backupFile}`);
      } catch (error) {
        throw new Error(`Pre-Migration-Sicherung fehlgeschlagen; Datenmigration wurde abgebrochen: ${error.message}`);
      }
    }
    return migrateState(loaded);
  }

  const backup = latestValidBackup();
  if (backup) {
    console.error(`Datenbestand ${DATA_FILE} fehlt; verwende Backup ${path.basename(backup.file)}.`);
    return migrateState(backup.data);
  }
  return initialState();
}

let state = loadState();
let geminiStatus = { state: "idle", item: "", detail: "" };
let imageStatus = { state: "idle", item: "", productId: "", detail: "" };
let appleRemindersSync = null;
let localCaldavSync = null;

function processedIconFor(product) {
  const key = processedIcons[product?.id] ? product.id : "product-" + normalizeText(product?.key || product?.name || "");
  const file = processedIcons[key] || "";
  return file && fs.existsSync(path.join(__dirname, "assets/product-images", file)) ? file : "";
}
function iconEditState(product) {
  if (product.iconEditStatus === "processed" && product.generatedImage && fs.existsSync(path.join(DATA_DIR, product.generatedImage.replace(/^generated-product-images\//, "product-images/")))) return "processed";
  return processedIconFor(product) ? "processed" : "unprocessed";
}
const iconJobs = new Map();

function upgradeIconOnUse(product, list) {
  if (process.env.ICON_TEST_PRODUCT && product.id !== process.env.ICON_TEST_PRODUCT) return;
  if (iconEditState(product) === "processed" || !geminiApiKey() || iconJobs.has(product)) return;
  product.iconEditStatus = "processing";
  const job = Promise.resolve().then(() => generateProductImage(product, list, {force:true})).then(() => {
    product.iconEditStatus = ["gemini", "upload", "inherited"].includes(product.imageSource) ? "processed" : "unprocessed";
    persist();
  }).catch(error => {product.iconEditStatus="unprocessed"; product.imageError=error.message; persist();}).finally(() => iconJobs.delete(product));
  iconJobs.set(product, job);
}

function activeList() { return state.lists.find((list) => list.id === state.activeListId) || state.lists[0]; }

function saveActiveList() {
  const list = activeList();
  if (!list) return;
  list.categories = state.categories; list.products = state.products; list.entries = state.entries; list.recent = state.recent; list.undo = state.undo || null; list.learningExamples = Array.isArray(state.learningExamples) ? state.learningExamples : [];
  list.deletedProductKeys = Array.isArray(state.deletedProductKeys) ? [...new Set(state.deletedProductKeys.filter(Boolean))] : [];
}

function activateList(listId) {
  const next = state.lists.find((list) => list.id === listId);
  if (!next) return false;
  saveActiveList(); state.activeListId = next.id; state.categories = next.categories; state.products = next.products; state.entries = next.entries; state.recent = next.recent; state.undo = next.undo || null; state.learningExamples = Array.isArray(next.learningExamples) ? next.learningExamples : []; state.deletedProductKeys = Array.isArray(next.deletedProductKeys) ? next.deletedProductKeys : [];
  geminiStatus = { state: "idle", item: "", detail: "" };
  imageStatus = { state: "idle", item: "", productId: "", detail: "" };
  return true;
}

function persist() {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  saveActiveList();
  state.updatedAt = new Date().toISOString();
  const temp = `${DATA_FILE}.tmp`;
  fs.writeFileSync(temp, JSON.stringify(state, null, 2), { mode: 0o600 });
  fs.renameSync(temp, DATA_FILE);
}

function backupPayload() {
  return { ...state, version: VERSION, backupCreatedAt: new Date().toISOString() };
}

function dailyBackupName(date = new Date()) {
  return `einkaufsliste-${date.toISOString().slice(0, 10)}.json`;
}

function createDailyBackup() {
  try {
    fs.mkdirSync(BACKUP_DIR, { recursive: true });
    const target = path.join(BACKUP_DIR, dailyBackupName());
    if (!fs.existsSync(target)) fs.writeFileSync(target, JSON.stringify(backupPayload(), null, 2), { mode: 0o600 });
    return target;
  } catch (error) {
    console.error(`Automatisches Backup konnte nicht erstellt werden: ${error.message}`);
    return null;
  }
}

function startDailyBackup() {
  createDailyBackup();
  const timer = setInterval(createDailyBackup, DAILY_BACKUP_INTERVAL_MS);
  timer.unref?.();
  return timer;
}

function id(prefix) { return `${prefix}-${crypto.randomUUID()}`; }

function categoryById(categoryId) { return state.categories.find((category) => category.id === categoryId) || state.categories[state.categories.length - 1]; }
function hasClassifiableCategory() { return state.categories.some((category) => category.id !== "other"); }
function hasClassifiableCategoryFor(list) { return Boolean(list?.categories?.some((category) => category.id !== "other")); }


const LEARNING_STOP_WORDS = new Set(["artikel","produkt","frisch","frische","frischer","frisches","packung","stuck","stueck","einmal","zweimal","klein","gross","groß","normal","natur"]);
function categoryExistsForList(list, categoryId) { return Boolean(list?.categories?.some((category) => category.id === categoryId)); }
function learningTerms(name) {
  const words = normalizeText(name).split(" ").filter((word) => word.length >= 4 && !LEARNING_STOP_WORDS.has(word) && !/^\d+$/.test(word));
  const terms = [...new Set(words)];
  for (let i = 0; i < words.length - 1; i += 1) terms.push(`${words[i]} ${words[i + 1]}`);
  return [...new Set(terms)].slice(0, 12);
}
function recordLearningExampleForList(list, productName, fromCategoryId, toCategoryId) {
  if (!list || !productName || !toCategoryId || fromCategoryId === toCategoryId) return;
  list.learningExamples = Array.isArray(list.learningExamples) ? list.learningExamples : [];
  const normalized = normalizeText(productName);
  const existing = list.learningExamples.find((item) => item.normalized === normalized && item.toCategoryId === toCategoryId);
  if (existing) { existing.count = Number(existing.count || 1) + 1; existing.updatedAt = new Date().toISOString(); existing.fromCategoryId = fromCategoryId || existing.fromCategoryId || "other"; }
  else list.learningExamples.push({ id: id("learn"), productName: firstUpper(productName), normalized, terms: learningTerms(productName), fromCategoryId: fromCategoryId || "other", toCategoryId, count: 1, updatedAt: new Date().toISOString() });
  list.learningExamples = list.learningExamples.slice(-80);
  if (state.activeListId === list.id) state.learningExamples = list.learningExamples;
}
function learnedCategoryForName(itemName, list) {
  const examples = Array.isArray(list?.learningExamples) ? list.learningExamples : [];
  const normalizedItem = normalizeText(itemName);
  const exact = examples
    .filter((example) => example.normalized === normalizedItem && categoryExistsForList(list, example.toCategoryId))
    .sort((a, b) => Number(b.count || 1) - Number(a.count || 1))[0];
  if (exact) return { categoryId: exact.toCategoryId, term: exact.normalized, weight: 100, exact: true };
  const itemTerms = new Set(learningTerms(itemName));
  if (!itemTerms.size || !examples.length) return null;
  const score = new Map();
  const conflicts = new Map();
  for (const example of examples) {
    for (const term of (example.terms || learningTerms(example.productName))) {
      if (!itemTerms.has(term)) continue;
      const key = `${term}|${example.toCategoryId}`;
      score.set(key, (score.get(key) || 0) + Math.max(1, Number(example.count || 1)));
      const cats = conflicts.get(term) || new Set(); cats.add(example.toCategoryId); conflicts.set(term, cats);
    }
  }
  let best = null;
  for (const [key, points] of score.entries()) {
    const split = key.lastIndexOf("|"); const term = key.slice(0, split); const categoryId = key.slice(split + 1);
    const safePhrase = term.includes(" ") && term.length >= 8;
    const requiredPoints = safePhrase ? 1 : 2;
    if (points < requiredPoints || (conflicts.get(term)?.size || 0) > 1 || !categoryExistsForList(list, categoryId)) continue;
    const weight = points * (safePhrase ? 2 : 1);
    if (!best || weight > best.weight) best = { categoryId, term, weight, exact: false };
  }
  return best;
}
function hardCategoryForName(itemName, list) {
  const key = normalizeText(itemName);
  const has = (id) => categoryExistsForList(list, id);
  const frozenHint = /(^| )(tk|tiefkuhl\w*|tiefkuehl\w*|tiefgekuhlt\w*|tiefgekuehlt\w*|gefroren\w*|tiefgefroren\w*)( |$)/.test(key);
  const iceHint = /(^| )(eis|eiscreme|magnum|sorbet|wassereis|cornetto)( |$)/.test(key);
  if (FREEZER_BAG_PATTERN.test(key) && has("household")) return { categoryId: "household", source: "hard-rule", reason: "Gefrier-/Tiefkühlbeutel sind Haushaltsartikel" };
  if (frozenHint && iceHint && has("ice_cream")) return { categoryId: "ice_cream", source: "hard-rule", reason: "Tiefkühl-Eis" };
  if (frozenHint && has("frozen")) return { categoryId: "frozen", source: "hard-rule", reason: "TK/gefroren" };
  return null;
}
function classificationExamplesText(list) {
  const examples = (list?.learningExamples || []).slice(-25);
  if (!examples.length) return "Keine bisherigen manuellen Korrekturen.";
  return examples.map((example) => `- ${example.productName} -> ${example.toCategoryId}`).join("\n");
}
function visualFallbackForProduct(product) {
  return sanitizeVisual(product || {}, inferVisual(product?.name || product?.key || "Artikel", product?.categoryId || "other"));
}
function compactProductKey(value) { return normalizeText(value).replace(/\s+/g, ""); }
function productSearchKeys(product) {
  return [...new Set([product?.key, product?.name, ...(Array.isArray(product?.aliases) ? product.aliases : [])].map(normalizeText).filter(Boolean))];
}
function learnProductAlias(product, incomingName) {
  if (!product) return false;
  const alias = normalizeText(incomingName);
  if (!alias) return false;
  product.aliases = Array.isArray(product.aliases) ? product.aliases.map(normalizeText).filter(Boolean) : [];
  if (product.aliases.includes(alias)) return false;
  product.aliases.push(alias);
  product.aliases = [...new Set(product.aliases)].slice(-40);
  product.aliasUpdatedAt = new Date().toISOString();
  return true;
}
function productForName(name, options = {}) {
  const key = normalizeText(name);
  const sourceTag = String(options.sourceTag || "");
  const categoryId = String(options.forcedCategoryId || options.categoryId || "");
  const choose = (matches) => {
    if (!matches.length) return null;
    if (sourceTag) {
      const tagged = matches.filter((product) => product.sourceTag === sourceTag);
      if (tagged.length === 1) return tagged[0];
      if (tagged.length > 1 && categoryId) {
        const sameCategory = tagged.filter((product) => product.categoryId === categoryId);
        if (sameCategory.length) return sameCategory[0];
      }
      if (categoryId) {
        const sameCategory = matches.filter((product) => product.categoryId === categoryId);
        if (sameCategory.length === 1) return sameCategory[0];
        if (sameCategory.length > 1) return sameCategory.find((product) => !product.sourceTag) || sameCategory[0];
      }
      return null;
    }
    if (categoryId) {
      const ordinarySameCategory = matches.filter((product) => product.categoryId === categoryId && !product.sourceTag);
      if (ordinarySameCategory.length === 1) return ordinarySameCategory[0];
      if (ordinarySameCategory.length > 1) return ordinarySameCategory[0];
      if (options.allowTaggedCategoryMatch) {
        const sameCategory = matches.filter((product) => product.categoryId === categoryId);
        if (sameCategory.length === 1) return sameCategory[0];
      }
      if (options.strictCategory) return null;
    }
    const ordinary = matches.filter((product) => !product.sourceTag);
    if (ordinary.length === 1) return ordinary[0];
    return null;
  };
  const exact = choose(state.products.filter((product) => productSearchKeys(product).includes(key)));
  if (exact) return exact;
  const compact = compactProductKey(name);
  if (compact.length < 5) return null;
  return choose(state.products.filter((product) => productSearchKeys(product).some((candidate) => compactProductKey(candidate) === compact)));
}

function catalogMatchForName(name) {
  const key = normalizeText(name);
  return catalogSeed.find((product) => normalizeText(product.name) === key || normalizeText(product.key) === key || (Array.isArray(product.aliases) && product.aliases.some((alias) => normalizeText(alias) === key)));
}
function processedProductForName(name, products = state.products, options = {}) {
  const key = normalizeText(name);
  if (!key) return null;
  const excludeId = String(options.excludeId || "");
  const matches = (products || []).filter((product) => String(product?.id || "") !== excludeId && productSearchKeys(product).includes(key) && iconEditState(product) === "processed");
  return matches.find((product) => !product.sourceTag) || matches[0] || null;
}
function ordinaryProcessedProductForName(name, products = state.products) {
  const key = normalizeText(name);
  if (!key) return null;
  const matches = (products || []).filter((product) => !product.sourceTag && productSearchKeys(product).includes(key));
  return matches.find((product) => iconEditState(product) === "processed") || null;
}
function copyProcessedImageToProduct(source, target) {
  if (!source || !target || iconEditState(source) !== "processed") return false;
  let sourcePath = "";
  let ext = "";
  const generated = productGeneratedImageFile(source);
  if (generated) { sourcePath = generated.filePath; ext = path.extname(generated.fileName) || ".webp"; }
  if (!sourcePath) {
    const processed = processedIconFor(source);
    if (processed) {
      const candidate = path.join(__dirname, "assets", "product-images", processed);
      if (fs.existsSync(candidate)) { sourcePath = candidate; ext = path.extname(processed) || ".webp"; }
    }
  }
  if (!sourcePath) return false;
  fs.mkdirSync(GENERATED_IMAGE_DIR, { recursive: true });
  const revision = Date.now();
  const fileName = `${safeImageFileStem(target, revision.toString(36))}${ext}`;
  const filePath = path.join(GENERATED_IMAGE_DIR, fileName);
  fs.copyFileSync(sourcePath, filePath);
  target.generatedImage = `generated-product-images/${fileName}`;
  target.imageSource = "inherited";
  target.iconEditStatus = "processed";
  target.imageInheritedFromProductId = source.id;
  target.imageInheritedFromName = source.name;
  target.imageGeneratedAt = new Date(revision).toISOString();
  target.imageRevision = revision;
  target.isCustomImage = true;
  delete target.imageError;
  delete target.imageGenerationVersion;
  delete target.imageRequestedManually;
  return true;
}
function productsShareImageFamily(left, right) {
  if (!left || !right) return false;
  const leftKeys = new Set(productSearchKeys(left));
  return productSearchKeys(right).some((key) => leftKeys.has(key));
}
function processedVariantForProduct(product, products = state.products) {
  if (!product) return null;
  return (products || []).find((candidate) => candidate && candidate.id !== product.id && productsShareImageFamily(product, candidate) && iconEditState(candidate) === "processed") || null;
}
function propagateProcessedImageToVariants(source, list = activeList()) {
  if (!source || !list || iconEditState(source) !== "processed") return false;
  let changed = false;
  for (const target of list.products || []) {
    if (!target || target.id === source.id || iconEditState(target) === "processed") continue;
    if (target.imageSource === "upload") continue;
    if (!productsShareImageFamily(source, target)) continue;
    if (copyProcessedImageToProduct(source, target)) changed = true;
  }
  return changed;
}
const familyImageJobs = new Map();
function productImageFamilyKey(product) {
  return normalizeText(product?.name || product?.key || product?.id || "artikel");
}
async function ensureProductImageOnUse(product, list = activeList()) {
  if (!product || !list) return product;
  const reusable = processedVariantForProduct(product, list.products || state.products);
  if (reusable) {
    if (iconEditState(product) !== "processed") copyProcessedImageToProduct(reusable, product);
    propagateProcessedImageToVariants(reusable, list);
    persist();
    return product;
  }
  if (iconEditState(product) === "processed") {
    if (propagateProcessedImageToVariants(product, list)) persist();
    return product;
  }
  if (!geminiApiKey()) return product;
  const familyKey = productImageFamilyKey(product);
  if (familyImageJobs.has(familyKey)) {
    await familyImageJobs.get(familyKey);
    const source = iconEditState(product) === "processed" ? product : processedVariantForProduct(product, list.products || state.products);
    if (source) {
      if (source.id !== product.id && iconEditState(product) !== "processed") copyProcessedImageToProduct(source, product);
      propagateProcessedImageToVariants(source, list);
      persist();
    }
    return product;
  }
  product.imageSource = "pending";
  product.iconEditStatus = "processing";
  product.imageGenerationVersion = VERSION;
  delete product.imageError;
  persist();
  const job = (async () => {
    await generateProductImage(product, list);
    if (iconEditState(product) === "processed") propagateProcessedImageToVariants(product, list);
    persist();
    return product;
  })().finally(() => familyImageJobs.delete(familyKey));
  familyImageJobs.set(familyKey, job);
  return job;
}

function specialBaseNameForProduct(product) {
  if (!product?.sourceTag) return "";
  if (product.sourceTag === "rewe" || product.sourceTag === "meyerhof") return product.name || "";
  if (/^category:/.test(String(product.sourceTag || ""))) return product.name || "";
  if (/^retailer:/.test(String(product.sourceTag || ""))) {
    const tagged = extractRetailerTag(product.name || product.key || "");
    return tagged.tagged ? (tagged.baseName || tagged.name.replace(/\s*\([^)]*\)\s*$/, "")) : String(product.name || "").replace(/\s*\([^)]*\)\s*$/, "");
  }
  return "";
}
function repairStoreSpecificImageReuse(list) {
  if (!list || !Array.isArray(list.products)) return false;
  let changed = false;
  for (const product of list.products) {
    if (!product?.sourceTag) continue;
    const ownsProcessedImage = ["gemini", "upload", "inherited"].includes(product.imageSource) && iconEditState(product) === "processed";
    if (ownsProcessedImage) continue;
    const baseName = specialBaseNameForProduct(product);
    if (!baseName) continue;
    const source = processedProductForName(baseName, list.products, { excludeId: product.id });
    if (source && copyProcessedImageToProduct(source, product)) { changed = true; continue; }
    if (["pending", "error"].includes(product.imageSource)) continue;
    if (product.imageSource === "catalog" || !product.imageSource) {
      product.imageSource = "pending";
      product.iconEditStatus = "unprocessed";
      product.imageGenerationVersion = VERSION;
      delete product.imageError;
      changed = true;
    }
  }
  return changed;
}
function repairAllStoreSpecificImageReuse() {
  let changed = false;
  for (const list of state.lists || []) if (repairStoreSpecificImageReuse(list)) changed = true;
  if (changed) {
    const active = activeList();
    if (active) { state.categories = active.categories; state.products = active.products; state.entries = active.entries; state.recent = active.recent; state.learningExamples = active.learningExamples || []; }
    persist();
  }
  return changed;
}

function baseProductForSpecial(name, options = {}) {
  const key = normalizeText(name);
  if (!key) return null;
  const targetCategoryId = String(options.forcedCategoryId || "");
  const targetSourceTag = String(options.sourceTag || "");
  const matches = (state.products || []).filter((product) => {
    if (!productSearchKeys(product).includes(key)) return false;
    if (targetCategoryId && product.categoryId === targetCategoryId && targetSourceTag && product.sourceTag === targetSourceTag) return false;
    return true;
  });
  if (!matches.length) return null;
  return matches.find((product) => !product.sourceTag)
    || matches.find((product) => iconEditState(product) === "processed")
    || matches[0];
}

function copyExistingProductMetadata(source, target) {
  if (!source || !target) return false;
  target.defaultQuantity = normalizeDefaultQuantity(source.defaultQuantity);
  target.visualBase = source.visualBase || target.visualBase;
  target.visualMotif = source.visualMotif || target.visualMotif;
  target.visualLabel = source.visualLabel ?? target.visualLabel ?? "";
  target.visualSource = source.visualSource || target.visualSource || "automatic";
  target.icon = source.icon || target.icon;
  target.imageKey = source.imageKey || target.imageKey || imageKeyForProduct(source.name, source.categoryId);
  target.imageInheritedFromProductId = source.id;
  target.imageInheritedFromName = source.name;

  if (copyProcessedImageToProduct(source, target)) return true;

  const generated = productGeneratedImageFile(source);
  if (generated) {
    target.generatedImage = source.generatedImage;
    target.imageSource = "inherited";
    target.iconEditStatus = "processed";
    target.imageGeneratedAt = source.imageGeneratedAt || new Date().toISOString();
    target.imageRevision = source.imageRevision || Date.now();
    target.isCustomImage = true;
    delete target.imageError;
    delete target.imageGenerationVersion;
    delete target.imageRequestedManually;
    return true;
  }

  // Auch bei einem vorhandenen, aber noch nicht individuell bearbeiteten Stammartikel
  // darf keine neue KI nur wegen der Zielvariante starten. Das vorhandene lokale/
  // katalogbasierte Bild wird daher übernommen und als Bestand behandelt.
  target.imageSource = source.imageSource && !["pending", "error"].includes(source.imageSource) ? source.imageSource : "catalog";
  target.iconEditStatus = iconEditState(source) === "processed" ? "processed" : "unprocessed";
  delete target.imageError;
  delete target.imageGenerationVersion;
  delete target.imageRequestedManually;
  return true;
}

function cloneSpecialVariantFromBase(baseProduct, parsed, options, categoryId) {
  const sourceTag = String(options.sourceTag || "");
  const targetName = options.targetKind === "retailer"
    ? friendlyProductName(parsed.name)
    : friendlyProductName(baseProduct?.name || options.inheritFromName || parsed.name);
  const key = options.keyName
    ? normalizeText(options.keyName) || productKeyForCategory(targetName, categoryId, state.products, "", true)
    : productKeyForCategory(targetName, categoryId, state.products, "", true);
  const visual = inferVisual(targetName, categoryId);
  const aliases = [...new Set([
    ...(Array.isArray(baseProduct?.aliases) ? baseProduct.aliases : []),
    normalizeText(baseProduct?.name),
    normalizeText(options.inheritFromName),
    normalizeText(options.lookupName),
    normalizeText(parsed.name),
    normalizeText(targetName),
  ].filter(Boolean))];
  const created = {
    id: id("product"), key, name: targetName, categoryId,
    icon: baseProduct?.icon || categoryIcon(categoryId), aliases,
    favorite: false, useCount: 0, defaultQuantity: normalizeDefaultQuantity(baseProduct?.defaultQuantity),
    classificationSource: "inherited", sourceTag,
    ...visual, imageKey: baseProduct?.imageKey || imageKeyForProduct(targetName, categoryId), imageSource: "catalog",
    clonedFromProductId: baseProduct?.id || "",
  };
  copyExistingProductMetadata(baseProduct, created);
  state.products.push(created);
  return created;
}

function productForParsed(parsed, options = {}) {
  const lookupName = options.lookupName || parsed.name;
  const list = activeList();

  // Normale Eingaben: existierenden Grundartikel immer zuerst verwenden. Dadurch
  // löst z. B. "Butter 10x" weder einen zweiten Stammartikel noch einen KI-Lauf aus.
  if (!options.forcedCategoryId && !options.sourceTag) {
    const existing = productForName(lookupName, options) || productForName(parsed.name, options);
    if (existing) return improveProduct(existing);
  }

  const hard = options.forcedCategoryId ? null : hardCategoryForName(parsed.name, list);
  const learned = (options.forcedCategoryId || hard) ? null : learnedCategoryForName(parsed.name, list);
  const rule = ruleForName(parsed.name);
  const usableRule = rule && state.categories.some((category) => category.id === rule.categoryId) ? rule : null;
  const categoryId = options.forcedCategoryId || hard?.categoryId || learned?.categoryId || usableRule?.categoryId || "other";

  // Explizite Zielvarianten (Firma, REWE, DM/Rossmann/Müller, Meyerhof):
  // 1. vorhandene Zielvariante verwenden,
  // 2. sonst vorhandenen Grundartikel klonen (inkl. Bild/Stammdaten, ohne KI),
  // 3. nur wenn nirgends ein Grundartikel existiert, wirklich neu anlegen.
  if (options.forcedCategoryId || options.sourceTag) {
    const scoped = productForName(lookupName, { ...options, categoryId, strictCategory: true, allowTaggedCategoryMatch: true });
    if (scoped) return improveProduct(scoped);

    const baseName = options.inheritFromName || parsed.name || lookupName;
    const baseProduct = baseProductForSpecial(baseName, { ...options, forcedCategoryId: categoryId });
    if (baseProduct) return cloneSpecialVariantFromBase(baseProduct, parsed, options, categoryId);
  }

  const forceScopedKey = Boolean(options.explicitCategorySuffix || String(options.sourceTag || "").startsWith("category:"));
  const key = options.keyName
    ? normalizeText(options.keyName) || "artikel"
    : productKeyForCategory(lookupName || parsed.name, categoryId, state.products, "", forceScopedKey);
  const visual = inferVisual(parsed.name, categoryId);
  const storeSpecific = Boolean(options.sourceTag);
  const catalogMatch = storeSpecific ? null : catalogMatchForName(parsed.name);
  const aliases = [...new Set([normalizeText(lookupName), normalizeText(parsed.name), normalizeText(options.inheritFromName)].filter(Boolean))];
  const created = { id: id("product"), key, name: friendlyProductName(parsed.name), categoryId, icon: usableRule?.icon || categoryIcon(categoryId), aliases, favorite: false, useCount: 0, defaultQuantity: null,
    classificationSource: options.forcedCategoryId ? "rule" : (hard ? "rule" : (learned ? "learned" : (usableRule ? "rule" : "automatic"))), ...(options.sourceTag ? { sourceTag: options.sourceTag } : {}), ...visual,
    imageKey: catalogMatch?.imageKey || imageKeyForProduct(parsed.name, categoryId), imageSource: catalogMatch ? "catalog" : "pending", ...(catalogMatch ? {} : { imageGenerationVersion: VERSION }) };
  state.products.push(created);
  return created;
}

function entryPayloadFor(list, entry) {
  const product = list?.products?.find((item) => item.id === entry.productId);
  const snapshot = entry?.productSnapshot || {};
  const category = list?.categories?.find((item) => item.id === entry.categoryId) || list?.categories?.[list.categories.length - 1];
  const productName = product?.name || snapshot.name || entry.name;
  return { ...entry, productName, productExists: Boolean(product), icon: product?.icon || snapshot.icon || "?", visualBase: product?.visualBase || snapshot.visualBase || null, visualMotif: product?.visualMotif || snapshot.visualMotif || null, visualLabel: product?.visualLabel || snapshot.visualLabel || "", visualSource: product?.visualSource || snapshot.visualSource || "automatic", imageRevision: product?.imageRevision || snapshot.imageRevision || "", imageKey: product?.imageKey || snapshot.imageKey || imageKeyForProduct(productName || entry.name, product?.categoryId || snapshot.categoryId || entry.categoryId), iconEditStatus: product ? (product.iconEditStatus === "processing" ? "processing" : iconEditState(product)) : "unprocessed", processedIcon: product ? processedIconFor(product) : (snapshot.processedIcon || ""), generatedImage: product?.generatedImage || snapshot.generatedImage || "", imageSource: product?.imageSource || snapshot.imageSource || "catalog", imageError: product?.imageError || snapshot.imageError || "", favorite: Boolean(product?.favorite), useCount: product?.useCount || snapshot.useCount || 0, category };
}

function entryPayload(entry) { return entryPayloadFor({ products: state.products, categories: state.categories }, entry); }

function addEntry(input, options = {}) {
  const list = activeList();
  const rawSpecial = !options.forcedCategoryId && typeof input === "string" ? parseSpecialTargetInput(input, list) : null;
  let parsed = rawSpecial ? rawSpecial.parsed : (typeof input === "string" ? parseItemInput(input) : input);
  parsed = prepareParsedProductDetail(parsed);
  const forcedSpecial = options.forcedCategoryId
    ? explicitCategorySpecial(parsed, list, options.forcedCategoryId, {
        sourceTag: options.sourceTag,
        targetKind: options.targetKind,
        storeLabel: options.storeLabel,
        inheritFromName: options.inheritFromName,
      })
    : null;
  const special = forcedSpecial || rawSpecial || prepareParsedForList(parsed, list);
  parsed = special.parsed;

  // Strukturierte Mengenangaben aus dem Alexa-Sync haben Vorrang, wenn der Rohtext
  // selbst keine bereits eindeutig erkannte Firma-Fehlhörer-Menge enthält.
  const keepSpokenFirmaQuantity = Boolean(special.spokenCategoryAlias && hasStoredQuantity(parsed.quantity));
  if (hasStoredQuantity(options.quantityOverride) && !keepSpokenFirmaQuantity) {
    parsed = { ...parsed, quantity: { ...options.quantityOverride, userEdited: true } };
  }

  const productCountBefore = state.products.length;
  const product = productForParsed(parsed, special);
  const createdProduct = state.products.length > productCountBefore;
  const clonedProduct = createdProduct && product.classificationSource === "inherited";
  const existingProduct = createdProduct ? null : product;
  const aliasLearned = existingProduct ? learnProductAlias(product, special.inheritFromName || special.lookupName || parsed.name) : false;
  if (!iconJobs.has(product)) product.iconEditStatus = iconEditState(product);
  const quantity = effectiveQuantityForProduct(parsed.quantity, product);
  const productDetail = normalizeProductDetail(options.productDetail ?? parsed.productDetail ?? "");

  // Ein Artikel darf innerhalb derselben Zielvariante nur einmal offen sein.
  // Menge, Notiz und Unterteilung (z. B. Hähnchen · Geschnetzeltes) ändern die
  // Artikelidentität nicht. Spezialvarianten besitzen bewusst eigene Produkt-Keys.
  const duplicate = state.entries.find((entry) => entry.productId === product.id || entry.productKey === product.key);
  if (duplicate && !options.allowDuplicate) {
    if (aliasLearned) persist();
    return { duplicate: true, entry: entryPayload(duplicate), createdProduct: false, clonedProduct: false, aliasLearned };
  }

  const entry = {
    id: id("entry"), productId: product.id, productKey: product.key, name: product.name,
    original: parsed.original || special.lookupName || parsed.name, quantity, productDetail,
    note: String(options.note ?? parsed.note ?? "").trim(),
    categoryId: special.entryCategoryId || special.forcedCategoryId || product.categoryId,
    createdAt: new Date().toISOString(),
  };
  product.useCount = (product.useCount || 0) + 1;
  state.entries.push(entry);

  // Bestehende Stammartikel werden beim bloßen Hinzufügen niemals automatisch
  // neu bebildert. KI/Bildverarbeitung ist nur für wirklich neue Grundartikel erlaubt.
  persist();
  return { duplicate: false, entry: entryPayload(entry), createdProduct, clonedProduct, aliasLearned };
}

function quantityFromRequest(value, unit) {
  if (value === "" || value === null) return null;
  const numeric = Number(String(value).replace(",", "."));
  if (!Number.isFinite(numeric) || numeric < 0) return undefined;
  const normalizedUnit = String(unit || "stück").trim();
  return normalizedUnit ? { value: numeric, unit: normalizedUnit } : undefined;
}

function json(res, status, body) {
  res.writeHead(status, { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" });
  res.end(JSON.stringify(body));
}

function readBody(req, maxBytes = 200000) {
  return new Promise((resolve, reject) => {
    let raw = "";
    let tooLarge = false;
    req.on("data", (chunk) => {
      if (tooLarge) return;
      raw += chunk;
      if (Buffer.byteLength(raw, "utf8") > maxBytes) { tooLarge = true; reject(new Error("Anfrage ist zu groß.")); }
    });
    req.on("end", () => {
      if (tooLarge) return;
      try { resolve(raw ? JSON.parse(raw) : {}); } catch { reject(new Error("Ungültiges JSON.")); }
    });
    req.on("error", reject);
  });
}

function publicState() {
  saveActiveList();
  const lists = state.lists.slice().sort((a, b) => a.sort - b.sort).map((list) => ({ id: list.id, name: list.name, color: list.color, sort: list.sort, itemCount: list.entries?.length || 0 }));
  const list = activeList();
  return { version: VERSION, updatedAt: state.updatedAt || null, lists, activeListId: state.activeListId, syncListId: state.syncListId || state.activeListId, list: { id: list.id, name: list.name, color: list.color }, categories: state.categories.slice().sort((a, b) => a.sort - b.sort).map((category) => ({...category, visualKind: categoryVisualKind(category), imageKey: categoryImageKey(category)})), entries: state.entries.map(entryPayload), recent: (state.recent || []).map(entryPayload), products: state.products.map(p => ({...p, iconEditStatus: p.iconEditStatus === "processing" ? "processing" : iconEditState(p), processedIcon: processedIconFor(p)})), undoAvailable: Boolean(state.undo && state.undo.expiresAt >= Date.now()), geminiConfigured: Boolean(geminiApiKey()), geminiStatus, imageStatus, remindersSync: appleRemindersSync ? appleRemindersSync.getStatus() : { state: "starting", detail: "Apple-Erinnerungen werden vorbereitet" }, caldavSync: localCaldavSync ? localCaldavSync.getStatus() : { state: "starting", detail: "CalDAV wird vorbereitet" }, backupStatus: backupStatus(), visualOptions: { bases: VISUAL_BASES, motifs: VISUAL_MOTIFS }, learningExampleCount: Array.isArray(state.learningExamples) ? state.learningExamples.length : 0, geminiImageUsage: publicGeminiImageUsage() };
}

function integrationListState(list) {
  return {
    list: { id: list.id, name: list.name, color: list.color },
    categories: list.categories.slice().sort((a, b) => a.sort - b.sort).map((category) => ({...category, visualKind: categoryVisualKind(category)})),
    entries: list.entries.map((entry) => entryPayloadFor(list, entry)),
    products: list.products,
  };
}

function appOptions() {
  try { return JSON.parse(fs.readFileSync(path.join(DATA_DIR, "options.json"), "utf8")); } catch { return {}; }
}

function syncToken() { return appOptions().sync_token || ""; }

function shortcutToken() { return String(appOptions().shortcut_token || "").trim(); }

function geminiApiKey() { return String(appOptions().gemini_api_key || "").trim(); }

function rememberedAppleReminderIds() {
  const ids = state.remindersSync?.importedIds;
  return ids && typeof ids === "object" ? ids : {};
}

// Apple-Erinnerungen bleiben unverändert. Die UID wird lokal gemerkt, damit ein
// noch offener Eintrag aus Erinnerungen nicht bei jedem Minutenabgleich erneut
// importiert wird. Der Speicher wird begrenzt, damit er nicht dauerhaft wächst.
function rememberAppleReminderIds(ids) {
  if (!state.remindersSync || typeof state.remindersSync !== "object") state.remindersSync = {};
  const known = rememberedAppleReminderIds();
  const now = new Date().toISOString();
  for (const idValue of ids) {
    const id = String(idValue || "").trim();
    if (id) known[id] = now;
  }
  const retained = Object.entries(known).sort((a, b) => String(b[1]).localeCompare(String(a[1]))).slice(0, 1000);
  state.remindersSync.importedIds = Object.fromEntries(retained);
}

async function importAppleReminders(items, targetListId) {
  const target = state.lists.find((list) => list.id === targetListId) || state.lists.find((list) => list.id === state.syncListId) || activeList();
  if (!target) throw new Error("Ziel-Einkaufsliste nicht gefunden");
  const known = rememberedAppleReminderIds();
  const pending = (items || []).filter((item) => item?.id && item?.name && !known[String(item.id)]);
  if (!pending.length) return { added: 0, duplicates: 0 };
  const previousListId = state.activeListId;
  let added = 0;
  let duplicates = 0;
  const importedIds = [];
  try {
    activateList(target.id);
    for (const item of pending) {
      try {
        const result = addEntry(String(item.name));
        if (result.duplicate) duplicates += 1;
        else {
          added += 1;
          void processCreatedProduct(result, target.id).catch((error) => {
            imageStatus = { state: "error", item: result.entry?.productName || result.entry?.name || "Artikel", productId: result.entry?.productId || "", detail: error.message };
            console.error(`Hintergrund-Verarbeitung für Apple-Erinnerung fehlgeschlagen: ${error.message}`);
          });
        }
        importedIds.push(String(item.id));
      } catch (error) {
        console.error(`Apple-Erinnerung konnte nicht importiert werden: ${error.message}`);
      }
    }
  } finally {
    if (previousListId !== target.id) activateList(previousListId);
    rememberAppleReminderIds(importedIds);
    persist();
  }
  return { added, duplicates };
}

async function importLocalCaldavReminders(items, targetListId) {
  return importAppleReminders((items || []).map((item) => ({ ...item, id: `caldav:${item.id}` })), targetListId);
}

function safeImageFileStem(product, revision = "") {
  const base = String(product.id || "product").replace(/[^a-zA-Z0-9_-]/g, "_");
  return `${base}${revision ? `-${revision}` : ""}`;
}
function detectGeneratedImageExtension(buffer) {
  if (!buffer || buffer.length < 4) return ".jpg";
  if (buffer[0] === 0xff && buffer[1] === 0xd8) return ".jpg";
  if (buffer[0] === 0x89 && buffer[1] === 0x50 && buffer[2] === 0x4e && buffer[3] === 0x47) return ".png";
  if (buffer[0] === 0x52 && buffer[1] === 0x49 && buffer[2] === 0x46 && buffer[3] === 0x46) return ".webp";
  return ".jpg";
}

const ICON_UPLOAD_MAX_BYTES = 3 * 1024 * 1024;
function decodeUploadedIcon(dataUrl) {
  const raw = String(dataUrl || "").trim();
  const match = raw.match(/^data:image\/(png|jpe?g|webp);base64,([A-Za-z0-9+/=\r\n]+)$/i);
  if (!match) throw new Error("Bitte eine PNG-, JPEG- oder WebP-Bilddatei auswählen.");
  const buffer = Buffer.from(match[2].replace(/\s+/g, ""), "base64");
  if (!buffer.length || buffer.length > ICON_UPLOAD_MAX_BYTES) throw new Error("Das vorbereitete Icon ist zu groß. Maximal 3 MB sind erlaubt.");
  const isPng = buffer.length >= 8 && buffer.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]));
  const isJpeg = buffer.length >= 4 && buffer[0] === 255 && buffer[1] === 216 && buffer[2] === 255 && buffer.lastIndexOf(Buffer.from([255,217])) > 0;
  const isWebp = buffer.length >= 12 && buffer.toString("ascii", 0, 4) === "RIFF" && buffer.toString("ascii", 8, 12) === "WEBP";
  if (!isPng && !isJpeg && !isWebp) throw new Error("Die ausgewählte Datei enthält kein gültiges PNG-, JPEG- oder WebP-Bild.");
  return { buffer, ext: isPng ? ".png" : (isWebp ? ".webp" : ".jpg") };
}
function productGeneratedImageFile(product) {
  const rel = String(product?.generatedImage || "");
  if (!rel.startsWith("generated-product-images/")) return null;
  const fileName = path.basename(rel);
  const filePath = path.join(GENERATED_IMAGE_DIR, fileName);
  return fs.existsSync(filePath) ? { fileName, filePath } : null;
}
function saveUploadedProductImage(productId, dataUrl) {
  const product = state.products.find((item) => item.id === productId);
  if (!product) throw new Error("Artikel nicht gefunden.");
  const { buffer, ext } = decodeUploadedIcon(dataUrl);
  fs.mkdirSync(GENERATED_IMAGE_DIR, { recursive: true });
  const revision = Date.now();
  const fileName = `${safeImageFileStem(product, revision.toString(36))}${ext}`;
  const filePath = path.join(GENERATED_IMAGE_DIR, fileName);
  const previous = productGeneratedImageFile(product);
  fs.writeFileSync(filePath + ".tmp", buffer, { mode: 0o600 });
  fs.renameSync(filePath + ".tmp", filePath);
  product.generatedImage = `generated-product-images/${fileName}`;
  product.imageSource = "upload";
  product.iconEditStatus = "processed";
  product.imageGeneratedAt = new Date(revision).toISOString();
  product.imageRevision = revision;
  product.isCustomImage = true;
  delete product.imageError;
  delete product.imageGenerationVersion;
  delete product.imageRequestedManually;
  if (previous && previous.filePath !== filePath) { try { fs.unlinkSync(previous.filePath); } catch {} }
  propagateProcessedImageToVariants(product, activeList());
  persist();
  return product;
}
function saveUploadedCategoryImage(categoryId, dataUrl) {
  const category = state.categories.find((item) => item.id === categoryId);
  if (!category) throw new Error("Kategorie nicht gefunden.");
  const { buffer, ext } = decodeUploadedIcon(dataUrl);
  fs.mkdirSync(GENERATED_CATEGORY_IMAGE_DIR, { recursive: true });
  const revision = Date.now();
  const fileName = `${safeCategoryImageFileStem(category, revision.toString(36))}${ext}`;
  const filePath = path.join(GENERATED_CATEGORY_IMAGE_DIR, fileName);
  const previous = categoryGeneratedImageFile(category);
  fs.writeFileSync(filePath + ".tmp", buffer, { mode: 0o600 });
  fs.renameSync(filePath + ".tmp", filePath);
  category.generatedImage = `generated-category-images/${fileName}`;
  category.imageSource = "upload";
  category.imageGeneratedAt = new Date(revision).toISOString();
  category.imageRevision = revision;
  category.isCustomImage = true;
  delete category.imageError;
  if (previous && previous.filePath !== filePath) { try { fs.unlinkSync(previous.filePath); } catch {} }
  persist();
  return category;
}
function generatedImageCandidateNames(product, revision = "") {
  const stem = safeImageFileStem(product, revision);
  return [".png", ".jpg", ".jpeg", ".webp"].map((ext) => `${stem}${ext}`);
}
function existingGeneratedImageFile(product) {
  for (const fileName of generatedImageCandidateNames(product)) {
    const filePath = path.join(GENERATED_IMAGE_DIR, fileName);
    if (fs.existsSync(filePath)) return { fileName, filePath };
  }
  return null;
}
function interactionImageData(payload) {
  for (const block of payload?.outputs || []) if (block?.type === "image" && block?.data) return block.data;
  if (payload?.output_image?.data) return payload.output_image.data;
  for (const step of payload?.steps || []) {
    if (step?.type !== "model_output") continue;
    for (const block of step?.content || []) if (block?.type === "image" && block?.data) return block.data;
  }
  return "";
}
function legacyImageData(payload) {
  for (const part of payload?.candidates?.[0]?.content?.parts || []) {
    const data = part?.inlineData?.data || part?.inline_data?.data;
    if (data) return data;
  }
  return "";
}
async function requestGeminiProductImage(apiKey, prompt, signal) {
  // Für Gemini-3-Bildmodelle reicht die Interactions-API ohne response_format.
  // Die zuvor verwendeten response_format-Felder lösten HTTP-400-Fehler aus.
  const primary = await fetch("https://generativelanguage.googleapis.com/v1beta/interactions", {
    method: "POST",
    headers: { "content-type": "application/json", "x-goog-api-key": apiKey },
    body: JSON.stringify({
      model: GEMINI_IMAGE_MODEL,
      input: [{ type: "text", text: prompt }]
    }),
    signal,
  });
  if (primary.ok) {
    const payload = await primary.json();
    const data = interactionImageData(payload);
    if (data) return { data, apiUsage: normalizeImageApiUsage(payload, "interactions") };
    throw new Error("Gemini Interactions API hat kein Bild zurückgegeben.");
  }

  const primaryDetail = (await primary.text()).slice(0, 260);
  const fallback = await fetch(`https://generativelanguage.googleapis.com/v1/models/${GEMINI_IMAGE_MODEL}:generateContent`, {
    method: "POST",
    headers: { "content-type": "application/json", "x-goog-api-key": apiKey },
    body: JSON.stringify({
      contents: [{ parts: [{ text: prompt }] }],
      generationConfig: { responseModalities: ["IMAGE"] }
    }),
    signal,
  });
  if (!fallback.ok) {
    const fallbackDetail = (await fallback.text()).slice(0, 260);
    throw new Error(`Gemini Bild-API fehlgeschlagen. Interactions HTTP ${primary.status}: ${primaryDetail}; GenerateContent HTTP ${fallback.status}: ${fallbackDetail}`);
  }
  const payload = await fallback.json();
  const data = legacyImageData(payload);
  if (!data) throw new Error("Gemini GenerateContent hat kein Bild zurückgegeben.");
  return { data, apiUsage: normalizeImageApiUsage(payload, "generateContent") };
}
const generationJobs = new Map();
let generationQueue = Promise.resolve();
function generateProductImage(product, list = activeList(), options = {}) {
  if (generationJobs.has(product)) return generationJobs.get(product);
  const job = generationQueue.then(() => generateProductImageNow(product, list, options));
  generationJobs.set(product, job);
  generationQueue = job.catch(() => {});
  job.finally(() => generationJobs.delete(product)).catch(() => {});
  return job;
}
async function generateProductImageNow(product, list = activeList(), options = {}) {
  if (process.env.ICON_TEST_PRODUCT && product?.id !== process.env.ICON_TEST_PRODUCT) return product;
  const force = Boolean(options.force);
  if (!product || (!force && product.imageSource !== "pending")) return product;
  if (!force) {
    const baseName = specialBaseNameForProduct(product) || product.name || product.key || "";
    const reusable = processedProductForName(baseName, list?.products || state.products, { excludeId: product.id });
    if (reusable && copyProcessedImageToProduct(reusable, product)) {
      imageStatus = { state: "success", item: product.name || "Artikel", productId: String(product.id || ""), detail: `Bereits bearbeitetes Bild aus „${reusable.name}“ übernommen; keine neue KI-Erstellung.` };
      persist();
      return product;
    }
  }
  const apiKey = geminiApiKey();
  const productId = String(product.id || "");
  if (!apiKey) {
    product.imageError = "Gemini ist nicht konfiguriert.";
    imageStatus = { state: "not_configured", item: product.name || "Artikel", productId, detail: product.imageError };
    return product;
  }
  fs.mkdirSync(GENERATED_IMAGE_DIR, { recursive: true });
  const existing = existingGeneratedImageFile(product);
  if (!force && existing) {
    product.generatedImage = `generated-product-images/${existing.fileName}`;
    product.imageSource = "gemini";
    product.iconEditStatus = "processed";
    product.imageRevision = Number(product.imageRevision || Date.now());
    product.isCustomImage = true;
    delete product.imageError;
    imageStatus = { state: "success", item: product.name || "Artikel", productId, detail: "Bereits vorhandenes lokales Gemini-Bild wird wiederverwendet." };
    return product;
  }
  const categoryName = (list?.categories || state.categories).find((c) => c.id === product.categoryId)?.name || product.categoryId || "Sonstiges";
  const prompt = `Erzeuge genau EINE freigestellte Produktillustration für eine deutsche Einkaufslisten-App.
Produkt: ${product.name}
Kategorie: ${categoryName}
${product.iconHint ? `Zusätzlicher Icon-Hinweis des Nutzers: ${product.iconHint}\n` : ""}
Vorgaben: quadratisches 1:1-Bild; reinweißer Hintergrund (#FFFFFF); ausschließlich das Produkt selbst, keine Kachel, kein Rahmen, keine Szene, keine Hände und keine Menschen. Das Produkt muss vollständig sichtbar und exakt optisch zentriert sein. Es soll ungefähr 78–84 % der nutzbaren Bildbreite bzw. -höhe ausfüllen und rundherum eine gleichmäßige Randreserve von etwa 8–11 % behalten. Nichts darf angeschnitten sein und es darf nicht winzig mit viel Leerraum dargestellt werden. Freundliche hochwertige Mini-Produktillustration, natürliches Licht, dezenter weicher Bodenschatten, klare natürliche Farben, leicht plastisch und konsistent mit modernen Einkaufslisten-Icons. Keine Markenlogos und keine erfundenen Marken. Keine Schrift, Zahlen oder Logos. Realistischer Mini-Produktfotostil mit natürlichen Materialtexturen, keine flache SVG- oder Vektorgrafik. Frische Ware lose; Tiefkühlware als Tiefkühlverpackung mit Schneeflocke. Verpackung und Inhalt müssen zum Produkt passen. ${product.key === "hefe" ? "Motiv: ein kleiner beige-grauer Frischhefewürfel mit teilweise geöffneter Folie." : ""} Das Produkt muss auch bei 64 px eindeutig erkennbar sein.`;
  imageStatus = { state: "requesting", item: product.name || "Artikel", productId, detail: force ? "Gemini-Icon wird auf ausdrücklichen Wunsch neu erzeugt." : "Neues individuelles Produktbild wird erzeugt." };
  product.imageSource = "pending";
  product.iconEditStatus = "processing";
  product.imageError = "";
  persist();
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000);
    let generated;
    try {
      generated = await requestGeminiProductImage(apiKey, prompt, controller.signal);
    } finally {
      clearTimeout(timeout);
    }
    if (product.imageSource === "upload") {
      imageStatus = { state: "success", item: product.name || "Artikel", productId, detail: "Eigenes hochgeladenes Icon bleibt aktiv; laufende Gemini-Antwort wurde verworfen." };
      return product;
    }
    const buffer = Buffer.from(generated.data, "base64");
    if (buffer.length < 4096) throw new Error("Gemini-Bildantwort ist unerwartet klein.");
    const validImage = buffer.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ||
      (buffer[0] === 255 && buffer[1] === 216 && buffer[2] === 255 && buffer.lastIndexOf(Buffer.from([255,217])) > 0) ||
      (buffer.toString("ascii",0,4) === "RIFF" && buffer.toString("ascii",8,12) === "WEBP");
    if (!validImage) throw new Error("Gemini hat keine gültige PNG-, JPEG- oder WebP-Bilddatei geliefert.");
    const revision = Date.now();
    const ext = detectGeneratedImageExtension(buffer);
    const fileStem = force ? safeImageFileStem(product, revision.toString(36)) : safeImageFileStem(product);
    const fileName = `${fileStem}${ext}`;
    const filePath = path.join(GENERATED_IMAGE_DIR, fileName);
    fs.writeFileSync(filePath + ".tmp", buffer, { mode: 0o600 });
    fs.renameSync(filePath + ".tmp", filePath);
    product.generatedImage = `generated-product-images/${fileName}`;
    product.imageSource = "gemini";
    product.iconEditStatus = "processed";
    product.imageGeneratedAt = new Date(revision).toISOString();
    product.imageRevision = revision;
    product.isCustomImage = true;
    delete product.imageError;
    await recordGeminiImageUsage("product", product.name || "Artikel", generated.apiUsage, new Date(revision));
    propagateProcessedImageToVariants(product, list);
    imageStatus = { state: "success", item: product.name || "Artikel", productId, detail: force ? "Gemini-Icon neu erzeugt und auf weitere unbearbeitete Varianten übertragen." : "Individuelles Bild erzeugt und auf weitere unbearbeitete Varianten übertragen." };
    console.log(`Gemini-Produktbild gespeichert: ${product.name} -> ${fileName}`);
  } catch (error) {
    product.imageSource = "error";
    product.iconEditStatus = "unprocessed";
    product.imageError = error.name === "AbortError" ? "Zeitüberschreitung nach 90 Sekunden." : error.message;
    imageStatus = { state: "error", item: product.name || "Artikel", productId, detail: product.imageError };
    console.error(`Gemini-Bildgenerierung fehlgeschlagen für ${product.name}: ${product.imageError}`);
  }
  return product;
}

async function resumePendingProductImages() {
  if (!geminiApiKey()) return;
  let processed = 0;
  for (const list of state.lists || []) {
    for (const product of list.products || []) {
      if (product.imageSource !== "pending") continue;
      product.imageGenerationVersion = VERSION;
      await generateProductImage(product, list);
      processed += 1;
      persist();
    }
  }
  if (processed) console.log(`Gemini-Bildgenerierung fortgesetzt: ${processed} ausstehende${processed === 1 ? "r" : ""} Artikel verarbeitet.`);
}

function safeCategoryImageFileStem(category, revision = "") {
  const base = String(category?.id || "category").replace(/[^a-zA-Z0-9_-]/g, "_");
  return `${base}${revision ? `-${revision}` : ""}`;
}
function categoryGeneratedImageFile(category) {
  const rel = String(category?.generatedImage || "");
  if (!rel.startsWith("generated-category-images/")) return null;
  const fileName = path.basename(rel);
  const filePath = path.join(GENERATED_CATEGORY_IMAGE_DIR, fileName);
  return fs.existsSync(filePath) ? { fileName, filePath } : null;
}
function generateCategoryImage(category) {
  const job = generationQueue.then(() => generateCategoryImageNow(category));
  generationQueue = job.catch(() => {});
  return job;
}
async function generateCategoryImageNow(category) {
  if (!category) return category;
  const apiKey = geminiApiKey();
  if (!apiKey) throw new Error("Gemini ist nicht konfiguriert.");
  fs.mkdirSync(GENERATED_CATEGORY_IMAGE_DIR, { recursive: true });
  const description = String(category.description || "").trim();
  const prompt = `Erzeuge genau EINE freigestellte Kategorie-Illustration für eine deutsche Einkaufslisten-App.
Kategorie: ${category.name}
Bedeutung der Kategorie: ${description || "Allgemeine Einkaufsartikel dieser Kategorie."}

Vorgaben: quadratisches 1:1-Bild; reinweißer Hintergrund (#FFFFFF); 2 bis 4 typische, klar erkennbare Beispielprodukte dieser Kategorie als harmonische kleine Gruppe; keine Szene, keine Regale, keine Menschen, keine Hände, keine Markenlogos, keine Schrift und keine Zahlen. Hochwertige plastisch-realistische Mini-Produktillustration mit natürlichen Farben, weichem Studioschatten und großzügigem weißen Rand. Die Motive müssen die BESCHREIBUNG der Kategorie treffen. Für Haushalt-Produkte insbesondere Verpackungs-/Haushaltsartikel und kleine Haushalts-/Elektroartikel zeigen, keine Putzmittelflaschen. Für Drogerie dürfen Reinigungs-, Wasch-, Hygiene- und Pflegeprodukte gezeigt werden.`;
  category.imageSource = "pending";
  delete category.imageError;
  try {
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 90000);
    let generated;
    try { generated = await requestGeminiProductImage(apiKey, prompt, controller.signal); }
    finally { clearTimeout(timeout); }
    if (category.imageSource === "upload") return category;
    const buffer = Buffer.from(generated.data, "base64");
    if (buffer.length < 4096) throw new Error("Gemini-Bildantwort ist unerwartet klein.");
    const validImage = buffer.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10])) ||
      (buffer[0] === 255 && buffer[1] === 216 && buffer[2] === 255 && buffer.lastIndexOf(Buffer.from([255,217])) > 0) ||
      (buffer.toString("ascii",0,4) === "RIFF" && buffer.toString("ascii",8,12) === "WEBP");
    if (!validImage) throw new Error("Gemini hat keine gültige PNG-, JPEG- oder WebP-Bilddatei geliefert.");
    const revision = Date.now();
    const ext = detectGeneratedImageExtension(buffer);
    const fileName = `${safeCategoryImageFileStem(category, revision.toString(36))}${ext}`;
    const filePath = path.join(GENERATED_CATEGORY_IMAGE_DIR, fileName);
    fs.writeFileSync(filePath + ".tmp", buffer, { mode: 0o600 });
    fs.renameSync(filePath + ".tmp", filePath);
    const previous = categoryGeneratedImageFile(category);
    category.generatedImage = `generated-category-images/${fileName}`;
    category.imageSource = "gemini";
    category.imageGeneratedAt = new Date(revision).toISOString();
    category.imageRevision = revision;
    delete category.imageError;
    if (previous && previous.filePath !== filePath) { try { fs.unlinkSync(previous.filePath); } catch {} }
    await recordGeminiImageUsage("category", category.name || "Kategorie", generated.apiUsage, new Date(revision));
    persist();
  } catch (error) {
    category.imageSource = "error";
    category.imageError = error.name === "AbortError" ? "Zeitüberschreitung nach 90 Sekunden." : error.message;
    persist();
    throw error;
  }
  return category;
}

function localProposalForItem(itemName, list, product = null) {
  const hard = hardCategoryForName(itemName, list);
  const learned = hard ? null : learnedCategoryForName(itemName, list);
  const categoryId = hard?.categoryId || learned?.categoryId || (categoryExistsForList(list, product?.categoryId) ? product.categoryId : "other");
  const visual = inferVisual(itemName, categoryId);
  return { displayName: firstUpper(itemName), categoryId, ...visual, proposalSource: hard ? "hard-rule" : (learned ? "learned" : "local") };
}

async function classifyWithGeminiForList(itemName, list, product = null) {
  const apiKey = geminiApiKey();
  const currentCategories = (list?.categories || state.categories).slice().sort((a, b) => a.sort - b.sort);
  const categoryIds = currentCategories.map((category) => category.id);
  const hard = hardCategoryForName(itemName, list);
  const learned = hard ? null : learnedCategoryForName(itemName, list);
  const local = localProposalForItem(itemName, list, product);
  if (!apiKey) { geminiStatus = { state: "not_configured", item: itemName, detail: "Kein gemini_api_key in /data/options.json gefunden." }; return local; }
  const categoryDescription = currentCategories.map((category) => `${category.id}: ${category.name}${category.description ? ` — ${category.description}` : ""}`).join("\n");
  const baseDescription = VISUAL_BASES.map((item) => `${item.id}: ${item.label}`).join("\n");
  const motifDescription = VISUAL_MOTIFS.map((item) => `${item.id}: ${item.label}`).join("\n");
  const lockedCategoryId = product?.sourceTag && categoryExistsForList(list, product.categoryId) ? product.categoryId : "";
  const protectedRule = lockedCategoryId
    ? `VERBINDLICHE REGEL: categoryId muss ${lockedCategoryId} bleiben. Die Kategorie wurde vom Nutzer ausdrücklich über die Eingabe festgelegt; verbessere nur Name und Darstellung.`
    : (hard ? `VERBINDLICHE REGEL: Kategorie muss ${hard.categoryId} sein (${hard.reason}).` : (learned ? `Gelernter Hinweis aus manuellen Korrekturen: Kategorie ${learned.categoryId} ist für das Muster „${learned.term}“ stark bevorzugt.` : ""));
  const prompt = `Du pflegst den Artikelstamm einer deutschen Einkaufsliste. Analysiere einen NEUEN Einkaufsartikel und liefere einen sauberen Produktdatensatz.\n\nAufgaben:\n1. displayName: sinnvolle kurze deutsche Bezeichnung mit korrekter Groß-/Kleinschreibung und Rechtschreibung. Entferne Mengenangaben, aber erfinde keine Marke oder Sorte. Bei eindeutig tiefgekühlten Lebensmitteln bevorzuge eine knappe Bezeichnung mit \"TK-\" (z. B. \"TK-Heidelbeeren\").\n2. categoryId: exakt eine der vorhandenen Kategorien. Entscheidend ist die PRODUKTART, nicht eine enthaltene Zutat, Geschmacksrichtung oder ein Wortbestandteil. Beispiele: Birnenkekse/Zitronenkekse -> Süßigkeiten/Gebäck statt Obst und Gemüse; Erdbeerjoghurt -> Milchprodukte statt Obst; Tomatenketchup -> Saucen statt Gemüse. Zustand/Verkaufsform hat zusätzlich Vorrang: gefroren/TK -> TK-Produkte, Eis/Sorbet -> TK-Eis, sofern diese Kategorien vorhanden sind.\n3. visualBase: reale Produkt-/Verpackungsform. Lose Ware -> loose; Konserve -> can; Getränkekarton -> carton; TK-Ware meist frozen_bag.\n4. visualMotif: was inhaltlich auf dem Icon erkennbar sein soll.\n5. visualLabel: nur wenn die Illustration sonst mehrdeutig wäre. Banane/Apfel/Heidelbeeren lose brauchen keinen Text. Haferdrink, H-Milch, Reiniger oder ähnliche verpackte Produkte dürfen einen kurzen Text tragen. Maximal 18 Zeichen, sonst leer.\n\n${protectedRule}\n\nVorhandene Kategorien:\n${categoryDescription}\n\nZulässige Produktformen:\n${baseDescription}\n\nZulässige Motive:\n${motifDescription}\n\nBisherige manuelle Korrekturen dieser Liste (als Lernbeispiele):\n${classificationExamplesText(list)}\n\nEingabe: ${itemName}`;
  geminiStatus = { state: "requesting", item: itemName, detail: "Name, Kategorie und Icon-Bausteine werden bestimmt." };
  console.log(`Gemini-Produktanalyse gestartet: ${itemName}`);
  try {
    const controller = new AbortController(); const timeout = setTimeout(() => controller.abort(), 45000);
    const response = await fetch("https://generativelanguage.googleapis.com/v1beta/models/gemini-3.5-flash-lite:generateContent", {
      method: "POST",
      headers: { "content-type": "application/json", "x-goog-api-key": apiKey },
      body: JSON.stringify({ contents: [{ parts: [{ text: prompt }] }], generationConfig: { responseMimeType: "application/json", responseSchema: { type: "object", properties: {
        displayName: { type: "string" },
        categoryId: { type: "string", enum: categoryIds },
        visualBase: { type: "string", enum: [...BASE_IDS] },
        visualMotif: { type: "string", enum: [...MOTIF_IDS] },
        visualLabel: { type: "string" },
      }, required: ["displayName", "categoryId", "visualBase", "visualMotif", "visualLabel"] } } }),
      signal: controller.signal,
    });
    clearTimeout(timeout);
    if (!response.ok) { const detail = (await response.text()).slice(0, 300); geminiStatus = { state: "error", item: itemName, detail: `HTTP ${response.status}: ${detail}` }; console.error(`Gemini-Fehler für ${itemName}: HTTP ${response.status} ${detail}`); return local; }
    const payload = await response.json(); const text = payload.candidates?.[0]?.content?.parts?.[0]?.text || ""; const parsed = JSON.parse(text);
    let categoryId = categoryIds.includes(parsed.categoryId) ? parsed.categoryId : local.categoryId;
    if (hard?.categoryId) categoryId = hard.categoryId;
    else if (learned?.categoryId && parsed.categoryId === "other") categoryId = learned.categoryId;
    const displayName = firstUpper(parsed.displayName) || local.displayName;
    const visual = sanitizeVisual(parsed, inferVisual(displayName, categoryId));
    const proposal = { displayName, categoryId, ...visual, proposalSource: hard ? "gemini+hard-rule" : (learned ? "gemini+learning" : "gemini") };
    geminiStatus = { state: "success", item: itemName, detail: `${displayName} · ${categoryId} · ${visual.visualBase}/${visual.visualMotif}` };
    console.log(`Gemini-Produktanalyse beendet: ${itemName} -> ${displayName} / ${categoryId}`);
    return proposal;
  } catch (error) { geminiStatus = { state: "error", item: itemName, detail: error.name === "AbortError" ? "Zeitüberschreitung nach 45 Sekunden." : error.message }; console.error(`Gemini-Fehler für ${itemName}: ${geminiStatus.detail}`); return local; }
}

async function classifyWithGemini(itemName) { return classifyWithGeminiForList(itemName, { categories: state.categories, learningExamples: state.learningExamples || [] }); }

function needsGeminiClassification(product, list = activeList(), forceNew = false) {
  if (!product || product.classificationSource === "manual" || !hasClassifiableCategoryFor(list)) return false;
  if (forceNew) {
    // Wenn ein identischer Artikel in einer anderen Kategorie bereits bearbeitet wurde,
    // wird dessen Bild/Visual lokal übernommen. Dafür ist kein weiterer KI-Lauf nötig.
    if (product.imageSource === "inherited" && iconEditState(product) === "processed") return false;
    // Wirklich neue Artikel werden von Gemini sprachlich bereinigt und fachlich eingeordnet.
    // Bei expliziten Shop-/Kategorie-Suffixen bleibt die Kategorie gesperrt; Gemini darf
    // dort trotzdem den Anzeigenamen (z. B. Alexa-Schreibweise) säubern.
    if (/^(?:category|retailer):/.test(String(product.sourceTag || ""))) return true;
    if (product.sourceTag) return false;
    if (hardCategoryForName(product.name || product.key || "", list)) return false;
    if (product.classificationSource === "learned") return false;
    return true;
  }
  if (["rule", "learned"].includes(product.classificationSource)) return false;
  if (product.imageSource === "catalog" && product.categoryId !== "other") return false;
  return product.classificationSource === "automatic" && product.categoryId === "other";
}

function applyClassificationProposal(list, product, proposal, options = {}) {
  if (!list || !product || !proposal) return product;
  const oldName = product.name;
  const oldKey = product.key;
  const allowName = options.allowName !== false && product.classificationSource !== "manual";
  const allowCategory = options.allowCategory !== false && product.classificationSource !== "manual";
  if (allowCategory && categoryExistsForList(list, proposal.categoryId)) product.categoryId = proposal.categoryId;
  if (allowName && proposal.displayName) {
    const proposedName = friendlyProductName(proposal.displayName);
    const proposedKey = normalizeText(proposedName);
    const collides = list.products.some((item) => item.id !== product.id && item.categoryId === product.categoryId && (normalizeText(item.name) === proposedKey || productSearchKeys(item).includes(proposedKey)));
    if (!collides) {
      product.name = proposedName;
      const forceScoped = String(product.sourceTag || "").startsWith("category:");
      product.key = productKeyForCategory(proposedName, product.categoryId, list.products, product.id, forceScoped);
    }
  }
  const visual = sanitizeVisual(proposal, visualFallbackForProduct(product));
  if (product.visualSource !== "manual" || options.forceVisual) {
    product.visualBase = visual.visualBase; product.visualMotif = visual.visualMotif; product.visualLabel = visual.visualLabel; product.visualSource = proposal.proposalSource?.startsWith("gemini") ? "gemini" : "automatic";
  }
  product.aliases = [...new Set([...(product.aliases || []), normalizeText(oldName), oldKey, normalizeText(product.name)])].filter(Boolean);
  if (product.classificationSource !== "manual") product.classificationSource = proposal.proposalSource?.includes("learning") ? "learned" : (proposal.proposalSource?.includes("hard-rule") ? "rule" : "gemini");
  return product;
}

async function classifyResult(result, listId = state.activeListId, forceNew = false) {
  const list = state.lists.find((item) => item.id === listId);
  if (!result || result.duplicate || !list || !result.createdProduct || !hasClassifiableCategoryFor(list)) return result;
  const entry = list.entries.find((item) => item.id === result.entry.id); if (!entry) return result;
  const product = list.products.find((item) => item.id === entry.productId); if (!needsGeminiClassification(product, list, forceNew)) return result;
  const proposal = await classifyWithGeminiForList(product.name || entry.productName || entry.name, list, product);
  if (!proposal) return result;
  applyClassificationProposal(list, product, proposal, { allowCategory: !product.sourceTag });
  entry.categoryId = product.categoryId; entry.name = product.name; entry.productKey = product.key;
  // Nur der wirklich neu angelegte Artikel besitzt imageSource=pending. Stamm-/Bestandsartikel kommen nie hier hinein.
  if (product.imageSource === "pending") { product.imageKey = imageKeyForProduct(product.name, product.categoryId); await generateProductImage(product, list); }
  persist(); result.entry = entryPayloadFor(list, entry); return result;
}

async function processCreatedProduct(result, listId = state.activeListId) {
  const list = state.lists.find((item) => item.id === listId);
  if (!result || result.duplicate || !list) return result;
  const entryId = result.entry?.id;
  let entry = list.entries.find((item) => item.id === entryId);
  let product = entry ? list.products.find((item) => item.id === entry.productId) : null;

  // Nur wirklich neue Grundartikel dürfen noch sprachlich/kategorial von Gemini
  // bestimmt werden. Bestehende oder geklonte Varianten behalten ihre Stammdaten.
  if (result.createdProduct && !result.clonedProduct && product && geminiApiKey() && needsGeminiClassification(product, list, true)) {
    try { await classifyResult(result, listId, true); }
    catch (error) {
      geminiStatus = { state: "error", item: product?.name || "Artikel", detail: error.message };
      console.error(`Gemini-Kategorisierung fehlgeschlagen; Bildverarbeitung wird trotzdem fortgesetzt: ${error.message}`);
    }
    entry = list.entries.find((item) => item.id === entryId);
    product = entry ? list.products.find((item) => item.id === entry.productId) : product;
  }

  // Bildstatus gilt grundartikelweit: erst ein bereits bearbeitetes Bild aus einer
  // anderen Kategorie übernehmen, sonst genau eine KI-Erstellung starten und das
  // Ergebnis anschließend auf alle noch unbearbeiteten Varianten übertragen.
  if (product) await ensureProductImageOnUse(product, list);
  persist();
  if (entry) result.entry = entryPayloadFor(list, entry);
  return result;
}

function importAllowed(req) {
  const expected = syncToken();
  return !expected || req.headers["x-sync-token"] === expected;
}

// Der iOS-Kurzbefehl übergibt normalerweise nur das Diktat. Falls Siri den
// vollständigen Satz weiterreicht, entfernen wir die Einleitung trotzdem,
// damit sie nicht versehentlich Teil des Artikelnamens wird.
function shortcutItemInput(value) {
  const input = String(value || "").replace(/\s+/g, " ").trim();
  const spoken = input.match(/^(?:bitte\s+)?(?:setze?|füge|packe?|schreibe?)\s+(.+?)\s+(?:auf|an|in)\s+(?:meine\s+|die\s+)?einkaufsliste[.!?]*$/i);
  return (spoken ? spoken[1] : input).trim();
}

function shortcutAllowed(req) {
  const expected = shortcutToken();
  return Boolean(expected) && req.headers["x-sync-token"] === expected;
}

function shortcutResponse(result, listName) {
  const itemName = String(result?.entry?.productName || result?.entry?.name || "Artikel").trim();
  const quotedItem = `„${itemName}“`;
  return result?.duplicate
    ? `${quotedItem} steht bereits auf ${listName}.`
    : `${quotedItem} steht jetzt auf ${listName}.`;
}

function applyOfflineOperation(operation) {
  const opId = String(operation?.opId || "");
  const type = String(operation?.type || "");
  const listId = String(operation?.listId || "");
  const entryId = String(operation?.entryId || operation?.entrySnapshot?.id || "");
  if (!opId || !["check", "restore"].includes(type) || !listId || !entryId) {
    return { opId, status: "error", reason: "invalid_operation", changed: false };
  }
  const list = state.lists.find((item) => item.id === listId);
  if (!list) return { opId, status: "conflict", reason: "list_missing", changed: false };
  list.entries = Array.isArray(list.entries) ? list.entries : [];
  list.recent = Array.isArray(list.recent) ? list.recent : [];

  if (type === "check") {
    const index = list.entries.findIndex((entry) => entry.id === entryId);
    if (index < 0) {
      const alreadyRecent = list.recent.some((entry) => entry.id === entryId);
      return { opId, status: alreadyRecent ? "already_applied" : "conflict", reason: alreadyRecent ? "already_checked" : "entry_missing", changed: false };
    }
    const [entry] = list.entries.splice(index, 1);
    const nextRecent = [entry, ...list.recent.filter((item) => item.id !== entry.id && (item.productKey !== entry.productKey || entryDuplicateKey(item.productKey, item.quantity, item.productDetail) !== entryDuplicateKey(entry.productKey, entry.quantity, entry.productDetail)))].slice(0, 30);
    list.recent.splice(0, list.recent.length, ...nextRecent);
    list.undo = null;
    if (state.activeListId === list.id) state.undo = null;
    return { opId, status: "applied", action: "checked", changed: true };
  }

  if (list.entries.some((entry) => entry.id === entryId)) {
    return { opId, status: "already_applied", reason: "already_open", changed: false };
  }
  const recentIndex = list.recent.findIndex((entry) => entry.id === entryId);
  if (recentIndex < 0) return { opId, status: "conflict", reason: "recent_entry_missing", changed: false };
  const entry = list.recent[recentIndex];
  const duplicate = list.entries.some((item) => entryDuplicateKey(item.productKey, item.quantity, item.productDetail) === entryDuplicateKey(entry.productKey, entry.quantity, entry.productDetail));
  if (duplicate) return { opId, status: "already_applied", reason: "same_item_open", changed: false };
  list.recent.splice(recentIndex, 1);
  list.entries.push(entry);
  list.undo = null;
  if (state.activeListId === list.id) state.undo = null;
  return { opId, status: "applied", action: "restored", changed: true };
}

async function api(req, res, pathname, searchParams = new URLSearchParams()) {
  if (pathname === "/api/reminders-sync/status" && req.method === "GET") {
    return json(res, 200, appleRemindersSync ? appleRemindersSync.getStatus() : { state: "starting", detail: "Apple-Erinnerungen werden vorbereitet" });
  }
  if (pathname === "/api/caldav/status" && req.method === "GET") {
    return json(res, 200, localCaldavSync ? localCaldavSync.getStatus() : { state: "starting", detail: "CalDAV wird vorbereitet" });
  }
  if (pathname === "/api/integration/lists" && req.method === "GET") {
    if (!importAllowed(req)) return json(res, 401, { error: "Import-Token fehlt oder ist ungültig." });
    saveActiveList();
    return json(res, 200, { lists: state.lists.slice().sort((a, b) => a.sort - b.sort).map((list) => ({ id: list.id, name: list.name, color: list.color, itemCount: list.entries.length })), syncListId: state.syncListId || state.activeListId });
  }
  if (pathname === "/api/integration/state" && req.method === "GET") {
    if (!importAllowed(req)) return json(res, 401, { error: "Import-Token fehlt oder ist ungültig." });
    saveActiveList();
    const target = state.lists.find((list) => list.id === (searchParams.get("listId") || state.syncListId || state.activeListId));
    if (!target) return json(res, 404, { error: "Sync-Zielliste nicht gefunden." });
    return json(res, 200, integrationListState(target));
  }
  if (pathname === "/api/integration/import" && req.method === "POST") {
    if (!importAllowed(req)) return json(res, 401, { error: "Import-Token fehlt oder ist ungültig." });
    const body = await readBody(req);
    const targetListId = body.listId || state.syncListId || state.activeListId;
    const target = state.lists.find((list) => list.id === targetListId);
    if (!target) return json(res, 404, { error: "Sync-Zielliste nicht gefunden." });
    if (!Array.isArray(body.items)) return json(res, 400, { error: "Keine Artikel übergeben." });
    const previousListId = state.activeListId;
    activateList(target.id);
    const results = [];
    try {
      for (const item of body.items) {
        const input = item?.name || item?.input || item;
        if (!String(input || "").trim()) { results.push({ status: "error", error: "Artikelname fehlt." }); continue; }
        try {
          let requestedQuantity = item && typeof item === "object" && item.quantity !== undefined && item.quantity !== null && item.quantity !== ""
            ? quantityFromRequest(item.quantity, item.unit)
            : null;
          let requestedSpecial = null;
          let requestedCategory = false;
          if (item && typeof item === "object") {
            const requestedId = String(item.categoryId || "").trim();
            const requestedName = String(item.categoryName || "").trim();
            requestedCategory = Boolean(requestedId || requestedName);
            requestedSpecial = resolveRequestedSpecialCategory(target, requestedId, requestedName);
            if (requestedCategory && !requestedSpecial?.category) {
              results.push({ status: "error", error: `Angeforderte Kategorie „${item.categoryName || item.categoryId}“ existiert in der Zielliste nicht.` });
              continue;
            }
          }
          let importInput = input;
          let inheritFromName = "";
          if (requestedSpecial?.category && typeof importInput === "string") {
            // Der Sync darf sowohl bereits bereinigte Namen als auch ältere Rohformen
            // liefern. Spezialziel und Menge werden deshalb vor der Stammartikelsuche
            // noch einmal defensiv herausgelöst.
            const parsedSpecial = parseSpecialTargetInput(importInput, target);
            if (parsedSpecial && parsedSpecial.forcedCategoryId === requestedSpecial.category.id) {
              importInput = parsedSpecial.inheritFromName || parsedSpecial.parsed.name;
              inheritFromName = parsedSpecial.inheritFromName || parsedSpecial.parsed.name;
              if (!requestedQuantity && hasStoredQuantity(parsedSpecial.parsed.quantity)) requestedQuantity = { ...parsedSpecial.parsed.quantity };
            } else {
              try {
                const parsedPlain = prepareParsedProductDetail(parseItemInput(importInput));
                if (hasStoredQuantity(parsedPlain.quantity)) {
                  importInput = parsedPlain.name;
                  if (!requestedQuantity) requestedQuantity = { ...parsedPlain.quantity };
                }
              } catch {}
              inheritFromName = friendlyProductName(importInput);
            }
          }
          const result = addEntry(importInput, {
            note: item?.note,
            productDetail: item?.productDetail,
            quantityOverride: requestedQuantity,
            forcedCategoryId: requestedSpecial?.category?.id || "",
            sourceTag: requestedSpecial?.sourceTag || "",
            targetKind: requestedSpecial?.targetKind || "",
            storeLabel: requestedSpecial?.storeLabel || "",
            inheritFromName,
          });
          if (result.duplicate) {
            results.push({ status: "duplicate", entry: result.entry });
          } else {
            results.push({ status: "added", entry: result.entry });
            void processCreatedProduct(result, target.id).catch((error) => {
              imageStatus = { state: "error", item: result.entry?.productName || result.entry?.name || "Artikel", productId: result.entry?.productId || "", detail: error.message };
              console.error(`Hintergrund-Verarbeitung für neuen Sync-Artikel fehlgeschlagen: ${error.message}`);
            });
          }
        } catch (error) { results.push({ status: "error", error: error.message }); }
      }
    } finally {
      if (previousListId !== target.id) activateList(previousListId);
      persist();
    }
    return json(res, 200, { list: { id: target.id, name: target.name }, added: results.filter((item) => item.status === "added").length, duplicates: results.filter((item) => item.status === "duplicate").length, results });
  }
  if (pathname === "/api/shortcut/add" && req.method === "POST") {
    if (!shortcutAllowed(req)) return json(res, 401, { error: "Der Siri-Kurzbefehl ist noch nicht mit dem Synchronisationsschlüssel verbunden." });
    const body = await readBody(req);
    const input = shortcutItemInput(body.input || body.text || body.item || body.name);
    if (!input) return json(res, 400, { error: "Bitte nenne einen Artikel für die Einkaufsliste." });
    const targetListId = body.listId || state.syncListId || state.activeListId;
    const target = state.lists.find((list) => list.id === targetListId);
    if (!target) return json(res, 404, { error: "Die gewählte Einkaufsliste wurde nicht gefunden." });
    const previousListId = state.activeListId;
    activateList(target.id);
    let result;
    try {
      result = addEntry(input);
      if (!result.duplicate) {
        void processCreatedProduct(result, target.id).catch((error) => {
          imageStatus = { state: "error", item: result.entry?.productName || result.entry?.name || "Artikel", productId: result.entry?.productId || "", detail: error.message };
          console.error(`Hintergrund-Verarbeitung für Siri-Kurzbefehl fehlgeschlagen: ${error.message}`);
        });
      }
    } finally {
      if (previousListId !== target.id) activateList(previousListId);
      persist();
    }
    return json(res, result.duplicate ? 200 : 201, {
      status: result.duplicate ? "duplicate" : "added",
      list: { id: target.id, name: target.name },
      entry: result.entry,
      message: shortcutResponse(result, target.name),
    });
  }
  if (pathname === "/api/offline-sync" && req.method === "POST") {
    const body = await readBody(req);
    const operations = Array.isArray(body.operations) ? body.operations : [];
    if (operations.length > 200) return json(res, 400, { error: "Zu viele Offline-Änderungen auf einmal." });
    saveActiveList();
    const results = [];
    let changed = false;
    for (const operation of operations) {
      const result = applyOfflineOperation(operation);
      changed = changed || result.changed;
      const { changed: _changed, ...publicResult } = result;
      results.push(publicResult);
    }
    if (changed) persist();
    return json(res, 200, { results, state: publicState(), serverUpdatedAt: state.updatedAt || null });
  }
  if (pathname === "/api/state" && req.method === "GET") return json(res, 200, publicState());
  if (pathname === "/api/lists" && req.method === "POST") {
    const body = await readBody(req); const name = firstUpper(body.name); if (!name) return json(res, 400, { error: "Listenname fehlt." });
    if (state.lists.some((list) => normalizeText(list.name) === normalizeText(name))) return json(res, 409, { error: "Diese Liste existiert bereits." });
    const source = state.lists.find((list) => list.id === body.copyFromId);
    const categories = source && body.copyCategories ? clone(source.categories) : [clone(categorySeed.find((category) => category.id === "other"))];
    const products = source && body.copyProducts ? clone(source.products).filter((product) => categories.some((category) => category.id === product.categoryId)) : [];
    const list = listRecord(id("list"), name, validColor(body.color) || DEFAULT_LIST_COLOR, { categories, products, entries: [], recent: [], undo: null, learningExamples: [], deletedProductKeys: [] }); list.categoryMode = source && body.copyCategories ? "copied" : "empty";
    list.sort = state.lists.length; state.lists.push(list); persist();
    if (body.activate !== false) { activateList(list.id); persist(); }
    return json(res, 201, { list: { id: list.id, name: list.name, color: list.color, sort: list.sort }, state: publicState() });
  }
  if (pathname === "/api/lists/switch" && req.method === "POST") {
    const body = await readBody(req); if (!activateList(body.listId)) return json(res, 404, { error: "Liste nicht gefunden." }); persist(); return json(res, 200, publicState());
  }
  if (pathname === "/api/lists/reorder" && req.method === "POST") {
    const body = await readBody(req); const lists = state.lists.slice().sort((a, b) => a.sort - b.sort); const index = lists.findIndex((list) => list.id === body.id); const direction = Number(body.direction);
    if (index < 0 || ![-1, 1].includes(direction)) return json(res, 400, { error: "Ungültige Listenverschiebung." });
    const target = index + direction; if (target >= 0 && target < lists.length) { [lists[index], lists[target]] = [lists[target], lists[index]]; lists.forEach((list, position) => { list.sort = position; }); state.lists = lists; persist(); }
    return json(res, 200, publicState());
  }
  if (pathname.startsWith("/api/lists/") && req.method === "PATCH") {
    const list = state.lists.find((item) => item.id === pathname.split("/").pop()); if (!list) return json(res, 404, { error: "Liste nicht gefunden." });
    const body = await readBody(req); const name = firstUpper(body.name); if (name) list.name = name; if (body.color) { const color = validColor(body.color); if (!color) return json(res, 400, { error: "Ungültige Listenfarbe." }); list.color = color; }
    if (body.syncTarget !== undefined) { if (!state.lists.some((item) => item.id === body.syncTarget)) return json(res, 400, { error: "Sync-Zielliste nicht gefunden." }); state.syncListId = body.syncTarget; }
    persist(); return json(res, 200, publicState());
  }
  if (pathname.startsWith("/api/lists/") && req.method === "DELETE") {
    const listId = pathname.split("/").pop(); if (state.lists.length <= 1) return json(res, 400, { error: "Die letzte Liste kann nicht gelöscht werden." });
    const list = state.lists.find((item) => item.id === listId); if (!list) return json(res, 404, { error: "Liste nicht gefunden." });
    const wasActive = state.activeListId === listId; saveActiveList(); state.lists = state.lists.filter((item) => item.id !== listId); if (state.syncListId === listId) state.syncListId = state.lists[0].id; if (wasActive) { const next = state.lists[0]; state.activeListId = next.id; state.categories = next.categories; state.products = next.products; state.entries = next.entries; state.recent = next.recent; state.undo = next.undo || null; state.learningExamples = next.learningExamples || []; } persist(); return json(res, 200, publicState());
  }
  if (pathname === "/api/settings" && req.method === "PATCH") {
    const body = await readBody(req); if (body.syncListId && !state.lists.some((list) => list.id === body.syncListId)) return json(res, 400, { error: "Sync-Zielliste nicht gefunden." });
    if (body.syncListId) state.syncListId = body.syncListId; persist(); return json(res, 200, publicState());
  }
  if (pathname === "/api/items" && req.method === "POST") {
    const body = await readBody(req); const rawInput = body.input || body.name || body;
    const requestedQuantity = body.quantity !== undefined && body.quantity !== null && body.quantity !== ""
      ? quantityFromRequest(body.quantity, body.unit)
      : null;
    const result = addEntry(rawInput, { note: body.note, productDetail: body.productDetail, quantityOverride: requestedQuantity }); if (result.duplicate) { result.error = "Artikel steht schon auf der Einkaufsliste"; return json(res, 409, result); }
    const isNew = Boolean(result.createdProduct);
    const geminiReady = Boolean(geminiApiKey());
    const createdProduct = isNew ? state.products.find((product) => product.id === result.entry?.productId) : null;
    const classificationPending = isNew && geminiReady && needsGeminiClassification(createdProduct, activeList(), true);
    const imagePending = result.entry?.iconEditStatus !== "processed" && geminiReady;
    void processCreatedProduct(result).catch((error) => {
      imageStatus = { state: "error", item: result.entry?.productName || result.entry?.name || "Artikel", productId: result.entry?.productId || "", detail: error.message };
      console.error(`Hintergrund-Verarbeitung für neuen Artikel fehlgeschlagen: ${error.message}`);
    });
    return json(res, 201, { ...result, classificationPending, imagePending, geminiReady });
  }
  if (pathname === "/api/backup" && req.method === "GET") {
    res.writeHead(200, { "content-type": "application/json; charset=utf-8", "content-disposition": `attachment; filename="eigene-einkaufsliste-backup.json"`, "cache-control": "no-store" });
    return res.end(JSON.stringify(backupPayload(), null, 2));
  }
  if (pathname === "/api/restore" && req.method === "POST") {
    const body = await readBody(req); if (!Array.isArray(body.categories) || !Array.isArray(body.products) || !Array.isArray(body.entries)) return json(res, 400, { error: "Ungültige Sicherungsdatei." });
    try { createRestoreSafetyBackup(); } catch (error) { return json(res, 500, { error: `Sicherheitskopie vor Wiederherstellung fehlgeschlagen. Wiederherstellung wurde abgebrochen: ${error.message}` }); }
    state = migrateState(body); persist(); return json(res, 200, publicState());
  }
  if (pathname === "/api/products" && req.method === "POST") {
    const body = await readBody(req); const name = firstUpper(body.name); const categoryId = body.categoryId;
    if (!name) return json(res, 400, { error: "Artikelname fehlt." });
    if (!state.categories.some((category) => category.id === categoryId)) return json(res, 400, { error: "Kategorie nicht gefunden." });
    if (state.products.some((product) => product.categoryId === categoryId && normalizeText(product.name) === normalizeText(name))) return json(res, 409, { error: "Artikel existiert in dieser Kategorie bereits." });
    const key = productKeyForCategory(name, categoryId, state.products); const visual = sanitizeVisual(body, inferVisual(name, categoryId)); const catalogMatch = catalogMatchForName(name);
    const product = { id: id("product"), key, name, categoryId, icon: categoryIcon(categoryId), aliases: [key], favorite: false, useCount: 0, defaultQuantity: normalizeDefaultQuantity(body.defaultQuantity), classificationSource: "manual", ...visual, visualSource: "manual", imageKey: catalogMatch?.imageKey || imageKeyForProduct(name, categoryId), imageSource: catalogMatch ? "catalog" : "pending", ...(catalogMatch ? {} : { imageGenerationVersion: VERSION }) };
    state.products.push(product); persist(); if (geminiApiKey()) void generateProductImage(product, activeList()).then(() => persist()).catch((error) => console.error(`Hintergrund-Bildgenerierung fehlgeschlagen: ${error.message}`)); return json(res, 201, { product, state: publicState() });
  }
  if (pathname.match(/^\/api\/products\/[^/]+\/upload-image$/) && req.method === "POST") {
    const productId = pathname.split("/")[3];
    try {
      const body = await readBody(req, 5 * 1024 * 1024);
      const product = saveUploadedProductImage(productId, body.dataUrl);
      return json(res, 200, { product, state: publicState() });
    } catch (error) {
      const status = error.message === "Artikel nicht gefunden." ? 404 : 400;
      return json(res, status, { error: error.message });
    }
  }
  if (pathname.match(/^\/api\/products\/[^/]+\/generate-image$/) && req.method === "POST") {
    const productId = pathname.split("/")[3]; const product = state.products.find((item) => item.id === productId); if (!product) return json(res, 404, { error: "Artikel nicht gefunden." });
    if (!geminiApiKey()) return json(res, 409, { error: "Gemini ist nicht konfiguriert." });
    // Automatisch bleiben Stammartikel kostenfrei. Dieser Endpunkt ist jedoch eine
    // ausdrückliche Nutzeraktion und darf deshalb auch ein Stammbild bewusst durch
    // ein individuelles Gemini-Bild ersetzen.
    product.imageSource = "pending"; product.imageGenerationVersion = VERSION; product.imageRequestedManually = true; delete product.imageError; persist();
    void generateProductImage(product, activeList(), { force: true }).then(() => { delete product.imageRequestedManually; persist(); }).catch((error) => {
      product.imageSource = "error"; product.imageError = error.message; delete product.imageRequestedManually; imageStatus = { state: "error", item: product.name, productId: product.id, detail: error.message }; persist();
    });
    return json(res, 202, { product, state: publicState() });
  }
  if (pathname.match(/^\/api\/products\/[^/]+\/reclassify$/) && req.method === "POST") {
    const productId = pathname.split("/")[3]; const product = state.products.find((item) => item.id === productId); if (!product) return json(res, 404, { error: "Artikel nicht gefunden." });
    if (!geminiApiKey()) return json(res, 409, { error: "Gemini ist nicht konfiguriert." });
    const proposal = await classifyWithGeminiForList(product.name, activeList(), product);
    return json(res, 200, { proposal });
  }
  if (pathname.match(/^\/api\/products\/[^/]+$/) && req.method === "DELETE") {
    const productId = pathname.split("/").pop();
    const product = state.products.find((item) => item.id === productId);
    if (!product) return json(res, 404, { error: "Artikel nicht gefunden." });
    const snapshot = {
      name: product.name, icon: product.icon, categoryId: product.categoryId, visualBase: product.visualBase || null,
      visualMotif: product.visualMotif || null, visualLabel: product.visualLabel || "", visualSource: product.visualSource || "automatic",
      imageRevision: product.imageRevision || "", imageKey: product.imageKey || imageKeyForProduct(product.name, product.categoryId),
      processedIcon: processedIconFor(product), generatedImage: product.generatedImage || "", imageSource: product.imageSource || "catalog",
      imageError: product.imageError || "", useCount: product.useCount || 0, defaultQuantity: normalizeDefaultQuantity(product.defaultQuantity),
    };
    const referencedEntries = [...state.entries, ...(state.recent || [])].filter((entry) => entry.productId === productId);
    for (const entry of referencedEntries) entry.productSnapshot = { ...snapshot };
    state.products = state.products.filter((item) => item.id !== productId);
    const deletedKey = normalizeText(product.key || product.name);
    state.deletedProductKeys = [...new Set([...(state.deletedProductKeys || []), deletedKey].filter(Boolean))];
    // Gemini-Dateien bleiben erhalten, solange aktive/zuletzt-erledigte Einträge darauf verweisen.
    if (!referencedEntries.length) {
      const prefix = `${String(product.id || "product").replace(/[^a-zA-Z0-9_-]/g, "_")}`;
      if (fs.existsSync(GENERATED_IMAGE_DIR)) {
        for (const candidate of fs.readdirSync(GENERATED_IMAGE_DIR)) {
          if (!/\.(png|jpg|jpeg|webp)$/i.test(candidate)) continue;
          const stem = candidate.replace(/\.(png|jpg|jpeg|webp)$/i, "");
          if (stem !== prefix && !stem.startsWith(`${prefix}-`)) continue;
          try { fs.unlinkSync(path.join(GENERATED_IMAGE_DIR, candidate)); } catch {}
        }
      }
    }
    persist();
    return json(res, 200, { deleted: true, productId, preservedEntries: referencedEntries.length, state: publicState() });
  }
  if (pathname.startsWith("/api/products/") && req.method === "PATCH") {
    const productId = pathname.split("/").pop(); const product = state.products.find((item) => item.id === productId); if (!product) return json(res, 404, { error: "Artikel nicht gefunden." });
    const body = await readBody(req); const oldName = product.name; const oldCategoryId = product.categoryId; const name = friendlyProductName(body.name) || product.name;
    const nextCategoryId = body.categoryId && state.categories.some((category) => category.id === body.categoryId) ? body.categoryId : product.categoryId;
    if (state.products.some((item) => item.id !== product.id && item.categoryId === nextCategoryId && normalizeText(item.name) === normalizeText(name))) return json(res, 409, { error: "Artikel existiert in dieser Kategorie bereits." });
    product.name = name; product.categoryId = nextCategoryId; product.key = productKeyForCategory(name, nextCategoryId, state.products, product.id, String(product.sourceTag || "").startsWith("category:")); product.aliases = [...new Set([...(product.aliases || []), normalizeText(oldName), normalizeText(name)])].filter(Boolean);
    if (body.iconHint !== undefined) product.iconHint = String(body.iconHint || "").trim();
    if (body.defaultQuantity !== undefined) product.defaultQuantity = normalizeDefaultQuantity(body.defaultQuantity);
    const visualInputProvided = body.visualBase !== undefined || body.visualMotif !== undefined || body.visualLabel !== undefined;
    if (visualInputProvided) { const visual = sanitizeVisual(body, visualFallbackForProduct(product)); product.visualBase = visual.visualBase; product.visualMotif = visual.visualMotif; product.visualLabel = visual.visualLabel; product.visualSource = "manual"; }
    if (body.favorite !== undefined) product.favorite = Boolean(body.favorite);
    if (body.categoryId !== undefined || body.name !== undefined) product.classificationSource = "manual";
    if ((body.categoryId !== undefined || body.name !== undefined) && product.imageSource === "catalog") product.imageKey = imageKeyForProduct(product.name, product.categoryId);
    if (oldCategoryId !== product.categoryId) recordLearningExampleForList(activeList(), product.name, oldCategoryId, product.categoryId);
    for (const entry of state.entries) if (entry.productId === product.id) { entry.name = product.name; entry.productKey = product.key; entry.categoryId = product.categoryId; }
    persist(); return json(res, 200, { product, state: publicState() });
  }
  if (pathname === "/api/items/check" && req.method === "POST") {
    const body = await readBody(req); const index = state.entries.findIndex((entry) => entry.id === body.id);
    if (index < 0) return json(res, 404, { error: "Artikel nicht gefunden." });
    const [entry] = state.entries.splice(index, 1);
    state.recent = [entry, ...(state.recent || []).filter((item) => item.productKey !== entry.productKey || entryDuplicateKey(item.productKey, item.quantity, item.productDetail) !== entryDuplicateKey(entry.productKey, entry.quantity, entry.productDetail))].slice(0, 30);
    state.undo = { entry, action: "check", expiresAt: Date.now() + UNDO_TTL_MS }; persist(); return json(res, 200, { entry: entryPayload(entry), undoAvailable: true });
  }
  if (pathname === "/api/undo" && req.method === "POST") {
    if (!state.undo || state.undo.expiresAt < Date.now()) { state.undo = null; return json(res, 409, { error: "Nichts rückgängig zu machen." }); }
    state.entries.push(state.undo.entry); const entry = state.undo.entry; state.recent = (state.recent || []).filter((item) => item.id !== entry.id); state.undo = null; persist(); return json(res, 200, { entry: entryPayload(entry) });
  }
  if (pathname === "/api/categories" && req.method === "POST") {
    const body = await readBody(req); const name = firstUpper(body.name); if (!name) return json(res, 400, { error: "Kategoriename fehlt." });
    if (state.categories.some((category) => normalizeText(category.name) === normalizeText(name))) return json(res, 409, { error: "Kategorie existiert bereits." });
    const category = { id: id("category"), name, icon: body.icon || "📦", description: String(body.description || "").trim(), sort: state.categories.length }; state.categories.push(category); persist(); return json(res, 201, { category });
  }
  if (pathname.match(/^\/api\/categories\/[^/]+\/upload-image$/) && req.method === "POST") {
    const categoryId = pathname.split("/")[3];
    try {
      const body = await readBody(req, 5 * 1024 * 1024);
      const category = saveUploadedCategoryImage(categoryId, body.dataUrl);
      return json(res, 200, { category, state: publicState() });
    } catch (error) {
      const status = error.message === "Kategorie nicht gefunden." ? 404 : 400;
      return json(res, status, { error: error.message });
    }
  }
  if (pathname.match(/^\/api\/categories\/[^/]+\/generate-image$/) && req.method === "POST") {
    const categoryId = pathname.split("/")[3];
    const category = state.categories.find((item) => item.id === categoryId);
    if (!category) return json(res, 404, { error: "Kategorie nicht gefunden." });
    if (!geminiApiKey()) return json(res, 409, { error: "Gemini ist nicht konfiguriert." });
    category.imageSource = "pending"; delete category.imageError; persist();
    void generateCategoryImage(category).catch((error) => console.error(`Gemini-Kategoriebild fehlgeschlagen für ${category.name}: ${error.message}`));
    return json(res, 202, { category, state: publicState() });
  }
  if (pathname === "/api/categories/reorder" && req.method === "POST") {
    const body = await readBody(req); const categories = state.categories.slice().sort((a, b) => a.sort - b.sort); const index = categories.findIndex((category) => category.id === body.id); const direction = Number(body.direction);
    if (index < 0 || ![-1, 1].includes(direction)) return json(res, 400, { error: "Ungültige Kategorienverschiebung." });
    const target = index + direction; if (target < 0 || target >= categories.length) return json(res, 200, publicState());
    [categories[index], categories[target]] = [categories[target], categories[index]];
    categories.forEach((category, position) => { category.sort = position; }); state.categories = categories; persist(); return json(res, 200, publicState());
  }
  if (pathname === "/api/bulk/move" && req.method === "POST") {
    const body = await readBody(req); if (!state.categories.some((category) => category.id === body.categoryId)) return json(res, 400, { error: "Kategorie nicht gefunden." });
    const ids = Array.isArray(body.ids) ? new Set(body.ids) : new Set();
    for (const entry of state.entries) if (ids.has(entry.id)) {
      const sourceProduct = state.products.find((item) => item.id === entry.productId);
      if (!sourceProduct) { entry.categoryId = body.categoryId; continue; }
      if (sourceProduct.categoryId === body.categoryId) { entry.categoryId = body.categoryId; continue; }
      const parsed = { original: sourceProduct.name, name: sourceProduct.name, quantity: null };
      const product = productForParsed(parsed, {
        lookupName: sourceProduct.name,
        keyName: `${sourceProduct.name} category ${body.categoryId}`,
        forcedCategoryId: body.categoryId,
        sourceTag: `category:${body.categoryId}`,
        inheritFromName: sourceProduct.name,
        explicitCategorySuffix: true,
      });
      entry.productId = product.id; entry.productKey = product.key; entry.name = product.name; entry.categoryId = product.categoryId;
    }
    persist(); return json(res, 200, publicState());
  }
  if (pathname === "/api/bulk/move-list" && req.method === "POST") {
    const body = await readBody(req);
    const ids = Array.isArray(body.ids) ? [...new Set(body.ids.map((value) => String(value || "").trim()).filter(Boolean))] : [];
    if (!ids.length) return json(res, 400, { error: "Keine Artikel ausgewählt." });
    const target = state.lists.find((list) => list.id === body.listId);
    if (!target) return json(res, 404, { error: "Ziel-Liste nicht gefunden." });
    if (target.id === state.activeListId) return json(res, 400, { error: "Die Artikel befinden sich bereits auf dieser Liste." });

    const selectedEntries = state.entries.filter((entry) => ids.includes(entry.id));
    if (!selectedEntries.length) return json(res, 404, { error: "Ausgewählte Artikel wurden nicht gefunden." });

    const movedIds = [];
    const skipped = [];
    for (const sourceEntry of selectedEntries) {
      const sourceProduct = state.products.find((product) => product.id === sourceEntry.productId);
      const sourceCategory = state.categories.find((category) => category.id === sourceEntry.categoryId);
      const existingProduct = target.products.find((product) => product.key === sourceEntry.productKey || (product.aliases || []).some((alias) => normalizeText(alias) === normalizeText(sourceEntry.productKey)));
      const targetProduct = existingProduct || { ...clone(sourceProduct || { key: sourceEntry.productKey, name: sourceEntry.name, icon: "📦", aliases: [sourceEntry.productKey] }), id: id("product") };
      targetProduct.categoryId = target.categories.some((category) => category.id === sourceEntry.categoryId)
        ? sourceEntry.categoryId
        : (target.categories.find((category) => normalizeText(category.name) === normalizeText(sourceCategory?.name || ""))?.id || "other");
      if (!existingProduct) target.products.push(targetProduct);

      const duplicate = target.entries.some((entry) => entryDuplicateKey(entry.productKey, entry.quantity, entry.productDetail) === entryDuplicateKey(targetProduct.key, sourceEntry.quantity, sourceEntry.productDetail));
      if (duplicate) {
        skipped.push({ id: sourceEntry.id, name: sourceEntry.name, reason: "duplicate" });
        continue;
      }

      const moved = { ...clone(sourceEntry), id: id("entry"), productId: targetProduct.id, productKey: targetProduct.key, categoryId: targetProduct.categoryId };
      target.entries.push(moved);
      movedIds.push(sourceEntry.id);
    }

    if (movedIds.length) state.entries = state.entries.filter((entry) => !movedIds.includes(entry.id));
    persist();
    return json(res, 200, {
      moved: movedIds.length,
      skipped: skipped.length,
      skippedItems: skipped,
      targetList: { id: target.id, name: target.name, color: target.color },
      state: publicState(),
    });
  }
  if (pathname.startsWith("/api/categories/") && req.method === "PATCH") {
    const categoryId = pathname.split("/").pop(); const category = state.categories.find((item) => item.id === categoryId); if (!category) return json(res, 404, { error: "Kategorie nicht gefunden." });
    const body = await readBody(req); category.name = firstUpper(body.name) || category.name; if (body.icon) category.icon = body.icon; if (body.description !== undefined) category.description = String(body.description || "").trim(); persist(); return json(res, 200, { category, state: publicState() });
  }
  if (pathname.startsWith("/api/categories/") && req.method === "DELETE") {
    const categoryId = pathname.split("/").pop(); const category = categoryById(categoryId); if (!category || category.id === "other") return json(res, 400, { error: "Diese Kategorie kann nicht gelöscht werden." });
    const body = await readBody(req); const target = categoryById(body.moveTo || "other");
    for (const product of state.products) if (product.categoryId === category.id) product.categoryId = target.id;
    for (const entry of state.entries) if (entry.categoryId === category.id) entry.categoryId = target.id;
    const generatedCategoryFile = categoryGeneratedImageFile(category);
    state.categories = state.categories.filter((item) => item.id !== category.id);
    if (generatedCategoryFile) { try { fs.unlinkSync(generatedCategoryFile.filePath); } catch {} }
    persist(); return json(res, 200, publicState());
  }
  if (pathname.startsWith("/api/items/") && req.method === "DELETE") {
    const itemId = pathname.split("/").pop(); const entry = state.entries.find((item) => item.id === itemId); if (!entry) return json(res, 404, { error: "Artikel nicht gefunden." }); state.entries = state.entries.filter((item) => item.id !== itemId); state.undo = { entry, action: "delete", expiresAt: Date.now() + UNDO_TTL_MS }; persist(); return json(res, 200, publicState());
  }
  if (pathname.match(/^\/api\/items\/[^/]+\/move-list$/) && req.method === "POST") {
    const parts = pathname.split("/"); const itemId = parts[3]; const body = await readBody(req); const target = state.lists.find((list) => list.id === body.listId);
    if (!target) return json(res, 404, { error: "Ziel-Liste nicht gefunden." });
    const index = state.entries.findIndex((entry) => entry.id === itemId); if (index < 0) return json(res, 404, { error: "Artikel nicht gefunden." });
    const sourceEntry = state.entries[index]; const sourceProduct = state.products.find((product) => product.id === sourceEntry.productId); const sourceCategory = state.categories.find((category) => category.id === sourceEntry.categoryId);
    const existingProduct = target.products.find((product) => product.key === sourceEntry.productKey || (product.aliases || []).some((alias) => normalizeText(alias) === normalizeText(sourceEntry.productKey)));
    const targetProduct = existingProduct || { ...clone(sourceProduct || { key: sourceEntry.productKey, name: sourceEntry.name, icon: "📦", aliases: [sourceEntry.productKey] }), id: id("product") };
    targetProduct.categoryId = target.categories.some((category) => category.id === sourceEntry.categoryId) ? sourceEntry.categoryId : (target.categories.find((category) => normalizeText(category.name) === normalizeText(sourceCategory?.name || ""))?.id || "other");
    if (!existingProduct) target.products.push(targetProduct);
    if (target.entries.some((entry) => entryDuplicateKey(entry.productKey, entry.quantity, entry.productDetail) === entryDuplicateKey(targetProduct.key, sourceEntry.quantity, sourceEntry.productDetail))) return json(res, 409, { error: "Artikel steht bereits auf der Ziel-Liste." });
    const moved = { ...clone(sourceEntry), id: id("entry"), productId: targetProduct.id, productKey: targetProduct.key, categoryId: targetProduct.categoryId };
    state.entries.splice(index, 1); target.entries.push(moved); persist(); return json(res, 200, publicState());
  }
  if (pathname.startsWith("/api/items/") && req.method === "PATCH") {
    const itemId = pathname.split("/").pop(); const entry = state.entries.find((item) => item.id === itemId); if (!entry) return json(res, 404, { error: "Artikel nicht gefunden." });
    const body = await readBody(req); const previousProduct = state.products.find((item) => item.id === entry.productId); let parsed = prepareParsedProductDetail(parseItemInput(body.name || entry.name)); let special = prepareParsedForList(parsed, activeList()); parsed = special.parsed;
    const requestedCategoryId = special.forcedCategoryId || body.categoryId || entry.categoryId;
    const requestedCategory = state.categories.find((category) => category.id === requestedCategoryId);
    if (!requestedCategory) return json(res, 400, { error: "Kategorie nicht gefunden." });

    // Beim Bearbeiten eines bereits shop-/kategoriespezifischen Eintrags darf das
    // Entfernen des gesprochenen Suffixes im Text nicht versehentlich die Stamm-
    // Variante wechseln. Solange die Zielkategorie gleich bleibt, behalten wir Tag
    // und Produktschlüssel bei. Ein echter Kategorienwechsel erzeugt dagegen eine
    // eigene Variante und lässt den bisherigen Stammartikel unangetastet.
    if (!special.sourceTag && previousProduct?.sourceTag === "meyerhof" && isMeyerhofCategoryName(requestedCategory?.name)) special = { ...special, lookupName: previousProduct.key || previousProduct.name, keyName: previousProduct.key || previousProduct.name, forcedCategoryId: requestedCategory.id, sourceTag: "meyerhof", inheritFromName: parsed.name };
    if (!special.sourceTag && previousProduct?.sourceTag === "rewe" && isReweCategoryName(requestedCategory?.name)) special = { ...special, lookupName: previousProduct.key || previousProduct.name, keyName: previousProduct.key || previousProduct.name, forcedCategoryId: requestedCategory.id, sourceTag: "rewe", inheritFromName: parsed.name };
    if (!special.sourceTag && /^retailer:/.test(String(previousProduct?.sourceTag || "")) && isRetailerCategoryName(requestedCategory?.name)) special = { ...special, lookupName: previousProduct.name, forcedCategoryId: requestedCategory.id, sourceTag: previousProduct.sourceTag, inheritFromName: parsed.name };
    if (!special.sourceTag && /^category:/.test(String(previousProduct?.sourceTag || "")) && previousProduct?.categoryId === requestedCategory.id) special = { ...special, lookupName: parsed.name, keyName: previousProduct.key, forcedCategoryId: requestedCategory.id, sourceTag: previousProduct.sourceTag, inheritFromName: parsed.name, explicitCategorySuffix: true };

    const sameName = previousProduct && normalizeText(previousProduct.name) === normalizeText(parsed.name);
    const sameCategory = previousProduct && previousProduct.categoryId === requestedCategoryId;
    const sameStoreSpecificProduct = Boolean(previousProduct?.sourceTag && special.sourceTag === previousProduct.sourceTag && sameName && sameCategory);
    let product;
    if (sameStoreSpecificProduct || (sameName && sameCategory && (!special.sourceTag || previousProduct.sourceTag === special.sourceTag || !previousProduct.sourceTag))) {
      product = previousProduct;
    } else {
      if (!special.forcedCategoryId) {
        special = {
          ...special,
          lookupName: parsed.name,
          forcedCategoryId: requestedCategoryId,
          ...(requestedCategoryId !== previousProduct?.categoryId ? {
            keyName: `${parsed.name} category ${requestedCategoryId}`,
            sourceTag: `category:${requestedCategoryId}`,
            inheritFromName: parsed.name,
            explicitCategorySuffix: true,
          } : (previousProduct?.sourceTag ? { sourceTag: previousProduct.sourceTag } : {})),
        };
      }
      product = productForParsed(parsed, special);
    }
    entry.productId = product.id; entry.productKey = product.key; entry.name = product.name; entry.categoryId = product.categoryId;
    if (Object.prototype.hasOwnProperty.call(body, "quantity")) {
      const requestedQuantity = quantityFromRequest(body.quantity, body.unit);
      if (body.quantity === "" || body.quantity === null) entry.quantity = null;
      else if (requestedQuantity) entry.quantity = { ...requestedQuantity, userEdited: true };
    } else if (parsed.quantity) {
      entry.quantity = parsed.quantity;
    }
    if (Object.prototype.hasOwnProperty.call(body, "productDetail")) entry.productDetail = normalizeProductDetail(body.productDetail);
    else if (parsed.productDetail) entry.productDetail = normalizeProductDetail(parsed.productDetail);
    if (Object.prototype.hasOwnProperty.call(body, "note")) entry.note = String(body.note || "").trim();
    persist(); return json(res, 200, { entry: entryPayload(entry) });
  }

  if (pathname === "/api/import" && req.method === "POST") {
    if (!importAllowed(req)) return json(res, 401, { error: "Import-Token fehlt oder ist ungültig." });
    const body = await readBody(req); const previousListId = state.activeListId; const targetListId = body.listId || state.syncListId || state.activeListId;
    if (!activateList(targetListId)) return json(res, 404, { error: "Sync-Zielliste nicht gefunden." });
    const results = [];
    for (const item of body.items || []) {
      try {
        const importInput = item.name || item.input || item;
        const requestedQuantity = item && typeof item === "object" && item.quantity !== undefined && item.quantity !== null && item.quantity !== ""
          ? quantityFromRequest(item.quantity, item.unit)
          : null;
        const added = addEntry(importInput, { note: item.note, productDetail: item.productDetail, quantityOverride: requestedQuantity });
        results.push(added.entry);
        void processCreatedProduct(added, targetListId).catch((error) => {
          imageStatus = { state: "error", item: added.entry?.productName || added.entry?.name || "Artikel", productId: added.entry?.productId || "", detail: error.message };
          console.error(`Hintergrund-Verarbeitung für importierten neuen Artikel fehlgeschlagen: ${error.message}`);
        });
      } catch (error) { results.push({ error: error.message }); }
    }
    if (previousListId !== targetListId) activateList(previousListId); persist(); return json(res, 200, { imported: results.length, results });
  }
  return json(res, 404, { error: "Nicht gefunden." });
}

function page() {
  return String.raw`<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"><title>Einkaufsliste</title><meta name="application-name" content="Einkaufsliste"><meta name="apple-mobile-web-app-title" content="Einkaufsliste"><meta name="apple-mobile-web-app-capable" content="yes"><meta name="apple-mobile-web-app-status-bar-style" content="default"><meta name="theme-color" content="#3f7f2d"><meta name="mobile-web-app-capable" content="yes"><link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png?v=0.3.59"><link rel="apple-touch-icon-precomposed" sizes="180x180" href="apple-touch-icon-precomposed.png?v=0.3.59"><link rel="icon" type="image/png" sizes="64x64" href="favicon-64.png?v=0.3.59"><link rel="shortcut icon" type="image/png" href="favicon-64.png?v=0.3.59"><link rel="manifest" href="manifest.webmanifest?v=0.3.59"><style>
:root{color-scheme:light;--bg:#edf3ef;--bg-strong:#dfe8e2;--paper:#fffdfa;--paper-2:#f7f3ee;--text:#1b2a22;--muted:#6a7b72;--line:#d8e2db;--shadow:0 18px 40px rgba(34,53,43,.10);--shadow-soft:0 8px 18px rgba(34,53,43,.08);--accent:#d86363;--accent-soft:#f8d7d7;--accent-text:#7f2727;--green:#387a57;--green-soft:#e6f1ea;--gold:#b88835;--gold-soft:#fff4de;--blue:#4d77a9;--blue-soft:#e9f0fb}*{box-sizing:border-box}html,body{height:100%}body{margin:0;background:radial-gradient(circle at top left,#f8fbf8 0,#edf3ef 36%,#e5ece7 100%);font:16px/1.4 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;color:var(--text)}button,input,select{font:inherit}button{border:0;cursor:pointer}body::before{content:"";position:fixed;inset:0;background:linear-gradient(180deg,rgba(255,255,255,.55),rgba(255,255,255,0));pointer-events:none}.app-shell{display:block;min-height:100vh}.desktop-pane{display:none}.main-stage{position:relative;max-width:860px;margin:0 auto;padding:18px 14px 140px}.content-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px;padding:calc(14px + env(safe-area-inset-top)) 2px 10px;border-top:4px solid var(--list-color,var(--accent));border-radius:4px}.title-wrap{min-width:0}.eyebrow{margin:0 0 6px;color:var(--muted);font-size:13px;font-weight:700;letter-spacing:.08em;text-transform:uppercase}.content-head h1{margin:0;font-size:34px;line-height:1.05;letter-spacing:-.04em;cursor:pointer;touch-action:pan-y}.summary{margin:8px 0 0;color:var(--muted);font-size:14px}.top-actions{display:flex;gap:8px;flex-shrink:0}.round,.tab,.secondary,.primary,.ghost,.chip-action{appearance:none}.round{width:46px;height:46px;border-radius:15px;background:rgba(255,255,255,.78);backdrop-filter:blur(10px);box-shadow:var(--shadow-soft);color:#274839;font-size:22px}.round.small{width:38px;height:38px;font-size:18px;border-radius:12px}.add{position:fixed;left:50%;bottom:68px;transform:translateX(-50%);width:min(860px,calc(100% - 24px));display:flex;gap:10px;padding:10px;border:1px solid rgba(255,255,255,.65);border-radius:22px;background:rgba(255,253,250,.92);backdrop-filter:blur(16px);box-shadow:0 14px 40px rgba(44,59,48,.16);z-index:6}.add input{flex:1;min-width:0;border:0;border-radius:16px;background:#fff;color:var(--text);padding:14px 16px;box-shadow:inset 0 0 0 1px var(--line)}.add input::placeholder{color:#87958e}.add-plus{display:none}.primary{padding:13px 18px;border-radius:16px;background:var(--accent);color:#fff;font-weight:800;box-shadow:0 10px 22px rgba(216,99,99,.28)}.secondary{padding:11px 14px;border-radius:14px;background:#edf2ee;color:#274839;font-weight:700}.ghost{padding:11px 14px;border-radius:14px;background:transparent;color:var(--muted)}.desktop-tabs{display:none}.section{margin:18px 0 0;padding:14px 14px 12px;background:var(--paper);border:1px solid rgba(255,255,255,.75);border-radius:24px;box-shadow:var(--shadow)}.section-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:4px 4px 12px;margin-bottom:4px;border-bottom:1px solid var(--line)}.section-title{display:flex;align-items:center;gap:12px;min-width:0}.section-head .cat-icon{width:38px;height:38px;display:grid;place-items:center;background:var(--cat-soft,var(--green-soft));color:var(--cat-accent,var(--green));border-radius:14px;flex:none}.section-head h2{margin:0;font-size:20px;line-height:1.1}.section-head small{display:block;color:var(--muted);font-size:13px;margin-top:3px}.section-head .actions{display:flex;align-items:center;gap:8px}.count-badge{display:inline-flex;align-items:center;justify-content:center;min-width:32px;height:32px;padding:0 10px;border-radius:999px;background:var(--cat-soft,#eef3ef);color:var(--cat-accent,#355944);font-weight:800;font-size:13px}.collapse-btn{width:34px;height:34px;border-radius:12px;background:#f4f7f4;color:#466450;font-size:18px}.list-group{display:grid;gap:8px}.card{position:relative;overflow:hidden;display:flex;align-items:center;justify-content:space-between;gap:12px;padding:12px 12px 12px 14px;border-radius:18px;background:linear-gradient(180deg,#fff,#fcf9f5);border:1px solid #edf1ed;box-shadow:0 3px 8px rgba(28,44,35,.05);-webkit-user-select:none;user-select:none;-webkit-touch-callout:none;touch-action:pan-y;transition:transform .16s ease,box-shadow .16s ease,border-color .16s ease}.card::before{content:"";position:absolute;left:0;top:12px;bottom:12px;width:3px;border-radius:0 999px 999px 0;background:var(--list-color,var(--accent));opacity:.55}.card:active{transform:scale(.993)}.card.selected{border-color:#78b08e;box-shadow:0 0 0 3px rgba(75,131,95,.14)}.card-main{display:flex;align-items:center;gap:12px;min-width:0;flex:1}.card .item-icon{width:42px;height:42px;border-radius:14px;display:grid;place-items:center;background:var(--paper-2);color:#476350;flex:none}.line-icon{width:24px;height:24px;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.card .item-text{min-width:0;flex:1}.card .name{font-size:18px;font-weight:750;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.card .original{display:none}.item-subline{margin-top:4px;display:flex;align-items:center;gap:8px;flex-wrap:wrap;color:var(--muted);font-size:13px}.card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}.qty,.tiny-pill{display:inline-flex;align-items:center;justify-content:center;padding:7px 10px;border-radius:999px;background:#eef3ef;color:#325040;font-weight:800;font-size:13px;white-space:nowrap}.icon-btn{background:#fff;border:1px solid #e6ece7;color:#66756d}.icon-btn,.check,.action-plus{width:42px;height:42px;border-radius:13px;display:grid;place-items:center;flex:none;touch-action:manipulation;-webkit-tap-highlight-color:transparent}.check{background:var(--green);color:#fff;font-size:20px;font-weight:900;box-shadow:0 8px 18px rgba(56,122,87,.25)}.select-dot{width:38px;height:38px;border-radius:13px;background:#eef3ef;color:#335744;display:grid;place-items:center;font-size:20px;font-weight:800}.recent-card{background:linear-gradient(180deg,#fff,#faf7f1)}.recent-search{margin:2px 0 12px}.recent-search input{width:100%;padding:11px 13px;border:1px solid #d9e2dc;border-radius:14px;background:#fff;color:var(--text);font-size:16px}.recent-filter-empty{padding:18px 10px;text-align:center;color:var(--muted)}.action-plus{background:var(--accent-soft);color:var(--accent-text);font-size:22px;font-weight:800}.empty{margin-top:22px;padding:48px 20px;border-radius:24px;background:rgba(255,255,255,.64);text-align:center;color:var(--muted)}.nav{position:fixed;left:50%;bottom:0;transform:translateX(-50%);width:min(900px,100%);display:flex;justify-content:space-around;padding:10px 8px calc(12px + env(safe-area-inset-bottom));background:rgba(255,253,250,.94);backdrop-filter:blur(16px);border-top:1px solid rgba(220,229,223,.9);z-index:5}.nav button{display:flex;flex-direction:column;align-items:center;gap:4px;min-width:88px;padding:6px 10px;background:transparent;color:var(--muted);font-size:13px;font-weight:700}.nav button .emoji{font-size:19px;line-height:1}.nav button.active{color:var(--green)}.nav-label{white-space:nowrap}.nav-label-wide{font-size:12px;letter-spacing:-.01em}.selection-bar{position:fixed;left:50%;bottom:70px;transform:translateX(-50%);width:min(860px,calc(100% - 24px));display:flex;gap:8px;padding:10px;border-radius:18px;background:rgba(40,60,48,.92);box-shadow:0 12px 30px rgba(0,0,0,.28);z-index:8}.selection-bar button{flex:1;color:#fff;background:rgba(255,255,255,.12);border-radius:13px;padding:12px}.snack{position:fixed;left:50%;bottom:146px;transform:translateX(-50%);min-width:min(560px,calc(100% - 24px));padding:15px 18px;border-radius:18px;background:rgba(35,53,43,.94);color:#fff;display:flex;gap:18px;align-items:center;justify-content:space-between;box-shadow:0 14px 34px rgba(0,0,0,.28);z-index:12;font-weight:700}.snack button{color:#fff;background:rgba(255,255,255,.14);border-radius:12px;padding:9px 12px;font-weight:800;white-space:nowrap}.hidden{display:none!important}.modal-back{position:fixed;inset:0;background:rgba(14,24,18,.42);display:grid;align-items:end;z-index:15}.sheet{background:#f7faf7;color:var(--text);border-radius:28px 28px 0 0;padding:18px 18px 30px;max-height:88vh;overflow:auto;box-shadow:0 -12px 32px rgba(0,0,0,.12)}.sheet h2{margin:4px 0 16px;font-size:28px}.sheet input,.sheet select{width:100%;padding:13px;border:1px solid #d9e2dc;background:#fff;color:var(--text);border-radius:14px;margin:5px 0 12px}.sheet label input[type=checkbox]{width:auto;margin:0 8px 0 0;vertical-align:middle}.manage-create-row{margin:12px 0 22px}.manage-create-row .primary{display:inline-flex;align-items:center;justify-content:center}.manage-setting{display:grid;gap:8px;margin:0 0 18px}.manage-setting label{display:block;font-weight:750;color:#355246}.manage-setting select{margin:0}.row{display:flex;gap:8px;align-items:center}.row>*{flex:1}.sheet-actions{display:flex;gap:9px;margin-top:10px}.danger{background:var(--accent);color:#fff;border-radius:14px;padding:12px 16px}.cat-choice{display:flex;align-items:center;gap:12px;width:100%;padding:13px;margin:7px 0;background:#fff;border:1px solid #dde5df;border-radius:16px;text-align:left;color:var(--text)}.cat-choice.selected{border-color:#89ba97;background:#f5faf6;color:#224532}.cat-choice .cat-icon{width:30px;height:30px;display:grid;place-items:center;background:#edf4ef;border-radius:12px}.cat-choice .plus{font-size:24px;color:var(--green)}.manage-row{display:flex;align-items:center;gap:7px;background:#fff;border:1px solid #e4ece6;border-radius:16px;padding:9px;margin:7px 0}.manage-row .label{flex:1}.manage-row small,.status-line{display:block;color:var(--muted)}.catalog-row{display:flex;align-items:center;gap:10px;padding:9px;background:#fff;border:1px solid #e4ece6;border-radius:16px;margin:6px 0}.catalog-row .label{flex:1}.list-color{width:18px;height:18px;border-radius:999px;border:2px solid #ffffffcc;box-shadow:0 0 0 1px rgba(27,42,34,.1)}.list-current{box-shadow:0 0 0 2px #cfe4d4,0 0 0 3px rgba(74,120,86,.18)}.pane-card{padding:16px;border-radius:22px;background:rgba(255,253,250,.85);border:1px solid rgba(255,255,255,.72);box-shadow:var(--shadow-soft)}.pane-head{display:flex;align-items:center;justify-content:space-between;gap:8px;margin-bottom:12px}.pane-head span{font-size:14px;font-weight:800;color:#476051;text-transform:uppercase;letter-spacing:.08em}.chip-action{padding:8px 12px;border-radius:999px;background:#eff4f0;color:#2f4d3b;font-size:13px;font-weight:800}.side-list,.side-link,.mini-action{width:100%;display:flex;align-items:center;justify-content:space-between;gap:10px;padding:12px 13px;border-radius:16px;background:rgba(255,255,255,.74);color:var(--text);margin:8px 0;text-align:left;border:1px solid rgba(224,232,226,.94)}.side-list.active,.side-link.active{background:#f4faf5;border-color:#b9d6c1;box-shadow:inset 0 0 0 1px rgba(74,120,86,.10)}.side-list .meta,.side-link .meta{display:block;color:var(--muted);font-size:12px;margin-top:2px}.side-link .left,.side-list .left{display:flex;align-items:center;gap:10px;min-width:0;flex:1}.side-list .left>span:last-child,.side-link .left>span:last-child{min-width:0;flex:1}.side-list strong,.side-link strong{display:block;overflow:hidden;text-overflow:ellipsis}.side-link .cat-icon{width:34px;height:34px;display:grid;place-items:center;border-radius:12px;background:var(--cat-soft,#edf4ef);color:var(--cat-accent,#387a57);flex:none}.side-link .left span:last-child,.side-list .left{min-width:0}.utility-stack{display:grid;gap:16px}.stat-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.stat{padding:14px;border-radius:18px;background:rgba(255,255,255,.72);border:1px solid #e5ede7}.stat .label{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.06em}.stat strong{display:block;margin-top:6px;font-size:24px;line-height:1.1}.mini-action{padding:10px 12px;margin:0;background:#fff}.mini-action strong{font-size:14px}.mini-action small{color:var(--muted)}.accent-line{height:4px;border-radius:999px;background:var(--list-color,var(--accent));margin:0 0 14px}.desktop-caption{display:none}.hidden-text{position:absolute!important;width:1px;height:1px;padding:0;margin:-1px;overflow:hidden;clip:rect(0,0,0,0);white-space:nowrap;border:0}.desktop-quick-add{display:none}@media(min-width:1100px){.app-shell{display:grid;grid-template-columns:minmax(310px,330px) minmax(0,1fr) 300px;gap:18px;max-width:1600px;margin:0 auto;padding:18px}.desktop-pane{display:block;position:sticky;top:18px;align-self:start;height:calc(100vh - 36px)}.sidebar,.utility{display:grid;gap:16px}.main-stage{max-width:none;margin:0;padding:0 0 26px;min-height:calc(100vh - 36px)}.content-head{padding:18px 18px 0}.content-head h1{font-size:42px}.summary{font-size:15px}.round{background:#fff}.desktop-tabs{display:flex;gap:10px;padding:18px 18px 8px}.tab{padding:11px 16px;border-radius:14px;background:#f1f5f1;color:#4f6558;font-weight:800}.tab.active{background:#fff;color:#274839;box-shadow:var(--shadow-soft)}.tab.ghost{background:transparent}.desktop-quick-add{display:block}.add{position:sticky;top:18px;left:auto;bottom:auto;transform:none;width:auto;margin:0 18px 8px;border-radius:24px;z-index:4}.nav{display:none}.selection-bar{bottom:18px;width:min(860px,calc(100% - 640px))}.snack{bottom:26px;left:auto;right:26px;transform:none;min-width:340px;max-width:480px}.mobile-only{display:none!important}.modal-back{align-items:center;justify-items:center;padding:28px}.sheet{width:min(760px,92vw);max-height:86vh;border-radius:28px;padding:24px 26px 28px}.sheet h2{font-size:30px}.content-head{margin:0 18px;padding-top:18px}.main-stage>.section,.main-stage>.empty{margin-left:18px;margin-right:18px}}@media(max-width:720px){.main-stage{padding-left:10px;padding-right:10px;padding-bottom:158px}.content-head h1{font-size:31px}.top-actions .round{width:42px;height:42px;font-size:20px}.section{margin-top:14px;padding:11px 11px 10px;border-radius:22px}.section-head{padding:2px 2px 9px;margin-bottom:2px}.section-head .cat-icon{width:36px;height:36px;border-radius:13px}.section-head h2{font-size:19px}.section-head small{font-size:12px}.list-group{gap:6px}.card{padding:9px 9px 9px 11px;min-height:58px;border-radius:16px}.card::before{top:10px;bottom:10px;width:2px}.card-main{gap:10px}.card .item-icon{width:38px;height:38px;border-radius:12px}.card .name{font-size:17px}.qty{font-size:12px;padding:6px 9px}.add{width:calc(100% - 16px);bottom:70px;padding:8px}.add input{padding:13px 14px}.add .primary{width:48px;padding:0;border-radius:15px}.add-label{display:none}.add-plus{display:inline;font-size:24px;line-height:1}.snack{bottom:144px}}@media(max-width:420px){.nav button{min-width:72px;font-size:12px}.nav-label-wide{font-size:11px}.card-actions{gap:6px}.check,.action-plus,.icon-btn,.select-dot{width:40px;height:40px;border-radius:12px}.count-badge{min-width:28px;height:28px;padding:0 8px}}.standalone body{min-height:100dvh}.standalone .main-stage{padding-bottom:calc(190px + env(safe-area-inset-bottom))}.standalone .nav{padding-bottom:calc(20px + env(safe-area-inset-bottom))}.standalone .add{bottom:calc(84px + env(safe-area-inset-bottom))}.standalone .selection-bar{bottom:calc(86px + env(safe-area-inset-bottom))}.standalone .snack{bottom:calc(164px + env(safe-area-inset-bottom))}@media (display-mode:standalone) and (max-width:1099px){html,body{min-height:100dvh}.main-stage{padding-bottom:calc(190px + env(safe-area-inset-bottom))}.nav{padding-bottom:calc(20px + env(safe-area-inset-bottom));}.add{bottom:calc(84px + env(safe-area-inset-bottom))}.selection-bar{bottom:calc(86px + env(safe-area-inset-bottom))}.snack{bottom:calc(164px + env(safe-area-inset-bottom))}}
/* 0.3.3 – illustrative mini icons + clean multi-select */
.mini-svg{width:34px;height:34px;display:block;overflow:visible;filter:drop-shadow(0 1px 1px rgba(41,55,46,.07))}.mini-svg .f1{fill:var(--i1)}.mini-svg .f2{fill:color-mix(in srgb,var(--i1) 28%,#fff)}.mini-svg .f3{fill:color-mix(in srgb,var(--i1) 48%,#fff)}.mini-svg .s{fill:none;stroke:color-mix(in srgb,var(--i1) 84%,#24382d);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.section-head .cat-icon{overflow:visible}.cat-choice .cat-icon{overflow:hidden;flex:none}
.section-head .cat-icon .mini-svg{width:32px;height:32px}
.card .item-icon{background:linear-gradient(145deg,#fffaf4,#f6f1ea);border:1px solid rgba(239,233,224,.8);overflow:visible}
.card .item-icon .mini-svg{width:32px;height:32px}
.catalog-row .item-icon .mini-svg{width:30px;height:30px}
.selection-active .add{display:none!important}
.selection-active .snack{display:none!important}
.selection-bar{bottom:76px;display:flex;flex-direction:column;gap:9px;padding:12px 13px;border:1px solid rgba(218,228,221,.95);border-radius:22px;background:rgba(255,253,250,.98);color:var(--text);box-shadow:0 18px 44px rgba(36,52,42,.20);backdrop-filter:blur(18px);z-index:9}
.selection-head{display:flex;align-items:center;justify-content:space-between;gap:12px;padding:0 2px}
.selection-head strong{display:block;font-size:17px}.selection-head small{display:block;margin-top:2px;color:var(--muted);font-size:12px}
.selection-counter{min-width:34px;height:34px;padding:0 10px;display:grid;place-items:center;border-radius:999px;background:var(--green-soft);color:var(--green);font-weight:850}
.selection-actions{display:grid;grid-template-columns:1fr 1fr 1fr;gap:9px}
.selection-actions button{padding:12px 13px;border-radius:14px;font-weight:800}
.selection-primary{background:var(--green)!important;color:#fff!important;box-shadow:0 8px 18px rgba(56,122,87,.20)}.selection-list{background:#e9f0fb!important;color:#355d8a!important;box-shadow:inset 0 0 0 1px rgba(77,119,169,.12)}
.selection-primary:disabled{opacity:.38;box-shadow:none;cursor:default}
.selection-cancel{background:#eef3ef!important;color:#365043!important}
.select-dot{border:2px solid #6a8978;background:#f6faf7;color:#fff;font-size:18px}
.select-dot.is-selected{border-color:var(--green);background:var(--green);box-shadow:0 8px 18px rgba(56,122,87,.20)}
.standalone .selection-bar{bottom:calc(90px + env(safe-area-inset-bottom))}
@media (display-mode:standalone) and (max-width:1099px){.selection-bar{bottom:calc(90px + env(safe-area-inset-bottom))}}
@media(max-width:520px){.selection-bar{width:calc(100% - 20px);padding:11px 12px}.selection-actions{grid-template-columns:1fr 1fr}.selection-actions button{padding:12px 8px;font-size:14px}.selection-cancel{grid-column:1/-1}}
.standalone .content-head{margin-top:28px;padding-top:18px}.standalone .main-stage{padding-top:4px}@media (display-mode:standalone) and (max-width:1099px){.content-head{margin-top:28px;padding-top:18px}.main-stage{padding-top:4px}}

.mini-img{width:36px;height:36px;display:block;object-fit:contain;filter:drop-shadow(0 1.5px 1px rgba(77,65,51,.14))}.section-head .cat-icon .mini-img{width:38px;height:38px}.side-link .cat-icon .mini-img{width:34px;height:34px}.card .item-icon .mini-img{width:38px;height:38px}.catalog-row .item-icon .mini-img{width:32px;height:32px}.catalog-category>.cat-choice{gap:14px;overflow:hidden}.catalog-category>.cat-choice .cat-icon{width:48px;height:48px;min-width:48px;flex:0 0 48px;overflow:hidden;border-radius:14px}.catalog-category>.cat-choice .category-photo{width:44px;height:44px;max-width:44px;max-height:44px}.catalog-category>.cat-choice .label{min-width:0;flex:1}.catalog-category>.cat-choice .label small{white-space:nowrap}.catalog-row .catalog-delete{padding:11px 13px;flex:none}
/* 0.3.8: Illustrative Mini – warme, handgezeichnete Formensprache */
.mini-svg{width:36px;height:36px;filter:drop-shadow(0 1.5px 1px rgba(77,65,51,.16))}.mini-svg .f1{fill:color-mix(in srgb,var(--i1) 72%,#f1b45e)}.mini-svg .f2{fill:color-mix(in srgb,var(--i2) 70%,#fff7e8)}.mini-svg .f3{fill:color-mix(in srgb,var(--i1) 32%,#f6d7a3)}.mini-svg .s{fill:none;stroke:#51483d;stroke-width:1.55;stroke-linecap:round;stroke-linejoin:round}.section-head .cat-icon,.side-link .cat-icon,.cat-choice .cat-icon{background:color-mix(in srgb,var(--cat-soft,#edf4ef) 74%,#fffaf2);box-shadow:inset 0 0 0 1px rgba(81,72,61,.035)}.card .item-icon{background:linear-gradient(145deg,#fffdf9,#f7f1e8);box-shadow:inset 0 0 0 1px rgba(81,72,61,.035)}
/* 0.3.8: klarere Hierarchie zwischen Kategorie, Artikel und Desktop-Seitenbereichen */
.section{background:linear-gradient(180deg,#eef4ef 0%,#f5f8f5 100%);border-color:#d6e1d9;box-shadow:0 15px 34px rgba(34,53,43,.085)}
.section-head{margin:-4px -4px 8px;padding:10px 10px 11px;background:#e5eee7;border:1px solid #d8e4db;border-radius:18px}
.list-group .card{background:linear-gradient(180deg,#fffdfa,#fbf8f3);border-color:#e8eee9}
.category-top-actions{display:grid;grid-template-columns:auto minmax(0,1fr) auto;gap:7px;margin:0 0 12px;align-items:stretch}
.category-top-actions button{min-width:0;padding:10px 8px;border-radius:12px;font-size:12px;line-height:1.15;font-weight:800;white-space:nowrap}
.category-top-actions .category-create{background:var(--green);color:#fff}
.category-top-actions .category-products,.category-top-actions .category-close{background:#eaf0eb;color:#294838}
.offline-status{display:inline-flex;align-items:center;gap:6px;width:max-content;max-width:100%;margin-top:7px;padding:5px 9px;border-radius:999px;font-size:11px;font-weight:800;letter-spacing:.01em;background:#e9f3eb;color:#356143;border:1px solid rgba(53,97,67,.12)}.offline-status::before{content:"";width:7px;height:7px;border-radius:50%;background:currentColor;opacity:.8}.offline-status.offline{background:#fff0dc;color:#9a5d16;border-color:#efd1aa}.offline-status.pending{background:#edf2fb;color:#466997;border-color:#cfdbee}.offline-status.syncing{background:#eef0f2;color:#59636d;border-color:#d8dde2}.offline-status.hidden{display:none}
@media(max-width:520px){.category-top-actions{gap:5px;margin-bottom:10px}.category-top-actions button{padding:9px 5px;font-size:10.5px;letter-spacing:-.025em}.sheet h2{margin-bottom:10px}}
@media(min-width:1100px){.sidebar{min-width:0}.sidebar .pane-card{min-width:0;padding:15px}.sidebar .side-list,.sidebar .side-link{min-width:0;max-width:100%;padding-left:11px;padding-right:11px}.sidebar .pane-head{min-width:0}.sidebar .pane-head>*{min-width:0}}
@media(min-width:1100px){html,body{height:100%;overflow:hidden}.app-shell{height:100vh;min-height:0;overflow:hidden}.desktop-pane,.main-stage{position:relative;top:auto;align-self:stretch;height:calc(100vh - 36px);min-height:0;overscroll-behavior:contain}.desktop-pane{overflow-y:auto;overflow-x:hidden;scrollbar-width:none;-ms-overflow-style:none}.desktop-pane::-webkit-scrollbar{width:0;height:0;display:none}.main-stage{overflow-y:auto;overflow-x:hidden;scrollbar-gutter:stable;scrollbar-width:thin;scrollbar-color:rgba(62,91,72,.34) transparent}.main-stage::-webkit-scrollbar{width:8px}.main-stage::-webkit-scrollbar-track{background:transparent}.main-stage::-webkit-scrollbar-thumb{background:rgba(62,91,72,.28);border-radius:999px;border:2px solid transparent;background-clip:padding-box}.sidebar,.utility{align-content:start;padding:12px;border:1px solid rgba(195,210,200,.92);border-radius:28px;background:linear-gradient(180deg,rgba(225,235,228,.96),rgba(235,242,237,.92));box-shadow:inset 0 1px 0 rgba(255,255,255,.7),0 12px 30px rgba(37,57,45,.07)}.sidebar .pane-card,.utility .pane-card{background:rgba(255,253,250,.92);border-color:rgba(255,255,255,.9)}.main-stage{min-height:0;padding-bottom:26px}.main-stage>.section:last-child{margin-bottom:24px}}

/* 0.3.20 – produktiver Icon-Baukasten */
.product-visual-svg{width:40px;height:40px;display:block;overflow:visible;filter:drop-shadow(0 1.5px 1.5px rgba(62,52,42,.13))}.product-visual-svg .vb{fill:#fffaf2;stroke:#6a6258;stroke-width:1.15;stroke-linejoin:round}.product-visual-svg .vb2{fill:#f1eadf;stroke:#6a6258;stroke-width:1.05;stroke-linejoin:round}.product-visual-svg .vm1{fill:var(--pv1,#5d8a64)}.product-visual-svg .vm2{fill:var(--pv2,#e7b65b)}.product-visual-svg .vms{fill:none;stroke:#51483d;stroke-width:1.3;stroke-linecap:round;stroke-linejoin:round}.product-visual-svg .vlabel{font:800 5.3px/1.1 system-ui,-apple-system,sans-serif;letter-spacing:.15px;fill:#4e493f;text-anchor:middle}.visual-editor{display:grid;grid-template-columns:150px minmax(0,1fr);gap:16px;align-items:start;margin:14px 0 18px}.visual-preview-card{display:grid;place-items:center;min-height:150px;border-radius:22px;background:linear-gradient(145deg,#fffdf9,#f4eee5);border:1px solid #e7ded2}.visual-preview-card .product-visual-svg{width:105px;height:105px}.visual-fields{display:grid;gap:11px}.visual-fields label{display:grid;gap:6px;font-size:13px;font-weight:800;color:#496052}.visual-fields input,.visual-fields select{width:100%;padding:11px 12px;border-radius:13px;border:1px solid #d6e1d9;background:#fff;color:var(--text);font:inherit}.visual-hint{font-size:12px;color:var(--muted);line-height:1.4}.proposal-note{padding:10px 12px;border-radius:13px;background:#eef5ff;color:#42648c;font-size:13px;font-weight:700}.catalog-row .label small{display:inline-flex;gap:5px;flex-wrap:wrap}.visual-source-pill{padding:2px 7px;border-radius:999px;background:#eef3ef;color:#597064;font-size:10px;font-weight:800}.editor-status{display:inline-flex;align-items:center;padding:5px 9px;border-radius:999px;background:#eef3ef;color:#587064;font-size:12px;font-weight:800}.editor-status.processed{background:#e6f1ea;color:#2f6b4b}.editor-status.processing{background:#fff4de;color:#8b6727}.editor-status-row{display:flex;align-items:center;gap:8px;margin:-2px 0 12px}.icon-hint-help{display:block;margin:-6px 0 10px;color:var(--muted);font-size:13px}@media(max-width:600px){.visual-editor{grid-template-columns:1fr}.visual-preview-card{min-height:120px}.visual-preview-card .product-visual-svg{width:90px;height:90px}}

/* 0.3.20 – freigegebener farbiger Illustrationsstil */
/* 0.3.20 – die farbigen Mini-Illustrationen bleiben auch mobil gut erkennbar */
.product-visual-v2{width:56px;height:56px}
.card .item-icon{width:58px;height:58px;border-radius:0;background:transparent;border:0;overflow:visible}
@media(max-width:720px){.product-visual-v2{width:50px;height:50px}.card .item-icon{width:52px;height:52px;border-radius:0;background:transparent;border:0}.section-head .cat-icon{width:40px;height:40px}}
.product-visual-v2{width:50px;height:50px;display:block;overflow:visible;filter:drop-shadow(0 2px 2px rgba(62,52,42,.12))}.product-visual-v2 .vm1{fill:var(--pv1,#4f9d59)}.product-visual-v2 .vm2{fill:var(--pv2,#e8c56d)}.product-visual-v2 .vms{fill:none;stroke:#544c43;stroke-width:1.45;stroke-linecap:round;stroke-linejoin:round}.product-visual-v2 .vb{fill:#fffaf2;stroke:#6a6258;stroke-width:1.05}.product-visual-v2 .vb2{fill:#f1eadf;stroke:#6a6258;stroke-width:1}.product-visual-v2 .vlabel{font:800 6px/1 system-ui,-apple-system,sans-serif;fill:#4d493f;text-anchor:middle}.product-visual-v2 .v2-pack-motif{opacity:.96}.category-visual-v2{width:42px;height:42px;display:block;overflow:visible;filter:drop-shadow(0 2px 2px rgba(70,58,45,.12))}.visual-preview-card .product-visual-v2{width:112px;height:112px}.catalog-row .product-visual-v2{width:44px;height:44px}@media(max-width:600px){.visual-preview-card .product-visual-v2{width:96px;height:96px}}

/* 0.3.20 – direkte, flächige Produktillustrationen (ohne Icon-Kachel) */
.card .item-icon{width:62px;height:62px;border:0;border-radius:0;background:transparent;overflow:visible}.product-visual-v3{width:62px;height:62px;display:block;overflow:visible;filter:drop-shadow(0 3px 2px rgba(62,52,42,.15))}.product-visual-v3 .shine{fill:#fff;opacity:.38}.product-visual-v3 .label{font:900 6px/1 system-ui,-apple-system,sans-serif;letter-spacing:.1px;text-anchor:middle;fill:#fff}.product-visual-v3 .label-dark{font:900 5.4px/1 system-ui,-apple-system,sans-serif;letter-spacing:.08px;text-anchor:middle;fill:#284639}.section-head .cat-icon,.cat-choice .cat-icon{background:transparent;border:0}.section-head .cat-icon{width:46px;height:46px}.visual-preview-card .product-visual-v3{width:124px;height:124px}.catalog-row .product-visual-v3{width:46px;height:46px}@media(max-width:720px){.card .item-icon{width:52px;height:52px}.product-visual-v3{width:52px;height:52px}.section-head .cat-icon{width:42px;height:42px}}@media(max-width:600px){.visual-preview-card .product-visual-v3{width:104px;height:104px}}.product-photo{width:62px;height:62px;display:block;object-fit:contain;border-radius:15px;filter:drop-shadow(0 2px 2px rgba(62,52,42,.10))}.category-photo{width:50px;height:50px;display:block;object-fit:contain;border-radius:13px;filter:drop-shadow(0 2px 2px rgba(62,52,42,.10))}.catalog-row .product-photo{width:46px;height:46px}.visual-preview-card .product-photo{width:124px;height:124px;border-radius:24px}.section-head .category-photo{width:50px;height:50px}.side-link .category-photo{width:44px;height:44px}@media(max-width:720px){.product-photo{width:54px;height:54px}.card .item-icon{width:54px;height:54px}.section-head .category-photo{width:44px;height:44px}}
.photo-state-wrap{position:relative;width:100%;height:100%;display:grid;place-items:center}.photo-state-badge{position:absolute;right:-3px;bottom:-3px;min-width:18px;height:18px;padding:0 5px;border-radius:999px;display:grid;place-items:center;font-size:10px;line-height:1;font-weight:900;background:#edf2fb;color:#466997;border:1px solid #cbd8e9;box-shadow:0 2px 5px rgba(34,53,43,.12)}.photo-state-badge.error{background:#fff0e7;color:#9b4c2e;border-color:#edc5b5}.photo-state-badge.pending{animation:imagepulse 1.1s ease-in-out infinite}@keyframes imagepulse{0%,100%{opacity:.55;transform:scale(.92)}50%{opacity:1;transform:scale(1)}}.catalog-link{width:38px;height:38px;border-radius:13px;background:#eef3ef;color:#355246;font-weight:900;display:grid;place-items:center}.gemini-cost-box{display:grid;gap:3px;margin:12px 0;padding:12px 14px;border:1px solid #dce7df;border-radius:16px;background:#fff}.gemini-cost-box strong{color:#2d4f3c}.gemini-cost-box span{color:var(--muted);font-size:13px}.sheet textarea{width:100%;padding:13px;border:1px solid #d9e2dc;background:#fff;color:var(--text);border-radius:14px;margin:5px 0 12px;resize:vertical;font:inherit}.category-manage-row .label small{margin-top:4px;line-height:1.25}.category-editor-preview{width:116px;height:116px;margin:0 auto 16px;display:grid;place-items:center;border-radius:24px;background:#fff;border:1px solid #e1e9e3}.category-editor-preview .category-photo{width:104px;height:104px}.wrap-actions{flex-wrap:wrap}.danger-zone{display:grid;gap:8px;margin:18px 0 12px;padding:14px;border:1px solid #efcaca;border-radius:16px;background:#fff7f7}.danger-zone span{font-size:13px;color:var(--muted)}@media(max-width:420px){.catalog-link{width:34px;height:34px;border-radius:12px}.category-manage-row{flex-wrap:wrap}.category-manage-row .label{min-width:calc(100% - 70px)}}.qty-inline{display:none}@media(max-width:520px){.qty-actions{display:none}.qty-inline{display:inline-flex}.item-subline{margin-top:3px}.card .name{font-size:17px}.card-main{gap:10px}}
/* 0.3.35 – ruhiges Ein-Zeile-pro-Artikel-Design */
.section{padding:0 10px 10px;overflow:hidden;background:rgba(247,250,247,.92);border:1px solid rgba(191,214,198,.68);box-shadow:0 10px 26px rgba(43,67,53,.075)}
.section-head{margin:0 -10px 4px;padding:14px 16px;border:0;background:linear-gradient(90deg,rgba(220,238,226,.88),rgba(237,246,240,.78))}
.section-title{gap:14px}.section-head .cat-icon{width:62px;height:62px;border-radius:20px;background:#fff;border:1px solid rgba(214,226,217,.86);box-shadow:0 4px 12px rgba(45,67,55,.06);overflow:hidden}
.section-head .category-photo{width:58px;height:58px;border-radius:17px}.section-head h2{font-size:23px;line-height:1.08;letter-spacing:-.02em}.section-head small{font-size:14px;margin-top:4px}
.count-badge{min-width:36px;height:36px;font-size:14px}.collapse-btn{width:38px;height:38px;border-radius:14px;background:rgba(255,255,255,.78)}
.list-group{gap:8px}.card{min-height:102px;padding:7px 14px 7px 8px;border-radius:20px;background:#fff;border:1px solid rgba(226,233,228,.92);box-shadow:0 4px 12px rgba(32,50,40,.045)}.card::before{display:none}.card:active{transform:scale(.997)}
.card-main{gap:16px}.card .item-icon{width:92px;height:88px;border-radius:18px;background:#fff;border:0;overflow:hidden}.card .product-photo{width:88px;height:84px;border-radius:17px;object-fit:contain}.card .name{font-size:21px;line-height:1.12;font-weight:780;white-space:normal;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.item-subline{margin-top:8px;gap:7px;font-size:14px}.qty,.entry-note{display:inline-flex;align-items:center;max-width:100%;padding:6px 10px;border-radius:999px;background:#edf4ef;color:#335342;font-size:13px;font-weight:750;line-height:1.2;white-space:normal}.entry-note{background:#f1f5f2}.product-detail{display:inline-flex;align-items:center;color:#687970;font-size:13px;font-weight:720;line-height:1.2;padding:3px 1px}.card-actions{min-width:0}.check{display:none!important}
@media(max-width:720px){.section{margin-top:14px;padding:0 8px 8px;border-radius:22px}.section-head{margin:0 -8px 2px;padding:12px 12px}.section-head .cat-icon{width:56px;height:56px;border-radius:18px}.section-head .category-photo{width:52px;height:52px;border-radius:15px}.section-head h2{font-size:20px}.section-head small{font-size:13px}.card{min-height:92px;padding:6px 12px 6px 6px;border-radius:18px}.card-main{gap:12px}.card .item-icon{width:82px;height:80px;border-radius:16px}.card .product-photo{width:78px;height:76px;border-radius:15px}.card .name{font-size:19px}.item-subline{margin-top:6px}.qty,.entry-note{font-size:12.5px;padding:5px 9px}}
@media(max-width:420px){.card .item-icon{width:76px;height:74px}.card .product-photo{width:72px;height:70px}.card .name{font-size:18px}.section-head h2{font-size:19px}}

/* 0.3.35 – ruhiges Ein-Zeile-Layout nach dem gewählten Entwurf */
.section{background:linear-gradient(180deg,rgba(231,241,234,.94),rgba(239,246,241,.88));border:1px solid #d8e5dc;box-shadow:0 7px 22px rgba(31,52,40,.055)}
.section-head{border-bottom:0;margin-bottom:0}.section-head .cat-icon{background:rgba(255,255,255,.45);overflow:hidden}.section-head .category-photo{object-fit:contain}.collapse-btn{border-radius:999px;background:rgba(255,255,255,.82);box-shadow:none}.list-group{gap:7px}
.card{background:rgba(255,255,255,.96);border-color:#e4ebe6;box-shadow:0 3px 10px rgba(35,53,43,.035)}
.card .item-icon{display:grid;place-items:center;overflow:hidden}.card .product-photo{filter:none}.card .name{color:#203129}.item-subline{color:#607269}
@media(max-width:720px){.section{padding:0 8px 9px}.section-head{padding:12px 10px 10px}.section-head .cat-icon{width:60px;height:60px;border-radius:19px}.section-head .category-photo{width:56px;height:56px;border-radius:16px}.section-head h2{font-size:21px}.section-head small{font-size:14px}.card{min-height:108px;padding:7px 14px 7px 7px}.card-main{gap:14px}.card .item-icon{width:98px;height:94px;border-radius:18px}.card .product-photo{width:94px;height:90px;border-radius:17px}.card .name{font-size:20px;line-height:1.16}.item-subline{margin-top:7px}.qty,.entry-note{font-size:13px;padding:5px 9px}}
@media(max-width:420px){.card{min-height:102px}.card .item-icon{width:90px;height:88px}.card .product-photo{width:86px;height:84px}.card .name{font-size:19px}.section-head .cat-icon{width:56px;height:56px}.section-head .category-photo{width:52px;height:52px}}

/* 0.3.36 – kompakter Kopf, kompakte Navigation und kein Doppeltipp-Zoom */
html,body,.app-shell,.main-stage,#list,.section,.card,.section-head,.nav,.add{touch-action:manipulation}
.content-head{padding:calc(7px + env(safe-area-inset-top)) 2px 5px;gap:8px}.eyebrow{margin:0 0 2px;font-size:10px;letter-spacing:.07em}.content-head h1{font-size:28px;line-height:1.02}.summary{margin-top:4px;font-size:12.5px}.top-actions{gap:6px}.round{width:40px;height:40px;border-radius:13px;font-size:19px}
.nav{padding:5px 6px calc(6px + env(safe-area-inset-bottom))}.nav button{gap:1px;min-width:70px;padding:3px 7px;font-size:11.5px}.nav button .emoji{font-size:16px}.nav-label-wide{font-size:10.5px}.add{bottom:48px}.selection-bar{bottom:50px}.snack{bottom:118px}.main-stage{padding-bottom:118px}
.catalog-search-wrap{position:sticky;top:-18px;z-index:2;padding:6px 0 10px;background:linear-gradient(#f7faf7 78%,rgba(247,250,247,0))}.catalog-search{width:100%;padding:12px 14px!important;margin:0!important;border-radius:14px!important}.catalog-search-empty{padding:18px 8px;color:var(--muted);text-align:center}.inherited-source-note{margin:-4px 0 12px!important;color:#4d6d5a!important;font-weight:700}
@media(max-width:720px){.main-stage{padding-top:2px;padding-bottom:108px}.content-head{align-items:center;padding:calc(3px + env(safe-area-inset-top)) 4px 3px}.content-head .eyebrow{display:none}.content-head h1{font-size:24px;max-width:250px;letter-spacing:-.035em}.summary{margin-top:2px;font-size:11.5px}.top-actions .round{width:36px;height:36px;font-size:17px}.nav{padding-top:3px}.nav button{min-width:62px;padding:1px 5px}.add{bottom:43px}.snack{bottom:108px}}
.standalone .main-stage{padding-bottom:calc(138px + env(safe-area-inset-bottom))}.standalone .nav{padding-bottom:calc(8px + env(safe-area-inset-bottom))}.standalone .add{bottom:calc(52px + env(safe-area-inset-bottom))}.standalone .selection-bar{bottom:calc(54px + env(safe-area-inset-bottom))}.standalone .snack{bottom:calc(124px + env(safe-area-inset-bottom))}
@media (display-mode:standalone) and (max-width:1099px){.main-stage{padding-bottom:calc(138px + env(safe-area-inset-bottom))}.nav{padding-bottom:calc(8px + env(safe-area-inset-bottom))}.add{bottom:calc(52px + env(safe-area-inset-bottom))}.selection-bar{bottom:calc(54px + env(safe-area-inset-bottom))}.snack{bottom:calc(124px + env(safe-area-inset-bottom))}}

/* 0.3.41 – weitere Verdichtung, klare Metadaten und stabile mobile Verwaltung */
html,body{max-width:100%;overflow-x:hidden}.sheet{max-width:100vw;overflow-x:hidden}.summary{display:inline-block;margin-right:5px}.offline-status{margin-top:2px}.offline-status:not(.offline):not(.pending):not(.syncing){padding:0;border:0;background:transparent;color:#4f765e;font-size:10.5px}.offline-status:not(.offline):not(.pending):not(.syncing)::before{width:6px;height:6px}
.section{margin-top:10px}.section-head{padding-top:8px!important;padding-bottom:7px!important}.section-title{gap:10px}.section-title>div{min-width:0}.section-head h2{max-width:100%;overflow-wrap:anywhere}.section-head h2.long-category{font-size:17px;line-height:1.08;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}.section-head small{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.shop-badge{display:inline-flex;align-items:center;padding:2px 6px;border-radius:999px;background:rgba(255,255,255,.72);border:1px solid rgba(85,117,94,.12);color:#58715f;font-size:9.5px;font-weight:800;letter-spacing:.02em}.qty{background:#e5f1e8;color:#2f5e43}.product-detail{padding:4px 8px;border-radius:8px;background:#eef3f6;color:#546a73;font-size:12px;font-weight:760}.entry-note{background:#f4efe7;color:#6c5b45;border-radius:10px;font-weight:700}.category-row-actions{display:flex;gap:7px;flex:none}.category-manage-row{max-width:100%;min-width:0}.category-manage-row .label{min-width:0}.category-manage-row .label strong,.category-manage-row .label small{overflow-wrap:anywhere}.manage-quick-actions{display:flex;gap:8px;margin:0 0 12px}.manage-quick-actions button{flex:1}.list-search-results{display:grid;gap:7px;margin-top:8px}.list-search-result{display:flex;align-items:center;gap:10px;width:100%;padding:10px;border-radius:14px;background:#fff;border:1px solid #e2eae4;color:var(--text);text-align:left}.list-search-result .item-icon{width:46px;height:46px;flex:none}.list-search-result .product-photo{width:44px;height:44px;border-radius:11px}.list-search-result .label{min-width:0;flex:1}.list-search-result strong{display:block}.list-search-result small{display:block;color:var(--muted);margin-top:2px}.list-search-empty{padding:20px 8px;text-align:center;color:var(--muted)}
.add{padding:6px 7px;gap:7px;border-radius:18px;transition:padding .16s ease,border-radius .16s ease}.add input{padding:10px 13px;border-radius:13px;transition:padding .16s ease}.add .primary{border-radius:13px}.add:focus-within{padding:8px;border-radius:20px}.add:focus-within input{padding:13px 14px}.nav{padding-top:2px}.nav button{padding-top:0;padding-bottom:0;font-size:10.5px;gap:0}.nav button .emoji{font-size:15px}.nav-label-wide{font-size:9.8px}.main-stage{padding-bottom:102px}.add{bottom:36px}.snack{bottom:94px}
@media(max-width:720px){.sheet{width:100%}.content-head{padding:calc(0px + env(safe-area-inset-top)) 4px 1px;gap:5px}.content-head{border-top-width:3px}.content-head h1{font-size:22px;line-height:1}.summary{font-size:10.8px;margin-top:2px}.top-actions{gap:4px}.top-actions .round{width:33px;height:33px;border-radius:11px;font-size:16px}.section{margin-top:9px;padding-bottom:7px}.section-head .cat-icon{width:52px;height:52px;border-radius:17px}.section-head .category-photo{width:48px;height:48px;border-radius:14px}.section-head h2{font-size:19px}.section-head small{font-size:11.5px;margin-top:2px}.section-head h2.long-category{font-size:16px}.collapse-btn{width:34px;height:34px}.list-group{gap:6px}.nav{padding-bottom:calc(4px + env(safe-area-inset-bottom))}.nav button{min-width:58px}.add{width:calc(100% - 12px);bottom:34px}.main-stage{padding-bottom:96px}.snack{bottom:91px}.category-manage-row{display:grid;grid-template-columns:44px minmax(0,1fr);align-items:center;gap:8px;padding:9px}.category-manage-row>.cat-icon{grid-column:1;grid-row:1}.category-manage-row>.label{grid-column:2;grid-row:1}.category-row-actions{grid-column:1 / -1;display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:6px}.category-row-actions .secondary,.category-row-actions .danger{width:100%;min-width:0;padding:9px 6px}.sheet{padding-left:14px;padding-right:14px}.manage-quick-actions{flex-direction:column}.standalone .main-stage{padding-bottom:calc(118px + env(safe-area-inset-bottom))}.standalone .nav{padding-bottom:calc(5px + env(safe-area-inset-bottom))}.standalone .add{bottom:calc(39px + env(safe-area-inset-bottom))}.standalone .snack{bottom:calc(98px + env(safe-area-inset-bottom))}}
@media (display-mode:standalone) and (max-width:1099px){.main-stage{padding-bottom:calc(118px + env(safe-area-inset-bottom))}.nav{padding-bottom:calc(5px + env(safe-area-inset-bottom))}.add{bottom:calc(39px + env(safe-area-inset-bottom))}.snack{bottom:calc(98px + env(safe-area-inset-bottom))}}

/* 0.3.41 – stabile Offline-Bilder und ruhige mobile Bottom-Navigation */
.nav{height:calc(62px + env(safe-area-inset-bottom));display:grid;grid-template-columns:repeat(3,minmax(0,1fr));align-items:stretch;justify-content:initial;padding:5px 9px env(safe-area-inset-bottom);background:rgba(255,253,250,.96);backdrop-filter:blur(18px);border-top:1px solid #dfe5e0}
.nav button{min-width:0;width:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;padding:4px 5px 3px;border-radius:10px;background:transparent;color:#75847b;font-size:10.5px;line-height:1.05;font-weight:720}
.nav button.active{color:var(--green)}.nav-icon{width:21px;height:21px;display:block;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}.nav-icon-star{fill:currentColor;stroke:currentColor}.nav-label-wide{font-size:10.2px;letter-spacing:-.015em;white-space:nowrap}
.add{bottom:calc(70px + env(safe-area-inset-bottom));width:min(860px,calc(100% - 24px))}.main-stage{padding-bottom:150px}.selection-bar{bottom:calc(72px + env(safe-area-inset-bottom))}.snack{bottom:calc(136px + env(safe-area-inset-bottom))}
@media(max-width:720px){.add input,.sheet input,.sheet select,.sheet textarea{font-size:16px}.nav{height:calc(62px + env(safe-area-inset-bottom));padding:5px 8px env(safe-area-inset-bottom)}.nav button{min-width:0;font-size:10.5px;gap:2px}.nav button .emoji{display:none}.nav-icon{width:21px;height:21px}.nav-label-wide{font-size:10px}.add{bottom:calc(70px + env(safe-area-inset-bottom));width:calc(100% - 12px)}.main-stage{padding-bottom:150px}.selection-bar{bottom:calc(72px + env(safe-area-inset-bottom))}.snack{bottom:calc(136px + env(safe-area-inset-bottom))}.standalone .main-stage{padding-bottom:150px}.standalone .nav{height:calc(62px + env(safe-area-inset-bottom));padding-bottom:env(safe-area-inset-bottom)}.standalone .add{bottom:calc(70px + env(safe-area-inset-bottom))}.standalone .snack{bottom:calc(136px + env(safe-area-inset-bottom))}}
@media (display-mode:standalone) and (max-width:1099px){.main-stage{padding-bottom:150px}.nav{height:calc(62px + env(safe-area-inset-bottom));padding-bottom:env(safe-area-inset-bottom)}.add{bottom:calc(70px + env(safe-area-inset-bottom))}.snack{bottom:calc(136px + env(safe-area-inset-bottom))}}

/* 0.3.41 – einkaufstaugliche Gesten und aufgeräumte Editoren */
.card{touch-action:manipulation;-webkit-tap-highlight-color:transparent}.card.checking{opacity:0;transform:translateX(14px) scale(.985);pointer-events:none}.check:active{transform:scale(.94)}
.offline-status.online{background:#e6f1ea;color:#2f6b4b;border-color:#bfdcc9}.offline-status.offline{background:#fde8e8;color:#a73333;border-color:#efbebe}
.sheet-head{position:sticky;top:-18px;z-index:4;display:flex;align-items:center;justify-content:space-between;gap:12px;margin:-4px -2px 14px;padding:10px 2px 9px;background:linear-gradient(180deg,#f7faf7 78%,rgba(247,250,247,.96));border-bottom:1px solid #e0e8e2}.sheet-head h2{margin:0;min-width:0}.sheet-head-actions{display:flex;gap:8px;flex:none;align-items:center}.sheet-icon-action{min-width:46px;height:46px;display:inline-flex;align-items:center;justify-content:center;gap:8px;padding:0 14px;border-radius:15px;background:#f5f8f5;color:#315442;border:1px solid #d6e2da;box-shadow:0 4px 12px rgba(38,66,51,.07);font-size:14px;font-weight:800;white-space:nowrap}.sheet-icon-action.icon-only{width:46px;min-width:46px;padding:0;font-size:25px}.sheet-icon-action.save{background:var(--green);border-color:var(--green);color:#fff;box-shadow:0 7px 16px rgba(56,122,87,.20)}.sheet-icon-action svg{width:21px;height:21px;fill:none;stroke:currentColor;stroke-width:1.9;stroke-linecap:round;stroke-linejoin:round;flex:none}.category-first{margin-bottom:14px}.choice-arrow{margin-left:auto;font-size:22px;color:var(--muted)}
.editor-status.unprocessed,.catalog-status.unprocessed{background:#fde7e7;color:#a13232}.editor-status.processed,.catalog-status.processed{background:#e4f1e8;color:#2c6b49}.catalog-status.processing{background:#fff2d8;color:#886321}.catalog-status{display:inline-flex;align-items:center;margin-left:5px;padding:3px 8px;border-radius:999px;font-size:10.5px;font-weight:850}.catalog-provenance{display:inline-flex;margin-left:5px;color:#60756a;font-size:10.5px;font-weight:700}.catalog-row .label small{align-items:center}.catalog-row{padding:10px}.catalog-row .item-icon{flex:none}.catalog-row .secondary,.catalog-row .danger{width:38px;height:38px;padding:0;display:grid;place-items:center;border-radius:12px}
.editor-action-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:8px;margin:14px 0}.editor-action-grid.two{grid-template-columns:repeat(2,minmax(0,1fr))}.editor-action-card{min-height:72px;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:5px;padding:10px;border:1px solid #dce6df;border-radius:15px;background:#fff;color:#315443;font-weight:800;text-align:center}.editor-action-card .action-glyph{font-size:22px;line-height:1}.compact-danger{margin-top:14px;padding-top:14px}.compact-danger .danger{width:100%}.editor-back{margin-top:12px;width:100%}.editor-status-row{flex-wrap:wrap}.inherited-source-note{margin:0!important}.category-editor-preview{margin:2px auto 14px}.category-top-actions{grid-template-columns:1fr 1fr}.category-top-actions .category-create,.category-top-actions .category-products{padding:11px 8px}.category-manage-row .label small{display:none}
@media(max-width:520px){.sheet-head{top:-18px;align-items:flex-start}.sheet-head h2{font-size:24px;line-height:1.12}.sheet-head-actions{gap:6px}.sheet-icon-action{height:44px;border-radius:14px;padding:0 11px;font-size:13px}.sheet-icon-action.icon-only{width:44px;min-width:44px;padding:0}.sheet-icon-action .action-label{display:inline}.editor-action-grid{grid-template-columns:1fr}.editor-action-grid.two{grid-template-columns:1fr 1fr}.editor-action-card{min-height:58px}.catalog-row{gap:7px}.catalog-row .label strong{font-size:14px}.catalog-row .label small{display:flex;font-size:10px}}
@media(max-width:390px){.sheet-head-actions{flex-direction:column-reverse;align-items:stretch}.sheet-icon-action{height:40px;padding:0 9px}.sheet-head h2{font-size:22px}}
</style></head><body><div class="app-shell"><aside class="sidebar desktop-pane"><div class="pane-card"><div class="accent-line"></div><p class="eyebrow">Familie</p><h2 style="margin:0;font-size:30px;line-height:1.05">Einkaufsliste</h2><p class="summary" style="margin-top:10px">Schnell erfassen, unterwegs abhaken und zuhause automatisch synchron halten.</p></div><div class="pane-card"><div class="pane-head"><span>Listen</span><button class="round small" id="sidebar-manage" title="Listen verwalten">⚙</button></div><div id="desktop-list-switcher"></div></div><div class="pane-card"><div class="pane-head"><span>Bereiche</span><button class="chip-action" id="category-shortcut">Verwalten</button></div><div id="desktop-categories"></div></div></aside><main class="main-stage"><header class="content-head"><div class="title-wrap"><p class="eyebrow" id="view-label">Aktive Liste</p><h1 id="title" onclick="pickList()" onpointerdown="listTouchStart(event)" onpointerup="listTouchEnd(event)">Einkaufsliste</h1><p class="summary" id="summary"></p><div id="offline-status" class="offline-status hidden"></div></div><div class="top-actions"><button class="round" id="select-btn" title="Artikel auswählen">✓</button><button class="round" id="manage-btn" title="Listen und Kategorien verwalten">⚙</button></div></header><div id="add" class="add"><input id="input" placeholder="z. B. Milch, Brot oder 500 g Mehl"><button class="primary" id="add-btn"><span class="add-label">Hinzufügen</span><span class="add-plus">＋</span></button></div><div class="desktop-tabs"><button id="desktop-list-tab" class="tab active" type="button" onclick="showList()">Liste</button><button id="desktop-recent-tab" class="tab" type="button" onclick="showRecent()">Zuletzt</button><button class="tab ghost" type="button" onclick="manageCategories()">Kategorien</button></div><div id="list"></div></main><aside class="utility desktop-pane"><div id="desktop-utility" class="utility-stack"></div></aside></div><div id="selection-bar" class="selection-bar hidden"></div><nav class="nav"><button id="list-btn" class="active" type="button"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M3 4h2l2.2 10.2a2 2 0 0 0 2 1.6h7.7a2 2 0 0 0 1.9-1.4L21 8H6.2"/><circle cx="10" cy="20" r="1.4"/><circle cx="18" cy="20" r="1.4"/></svg><span>Liste</span></button><button id="recent-btn" type="button"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="8.5"/><path d="M12 7.5v5l3.5 2"/></svg><span class="nav-label">Zuletzt</span></button><button id="category-nav" type="button"><svg class="nav-icon" viewBox="0 0 24 24" aria-hidden="true"><path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></svg><span>Kategorien</span></button></nav><div id="overlay" class="hidden"></div><div id="snack" class="hidden"></div><input id="restore-file" type="file" accept="application/json" class="hidden"><script>
let appState={updatedAt:null,lists:[],activeListId:'',syncListId:'',list:null,categories:[],entries:[],recent:[],products:[],geminiConfigured:false,geminiStatus:null,imageStatus:null,geminiImageUsage:null}, selectionMode=false, selected=new Set(), collapsedCategories=new Set(), pressTimer=null, editId=null, editCategory=null, view='list', lastTap={id:'',time:0}, snackTimer=null, listTouchX=null, swipeStart=null, suppressTitleClick=false, holdTriggered=false, gestureMoved=false, listEditId=null, autoRefreshBusy=false, catalogReturnMode='catalog';
let offlineQueue=[],offlineDb=null,offlineStorageReady=false,serverReachable=null,offlineSyncBusy=false,lastOfflineConflictNotice='',offlineWorkerReady=false,offlineWorkerAvailable=('serviceWorker'in navigator),offlineWorkerRegistration=null,offlineAssetsReady=false,offlineImageSignature='',offlineWarmTimer=null;
const OFFLINE_DB='eigene-einkaufsliste-offline-v1',OFFLINE_STORE='kv',OFFLINE_CACHE_KEY='localState',OFFLINE_BASE_KEY='baseState',OFFLINE_QUEUE_KEY='queue';
const isStandalone=window.matchMedia('(display-mode: standalone)').matches||window.navigator.standalone===true;if(isStandalone)document.documentElement.classList.add('standalone');
const $=id=>document.getElementById(id); const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const deepClone=v=>v==null?v:JSON.parse(JSON.stringify(v));
function eur(v){return Number(v||0).toLocaleString('de-DE',{minimumFractionDigits:4,maximumFractionDigits:4})+' €'}
function geminiCostHtml(){const u=appState.geminiImageUsage||{};const last=u.lastGeneration;const lastText=last?(last.costEur==null?'Letzte Erstellung: Kosten nicht vollständig ermittelbar':'Letzte Erstellung: '+eur(last.costEur)):'Letzte Erstellung: noch keine seit '+esc(u.trackingVersion||'0.3.29');const lastItem=last&&last.itemName?((last.kind==='category'?'Kategorie':'Artikel')+': '+esc(last.itemName)):'';return '<div id="gemini-cost-box" class="gemini-cost-box"><strong>Gemini-Iconkosten</strong><span>'+lastText+'</span>'+(lastItem?'<span><strong>Zuletzt erstellt</strong><br>'+lastItem+'</span>':'')+'<span>Heute: '+Number(u.todayImages||0)+' · '+eur(u.todayCostEur||0)+'</span><span>Gesamt seit '+esc(u.trackingVersion||'0.3.29')+': '+Number(u.totalImages||0)+' · '+eur(u.totalCostEur||0)+'</span><span>Nach tatsächlicher API-Nutzung berechnet; Euro-Umrechnung mit dem gespeicherten ECB-Tagesreferenzkurs.</span></div>'}
function refreshGeminiCostDisplay(){const box=$('gemini-cost-box');if(box)box.outerHTML=geminiCostHtml()}
const offlineId=()=>window.crypto?.randomUUID?.()||('offline-'+Date.now()+'-'+Math.random().toString(16).slice(2));
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function api(url,options={}){const raw=String(url||'');const requestUrl=/^https?:\/\//i.test(raw)?raw:new URL(raw.replace(/^\/+/,''),document.baseURI).href;const controller=new AbortController();const upstreamSignal=options.signal;const timer=setTimeout(()=>controller.abort(),10000);if(upstreamSignal){if(upstreamSignal.aborted)controller.abort();else upstreamSignal.addEventListener('abort',()=>controller.abort(),{once:true})}let r;try{const headers={...(options.headers||{})};if(options.body!=null&&!headers['content-type']&&!headers['Content-Type'])headers['content-type']='application/json';r=await fetch(requestUrl,{cache:'no-store',...options,headers,signal:controller.signal})}catch(error){const wrapped=error?.name==='AbortError'?new Error('Serveranfrage hat zu lange gedauert.'):error;wrapped.isNetwork=true;throw wrapped}finally{clearTimeout(timer)}let j={};try{j=await r.json()}catch{}if(!r.ok){const error=new Error(j.error||('HTTP '+r.status));error.status=r.status;throw error}return j}
function openOfflineDb(){if(offlineDb)return Promise.resolve(offlineDb);return new Promise((resolve,reject)=>{if(!('indexedDB'in window))return reject(new Error('IndexedDB nicht verfügbar'));let settled=false;const finish=(fn,value)=>{if(settled)return;settled=true;clearTimeout(timer);fn(value)};const timer=setTimeout(()=>finish(reject,new Error('IndexedDB reagiert nicht')),1200);let request;try{request=indexedDB.open(OFFLINE_DB,1)}catch(error){finish(reject,error);return}request.onupgradeneeded=()=>{const db=request.result;if(!db.objectStoreNames.contains(OFFLINE_STORE))db.createObjectStore(OFFLINE_STORE)};request.onsuccess=()=>{if(settled){try{request.result.close()}catch{}return}offlineDb=request.result;finish(resolve,offlineDb)};request.onerror=()=>finish(reject,request.error||new Error('Offline-Speicher konnte nicht geöffnet werden'));request.onblocked=()=>finish(reject,new Error('Offline-Speicher ist blockiert'))})}
async function offlineGet(key){try{const db=await openOfflineDb();return await new Promise((resolve,reject)=>{let settled=false;const done=(fn,value)=>{if(settled)return;settled=true;clearTimeout(timer);fn(value)};const timer=setTimeout(()=>done(reject,new Error('Offline-Lesen hat zu lange gedauert')),1000);let tx,req;try{tx=db.transaction(OFFLINE_STORE,'readonly');req=tx.objectStore(OFFLINE_STORE).get(key)}catch(error){done(reject,error);return}req.onsuccess=()=>done(resolve,req.result);req.onerror=()=>done(reject,req.error)})}catch{try{const raw=localStorage.getItem('einkauf-offline-'+key);return raw?JSON.parse(raw):null}catch{return null}}}
async function offlineSet(key,value){try{const db=await openOfflineDb();await new Promise((resolve,reject)=>{let settled=false;const done=(fn,value)=>{if(settled)return;settled=true;clearTimeout(timer);fn(value)};const timer=setTimeout(()=>done(reject,new Error('Offline-Schreiben hat zu lange gedauert')),1000);let tx;try{tx=db.transaction(OFFLINE_STORE,'readwrite');tx.objectStore(OFFLINE_STORE).put(value,key)}catch(error){done(reject,error);return}tx.oncomplete=()=>done(resolve);tx.onerror=()=>done(reject,tx.error);tx.onabort=()=>done(reject,tx.error||new Error('Offline-Schreiben wurde abgebrochen'))})}catch{try{localStorage.setItem('einkauf-offline-'+key,JSON.stringify(value))}catch{}}}
let offlineStorageInitPromise=null;
async function initOfflineStorage(){if(offlineStorageReady)return;if(offlineStorageInitPromise)return offlineStorageInitPromise;offlineStorageInitPromise=(async()=>{const stored=await offlineGet(OFFLINE_QUEUE_KEY);offlineQueue=Array.isArray(stored)?stored:[];offlineStorageReady=true;updateOfflineStatus()})();try{await offlineStorageInitPromise}finally{if(!offlineStorageReady)offlineStorageInitPromise=null}}
async function saveOfflineQueue(){await offlineSet(OFFLINE_QUEUE_KEY,offlineQueue);updateOfflineStatus()}
async function saveLocalState(){await offlineSet(OFFLINE_CACHE_KEY,deepClone(appState))}
function listSummaryDelta(state,listId,delta){const list=(state.lists||[]).find(item=>item.id===listId);if(list)list.itemCount=Math.max(0,Number(list.itemCount||0)+delta)}
function clientEntryKey(entry){const q=entry?.quantity||{};return [entry?.productKey||entry?.productId||entry?.productName||entry?.name||'',q.value??'',q.unit||'',keyText(entry?.productDetail||'')].join('|')}
function applyClientOperation(state,operation){if(!state||operation.listId!==state.activeListId)return state;const snapshot=deepClone(operation.entrySnapshot||{});const entryId=operation.entryId||snapshot.id;if(!entryId)return state;if(operation.type==='check'){const index=(state.entries||[]).findIndex(entry=>entry.id===entryId);if(index>=0){const [entry]=state.entries.splice(index,1);state.recent=[entry,...(state.recent||[]).filter(item=>item.id!==entryId)].slice(0,30);listSummaryDelta(state,operation.listId,-1)}}else if(operation.type==='restore'){if(!(state.entries||[]).some(entry=>entry.id===entryId)){const recentIndex=(state.recent||[]).findIndex(entry=>entry.id===entryId);const entry=recentIndex>=0?state.recent.splice(recentIndex,1)[0]:snapshot;if(entry&&entry.id){state.entries.push(entry);listSummaryDelta(state,operation.listId,1)}}}return state}
function materializePending(serverState){const next=deepClone(serverState);for(const operation of offlineQueue)applyClientOperation(next,operation);return next}
function updateOfflineStatus(){const el=$('offline-status');if(!el)return;const waiting=offlineQueue.length;let text='',kind='';if(serverReachable===false||navigator.onLine===false){text='Offline'+(waiting?' · '+waiting+' offene Änderung'+(waiting===1?'':'en'):'');kind='offline'}else if(serverReachable===true){text='Online';kind='online'}else{el.textContent='';el.className='offline-status hidden';return}el.textContent=text;el.className='offline-status '+kind}
async function persistOfflineView(){await saveOfflineQueue();await saveLocalState()}
async function syncPending(){await initOfflineStorage();if(offlineSyncBusy||!offlineQueue.length){updateOfflineStatus();return false}offlineSyncBusy=true;updateOfflineStatus();const batch=offlineQueue.map(deepClone);let succeeded=false;try{const response=await api('/api/offline-sync',{method:'POST',body:JSON.stringify({operations:batch,baseUpdatedAt:(await offlineGet(OFFLINE_BASE_KEY))?.updatedAt||null})});serverReachable=true;succeeded=true;const terminal=new Set((response.results||[]).filter(result=>['applied','already_applied','conflict','error'].includes(result.status)).map(result=>result.opId));const conflicts=(response.results||[]).filter(result=>['conflict','error'].includes(result.status));offlineQueue=offlineQueue.filter(operation=>!terminal.has(operation.opId));await saveOfflineQueue();await offlineSet(OFFLINE_BASE_KEY,deepClone(response.state));appState=materializePending(response.state);await saveLocalState();render();if(conflicts.length){const message=conflicts.length+' Offline-Änderung'+(conflicts.length===1?'':'en')+' konnte'+(conflicts.length===1?'':'n')+' nicht automatisch abgeglichen werden.';if(message!==lastOfflineConflictNotice){lastOfflineConflictNotice=message;showSnack(message)}}return true}catch(error){if(error.isNetwork)serverReachable=false;else serverReachable=true;return false}finally{offlineSyncBusy=false;updateOfflineStatus();if(succeeded&&offlineQueue.length)setTimeout(()=>syncPending(),20)}}
function currentOfflineImageUrls(){return [...document.querySelectorAll('img.product-photo,img.category-photo')].map(img=>img.currentSrc||img.src).filter(Boolean).map(src=>new URL(src,document.baseURI).href)}
function scheduleOfflineImageWarmup(){if(!offlineWorkerReady||serverReachable!==true)return;clearTimeout(offlineWarmTimer);offlineWarmTimer=setTimeout(()=>{const urls=[...new Set(currentOfflineImageUrls())].sort();const signature=urls.join('|');if(!urls.length){offlineAssetsReady=true;updateOfflineStatus();return}if(signature===offlineImageSignature&&offlineAssetsReady)return;offlineImageSignature=signature;offlineAssetsReady=false;updateOfflineStatus();const worker=offlineWorkerRegistration?.active||navigator.serviceWorker.controller;if(worker)worker.postMessage({type:'cache-images',urls})},180)}
function markOfflineWorkerReady(registration){offlineWorkerRegistration=registration||offlineWorkerRegistration;offlineWorkerReady=Boolean(offlineWorkerRegistration?.active||navigator.serviceWorker.controller);updateOfflineStatus();if(offlineWorkerReady)scheduleOfflineImageWarmup()}
async function registerOfflineWorker(){if(!offlineWorkerAvailable)return false;try{const workerUrl=new URL('sw.js',document.baseURI);const registration=await navigator.serviceWorker.register(workerUrl.href,{scope:'./'});offlineWorkerRegistration=registration;const candidate=registration.installing||registration.waiting||registration.active;if(candidate)candidate.addEventListener('statechange',()=>{if(candidate.state==='activated')markOfflineWorkerReady(registration)});const ready=await Promise.race([navigator.serviceWorker.ready,new Promise(resolve=>setTimeout(()=>resolve(null),2500))]);markOfflineWorkerReady(ready||registration);return offlineWorkerReady}catch(error){offlineWorkerAvailable=false;offlineWorkerReady=false;console.warn('Offline-Service-Worker konnte nicht registriert werden:',error);updateOfflineStatus();return false}}
const CAT_TONES={produce:['#3f7d55','#e8f3eb'],vegetarian:['#58844d','#edf5e9'],bakery_fitness:['#a66f38','#f8eee1'],baking:['#a07a45','#f6efe3'],milk:['#4d7894','#eaf2f7'],canned:['#7b7564','#f0eee9'],pasta_rice:['#9a7440','#f8f0e2'],oils_sauces:['#6c7f45','#eef2e6'],cheese:['#b88835','#fff4de'],household:['#587c79','#e8f2f1'],milk_uncooled:['#64849a','#edf3f6'],ready_chilled:['#8a695e','#f5ece8'],frozen:['#527fa8','#eaf2fb'],meat:['#9b5a5f','#f7e9ea'],drinks:['#4b78a6','#e9f0f8'],sweets:['#9b5f83','#f7eaf2'],drugstore:['#7b679a','#f0ebf7'],ice_cream:['#6d86a6','#eef3f9'],other:['#6e786f','#eef1ee']};
function categoryTone(id){if(CAT_TONES[id])return CAT_TONES[id];const c=(appState.categories||[]).find(x=>x.id===id);const map={yogurt_scene:'milk',counter_scene:'meat',stationery_scene:'household',kids_snack_scene:'sweets',cleaner_scene:'household',paper_scene:'household',bodycare_scene:'drugstore'};return CAT_TONES[map[c?.visualKind]]||CAT_TONES.other}
const CATEGORY_KIND={produce:'produce_scene',vegetarian:'veg_scene',bakery_fitness:'bakery_scene',baking:'baking_scene',milk:'milk_scene',canned:'can',pasta_rice:'pasta',oils_sauces:'oil',cheese:'cheese',household:'household_scene',milk_uncooled:'milk_scene',ready_chilled:'butter_scene',frozen:'frozen_scene',meat:'meat',drinks:'drink_scene',sweets:'sweet',drugstore:'drugstore_scene',ice_cream:'icecream_scene',other:'box'};
const ILLUSTRATIONS={
leaf:'<path class="f2" d="M8 33c5-14 17-23 31-24-1 14-10 27-25 29z"/><path class="s" d="M13 34c7-9 14-15 24-22"/><path class="f1" d="M9 15c8 0 14 4 17 10-8 2-15-1-20-7z"/>',
basket:'<path class="f3" d="M9 21h30l-4 18H13z"/><path class="s" d="M14 21c2-8 7-12 10-12s8 4 10 12M16 27h16M18 33h12"/><path class="f1" d="M10 18c6-7 12-8 17-6-3 6-9 9-17 6z"/><path class="f2" d="M27 14c5-5 10-5 14-3-2 5-7 7-14 3z"/>',
bread:'<path class="f3" d="M8 20c0-7 6-12 16-12s16 5 16 12v18H8z"/><path class="s" d="M14 20c3-3 6-4 9-2M23 15c3-2 6-2 9 1M16 27h16"/>',
flourbag:'<path class="f3" d="M12 9h24l-3 31H15z"/><path class="f2" d="M16 15h16v16H16z"/><path class="s" d="M13 14h22M19 26c3-5 7-7 10-8M24 18v12"/>',
milk:'<path class="f3" d="M15 8h15l4 8v24H14V16z"/><path class="f2" d="M15 18h19v12H15z"/><path class="s" d="M15 8l5 8h14M20 8v8"/>',
can:'<ellipse class="f3" cx="24" cy="10" rx="13" ry="5"/><path class="f2" d="M11 10v28c0 4 26 4 26 0V10z"/><ellipse class="s" cx="24" cy="10" rx="13" ry="5"/><path class="s" d="M11 10v28c0 4 26 4 26 0V10"/><circle class="f1" cx="24" cy="25" r="7"/>',
pasta:'<path class="f3" d="M7 22h34c0 10-7 18-17 18S7 32 7 22z"/><path class="s" d="M12 18c5-6 10 2 15-4s7 2 10-3M14 25c5 4 12 4 20 0"/><path class="f1" d="M20 9c2-3 5-3 8 0-3 3-5 3-8 0z"/>',
oil:'<path class="f3" d="M19 6h10v7l5 7v20H14V20l5-7z"/><path class="f2" d="M15 26h18v10H15z"/><path class="s" d="M19 10h10M15 21h18"/><path class="f1" d="M33 17c4-4 8-4 11-2-2 4-6 6-11 2z"/>',
cheese:'<path class="f3" d="M7 31 23 12l18 12v15H7z"/><path class="s" d="M7 31h34M23 12v19"/><circle class="f2" cx="28" cy="27" r="3"/><circle class="f2" cx="34" cy="34" r="2.5"/>',
cleaning:'<path class="f3" d="M12 17h19l4 6v17H9V23z"/><path class="f2" d="M18 8h12v7H18z"/><path class="s" d="M18 8h12M27 15l7 4M14 28c5-4 11-4 16 0"/><path class="f1" d="M36 27h7v10h-7z"/>',
chilled:'<path class="f3" d="M11 17h26v20H11z"/><path class="f2" d="M15 12h18v7H15z"/><path class="s" d="M11 23h26M16 31h16"/><circle class="f1" cx="36" cy="11" r="5"/>',
frozen:'<circle class="f2" cx="24" cy="24" r="17"/><path class="s" d="M24 9v30M11 16l26 16M37 16 11 32M18 11l6 6 6-6M18 37l6-6 6 6"/>',
meat:'<path class="f3" d="M8 29c0-10 8-18 19-18 7 0 13 4 13 10 0 5-4 7-8 8-4 2-4 9-11 9-7 0-13-3-13-9z"/><circle class="f2" cx="27" cy="21" r="5"/><path class="s" d="M15 31c4 2 8 2 12 0"/>',
drink:'<path class="f3" d="M10 8h13v6l4 6v20H7V20l3-6z"/><path class="f2" d="M8 25h18v11H8z"/><path class="s" d="M10 12h13M8 21h18"/><path class="f1" d="M31 18h10v20H29V24z"/><path class="s" d="M31 23h10"/>',
sweet:'<rect class="f3" x="9" y="10" width="30" height="27" rx="6"/><path class="f2" d="M14 15h8v8h-8zM26 15h8v8h-8zM14 27h8v6h-8zM26 27h8v6h-8z"/><path class="s" d="M24 10v27M9 24h30"/>',
toiletries:'<path class="f3" d="M15 15h19v25H11V21z"/><path class="f2" d="M18 7h10v8H18z"/><path class="s" d="M18 7h12v4M15 26h19"/><path class="f1" d="M32 9h8v5h-8z"/>',
icecream:'<path class="f3" d="M15 20c0-7 5-12 10-12 6 0 11 5 11 12 0 3-1 5-3 7H18c-2-2-3-4-3-7z"/><path class="f2" d="M19 27h13l-6 14z"/><path class="s" d="M20 31l9 6M29 31l-7 6"/>',
box:'<path class="f3" d="m8 17 16-9 16 9-16 9z"/><path class="f2" d="M8 17v20l16 8V26zM40 17v20l-16 8V26z"/><path class="s" d="m8 17 16 9 16-9M24 26v19"/>',
fruit:'<path class="f3" d="M12 23c0-8 5-13 12-13s12 5 12 13c0 10-6 17-12 17s-12-7-12-17z"/><path class="f1" d="M24 10c2-6 7-7 11-5-2 5-6 7-11 5z"/><path class="s" d="M24 10c0-3 1-5 3-7"/>',
carrot:'<path class="f3" d="m18 14 14 4-8 23-9-8z"/><path class="f1" d="M18 14c-5 0-8-4-8-8 5 0 8 3 8 8zM20 14c2-6 6-9 10-9 0 5-3 9-10 9z"/><path class="s" d="M19 22l8 3M17 28l8 3"/>',
mushroom:'<path class="f3" d="M8 24c1-9 8-15 16-15s15 6 16 15z"/><path class="f2" d="M18 24h12l2 15H16z"/><path class="s" d="M8 24h32"/>',
tofu:'<path class="f3" d="m10 18 14-8 14 8-14 8z"/><path class="f2" d="M10 18v16l14 7V26zM38 18v16l-14 7V26z"/><circle class="f1" cx="18" cy="20" r="2"/><circle class="f1" cx="28" cy="16" r="1.8"/><path class="s" d="m10 18 14 8 14-8"/>',
bowl:'<path class="f3" d="M7 21h34c0 12-7 18-17 18S7 33 7 21z"/><path class="f2" d="M14 18c4-7 16-7 20 0z"/><path class="s" d="M13 40h22M18 15c2-4 10-4 12 0"/>',
sausage:'<path class="f3" d="M9 28c0-6 4-11 10-11h10c6 0 10 5 10 11s-4 11-10 11H19C13 39 9 34 9 28z"/><path class="s" d="M16 19c-3-4-4-6-2-9M32 19c3-4 4-6 2-9M19 24h10"/>',
bar:'<rect class="f3" x="8" y="14" width="32" height="20" rx="5"/><path class="f2" d="M12 18h24v5H12zM12 27h17v4H12z"/><path class="s" d="M33 27l5 5"/>',
yeast:'<path class="f3" d="M10 24h28v14H10z"/><path class="f2" d="M15 12h18v12H15z"/><path class="s" d="M15 18h18M14 31h20"/><circle class="f1" cx="36" cy="11" r="4"/>',
pizza:'<path class="f3" d="m10 36 29-22-5 28z"/><path class="s" d="M14 33c7 3 14 3 21 1"/><circle class="f2" cx="27" cy="27" r="3"/><circle class="f2" cx="32" cy="20" r="2.5"/>',
fries:'<path class="f3" d="M13 18h22l-3 23H16z"/><path class="f2" d="M16 7h4v13h-4zM23 5h4v15h-4zM30 8h4v12h-4z"/><path class="s" d="M13 23h22"/>',
fish:'<path class="f3" d="M7 24c7-10 18-12 28-4l7-6v20l-7-6c-10 8-21 6-28-4z"/><circle class="f2" cx="19" cy="21" r="2"/><path class="s" d="M27 19c3 3 3 7 0 10"/>',
sauce:'<path class="f3" d="M16 7h16v8l4 7v19H12V22l4-7z"/><path class="f2" d="M13 25h22v10H13z"/><path class="s" d="M16 12h16M13 22h22"/>',
paper:'<path class="f3" d="M11 12h26v25H11z"/><path class="f2" d="M15 16h18v17H15z"/><path class="s" d="M16 20h16M16 25h12M16 30h9"/>',
eggs:'<path class="f3" d="M8 19h32v18H8z"/><ellipse class="f2" cx="16" cy="22" rx="5" ry="7"/><ellipse class="f2" cx="25" cy="22" rx="5" ry="7"/><ellipse class="f2" cx="34" cy="22" rx="5" ry="7"/><path class="s" d="M8 19h32M13 30h22"/>',
coffee:'<path class="f3" d="M10 13h24v24H10z"/><path class="f2" d="M15 18h14v9H15z"/><path class="s" d="M10 13h24M15 32h14"/><path class="f1" d="M36 20c5 1 7 4 7 7s-2 6-7 7"/>',
toothpaste:'<path class="f3" d="M11 15h25l-4 23H8z"/><path class="f2" d="M14 21h17v7H14z"/><path class="s" d="M11 15h25M15 33h13"/>',
roll:'<ellipse class="f3" cx="20" cy="24" rx="13" ry="15"/><ellipse class="f2" cx="20" cy="24" rx="5" ry="7"/><path class="f1" d="M31 17h8v21h-8z"/><path class="s" d="M31 17h8"/>',
diaper:'<path class="f3" d="M10 13h28l-3 25H13z"/><path class="f2" d="M15 20c5 4 13 4 18 0v12c-6 4-12 4-18 0z"/><path class="s" d="M10 13l7 7M38 13l-7 7"/>'
 };
Object.assign(ILLUSTRATIONS,{
produce_scene:'<path class="f3" d="M8 22h31l-4 18H12z"/><path class="s" d="M11 27h25M15 22c2-6 5-9 9-9s8 3 10 9M16 27v9M23 27v11M30 27v9"/><path class="f1" d="M12 19c1-6 5-10 10-10 0 6-4 10-10 10z"/><path class="f2" d="M26 17c3-7 8-9 13-7-2 6-7 9-13 7z"/><path class="f3" d="m33 11 4 2-7 13-5-3z"/><path class="s" d="m30 13 4 2"/>',
veg_scene:'<path class="f3" d="M8 23h31l-4 17H12z"/><path class="s" d="M12 28h23M15 28v8M22 28v10M29 28v8"/><path class="f2" d="m19 18 7-4 8 4-8 4z"/><path class="f3" d="M19 18v8l7 3v-7zM34 18v8l-8 3v-7z"/><path class="s" d="m19 18 7 4 8-4"/><path class="f1" d="M10 20c0-7 5-11 11-10-1 6-5 10-11 10zM30 16c2-7 7-10 12-8-1 6-6 10-12 8z"/><path class="s" d="M12 19c3-3 5-5 8-7M32 15c3-2 5-4 8-5"/>',
bakery_scene:'<path class="f3" d="M6 26c0-8 6-13 15-13s15 5 15 13v9H6z"/><path class="s" d="M11 23c3-4 6-5 10-3M20 18c4-3 8-2 11 1M12 29h18"/><rect class="f2" x="29" y="9" width="13" height="25" rx="3" transform="rotate(15 35.5 21.5)"/><path class="s" d="M31 14l10 3M30 20l10 3M29 27l9 3"/><circle class="f1" cx="34" cy="17" r="1.4"/><circle class="f1" cx="37" cy="24" r="1.3"/>',
baking_scene:'<path class="f3" d="M7 10h20l-2 31H9z"/><path class="f2" d="M10 16h14v16H10z"/><path class="s" d="M8 15h18M14 28c2-6 5-9 8-11M18 18v13"/><path class="f3" d="M27 27h16c0 8-4 13-8 13s-8-5-8-13z"/><path class="f2" d="M29 25c2-5 11-5 13 0z"/><path class="s" d="M28 31h14"/>',
milk_scene:'<path class="f3" d="M7 9h17l4 8v23H8V17z"/><path class="f2" d="M9 21h18v12H9z"/><path class="s" d="M7 9l6 8h15M13 9v8"/><path class="f3" d="m27 30 8-10 9 6v13H27z"/><path class="s" d="M27 30h17M35 20v10"/><circle class="f2" cx="37" cy="31" r="2.2"/>',
butter_scene:'<ellipse class="f2" cx="24" cy="37" rx="18" ry="5"/><path class="f3" d="m11 22 8-7h19l-7 15H12z"/><path class="s" d="m11 22 12 4 15-11M23 26v8M12 30h19"/><path class="f1" d="M23 18c2-3 5-4 7-2-1 3-4 4-7 2z"/>',
household_scene:'<path class="f3" d="M8 20h18l4 6v14H6V25z"/><path class="f2" d="M13 10h10v8H13z"/><path class="s" d="M13 10h13v4M22 18l8 5M10 30c5-4 11-4 16 0"/><path class="f1" d="M30 27h12v11H30z"/><path class="s" d="M32 30h8M32 34h8"/>',
drugstore_scene:'<path class="f3" d="M8 17h18v23H7V22z"/><path class="f2" d="M12 8h10v8H12z"/><path class="s" d="M12 8h13v4M12 27h11"/><path class="f1" d="M29 25h13v11H29z"/><path class="s" d="M31 28h9M31 32h7"/><circle class="f2" cx="35" cy="18" r="4"/>',
icecream_scene:'<path class="f3" d="M9 14h30l-3 27H12z"/><path class="f2" d="M11 20h26v14H11z"/><path class="s" d="M9 14c0-3 30-3 30 0M12 40h24M15 27c3-6 7-8 11-6 4 2 5 7 3 11"/><path class="f1" d="M31 21c5 0 8 3 8 7-4 1-8-1-8-7z"/><path class="s" d="M15 10l3 3M18 10l-3 3M33 9v6M30 12h6"/>',
drink_scene:'<path class="f3" d="M12 7h13v7l4 6v21H8V20l4-6z"/><path class="f2" d="M9 25h19v11H9z"/><path class="s" d="M12 11h13M9 21h19"/><circle class="f1" cx="19" cy="30" r="4"/><path class="s" d="M18 26c2-3 5-4 7-3"/><path class="f1" d="M31 26c5-5 9-5 13-2-2 5-7 7-13 2z"/>',
frozen_scene:'<path class="f3" d="M8 11h32l-3 30H11z"/><path class="f2" d="M11 20h26v14H11z"/><path class="s" d="M9 16h30M24 21v12M18 24l12 7M30 24l-12 7M21 22l3 3 3-3"/>',
tofu_plate:'<ellipse class="f2" cx="24" cy="38" rx="17" ry="4"/><path class="f3" d="m11 20 12-7 13 6-12 7z"/><path class="f2" d="M11 20v12l13 5V26zM36 19v12l-12 6V26z"/><path class="s" d="m11 20 13 6 12-7M24 26v11"/><path class="f1" d="M33 14c1-6 5-9 10-8-1 5-5 8-10 8z"/><path class="s" d="M34 13c2-2 4-4 7-5"/>',
bar_wrapped:'<path class="f2" d="m8 29 5-15 28 8-5 15z"/><path class="f3" d="m13 14 22 6-4 14-23-5z"/><path class="s" d="m13 14 22 6M10 23l23 7M16 17l-3 12M32 20l-4 14"/><circle class="f1" cx="20" cy="22" r="2"/><circle class="f1" cx="26" cy="24" r="1.7"/>',
flour_wheat:'<path class="f3" d="M10 8h27l-3 33H13z"/><path class="f2" d="M14 15h19v18H14z"/><path class="s" d="M11 14h25M20 31c1-9 5-14 10-17M25 18v13M22 21l5 2M22 25l5 2"/><path class="f1" d="M28 15c3-3 6-3 8-1-2 3-5 4-8 1z"/>',
yeast_cube:'<path class="f2" d="M9 30h30v9H9z"/><path class="f3" d="m12 18 12-7 13 6-12 8z"/><path class="f2" d="M12 18v12l13 5V25zM37 17v12l-12 6V25z"/><path class="s" d="m12 18 13 7 12-8M25 25v10"/><circle class="f1" cx="18" cy="22" r="1.5"/><circle class="f1" cx="29" cy="18" r="1.3"/>',
salt_box:'<path class="f3" d="M12 8h24l4 8-3 25H11L8 16z"/><path class="f2" d="M12 20h24v14H12z"/><path class="s" d="M8 16h32M17 13h14M17 27h14"/><circle class="f1" cx="20" cy="31" r="1.4"/><circle class="f1" cx="25" cy="29" r="1.2"/><circle class="f1" cx="30" cy="32" r="1.3"/><path class="s" d="M38 7v7M34 10h8"/>',
ice_cubes:'<path class="f2" d="M7 17h34l-3 22H10z"/><path class="s" d="M10 24h28M15 17v19M24 17v20M33 17v19"/><path class="f3" d="M12 10h10v10H12zM26 8h10v10H26z"/><path class="s" d="M12 10l5 4 5-4M26 8l5 4 5-4"/>',
potato:'<path class="f3" d="M10 28c0-11 7-18 17-18 9 0 14 7 12 16-2 10-10 15-19 13-7-1-10-5-10-11z"/><circle class="f2" cx="19" cy="21" r="2"/><circle class="f2" cx="30" cy="27" r="1.8"/><circle class="f2" cx="22" cy="33" r="1.5"/><path class="s" d="M14 28c3 6 9 8 16 7"/>',
sugar_bag:'<path class="f3" d="M11 8h26l-3 33H14z"/><path class="f2" d="M15 17h18v16H15z"/><path class="s" d="M12 14h24M19 29h10"/><path class="s" d="M24 20v8M20 24h8M21 21l6 6M27 21l-6 6"/>',
milk_glass:'<path class="f3" d="M13 9h22l-3 32H16z"/><path class="f2" d="M16 20h16l-1 17H17z"/><path class="s" d="M13 9h22M15 16h19"/>',
butter_product:'<ellipse class="f2" cx="24" cy="38" rx="17" ry="4"/><path class="f3" d="m10 24 9-8h20l-8 15H11z"/><path class="s" d="m10 24 12 4 17-12M22 28v6"/><path class="f1" d="M29 20c2-3 5-4 7-2-1 3-4 4-7 2z"/>'
});
function keyText(value){return String(value||'').toLowerCase().normalize('NFKD').replace(/[\u0300-\u036f]/g,'').replace(/ß/g,'ss').replace(/[^a-z0-9]+/g,' ').trim()}
function illustration(kind,categoryId='other'){const tone=categoryTone(categoryId);const body=ILLUSTRATIONS[kind]||ILLUSTRATIONS.box;return '<svg class="mini-svg" viewBox="0 0 48 48" aria-hidden="true" style="--i1:'+tone[0]+';--i2:'+tone[1]+'">'+body+'</svg>'}
function iconSvg(key){const map={sweet:'sweet',generic:'basket',fruit:'fruit',bread:'bread',flour:'flourbag',milk:'milk',cheese:'cheese',can:'can',oil:'oil',meat:'meat',fish:'fish',frozen:'frozen',drink:'drink',hygiene:'toiletries',household:'cleaning',ice:'icecream',tofu:'tofu',egg:'eggs',bowl:'bowl'};return illustration(map[key]||'basket','other')}
function categoryIcon(c){const map={produce_scene:'produce_scene',veg_scene:'veg_scene',bakery_scene:'bakery_scene',baking_scene:'baking_scene',milk_scene:'milk_scene',canned_scene:'can',pasta_scene:'pasta',sauce_scene:'oil',cheese_scene:'cheese',household_scene:'household_scene',pantry_milk_scene:'milk_scene',chilled_scene:'butter_scene',frozen_scene:'frozen_scene',meat_scene:'meat',drink_scene:'drink_scene',sweet_scene:'sweet',drugstore_scene:'drugstore_scene',icecream_scene:'icecream_scene',yogurt_scene:'bowl',counter_scene:'meat',stationery_scene:'paper',kids_snack_scene:'bar_wrapped',cleaner_scene:'household_scene',paper_scene:'roll',bodycare_scene:'drugstore_scene',box_scene:'box'};const kind=map[c?.visualKind]||CATEGORY_KIND[c?.id]||'box';return illustration(kind,c?.id||'other')}
function productKind(e){const k=keyText(e?.productKey||e?.productName||e?.name||'');const rules=[
[["spulmaschinensalz","spuelmaschinensalz"],'salt_box'],[["eiswurfel","eiswuerfel"],'ice_cubes'],[["tofu"],'tofu_plate'],[["musliriegel","muesliriegel","proteinriegel","riegel"],'bar_wrapped'],[["hefe"],'yeast_cube'],[["zucker","puderzucker","vanillezucker"],'sugar_bag'],[["mehl","backpulver","speisestarke","kakao"],'flour_wheat'],[["kartoffel"],'potato'],[["milch","kondensmilch","kaffeesahne","sahne"],'milk_glass'],[["butter"],'butter_product'],
[["hummus","quark","joghurt","jogurt","skyr","creme fraiche","frischkase","frischkaese"],'bowl'],[["vegetarische bratwurst","vegane bratwurst","wurstchen","wuerstchen","bratwurst"],'sausage'],[["schnitzel","steak","salami","aufschnitt","schinken","bacon","hack"],'meat'],[["falafel","linsen","bohnen","erbsen"],'bowl'],
[["toast","brot","brotchen","broetchen","baguette","croissant"],'bread'],[["eier"," ei ",'ei'],'eggs'],[["dosentomaten","tomatenmark","mais","thunfisch","ravioli"],'can'],[["ketchup","mayonnaise","mayo","senf","pesto","olivenol","olivenoel","essig","sojasauce"],'sauce'],[["gouda","mozzarella","parmesan","feta","kase","kaese"],'cheese'],
[["mullbeutel","muellbeutel","alufolie","frischhaltefolie","backpapier","kuchenrolle","kuechenrolle","taschentucher","taschentuecher"],'paper'],[["spulschwamm","spuelschwamm","allzweckreiniger","spulmittel","spuelmittel","waschmittel"],'household_scene'],[["gnocchi","tortellini","maultaschen"],'pasta'],[["pizza"],'pizza'],[["pommes"],'fries'],[["fischstabchen","fischstaebchen"],'fish'],[["tk gemuse","tiefkuhlgemuse","spinat"],'frozen_scene'],[["hackfleisch","fleisch","hahnchen","haehnchen","huhnchen","huehnchen"],'meat'],
[["wasser","saft","cola","limonade","limo","bier","wein","energy"],'drink_scene'],[["tee","kaffee"],'coffee'],[["nutella","schokolade","gummibarchen","gummibaerchen","bonbons","kekse","chips"],'sweet'],[["shampoo","duschgel","deo","mundspulung","mundspuelung"],'drugstore_scene'],[["zahnpasta"],'toothpaste'],[["zahnburste","zahnbuerste","rasierer"],'drugstore_scene'],[["toilettenpapier"],'roll'],[["windeln"],'diaper'],[["tampons"],'drugstore_scene'],[["eiscreme","magnum","sorbet"],'icecream_scene'],
[["apfel","birne","orange","zitrone","erdbeere","erdbeeren","traube","trauben","kirsche","kirschen","avocado","banane"],'fruit'],[["mohre","mohren","moehre","moehren","karotte","karotten"],'carrot'],[["champignon"],'mushroom'],[["paprika","zucchini","brokkoli","salat","zwiebel","knoblauch","gurke"],'produce_scene']];
for(const [terms,kind] of rules)if(terms.some(term=>k.includes(term.trim())))return kind;return CATEGORY_KIND[e?.categoryId]||'box'}
function xmlEsc(v){return String(v??'').replace(/[&<>\"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','\"':'&quot;',"'":'&apos;'}[c]))}
function visualBaseMarkup(base){const map={
loose:'<ellipse class="vb2" cx="32" cy="53" rx="19" ry="4"/>',
carton:'<path class="vb" d="M18 10h20l7 9v35H18z"/><path class="vb2" d="M18 10h20l7 9H25z"/><path class="vms" d="M25 19v35M38 10v9"/>',
can:'<ellipse class="vb2" cx="32" cy="15" rx="15" ry="5"/><path class="vb" d="M17 15v34c0 5 30 5 30 0V15"/><ellipse class="vms" cx="32" cy="15" rx="15" ry="5"/><path class="vms" d="M17 48c0 5 30 5 30 0"/>',
bottle:'<path class="vb" d="M26 7h12v9l6 7v31H20V23l6-7z"/><path class="vb2" d="M25 8h14v6H25z"/>',
squeeze:'<path class="vb" d="M23 10h18l-2 8 5 6-5 31H19l-3-31 6-6z"/><path class="vb2" d="M24 7h16v6H24z"/>',
jar:'<path class="vb2" d="M18 11h28v8H18z"/><path class="vb" d="M20 19h24l2 33H18z"/>',
bag:'<path class="vb" d="M16 10h32l-4 45H20z"/><path class="vb2" d="M16 10h32v8H16z"/>',
frozen_bag:'<path class="vb" d="M15 9h34l-4 46H19z"/><path class="vb2" d="M15 9h34v9H15z"/><path class="vms" d="M42 12v7M38.5 15.5h7"/>',
cup:'<path class="vb2" d="M18 16h28v7H18z"/><path class="vb" d="M20 23h24l-3 30H23z"/>',
pouch:'<path class="vb" d="M16 12h32l-3 42H19z"/><path class="vms" d="M18 18h28"/>',
tray:'<rect class="vb" x="12" y="18" width="40" height="31" rx="7"/><path class="vb2" d="M16 23h32v20H16z"/>',
box:'<rect class="vb" x="14" y="12" width="36" height="42" rx="3"/><path class="vb2" d="M14 12h36v10H14z"/>',
tube:'<path class="vb" d="M23 9h18l5 43H18z"/><path class="vb2" d="M22 7h20v7H22z"/>',
roll:'<ellipse class="vb" cx="28" cy="33" rx="16" ry="20"/><ellipse class="vb2" cx="28" cy="33" rx="6" ry="8"/><path class="vb" d="M41 18h10v34H41z"/>',
bar:'<path class="vb" d="M11 23l8-12 35 13-8 27-36-13z"/><path class="vb2" d="M17 15l32 12-3 8-33-12z"/>',
paper:'<path class="vb" d="M18 8h30v47H18z"/><path class="vms" d="M24 19h18M24 26h15M24 33h17"/>',
bundle:'<path class="vb2" d="M18 20c6-8 22-8 28 0v30H18z"/><path class="vms" d="M18 28h28"/>'};return map[base]||map.loose}
function visualMotifMarkup(id){const map={
generic:'<circle class="vm1" cx="32" cy="33" r="7"/><path class="vms" d="M28 33h8M32 29v8"/>',
apple:'<circle class="vm1" cx="31" cy="34" r="9"/><path class="vm2" d="M31 23c2-5 5-7 9-6-1 4-4 7-9 6z"/><path class="vms" d="M32 25v-5"/>',
banana:'<path class="vm2" d="M22 26c5 15 18 18 27 8-8 4-16-1-19-11z"/><path class="vms" d="M24 25c4 12 14 15 22 10"/>',
berries:'<circle class="vm1" cx="25" cy="34" r="5"/><circle class="vm1" cx="33" cy="29" r="5"/><circle class="vm1" cx="39" cy="36" r="5"/><circle class="vm1" cx="31" cy="40" r="5"/><path class="vm2" d="M30 24c4-5 8-5 11-3-2 4-6 6-11 3z"/>',
citrus:'<circle class="vm2" cx="32" cy="34" r="9"/><path class="vms" d="M32 25v18M23 34h18M26 28l12 12M38 28L26 40"/>',
grape:'<circle class="vm1" cx="28" cy="28" r="4"/><circle class="vm1" cx="35" cy="30" r="4"/><circle class="vm1" cx="25" cy="35" r="4"/><circle class="vm1" cx="32" cy="37" r="4"/><circle class="vm1" cx="39" cy="36" r="4"/><path class="vm2" d="M30 22c3-4 7-5 10-3-2 4-5 5-10 3z"/>',
pear:'<path class="vm1" d="M32 22c6 4 9 10 8 16-1 7-5 10-9 10s-9-3-10-10c-1-6 3-12 8-16z"/><path class="vm2" d="M31 20c3-4 7-5 10-2-2 4-6 5-10 2z"/>',
fruit:'<path class="vm2" d="M23 38c0-9 6-15 14-15 7 0 12 5 12 12 0 8-6 13-14 13-7 0-12-4-12-10z"/><path class="vm1" d="M33 23c3-5 7-7 12-4-2 5-6 7-12 4z"/><path class="vms" d="M34 24v-5"/>',
tomato:'<circle class="vm1" cx="32" cy="35" r="10"/><path class="vm2" d="m32 23 3 5 6-2-4 5 4 4-6-1-3 5-2-5-6 1 4-4-4-5 6 2z"/>',
carrot:'<path class="vm2" d="M28 26h10l-4 21h-8z"/><path class="vm1" d="M31 26c-6-5-6-10-4-13 5 2 7 6 4 13zM35 26c1-7 5-10 9-9 0 5-3 8-9 9z"/>',
potato:'<path class="vm2" d="M22 36c0-9 6-15 14-15 8 0 12 6 10 13-2 8-8 12-16 11-5-1-8-4-8-9z"/><circle class="vms" cx="31" cy="30" r="1.3"/><circle class="vms" cx="39" cy="37" r="1.2"/>',
cucumber:'<path class="vm1" d="M19 34c5-8 18-12 27-8 5 2 4 9-1 12-9 5-22 5-26-4z"/><path class="vms" d="M25 32c5 1 10 0 15-2"/>',
pepper:'<path class="vm1" d="M25 28c0-6 4-9 8-8 4-2 9 1 9 7 5 5 2 16-9 18-11-1-14-11-8-17z"/><path class="vms" d="M33 21c0-5 2-7 5-8"/>',
broccoli:'<circle class="vm1" cx="25" cy="28" r="6"/><circle class="vm1" cx="34" cy="25" r="7"/><circle class="vm1" cx="41" cy="30" r="6"/><path class="vm2" d="M31 31h7l3 15H27z"/>',
cauliflower:'<circle class="vm2" cx="25" cy="29" r="6"/><circle class="vm2" cx="34" cy="25" r="7"/><circle class="vm2" cx="41" cy="31" r="6"/><path class="vm1" d="M25 38c5-7 12-7 18 0-4 6-14 8-18 0z"/>',
leaf:'<path class="vm1" d="M21 43c3-15 13-23 26-23-1 14-10 24-26 23z"/><path class="vms" d="M24 40c7-7 12-12 20-17"/>',
onion:'<path class="vm2" d="M32 20c8 7 11 13 9 20-2 6-6 9-10 9-5 0-10-3-11-10-1-7 4-13 12-19z"/><path class="vms" d="M32 20c0-5 2-8 5-10M29 22c-3-5-2-8 0-11"/>',
garlic:'<path class="vm2" d="M32 22c8 3 12 9 10 17-2 7-7 10-12 9-6-1-10-5-9-12 0-7 4-11 11-14z"/><path class="vms" d="M32 22c-1-5 1-9 4-12M27 27c4 5 4 12 2 18M36 26c-3 6-2 13 0 17"/>',
mushroom:'<path class="vm1" d="M20 33c1-9 7-14 14-14 8 0 13 6 14 14z"/><path class="vm2" d="M29 33h10l2 14H27z"/>',
corn:'<ellipse class="vm2" cx="33" cy="34" rx="7" ry="13"/><path class="vms" d="M29 24l8 20M37 24l-8 20M26 31h14M26 37h14"/><path class="vm1" d="M24 43c1-9 4-14 8-18-1 9-2 15-8 18z"/>',
oat:'<path class="vms" d="M30 45c2-12 3-21 3-30"/><ellipse class="vm2" cx="27" cy="24" rx="3" ry="5" transform="rotate(-28 27 24)"/><ellipse class="vm2" cx="39" cy="20" rx="3" ry="5" transform="rotate(28 39 20)"/><ellipse class="vm2" cx="27" cy="33" rx="3" ry="5" transform="rotate(-30 27 33)"/><ellipse class="vm2" cx="39" cy="30" rx="3" ry="5" transform="rotate(30 39 30)"/>',
wheat:'<path class="vms" d="M32 47V18"/><ellipse class="vm2" cx="27" cy="25" rx="3" ry="5" transform="rotate(-30 27 25)"/><ellipse class="vm2" cx="37" cy="23" rx="3" ry="5" transform="rotate(30 37 23)"/><ellipse class="vm2" cx="27" cy="34" rx="3" ry="5" transform="rotate(-30 27 34)"/><ellipse class="vm2" cx="37" cy="32" rx="3" ry="5" transform="rotate(30 37 32)"/>',
rice:'<path class="vm2" d="M21 39c4-12 18-16 23-4-4 10-18 15-23 4z"/><path class="vms" d="M26 39c3-5 7-8 12-9M30 43c4-4 8-6 12-6"/>',
pasta:'<path class="vms" d="M23 25c7 6 11 0 18 6M22 31c7 6 12 1 19 7M24 37c6 4 11 1 16 5"/><path class="vm2" d="M21 22h22v23H21z" opacity=".16"/>',
bread:'<path class="vm2" d="M20 34c0-8 5-13 13-13s13 5 13 13v11H20z"/><path class="vms" d="M25 31c3-4 6-5 9-3M33 26c4-2 7-1 9 2"/>',
baking:'<path class="vm2" d="M22 29h20c0 10-4 16-10 16s-10-6-10-16z"/><path class="vms" d="M24 26c3-7 14-7 17 0M32 15v10M28 18h8"/>',
sugar:'<path class="vm2" d="M25 29h15l5 14H20z"/><path class="vms" d="M32 23v16M26 31h12"/>',
milk:'<path class="vm1" d="M32 20c7 9 10 14 9 19-1 5-4 8-9 8s-8-3-9-8c-1-5 2-10 9-19z"/>',
yogurt:'<path class="vm2" d="M23 28h19l-2 17H25z"/><path class="vms" d="M22 28h21M27 35h11"/>',
butter:'<path class="vm2" d="m22 32 9-7h15l-7 15H23z"/><path class="vms" d="m22 32 11 4 13-11"/>',
cheese:'<path class="vm2" d="m22 40 21-19 4 22H22z"/><circle class="vms" cx="36" cy="35" r="2"/><circle class="vms" cx="42" cy="29" r="1.5"/>',
egg:'<ellipse class="vm2" cx="32" cy="35" rx="9" ry="13"/><circle class="vm1" cx="32" cy="36" r="4"/>',
meat:'<path class="vm1" d="M22 33c5-11 17-15 24-7 7 8 0 20-11 21-10 1-17-5-13-14z"/><circle class="vm2" cx="39" cy="31" r="3"/>',
chicken:'<path class="vm1" d="M25 27c6-7 15-7 20-2 5 6 2 14-5 18-7 4-14 2-17-4-2-4-1-8 2-12z"/><path class="vm2" d="M23 39l-6 7M19 42l-4-2M20 43l2 4"/>',
sausage:'<path class="vm1" d="M22 36c0-6 4-10 9-10h5c5 0 9 4 9 10s-4 10-9 10h-5c-5 0-9-4-9-10z"/><path class="vms" d="M24 29c-3-3-4-6-2-9M43 29c3-3 4-6 2-9"/>',
fish:'<path class="vm1" d="M20 34c7-9 16-10 24-4l6-5v18l-6-5c-8 6-17 5-24-4z"/><circle class="vm2" cx="29" cy="32" r="1.6"/>',
veggie:'<path class="vm1" d="M21 44c3-14 12-22 25-23-1 13-9 23-25 23z"/><path class="vms" d="M24 41c6-7 12-12 19-17"/><circle class="vm2" cx="23" cy="27" r="4"/>',
tofu:'<path class="vm2" d="m21 30 11-6 12 6-12 7z"/><path class="vm1" d="M21 30v12l11 5V37zM44 30v12l-12 5V37z"/><path class="vms" d="m21 30 11 7 12-7"/>',
beans:'<ellipse class="vm1" cx="27" cy="32" rx="5" ry="7" transform="rotate(-25 27 32)"/><ellipse class="vm1" cx="38" cy="36" rx="5" ry="7" transform="rotate(25 38 36)"/><path class="vms" d="M25 32c2 2 4 2 6 0M36 36c2 2 4 2 6 0"/>',
water:'<path class="vm1" d="M32 20c7 9 10 14 9 19-1 5-4 8-9 8s-8-3-9-8c-1-5 2-10 9-19z"/><path class="vms" d="M28 40c2 2 5 3 8 1"/>',
juice:'<circle class="vm2" cx="31" cy="35" r="8"/><path class="vm1" d="M32 25c3-5 7-6 10-4-2 4-5 6-10 4z"/>',
cola:'<circle class="vm1" cx="28" cy="36" r="4"/><circle class="vm1" cx="37" cy="30" r="3"/><circle class="vm2" cx="40" cy="40" r="2.5"/><path class="vms" d="M24 44h19"/>',
coffee:'<ellipse class="vm1" cx="32" cy="34" rx="8" ry="12" transform="rotate(25 32 34)"/><path class="vms" d="M28 24c6 5 7 14 3 21"/>',
tea:'<path class="vm1" d="M22 42c4-13 12-20 24-20-2 12-10 20-24 20z"/><path class="vms" d="M25 39c5-5 10-10 18-14"/>',
energy:'<path class="vm2" d="M35 18 24 35h9l-4 14 12-19h-9z"/>',
sauce:'<path class="vm1" d="M32 22c6 8 9 13 8 18-1 5-4 7-8 7s-7-2-8-7c-1-5 2-10 8-18z"/>',
oil:'<path class="vm2" d="M32 20c7 9 10 14 9 19-1 5-4 8-9 8s-8-3-9-8c-1-5 2-10 9-19z"/>',
spread:'<path class="vm1" d="M23 37c5-9 14-13 21-8 6 5 2 13-5 16-8 4-17 1-16-8z"/><path class="vms" d="M27 38c5-3 9-4 14-4"/>',
sweet:'<path class="vm2" d="m23 31 6-6h8l6 6-6 10h-8z"/><path class="vms" d="m23 31-6-4M43 31l5-4M23 37l-6 4M43 37l5 4"/>',
chocolate:'<rect class="vm1" x="23" y="24" width="20" height="22" rx="2"/><path class="vms" d="M30 24v22M37 24v22M23 31h20M23 38h20"/>',
cookie:'<circle class="vm2" cx="32" cy="35" r="11"/><circle class="vm1" cx="28" cy="31" r="1.7"/><circle class="vm1" cx="37" cy="34" r="1.7"/><circle class="vm1" cx="31" cy="40" r="1.7"/>',
chips:'<path class="vm2" d="M22 25c8-5 18-3 23 4-3 9-12 15-22 10-4-4-4-9-1-14z"/><path class="vms" d="M26 29c5 1 9 4 13 8"/>',
icecream:'<path class="vm2" d="M26 34h13l-6 17z"/><circle class="vm1" cx="32" cy="29" r="8"/><circle class="vm1" cx="27" cy="31" r="5"/><circle class="vm1" cx="38" cy="32" r="5"/>',
icecube:'<path class="vm1" d="m23 29 9-6 9 6-9 7z"/><path class="vm2" d="M23 29v12l9 6V36zM41 29v12l-9 6V36z"/><path class="vms" d="m23 29 9 7 9-7"/>',
cleaner:'<path class="vm1" d="M25 35c4-8 11-12 19-10-2 8-8 13-19 10z"/><path class="vms" d="M39 20v7M35.5 23.5h7M23 24l3 3M26 24l-3 3"/>',
dish:'<circle class="vms" cx="32" cy="37" r="9"/><path class="vms" d="M23 37h18"/><circle class="vm1" cx="42" cy="24" r="3"/><circle class="vm2" cx="37" cy="20" r="2"/>',
laundry:'<path class="vm1" d="m23 25 6-5 6 4 7 3-3 7-4-2v14H22V32l-4 2-3-7z"/><path class="vms" d="M28 21c1 3 6 3 7 0"/>',
paper:'<ellipse class="vm2" cx="29" cy="35" rx="9" ry="12"/><ellipse class="vms" cx="29" cy="35" rx="3.5" ry="5"/><path class="vm1" d="M37 27h8v18h-8z"/>',
trash:'<path class="vm1" d="M23 25h19l3 22H20z"/><path class="vms" d="M26 25c1-5 4-7 7-7s6 2 7 7M25 34h15"/>',
hair:'<path class="vms" d="M22 27c5 1 5 8 10 8s5-8 10-8M22 35c5 1 5 8 10 8s5-8 10-8"/><path class="vm1" d="M25 22c4-5 10-6 15-3-4 4-9 5-15 3z"/>',
bodycare:'<path class="vm1" d="M32 21c7 9 10 14 9 19-1 5-4 8-9 8s-8-3-9-8c-1-5 2-10 9-19z"/><path class="vms" d="M27 40c3 2 7 2 10 0"/>',
tooth:'<path class="vm2" d="M24 25c2-5 7-6 9-3 3-3 8-1 9 4 1 5-2 9-4 14-1 5-2 8-5 8s-3-4-4-8c-2-5-7-9-5-15z"/>',
baby:'<circle class="vm2" cx="32" cy="34" r="10"/><path class="vms" d="M28 32h1M35 32h1M28 38c3 2 6 2 9 0M32 24c-1-4 1-7 4-8"/>',
hygiene:'<path class="vm1" d="M32 20c6 8 9 13 8 18-1 5-4 8-8 8s-7-3-8-8c-1-5 2-10 8-18z"/><path class="vms" d="M27 36h10"/>',
stationery:'<path class="vm2" d="m23 43 3-15 12-12 7 7-12 12z"/><path class="vms" d="m26 28 7 7M38 16l7 7"/>',
tape:'<circle class="vm2" cx="31" cy="35" r="11"/><circle class="vb" cx="31" cy="35" r="5"/><path class="vm1" d="M39 29h9v7h-9z"/>',
protein:'<circle class="vm1" cx="32" cy="34" r="11"/><text class="vlabel" x="32" y="37" style="font-size:12px;fill:#fff">P</text>',
frozen:'<path class="vms" d="M32 21v27M20 28l24 14M44 28 20 42M27 24l5 5 5-5M23 37l7 1-2 7M41 37l-7 1 2 7"/>',
snack:'<rect class="vm2" x="22" y="27" width="21" height="14" rx="4"/><path class="vms" d="M26 31h13M26 36h9"/>'};return map[id]||map.generic}
function productVisualSvg(e){const tone=categoryTone(e?.categoryId||'other');const base=e?.visualBase||'loose';const motif=e?.visualMotif||'generic';const label=String(e?.visualLabel||'').trim().toUpperCase().slice(0,18);const labelY=['loose','roll'].includes(base)?55:52;return '<svg class="product-visual-svg" viewBox="0 0 64 64" aria-hidden="true" style="--pv1:'+tone[0]+';--pv2:'+tone[1]+'">'+visualBaseMarkup(base)+'<g>'+visualMotifMarkup(motif)+'</g>'+(label?'<text class="vlabel" x="32" y="'+labelY+'">'+xmlEsc(label)+'</text>':'')+'</svg>'}
function productIcon(e){if(e?.visualBase||e?.visualMotif)return productVisualSvg(e);return illustration(productKind(e),e?.categoryId||'other')}
/* 0.3.20 – farbige Mini-Produktillustrationen */
function visualNameV2(e){return keyText(e?.productName||e?.name||e?.productKey||e?.key||'')}
function visualPaletteV2(motif,categoryId,key){
  if(key.includes('saure sahne'))return ['#3fa36b','#eaf8ef'];
  if(key.includes('schmand'))return ['#287ec2','#eaf4fc'];
  if(key.includes('toastkase')||key.includes('toastkaese'))return ['#f1b735','#fff1b5'];
  const map={
    apple:['#d9352c','#85a53d'],banana:['#f2c331','#7f9b35'],berries:['#3158a8','#6e8ed0'],citrus:['#ef9b2d','#f8cb58'],grape:['#7651a5','#8eb04c'],pear:['#a9bc45','#d8dc73'],fruit:['#e7753f','#6da85a'],
    tomato:['#e34b3d','#55a24b'],carrot:['#ef8a2d','#67a84b'],potato:['#c48b55','#ecd2a0'],cucumber:['#2d9147','#83c65d'],pepper:['#e04c43','#65a64b'],broccoli:['#3d9651','#74b65d'],cauliflower:['#efe4c6','#6fa55a'],leaf:['#4f9d4e','#83c769'],onion:['#b785b7','#ded0b5'],garlic:['#e9dfca','#8eb15c'],mushroom:['#b88a64','#efe5d7'],corn:['#e9b72f','#65a34d'],
    oat:['#d6a64d','#f1d27b'],wheat:['#cf9943','#efc76d'],rice:['#f4e5c6','#caa96b'],pasta:['#dfa93a','#f4d67b'],bread:['#c47b35','#edbd72'],baking:['#c99050','#f4d59c'],sugar:['#c9b98f','#f6efe1'],
    milk:['#368cc6','#eaf6fc'],yogurt:['#548ec6','#edf6fb'],butter:['#e7ba3a','#fff0a6'],cheese:['#e8ae2f','#ffe58a'],egg:['#d9b36b','#fff3ce'],
    meat:['#b95658','#f3b4aa'],chicken:['#d59263','#f2c6a0'],sausage:['#b75d58','#e9a18b'],fish:['#4c8eb4','#9ed0dd'],veggie:['#4b9a5d','#b9dda4'],tofu:['#e7d8b2','#82ac62'],beans:['#9b6d4a','#caa279'],
    water:['#4ca6d5','#aee4f5'],juice:['#e9982c','#f5c85b'],cola:['#b33c35','#e7a058'],coffee:['#7d4a31','#c89567'],tea:['#5e9b55','#b3d17f'],energy:['#7d63b1','#ecd750'],
    sauce:['#d95443','#f0a041'],oil:['#8c9b40','#d2b84b'],spread:['#a66c3d','#d9ad67'],sweet:['#d45f8e','#f3b3cf'],chocolate:['#6e3d2b','#b66b47'],cookie:['#bb7c3d','#e5b56e'],chips:['#d59a38','#f0cf72'],icecream:['#6f8fbb','#f0b5cd'],icecube:['#5ca9cf','#d7f2fb'],
    cleaner:['#2f9bb3','#9bdce1'],dish:['#3a9cad','#9adfd5'],laundry:['#4f8eb7','#bfd6e7'],paper:['#8f9ca4','#eef1f3'],trash:['#718079','#d7dfda'],hair:['#568bb5','#aad0e7'],bodycare:['#5b8fc6','#b6d6e9'],tooth:['#50a1b8','#d8f0f2'],baby:['#6fa0c2','#efd5a7'],hygiene:['#7b79b5','#d4d2ed'],stationery:['#3b79b8','#e45c59'],tape:['#d9a83d','#efe1a4'],protein:['#d07a35','#f0c15f'],frozen:['#388dcc','#d7eef9'],snack:['#b9783c','#e8c16e'],generic:['#708879','#c8d5cc']
  };
  if(map[motif])return map[motif];
  if(categoryId==='frozen'||categoryId==='ice_cream')return ['#388dcc','#d7eef9'];
  if(categoryId==='meat')return ['#b95658','#f3b4aa'];
  if(categoryId==='drinks')return ['#4c97c5','#b8dbea'];
  if(categoryId==='drugstore'||categoryId==='household')return ['#4b99a0','#b6dcd9'];
  return ['#5f9269','#d8e8d9'];
}
function visualDefsV2(){return '<defs><linearGradient id="v2Yellow" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ffe36b"/><stop offset=".55" stop-color="#f2c52c"/><stop offset="1" stop-color="#d89b18"/></linearGradient><linearGradient id="v2Red" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#ff7667"/><stop offset=".52" stop-color="#e74538"/><stop offset="1" stop-color="#bb2927"/></linearGradient><linearGradient id="v2Green" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#76c653"/><stop offset=".52" stop-color="#2f9146"/><stop offset="1" stop-color="#176b36"/></linearGradient><linearGradient id="v2Blue" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#7898dd"/><stop offset=".55" stop-color="#365fb3"/><stop offset="1" stop-color="#203d84"/></linearGradient><linearGradient id="v2Brown" x1="0" y1="0" x2="1" y2="1"><stop stop-color="#deb179"/><stop offset=".55" stop-color="#b77a43"/><stop offset="1" stop-color="#85512f"/></linearGradient><linearGradient id="v2Cream" x1="0" y1="0" x2="0" y2="1"><stop stop-color="#fffef9"/><stop offset="1" stop-color="#eee8dc"/></linearGradient><linearGradient id="v2Silver" x1="0" y1="0" x2="1" y2="0"><stop stop-color="#dce4e7"/><stop offset=".35" stop-color="#f8fafb"/><stop offset=".68" stop-color="#bcc8cd"/><stop offset="1" stop-color="#edf2f4"/></linearGradient><filter id="v2Soft" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="2" stdDeviation="1.8" flood-color="#5a4a3a" flood-opacity=".18"/></filter></defs>'}
function shadowV2(rx=19,cy=55){return '<ellipse cx="32" cy="'+cy+'" rx="'+rx+'" ry="3.4" fill="#6a5948" opacity=".13"/>'}
function starV2(cx,cy,r,fill){return '<path d="M'+cx+' '+(cy-r)+'l1.5 '+(r*.58)+' '+(r*.58)+' 1.5-'+(r*.58)+' 1.5-1.5 '+(r*.58)+'-1.5-'+(r*.58)+'-'+(r*.58)+'-1.5 '+(r*.58)+'-1.5z" fill="'+fill+'"/>'}
function looseArtV2(motif,key){
  if(key.includes('banane')||motif==='banana')return shadowV2(18,55)+'<g filter="url(#v2Soft)" transform="rotate(-12 32 32)"><path d="M14 31c7 18 25 24 38 9-11 7-23 1-29-15-3 1-6 3-9 6z" fill="url(#v2Yellow)" stroke="#c88d17" stroke-width="1.1"/><path d="M21 27c6 12 15 17 25 15" fill="none" stroke="#fff6ae" stroke-width="2" stroke-linecap="round" opacity=".8"/><path d="M19 28l-3-3 2-4 4 3zM49 40l4 1-1 4-4-1z" fill="#795321"/></g>';
  if(key.includes('tomate')||motif==='tomato')return shadowV2(16,55)+'<g filter="url(#v2Soft)"><circle cx="32" cy="34" r="15" fill="url(#v2Red)" stroke="#bd312c" stroke-width="1.1"/><ellipse cx="27" cy="28" rx="5" ry="3" fill="#ffb0a6" opacity=".42"/><path d="M32 18l3 7 7-4-4 7 8 1-8 3 4 6-8-3-3 7-2-8-8 3 4-7-8-2 8-2-3-7 7 4z" fill="#3b9846" stroke="#25713a" stroke-width=".6"/></g>';
  if(key.includes('gurke')||motif==='cucumber')return shadowV2(18,55)+'<g filter="url(#v2Soft)" transform="rotate(-18 32 33)"><rect x="11" y="25" width="40" height="17" rx="8.5" fill="url(#v2Green)" stroke="#176a35" stroke-width="1.1"/><path d="M18 29h24" stroke="#9bd574" stroke-width="2" stroke-linecap="round" opacity=".65"/><circle cx="18" cy="35" r="1" fill="#d9efaf" opacity=".7"/><circle cx="28" cy="31" r=".9" fill="#d9efaf" opacity=".7"/><circle cx="39" cy="36" r="1" fill="#d9efaf" opacity=".7"/></g><g filter="url(#v2Soft)"><circle cx="46" cy="46" r="7" fill="#9ad96d" stroke="#3a8f47"/><circle cx="46" cy="46" r="5.2" fill="#c9eda4"/><ellipse cx="43.5" cy="44.5" rx=".7" ry="1.5" fill="#7aa457"/><ellipse cx="48.3" cy="44.8" rx=".7" ry="1.5" fill="#7aa457"/><ellipse cx="46" cy="48" rx=".7" ry="1.5" fill="#7aa457"/></g>';
  if(key.includes('ruccola')||key.includes('rucola'))return shadowV2(17,55)+'<g filter="url(#v2Soft)"><path d="M29 51c-3-14 3-26 12-34-1 7-4 11-8 13 7-2 12 0 15 3-6 3-11 4-15 3 5 4 7 9 7 14-5-2-9-5-11-9 0 4 0 7 0 10z" fill="url(#v2Green)"/><path d="M24 51c1-13-5-24-14-30 2 7 5 10 10 12-6-1-11 1-14 4 6 2 10 3 14 1-4 5-5 9-4 14 4-2 7-5 9-9" fill="#58aa46"/><path d="M33 50c1-13-2-24-8-33" fill="none" stroke="#1d6b35" stroke-width="1.4"/><path d="M22 50c-1-10-4-18-10-24" fill="none" stroke="#2b763b" stroke-width="1.2"/></g>';
  if(key.includes('kartoffel')||motif==='potato')return shadowV2(18,55)+'<g filter="url(#v2Soft)"><ellipse cx="27" cy="35" rx="15" ry="12" transform="rotate(-18 27 35)" fill="url(#v2Brown)" stroke="#9a6234" stroke-width="1"/><ellipse cx="43" cy="39" rx="10" ry="8" transform="rotate(14 43 39)" fill="#d9a76d" stroke="#a66d3d"/><circle cx="21" cy="31" r="1.2" fill="#8e5b32"/><circle cx="32" cy="39" r="1" fill="#8e5b32"/><circle cx="41" cy="36" r=".9" fill="#93613a"/><path d="M18 28c5-4 11-5 16-2" fill="none" stroke="#f2d19d" stroke-width="2" stroke-linecap="round" opacity=".55"/></g>';
  if(key.includes('heidelbeere')||key.includes('blaubeere'))return shadowV2(17,55)+'<g filter="url(#v2Soft)"><circle cx="22" cy="38" r="8" fill="url(#v2Blue)"/><circle cx="31" cy="30" r="8.5" fill="url(#v2Blue)"/><circle cx="41" cy="37" r="8.5" fill="url(#v2Blue)"/><circle cx="32" cy="43" r="8" fill="url(#v2Blue)"/>'+starV2(22,34,3,'#a8b9e5')+starV2(31,26,3,'#a8b9e5')+starV2(41,33,3,'#a8b9e5')+starV2(32,39,3,'#a8b9e5')+'<path d="M25 23c7-7 14-7 20-3-4 5-10 7-20 3z" fill="#55a34b"/></g>';
  if(key.includes('knusperbrot'))return shadowV2(17,55)+'<g filter="url(#v2Soft)"><rect x="15" y="25" width="31" height="14" rx="3" transform="rotate(-8 30 32)" fill="#c58a43" stroke="#9a622e"/><rect x="18" y="30" width="31" height="14" rx="3" transform="rotate(7 33 37)" fill="#d8a55d" stroke="#a26c35"/><g fill="#8b5d2f" opacity=".65"><circle cx="22" cy="30" r="1"/><circle cx="28" cy="34" r="1"/><circle cx="36" cy="30" r="1"/><circle cx="42" cy="35" r="1"/><circle cx="25" cy="39" r="1"/><circle cx="34" cy="40" r="1"/><circle cx="43" cy="40" r="1"/></g><path d="M21 27h20" stroke="#f3d09b" stroke-width="1.2" opacity=".7"/></g>';
  if(key.includes('musliriegel')||key.includes('muesliriegel')||key.includes('proteinriegel'))return shadowV2(17,55)+'<g filter="url(#v2Soft)" transform="rotate(8 32 34)"><rect x="13" y="27" width="38" height="15" rx="5" fill="#b9783c" stroke="#8d572f"/><g fill="#e8c16e"><circle cx="20" cy="31" r="2.2"/><circle cx="26" cy="35" r="2"/><circle cx="34" cy="31" r="2.4"/><circle cx="41" cy="35" r="2"/><circle cx="46" cy="30" r="1.8"/></g><g fill="#6f472b"><circle cx="23" cy="38" r="1.6"/><circle cx="37" cy="37" r="1.5"/></g><path d="M12 27l5-5 5 6-5 14-6-4zM52 29l4 4-5 8-5-3 1-10z" fill="#e9eef2" stroke="#b8c1c8"/></g>';
  if(key.includes('toastkase')||key.includes('toastkaese'))return shadowV2(18,55)+'<g filter="url(#v2Soft)"><rect x="12" y="16" width="40" height="34" rx="5" fill="#eef5f9" stroke="#b9c8d2"/><rect x="15" y="19" width="34" height="10" rx="3" fill="#2e8fc6"/><text x="32" y="26" text-anchor="middle" font-size="7" font-weight="800" fill="#fff">TOASTKÄSE</text><rect x="20" y="32" width="24" height="13" rx="2" fill="#f2c546" stroke="#d8a722"/><rect x="24" y="35" width="20" height="12" rx="2" fill="#ffd965" stroke="#d7aa2d"/><path d="M17 22l5-3M47 46l4-5" stroke="#fff" stroke-width="1.5" opacity=".75"/></g>';
  if(key.includes('schmand'))return shadowV2(17,55)+'<g filter="url(#v2Soft)"><ellipse cx="32" cy="19" rx="15" ry="5" fill="#2e8fc6" stroke="#2876a4"/><path d="M18 19h28l-3 33H21z" fill="url(#v2Cream)" stroke="#b4bab8"/><path d="M21 29h22v18H21z" fill="#dceffc"/><text x="32" y="39" text-anchor="middle" font-size="6.2" font-weight="900" fill="#276d9a">SCHMAND</text><path d="M28 29c0-4 8-4 8 0 4 0 5 5 1 7H27c-4-2-3-7 1-7z" fill="#fff" stroke="#d9dedc"/></g>';
  if(key.includes('saure sahne'))return shadowV2(17,55)+'<g filter="url(#v2Soft)"><ellipse cx="32" cy="19" rx="15" ry="5" fill="#43a568" stroke="#2c8050"/><path d="M18 19h28l-3 33H21z" fill="url(#v2Cream)" stroke="#b4bab8"/><path d="M21 29h22v18H21z" fill="#e6f6eb"/><text x="32" y="37" text-anchor="middle" font-size="5.3" font-weight="900" fill="#2c8050">SAURE</text><text x="32" y="43" text-anchor="middle" font-size="5.3" font-weight="900" fill="#2c8050">SAHNE</text><path d="M28 29c0-4 8-4 8 0 4 0 5 5 1 7H27c-4-2-3-7 1-7z" fill="#fff" stroke="#d9dedc"/></g>';
  if(motif==='apple')return shadowV2(15,55)+'<g filter="url(#v2Soft)"><path d="M19 36c0-10 6-17 13-17 3 0 5 2 7 2 2 0 4-2 7-2 7 0 11 7 10 16-1 12-9 18-17 18s-20-5-20-17z" fill="url(#v2Red)"/><path d="M34 20c1-7 5-10 11-9-1 6-5 10-11 9z" fill="#4a9947"/><path d="M34 21l1-8" stroke="#72512d" stroke-width="2"/></g>';
  if(motif==='carrot')return shadowV2(13,55)+'<g filter="url(#v2Soft)" transform="rotate(12 32 34)"><path d="M25 20l19 5-13 29-11-12z" fill="#ed8429" stroke="#c96520"/><path d="M28 23l10 3M26 31l9 3M24 39l7 2" stroke="#f3b15e" stroke-width="1.2"/><path d="M27 20c-8-2-12-7-11-13 7 0 12 5 11 13zM29 20c1-8 6-13 13-14 0 7-5 12-13 14z" fill="#4c9e4c"/></g>';
  if(motif==='broccoli')return shadowV2(16,55)+'<g filter="url(#v2Soft)"><circle cx="23" cy="29" r="8" fill="#3b9147"/><circle cx="33" cy="25" r="9" fill="#4aa352"/><circle cx="43" cy="30" r="8" fill="#378b45"/><path d="M28 34h10l4 18H24z" fill="#78ad5a"/><path d="M25 46c5-6 9-6 15 0" fill="none" stroke="#5c9146" stroke-width="3"/></g>';
  if(motif==='leaf')return shadowV2(15,55)+'<g filter="url(#v2Soft)"><path d="M17 48c3-18 15-29 31-30-2 17-12 29-31 30z" fill="url(#v2Green)"/><path d="M20 45c8-9 15-16 25-23" stroke="#b8df8b" stroke-width="2" fill="none"/></g>';
  if(motif==='cheese')return shadowV2(16,55)+'<g filter="url(#v2Soft)"><path d="M14 45l27-28 9 29H14z" fill="#f2c44d" stroke="#d5a333"/><circle cx="37" cy="34" r="3" fill="#d9a336"/><circle cx="44" cy="40" r="2.2" fill="#d9a336"/><circle cx="32" cy="42" r="1.8" fill="#d9a336"/><path d="M18 43l22-22" stroke="#ffe889" stroke-width="2"/></g>';
  if(motif==='bread')return shadowV2(17,55)+'<g filter="url(#v2Soft)"><path d="M13 34c0-11 8-19 20-19s19 8 19 19v17H13z" fill="url(#v2Brown)" stroke="#9a5d2e"/><path d="M19 31c4-6 8-8 13-5M31 23c5-3 10-2 14 2" fill="none" stroke="#f0c98d" stroke-width="2.2" stroke-linecap="round"/></g>';
  if(motif==='fruit')return shadowV2(16,55)+'<g filter="url(#v2Soft)"><circle cx="27" cy="37" r="12" fill="#ec9b35"/><circle cx="39" cy="34" r="10" fill="#d94e40"/><path d="M31 22c6-7 12-7 17-3-4 5-9 7-17 3z" fill="#55a34b"/></g>';
  return '';
}
function packageBaseV2(base,p1,p2,key,label){
  const l=xmlEsc(label||'');
  if(base==='carton')return '<g filter="url(#v2Soft)"><path d="M19 10h21l7 9v36H19z" fill="url(#v2Cream)" stroke="#b9b8b1"/><path d="M19 10h21l7 9H27z" fill="'+p2+'"/><path d="M27 19v36" stroke="#c3c0b7"/><rect x="22" y="28" width="22" height="18" rx="3" fill="'+p1+'" opacity=".95"/>'+(l?'<text x="33" y="39" text-anchor="middle" font-size="6.2" font-weight="900" fill="#fff">'+l+'</text>':'')+'</g>';
  if(base==='can')return '<g filter="url(#v2Soft)"><ellipse cx="32" cy="15" rx="15" ry="5" fill="url(#v2Silver)" stroke="#9ba7ac"/><path d="M17 15v34c0 6 30 6 30 0V15" fill="url(#v2Silver)" stroke="#9ba7ac"/><rect x="18.5" y="25" width="27" height="18" rx="3" fill="'+p1+'" opacity=".94"/>'+(l?'<text x="32" y="36" text-anchor="middle" font-size="5.8" font-weight="900" fill="#fff">'+l+'</text>':'')+'</g>';
  if(base==='bottle')return '<g filter="url(#v2Soft)"><path d="M26 7h12v9l6 7v30c0 4-3 6-7 6H27c-4 0-7-2-7-6V23l6-7z" fill="'+p2+'" stroke="#a6b0ae"/><rect x="25" y="7" width="14" height="8" rx="2" fill="'+p1+'"/><rect x="22" y="29" width="20" height="17" rx="5" fill="'+p1+'" opacity=".92"/>'+(l?'<text x="32" y="39" text-anchor="middle" font-size="5.5" font-weight="900" fill="#fff">'+l+'</text>':'')+'</g>';
  if(base==='squeeze')return '<g filter="url(#v2Soft)"><path d="M23 13h18l-2 7 5 6-5 30H20l-4-30 6-6z" fill="'+p1+'" stroke="#a9543e"/><rect x="24" y="7" width="16" height="8" rx="2" fill="#f4eee5" stroke="#b8b1a8"/><rect x="21" y="31" width="18" height="14" rx="5" fill="#fff" opacity=".88"/>'+(l?'<text x="30" y="39" text-anchor="middle" font-size="5.4" font-weight="900" fill="'+p1+'">'+l+'</text>':'')+'</g>';
  if(base==='jar')return '<g filter="url(#v2Soft)"><rect x="18" y="11" width="28" height="8" rx="2" fill="'+p1+'"/><path d="M20 19h24l2 34H18z" fill="rgba(255,255,255,.78)" stroke="#a8b4b2"/><rect x="20" y="28" width="24" height="16" rx="4" fill="'+p2+'"/>'+(l?'<text x="32" y="38" text-anchor="middle" font-size="5.7" font-weight="900" fill="#57483d">'+l+'</text>':'')+'</g>';
  if(base==='frozen_bag')return '<g filter="url(#v2Soft)"><path d="M15 10h34l-4 45H19z" fill="#4aa4d7" stroke="#247cae"/><path d="M15 10h34v8H15z" fill="#d7effb"/><path d="M21 25h22l-2 20H23z" fill="#eaf7fc" opacity=".93"/>'+(l?'<text x="32" y="51" text-anchor="middle" font-size="6" font-weight="900" fill="#fff">'+l+'</text>':'')+'<path d="M42 13v8M38 17h8" stroke="#fff" stroke-width="1.7" stroke-linecap="round"/></g>';
  if(base==='cup')return '<g filter="url(#v2Soft)"><ellipse cx="32" cy="20" rx="15" ry="5" fill="'+p1+'" stroke="#8ca1a6"/><path d="M18 20h28l-3 33H21z" fill="url(#v2Cream)" stroke="#b4bab8"/><path d="M21 29h22v18H21z" fill="'+p2+'" opacity=".92"/>'+(l?'<text x="32" y="40" text-anchor="middle" font-size="5.5" font-weight="900" fill="#325448">'+l+'</text>':'')+'</g>';
  if(base==='pouch')return '<g filter="url(#v2Soft)"><path d="M16 12h32l-3 42H19z" fill="rgba(255,255,255,.82)" stroke="#aab8b7"/><path d="M18 18h28" stroke="'+p1+'" stroke-width="4"/><rect x="21" y="28" width="22" height="17" rx="4" fill="'+p2+'"/>'+(l?'<text x="32" y="39" text-anchor="middle" font-size="5.5" font-weight="900" fill="#4e4d45">'+l+'</text>':'')+'</g>';
  if(base==='tray')return '<g filter="url(#v2Soft)"><rect x="11" y="17" width="42" height="33" rx="8" fill="#eef0ef" stroke="#a8b0ac"/><rect x="15" y="21" width="34" height="25" rx="5" fill="'+p2+'"/><rect x="16" y="24" width="32" height="9" rx="3" fill="#fff" opacity=".72"/>'+(l?'<text x="32" y="31" text-anchor="middle" font-size="5.4" font-weight="900" fill="#5a5149">'+l+'</text>':'')+'</g>';
  if(base==='box')return '<g filter="url(#v2Soft)"><rect x="15" y="11" width="34" height="44" rx="4" fill="'+p2+'" stroke="#a6a79f"/><rect x="15" y="11" width="34" height="10" rx="4" fill="'+p1+'"/><rect x="20" y="28" width="24" height="16" rx="4" fill="#fff" opacity=".7"/>'+(l?'<text x="32" y="38" text-anchor="middle" font-size="5.5" font-weight="900" fill="#4b514d">'+l+'</text>':'')+'</g>';
  if(base==='tube')return '<g filter="url(#v2Soft)"><path d="M23 9h18l5 43H18z" fill="'+p2+'" stroke="#aeb6b4"/><rect x="22" y="7" width="20" height="7" rx="2" fill="'+p1+'"/><rect x="23" y="28" width="18" height="15" rx="4" fill="#fff" opacity=".78"/>'+(l?'<text x="32" y="37" text-anchor="middle" font-size="5.2" font-weight="900" fill="'+p1+'">'+l+'</text>':'')+'</g>';
  if(base==='roll')return '<g filter="url(#v2Soft)"><ellipse cx="27" cy="34" rx="15" ry="20" fill="#fff" stroke="#c1c6c2"/><ellipse cx="27" cy="34" rx="5" ry="7" fill="#d9cec0"/><path d="M39 18h10v34H39z" fill="#fff7ed" stroke="#c7c0b5"/></g>';
  if(base==='bar')return looseArtV2('snack','musliriegel');
  if(base==='bag')return '<g filter="url(#v2Soft)"><path d="M16 10h32l-4 45H20z" fill="'+p2+'" stroke="#aaa393"/><path d="M16 10h32v8H16z" fill="'+p1+'"/><rect x="21" y="28" width="22" height="17" rx="4" fill="#fff" opacity=".7"/>'+(l?'<text x="32" y="38" text-anchor="middle" font-size="5.4" font-weight="900" fill="#594c3e">'+l+'</text>':'')+'</g>';
  if(base==='paper')return '<g filter="url(#v2Soft)"><path d="M18 8h30v47H18z" fill="#fffdf7" stroke="#bfc6c2"/><path d="M24 20h18M24 27h15M24 34h17" stroke="'+p1+'" stroke-width="2" stroke-linecap="round"/></g>';
  if(base==='bundle')return '<g filter="url(#v2Soft)"><path d="M18 22c5-9 23-9 28 0v29H18z" fill="'+p2+'" stroke="#87978c"/><path d="M18 31h28" stroke="'+p1+'" stroke-width="3"/></g>';
  return '<g filter="url(#v2Soft)"><rect x="15" y="13" width="34" height="40" rx="6" fill="'+p2+'" stroke="#a8afa9"/></g>';
}
function productVisualSvgV2(e){
  const key=visualNameV2(e);const base=e?.visualBase||'loose';const motif=e?.visualMotif||'generic';let label=String(e?.visualLabel||'').trim().toUpperCase().slice(0,18);
  if(!label){if(key.includes('schmand'))label='SCHMAND';else if(key.includes('saure sahne'))label='SAURE SAHNE';else if(key.includes('toastkase')||key.includes('toastkaese'))label='TOASTKÄSE';else if(key.includes('hafermilch')||key.includes('haferdrink'))label='HAFER';else if(key.includes('h milch'))label='H-MILCH';}
  const pal=visualPaletteV2(motif,e?.categoryId||'other',key);
  const special=looseArtV2(motif,key);if(special)return '<svg class="product-visual-v2" viewBox="0 0 64 64" aria-hidden="true">'+visualDefsV2()+special+'</svg>';
  const pack=packageBaseV2(base,pal[0],pal[1],key,label);const motifMarkup=visualMotifMarkup(motif);const motifScale=(base==='cup'||base==='tray')?.46:.42;const motifY=(base==='cup'||base==='tray')?10:12;return '<svg class="product-visual-v2" viewBox="0 0 64 64" aria-hidden="true" style="--pv1:'+pal[0]+';--pv2:'+pal[1]+'">'+visualDefsV2()+shadowV2(18,58)+pack+'<g class="v2-pack-motif" transform="translate('+(32-32*motifScale)+' '+motifY+') scale('+motifScale+')">'+motifMarkup+'</g></svg>';
}
function illustrationDefsV3(){return '<defs><linearGradient id="v3yellow" x1=".1" y1="0" x2=".9" y2="1"><stop stop-color="#fff28a"/><stop offset=".52" stop-color="#f7ca31"/><stop offset="1" stop-color="#df941d"/></linearGradient><linearGradient id="v3red" x1=".1" y1="0" x2=".9" y2="1"><stop stop-color="#ff9780"/><stop offset=".5" stop-color="#ef4e3e"/><stop offset="1" stop-color="#c72f35"/></linearGradient><linearGradient id="v3green" x1=".1" y1="0" x2=".9" y2="1"><stop stop-color="#96db65"/><stop offset=".52" stop-color="#3fa254"/><stop offset="1" stop-color="#20723f"/></linearGradient><linearGradient id="v3blue" x1=".1" y1="0" x2=".9" y2="1"><stop stop-color="#8faaff"/><stop offset=".52" stop-color="#466cce"/><stop offset="1" stop-color="#2a428e"/></linearGradient><linearGradient id="v3potato" x1=".1" y1="0" x2=".9" y2="1"><stop stop-color="#f0c78c"/><stop offset=".56" stop-color="#ce8d4e"/><stop offset="1" stop-color="#9b5c35"/></linearGradient><filter id="v3shadow" x="-30%" y="-25%" width="160%" height="165%"><feDropShadow dx="0" dy="2" stdDeviation="1.45" flood-color="#4c3928" flood-opacity=".22"/></filter></defs>'}
function shadowV3(){return '<ellipse cx="32" cy="56" rx="19" ry="2.7" fill="#4e3c2d" opacity=".14"/>'}
function naturalArtV3(motif,key){
  // 0.3.28: konkrete Einzelmotive für Obst/Gemüse und Backwaren statt Sammel-Silhouetten.
  if(key.includes('birne'))return '<g filter="url(#v3shadow)"><path d="M31 16c6 5 10 13 9 22-1 10-7 16-15 16S12 48 13 38c1-9 7-16 13-22z" fill="#a9bc45"/><path d="M31 16c2-6 7-8 12-6-2 5-6 8-12 6z" fill="#58a44d"/><path d="M30 18l1-7" stroke="#75502f" stroke-width="2.5" stroke-linecap="round"/></g>';
  if(key.includes('orange')||key.includes('mandarine')||key.includes('clementine'))return '<g filter="url(#v3shadow)"><circle cx="31" cy="35" r="17" fill="#ef9325"/><circle cx="26" cy="29" r="5" fill="#ffbd55" opacity=".42"/><path d="M31 18c4-6 10-7 15-4-3 5-8 7-15 4z" fill="#4f9f48"/></g>';
  if(key.includes('zitrone'))return '<g filter="url(#v3shadow)" transform="rotate(-12 32 35)"><ellipse cx="32" cy="35" rx="19" ry="12" fill="#f2d534"/><path d="M13 35l4-3v6zM51 35l-4-3v6z" fill="#d1ad1f"/><ellipse cx="26" cy="31" rx="6" ry="3" fill="#fff7a1" opacity=".45"/></g>';
  if(key.includes('limette'))return '<g filter="url(#v3shadow)"><circle cx="32" cy="35" r="16" fill="#6fb64b"/><path d="M32 19c5-5 9-6 13-3-3 4-7 6-13 3z" fill="#3c8f40"/><ellipse cx="27" cy="29" rx="5" ry="3" fill="#c9e98e" opacity=".45"/></g>';
  if(key.includes('erdbeere'))return '<g filter="url(#v3shadow)"><path d="M32 18c13 0 19 8 16 18-3 11-11 18-16 21-6-3-14-10-17-21-3-10 4-18 17-18z" fill="#e8463f"/><path d="M22 20l10 5 10-5-2 9-8-3-8 3z" fill="#489d45"/><g fill="#ffd77f"><circle cx="24" cy="33" r="1.3"/><circle cx="32" cy="36" r="1.3"/><circle cx="40" cy="32" r="1.3"/><circle cx="28" cy="44" r="1.3"/><circle cx="37" cy="45" r="1.3"/></g></g>';
  if(key.includes('himbeere'))return '<g filter="url(#v3shadow)" fill="#d92f55"><circle cx="24" cy="30" r="6"/><circle cx="32" cy="27" r="6"/><circle cx="40" cy="31" r="6"/><circle cx="21" cy="38" r="6"/><circle cx="30" cy="38" r="6"/><circle cx="39" cy="39" r="6"/><circle cx="32" cy="47" r="6"/></g>';
  if(key.includes('brombeere'))return '<g filter="url(#v3shadow)" fill="#54316f"><circle cx="24" cy="30" r="6"/><circle cx="32" cy="27" r="6"/><circle cx="40" cy="31" r="6"/><circle cx="21" cy="38" r="6"/><circle cx="30" cy="38" r="6"/><circle cx="39" cy="39" r="6"/><circle cx="32" cy="47" r="6"/></g>';
  if(key.includes('johannisbeere'))return '<g filter="url(#v3shadow)"><path d="M31 17c2 10 4 20 5 31" stroke="#4d8f44" stroke-width="2" fill="none"/><g fill="#c93442"><circle cx="26" cy="29" r="5"/><circle cx="35" cy="33" r="5"/><circle cx="28" cy="40" r="5"/><circle cx="38" cy="44" r="5"/></g></g>';
  if(key.includes('stachelbeere'))return '<g filter="url(#v3shadow)"><circle cx="24" cy="35" r="11" fill="#8fbf57"/><circle cx="40" cy="36" r="11" fill="#a8c967"/><path d="M20 26l8 18M36 27l8 18" stroke="#d9e6a3" stroke-width="1.2"/></g>';
  if(key.includes('kirsche'))return '<g filter="url(#v3shadow)"><path d="M30 19c2 8 1 14-3 20M33 19c5 6 8 12 9 20" stroke="#4d8c41" stroke-width="2.2" fill="none"/><circle cx="24" cy="43" r="10" fill="#c92e39"/><circle cx="43" cy="43" r="10" fill="#d83a42"/><path d="M31 19c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#4f9c45"/></g>';
  if(key.includes('avocado'))return '<g filter="url(#v3shadow)"><path d="M32 14c7 7 15 18 14 29-1 9-7 14-14 14s-13-5-14-14c-1-11 7-22 14-29z" fill="#4e9b4a"/><path d="M32 20c5 6 10 15 9 23-1 6-4 9-9 9s-9-3-10-9c-1-8 5-17 10-23z" fill="#c7d86c"/><circle cx="32" cy="42" r="7" fill="#86542f"/></g>';
  if(key.includes('paprika'))return '<g filter="url(#v3shadow)"><path d="M20 28c0-7 5-11 12-10 7-1 12 3 12 10 6 3 7 12 3 20-4 8-11 9-15 5-5 4-12 3-16-5-4-8-3-17 4-20z" fill="#e44b42"/><path d="M31 18c0-6 4-9 8-9 0 4-2 7-6 9z" fill="#458f42"/></g>';
  if(key.includes('zwiebel'))return '<g filter="url(#v3shadow)"><path d="M32 16c7 8 15 15 14 25-1 10-7 15-14 15s-13-5-14-15c-1-10 7-17 14-25z" fill="#c79bc6"/><path d="M32 17c-4-5-3-9 0-12 3 3 4 7 0 12z" fill="#7f9b55"/><path d="M25 50c4 4 10 4 14 0" stroke="#fff1dd" stroke-width="1.6" fill="none"/></g>';
  if(key.includes('knoblauch'))return '<g filter="url(#v3shadow)"><path d="M32 15c3 5 5 8 5 12 7 0 12 7 10 15-2 9-9 14-15 14S19 51 17 42c-2-8 3-15 10-15 0-4 2-8 5-12z" fill="#eee3cd"/><path d="M32 18v36M25 29c-2 8-1 16 3 23M39 29c2 8 1 16-3 23" stroke="#c7b99e" stroke-width="1.4" fill="none"/><path d="M32 16c-2-6 1-10 5-12" stroke="#6f9a55" stroke-width="2" fill="none"/></g>';
  if(key.includes('champignon')||key.includes('pilz'))return '<g filter="url(#v3shadow)"><path d="M15 32c2-11 9-17 17-17s15 6 17 17z" fill="#c79b79"/><path d="M27 31h10l4 22H23z" fill="#eee1cd"/><path d="M18 31h28" stroke="#a57a5d" stroke-width="1.4"/></g>';
  if(key.includes('mango'))return '<g filter="url(#v3shadow)" transform="rotate(12 32 35)"><ellipse cx="32" cy="35" rx="16" ry="20" fill="#ed9a36"/><path d="M22 24c6-6 15-7 22-3" stroke="#e65b43" stroke-width="5" opacity=".7"/><path d="M32 16c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#4a9947"/></g>';
  if(key.includes('ananas'))return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="39" rx="14" ry="18" fill="#e4b53d"/><path d="M20 31l24 16M20 47l24-16M18 39h28" stroke="#b98c2c" stroke-width="1.4"/><path d="M32 20c-7-5-8-10-6-14 5 3 7 7 6 14zm0 0c6-6 10-8 14-6-2 5-7 7-14 6zm0 0c0-8 3-13 7-15 2 6-1 11-7 15z" fill="#4c9a49"/></g>';
  if(key.includes('kiwi'))return '<g filter="url(#v3shadow)"><circle cx="32" cy="35" r="18" fill="#87613f"/><circle cx="32" cy="35" r="14" fill="#84b94d"/><circle cx="32" cy="35" r="5" fill="#e9e5a4"/><g fill="#3c3b32"><circle cx="32" cy="23" r="1.2"/><circle cx="42" cy="28" r="1.2"/><circle cx="43" cy="40" r="1.2"/><circle cx="32" cy="47" r="1.2"/><circle cx="21" cy="40" r="1.2"/><circle cx="21" cy="28" r="1.2"/></g></g>';
  if(key.includes('pfirsich'))return '<g filter="url(#v3shadow)"><circle cx="32" cy="36" r="18" fill="#ef9a67"/><path d="M33 19c-2 9-1 18 3 31" stroke="#d55d63" stroke-width="2" fill="none"/><path d="M32 18c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#4d9b49"/></g>';
  if(key.includes('nektarine'))return '<g filter="url(#v3shadow)"><circle cx="32" cy="36" r="18" fill="#e66e45"/><ellipse cx="26" cy="29" rx="6" ry="4" fill="#f4ad67" opacity=".5"/><path d="M32 18c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#4d9b49"/></g>';
  if(key.includes('pflaume'))return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="36" rx="17" ry="19" fill="#7650a0"/><path d="M32 18c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#4d9b49"/></g>';
  if(key.includes('aprikose'))return '<g filter="url(#v3shadow)"><circle cx="32" cy="36" r="18" fill="#efa04a"/><path d="M33 19c-1 9 0 18 3 31" stroke="#dc7440" stroke-width="1.8"/><path d="M32 18c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#4d9b49"/></g>';
  if(key.includes('granatapfel'))return '<g filter="url(#v3shadow)"><circle cx="32" cy="38" r="17" fill="#c9363f"/><path d="M25 20l4-7 4 6 5-6 2 9z" fill="#a52630"/><circle cx="26" cy="32" r="5" fill="#ef6d6e" opacity=".45"/></g>';
  if(key.includes('wassermelone'))return '<g filter="url(#v3shadow)"><path d="M13 45c8-20 28-25 40-9L32 55z" fill="#e84f55"/><path d="M13 45l19 10 21-19" stroke="#52a04c" stroke-width="5"/><g fill="#4d372e"><ellipse cx="29" cy="41" rx="1.2" ry="2"/><ellipse cx="38" cy="43" rx="1.2" ry="2"/><ellipse cx="44" cy="38" rx="1.2" ry="2"/></g></g>';
  if(key.includes('honigmelone'))return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="36" rx="20" ry="17" fill="#d8c86a"/><path d="M17 30c10 5 20 8 31 6M18 42c9-4 20-5 29-2M26 20c-3 10-3 21 1 32M39 20c3 10 3 21-1 32" stroke="#a9984b" stroke-width="1.2" fill="none"/></g>';
  if(key.includes('galiamelone'))return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="36" rx="20" ry="17" fill="#c7b86c"/><path d="M15 29c11 4 23 4 34 0M15 43c11-4 23-4 34 0M23 21c-2 10-2 20 0 30M41 21c2 10 2 20 0 30" stroke="#eee2aa" stroke-width="1.4" fill="none"/></g>';
  if(key.includes('traube'))return '<g filter="url(#v3shadow)"><path d="M31 18c5-5 10-5 14-2-3 4-8 6-14 2z" fill="#55a34b"/><g fill="#7651a5"><circle cx="27" cy="28" r="6"/><circle cx="37" cy="29" r="6"/><circle cx="23" cy="37" r="6"/><circle cx="33" cy="38" r="6"/><circle cx="42" cy="38" r="6"/><circle cx="29" cy="47" r="6"/><circle cx="38" cy="47" r="6"/></g></g>';
  if(key.includes('toast'))return '<g filter="url(#v3shadow)"><path d="M17 20c0-8 6-12 15-12s15 4 15 12v31H17z" fill="#d99a53"/><path d="M21 22c0-6 4-9 11-9s11 3 11 9v24H21z" fill="#f2c981"/></g>';
  if(key.includes('croissant'))return '<g filter="url(#v3shadow)"><path d="M13 41c6-18 18-25 38-17-5 2-8 6-10 11 4 2 7 5 9 9-15 7-29 5-37-3z" fill="#d98a3f"/><path d="M20 36c7-7 15-10 24-8M25 43c5-6 10-8 16-8" stroke="#f1c17a" stroke-width="2" fill="none"/></g>';
  if(key.includes('baguette')||key.includes('ciabatta'))return '<g filter="url(#v3shadow)" transform="rotate(-10 32 34)"><rect x="9" y="25" width="46" height="18" rx="9" fill="#c9823d"/><path d="M18 28l6 9M29 27l6 9M40 27l6 8" stroke="#f1c887" stroke-width="2"/></g>';
  if(key.includes('burger buns'))return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="31" rx="19" ry="11" fill="#d58a45"/><path d="M14 34h36c-2 10-8 15-18 15s-16-5-18-15z" fill="#bc7339"/><g fill="#f4d69a"><circle cx="24" cy="27" r="1.2"/><circle cx="32" cy="24" r="1.2"/><circle cx="39" cy="28" r="1.2"/></g></g>';
  if(key.includes('hotdog'))return '<g filter="url(#v3shadow)" transform="rotate(-6 32 35)"><rect x="10" y="27" width="44" height="17" rx="8" fill="#d18a48"/><path d="M16 34h32" stroke="#f4c983" stroke-width="3" stroke-linecap="round"/></g>';
  if(key.includes('laugenbrezel'))return '<g filter="url(#v3shadow)"><path d="M18 44c-8-7-6-19 3-20 8-1 11 8 11 14 0-6 3-15 11-14 9 1 11 13 3 20-6 5-12 7-14 7s-8-2-14-7z" fill="none" stroke="#9b572d" stroke-width="7" stroke-linecap="round"/><path d="M23 28l18 18M41 28L23 46" stroke="#9b572d" stroke-width="5"/></g>';
  if(key.includes('laugenstange'))return '<g filter="url(#v3shadow)" transform="rotate(-8 32 34)"><rect x="10" y="27" width="44" height="16" rx="8" fill="#9d5a30"/><path d="M20 29l5 12M32 27l5 13M43 27l5 11" stroke="#f4d6a3" stroke-width="2"/></g>';
  if(key.includes('tortilla-wrap')||key==='wraps'||key.includes(' wraps'))return '<g filter="url(#v3shadow)"><ellipse cx="30" cy="40" rx="20" ry="9" fill="#d7aa63"/><ellipse cx="34" cy="33" rx="20" ry="10" fill="#f2d79d" stroke="#c99550"/><g fill="#b78343" opacity=".65"><circle cx="24" cy="31" r="1"/><circle cx="39" cy="35" r="1.2"/></g></g>';
  if(key.includes('pita'))return '<g filter="url(#v3shadow)"><path d="M11 40c3-15 12-23 22-23 11 0 19 9 20 23-9 8-33 9-42 0z" fill="#e8bd79"/><path d="M18 35c9-5 20-6 29-1" fill="none" stroke="#b87b3b" stroke-width="2.2" stroke-linecap="round"/></g>';
  if(key.includes('naan'))return '<g filter="url(#v3shadow)"><path d="M18 51c-8-11-6-24 5-34 8-8 20-6 25 3 7 13 0 28-12 34-7 3-14 2-18-3z" fill="#efc77f"/><g fill="#ae793c"><circle cx="28" cy="28" r="1.4"/><circle cx="39" cy="35" r="1.2"/><circle cx="25" cy="43" r="1.1"/></g></g>';
  if(key.includes('fladenbrot'))return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="37" rx="22" ry="14" fill="#dca85a"/><ellipse cx="32" cy="34" rx="18" ry="10" fill="#f2d59b"/><g fill="#9c6b30"><circle cx="23" cy="32" r="1.3"/><circle cx="32" cy="39" r="1.2"/><circle cx="41" cy="31" r="1.3"/><circle cx="35" cy="29" r=".9"/></g></g>';
  if(key.includes('mehrkornbrot'))return '<g filter="url(#v3shadow)"><path d="M12 35c0-12 9-20 20-20 13 0 21 9 21 21v16H12z" fill="#9f652f"/><g fill="#e9cc84"><ellipse cx="21" cy="28" rx="2" ry="1"/><ellipse cx="31" cy="23" rx="2" ry="1"/><ellipse cx="42" cy="29" rx="2" ry="1"/><ellipse cx="27" cy="38" rx="2" ry="1"/><ellipse cx="39" cy="42" rx="2" ry="1"/></g></g>';
  if(key.includes('roggenbrot'))return '<g filter="url(#v3shadow)"><path d="M11 38c0-12 8-20 21-20 13 0 21 8 21 20v14H11z" fill="#7a4728"/><path d="M18 31c8 4 20 4 29 0" fill="none" stroke="#d9ad6b" stroke-width="2"/></g>';
  if(key.includes('dinkelbrot'))return '<g filter="url(#v3shadow)"><path d="M12 37c0-12 8-20 20-20s20 8 20 20v15H12z" fill="#b87938"/><path d="M19 29l8 5M29 25l8 5M39 28l7 4" stroke="#f0ce8b" stroke-width="2.2" stroke-linecap="round"/></g>';
  if(key.includes('eiweissbrot')||key.includes('eiweißbrot'))return '<g filter="url(#v3shadow)"><path d="M12 37c0-12 8-20 20-20s20 8 20 20v15H12z" fill="#83502c"/><g fill="#f0d38c"><circle cx="21" cy="29" r="1.3"/><circle cx="29" cy="25" r="1.2"/><circle cx="39" cy="30" r="1.3"/><circle cx="31" cy="41" r="1.2"/><circle cx="44" cy="40" r="1.1"/></g></g>';
  if(key.includes('sandwichtoast'))return '<g filter="url(#v3shadow)"><rect x="16" y="17" width="32" height="39" rx="10" fill="#be7e3e"/><rect x="20" y="21" width="24" height="31" rx="8" fill="#f3c879"/></g>';
  if(key.includes('vollkornbrot'))return '<g filter="url(#v3shadow)"><path d="M12 37c0-12 8-20 20-20s20 8 20 20v15H12z" fill="#8d552d"/><path d="M18 31c8-5 19-7 29-3" fill="none" stroke="#d2a35d" stroke-width="2"/></g>';
  if(key.includes('brotchen')||key.includes('broetchen'))return '<g filter="url(#v3shadow)"><ellipse cx="23" cy="39" rx="12" ry="10" fill="#cf8643"/><ellipse cx="41" cy="39" rx="12" ry="10" fill="#d8944d"/><path d="M17 35c4-4 8-4 12 0M35 35c4-4 8-4 12 0" stroke="#f0c98b" stroke-width="2" fill="none"/></g>';
  if(key.includes('banane')||motif==='banana')return '<g filter="url(#v3shadow)" transform="rotate(-16 32 33)"><path d="M12 29c5 20 25 28 42 11-13 6-25-1-30-16-4 2-8 3-12 5z" fill="url(#v3yellow)"/><path d="M20 28c7 13 17 18 27 15" fill="none" stroke="#fff7b5" stroke-width="2.6" stroke-linecap="round"/><path d="m18 27-4-3 2-4 5 3M51 40l4 1-2 4-4-2" fill="#72502d"/></g>';
  if(key.includes('tomate')||motif==='tomato')return '<g filter="url(#v3shadow)"><circle cx="32" cy="35" r="17" fill="url(#v3red)"/><ellipse cx="26" cy="28" rx="6" ry="3.3" class="shine"/><path d="m32 19 3 7 7-4-4 7 8 2-8 2 3 7-7-4-2 8-2-8-7 4 3-7-8-2 8-2-4-7 7 4z" fill="#3c9c4d"/><circle cx="38" cy="43" r="2" fill="#d33035" opacity=".45"/></g>';
  if(key.includes('gurke')||motif==='cucumber')return '<g filter="url(#v3shadow)" transform="rotate(-17 32 33)"><rect x="9" y="24" width="43" height="19" rx="9.5" fill="url(#v3green)"/><path d="M17 29h27" stroke="#c1ec7d" stroke-width="2.2" stroke-linecap="round" opacity=".8"/><g fill="#e4f4a9" opacity=".8"><circle cx="18" cy="36" r="1.2"/><circle cx="27" cy="31" r="1.1"/><circle cx="37" cy="36" r="1.2"/><circle cx="45" cy="31" r="1.1"/></g></g>';
  if(key.includes('ruccola')||key.includes('rucola'))return '<g filter="url(#v3shadow)"><path d="M30 54c-3-17 2-29 14-39-1 9-5 14-10 17 9-2 14 1 18 5-7 3-13 4-18 3 6 4 8 9 7 15-6-3-10-7-12-12" fill="url(#v3green)"/><path d="M27 54c1-15-5-27-16-34 3 9 8 13 13 15-8 0-12 3-15 7 7 2 12 2 16 0-4 5-5 9-4 14 3-3 6-7 7-12" fill="#69bc52"/><path d="M30 51c1-13 4-22 10-31M26 51c-2-11-6-19-12-25" fill="none" stroke="#257440" stroke-width="1.8" stroke-linecap="round"/></g>';
  if(key.includes('kartoffel')||motif==='potato')return '<g filter="url(#v3shadow)"><path d="M13 38c0-10 9-19 20-19 13 0 20 9 17 20-3 10-13 16-25 14-8-1-12-7-12-15z" fill="url(#v3potato)"/><ellipse cx="27" cy="29" rx="6" ry="3" class="shine"/><g fill="#83502e"><circle cx="21" cy="39" r="1.4"/><circle cx="34" cy="46" r="1.2"/><circle cx="42" cy="33" r="1.3"/></g><path d="M47 26c2-7 7-10 12-8-2 6-6 9-12 8z" fill="#65a94d"/></g>';
  if(key.includes('heidelbeere')||key.includes('blaubeere')||motif==='berries')return '<g filter="url(#v3shadow)"><g fill="url(#v3blue)"><circle cx="21" cy="39" r="8"/><circle cx="31" cy="30" r="9"/><circle cx="42" cy="38" r="9"/><circle cx="31" cy="47" r="8"/></g><g fill="#b9c8ff" opacity=".9"><path d="m21 33 1.3 3.1 3.2.4-2.4 2 1 3.1-3.1-1.7-3 1.7 1-3.1-2.4-2 3.2-.4z"/><path d="m31 23 1.3 3.1 3.2.4-2.4 2 1 3.1-3.1-1.7-3 1.7 1-3.1-2.4-2 3.2-.4z"/><path d="m42 31 1.3 3.1 3.2.4-2.4 2 1 3.1-3.1-1.7-3 1.7 1-3.1-2.4-2 3.2-.4z"/></g><path d="M25 23c7-7 15-7 21-2-5 5-12 6-21 2z" fill="#54a44f"/></g>';
  if(motif==='apple')return '<g filter="url(#v3shadow)"><path d="M17 37c0-11 7-19 15-19 3 0 5 2 7 2s4-2 7-2c8 0 12 8 10 18-2 11-10 18-19 18s-20-6-20-17z" fill="url(#v3red)"/><ellipse cx="26" cy="29" rx="5" ry="3" class="shine"/><path d="M36 19c2-7 7-10 13-8-2 6-7 9-13 8z" fill="#58a44d"/><path d="M36 21l1-8" stroke="#744a2d" stroke-width="2.4" stroke-linecap="round"/></g>';
  if(motif==='carrot')return '<g filter="url(#v3shadow)" transform="rotate(15 32 34)"><path d="m23 21 22 8-14 27-14-13z" fill="#f18a32"/><path d="M27 24 38 28M24 32l10 4M22 40l8 3" stroke="#ffc06d" stroke-width="1.8" stroke-linecap="round"/><path d="M27 23c-8-2-12-8-11-14 8 0 12 6 11 14zM29 23c1-8 7-13 14-14-1 8-6 13-14 14z" fill="#54a54f"/></g>';
  if(motif==='broccoli')return '<g filter="url(#v3shadow)"><g fill="#41974f"><circle cx="22" cy="30" r="9"/><circle cx="33" cy="25" r="10"/><circle cx="44" cy="31" r="9"/></g><path d="M27 34h12l4 19H23z" fill="#78af5b"/><path d="M26 48c5-6 10-6 15 0" stroke="#5e9348" stroke-width="3" fill="none"/></g>';
  if(motif==='leaf')return '<g filter="url(#v3shadow)"><path d="M14 50c3-20 16-32 36-34-2 19-14 32-36 34z" fill="url(#v3green)"/><path d="M18 47c9-11 18-18 29-27" stroke="#d3ee93" stroke-width="2.5" fill="none" stroke-linecap="round"/></g>';
  if(motif==='bread')return '<g filter="url(#v3shadow)"><path d="M11 35c0-12 9-21 21-21 13 0 21 9 21 21v17H11z" fill="#c8843e"/><path d="M18 31c5-6 9-7 14-4M31 24c6-4 11-2 15 3" fill="none" stroke="#f6d394" stroke-width="3" stroke-linecap="round"/></g>';
  return '';
}
function packageArtV3(base,p1,p2,label,motif){
  const l=xmlEsc((label||'').slice(0,18));const stripe='<path d="M19 24h26" stroke="#fff" stroke-opacity=".32" stroke-width="2"/>';const text=l?'<text x="32" y="39" text-anchor="middle" dominant-baseline="middle" textLength="22" lengthAdjust="spacingAndGlyphs" style="font-size:5.2px;font-weight:900;letter-spacing:.1px;fill:#263833">'+l+'</text>':'';
  if(base==='cup')return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="18" rx="17" ry="6" fill="'+p1+'"/><path d="M15 18h34l-4 37H19z" fill="'+p2+'"/><path d="M19 29h26v18H19z" fill="'+p1+'"/>'+stripe+text+'</g>';
  if(base==='carton')return '<g filter="url(#v3shadow)"><path d="M17 11h23l8 10v35H17z" fill="'+p2+'"/><path d="M17 11h23l8 10H28z" fill="'+p1+'"/><rect x="21" y="29" width="24" height="17" rx="3" fill="'+p1+'"/>'+text+'</g>';
  if(base==='bottle'||base==='squeeze')return '<g filter="url(#v3shadow)"><path d="M25 8h14v10l6 8v28c0 4-3 6-7 6H26c-4 0-7-2-7-6V26l6-8z" fill="'+p2+'"/><rect x="24" y="8" width="16" height="9" rx="2" fill="'+p1+'"/><rect x="22" y="32" width="20" height="15" rx="5" fill="'+p1+'"/>'+text+'</g>';
  if(base==='can')return '<g filter="url(#v3shadow)"><ellipse cx="32" cy="16" rx="16" ry="5" fill="#dbe3e6"/><path d="M16 16v34c0 7 32 7 32 0V16" fill="'+p2+'"/><rect x="17" y="27" width="30" height="19" rx="3" fill="'+p1+'"/>'+text+'</g>';
  if(base==='tray')return '<g filter="url(#v3shadow)"><rect x="9" y="19" width="46" height="32" rx="9" fill="#e8ece8"/><rect x="13" y="23" width="38" height="24" rx="6" fill="'+p2+'"/><path d="M16 27h32" stroke="#fff" stroke-width="3" opacity=".7"/>'+text+'</g>';
  if(base==='bar')return '<g filter="url(#v3shadow)" transform="rotate(6 32 34)"><path d="M10 28l6-5h32l6 6-5 16H15z" fill="'+p1+'"/><path d="M16 28h32v14H16z" fill="'+p2+'"/><path d="M10 28l6 4v12l-6-4zM54 29l-6 4v12l6-5z" fill="#f7f2e9"/>'+text+'</g>';
  if(base==='bag'||base==='frozen_bag'||base==='pouch')return '<g filter="url(#v3shadow)"><path d="M14 10h36l-4 47H18z" fill="'+p2+'"/><path d="M14 10h36v9H14z" fill="'+p1+'"/><rect x="19" y="29" width="26" height="18" rx="4" fill="'+p1+'"/>'+text+'</g>';
  if(base==='box'||base==='tube'||base==='jar')return '<g filter="url(#v3shadow)"><rect x="15" y="10" width="34" height="46" rx="5" fill="'+p2+'"/><path d="M15 10h34v11H15z" fill="'+p1+'"/><rect x="20" y="29" width="24" height="17" rx="4" fill="'+p1+'"/>'+text+'</g>';
  return '<g filter="url(#v3shadow)"><rect x="14" y="12" width="36" height="43" rx="7" fill="'+p2+'"/><rect x="19" y="29" width="26" height="17" rx="4" fill="'+p1+'"/>'+text+'</g>';
}
function compactCaptionV3(label){const l=xmlEsc(String(label||'').slice(0,18));if(!l)return '';return '<g><rect x="11" y="48" width="42" height="10" rx="5" fill="rgba(255,255,255,.94)"/><text x="32" y="53" text-anchor="middle" dominant-baseline="middle" textLength="31" lengthAdjust="spacingAndGlyphs" style="font-size:4.8px;font-weight:900;fill:#34413d">'+l+'</text></g>'}
function specialProductArtV3(base,motif,key,label,pal){
  const cap=compactCaptionV3(label);
  if(base==='tray' && (motif==='cheese'||key.includes('kase')||key.includes('kaese')||key.includes('gouda')||key.includes('parmesan')||key.includes('feta')||key.includes('brie')||key.includes('camembert')||key.includes('mozzarella'))){
    let food='';
    if(key.includes('camembert')||key.includes('brie'))food='<ellipse cx="31" cy="33" rx="15" ry="11" fill="#f4e7c8" stroke="#d6c29a"/><path d="M31 22v22l15-8c-2-8-7-13-15-14z" fill="#fff2cf" stroke="#d6c29a"/>';
    else if(key.includes('feta')||key.includes('hirten'))food='<g fill="#f8f4e8" stroke="#d8d2c1"><rect x="17" y="27" width="13" height="12" rx="2"/><rect x="31" y="24" width="14" height="13" rx="2"/><rect x="26" y="37" width="14" height="10" rx="2"/></g>';
    else if(key.includes('mozzarella'))food='<g fill="#fffdf5" stroke="#d8ddd4"><circle cx="25" cy="34" r="9"/><circle cx="39" cy="32" r="10"/></g><path d="M18 25c7-7 14-7 19-4" fill="none" stroke="#5b9b50" stroke-width="2"/>';
    else if(key.includes('parmesan')||key.includes('grana'))food='<path d="M16 43 42 19l8 27H16z" fill="#e9c56f" stroke="#c99b48"/><g fill="#c8994b"><circle cx="38" cy="34" r="1.8"/><circle cx="44" cy="40" r="1.4"/></g>';
    else if(key.includes('emmentaler'))food='<path d="M15 43 42 19l8 27H15z" fill="#f2c54e" stroke="#d2a131"/><g fill="#d39e2f"><circle cx="37" cy="32" r="3"/><circle cx="44" cy="40" r="2.2"/><circle cx="30" cy="42" r="1.8"/></g>';
    else if(key.includes('gouda'))food='<path d="M15 43 40 21l10 25H15z" fill="#f0c44d" stroke="#d09a30"/><path d="M40 21 50 46h-5l-9-21z" fill="#e18a34"/>';
    else food='<path d="M15 43 41 20l9 27H15z" fill="#f1c34c" stroke="#d19f32"/>';
    return '<g filter="url(#v3shadow)"><rect x="8" y="15" width="48" height="38" rx="9" fill="#eef2ef" stroke="#c7d0cc"/><rect x="12" y="19" width="40" height="30" rx="7" fill="#fffdf6" opacity=".86"/>'+food+'</g>'+cap;
  }
  if(base==='tray' && ['meat','chicken','sausage','veggie','tofu'].includes(motif)){
    let food='';
    if(/rohschinken|rohen schinken|serrano|parma|prosciutto/.test(key))food='<g fill="#a84643" opacity=".95"><path d="M15 27c9-7 22-6 31 0-8 5-18 6-31 0z"/><path d="M17 35c10-6 21-5 30 1-9 6-21 6-30-1z"/><path d="M20 43c9-5 18-4 25 1-8 4-16 5-25-1z"/></g><path d="M18 30c8 2 18 2 27-1" stroke="#e7a09b" stroke-width="1.5" fill="none"/>';
    else if(/kochschinken|schinken|aufschnitt|mortadella/.test(key))food='<g fill="#e98f8b" stroke="#c96e6a"><rect x="16" y="24" width="30" height="9" rx="4"/><rect x="19" y="33" width="29" height="9" rx="4"/><rect x="15" y="41" width="28" height="7" rx="3"/></g>';
    else if(/salami/.test(key))food='<g fill="#b84f4c" stroke="#8f3736"><circle cx="22" cy="31" r="8"/><circle cx="36" cy="29" r="8"/><circle cx="42" cy="40" r="8"/><circle cx="27" cy="42" r="8"/></g><g fill="#f0c7ae"><circle cx="20" cy="30" r="1.2"/><circle cx="38" cy="27" r="1.2"/><circle cx="42" cy="41" r="1.2"/></g>';
    else if(/bacon/.test(key))food='<g transform="rotate(-8 32 34)"><rect x="13" y="25" width="39" height="8" rx="4" fill="#bf5f57"/><rect x="13" y="35" width="39" height="8" rx="4" fill="#c8675d"/><path d="M16 28h33M16 38h33" stroke="#f1c2aa" stroke-width="2"/></g>';
    else if(/bratwurst|bockwurst|wiener|wurstchen|wuerstchen|fleischwurst|wurst/.test(key))food='<g fill="#d78965" stroke="#b9674d" stroke-width="1.2"><rect x="13" y="27" width="37" height="8" rx="4" transform="rotate(-8 32 31)"/><rect x="15" y="38" width="35" height="8" rx="4" transform="rotate(7 32 42)"/></g>';
    else if(/hahnchen|haehnchen|huhnchen|huehnchen|pute/.test(key)||motif==='chicken')food='<g fill="#efb68f" stroke="#d79370"><path d="M14 37c4-12 14-18 23-14 9 4 8 14 2 22-10 6-22 3-25-8z"/><path d="M33 29c5-7 14-8 18-2 5 7-1 16-9 20-8-3-12-10-9-18z"/></g>';
    else if(/hack|bolognese/.test(key))food='<g fill="none" stroke="#b95754" stroke-width="2.7" stroke-linecap="round"><path d="M16 27c8-5 14 7 22 1s14 4 9 9-13-1-18 5-12 1-7-5 3-4 4-10 1-10-5-13-5-4-11-5"/></g>';
    else if(/steak|schnitzel|nacken|gulasch|roulade/.test(key))food='<path d="M15 36c2-12 14-19 25-15 12 4 14 15 6 24-10 7-28 5-31-9z" fill="#bd625c" stroke="#9f4947"/><ellipse cx="36" cy="31" rx="6" ry="4" fill="#efb59b" opacity=".7"/>';
    else if(motif==='tofu')food='<g fill="#e8dfbc" stroke="#c8bd94"><rect x="17" y="25" width="15" height="15" rx="2"/><rect x="31" y="22" width="15" height="15" rx="2"/><rect x="26" y="38" width="16" height="10" rx="2"/></g>';
    else if(motif==='veggie')food='<g fill="#75a85c" stroke="#4d7d40"><circle cx="24" cy="32" r="10"/><circle cx="39" cy="36" r="11"/></g>';
    else food='<path d="M15 36c2-12 14-19 25-15 12 4 14 15 6 24-10 7-28 5-31-9z" fill="#c86f67"/>';
    return '<g filter="url(#v3shadow)"><rect x="8" y="15" width="48" height="38" rx="9" fill="#edf1ef" stroke="#c7d0cc"/><rect x="12" y="19" width="40" height="30" rx="7" fill="#fff" opacity=".62"/>'+food+'</g>'+cap;
  }
  if(base==='bag' && (motif==='pasta'||motif==='rice')){
    let food='';
    if(/spaghetti|linguine/.test(key))food='<g stroke="#d8a02b" stroke-width="2.3" stroke-linecap="round"><path d="M22 24v20M27 23v22M32 25v19M37 23v22M42 24v20"/></g>';
    else if(/tagliatelle/.test(key))food='<g fill="none" stroke="#d7a02c" stroke-width="2.5"><ellipse cx="26" cy="33" rx="8" ry="6"/><ellipse cx="39" cy="34" rx="8" ry="6"/></g>';
    else if(/fusilli/.test(key))food='<g fill="none" stroke="#d69c2d" stroke-width="2.2"><path d="M20 25c9 4-2 8 7 12s-2 7 6 11M33 23c9 4-2 8 7 12s-2 7 6 10"/></g>';
    else if(/penne|nudeln|dinkelnudeln|vollkornnudeln|suppennudeln/.test(key))food='<g stroke="#d79c2b" stroke-width="5" stroke-linecap="round"><path d="M20 27l7 4M34 25l7 4M22 39l7 4M36 37l7 4"/></g>';
    else if(/makkaroni/.test(key))food='<g fill="none" stroke="#d99f31" stroke-width="4"><path d="M18 31c0-8 12-8 12 0v8M34 28c0-8 12-8 12 0v10"/></g>';
    else if(/lasagne/.test(key))food='<g fill="#e6b953" stroke="#c7922c"><path d="M18 25h28l-3 7H15z"/><path d="M20 34h28l-3 7H17z"/><path d="M18 43h25l-2 5H16z"/></g>';
    else if(/glasnudel/.test(key))food='<g fill="none" stroke="#e5d5a7" stroke-width="1.7"><path d="M17 30c9-8 20 8 29-1M17 36c10-8 20 8 30 0M18 42c8-7 18 7 27 0"/></g>';
    else if(/mie/.test(key))food='<rect x="17" y="25" width="30" height="22" rx="3" fill="#e1bd66"/><g stroke="#bd8f35" stroke-width="1"><path d="M20 29h24M20 33h24M20 37h24M20 41h24"/></g>';
    else food='<g fill="#efe4c5"><ellipse cx="24" cy="30" rx="2.1" ry="1"/><ellipse cx="30" cy="34" rx="2.1" ry="1"/><ellipse cx="37" cy="29" rx="2.1" ry="1"/><ellipse cx="42" cy="37" rx="2.1" ry="1"/><ellipse cx="26" cy="42" rx="2.1" ry="1"/><ellipse cx="35" cy="43" rx="2.1" ry="1"/></g>';
    return '<g filter="url(#v3shadow)"><path d="M14 10h36l-4 47H18z" fill="'+pal[1]+'" stroke="#c8aa68"/><path d="M14 10h36v9H14z" fill="'+pal[0]+'"/><rect x="17" y="21" width="30" height="28" rx="5" fill="#fff8df" opacity=".86"/>'+food+'</g>'+cap;
  }
  if(base==='frozen_bag'){
    let food='';
    if(motif==='berries')food='<g fill="#5968b6"><circle cx="24" cy="33" r="6"/><circle cx="34" cy="28" r="6"/><circle cx="42" cy="36" r="6"/><circle cx="30" cy="41" r="6"/></g>';
    else if(motif==='potato')food='<g stroke="#edc34a" stroke-width="4" stroke-linecap="round"><path d="M21 27l4 18M29 25l3 20M38 25l-2 20M45 28l-4 16"/></g>';
    else if(motif==='leaf'||motif==='broccoli'||motif==='cauliflower'||motif==='beans'||motif==='corn'||motif==='frozen')food='<g fill="#64a755"><circle cx="25" cy="32" r="7"/><circle cx="38" cy="30" r="8"/><path d="M20 42c8-8 17-8 25 0" stroke="#3d7b40" stroke-width="3" fill="none"/></g>';
    else if(motif==='fish')food='<path d="M18 35c8-9 19-11 29-2l7-5-2 10 2 9-8-5c-10 7-21 4-28-7z" fill="#8bbbc7"/>';
    else if(motif==='chicken')food='<g fill="#e6aa72"><ellipse cx="27" cy="34" rx="9" ry="6"/><ellipse cx="40" cy="37" rx="8" ry="6"/></g>';
    else if(motif==='icecube')food='<g fill="#c7ecf8" stroke="#72b5cb"><rect x="19" y="25" width="13" height="13" rx="2" transform="rotate(-10 25 31)"/><rect x="34" y="24" width="13" height="13" rx="2" transform="rotate(8 40 30)"/><rect x="27" y="37" width="13" height="13" rx="2" transform="rotate(5 33 43)"/></g>';
    else if(/pizza|flammkuchen/.test(key))food='<circle cx="32" cy="35" r="14" fill="#dca85f"/><circle cx="32" cy="35" r="11" fill="#e65b47"/><g fill="#f0d06b"><circle cx="27" cy="32" r="3"/><circle cx="38" cy="38" r="3"/></g>';
    if(food)return '<g filter="url(#v3shadow)"><path d="M14 10h36l-4 47H18z" fill="#4b93d0" stroke="#2b6eac"/><path d="M14 10h36v9H14z" fill="#dceff9"/><rect x="18" y="22" width="28" height="27" rx="5" fill="#f5fbfd" opacity=".88"/>'+food+'</g>'+cap;
  }
  return '';
}
function productVisualSvgV3(e){
  const key=visualNameV2(e),base=e?.visualBase||'loose',motif=e?.visualMotif||'generic',pal=visualPaletteV2(motif,e?.categoryId||'other',key);let label=String(e?.visualLabel||'').trim().toUpperCase();
  if(!label&&key.includes('schmand'))label='SCHMAND';if(!label&&key.includes('saure sahne'))label='SAHNE';if(!label&&key.includes('toastkase'))label='TOASTKÄSE';if(!label&&key.includes('musliriegel'))label='MÜSLI';
  let art=specialProductArtV3(base,motif,key,label,pal);if(!art)art=base==='loose'?naturalArtV3(motif,key):'';if(!art&&base==='loose')art=naturalArtV3(motif==='generic'?'fruit':motif,key)||'<g filter="url(#v3shadow)"><circle cx="32" cy="34" r="18" fill="'+pal[0]+'"/><path d="M20 37c8-10 17-14 25-18" stroke="#fff" stroke-opacity=".42" stroke-width="3" stroke-linecap="round"/></g>';
  if(!art)art=packageArtV3(base,pal[0],pal[1],label,motif);
  const looseLabel=(base==='loose'&&label)?'<g filter="url(#v3shadow)"><rect x="8" y="47" width="48" height="12" rx="6" fill="rgba(255,255,255,.94)"/><text x="32" y="54" text-anchor="middle" dominant-baseline="middle" textLength="38" lengthAdjust="spacingAndGlyphs" style="font-size:5.3px;font-weight:900;letter-spacing:.1px;fill:#35433f">'+xmlEsc(label.slice(0,12))+'</text></g>':'';
  return '<svg class="product-visual-v3" viewBox="0 0 64 64" aria-hidden="true">'+illustrationDefsV3()+shadowV3()+art+looseLabel+'</svg>';
}
function productIcon(e){let src=e?.generatedImage?String(e.generatedImage):"";if(e?.generatedImage){src+=(src.includes('?')?'&':'?')+'v='+encodeURIComponent(String(e.imageRevision||e.imageGeneratedAt||"1"))}if(src){const img='<img class="product-photo" src="'+esc(src)+'" alt="" loading="lazy" decoding="async">';if(e?.imageSource==='pending')return '<span class="photo-state-wrap">'+img+'<span class="photo-state-badge pending" title="Gemini-Bild wird erzeugt">KI</span></span>';if(e?.imageSource==='error')return '<span class="photo-state-wrap">'+img+'<span class="photo-state-badge error" title="'+esc(e.imageError||'Bildgenerierung fehlgeschlagen')+'">!</span></span>';return img}const local='<img class="product-photo" src="product-images/'+esc(e.processedIcon || ((e.imageKey||"misc")+".webp"))+'" alt="" loading="lazy">';if(e?.imageSource==='pending')return '<span class="photo-state-wrap">'+local+'<span class="photo-state-badge pending" title="Gemini-Bild wird erzeugt">KI</span></span>';if(e?.imageSource==='error')return '<span class="photo-state-wrap">'+local+'<span class="photo-state-badge error" title="'+esc(e.imageError||'Bildgenerierung fehlgeschlagen')+'">!</span></span>';return local}
function categorySceneV2(kind){
  const defs=visualDefsV2();const sh=shadowV2(18,57);let body='';
  if(kind==='produce_scene')body='<g filter="url(#v2Soft)"><path d="M12 31h40l-5 20H17z" fill="#cda45a" stroke="#987342"/><path d="M17 31c2-9 8-14 15-14s13 5 15 14" fill="none" stroke="#9a7441" stroke-width="3"/><circle cx="24" cy="28" r="8" fill="url(#v2Red)"/><path d="M24 18l2 5 5-2-3 5" fill="#3c9846"/><path d="M37 23l10 3-8 18-6-8z" fill="#ed8429"/><path d="M39 23c-5-2-7-6-7-10 5 0 8 4 7 10z" fill="#4c9e4c"/><path d="M16 29c3-9 9-13 17-13-2 9-8 14-17 13z" fill="#5ba24d"/></g>';
  else if(kind==='veg_scene')body='<g filter="url(#v2Soft)"><path d="m18 32 13-7 14 7-14 8z" fill="#eee1bf" stroke="#b9aa83"/><path d="M18 32v14l13 7V40zM45 32v14l-14 7V40z" fill="#ded0aa"/><path d="M13 43c4-14 13-21 26-21-2 13-10 22-26 21z" fill="#56a657"/><path d="M15 40c7-7 12-12 21-16" stroke="#b8df8b" stroke-width="2" fill="none"/></g>';
  else if(kind==='bakery_scene')body='<g filter="url(#v2Soft)"><path d="M9 38c0-10 7-17 18-17s17 7 17 17v14H9z" fill="url(#v2Brown)" stroke="#91592e"/><path d="M15 34c4-5 8-6 11-4M26 27c5-3 9-2 13 2" stroke="#f1c98a" stroke-width="2" fill="none"/><rect x="34" y="35" width="20" height="9" rx="4" fill="#b9783c"/><circle cx="40" cy="39" r="1.4" fill="#edcf80"/><circle cx="47" cy="39" r="1.4" fill="#6f472b"/></g>';
  else if(kind==='baking_scene')body='<g filter="url(#v2Soft)"><path d="M17 11h27l-3 42H20z" fill="#f1dfbb" stroke="#b79a68"/><text x="30" y="36" text-anchor="middle" font-size="10" font-weight="900" fill="#8c5b31">MEHL</text><path d="M43 48c-1-15 3-28 11-37M49 41l6-5M46 33l7-5M44 25l6-5" stroke="#d0a041" stroke-width="2" fill="none"/></g>';
  else if(kind==='milk_scene')body='<g filter="url(#v2Soft)"><path d="M12 18h10l4 6v27H11V24z" fill="#f7fbfd" stroke="#a8bdc7"/><rect x="12" y="30" width="13" height="12" fill="#4a9bd0"/><path d="M30 26h18l-2 25H32z" fill="#f8fcfd" stroke="#a8bdc7"/><ellipse cx="39" cy="26" rx="9" ry="3" fill="#3f91c7"/><path d="M44 43l10-10 4 17H43z" fill="#efc64e" stroke="#d7aa31"/></g>';
  else if(kind==='canned_scene')body='<g filter="url(#v2Soft)"><ellipse cx="32" cy="16" rx="14" ry="5" fill="url(#v2Silver)" stroke="#94a1a7"/><path d="M18 16v34c0 5 28 5 28 0V16" fill="url(#v2Silver)" stroke="#94a1a7"/><rect x="20" y="28" width="24" height="15" rx="3" fill="#e95443"/><circle cx="32" cy="35" r="6" fill="#f06452"/><path d="M32 28l2 4 4-2-2 4" fill="#3c9846"/></g>';
  else if(kind==='pasta_scene')body='<g filter="url(#v2Soft)"><g stroke="#dda438" stroke-width="4" stroke-linecap="round"><path d="M12 22l17 11M15 17l17 11M20 14l16 10"/></g><path d="M34 34h22c0 11-5 17-11 17s-11-6-11-17z" fill="#fff" stroke="#c4c7c1"/><ellipse cx="45" cy="35" rx="10" ry="3" fill="#f0dfbd"/><path d="M37 35c3-3 5-4 8-2M42 36c3-3 6-3 9-1" stroke="#c4a470" stroke-width="1.2"/></g>';
  else if(kind==='sauce_scene')body='<g filter="url(#v2Soft)"><path d="M15 10h8v7l5 6v29H10V23l5-6z" fill="#d8bd49" stroke="#988331"/><rect x="12" y="30" width="14" height="14" rx="3" fill="#8a9b3b"/><path d="M37 14h13l-2 7 4 5-4 27H35l-3-27 4-5z" fill="#df4b3d" stroke="#ad342e"/><rect x="36" y="32" width="13" height="12" rx="3" fill="#fff" opacity=".82"/></g>';
  else if(kind==='cheese_scene')body='<g filter="url(#v2Soft)"><path d="M13 49l27-29 10 30H13z" fill="#efc34c" stroke="#d5a22e"/><circle cx="37" cy="38" r="3" fill="#d8a12f"/><circle cx="44" cy="44" r="2.2" fill="#d8a12f"/><path d="M19 47l21-23" stroke="#ffe88b" stroke-width="2"/></g>';
  else if(kind==='household_scene'||kind==='cleaner_scene')body='<g filter="url(#v2Soft)"><path d="M16 19h20l4 6v27H12V25z" fill="#54a9c8" stroke="#3584a0"/><path d="M22 10h12v8H22z" fill="#2d7ea2"/><path d="M38 18h12l5 4-4 4-8-3" fill="#2d7ea2"/><rect x="34" y="38" width="20" height="12" rx="3" fill="#e2c65d" stroke="#b59a38"/><path d="M37 41h14M37 45h14" stroke="#f3e89e"/></g>';
  else if(kind==='pantry_milk_scene')body='<g filter="url(#v2Soft)"><path d="M12 13h19l6 8v32H12z" fill="#f8fcfd" stroke="#a8bac2"/><path d="M12 13h19l6 8H19z" fill="#82b5d4"/><rect x="16" y="31" width="17" height="14" rx="3" fill="#4d9bcb"/><ellipse cx="47" cy="40" rx="8" ry="11" fill="#f1dfbd" stroke="#c6ad7a"/></g>';
  else if(kind==='yogurt_scene')body='<g filter="url(#v2Soft)"><ellipse cx="31" cy="21" rx="14" ry="4" fill="#418fc4"/><path d="M18 21h27l-3 31H21z" fill="#fff" stroke="#b0b9b5"/><rect x="21" y="31" width="21" height="15" rx="4" fill="#d8edf8"/><circle cx="39" cy="38" r="4" fill="#365fb3"/><circle cx="34" cy="42" r="3" fill="#3158a8"/></g>';
  else if(kind==='chilled_scene')body='<g filter="url(#v2Soft)"><rect x="10" y="31" width="19" height="14" rx="3" fill="#f0c44d" stroke="#d4a631"/><rect x="29" y="25" width="26" height="23" rx="5" fill="#e8edf0" stroke="#aab4b6"/><rect x="33" y="30" width="18" height="13" rx="3" fill="#f2d28a"/><path d="M37 34h10" stroke="#74a86c" stroke-width="2"/></g>';
  else if(kind==='counter_scene')body='<g filter="url(#v2Soft)"><path d="M10 47h44v7H10z" fill="#a8784c"/><path d="M13 38c5-10 16-12 23-6 4 4 3 10-2 14H15z" fill="#b95958"/><path d="M37 43l11-13 6 16H37z" fill="#efc44e"/><circle cx="47" cy="40" r="2" fill="#d7a22f"/></g>';
  else if(kind==='frozen_scene')body='<g filter="url(#v2Soft)"><path d="M13 13h38l-4 40H17z" fill="#48a1d5" stroke="#277cac"/><path d="M13 13h38v8H13z" fill="#d9f0fb"/><path d="M22 34c8-7 19-7 26 0-6 7-18 10-26 0z" fill="#65ac4e"/><path d="M43 17v9M39 21h8" stroke="#fff" stroke-width="2"/></g>';
  else if(kind==='meat_scene')body='<g filter="url(#v2Soft)"><rect x="10" y="18" width="44" height="34" rx="8" fill="#e8eceb" stroke="#aab2ae"/><path d="M17 36c5-12 18-16 26-8 7 7 1 18-10 19-10 1-19-3-16-11z" fill="#bd605d"/><circle cx="38" cy="31" r="4" fill="#f0b59b"/></g>';
  else if(kind==='drink_scene')body='<g filter="url(#v2Soft)"><path d="M13 10h9v7l5 6v30H9V23l4-6z" fill="#d9f1fa" stroke="#6da8c5"/><rect x="11" y="31" width="14" height="13" rx="3" fill="#52a5d2"/><path d="M34 15h18l5 7v31H34z" fill="#fff5d8" stroke="#b8ad8a"/><rect x="36" y="31" width="18" height="14" rx="3" fill="#ef9e30"/><circle cx="45" cy="38" r="5" fill="#f7bc4c"/></g>';
  else if(kind==='drugstore_scene'||kind==='bodycare_scene')body='<g filter="url(#v2Soft)"><path d="M15 16h20v36H12V22z" fill="#69a8d1" stroke="#4384ad"/><rect x="20" y="8" width="11" height="9" rx="2" fill="#3479a6"/><path d="M40 16h4v34h-4z" fill="#6bb0ce"/><path d="M37 15h10l-1 8-8-1z" fill="#f2f5f6"/><ellipse cx="51" cy="45" rx="7" ry="5" fill="#f1e8d9" stroke="#bfc1b9"/></g>';
  else if(kind==='sweet_scene')body='<g filter="url(#v2Soft)"><rect x="12" y="17" width="27" height="30" rx="4" fill="#6d3b2a"/><path d="M21 17v30M30 17v30M12 27h27M12 37h27" stroke="#a86c4b"/><circle cx="47" cy="35" r="6" fill="#e55d51"/><circle cx="51" cy="43" r="5" fill="#e0b135"/><circle cx="42" cy="44" r="5" fill="#79a84b"/></g>';
  else if(kind==='stationery_scene')body='<g filter="url(#v2Soft)"><rect x="12" y="14" width="28" height="38" rx="4" fill="#f9fbfc" stroke="#98a9b4"/><path d="M18 22h16M18 29h16M18 36h13" stroke="#87a0b4" stroke-width="1.6"/><path d="M43 45l4-27 6 1-4 27z" fill="#3d83c2"/><path d="M35 47l7-26 6 2-7 26z" fill="#e35c58"/></g>';
  else if(kind==='icecream_scene')body='<g filter="url(#v2Soft)"><path d="M19 28h26l-3 24H22z" fill="#5b9ed1" stroke="#3d7ca8"/><ellipse cx="32" cy="28" rx="13" ry="4" fill="#d9f0f9"/><circle cx="32" cy="26" r="10" fill="#f0c9dc"/><path d="M47 17v12M41 20l12 6M53 20l-12 6" stroke="#4d9bc8" stroke-width="1.8"/></g>';
  else if(kind==='paper_scene')body='<g filter="url(#v2Soft)"><ellipse cx="25" cy="35" rx="13" ry="18" fill="#fff" stroke="#c1c7c4"/><ellipse cx="25" cy="35" rx="5" ry="7" fill="#ded5c9"/><path d="M39 18h11v34H39z" fill="#fff8ef" stroke="#c4bdb1"/></g>';
  else if(kind==='kids_snack_scene')body='<g filter="url(#v2Soft)"><rect x="12" y="27" width="40" height="15" rx="5" fill="#b97a3c"/><circle cx="20" cy="32" r="2" fill="#efd184"/><circle cx="28" cy="36" r="2" fill="#6f472b"/><circle cx="36" cy="31" r="2" fill="#efd184"/><circle cx="44" cy="36" r="2" fill="#6f472b"/><path d="M12 27l5-6 5 6M52 28l5 5-5 7" fill="#e8edf0" stroke="#aab5bc"/></g>';
  else body='<g filter="url(#v2Soft)"><path d="m12 22 20-11 20 11-20 11z" fill="#d4a96a"/><path d="M12 22v25l20 10V33zM52 22v25L32 57V33z" fill="#c69255"/><path d="M12 22l20 11 20-11" stroke="#8d673d" fill="none"/></g>';
  return '<svg class="category-visual-v2" viewBox="0 0 64 64" aria-hidden="true">'+defs+sh+body+'</svg>';
}
function categoryIcon(c){if(c?.generatedImage){let src=String(c.generatedImage);src+=(src.includes('?')?'&':'?')+'v='+encodeURIComponent(String(c.imageRevision||c.imageGeneratedAt||'1'));return '<img class="category-photo" src="'+esc(src)+'" alt="" loading="lazy" decoding="async">'}const key=c?.imageKey||c?.id||'other';if(key)return '<img class="category-photo" src="category-images/'+encodeURIComponent(key)+'.webp?v=0.3.59" alt="" loading="lazy" decoding="async" onerror="this.style.display=\'none\'">';return categorySceneV2(c?.visualKind||CATEGORY_KIND[c?.id]||'box_scene')}

function firstUpper(value){const text=String(value||'').trim();return text?text.charAt(0).toUpperCase()+text.slice(1):''}
function unitLabel(unit,value){const key=String(unit||'stück').toLowerCase();const labels={stück:['Stück','Stück'],kiste:['Kiste','Kisten'],karton:['Karton','Kartons'],packung:['Packung','Packungen'],paket:['Paket','Pakete'],flasche:['Flasche','Flaschen'],dose:['Dose','Dosen'],bund:['Bund','Bunde'],beutel:['Beutel','Beutel'],tüte:['Tüte','Tüten'],kg:['kg','kg'],g:['g','g'],mg:['mg','mg'],l:['l','l'],ml:['ml','ml']};const pair=labels[key]||[firstUpper(key),firstUpper(key)];return Number(value)===1?pair[0]:pair[1]}
function qty(q){return q?'<span class="qty">'+esc(q.value+' '+unitLabel(q.unit,q.value))+'</span>':''}
function currentList(){return appState.lists.find(l=>l.id===appState.activeListId)||appState.list||{name:'Einkaufsliste',color:'#ef5d61'}}
function listColor(){const color=String(currentList().color||'').toLowerCase();return /^#[0-9a-f]{6}$/.test(color)?color:'#ef5d61'}
function cardStyle(){return 'style="--list-color:'+listColor()+'"'}
function sortedCategories(){return (appState.categories||[]).slice().sort((a,b)=>(a.sort??0)-(b.sort??0))}
function groupedEntries(){const groups=new Map(sortedCategories().map(c=>[c.id,[]]));for(const e of (appState.entries||[])){if(!groups.has(e.categoryId))groups.set(e.categoryId,[]);groups.get(e.categoryId).push(e)}return groups}
function categoryName(id){return appState.categories.find(c=>c.id===id)?.name||'Sonstiges'}
function openCount(){return (appState.entries||[]).length}
function doneCount(){return (appState.recent||[]).length}
function syncAge(){if(!appState.updatedAt)return 'bereit';const seconds=Math.max(0,Math.round((Date.now()-new Date(appState.updatedAt).getTime())/1000));if(seconds<10)return 'gerade eben';if(seconds<60)return 'vor '+seconds+' s';const minutes=Math.floor(seconds/60);return 'vor '+minutes+' Min.'}
function summaryText(){const areas=sortedCategories().filter(c=>(groupedEntries().get(c.id)||[]).length).length;return view==='recent'?(doneCount()+' zuletzt erledigt'):(openCount()+' offene Artikel · '+areas+' Bereiche')}
function renderShell(){document.documentElement.style.setProperty('--list-color',listColor());const active=currentList();$('title').textContent=active.name;$('summary').textContent=summaryText();$('view-label').textContent=view==='recent'?'Zuletzt':'Aktive Liste';if($('desktop-list-switcher'))$('desktop-list-switcher').innerHTML=appState.lists.slice().sort((a,b)=>(a.sort??0)-(b.sort??0)).map(list=>'<button class="side-list '+(list.id===appState.activeListId?'active':'')+'" onclick="switchList(\''+list.id+'\')"><span class="left"><span class="list-color '+(list.id===appState.activeListId?'list-current':'')+'" style="background:'+esc(list.color||'#ef5d61')+'"></span><span><strong>'+esc(list.name)+'</strong><span class="meta">'+(list.itemCount||0)+' Artikel</span></span></span><span>›</span></button>').join('')||'<div class="status-line">Noch keine Listen</div>';if($('desktop-categories')){const groups=groupedEntries();const visible=sortedCategories().filter(c=>(groups.get(c.id)||[]).length);$('desktop-categories').innerHTML=(visible.length?visible.map(c=>{const count=(groups.get(c.id)||[]).length;const action=view==='list'&&count?(' onclick="scrollToCategory(\''+c.id+'\')"'):'';const tone=categoryTone(c.id);return '<button class="side-link '+(view==='list'&&count?'active':'')+'"'+action+' style="--cat-accent:'+tone[0]+';--cat-soft:'+tone[1]+'"><span class="left"><span class="cat-icon">'+categoryIcon(c)+'</span><span><strong>'+esc(c.name)+'</strong><span class="meta">'+count+' Artikel</span></span></span><span class="tiny-pill">'+count+'</span></button>'}).join(''):'<div class="status-line">Noch keine gefüllten Bereiche.</div>')}if($('desktop-utility')){const recent=(appState.recent||[]).slice(0,5);const areas=sortedCategories().filter(c=>(groupedEntries().get(c.id)||[]).length).length;$('desktop-utility').innerHTML='<div class="pane-card"><div class="accent-line"></div><div class="pane-head"><span>Überblick</span><button class="chip-action" onclick="manageLists()">Einstellungen</button></div><div class="stat-grid"><div class="stat"><span class="label">Offen</span><strong>'+openCount()+'</strong></div><div class="stat"><span class="label">Zuletzt</span><strong>'+doneCount()+'</strong></div><div class="stat"><span class="label">Bereiche</span><strong>'+areas+'</strong></div><div class="stat"><span class="label">Sync</span><strong style="font-size:16px">'+(appState.syncListId===appState.activeListId?'aktiv':'andere Liste')+'</strong></div></div></div>'+'<div class="pane-card"><div class="pane-head"><span>Zuletzt</span><button class="chip-action" onclick="showRecent()">Öffnen</button></div>'+(recent.length?recent.map(e=>'<button class="mini-action" onclick="readd(event,\''+e.id+'\')"><span><strong>'+esc(e.productName||e.name||'Artikel')+'</strong><br><small>'+(e.productDetail?esc(e.productDetail):(e.quantity?esc(e.quantity.value+' '+unitLabel(e.quantity.unit,e.quantity.value)):'zuletzt erledigt'))+'</small></span><span>＋</span></button>').join(''):'<div class="status-line">Noch keine erledigten Artikel.</div>')+'</div>'+'<div class="pane-card"><div class="pane-head"><span>Status</span></div><div class="status-line">Automatische Aktualisierung: alle 5 Sekunden · zuletzt '+syncAge()+'.<br>Gemini-Kategorisierung: '+(appState.geminiConfigured?'aktiv':'nicht konfiguriert')+'.</div></div>'}}

function categorySection(c,items){const collapsed=collapsedCategories.has(c.id);const tone=categoryTone(c.id);const longName=String(c.name||'').length>24?' long-category':'';const shop=/^(rewe|meyerhof|dm\/rossmann\/müller)$/i.test(String(c.name||'').trim())?'<span class="shop-badge">Einkaufsort</span>':'';return '<section class="section" id="section-'+c.id+'" style="--cat-accent:'+tone[0]+';--cat-soft:'+tone[1]+'"><div class="section-head"><div class="section-title"><span class="cat-icon">'+categoryIcon(c)+'</span><div><h2 class="'+longName.trim()+'">'+esc(c.name)+'</h2><small>'+items.length+' Artikel '+shop+'</small></div></div><div class="actions"><button class="collapse-btn" onclick="toggleSection(\''+c.id+'\')">'+(collapsed?'＋':'⌄')+'</button></div></div><div data-group="'+c.id+'" class="list-group'+(collapsed?' hidden':'')+'">'+items.map(card).join('')+'</div></section>'}
function render(){renderShell();updateOfflineStatus();if(view==='recent'){renderRecent();updateOfflineStatus();updateNav();scheduleOfflineImageWarmup();return}const groups=groupedEntries();$('list').innerHTML=sortedCategories().map(c=>{const items=groups.get(c.id)||[];if(!items.length)return '';return categorySection(c,items)}).join('')||'<div class="empty">Noch nichts auf der Einkaufsliste.<br><small>Füge unten deinen ersten Artikel hinzu.</small></div>';updateSelectionBar();updateNav();scheduleOfflineImageWarmup()}
function renderRecent(){renderShell();const items=appState.recent||[];const recentHtml=items.length?'<section class="section"><div class="section-head"><div class="section-title"><span class="cat-icon">'+iconSvg('generic')+'</span><div><h2>Zuletzt</h2><small>Abgehakte Artikel mit einem Tippen zurück auf die Liste setzen</small></div></div><div class="actions"><span id="recent-count" class="count-badge">'+items.length+'</span></div></div><div class="recent-search"><input id="recent-search" type="search" inputmode="search" placeholder="Zuletzt durchsuchen" aria-label="Zuletzt durchsuchen" oninput="filterRecent(this.value)"></div><div id="recent-list" class="list-group">'+items.map(recentCard).join('')+'</div><div id="recent-filter-empty" class="recent-filter-empty hidden">Kein passender Artikel.</div></section>':'<div class="empty">Noch keine abgehakten Artikel.</div>';$('list').innerHTML=recentHtml;updateSelectionBar();updateNav()}
function filterRecent(value){const query=keyText(value);let visible=0;document.querySelectorAll('.recent-card[data-search]').forEach(card=>{const match=!query||String(card.dataset.search||'').includes(query);card.classList.toggle('hidden',!match);if(match)visible++});const badge=$('recent-count');if(badge)badge.textContent=String(visible);const empty=$('recent-filter-empty');if(empty)empty.classList.toggle('hidden',visible!==0)}

function recentCard(e){const details=[];if(e.productDetail)details.push('<span class="product-detail">'+esc(e.productDetail)+'</span>');if(e.quantity)details.push(qty(e.quantity));if(e.note)details.push('<span class="entry-note">'+esc(e.note)+'</span>');if(!details.length)details.push('<span>Zuletzt erledigt</span>');const search=keyText([e.productName||e.name||'',e.productDetail||'',e.note||'',categoryName(e.categoryId)].join(' '));return '<article class="card recent-card" data-search="'+esc(search)+'" '+cardStyle()+'><div class="card-main"><div class="item-icon">'+productIcon(e)+'</div><div class="item-text"><div class="name">'+esc(e.productName||e.name||'Artikel')+'</div><div class="item-subline">'+details.join('')+'</div></div></div><div class="card-actions"><button class="action-plus" type="button" aria-label="Zur Liste hinzufügen" onclick="readd(event,\''+e.id+'\')">+</button></div></article>'}
function card(e){const chosen=selected.has(e.id)?' selected':'';const action=selectionMode?'<span class="select-dot '+(selected.has(e.id)?'is-selected':'')+'">'+(selected.has(e.id)?'✓':'')+'</span>':'<button class="check" type="button" aria-label="'+esc(e.productName)+' abhaken" title="Abhaken" onpointerdown="event.stopPropagation()" onpointerup="event.stopPropagation()" onclick="checkItem(event,\''+e.id+'\')">✓</button>';const parts=[];if(e.productDetail)parts.push('<span class="product-detail">'+esc(e.productDetail)+'</span>');if(e.quantity)parts.push(qty(e.quantity));if(e.note)parts.push('<span class="entry-note">'+esc(e.note)+'</span>');const subline=parts.length?'<div class="item-subline">'+parts.join('')+'</div>':'';return '<article class="card'+chosen+'" '+cardStyle()+' data-id="'+e.id+'" oncontextmenu="return false" onselectstart="return false" ondblclick="event.preventDefault();return false" onpointerdown="gestureStart(event,\''+e.id+'\')" onpointermove="gestureMove(event,\''+e.id+'\')" onpointerup="gestureEnd(event,\''+e.id+'\')" onpointercancel="gestureCancel()"><div class="card-main"><div class="item-icon">'+productIcon(e)+'</div><div class="item-text"><div class="name">'+esc(e.productName)+'</div>'+subline+'</div></div><div class="card-actions">'+action+'</div></article>'}
function showSnack(text){clearTimeout(snackTimer);$('snack').className='snack';$('snack').style.setProperty('--list-color',listColor());$('snack').innerHTML='<span>'+esc(text)+'</span>';$('snack').classList.remove('hidden');snackTimer=setTimeout(()=>$('snack').classList.add('hidden'),30000)}
async function refresh(){const offlineInit=initOfflineStorage();try{const serverState=await api('/api/state');serverReachable=true;await Promise.race([offlineInit,wait(350)]);if(offlineStorageReady&&offlineQueue.length){const synced=await syncPending();if(synced)return appState}appState=materializePending(serverState);render();updateOfflineStatus();void offlineSet(OFFLINE_BASE_KEY,deepClone(serverState));void saveLocalState();return appState}catch(error){if(!error.isNetwork)throw error;serverReachable=false;await Promise.race([offlineInit,wait(500)]);const cached=await offlineGet(OFFLINE_CACHE_KEY);if(cached){appState=cached;render()}updateOfflineStatus();return appState}}
function show(html){$('overlay').innerHTML='<div class="modal-back" onclick="if(event.target===this)closeOverlay()">'+html+'</div>';$('overlay').classList.remove('hidden')};function closeOverlay(){$('overlay').classList.add('hidden');$('overlay').innerHTML='';editId=null}
function categoryPicker(mode){const choices=appState.categories.map(c=>'<button class="cat-choice '+((mode==='edit'?editCategory:selectedCategory())===c.id?'selected':'')+'" onclick="chooseCategory(\''+mode+'\',\''+c.id+'\')"><span class="cat-icon">'+categoryIcon(c)+'</span><span>'+esc(c.name)+'</span><span>✓</span></button>').join('');show('<div class="sheet"><h2>Kategorie wählen</h2>'+choices+'<button class="cat-choice" onclick="createCategory(\''+mode+'\')"><span class="plus">+</span><span>Neue Kategorie erstellen</span></button><button class="secondary" onclick="closeOverlay()">Abbrechen</button></div>')}
function selectedCategory(){return editCategory||'other'}
function chooseCategory(mode,id){if(mode==='edit'){editCategory=id;openEdit(editId,id)}else{moveSelected(id)}}
function cardClick(ev,id){ev.stopPropagation();if(selectionMode){selected.has(id)?selected.delete(id):selected.add(id);render();return}const now=Date.now();if(lastTap.id===id&&now-lastTap.time<550){lastTap={id:'',time:0};checkItem(ev,id)}else lastTap={id,time:now}}
async function createCategory(mode){const name=prompt('Name der neuen Kategorie:');if(!name)return;try{const r=await api('/api/categories',{method:'POST',body:JSON.stringify({name})});appState.categories.push(r.category);if(mode==='edit'){editCategory=r.category.id;openEdit(editId)}else if(mode==='manage'){closeOverlay();await refresh();manageLists()}else if(mode==='categories'){closeOverlay();await refresh();manageCategories()}else moveSelected(r.category.id)}catch(e){showSnack(e.message)}}
function cancelSelection(){selectionMode=false;selected.clear();document.body.classList.remove('selection-active');$('select-btn').textContent='✓';$('snack').classList.add('hidden');render()}
function enterSelection(){selectionMode=true;selected.clear();document.body.classList.add('selection-active');$('select-btn').textContent='×';$('snack').classList.add('hidden');render()}
async function moveSelected(categoryId){if(!selected.size)return;await api('/api/bulk/move',{method:'POST',body:JSON.stringify({ids:[...selected],categoryId})});selected.clear();selectionMode=false;document.body.classList.remove('selection-active');$('select-btn').textContent='✓';closeOverlay();await refresh();showSnack('Kategorie geändert')}
async function moveSelectedToList(listId){if(!selected.size)return;try{const result=await api('/api/bulk/move-list',{method:'POST',body:JSON.stringify({ids:[...selected],listId})});selected.clear();selectionMode=false;document.body.classList.remove('selection-active');$('select-btn').textContent='✓';closeOverlay();await refresh();const moved=Number(result.moved||0),skipped=Number(result.skipped||0),target=result.targetList?.name||'Ziel-Liste';showSnack(moved+' Artikel nach „'+target+'“ verschoben'+(skipped?' · '+skipped+' bereits vorhanden':'') )}catch(e){showSnack(e.message)}}
function updateSelectionBar(){const bar=$('selection-bar');document.body.classList.toggle('selection-active',selectionMode&&view==='list');if(selectionMode&&view==='list'){const count=selected.size;bar.classList.remove('hidden');bar.innerHTML='<div class="selection-head"><div><strong>'+count+' ausgewählt</strong><small>'+(count?'Kategorie ändern oder in eine andere Liste verschieben':'Tippe die gewünschten Artikel an')+'</small></div><span class="selection-counter">'+count+'</span></div><div class="selection-actions"><button class="selection-primary" '+(count?'':'disabled')+' onclick="selectionPicker()">Kategorie</button><button class="selection-list" '+(count?'':'disabled')+' onclick="listMovePicker()">Andere Liste</button><button class="selection-cancel" onclick="cancelSelection()">Abbrechen</button></div>'}else bar.classList.add('hidden')}
function selectionPicker(){if(!selected.size){showSnack('Bitte zuerst Artikel auswählen');return}const choices=appState.categories.map(c=>'<button class="cat-choice" onclick="moveSelected(\''+c.id+'\')"><span class="cat-icon">'+categoryIcon(c)+'</span><span>'+esc(c.name)+'</span></button>').join('');show('<div class="sheet"><h2>Kategorie ändern</h2><p class="status-line">'+selected.size+' ausgewählte Artikel</p>'+choices+'<button class="cat-choice" onclick="createCategory(\'bulk\')"><span class="plus">+</span><span>Neue Kategorie erstellen</span></button><button class="secondary" onclick="closeOverlay()">Abbrechen</button></div>')}
function listMovePicker(){if(!selected.size){showSnack('Bitte zuerst Artikel auswählen');return}const lists=(appState.lists||[]).filter(list=>list.id!==appState.activeListId).sort((a,b)=>(a.sort??0)-(b.sort??0));if(!lists.length){showSnack('Es gibt keine andere bestehende Liste');return}const choices=lists.map(list=>'<button class="cat-choice" onclick="moveSelectedToList(\''+list.id+'\')"><span class="list-color" style="background:'+esc(list.color||'#ef5d61')+'"></span><span class="label"><strong>'+esc(list.name)+'</strong><small>'+Number(list.itemCount||0)+' Artikel</small></span><span>›</span></button>').join('');show('<div class="sheet"><h2>In andere Liste verschieben</h2><p class="status-line">'+selected.size+' ausgewählte Artikel · Ziel-Liste wählen</p>'+choices+'<button class="secondary" onclick="closeOverlay()">Abbrechen</button></div>')}
function geminiDiagnostic(){const status=appState.geminiStatus||{};const image=appState.imageStatus||{};let html='';if(status.item&&status.state!=='idle'){const label={requesting:'letzter Status: Prompt wird gesendet',success:'letzter Status: Antwort erhalten',error:'letzter Status: Fehler',not_configured:'letzter Status: Schlüssel fehlt'}[status.state]||'letzter Status';html+='<p class="status-line">Gemini-Kategorisierung für '+esc(status.item)+': '+esc(label)+' – '+esc(status.detail||'')+'</p>'}if(image.item&&image.state!=='idle'){const label={requesting:'Bild wird erzeugt',success:'Bild gespeichert',error:'Bildfehler',not_configured:'Schlüssel fehlt'}[image.state]||image.state;html+='<p class="status-line">Gemini-Bild für '+esc(image.item)+': '+esc(label)+' – '+esc(image.detail||'')+'</p>'}return html}
function backupStatusText(){const info=appState.backupStatus||{};if(!info.daily?.modifiedAt)return 'Automatisches Backup: noch keine tägliche Sicherung vorhanden.';try{return 'Letzte automatische Sicherung: '+new Date(info.daily.modifiedAt).toLocaleString('de-DE')+'.'}catch{return 'Letzte automatische Sicherung vorhanden.'}}
function listRows(){return appState.lists.slice().sort((a,b)=>a.sort-b.sort).map(list=>'<div class="manage-row"><button class="list-color '+(list.id===appState.activeListId?'list-current':'')+'" style="background:'+list.color+'" onclick="switchList(\''+list.id+'\')"></button><span class="label"><strong>'+esc(list.name)+'</strong><small>'+list.itemCount+' Artikel'+(list.id===appState.syncListId?' · Alexa-Ziel':'')+'</small></span><button class="secondary" onclick="reorderList(\''+list.id+'\',-1)">↑</button><button class="secondary" onclick="reorderList(\''+list.id+'\',1)">↓</button><button class="secondary" onclick="listForm(\''+list.id+'\')">✎</button><button class="danger" onclick="deleteList(\''+list.id+'\')">⌫</button></div>').join('')}
function listForm(id){listEditId=id||'';const list=appState.lists.find(item=>item.id===id)||{name:'',color:'#ef5d61'};const sources=appState.lists.filter(item=>item.id!==id).map(item=>'<option value="'+item.id+'">'+esc(item.name)+'</option>').join('');const label=id?'Name der Liste':'Zusatz in Klammern';const value=id?list.name:'';const placeholder=id?'Einkaufsliste (Drogerie)':'z. B. Drogerie';show('<div class="sheet"><h2>'+(id?'Liste bearbeiten':'Neue Liste erstellen')+'</h2><label>'+label+'</label><input id="list-name" value="'+esc(value)+'" placeholder="'+placeholder+'">'+(id?'':'<p class="status-line">Die Liste heißt automatisch „Einkaufsliste (Zusatz)“.</p>')+'<label>Hintergrundfarbe der Artikel</label><input id="list-color" type="color" value="'+list.color+'"><div id="list-copy-options" '+(id?'class="hidden"':'')+'><label>Optional aus einer bestehenden Liste übernehmen</label><select id="list-copy-source"><option value="">Leer starten</option>'+sources+'</select><label><input id="copy-categories" type="checkbox"> Kategorien übernehmen</label><label><input id="copy-products" type="checkbox"> Artikelstamm übernehmen</label></div><div class="sheet-actions"><button class="primary" onclick="saveListForm()">Speichern</button><button class="secondary" onclick="manageLists()">Abbrechen</button></div></div>')}
async function saveListForm(){const entered=$('list-name').value.trim();const name=listEditId?entered:('Einkaufsliste ('+entered+')');const color=$('list-color').value;try{if(!entered){showSnack('Bitte eine Bezeichnung eingeben');return}if(listEditId){await api('/api/lists/'+listEditId,{method:'PATCH',body:JSON.stringify({name,color})})}else{await api('/api/lists',{method:'POST',body:JSON.stringify({name,color,copyFromId:$('list-copy-source').value,copyCategories:$('copy-categories').checked,copyProducts:$('copy-products').checked,activate:true})})}listEditId=null;closeOverlay();await refresh();showSnack('Liste gespeichert')}catch(e){showSnack(e.message)}}
async function reorderList(id,direction){await api('/api/lists/reorder',{method:'POST',body:JSON.stringify({id,direction})});await refresh();manageLists()}
async function deleteList(id){const list=appState.lists.find(item=>item.id===id);if(!list||!confirm('Liste „'+list.name+'“ wirklich löschen?'))return;try{await api('/api/lists/'+id,{method:'DELETE'});closeOverlay();await refresh();showSnack('Liste gelöscht')}catch(e){showSnack(e.message)}}
async function setSyncList(id){try{appState=await api('/api/settings',{method:'PATCH',body:JSON.stringify({syncListId:id})});manageLists()}catch(e){showSnack(e.message)}}
function categoryRows(){return appState.categories.map(c=>'<div class="manage-row category-manage-row"><span class="cat-icon">'+categoryIcon(c)+'</span><span class="label"><strong>'+esc(c.name)+'</strong></span><span class="category-row-actions"><button class="secondary" onclick="moveCategory(\''+c.id+'\',-1)">↑</button><button class="secondary" onclick="moveCategory(\''+c.id+'\',1)">↓</button><button class="secondary" onclick="editCategorySettings(\''+c.id+'\')" title="Kategorie bearbeiten und Icon erzeugen">✎</button>'+(c.id==='other'?'<span></span>':'<button class="danger" onclick="deleteCategory(\''+c.id+'\')">⌫</button>')+'</span></div>').join('')}
function copySiriEndpoint(){const endpoint=new URL('/api/shortcut/add',window.location.origin).href;navigator.clipboard?.writeText(endpoint).then(()=>showSnack('Siri-Adresse kopiert')).catch(()=>showSnack('Die Siri-Adresse lautet: '+endpoint))}
function siriShortcutSetup(){const endpoint=esc(new URL('/api/shortcut/add',window.location.origin).href);show('<div class="sheet"><div class="sheet-head"><h2>Siri einrichten</h2><button class="sheet-icon-action icon-only" onclick="closeOverlay()" title="Schließen" aria-label="Schließen">×</button></div><p class="status-line">Der Kurzbefehl spricht direkt mit dieser Einkaufsliste. Dein Mac kann danach zugeklappt und gesperrt bleiben.</p><ol class="status-line" style="padding-left:20px"><li>In Home Assistant bei dieser App einen langen <strong>shortcut_token</strong> hinterlegen. Der Alexa-Schlüssel bleibt unverändert.</li><li>In <strong>Kurzbefehle</strong> einen neuen Kurzbefehl namens „Auf die Einkaufsliste“ erstellen.</li><li>Die Aktion <strong>Text diktieren</strong> hinzufügen.</li><li><strong>Inhalte von URL abrufen</strong>: POST an die untenstehende Adresse, JSON-Feld <strong>input</strong> = diktierten Text, Header <strong>X-Sync-Token</strong> = dein shortcut_token.</li><li>Den Wert <strong>message</strong> aus der Antwort mit <strong>Text sprechen</strong> vorlesen lassen.</li></ol><p class="status-line"><strong>Adresse</strong><br><code style="font-size:12px;word-break:break-all">'+endpoint+'</code></p><div class="sheet-actions"><button class="primary" onclick="copySiriEndpoint()">Adresse kopieren</button><button class="secondary" onclick="manageLists()">Zurück</button></div><p class="status-line">Danach genügt: „Hey Siri, Auf die Einkaufsliste“ – Siri fragt nach dem Artikel und bestätigt ihn anschließend.</p></div>')}
function manageLists(){show('<div class="sheet"><h2>Listen verwalten</h2><div class="manage-quick-actions"><button class="secondary" onclick="searchCurrentList()">⌕ Liste durchsuchen</button><button class="secondary" onclick="siriShortcutSetup()">⌁ Siri einrichten</button></div><p class="status-line">Jede Liste hat eigene Kategorien, Artikelstämme und Farben.</p>'+listRows()+'<div class="manage-create-row"><button class="primary" onclick="listForm()">+ Liste erstellen</button></div><div class="manage-setting"><label for="sync-list-select">Alexa- und Siri-Zielliste</label><select id="sync-list-select" onchange="setSyncList(this.value)">'+appState.lists.slice().sort((a,b)=>a.sort-b.sort).map(list=>'<option value="'+list.id+'" '+(list.id===appState.syncListId?'selected':'')+'>'+esc(list.name)+'</option>').join('')+'</select></div><p class="status-line">Gemini-Kategorisierung: '+(appState.geminiConfigured?'aktiv':'nicht konfiguriert – Schlüssel in der Home-Assistant-Konfiguration eintragen')+'</p>'+geminiCostHtml()+geminiDiagnostic()+'<div class="manage-setting"><label>Datensicherung</label><p class="status-line">'+esc(backupStatusText())+' Vor jeder Versionsmigration wird der unveränderte alte Datenbestand zusätzlich gesichert. Vor dem Einlesen einer Sicherung wird ebenfalls automatisch eine Sicherheitskopie des aktuellen Stands erstellt.</p><div class="sheet-actions"><button class="secondary" onclick="downloadBackup()">Daten sichern</button><button class="secondary" onclick="restoreBackup()">Sicherung einlesen</button></div></div><button class="secondary" onclick="closeOverlay()">Schließen</button></div>')}
function manageCategories(){show('<div class="sheet"><div class="sheet-head"><h2>Kategorien</h2><button class="sheet-icon-action icon-only" onclick="closeOverlay()" title="Schließen" aria-label="Schließen">×</button></div><div class="category-top-actions"><button class="category-create" onclick="createCategory(\'categories\')">Kategorie erstellen</button><button class="category-products" onclick="manageProducts()">Artikelstamm</button></div>'+geminiCostHtml()+categoryRows()+'</div>')}
function manage(){manageLists()}
function catalogRow(p,c){const status=p.iconEditStatus==='processing'?'In Bearbeitung':p.iconEditStatus==='processed'?'Bearbeitet':'Unbearbeitet';const statusClass=p.iconEditStatus==='processing'?'processing':p.iconEditStatus==='processed'?'processed':'unprocessed';const provenance=p.imageSource==='inherited'&&p.imageInheritedFromName?'<span class="catalog-provenance">Übernommen von '+esc(p.imageInheritedFromName)+'</span>':'';const retry=p.imageSource==='error'?'<button class="secondary" onclick="retryProductImage(event,\''+p.id+'\')" title="Gemini-Bild erneut erzeugen">↻</button>':'';return '<div class="catalog-row"><span class="item-icon">'+productIcon(p)+'</span><span class="label"><strong>'+esc(p.name)+'</strong><small>'+esc(c.name)+' <span class="catalog-status '+statusClass+'">'+status+'</span>'+provenance+'</small></span>'+retry+'<button class="secondary" onclick="editCatalogProduct(\''+p.id+'\')" title="Artikel bearbeiten">✎</button><button class="danger catalog-delete" onclick="deleteCatalogProduct(event,\''+p.id+'\',\''+c.id+'\')" title="Artikel aus dem Artikelstamm löschen">⌫</button></div>'}
async function retryProductImage(ev,id){if(ev)ev.stopPropagation();try{await api('/api/products/'+id+'/generate-image',{method:'POST',body:'{}'});await refresh();showSnack('Gemini-Bild wird neu erzeugt');watchNewProduct(id)}catch(e){showSnack(e.message)}}
function renderCatalogCategories(){const query=keyText($('catalog-search')?.value||'');const groups=new Map(appState.categories.map(c=>[c.id,[]]));for(const p of (appState.products||[])){if(query&&!keyText([p.name,p.key,...(p.aliases||[])].filter(Boolean).join(' ')).includes(query))continue;if(!groups.has(p.categoryId))groups.set(p.categoryId,[]);groups.get(p.categoryId).push(p)}const sections=appState.categories.map(c=>{const products=(groups.get(c.id)||[]).sort((a,b)=>a.name.localeCompare(b.name,'de'));if(query&&!products.length)return '';const open=query?'':' hidden';return '<div class="catalog-category"><button class="cat-choice" onclick="toggleCatalogCategory(\''+c.id+'\')"><span class="cat-icon">'+categoryIcon(c)+'</span><span class="label">'+esc(c.name)+' <small>('+products.length+' Artikel)</small></span><span>⌄</span></button><div id="catalog-group-'+c.id+'" class="catalog-group'+open+'">'+products.map(p=>catalogRow(p,c)).join('')+(query?'':'<button class="cat-choice" onclick="addCatalogProduct(\''+c.id+'\')"><span class="plus">+</span><span>Artikel in dieser Kategorie hinzufügen</span></button>')+'</div></div>'}).join('');$('catalog-list').innerHTML=sections||(query?'<div class="catalog-search-empty">Kein Artikel gefunden.</div>':'')}
function toggleCatalogCategory(id){const group=$('catalog-group-'+id);if(group)group.classList.toggle('hidden')}
function manageProducts(expandId){catalogReturnMode='catalog';show('<div class="sheet"><div class="sheet-head"><h2>Artikelstamm</h2><button class="sheet-icon-action icon-only" onclick="closeOverlay()" title="Schließen" aria-label="Schließen">×</button></div><div class="catalog-search-wrap"><input id="catalog-search" class="catalog-search" type="search" placeholder="Artikel suchen …" autocomplete="off" oninput="renderCatalogCategories()"></div>'+geminiCostHtml()+'<div id="catalog-list"></div></div>');renderCatalogCategories();if(expandId)toggleCatalogCategory(expandId)}
async function addCatalogProduct(categoryId){const name=prompt('Neuer Artikel für diese Kategorie:');if(!name)return;try{const r=await api('/api/products',{method:'POST',body:JSON.stringify({name,categoryId})});await refresh();manageProducts(categoryId);if(r.product?.imageSource==='pending'&&appState.geminiConfigured){showSnack('Artikel angelegt · individuelles Bild wird erzeugt');watchNewProduct(r.product.id)}}catch(e){showSnack(e.message)}}
async function deleteCatalogProduct(ev,id,categoryId){if(ev)ev.stopPropagation();const p=(appState.products||[]).find(x=>x.id===id);if(!p)return;if(!confirm('Artikel „'+p.name+'“ wirklich dauerhaft aus dem Artikelstamm löschen? Aktuelle bzw. zuletzt erledigte Listeneinträge bleiben als Verlauf erhalten.'))return;try{await api('/api/products/'+id,{method:'DELETE'});await refresh();if(catalogReturnMode==='list'){closeOverlay();render()}else manageProducts(categoryId);showSnack('Artikel aus dem Artikelstamm gelöscht')}catch(e){showSnack(e.message)}}
function productEditorPreviewData(){const p=appState.products.find(x=>x.id===editId)||{};return {...p,name:$('product-name')?.value||p.name,productName:$('product-name')?.value||p.name,categoryId:$('product-category')?.value||p.categoryId}}
function updateVisualPreview(){const target=$('visual-preview');if(target)target.innerHTML=productIcon(productEditorPreviewData())}
function currentProductEditorBody(){const rawValue=$('default-quantity-value')?.value?.trim()||'';const rawUnit=$('default-quantity-unit')?.value?.trim()||'';return {name:$('product-name').value,categoryId:$('product-category').value,iconHint:$('icon-hint').value,defaultQuantity:rawValue?{value:rawValue,unit:rawUnit||'Stück'}:null}}
async function regenerateProductImage(){const p=appState.products.find(x=>x.id===editId);if(!p)return;const button=$('regenerate-image-btn');const note=$('proposal-note');if(button){button.disabled=true;button.textContent='Gemini erzeugt …'}if(note){note.classList.remove('hidden');note.textContent='Gemini erzeugt jetzt ein neues individuelles Produktbild. Das kann einige Sekunden dauern.'}try{await api('/api/products/'+p.id,{method:'PATCH',body:JSON.stringify(currentProductEditorBody())});await api('/api/products/'+p.id+'/generate-image',{method:'POST',body:'{}'});watchEditedProductImage(p.id)}catch(e){if(note)note.textContent='Bildgenerierung konnte nicht gestartet werden: '+e.message;showSnack(e.message);if(button){button.disabled=false;button.textContent='Icon neu erstellen'}}}
async function watchEditedProductImage(productId){let attempts=0;const poll=async()=>{try{const next=await api('/api/state');appState=next;refreshGeminiCostDisplay();const p=(next.products||[]).find(x=>x.id===productId);const target=$('visual-preview');if(target&&p)target.innerHTML=productIcon({...productEditorPreviewData(),generatedImage:p.generatedImage,imageSource:p.imageSource,imageError:p.imageError,imageRevision:p.imageRevision});const note=$('proposal-note');const button=$('regenerate-image-btn');if(!p)return;if(p.imageSource==='gemini'){if(note){note.classList.remove('hidden');note.textContent='Neues Gemini-Icon wurde erzeugt, lokal gespeichert und ist sofort aktiv.'}if(button){button.disabled=false;button.textContent='Icon neu erstellen'}showSnack('Neues Gemini-Icon gespeichert');return}if(p.imageSource==='error'){if(note){note.classList.remove('hidden');note.textContent='Gemini-Bildfehler: '+(p.imageError||'Unbekannter Fehler')}if(button){button.disabled=false;button.textContent='Erneut versuchen'}showSnack('Bildgenerierung fehlgeschlagen');return}if(++attempts<100)setTimeout(poll,1000);else{if(note)note.textContent='Bildgenerierung dauert ungewöhnlich lange. Der Status bleibt im Artikel gespeichert.';if(button){button.disabled=false;button.textContent='Erneut versuchen'}}}catch(e){if(++attempts<100)setTimeout(poll,1200)}};setTimeout(poll,700)}
async function saveCatalogProduct(){const p=appState.products.find(x=>x.id===editId);if(!p)return;const body=currentProductEditorBody();try{await api('/api/products/'+p.id,{method:'PATCH',body:JSON.stringify(body)});const categoryId=body.categoryId;await refresh();if(catalogReturnMode==='list'){closeOverlay();render()}else manageProducts(categoryId);showSnack('Artikel gespeichert')}catch(e){showSnack(e.message)}}
async function autoReclassifyProduct(){const p=appState.products.find(x=>x.id===editId);if(!p)return;const button=$('auto-reclassify-btn');if(button){button.disabled=true;button.textContent='Gemini prüft …'}try{const response=await api('/api/products/'+p.id+'/reclassify',{method:'POST',body:'{}'});const q=response.proposal||{};if(q.displayName)$('product-name').value=q.displayName;if(q.categoryId)$('product-category').value=q.categoryId;updateVisualPreview();const note=$('proposal-note');if(note){note.classList.remove('hidden');note.textContent='Gemini-Vorschlag für Name und Kategorie geladen. Dein Icon-Hinweis bleibt unverändert. Erst mit „Änderungen speichern“ wird der Vorschlag übernommen.'}}catch(e){showSnack(e.message)}finally{if(button){button.disabled=false;button.textContent='Automatisch neu bestimmen'}}}
function fileToDataUrl(file){return new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result||''));reader.onerror=()=>reject(new Error('Bilddatei konnte nicht gelesen werden.'));reader.readAsDataURL(file)})}
function imageFromDataUrl(dataUrl){return new Promise((resolve,reject)=>{const img=new Image();img.onload=()=>resolve(img);img.onerror=()=>reject(new Error('Bilddatei konnte nicht geöffnet werden.'));img.src=dataUrl})}
function canvasToBlob(canvas,type,quality){return new Promise((resolve,reject)=>{canvas.toBlob(blob=>blob?resolve(blob):reject(new Error('Icon konnte nicht vorbereitet werden.')),type,quality)})}
async function prepareIconUpload(file){if(!file)throw new Error('Keine Bilddatei ausgewählt.');if(file.size>20*1024*1024)throw new Error('Die ausgewählte Bilddatei ist zu groß. Maximal 20 MB.');const raw=await fileToDataUrl(file);const img=await imageFromDataUrl(raw);const size=1024,canvas=document.createElement('canvas');canvas.width=size;canvas.height=size;const ctx=canvas.getContext('2d');if(!ctx)throw new Error('Bildverarbeitung wird von diesem Browser nicht unterstützt.');ctx.fillStyle='#FFFFFF';ctx.fillRect(0,0,size,size);const iw=img.naturalWidth||img.width,ih=img.naturalHeight||img.height;if(!iw||!ih)throw new Error('Bildabmessungen konnten nicht gelesen werden.');const scale=Math.min(size/iw,size/ih),w=Math.max(1,Math.round(iw*scale)),h=Math.max(1,Math.round(ih*scale)),x=Math.round((size-w)/2),y=Math.round((size-h)/2);ctx.drawImage(img,x,y,w,h);const blob=await canvasToBlob(canvas,'image/jpeg',0.92);return fileToDataUrl(blob)}
async function uploadProductIcon(ev,id){const input=ev?.target,file=input?.files?.[0];if(!file)return;const note=$('proposal-note'),status=$('editor-icon-status');try{if(note){note.classList.remove('hidden');note.textContent='Eigenes Icon wird vorbereitet und gespeichert …'}const dataUrl=await prepareIconUpload(file);const result=await api('/api/products/'+id+'/upload-image',{method:'POST',body:JSON.stringify({dataUrl})});appState=result.state||await api('/api/state');const p=(appState.products||[]).find(x=>x.id===id);const preview=$('visual-preview');if(preview&&p)preview.innerHTML=productIcon(p);if(status){status.textContent='Bearbeitet';status.className='editor-status processed'}if(note)note.textContent='Eigenes Icon wurde gespeichert. Gemini wurde dafür nicht verwendet.';showSnack('Eigenes Icon gespeichert')}catch(e){if(note){note.classList.remove('hidden');note.textContent='Eigenes Icon konnte nicht gespeichert werden: '+e.message}showSnack(e.message)}finally{if(input)input.value=''}}
async function uploadCategoryIcon(ev,id){const input=ev?.target,file=input?.files?.[0];if(!file)return;const note=$('category-image-note');try{if(note){note.classList.remove('hidden');note.textContent='Eigenes Kategorie-Icon wird vorbereitet und gespeichert …'}const dataUrl=await prepareIconUpload(file);const result=await api('/api/categories/'+id+'/upload-image',{method:'POST',body:JSON.stringify({dataUrl})});appState=result.state||await api('/api/state');const c=(appState.categories||[]).find(x=>x.id===id);const preview=$('category-preview');if(preview&&c)preview.innerHTML=categoryIcon(c);if(note)note.textContent='Eigenes Kategorie-Icon wurde gespeichert. Gemini wurde dafür nicht verwendet.';showSnack('Eigenes Kategorie-Icon gespeichert')}catch(e){if(note){note.classList.remove('hidden');note.textContent='Eigenes Kategorie-Icon konnte nicht gespeichert werden: '+e.message}showSnack(e.message)}finally{if(input)input.value=''}}
function editCatalogProduct(id,returnMode='catalog'){const p=appState.products.find(x=>x.id===id);if(!p){showSnack('Artikel ist nicht mehr im Artikelstamm');return}catalogReturnMode=returnMode;editId=id;const categoryOptions=appState.categories.map(c=>'<option value="'+c.id+'" '+(c.id===p.categoryId?'selected':'')+'>'+esc(c.name)+'</option>').join('');const back=returnMode==='list'?'<button class="secondary editor-back" onclick="closeOverlay()">Zur Einkaufsliste</button>':'<button class="secondary editor-back" onclick="manageProducts(\''+p.categoryId+'\')">Zurück</button>';const status=p.iconEditStatus==='processing'?'In Bearbeitung':p.iconEditStatus==='processed'?'Bearbeitet':'Unbearbeitet';const statusClass=p.iconEditStatus==='processing'?'processing':p.iconEditStatus==='processed'?'processed':'unprocessed';const inheritedNote=p.imageSource==='inherited'&&p.imageInheritedFromName?'<span class="catalog-provenance inherited-source-note">Bild übernommen aus „'+esc(p.imageInheritedFromName)+'“</span>':'';const dq=p.defaultQuantity||null;const dqValue=dq&&dq.value!=null?String(dq.value):'';const dqUnit=dq?String(dq.unit||''):'';show('<div class="sheet"><div class="sheet-head"><h2>Artikelstamm bearbeiten</h2><button class="sheet-icon-action save" onclick="saveCatalogProduct()" title="Speichern" aria-label="Speichern">'+editorActionIcon('save')+'<span class="action-label">Speichern</span></button></div><div class="editor-status-row"><span id="editor-icon-status" class="editor-status '+statusClass+'">'+esc(status)+'</span>'+inheritedNote+'</div><div class="visual-editor"><div class="visual-preview-card"><div id="visual-preview">'+productIcon(p)+'</div></div><div class="visual-fields"><label>Kategorie<select id="product-category" onchange="updateVisualPreview()">'+categoryOptions+'</select></label><label>Artikelname<input id="product-name" value="'+esc(p.name)+'" oninput="updateVisualPreview()"></label><div class="row"><label>Standardmenge (optional)<input id="default-quantity-value" type="number" min="0.01" step="any" inputmode="decimal" value="'+esc(dqValue)+'" placeholder="z. B. 1"></label><label>Standardeinheit<input id="default-quantity-unit" value="'+esc(dqUnit)+'" placeholder="z. B. Nachfüllbeutel"></label></div><label>Icon-Hinweis (optional)<input id="icon-hint" maxlength="160" value="'+esc(p.iconHint||'')+'" placeholder="z. B. frischer Rosmarin"></label></div></div>'+geminiCostHtml()+'<div id="proposal-note" class="proposal-note hidden"></div><input id="product-icon-upload" type="file" accept="image/*" hidden onchange="uploadProductIcon(event,\''+p.id+'\')"><div class="editor-action-grid"><button class="editor-action-card" onclick="$(\'product-icon-upload\').click()"><span class="action-glyph">▣</span><span>Eigenes Icon</span></button><button class="editor-action-card" id="regenerate-image-btn" onclick="regenerateProductImage()"><span class="action-glyph">✦</span><span>Icon neu erstellen</span></button><button class="editor-action-card" id="auto-reclassify-btn" onclick="autoReclassifyProduct()"><span class="action-glyph">↻</span><span>Neu bestimmen</span></button></div><div class="danger-zone compact-danger"><button class="danger" onclick="deleteCatalogProduct(null,\''+p.id+'\',\''+p.categoryId+'\')">Artikel aus Stamm löschen</button></div>'+back+'</div>');updateVisualPreview()}
async function moveCategory(id,direction){await api('/api/categories/reorder',{method:'POST',body:JSON.stringify({id,direction})});closeOverlay();await refresh();manageCategories()}
async function saveCategorySettings(id){const c=appState.categories.find(x=>x.id===id);if(!c)return;try{await api('/api/categories/'+id,{method:'PATCH',body:JSON.stringify({name:$('category-name').value,description:$('category-description').value})});await refresh();manageCategories();showSnack('Kategorie gespeichert')}catch(e){showSnack(e.message)}}
function editCategorySettings(id){const c=appState.categories.find(x=>x.id===id);if(!c)return;show('<div class="sheet"><div class="sheet-head"><h2>Kategorie bearbeiten</h2><button class="sheet-icon-action save" onclick="saveCategorySettings(\''+id+'\')" title="Speichern" aria-label="Speichern">'+editorActionIcon('save')+'<span class="action-label">Speichern</span></button></div><div class="category-editor-preview" id="category-preview">'+categoryIcon(c)+'</div><label>Kategoriename<input id="category-name" value="'+esc(c.name)+'"></label><label>Beschreibung für automatische Zuordnung<textarea id="category-description" rows="4" placeholder="Welche Artikel gehören hier hinein?">'+esc(c.description||'')+'</textarea></label>'+geminiCostHtml()+'<div id="category-image-note" class="proposal-note hidden"></div><input id="category-icon-upload" type="file" accept="image/*" hidden onchange="uploadCategoryIcon(event,\''+id+'\')"><div class="editor-action-grid two"><button class="editor-action-card" onclick="$(\'category-icon-upload\').click()"><span class="action-glyph">▣</span><span>Eigenes Icon</span></button><button class="editor-action-card" id="category-image-btn" onclick="regenerateCategoryImage(\''+id+'\')"><span class="action-glyph">✦</span><span>Icon erzeugen</span></button></div><button class="secondary editor-back" onclick="manageCategories()">Zurück</button></div>')}
async function regenerateCategoryImage(id){const c=appState.categories.find(x=>x.id===id);if(!c)return;const button=$('category-image-btn'),note=$('category-image-note');if(button){button.disabled=true;button.textContent='Gemini erzeugt …'}if(note){note.classList.remove('hidden');note.textContent='Kategorie wird gespeichert und anschließend ein neues Icon erzeugt.'}try{await api('/api/categories/'+id,{method:'PATCH',body:JSON.stringify({name:$('category-name').value,description:$('category-description').value})});const before=c.imageRevision||0;await api('/api/categories/'+id+'/generate-image',{method:'POST',body:'{}'});watchCategoryImage(id,before)}catch(e){if(note)note.textContent='Kategorie-Icon konnte nicht gestartet werden: '+e.message;if(button){button.disabled=false;button.textContent='Kategorie-Icon erzeugen'}showSnack(e.message)}}
async function watchCategoryImage(id,before){let attempts=0;const poll=async()=>{try{const next=await api('/api/state');appState=next;refreshGeminiCostDisplay();const c=(next.categories||[]).find(x=>x.id===id);const preview=$('category-preview'),note=$('category-image-note'),button=$('category-image-btn');if(preview&&c)preview.innerHTML=categoryIcon(c);if(!c)return;if(c.imageSource==='gemini'&&Number(c.imageRevision||0)!==Number(before||0)){if(note){note.classList.remove('hidden');note.textContent='Neues Kategorie-Icon wurde erzeugt und gespeichert.'}if(button){button.disabled=false;button.textContent='Kategorie-Icon neu erzeugen'}showSnack('Kategorie-Icon gespeichert');return}if(c.imageSource==='error'){if(note){note.classList.remove('hidden');note.textContent='Gemini-Bildfehler: '+(c.imageError||'Unbekannter Fehler')}if(button){button.disabled=false;button.textContent='Erneut versuchen'}return}if(++attempts<100)setTimeout(poll,1000);else if(button){button.disabled=false;button.textContent='Erneut versuchen'}}catch(e){if(++attempts<100)setTimeout(poll,1200)}};setTimeout(poll,700)}
async function renameCategory(id){const c=appState.categories.find(x=>x.id===id);const name=prompt('Kategorie umbenennen:',c.name);if(!name)return;await api('/api/categories/'+id,{method:'PATCH',body:JSON.stringify({name})});closeOverlay();await refresh();manageCategories()}
async function deleteCategory(id){const options=appState.categories.filter(c=>c.id!==id).map(c=>c.name).join(', ');const targetName=prompt('Artikel verschieben nach ('+options+'):', 'Sonstiges');const target=appState.categories.find(c=>c.name.toLowerCase()===String(targetName||'').toLowerCase());if(!target||target.id===id){showSnack('Bitte eine gültige Zielkategorie wählen');return}await api('/api/categories/'+id,{method:'DELETE',body:JSON.stringify({moveTo:target.id})});closeOverlay();await refresh();manageCategories()}
function updateNav(){const listTargets=['list-btn','desktop-list-tab'];const recentTargets=['recent-btn','desktop-recent-tab'];[...listTargets,...recentTargets].forEach(id=>$(id)&&$(id).classList.remove('active'));(view==='recent'?recentTargets:listTargets).forEach(id=>$(id)&&$(id).classList.add('active'))}
function showList(){view='list';cancelSelection()}
function showRecent(){view='recent';cancelSelection()}
function toggleSection(id){const group=document.querySelector('[data-group="'+id+'"]');if(!group)return;group.classList.toggle('hidden');if(group.classList.contains('hidden'))collapsedCategories.add(id);else collapsedCategories.delete(id)}
function visibleStateSignature(value){const state=value||{};return JSON.stringify({activeListId:state.activeListId,syncListId:state.syncListId,lists:state.lists,categories:state.categories,entries:state.entries,recent:state.recent,products:state.products,undoAvailable:state.undoAvailable,geminiStatus:state.geminiStatus,imageStatus:state.imageStatus})}
async function backgroundRefresh(){if(autoRefreshBusy||offlineSyncBusy)return;autoRefreshBusy=true;try{await initOfflineStorage();if(offlineQueue.length)await syncPending();if(serverReachable===false&&offlineQueue.length)return;const next=await api('/api/state');serverReachable=true;await offlineSet(OFFLINE_BASE_KEY,deepClone(next));const materialized=materializePending(next);const needsPaint=visibleStateSignature(materialized)!==visibleStateSignature(appState);appState=materialized;await saveLocalState();if(needsPaint)render();else updateOfflineStatus()}catch(error){if(error.isNetwork){serverReachable=false;updateOfflineStatus()}}finally{autoRefreshBusy=false}}
function searchCurrentList(){show('<div class="sheet"><h2>Liste durchsuchen</h2><p class="status-line">Suche in den aktuell offenen Artikeln.</p><input id="list-search" class="catalog-search" type="search" placeholder="Artikel, Größe oder Notiz suchen …" autocomplete="off" oninput="renderListSearchResults()"><div id="list-search-results" class="list-search-results"></div><button class="secondary" onclick="manageLists()">Zurück</button></div>');renderListSearchResults();setTimeout(()=>$('list-search')?.focus(),80)}
function renderListSearchResults(){const target=$('list-search-results');if(!target)return;const query=keyText($('list-search')?.value||'');if(!query){target.innerHTML='<div class="list-search-empty">Suchbegriff eingeben.</div>';return}const results=(appState.entries||[]).filter(e=>keyText([e.productName,e.productDetail,e.note,e.quantity?.value,e.quantity?.unit,categoryName(e.categoryId)].filter(Boolean).join(' ')).includes(query));target.innerHTML=results.length?results.map(e=>'<button class="list-search-result" onclick="jumpToListEntry(\''+e.id+'\',\''+e.categoryId+'\')"><span class="item-icon">'+productIcon(e)+'</span><span class="label"><strong>'+esc(e.productName)+'</strong><small>'+esc(categoryName(e.categoryId))+(e.productDetail?' · '+esc(e.productDetail):'')+(e.note?' · '+esc(e.note):'')+'</small></span><span>›</span></button>').join(''):'<div class="list-search-empty">Kein offener Artikel gefunden.</div>'}
function jumpToListEntry(id,categoryId){view='list';collapsedCategories.delete(categoryId);closeOverlay();render();requestAnimationFrame(()=>{const target=document.querySelector('[data-id="'+CSS.escape(id)+'"]');if(target)target.scrollIntoView({behavior:'smooth',block:'center'})})}
function scrollToCategory(id){const target=$('section-'+id);if(target)target.scrollIntoView({behavior:'smooth',block:'start'})}
function pickList(){if(suppressTitleClick){suppressTitleClick=false;return}const choices=appState.lists.map(list=>'<button class="cat-choice '+(list.id===appState.activeListId?'selected':'')+'" onclick="switchList(\''+list.id+'\')"><span class="list-color" style="background:'+list.color+'"></span><span>'+esc(list.name)+'</span><small>'+list.itemCount+' Artikel</small></button>').join('');show('<div class="sheet"><h2>Liste auswählen</h2>'+choices+'<button class="primary" onclick="listForm()">+ Neue Liste erstellen</button><button class="secondary" onclick="closeOverlay()">Abbrechen</button></div>')}
async function switchList(id){try{await api('/api/lists/switch',{method:'POST',body:JSON.stringify({listId:id})});view='list';selectionMode=false;selected.clear();document.body.classList.remove('selection-active');closeOverlay();await refresh()}catch(e){showSnack(e.message)}}
function listTouchStart(ev){listTouchX=ev.clientX}
function listTouchEnd(ev){if(listTouchX===null)return;const dx=ev.clientX-listTouchX;listTouchX=null;if(Math.abs(dx)<70)return;const lists=appState.lists.slice().sort((a,b)=>a.sort-b.sort);const index=lists.findIndex(l=>l.id===appState.activeListId);const next=lists[index+(dx<0?1:-1)];if(next){suppressTitleClick=true;switchList(next.id)}}
async function readd(ev,id){ev.stopPropagation();await initOfflineStorage();const item=(appState.recent||[]).find(x=>x.id===id);if(!item)return;if((appState.entries||[]).some(entry=>clientEntryKey(entry)===clientEntryKey(item))){showSnack('Artikel steht bereits auf der Liste');return}const operation={opId:offlineId(),type:'restore',listId:appState.activeListId,entryId:id,entrySnapshot:deepClone(item),baseUpdatedAt:appState.updatedAt||null,createdAt:new Date().toISOString()};offlineQueue.push(operation);applyClientOperation(appState,operation);await persistOfflineView();view='list';render();void syncPending()}
async function watchGemini(itemName){let attempts=0;const poll=async()=>{try{const next=await api('/api/state');const status=next.geminiStatus||{};if(status.item===itemName&&['success','error','not_configured'].includes(status.state)){appState=next;render();return}if(++attempts<50)setTimeout(poll,1000)}catch{if(++attempts<50)setTimeout(poll,1000)}};setTimeout(poll,500)}
async function watchNewProduct(productId){let attempts=0,lastSignature='';const poll=async()=>{try{const next=await api('/api/state');const p=(next.products||[]).find(x=>x.id===productId);const signature=p?JSON.stringify([p.imageSource,p.generatedImage,p.imageRevision,p.imageError,p.iconEditStatus]):'missing';appState=next;if(signature!==lastSignature){lastSignature=signature;render()}if(!p||(p.iconEditStatus!=='processing'&&['gemini','error','catalog'].includes(p.imageSource))){if(p?.imageSource==='gemini')showSnack('Neues Produktbild gespeichert');else if(p?.imageSource==='error')showSnack('Bildgenerierung fehlgeschlagen – im Artikelstamm kann erneut versucht werden');return}if(++attempts<90)setTimeout(poll,1000)}catch{if(++attempts<90)setTimeout(poll,1000)}};setTimeout(poll,700)}
async function add(){const input=$('input').value.trim();if(!input)return;$('input').value='';$('input').focus();try{const r=await api('/api/items',{method:'POST',body:JSON.stringify({input})});await refresh();if(r.imagePending)showSnack(r.geminiReady?'Artikel hinzugefügt · individuelles Bild wird erzeugt':'Artikel hinzugefügt · Gemini-Bild wartet auf Konfiguration');else showSnack('Artikel hinzugefügt');if(r.imagePending&&r.geminiReady)watchNewProduct(r.entry.productId);else if(r.classificationPending)watchGemini(r.entry.productName)}catch(e){showSnack(e.message)}}
async function checkItem(ev,id){ev.stopPropagation();const cardEl=document.querySelector('.card[data-id="'+id+'"]');if(cardEl){cardEl.classList.add('checking');await new Promise(resolve=>setTimeout(resolve,120))}await initOfflineStorage();const entry=(appState.entries||[]).find(item=>item.id===id);if(!entry)return;const operation={opId:offlineId(),type:'check',listId:appState.activeListId,entryId:id,entrySnapshot:deepClone(entry),baseUpdatedAt:appState.updatedAt||null,createdAt:new Date().toISOString()};offlineQueue.push(operation);applyClientOperation(appState,operation);selected.delete(id);await persistOfflineView();render();void syncPending()}
async function deleteItem(id){if(selectionMode){selected.has(id)?selected.delete(id):selected.add(id);render();return}await api('/api/items/'+id,{method:'DELETE'});await refresh();showSnack('Artikel gelöscht')}
function gestureStart(ev,id){holdTriggered=false;gestureMoved=false;swipeStart={x:ev.clientX,y:ev.clientY,id,pointerId:ev.pointerId};holdStart(id)}
function gestureMove(ev,id){if(!swipeStart||swipeStart.id!==id)return;const dx=ev.clientX-swipeStart.x,dy=ev.clientY-swipeStart.y;if(Math.hypot(dx,dy)>10){gestureMoved=true;holdEnd()}}
function gestureCancel(){holdEnd();swipeStart=null;gestureMoved=false}
function gestureEnd(ev,id){holdEnd();if(holdTriggered){holdTriggered=false;swipeStart=null;gestureMoved=false;if(ev.pointerType==='touch')ev.preventDefault();return}if(!swipeStart)return;const dx=ev.clientX-swipeStart.x;const dy=ev.clientY-swipeStart.y;const moved=gestureMoved||Math.hypot(dx,dy)>10;swipeStart=null;gestureMoved=false;if(Math.abs(dx)>70&&Math.abs(dx)>Math.abs(dy)){lastTap={id:'',time:0};if(dx<0)deleteItem(id);else cardActions(id);return}if(moved){lastTap={id:'',time:0};return}if(ev.pointerType==='touch')ev.preventDefault();cardClick(ev,id)}
function cardActions(id){const e=(appState.entries||[]).find(x=>x.id===id);const master=e?.productExists?'<button class="cat-choice" onclick="editCatalogProduct(\''+e.productId+'\',\'list\')"><span>⚙</span><span>Artikelstamm bearbeiten</span></button>':'';show('<div class="sheet"><h2>Artikel</h2><button class="cat-choice" onclick="closeOverlay();openEdit(\''+id+'\')"><span>✎</span><span>Listeneintrag bearbeiten</span></button>'+master+'<button class="cat-choice" onclick="moveItemPicker(\''+id+'\')"><span>📁</span><span>In eine andere Liste verschieben</span></button><button class="secondary" onclick="closeOverlay()">Abbrechen</button></div>')}
function moveItemPicker(id){const choices=appState.lists.filter(list=>list.id!==appState.activeListId).map(list=>'<button class="cat-choice" onclick="moveItem(\''+id+'\',\''+list.id+'\')"><span class="list-color" style="background:'+list.color+'"></span><span>'+esc(list.name)+'</span></button>').join('');show('<div class="sheet"><h2>In andere Liste verschieben</h2>'+(choices||'<p class="status-line">Keine andere Liste vorhanden.</p>')+'<button class="secondary" onclick="closeOverlay()">Abbrechen</button></div>')}
async function moveItem(id,listId){try{await api('/api/items/'+id+'/move-list',{method:'POST',body:JSON.stringify({listId})});closeOverlay();await refresh();showSnack('Artikel in andere Liste verschoben')}catch(e){showSnack(e.message)}}
function downloadBackup(){window.location.href=new URL('api/backup',document.baseURI).href;showSnack('Sicherung wird erstellt')}
function restoreBackup(){$('restore-file').click()}
async function restoreFile(ev){const file=ev.target.files?.[0];if(!file)return;try{const body=JSON.parse(await file.text());appState=await api('/api/restore',{method:'POST',body:JSON.stringify(body)});view='list';render();showSnack('Sicherung wiederhergestellt')}catch(e){showSnack('Sicherung konnte nicht gelesen werden: '+e.message)}ev.target.value=''}
function holdStart(id){clearTimeout(pressTimer);pressTimer=setTimeout(()=>{if(gestureMoved||!swipeStart||swipeStart.id!==id)return;holdTriggered=true;window.getSelection?.().removeAllRanges();openEdit(id)},800)}function holdEnd(){clearTimeout(pressTimer);pressTimer=null}
function editorActionIcon(kind){if(kind==='save')return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m5 12 4 4L19 6"/></svg>';return '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/></svg>'}
function openEdit(id,categoryOverride){editId=id;const e=appState.entries.find(x=>x.id===id);if(!e)return;if(categoryOverride===undefined)editCategory=e.categoryId;const cat=appState.categories.find(c=>c.id===editCategory)||{id:'other',name:'Sonstiges'};const master=e.productExists?'<button class="sheet-icon-action" onclick="saveEditAndOpenMaster(\''+e.productId+'\')" title="Artikelstamm bearbeiten" aria-label="Artikelstamm bearbeiten">'+editorActionIcon('master')+'<span class="action-label">Artikelstamm</span></button>':'';show('<div class="sheet"><div class="sheet-head"><h2>'+esc(e.productName)+' bearbeiten</h2><div class="sheet-head-actions">'+master+'<button class="sheet-icon-action save" onclick="saveEdit()" title="Speichern" aria-label="Speichern">'+editorActionIcon('save')+'<span class="action-label">Speichern</span></button></div></div><label>Kategorie</label><button class="cat-choice category-first" onclick="categoryPicker(\'edit\')">'+categoryIcon(cat)+' <span>'+esc(cat.name)+'</span><span class="choice-arrow">›</span></button><label>Name</label><input id="edit-name" value="'+esc(e.productName)+'"><label>Anzahl / Einheit</label><div class="row"><input id="edit-qty" type="number" step="any" value="'+(e.quantity?.value??'')+'"><input id="edit-unit" value="'+esc(firstUpper(e.quantity?.unit||'stück'))+'"></div><label>Produktgröße / Variante (optional)</label><input id="edit-product-detail" value="'+esc(e.productDetail||'')+'" placeholder="z. B. 1 Liter oder 500 g"><label>Notiz (optional)</label><textarea id="edit-note" rows="2" placeholder="z. B. vor dem nächsten Flammkuchen">'+esc(e.note||'')+'</textarea></div>')}
function currentEntryEditorBody(){return {name:$('edit-name').value,quantity:$('edit-qty').value,unit:String($('edit-unit').value||'stück').trim().toLowerCase(),productDetail:String($('edit-product-detail').value||'').trim(),note:String($('edit-note').value||'').trim(),categoryId:editCategory}}

async function saveEdit(){try{await api('/api/items/'+editId,{method:'PATCH',body:JSON.stringify(currentEntryEditorBody())});closeOverlay();await refresh();showSnack('Artikel gespeichert')}catch(e){showSnack(e.message)}}
async function saveEditAndOpenMaster(productId){try{const saved=await api('/api/items/'+editId,{method:'PATCH',body:JSON.stringify(currentEntryEditorBody())});await refresh();editCatalogProduct(saved.entry?.productId||productId,'list');showSnack('Listeneintrag gespeichert')}catch(e){showSnack(e.message)}}

$('add-btn').onclick=add;$('input').addEventListener('keydown',e=>{if(e.key==='Enter')add()});$('select-btn').onclick=()=>selectionMode?cancelSelection():enterSelection();$('manage-btn').onclick=manageLists;$('sidebar-manage').onclick=manageLists;$('category-shortcut').onclick=manageCategories;$('category-nav').onclick=manageCategories;$('list-btn').onclick=showList;$('recent-btn').onclick=showRecent;$('restore-file').addEventListener('change',restoreFile);
async function boot(){void registerOfflineWorker();const offlineInit=initOfflineStorage();void (async()=>{await offlineInit;const cached=await offlineGet(OFFLINE_CACHE_KEY);if(cached&&serverReachable!==true){appState=cached;render();updateOfflineStatus()}if(offlineQueue.length)void syncPending()})();try{await refresh()}catch(error){showSnack(error.message||'Einkaufsliste konnte nicht geladen werden')}setInterval(backgroundRefresh,5000)}
if('serviceWorker'in navigator){navigator.serviceWorker.addEventListener('controllerchange',()=>{offlineWorkerReady=true;updateOfflineStatus();scheduleOfflineImageWarmup()});navigator.serviceWorker.addEventListener('message',event=>{if(event.data?.type==='offline-images-ready'){offlineAssetsReady=true;updateOfflineStatus()}})}
window.addEventListener('offline',()=>{serverReachable=false;updateOfflineStatus()});window.addEventListener('online',()=>{void syncPending();void backgroundRefresh();scheduleOfflineImageWarmup()});boot();
</script></body></html>`;
}

const server = http.createServer(async (req, res) => {
  try {
    const url = new URL(req.url, `http://${req.headers.host || "localhost"}`);
    if (url.pathname.startsWith("/api/")) return await api(req, res, url.pathname, url.searchParams);
    const staticFiles = {
      "/apple-touch-icon.png": ["apple-touch-icon.png", "image/png"],
      "/apple-touch-icon-precomposed.png": ["apple-touch-icon.png", "image/png"],
      "/favicon-64.png": ["favicon-64.png", "image/png"],
      "/icon-192.png": ["icon-192.png", "image/png"],
      "/icon-512.png": ["icon-512.png", "image/png"],
      "/icon-1024.png": ["icon-1024.png", "image/png"],
      "/manifest.webmanifest": ["manifest.webmanifest", "application/manifest+json; charset=utf-8"],
      "/sw.js": ["sw.js", "application/javascript; charset=utf-8"],
    };
    if (req.method === "GET" && staticFiles[url.pathname]) {
      const [fileName, contentType] = staticFiles[url.pathname];
      const body = fs.readFileSync(path.join(__dirname, "assets", fileName));
      const cacheControl = ["sw.js", "manifest.webmanifest", "apple-touch-icon.png", "favicon-64.png"].includes(fileName) ? "no-cache, must-revalidate" : "public, max-age=86400";
      res.writeHead(200, { "content-type": contentType, "cache-control": cacheControl });
      return res.end(body);
    }
    if (req.method === "GET" && url.pathname.startsWith("/product-images/")) {
      const fileName = path.basename(url.pathname);
      if (!/^[a-zA-Z0-9_-]+\.(webp|png|jpg)$/.test(fileName)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      const filePath = path.join(__dirname, "assets", "product-images", fileName);
      if (!fs.existsSync(filePath)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      res.writeHead(200, { "content-type": fileName.endsWith(".png") ? "image/png" : fileName.endsWith(".jpg") ? "image/jpeg" : "image/webp", "cache-control": "public, max-age=604800" });
      return fs.createReadStream(filePath).pipe(res);
    }
    if (req.method === "GET" && url.pathname.startsWith("/category-images/")) {
      const fileName = path.basename(url.pathname);
      if (!/^[a-zA-Z0-9_-]+\.webp$/.test(fileName)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      const filePath = path.join(__dirname, "assets", "category-images", fileName);
      if (!fs.existsSync(filePath)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      res.writeHead(200, { "content-type": "image/webp", "cache-control": "public, max-age=604800" });
      return fs.createReadStream(filePath).pipe(res);
    }
    if (req.method === "GET" && url.pathname.startsWith("/generated-product-images/")) {
      const fileName = path.basename(url.pathname);
      if (!/^[a-zA-Z0-9_-]+\.(png|jpg|jpeg|webp)$/i.test(fileName)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      const filePath = path.join(GENERATED_IMAGE_DIR, fileName);
      if (!fs.existsSync(filePath)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      const ext = path.extname(fileName).toLowerCase();
      const types = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };
      res.writeHead(200, { "content-type": types[ext] || 'application/octet-stream', "cache-control": "public, max-age=31536000, immutable" });
      return fs.createReadStream(filePath).pipe(res);
    }
    if (req.method === "GET" && url.pathname.startsWith("/generated-category-images/")) {
      const fileName = path.basename(url.pathname);
      if (!/^[a-zA-Z0-9_-]+\.(png|jpg|jpeg|webp)$/i.test(fileName)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      const filePath = path.join(GENERATED_CATEGORY_IMAGE_DIR, fileName);
      if (!fs.existsSync(filePath)) { res.writeHead(404); return res.end("Nicht gefunden"); }
      const ext = path.extname(fileName).toLowerCase();
      const types = { '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.webp': 'image/webp' };
      res.writeHead(200, { "content-type": types[ext] || 'application/octet-stream', "cache-control": "public, max-age=31536000, immutable" });
      return fs.createReadStream(filePath).pipe(res);
    }
    if (req.method === "GET" && (url.pathname === "/" || url.pathname === "/index.html")) { res.writeHead(200, { "content-type": "text/html; charset=utf-8" }); return res.end(page()); }
    res.writeHead(404); res.end("Nicht gefunden");
  } catch (error) { json(res, 500, { error: error.message }); }
});

if (require.main === module) {
  appleRemindersSync = createAppleRemindersSync({ getOptions: appOptions, onItems: importAppleReminders, log: (message) => console.error(message) });
  localCaldavSync = createLocalCaldavSync({ getOptions: appOptions, onItems: importLocalCaldavReminders, root: path.join(DATA_DIR, "caldav", "collections"), log: (message) => console.error(message) });
  startDailyBackup();
  server.listen(PORT, process.env.APP_BIND || "0.0.0.0", () => {
    console.log(`Einkaufsliste v${VERSION} läuft auf Port ${PORT}.`);
    appleRemindersSync.start();
    localCaldavSync.start();
    try { repairAllStoreSpecificImageReuse(); } catch (error) { console.error(`Bildübernahme für Ladenartikel konnte nicht geprüft werden: ${error.message}`); }
    setTimeout(() => resumePendingProductImages().catch((error) => console.error(`Ausstehende Gemini-Bilder konnten nicht fortgesetzt werden: ${error.message}`)), 1200);
  });
}
module.exports = { server, initialState, migrateState, loadState, latestValidBackup, createPreMigrationBackup, createRestoreSafetyBackup, backupStatus, addEntry, quantityFromRequest, normalizeDefaultQuantity, effectiveQuantityForProduct, learnedCategoryForName, compactProductKey, needsGeminiClassification, publicState, page, requestGeminiProductImage, normalizeImageApiUsage, calculateGeminiImageCostUsd, detectGeneratedImageExtension , decodeUploadedIcon, saveUploadedProductImage, saveUploadedCategoryImage, stripMeyerhofTag, stripReweTag, isReweCategoryName, reweCategoryForList, ensureReweCategoryForList, extractRetailerTag, isRetailerCategoryName, retailerCategoryForList, prepareParsedForList, parseSpokenFirmaInput, categorySuffixMatch, productKeyForCategory, prepareParsedProductDetail, migrateEntryNote, migrateEntryProductDetail, entryDuplicateKey, friendlyProductName, processCreatedProduct, resumePendingProductImages, ordinaryProcessedProductForName, processedProductForName, copyProcessedImageToProduct, processedVariantForProduct, propagateProcessedImageToVariants, ensureProductImageOnUse, repairStoreSpecificImageReuse, repairAllStoreSpecificImageReuse, specialBaseNameForProduct, shortcutItemInput, shortcutResponse };
