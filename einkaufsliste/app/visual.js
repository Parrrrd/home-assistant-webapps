const { normalizeText, firstUpper } = require('./core');

const VISUAL_BASES = [
  ['loose','Lose / unverpackt'],['carton','Karton'],['can','Dose'],['bottle','Flasche'],['squeeze','Squeeze-Flasche'],
  ['jar','Glas'],['bag','Beutel / Tüte'],['frozen_bag','TK-Beutel'],['cup','Becher'],['pouch','Beutel-Packung'],
  ['tray','Schale'],['box','Schachtel / Box'],['tube','Tube'],['roll','Rolle'],['bar','Riegel'],['paper','Papier / flach'],['bundle','Bund / Bündel']
].map(([id,label])=>({id,label}));

const VISUAL_MOTIFS = [
  ['generic','Allgemein'],['apple','Apfel'],['banana','Banane'],['berries','Beeren'],['citrus','Zitrus'],['grape','Trauben'],['pear','Birne'],['fruit','Obst allgemein'],
  ['tomato','Tomate'],['carrot','Möhre'],['potato','Kartoffel'],['cucumber','Gurke'],['pepper','Paprika'],['broccoli','Brokkoli'],['cauliflower','Blumenkohl'],['leaf','Blatt / Salat'],['onion','Zwiebel'],['garlic','Knoblauch'],['mushroom','Pilz'],['corn','Mais'],
  ['oat','Hafer'],['wheat','Getreide / Mehl'],['rice','Reis'],['pasta','Nudeln'],['bread','Brot'],['baking','Backen'],['sugar','Zucker'],
  ['milk','Milch'],['yogurt','Joghurt'],['butter','Butter'],['cheese','Käse'],['egg','Ei'],
  ['meat','Fleisch'],['chicken','Hähnchen'],['sausage','Wurst'],['fish','Fisch'],['veggie','Vegetarisch / Vegan'],['tofu','Tofu'],['beans','Hülsenfrüchte'],
  ['water','Wasser'],['juice','Saft'],['cola','Cola / Limo'],['coffee','Kaffee'],['tea','Tee'],['energy','Energy'],
  ['sauce','Sauce'],['oil','Öl'],['spread','Aufstrich'],['sweet','Süßigkeit'],['chocolate','Schokolade'],['cookie','Keks'],['chips','Chips'],['icecream','Eis'],['icecube','Eiswürfel'],
  ['cleaner','Reiniger'],['dish','Spülen'],['laundry','Wäsche'],['paper','Papierwaren'],['trash','Müllbeutel'],['hair','Haarpflege'],['bodycare','Körperpflege'],['tooth','Zahnpflege'],['baby','Baby / Windeln'],['hygiene','Hygiene'],['stationery','Schreibwaren'],['tape','Klebeband'],
  ['protein','Protein'],['frozen','Tiefkühl'],['snack','Snack']
].map(([id,label])=>({id,label}));

const BASE_IDS = new Set(VISUAL_BASES.map(v=>v.id));
const MOTIF_IDS = new Set(VISUAL_MOTIFS.map(v=>v.id));

const motifRules = [
  ['banana',['banane']],['apple',['apfel']],['berries',['heidelbeere','blaubeere','erdbeere','himbeere','brombeere','beere']],['citrus',['orange','zitrone','limette','mandarine','clementine']],['grape',['traube']],['pear',['birne']],['fruit',['mango','ananas','kiwi','pfirsich','nektarine','pflaume','aprikose','kaki','maracuja','passionsfrucht','melone','granatapfel','feige']],
  ['tomato',['tomate','ketchup']],['carrot',['mohre','moehre','karotte']],['potato',['kartoffel','pommes']],['cucumber',['gurke']],['pepper',['paprika']],['broccoli',['brokkoli']],['cauliflower',['blumenkohl']],['leaf',['salat','spinat','rucola','ruccola','krauter','kräuter']],['onion',['zwiebel']],['garlic',['knoblauch']],['mushroom',['champignon','pilz']],['corn',['mais']],
  ['oat',['hafer']],['wheat',['mehl','weizen','dinkel','roggen','getreide']],['rice',['reis']],['pasta',['nudel','spaghetti','penne','fusilli','tortellini','gnocchi','maultasche']],['bread',['brot','toast','baguette','brotchen','broetchen','croissant','brezel']],['baking',['backpulver','hefe','vanille']],['sugar',['zucker','stevia']],
  ['milk',['milch','sahne','schmand']],['yogurt',['joghurt','jogurt','skyr','quark','pudding']],['butter',['butter']],['cheese',['kase','kaese','gouda','mozzarella','feta','parmesan']],['egg',['eier']],
  ['chicken',['hahnchen','haehnchen','huhnchen','huehnchen']],['sausage',['wurst','salami','schinken','aufschnitt','bacon']],['meat',['fleisch','steak','hack']],['fish',['fisch','thunfisch']],['tofu',['tofu']],['veggie',['vegan','vegetar','veggie','falafel']],['beans',['bohne','linse','kichererbse','erbse','hummus']],
  ['cola',['cola','fanta','sprite','limonade','limo']],['juice',['saft','schorle']],['water',['wasser']],['coffee',['kaffee']],['tea',['tee']],['energy',['energy']],
  ['oil',['olivenol','olivenoel',' öl',' oel','essig']],['sauce',['sauce','sose','soße','ketchup','senf','mayonnaise','mayo','pesto']],['spread',['nutella','honig','aufstrich']],
  ['chocolate',['schokolade']],['cookie',['keks']],['chips',['chips']],['icecube',['eiswurfel','eiswuerfel']],['icecream',['eiscreme','magnum','sorbet']],['sweet',['gummibar','gummibaer','bonbon','suß','suess']],['protein',['proteinriegel','protein']],['snack',['musliriegel','muesliriegel','reiswaffel','snack']],
  ['dish',['spulmittel','spuelmittel','spulmaschinen','spuelmaschinen','spulschwamm','spuelschwamm']],['laundry',['waschmittel','wasche','waesche']],['cleaner',['reiniger']],['paper',['toilettenpapier','kuchenrolle','kuechenrolle','taschentuch','zewa','backpapier']],['trash',['mullbeutel','muellbeutel','gefrierbeutel']],['hair',['shampoo','haar']],['tooth',['zahnpasta','zahnburste','zahnbuerste','mundspulung','mundspuelung']],['baby',['windel']],['hygiene',['tampon','intim','deo','duschgel','rasierer']],['bodycare',['korperpflege','koerperpflege']],['stationery',['schreib','stift','papier','heft']],['tape',['klebeband','tesa']],
];

function motifForName(name, categoryId='other') {
  const key = normalizeText(name);
  if (/toastkase|toastkaese/.test(key)) return 'cheese';
  if (/^hefe$|frische hefe|frischhefe|trockenhefe/.test(key)) return 'baking';
  if (/^knoblauch$/.test(key)) return 'garlic';
  if (/^granatapfel$/.test(key)) return 'fruit';
  if (/^zucchini$/.test(key)) return 'cucumber';
  if (/^buttermilch$/.test(key)) return 'milk';
  if (/vegane mayo/.test(key)) return 'sauce';
  if (/vegane sahne/.test(key)) return 'milk';
  if (/vegane creme fraiche|vegane crème fraîche/.test(key)) return 'yogurt';

  if (categoryId === 'produce') {
    if (/banane/.test(key)) return 'banana';
    if (/apfel/.test(key)) return 'apple';
    if (/heidelbeer|blaubeer|erdbeer|himbeer|brombeer|johannisbeer|stachelbeer|preiselbeer/.test(key)) return 'berries';
    if (/orange|zitrone|limette|mandarine|clementine|grapefruit|pomelo/.test(key)) return 'citrus';
    if (/traube/.test(key)) return 'grape';
    if (/birne/.test(key)) return 'pear';
    if (/tomate/.test(key)) return 'tomato';
    if (/mohre|moehre|karotte/.test(key)) return 'carrot';
    if (/kartoffel/.test(key)) return 'potato';
    if (/gurke/.test(key)) return 'cucumber';
    if (/paprika/.test(key)) return 'pepper';
    if (/brokkoli/.test(key)) return 'broccoli';
    if (/blumenkohl/.test(key)) return 'cauliflower';
    if (/salat|spinat|rucola|ruccola/.test(key)) return 'leaf';
    if (/zwiebel|lauch/.test(key)) return 'onion';
    if (/knoblauch/.test(key)) return 'garlic';
    if (/champignon|pilz/.test(key)) return 'mushroom';
    if (/gurke/.test(key)) return 'cucumber';
    if (/mais/.test(key)) return 'corn';
    return 'fruit';
  }
  if (categoryId === 'vegetarian') {
    if (/tofu|tempeh|seitan/.test(key)) return 'tofu';
    if (/hummus|linse|kichererb|bohne/.test(key)) return 'beans';
    if (/wurst|salami|mortadella|lyoner|leberwurst|teewurst/.test(key)) return 'sausage';
    return 'veggie';
  }
  if (categoryId === 'bakery_fitness') {
    if (/haferflocken|musli|muesli/.test(key)) return 'oat';
    if (/protein/.test(key)) return 'protein';
    if (/riegel|reiswaffel|maiswaffel/.test(key)) return 'snack';
    if (/honig|marmelade|konfiture|aufstrich|nutella|mus/.test(key)) return 'spread';
    return 'bread';
  }
  if (categoryId === 'baking') {
    if (/mehl|gries|griess|panier|semmelbro/.test(key)) return 'wheat';
    if (/zucker|stevia/.test(key)) return 'sugar';
    if (/kakao|schoko|kuverture/.test(key)) return 'chocolate';
    return 'baking';
  }
  if (categoryId === 'milk') {
    if (/eier|(^| )ei( |$)/.test(key)) return 'egg';
    if (/butter|margarine/.test(key)) return 'butter';
    if (/joghurt|jogurt|skyr|quark|pudding|kefir|creme/.test(key)) return 'yogurt';
    return 'milk';
  }
  if (categoryId === 'canned') {
    if (/tomate/.test(key)) return 'tomato';
    if (/bohne|kichererb|linse|erbse/.test(key)) return 'beans';
    if (/thunfisch|sardine|makrele/.test(key)) return 'fish';
    if (/mais/.test(key)) return 'corn';
    if (/champignon|pilz/.test(key)) return 'mushroom';
    if (/gurke/.test(key)) return 'cucumber';
    if (/mandarine|pfirsich|ananas/.test(key)) return 'fruit';
    if (/mohre|karotte/.test(key)) return 'carrot';
    return 'generic';
  }
  if (categoryId === 'pasta_rice') return /reis|couscous|bulgur|quinoa|polenta|knodel|knoedel|puree|püree/.test(key) ? 'rice' : 'pasta';
  if (categoryId === 'oils_sauces') return /olivenol|olivenoel|sonnenblumenol|sonnenblumenoel|rapsol|rapsoel|kokosol|kokosoel|sesamol|sesamoel/.test(key) ? 'oil' : 'sauce';
  if (categoryId === 'cheese') return 'cheese';
  if (categoryId === 'household') {
    if (/toilettenpapier|kuchenrolle|kuechenrolle|backpapier|folie/.test(key)) return 'paper';
    if (/mullbeutel|muellbeutel|gefrierbeutel/.test(key)) return 'trash';
    if (/spul|spuel|geschirr|schwamm|burste|buerste|topfreiniger/.test(key)) return 'dish';
    if (/waschmittel|weichspul|weichspuel|wasche|waesche/.test(key)) return 'laundry';
    return 'cleaner';
  }
  if (categoryId === 'milk_uncooled') {
    if (/hafer|mandel|soja|kokos|reisdrink/.test(key)) return 'oat';
    if (/eier|(^| )ei( |$)/.test(key)) return 'egg';
    return 'milk';
  }
  if (categoryId === 'ready_chilled') {
    if (/^butter/.test(key)) return 'butter';
    if (/gnocchi|tortellini|ravioli|maultasche|pasta/.test(key)) return 'pasta';
    if (/margarine/.test(key)) return 'butter';
    return 'generic';
  }
  if (categoryId === 'frozen') {
    if (/heidelbeer|blaubeer|erdbeer|himbeer|beeren|kirsche|mango/.test(key)) return 'berries';
    if (/pommes|krokette|kartoffel/.test(key)) return 'potato';
    if (/spinat|krauter|kraeuter/.test(key)) return 'leaf';
    if (/mais/.test(key)) return 'corn';
    if (/erbse|bohne/.test(key)) return 'beans';
    if (/brokkoli/.test(key)) return 'broccoli';
    if (/blumenkohl/.test(key)) return 'cauliflower';
    if (/fisch|lachs|garnele/.test(key)) return 'fish';
    if (/hahnchen|haehnchen|nugget/.test(key)) return 'chicken';
    return 'frozen';
  }
  if (categoryId === 'meat') {
    if (/hahnchen|haehnchen|huhnchen|huehnchen|pute/.test(key)) return 'chicken';
    if (/wurst|salami|schinken|aufschnitt|bacon|mortadella|leberwurst|teewurst/.test(key)) return 'sausage';
    if (/fisch|lachs|garnele/.test(key)) return 'fish';
    return 'meat';
  }
  if (categoryId === 'drinks') {
    if (/wasser/.test(key)) return 'water';
    if (/kaffee|espresso/.test(key)) return 'coffee';
    if (/tee/.test(key)) return 'tea';
    if (/energy/.test(key)) return 'energy';
    if (/cola|fanta|sprite|limonade|limo/.test(key)) return 'cola';
    return 'juice';
  }
  if (categoryId === 'sweets') {
    if (/nutella|schokocreme/.test(key)) return 'spread';
    if (/schokolade|schokoriegel|kinder riegel|duplo|hanuta|kinder bueno|kinder pingui/.test(key)) return 'chocolate';
    if (/chips|flips|salzstangen|popcorn/.test(key)) return 'chips';
    if (/keks|cookie|prinzenrolle|waffel/.test(key)) return 'cookie';
    return 'sweet';
  }
  if (categoryId === 'drugstore') {
    if (/zahn|mundspul|mundspuel/.test(key)) return 'tooth';
    if (/shampoo|haar|spulung|spuelung/.test(key)) return 'hair';
    if (/windel|baby/.test(key)) return 'baby';
    if (/taschentuch|toilettenpapier|kosmetiktuch/.test(key)) return 'paper';
    if (/deo|rasier|tampon|intim/.test(key)) return 'hygiene';
    return 'bodycare';
  }
  if (categoryId === 'ice_cream') return /eiswurfel|eiswuerfel/.test(key) ? 'icecube' : 'icecream';

  const padded = ` ${key} `;
  for (const [motif,terms] of motifRules) if (terms.some(term=>padded.includes(normalizeText(term)))) return motif;
  return 'generic';
}

function baseForName(name, categoryId='other') {
  const key = normalizeText(name);
  if (/toastkase|toastkaese/.test(key)) return 'tray';
  if (/^hefe$|frische hefe|frischhefe/.test(key)) return 'box';
  if (/^buttermilch$/.test(key)) return 'carton';
  if (categoryId==='produce') return 'loose';
  if (categoryId==='bakery_fitness') {
    if (/honig|marmelade|konfiture|aufstrich|nutella|erdnussbutter|mandelmus|tahini/.test(key)) return 'jar';
    if (/proteinriegel|musliriegel|muesliriegel|riegel/.test(key)) return 'bar';
    if (/haferflocken|musli|muesli/.test(key)) return 'bag';
    if (/knusperbrot|knackebrot|knäckebrot|cracker/.test(key)) return 'box';
    return 'loose';
  }
  if (categoryId==='baking') {
    if (/frische hefe|frischhefe/.test(key)) return 'box';
    if (/trockenhefe/.test(key)) return 'bag';
    if (/vanilleextrakt/.test(key)) return 'bottle';
    if (/vanillepaste/.test(key)) return 'tube';
    if (/vanilleschote/.test(key)) return 'paper';
    return 'bag';
  }
  if (categoryId==='milk') {
    if (/eier|(^| )ei( |$)/.test(key)) return 'box';
    if (/butter|margarine/.test(key)) return 'box';
    if (/joghurt|jogurt|skyr|quark|schmand|saure sahne|creme|pudding|kefir/.test(key)) return 'cup';
    return 'carton';
  }
  if (categoryId==='canned') return 'can';
  if (categoryId==='pasta_rice') return 'bag';
  if (categoryId==='oils_sauces') {
    if (/ketchup|sriracha|sweet chili|sweet-chili|bbq|barbecue|cocktailsauce/.test(key)) return 'squeeze';
    if (/pesto|mayonnaise|mayo|senf|aioli|remoulade/.test(key)) return 'jar';
    return 'bottle';
  }
  if (categoryId==='cheese') {
    if (/frischkase|frischkaese|korniger|koerniger/.test(key)) return 'cup';
    if (/mozzarella/.test(key) && !/gerieben/.test(key)) return 'pouch';
    if (/gerieben/.test(key)) return 'bag';
    return 'tray';
  }
  if (categoryId==='household') {
    if (/toilettenpapier|kuchenrolle|kuechenrolle/.test(key)) return 'roll';
    if (/mullbeutel|muellbeutel|gefrierbeutel|alufolie|frischhaltefolie|backpapier/.test(key)) return 'box';
    if (/spulmaschinentab|spuelmaschinentab|spulmaschinenpulver|spuelmaschinenpulver|spulmaschinensalz|spuelmaschinensalz/.test(key)) return 'box';
    if (/schwamm|burste|buerste|tuch|topfreiniger/.test(key)) return 'bundle';
    return 'bottle';
  }
  if (categoryId==='milk_uncooled') return 'carton';
  if (categoryId==='ready_chilled') return /^butter/.test(key) ? 'box' : 'tray';
  if (categoryId==='frozen') return 'frozen_bag';
  if (categoryId==='meat') return 'tray';
  if (categoryId==='drinks') {
    if (/kaffee|espresso/.test(key)) return 'bag';
    if (/^tee$|schwarzer tee|gruner tee|gruener tee|fruchtetee|fruechtetee|krautertee|kraeutertee/.test(key)) return 'box';
    if (/saft|schorle/.test(key)) return 'carton';
    return 'bottle';
  }
  if (categoryId==='sweets') {
    if (/nutella|schokocreme/.test(key)) return 'jar';
    if (/schokolade|schokoriegel|kinder riegel|duplo|hanuta|kinder bueno|kinder pingui/.test(key)) return 'bar';
    if (/chips|flips|salzstangen|popcorn|nusse|nuesse|studentenfutter/.test(key)) return 'bag';
    return 'box';
  }
  if (categoryId==='drugstore') {
    if (/zahnpasta/.test(key)) return 'tube';
    if (/toilettenpapier/.test(key)) return 'roll';
    if (/taschentuch|kosmetiktuch|tampon|binde|slipeinlage|zahnburste|zahnbuerste|rasierer/.test(key)) return 'box';
    if (/windel/.test(key)) return 'bag';
    return 'bottle';
  }
  if (categoryId==='ice_cream') {
    if (/eiswurfel|eiswuerfel/.test(key)) return /beutel/.test(key) ? 'frozen_bag' : 'loose';
    if (/magnum|cornetto/.test(key)) return 'bar';
    return 'cup';
  }
  if (categoryId==='vegetarian') {
    if (/vegane mayo/.test(key)) return 'jar';
    if (/vegane sahne/.test(key)) return 'carton';
    if (/vegane creme fraiche|vegane crème fraîche/.test(key)) return 'cup';
    if (/hummus/.test(key)) return 'cup';
    if (/tofu|tempeh|seitan|schnitzel|nugget|burger|frikadelle|cevapcici|wurst|salami|mortadella|lyoner|hack|bolognese/.test(key)) return 'tray';
    if (/linse|kichererb|bohne/.test(key)) return 'bag';
    return 'tray';
  }
  if (categoryId==='other') return 'loose';
  return 'loose';
}

function labelFor(name, base, motif, categoryId='other') {
  const key = normalizeText(name);
  const short = (value, max=14) => firstUpper(String(value || '')).toUpperCase().replace(/[^A-ZÄÖÜ0-9 -]/g,'').replace(/\s+/g,' ').trim().slice(0,max);

  // TK-Produkte immer klar kennzeichnen.
  if (categoryId==='frozen') {
    if (/fischstabchen|fischstaebchen/.test(key)) return 'FISCHSTÄB.';
    if (/tk beerenmix/.test(key)) return 'TK BEERENMIX';
    if (/tk brokkoli/.test(key)) return 'TK BROKKOLI';
    if (/tk blumenkohl/.test(key)) return 'TK BLUMENK.';
    if (/tk mais/.test(key)) return 'TK MAIS';
    if (/tk krauter|tk kraeuter/.test(key)) return 'TK KRÄUTER';
    if (/heidelbeer|blaubeer/.test(key)) return 'TK HEIDEL';
    if (/himbeer/.test(key)) return 'TK HIMBEER';
    if (/erdbeer/.test(key)) return 'TK ERDBEER';
    if (/kirsch/.test(key)) return 'TK KIRSCH';
    if (/mango/.test(key)) return 'TK MANGO';
    if (/gemusemix|gemuesemix/.test(key)) return 'TK MIX';
    if (/wokgemuse|wokgemuese/.test(key)) return 'TK WOK';
    if (/suppengemuse|suppengemuese/.test(key)) return 'TK SUPPE';
    if (/bohnen/.test(key)) return 'TK BOHNEN';
    if (/erbsen/.test(key)) return 'TK ERBSEN';
    if (/^pommes$/.test(key)) return 'POMMES';
    if (/^tk pommes$/.test(key)) return 'TK POMMES';
    if (/krokette/.test(key)) return 'TK KROKETTE';
    if (/pizza/.test(key)) return 'TK PIZZA';
    if (/^spinat$/.test(key)) return 'SPINAT';
    if (/^tk spinat$/.test(key)) return 'TK SPINAT';
    if (/baguette/.test(key)) return 'TK BAGUETTE';
    if (/brotchen|broetchen/.test(key)) return 'TK BRÖTCHEN';
    return 'TK';
  }

  // Explizite Einzelbegriffe, die sonst zu ähnlich aussehen würden.
  if (/heidelbeer|blaubeer/.test(key)) return categoryId==='produce' ? 'HEIDEL' : 'HEIDELBEER';
  if (/himbeer/.test(key)) return 'HIMBEER';
  if (/erdbeer/.test(key)) return 'ERDBEER';
  if (/brombeer/.test(key)) return 'BROMBEER';
  if (/johannisbeer/.test(key)) return 'JOHANNIS';
  if (/stachelbeer/.test(key)) return 'STACHEL';
  if (/orange/.test(key)) return 'ORANGE';
  if (/zitrone/.test(key)) return 'ZITRONE';
  if (/limette/.test(key)) return 'LIMETTE';
  if (/mandarine/.test(key)) return 'MANDARINE';
  if (/clementine/.test(key)) return 'CLEMENTINE';
  if (/mango/.test(key)) return 'MANGO';
  if (/ananas/.test(key)) return 'ANANAS';
  if (/kiwi/.test(key)) return 'KIWI';
  if (/pfirsich/.test(key)) return 'PFIRSICH';
  if (/nektarine/.test(key)) return 'NEKTARINE';
  if (/pflaume/.test(key)) return 'PFLAUME';
  if (/aprikose/.test(key)) return 'APRIKOSE';
  if (/wassermelone/.test(key)) return 'WASSERMEL.';
  if (/honigmelone/.test(key)) return 'HONIGMELONE';
  if (/galiamelone/.test(key)) return 'GALIAMELONE';
  if (/granatapfel/.test(key)) return 'GRANAT';
  if (/avocado/.test(key)) return 'AVOCADO';
  if (/kirsch/.test(key)) return 'KIRSCHEN';
  if (/feige/.test(key)) return 'FEIGEN';
  if (/schmand/.test(key)) return 'SCHMAND';
  if (/saure sahne/.test(key)) return 'SAURE SAHNE';
  if (/haferdrink barista/.test(key)) return 'BARISTA';
  if (/hafermilch/.test(key)) return 'HAFERMILCH';
  if (/haferdrink/.test(key)) return 'HAFERDRINK';
  if (/mandelmilch/.test(key)) return 'MANDELMILCH';
  if (/mandeldrink/.test(key)) return 'MANDELDRINK';
  if (/(sojamilch|sojadrink)/.test(key)) return 'SOJA';
  if (/laktosefreie h milch|laktosefreie h-milch/.test(key)) return 'H-MILCH LF';
  if (/h milch 1 5|h-milch 1 5/.test(key)) return 'H-MILCH 1,5';
  if (/h milch 3 5|h-milch 3 5/.test(key)) return 'H-MILCH 3,5';
  if (/(h milch|h-milch)/.test(key)) return 'H-MILCH';
  if (/(toastkase|toastkaese)/.test(key)) return 'TOASTKÄSE';
  if (/(knusperbrot)/.test(key)) return 'KNUSPER';
  if (/(knackebrot|knäckebrot)/.test(key)) return 'KNÄCKE';
  if (/(musliriegel|muesliriegel)/.test(key)) return 'MÜSLI';
  if (/honig/.test(key)) return 'HONIG';
  if (/nutella|schokocreme/.test(key)) return 'NUSS';
  if (/marmelade|konfiture|konfituere|fruchtaufstrich/.test(key)) return 'AUFSTRICH';
  if (/reiswaffel/.test(key)) return 'REIS';
  if (/maiswaffel/.test(key)) return 'MAIS';
  if (/haferdrink barista/.test(key)) return 'BARISTA';
  if (/hafermilch/.test(key)) return 'HAFERMILCH';
  if (/haferdrink/.test(key)) return 'HAFERDRINK';
  if (/haferflocken/.test(key)) return 'HAFER';
  if (/fladenbrot/.test(key)) return 'FLADEN';
  if (/hotdog/.test(key)) return 'HOTDOG';
  if (/tortilla wraps|tortilla-wraps/.test(key)) return 'TORTILLA';
  if (/wrap/.test(key)) return 'WRAPS';
  if (/toast vollkorn|vollkorntoast/.test(key)) return 'VK TOAST';
  if (/vollkornbrot/.test(key)) return 'VK BROT';
  if (/laugenbrezel/.test(key)) return 'LAUGENBREZ.';
  if (/laugenstange/.test(key)) return 'LAUGENSTANG';
  if (/dinkelbrot/.test(key)) return 'DINKEL';
  if (/roggenbrot/.test(key)) return 'ROGGEN';
  if (/naan/.test(key)) return 'NAAN';
  if (/pita/.test(key)) return 'PITA';
  if (/dinkelmehl type 630/.test(key)) return 'DINKEL 630';
  if (/dinkelmehl type 1050/.test(key)) return 'DINKEL 1050';
  if (/dinkelmehl/.test(key)) return 'DINKEL';
  if (/roggenmehl/.test(key)) return 'ROGGEN';
  if (/weizenmehl type 405|mehl 405/.test(key)) return 'WEIZEN 405';
  if (/weizenmehl type 550|mehl 550/.test(key)) return 'WEIZEN 550';
  if (/weizenmehl type 1050|mehl 1050/.test(key)) return 'WEIZEN 1050';
  if (/weizenmehl/.test(key)) return 'WEIZEN';
  if (/hartweizengri|hartweizengrie|hartweizengrieß|hartweizengriß/.test(key)) return 'HARTWEIZEN';
  if (/paniermehl/.test(key)) return 'PANIERMEHL';
  if (/semmelbrosel|semmelbroesel/.test(key)) return 'SEMMELBRÖSEL';
  if (/puderzucker/.test(key)) return 'PUDER';
  if (/brauner zucker/.test(key)) return 'BRAUN';
  if (/vanillezucker/.test(key)) return 'VANILLEZUCKER';
  if (/stevia/.test(key)) return 'STEVIA';
  if (/(zucker|rohrzucker|hagelzucker)/.test(key)) return 'ZUCKER';
  if (/natron/.test(key)) return 'NATRON';
  if (/backpulver/.test(key)) return 'BACKPULVER';
  if (/speisestarke|speisestaerke|kartoffelstarke|kartoffelstaerke/.test(key)) return 'STÄRKE';
  if (/trockenhefe/.test(key)) return 'TROCKEN';
  if (/frische hefe|frischhefe/.test(key)) return 'FRISCH';
  if (/hefe/.test(key)) return 'HEFE';
  if (/backkakao/.test(key)) return 'BACKKAKAO';
  if (/^kakao$/.test(key)) return 'KAKAO';
  if (/vanillezucker/.test(key)) return 'VANILLE';
  if (/vanilleschote/.test(key)) return 'SCHOTE';
  if (/vanillepaste/.test(key)) return 'PASTE';
  if (/vanilleextrakt/.test(key)) return 'EXTRAKT';
  if (/passierte tomaten/.test(key)) return 'PASSIERT';
  if (/tomatenmark/.test(key)) return 'MARK';
  if (/gehackte tomaten/.test(key)) return 'GEHACKT';
  if (/geschalte tomaten/.test(key)) return 'GESCHÄLT';
  if (/dosentomaten/.test(key)) return 'DOSE TOMATE';
  if (/thunfisch in ol|thunfisch in oel/.test(key)) return 'THUN IN ÖL';
  if (/thunfisch im eigenen saft/.test(key)) return 'THUN SAFT';
  if (/thunfisch/.test(key)) return 'THUN';
  if (/mais dose/.test(key) && categoryId==='canned') return 'MAIS DOSE';
  if (/^mais$/.test(key) && categoryId==='canned') return 'MAIS';
  if (/kidneybohnen/.test(key) && categoryId==='canned') return 'KIDNEY';
  if (/weiße bohnen|weisse bohnen/.test(key) && categoryId==='canned') return 'WEISSE';
  if (/bohnen/.test(key) && categoryId==='canned') return 'BOHNEN';
  if (/kichererb/.test(key) && categoryId==='canned') return 'KICHER';
  if (/linsen/.test(key) && categoryId==='canned') return 'LINSEN';
  if (/erbsen und mohren|erbsen und moehren/.test(key) && categoryId==='canned') return 'ERBSEN+MÖHR';
  if (/^erbsen$/.test(key) && categoryId==='canned') return 'ERBSEN';
  if (/gurke|gurken/.test(key) && categoryId==='canned') return 'GURKEN';
  if (/penne/.test(key)) return 'PENNE';
  if (/fusilli/.test(key)) return 'FUSILLI';
  if (/tagliatelle/.test(key)) return 'TAGLIATELLE';
  if (/linguine/.test(key)) return 'LINGUINE';
  if (/makkaroni/.test(key)) return 'MAKKARONI';
  if (/lasagne/.test(key)) return 'LASAGNE';
  if (/glasnudeln/.test(key)) return 'GLASNUDELN';
  if (/mie nudeln/.test(key)) return 'MIE';
  if (/frische gnocchi/.test(key)) return 'GNOCCHI FR.';
  if (/gnocchi/.test(key)) return 'GNOCCHI';
  if (/frische tortellini/.test(key)) return 'TORTELLINI FR';
  if (/tortellini/.test(key)) return 'TORTELLINI';
  if (/maultaschen vegetarisch/.test(key)) return 'MAULT VEG';
  if (/maultaschen fleisch/.test(key)) return 'MAULT FLEISCH';
  if (/maultaschen/.test(key)) return 'MAULTASCHEN';
  if (/sojasauce hell/.test(key)) return 'HELL';
  if (/sojasauce dunkel/.test(key)) return 'DUNKEL';
  if (/sojasauce/.test(key)) return 'SOJA';
  if (/balsamico bianco/.test(key)) return 'BIANCO';
  if (/balsamico/.test(key)) return 'BALSAMICO';
  if (/teriyaki/.test(key)) return 'TERIYAKI';
  if (/sweet[ -]?chili/.test(key)) return 'CHILI';
  if (/sriracha/.test(key)) return 'SRIRACHA';
  if (/bbq|barbecue/.test(key)) return 'BBQ';
  if (/cocktailsauce/.test(key)) return 'COCKTAIL';
  if (/remoulade/.test(key)) return 'REMOULADE';
  if (/eiswurfel beutel|eiswuerfel beutel/.test(key)) return 'EIS BEUTEL';
  if (/eiswurfel|eiswuerfel/.test(key)) return 'EISWÜRFEL';
  if (/magnum mandel/.test(key)) return 'MANDEL';
  if (/magnum classic/.test(key)) return 'CLASSIC';
  if (/ben & jerry/.test(key)) return 'BEN&JERRY';
  if (/stracciatella/.test(key)) return 'STRACCIA';
  if (/cornetto/.test(key)) return 'CORNETTO';
  if (/mineralwasser still/.test(key)) return 'WASSER STILL';
  if (/mineralwasser medium/.test(key)) return 'WASSER MED.';
  if (/mineralwasser classic/.test(key)) return 'WASSER CLASS.';
  if (/gefrierbeutel 1 l/.test(key)) return 'GEFRIER 1 L';
  if (/gefrierbeutel 3 l/.test(key)) return 'GEFRIER 3 L';
  if (/vegetarische bratwurst/.test(key)) return 'VEG BRATW.';
  if (/vegetarische wurstchen|vegetarische wuerstchen/.test(key)) return 'VEG WÜRST.';
  if (/backkakao/.test(key)) return 'BACKKAKAO';
  if (/^kakao$/.test(key)) return 'KAKAO';
  if (/^pommes$/.test(key) && categoryId==='frozen') return 'POMMES';
  if (/^tk pommes$/.test(key) && categoryId==='frozen') return 'TK POMMES';
  if (/^spinat$/.test(key) && categoryId==='frozen') return 'SPINAT';
  if (/^tk spinat$/.test(key) && categoryId==='frozen') return 'TK SPINAT';
  if (/mandelmilch/.test(key)) return 'MANDELMILCH';
  if (/mandeldrink/.test(key)) return 'MANDELDRINK';
  if (/zitronenlimonade/.test(key)) return 'ZITRO LIMO';
  if (/eistee zitrone/.test(key)) return 'EISTEE ZITR.';

  // Für lose Motive lieber ein eigenes Kurzlabel statt identischer Symbole.
  if (base==='loose') {
    const text = short(name, 12);
    if (text) return text;
  }

  if (['sauce','cleaner','hair','bodycare','dish','laundry','protein','cola','juice','coffee','tea','water','sweet','chocolate','cookie','chips','icecream','paper'].includes(motif)) {
    const text = short(name);
    if (text) return text;
  }
  if (['bag','box','jar','carton','can','bottle','squeeze','cup','pouch','tray','tube','bar','roll','paper'].includes(base)) {
    const first = short(name.split(/[,/]/)[0]);
    if (first && first.length >= 3 && first.length <= 14) return first;
  }
  return '';
}

function inferVisual(name, categoryId='other') {
  const visualBase = baseForName(name, categoryId);
  const visualMotif = motifForName(name, categoryId);
  return { visualBase, visualMotif, visualLabel: labelFor(name, visualBase, visualMotif, categoryId), visualSource:'automatic' };
}

function sanitizeVisual(input={}, fallback={}) {
  const base = BASE_IDS.has(input.visualBase) ? input.visualBase : (BASE_IDS.has(fallback.visualBase) ? fallback.visualBase : 'loose');
  const motif = MOTIF_IDS.has(input.visualMotif) ? input.visualMotif : (MOTIF_IDS.has(fallback.visualMotif) ? fallback.visualMotif : 'generic');
  let label = input.visualLabel === undefined ? String(fallback.visualLabel||'') : String(input.visualLabel||'');
  label = label.trim().toUpperCase().replace(/\s+/g,' ').slice(0,18);
  return { visualBase:base, visualMotif:motif, visualLabel:label };
}

function categoryVisualKind(category={}) {
  const id = category.id || '';
  const key = normalizeText(category.name||'');
  const byId = {produce:'produce_scene',vegetarian:'veg_scene',bakery_fitness:'bakery_scene',baking:'baking_scene',milk:'milk_scene',canned:'canned_scene',pasta_rice:'pasta_scene',oils_sauces:'sauce_scene',cheese:'cheese_scene',household:'household_scene',milk_uncooled:'pantry_milk_scene',ready_chilled:'chilled_scene',frozen:'frozen_scene',meat:'meat_scene',drinks:'drink_scene',sweets:'sweet_scene',drugstore:'drugstore_scene',ice_cream:'icecream_scene',other:'box_scene'};
  if (byId[id]) return byId[id];
  if (key.includes('joghurt')) return 'yogurt_scene';
  if (key.includes('theke')) return 'counter_scene';
  if (key.includes('schreib')) return 'stationery_scene';
  if (key.includes('kinder')&&key.includes('snack')) return 'kids_snack_scene';
  if (key.includes('reinig')) return 'cleaner_scene';
  if (key.includes('papier')) return 'paper_scene';
  if (key.includes('korperpflege')||key.includes('koerperpflege')) return 'bodycare_scene';
  return 'box_scene';
}

module.exports = { VISUAL_BASES, VISUAL_MOTIFS, BASE_IDS, MOTIF_IDS, inferVisual, sanitizeVisual, categoryVisualKind };
