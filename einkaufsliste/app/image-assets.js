const { normalizeText } = require('./core');

const CATEGORY_IMAGE_KEYS = {
  produce: 'produce', vegetarian: 'vegetarian', bakery_fitness: 'bakery_fitness', baking: 'baking', milk: 'milk', canned: 'canned',
  pasta_rice: 'pasta_rice', oils_sauces: 'oils_sauces', cheese: 'cheese', household: 'household', milk_uncooled: 'milk_uncooled',
  ready_chilled: 'ready_chilled', frozen: 'frozen', meat: 'meat', drinks: 'drinks', sweets: 'sweets', drugstore: 'drugstore',
  ice_cream: 'ice_cream', other: 'other'
};

const RULES = [
  ['toast_cheese',['toastkase','toastkaese']], ['schmand',['schmand']], ['soured_cream',['saure sahne']],
  ['blueberries',['heidelbeere','blaubeere']], ['tomato',['tomate']], ['raspberry',['himbeere']], ['strawberry',['erdbeere']], ['cherry_tomatoes',['cherrytomate','cocktailtomate','tomatenmix']],
  ['banana',['banane']], ['apple',['apfel']], ['lemon',['zitrone']], ['lime',['limette']], ['grapes',['traube']],
  ['cucumber',['gurke']], ['rucola',['ruccola','rucola']], ['potato',['kartoffel']], ['carrot',['mohre','moehre','karotte']], ['paprika',['paprika']],
  ['broccoli',['brokkoli']], ['cauliflower',['blumenkohl']], ['iceberg_lettuce',['eisbergsalat','kopfsalat','romanasalat']], ['salad_mix',['salat','feldsalat']],
  ['onion',['zwiebel','lauch','fruhlingszwiebel']], ['garlic',['knoblauch']], ['eggplant',['aubergine']], ['zucchini',['zucchini']], ['mushroom',['champignon','pilz']], ['ginger',['ingwer','kurkuma']],
  ['toast',['toast','sandwichtoast']], ['baguette',['baguette','ciabatta','fladenbrot']], ['croissant',['croissant']], ['rolls',['brotchen','broetchen','laugenstange','brezel','burger buns','hotdog']], ['bread',['brot','zwieback','knackebrot','knäckebrot']],
  ['knusperbrot',['knusperbrot','cracker']], ['muesli_bar',['musliriegel','muesliriegel','hafer-riegel','nussriegel','proteinriegel','reiswaffel','maiswaffel','protein-cookie']],
  ['flour',['mehl','grieß','griess','paniermehl','semmelbrosel','semmelbroesel','backpulver','hefe','natron','speisestarke','speisestaerke']],
  ['spices',['vanille','zimt','lebkuchengewurz','lebkuchengewuerz','kakao','gelatine','agar agar','kokosraspel','mandel','haselnuss','walnuss','pekannuss','cashew','rosinen','sultaninen']],
  ['sweets',['zucker','puderzucker','rohrzucker','brauner zucker','hagelzucker','kuverture','kuverture','schokotropfen','backschokolade']],
  ['milk_carton',['h-milch','h milch','vollmilch','fettarme milch','milch frisch','kondensmilch','kaffeesahne','milchpulver','kaffeeweisser','kaffeeweißer']],
  ['oat_drink',['haferdrink','hafermilch','mandeldrink','mandelmilch','sojadrink','sojamilch','kokosdrink','reisdrink']],
  ['yogurt',['joghurt','jogurt','skyr','protein-joghurt','sojajoghurt','haferjoghurt']], ['quark',['quark','creme fraiche','creme légère','creme legere','mascarpone','ricotta','kefir']],
  ['schmand',['schmand']], ['soured_cream',['saure sahne']], ['butter',['butter','margarine']], ['cream_cheese',['frischkase','frischkaese']], ['cheese',['kase','kaese','gouda','emmentaler','mozzarella','parmesan','feta','hirtenkase','camembert','brie','cheddar','raclette','ziegenkase','halloumi']], ['eggs',['eier']],
  ['canned_tomato',['passierte tomaten','gehackte tomaten','geschalte tomaten','tomaten in stucken','tomatenmark','dosentomaten']],
  ['pickles',['gewurzgurke','eingelegte gurke','jalapeno','peperoni','olive','kapern','artischock','rote bete glas','sauerkraut','rotkohl glas','apfelmus']],
  ['canned_goods',['mais dose','bohnen dose','kichererbsen dose','erbsen dose','mohren dose','linsen dose','thunfisch','sardinen','makrelen','champignons dose','mandarinen dose','pfirsiche dose','ananas dose','kokosmilch dose','ravioli dose','suppe dose','dose']],
  ['pasta',['spaghetti','penne','fusilli','tagliatelle','linguine','makkaroni','lasagne','suppennudeln','dinkelnudeln','vollkornnudeln','glasnudeln','mie-nudeln','nudel']],
  ['rice',['reis','couscous','bulgur','quinoa','polenta','knodel','knoedel','kartoffelpuree','kartoffelpüree']],
  ['ketchup',['ketchup']], ['oils_sauces',['mayonnaise','mayo','senf','pesto','ajvar','sambal','sauce','soße','sosse','dressing','currypaste','sojasauce','teriyaki','sriracha','remoulade','aioli']],
  ['olive_oil',['olivenol','olivenoel']], ['sunflower_oil',['sonnenblumenol','sonnenblumenoel','rapsol','rapsoel','kokosol','kokosoel','sesamol','sesamoel']], ['oils_sauces',['essig','balsamico']],
  ['vegan',['tofu','tempeh','seitan','vegan','vegetar','veggie','falafel','hummus','linse','kichererbse','weiße bohnen','weisse bohnen','kidneybohne','schwarze bohne']],
  ['deli_meat',['schinken','salami','aufschnitt','bacon','mortadella','leberwurst','teewurst','fleischwurst','wiener','bockwurst','bratwurst']],
  ['meat',['hack','steak','schnitzel','gulasch','rouladen','frikadelle','fleisch']], ['meat',['hahnchen','haehnchen','huhnchen','huehnchen','pute']], ['fish',['lachs','fisch','garnele']],
  ['frozen_vegetables',['tk-','tk ','tiefkuhl','tiefkuehl','gefroren']],
  ['ice_cream',['vanilleeis','schokoladeneis','erdbeereis','stracciatella','ben & jerry','magnum','cornetto','wassereis','sorbet','eiswurfel','eiswuerfel']],
  ['water',['mineralwasser','wasser']], ['juice',['saft','schorle']], ['lemonade',['cola','fanta','sprite','limonade','limo','eistee','energy','malzbier','bier']], ['coffee',['kaffee','espresso','kaffeepad','kaffeekapsel']], ['tea',['schwarzer tee','gruner tee','gruener tee','fruchtetee','fruechtetee','krautertee','kraeutertee',' tee']],
  ['chocolate',['schokolade','duplo','hanuta','kinder riegel','kinder bueno','kinder pingui']], ['chips',['chips','tortilla chips','erdnussflips','salzstangen','popcorn']], ['candy',['gummibar','gummibaer','lakritz','bonbon','marshmallow','waffel','keks','cookie','prinzenrolle','nusse gerostet','nuesse geroestet','studentenfutter']],
  ['toilet_paper',['toilettenpapier']], ['household',['spulmaschinentab','spuelmaschinentab','spulmaschinenpulver','spuelmaschinenpulver','spulmaschinensalz','spuelmaschinensalz','klarspuler','klarspueler','spulschwamm','spuelschwamm','spulburste','spuelbuerste','geschirrtuch','mikrofasertuch','allzwecktuch']],
  ['cleaner',['spulmittel','spuelmittel','allzweckreiniger','badreiniger','glasreiniger','kuchenreiniger','kuechenreiniger','wc-reiniger','entkalker','rohrreiniger','bodenreiniger','waschmittel','weichspuler','weichspueler','fleckenspray','wasche-desinfektion','waesche-desinfektion']],
  ['misc',['mullbeutel','muellbeutel','gefrierbeutel','frischhaltefolie','backpapier','alufolie','kuchenrolle','kuechenrolle']],
  ['drugstore',['shampoo','spulung haare','spuelung haare','haarkur','duschgel','seife','intim','deo','rasierschaum','rasiergel','rasierer','zahnpasta','zahnburste','zahnbuerste','zahnseide','interdental','mundspulung','mundspuelung','taschentuch','kosmetiktuch','wattepad','wattestabchen','wattestaebchen','tampon','binde','slipeinlage','sonnencreme','handcreme','bodylotion','lippenpflege']], ['baby',['windel','feuchttuch','babyshampoo','babyduschgel']],
  ['stationery',['schreib','stift','heft','papier','klebeband','tesa']]
];

function imageKeyForProduct(name, categoryId='other') {
  const normalized = normalizeText(name);

  // 0.3.26: echte Einzeldateien für bislang zu grob zusammengefasste Stammartikel.
  // Diese Regeln stehen ganz oben, damit eindeutige Produktnamen niemals auf ein
  // generisches Kategorie-/Sammelbild zurückfallen.
  const exactStandalone = [
    ['pear', /^(birne|birnen)$/], ['orange', /^(orange|orangen)$/], ['cherries', /^kirschen?$/],
    ['avocado', /^avocado$/], ['mango', /^mango$/], ['pineapple', /^ananas$/], ['kiwi', /^kiwi$/],
    ['mandarin', /^(mandarine|mandarinen|clementine|clementinen)$/], ['peach', /^(pfirsich|pfirsiche|nektarine|nektarinen|aprikose|aprikosen)$/],
    ['plum', /^(pflaume|pflaumen)$/], ['pomegranate', /^granatapfel$/], ['watermelon', /^wassermelone$/],
    ['melon', /^(honigmelone|galiamelone)$/], ['blackberry', /^brombeeren?$/],
    ['currants', /^(johannisbeeren?|stachelbeeren?|preiselbeeren?)$/],
    ['soft_cheese', /^(camembert|brie)$/], ['blue_cheese', /^blauschimmelkase$/],
    ['cheddar_block', /^cheddar$/], ['long_pasta', /^(spaghetti|tagliatelle|linguine)$/],
    ['lasagne_sheets', /^lasagneplatten$/], ['glass_noodles', /^glasnudeln$/], ['asian_noodles', /^mie nudeln$/],
    ['gnocchi', /^(gnocchi|frische gnocchi)$/], ['tortellini', /^(tortellini|frische tortellini)$/],
    ['ravioli', /^frische ravioli$/], ['maultaschen', /^(maultaschen|maultaschen vegetarisch|maultaschen fleisch)$/]
  ];
  for (const [imageKey, pattern] of exactStandalone) if (pattern.test(normalized)) return imageKey;

  // Eindeutige Produktformen schlagen eine eventuell alte/falsche Kategorie.
  // Das ist wichtig für Bestandsdaten, deren Kategorie absichtlich nicht still geändert wird.
  if (/^feigen?$/.test(normalized)) return 'figs';
  if (/reiswaffel|maiswaffel/.test(normalized)) return 'rice_cakes';
  if (/zewa smart|kuchenrolle|kuechenrolle|papierrolle/.test(normalized)) return 'paper_towels';
  if (/^knoblauch$/.test(normalized)) return 'garlic';
  if (/^buttermilch$/.test(normalized)) return 'milk_bottle';
  if (/^nutella$|^schokocreme$/.test(normalized)) return 'chocolate_bar';
  if (/^pesto$|tomatenpesto/.test(normalized)) return 'pesto_jar';
  if (/^bananen?$/.test(normalized)) return 'banana';
  if (/^tomaten?$/.test(normalized)) return 'tomato';
  if (/^gurken?$/.test(normalized)) return 'cucumber';
  if (/^ruccola$|^rucola$/.test(normalized)) return 'rucola';
  if (/^kartoffeln?$/.test(normalized)) return 'potato';
  if (/^heidelbeeren?$|^blaubeeren?$/.test(normalized)) return 'blueberries';
  if (/knusperbrot|knackebrot|knäckebrot/.test(normalized)) return 'knusperbrot';
  if (/^musliriegel$|^muesliriegel$/.test(normalized)) return 'muesli_bar_new';
  if (/^hahnchen$|^haehnchen$|^huhnchen$|^huehnchen$/.test(normalized)) return 'chicken_fillets';
  if (/toastkase|toastkaese/.test(normalized)) return 'toast_cheese';
  if (/gerieben.*kase|gerieben.*kaese/.test(normalized)) return 'grated_cheese_bowl';
  if (/parmesan|grana padano/.test(normalized)) return 'parmesan_wedge';
  if (/schmand/.test(normalized)) return 'schmand_cup';
  if (/saure sahne/.test(normalized)) return 'soured_cream_cup';
  if (/gefrierbeutel/.test(normalized)) return 'freezer_bags2';
  if (/eiswurfel|eiswuerfel/.test(normalized)) return 'ice_cubes';
  if (/bunte nudeln|meyerhof.*nudeln|nudeln.*meyerhof/.test(normalized)) return 'colored_pasta';
  if (/flammkuchenboden|flammkuchenteig/.test(normalized)) return 'flammkuchen_dough';
  if (/rohschinken|rohen schinken|serrano[ -]?schinken|parmaschinken|prosciutto/.test(normalized)) return 'raw_ham';
  if (!/vegetar|vegan/.test(normalized) && /schinken/.test(normalized)) return 'ham_slices2';
  if (/vierertrager.*cola|cola.*4er|cola 4er/.test(normalized)) return 'cola_bottle';
  if (/^gemuse(?: eins komma.*)?$/.test(normalized)) return 'produce';
  if (/frische hefe|frischhefe/.test(normalized)) return 'fresh_yeast';
  if (/trockenhefe/.test(normalized)) return 'dry_yeast';
  if (/(^| )hefe( |$)/.test(normalized)) return 'fresh_yeast';

  const looksFrozen = /(^| )(tk|tiefkuhl\w*|tiefkuehl\w*|gefroren\w*|tiefgefroren\w*)( |$)/.test(normalized);
  if (looksFrozen && categoryId !== 'ice_cream') {
    if (/heidelbeere|blaubeere|himbeere|erdbeere|beeren|mango|kirsche/.test(normalized)) return 'frozen_berries2';
    if (/pizza|flammkuchen/.test(normalized)) return 'frozen_pizza2';
    if (/fischstabchen|fischstaebchen/.test(normalized)) return 'fish_sticks';
    if (/lachs|fisch|garnele/.test(normalized)) return 'frozen_fish';
    if (/pommes|krokette|rosti|roesti|kartoffelspalten/.test(normalized)) return 'frozen_fries';
    if (/spinat|krauter|kraeuter/.test(normalized)) return 'frozen_spinach';
    if (/hahnchen|haehnchen|nugget/.test(normalized)) return 'frozen_chicken';
    if (/baguette/.test(normalized)) return 'frozen_bread';
    if (/brotchen|broetchen/.test(normalized)) return 'frozen_rolls';
    return 'frozen_vegetables_new';
  }

  // Kategorie und konkrete Verkaufsform haben Vorrang vor allgemeinen Worttreffern.
  // Dadurch kann z. B. Vollmilchschokolade niemals als Milchkarton enden.
  if (categoryId === 'cheese') {
    if (/toastkase|toastkaese/.test(normalized)) return 'toast_cheese';
    if (/frischkase|frischkaese|korniger frischkase|koerniger frischkaese/.test(normalized)) return 'cream_cheese_tub2';
    if (/gerieben/.test(normalized)) return 'grated_cheese_bowl';
    if (/parmesan|grana padano/.test(normalized)) return 'parmesan_wedge';
    if (/mozzarella/.test(normalized)) return 'mozzarella_ball';
    if (/feta|hirtenkase|hirtenkaese|halloumi|ziegenkase|ziegenkaese/.test(normalized)) return 'feta_block';
    if (/gouda/.test(normalized)) return 'gouda_wheel';
    if (/^cheddar$/.test(normalized)) return 'cheddar_block';
    if (/cheddar|scheibenkase|scheibenkaese|raclette/.test(normalized)) return 'cheese_slices';
    if (/camembert|brie/.test(normalized)) return 'soft_cheese';
    if (/blauschimmel/.test(normalized)) return 'blue_cheese';
    return 'cheese_wedge';
  }

  if (categoryId === 'household') {
    if (/gefrierbeutel/.test(normalized)) return 'freezer_bags2';
    if (/mullbeutel|muellbeutel/.test(normalized)) return 'trash_bags2';
    if (/alufolie/.test(normalized)) return 'aluminum_foil';
    if (/frischhaltefolie/.test(normalized)) return 'cling_film';
    if (/backpapier/.test(normalized)) return 'baking_paper';
    if (/kuchenrolle|kuechenrolle/.test(normalized)) return 'kitchen_roll_new';
    if (/spulschwamm|spuelschwamm|topfreiniger|spulburste|spuelbuerste/.test(normalized)) return 'dish_sponge';
    if (/spulmaschinentab|spuelmaschinentab/.test(normalized)) return 'dishwasher_tabs';
    if (/spulmaschinenpulver|spuelmaschinenpulver/.test(normalized)) return 'dishwasher_powder';
    if (/spulmaschinensalz|spuelmaschinensalz/.test(normalized)) return 'dishwasher_salt';
    if (/klarspuler|klarspueler/.test(normalized)) return 'dishwashing_liquid2';
    if (/spulmittel|spuelmittel/.test(normalized)) return 'dishwashing_liquid2';
    if (/weichspuler|weichspueler/.test(normalized)) return 'fabric_softener';
    if (/waschmittel/.test(normalized)) return 'laundry_detergent';
    if (/reiniger|flecken|desinfektion|entkalker/.test(normalized)) return 'allpurpose_cleaner2';
    if (/geschirrtuch|mikrofasertuch|allzwecktuch/.test(normalized)) return 'household';
    return 'household';
  }

  if (categoryId === 'vegetarian') {
    if (/tofu|tempeh|seitan/.test(normalized)) return 'tofu_block';
    if (/hummus|kichererb/.test(normalized)) return 'chickpeas_bowl';
    if (/linse|bohne/.test(normalized)) return 'lentils_bowl';
    if (/bratwurst|wurstchen|wuerstchen|fleischwurst/.test(normalized)) return 'veggie_sausage';
    if (/salami|mortadella|lyoner|aufschnitt|leberwurst|teewurst/.test(normalized)) return 'veggie_deli';
    if (/hack|bolognese/.test(normalized)) return 'veggie_mince';
    if (/schnitzel|cevapcici|frikadelle/.test(normalized)) return 'veggie_schnitzel';
    if (/nugget/.test(normalized)) return 'veggie_nuggets';
    if (/burger/.test(normalized)) return 'veggie_burger';
    if (/falafel/.test(normalized)) return 'vegan';
    if (/mayo/.test(normalized)) return 'mayonnaise_jar';
    if (/sahne|creme fraiche/.test(normalized)) return 'cream_carton';
    if (/joghurt/.test(normalized)) return 'yogurt_cup';
    return 'vegan';
  }

  if (categoryId === 'frozen') {
    if (/heidelbeere|blaubeere|himbeere|erdbeere|beeren|mango|kirsche/.test(normalized)) return 'frozen_berries2';
    if (/pizza|flammkuchen/.test(normalized)) return 'frozen_pizza2';
    if (/fischstabchen|fischstaebchen/.test(normalized)) return 'fish_sticks';
    if (/lachs|fisch|garnele/.test(normalized)) return 'frozen_fish';
    if (/pommes|krokette|rosti|roesti|kartoffelspalten/.test(normalized)) return 'frozen_fries';
    if (/spinat|krauter|kraeuter/.test(normalized)) return 'frozen_spinach';
    if (/hahnchen|haehnchen|nugget/.test(normalized)) return 'frozen_chicken';
    if (/baguette/.test(normalized)) return 'frozen_bread';
    if (/brotchen|broetchen/.test(normalized)) return 'frozen_rolls';
    return 'frozen_vegetables_new';
  }

  if (categoryId === 'ice_cream') {
    if (/eiswurfel|eiswuerfel/.test(normalized)) return 'ice_cubes';
    return 'ice_cream_cup';
  }

  if (categoryId === 'meat') {
    if (/hack/.test(normalized)) return 'minced_meat';
    if (/hahnchen|haehnchen|huhnchen|huehnchen|pute/.test(normalized)) return 'chicken_fillets';
    if (/salami/.test(normalized)) return 'salami_slices';
    if (/schinken|aufschnitt|bacon|mortadella|leberwurst|teewurst/.test(normalized)) return 'ham_slices2';
    if (/bratwurst|bockwurst|wiener|fleischwurst|wurstchen|wuerstchen|wurst/.test(normalized)) return 'sausage';
    if (/steak|schnitzel|gulasch|roulade|frikadelle|fleisch/.test(normalized)) return 'beef_steak';
    return 'beef';
  }

  if (categoryId === 'canned') {
    if (/tomate|tomatenmark/.test(normalized)) return 'canned_tomato_new';
    if (/mais/.test(normalized)) return 'canned_corn';
    if (/bohne|kichererb|linse|erbse|mohre/.test(normalized)) return 'canned_beans';
    if (/thunfisch|sardine|makrele/.test(normalized)) return 'canned_tuna';
    if (/gurke|jalapeno|peperoni|olive|kapern|artischock|rote bete|sauerkraut|rotkohl|apfelmus/.test(normalized)) return 'pickles';
    if (/ravioli|suppe/.test(normalized)) return 'ready_meal_tray';
    return 'canned_goods';
  }

  if (categoryId === 'oils_sauces') {
    if (/ketchup/.test(normalized)) return 'ketchup_bottle';
    if (/mayonnaise|mayo|aioli|remoulade/.test(normalized)) return 'mayonnaise_jar';
    if (/senf/.test(normalized)) return 'mustard_jar';
    if (/pesto/.test(normalized)) return 'pesto_jar';
    if (/sojasauce|teriyaki/.test(normalized)) return 'soy_sauce';
    if (/essig|balsamico/.test(normalized)) return 'vinegar_bottle';
    if (/olivenol|olivenoel|sonnenblumenol|sonnenblumenoel|rapsol|rapsoel|kokosol|kokosoel|sesamol|sesamoel/.test(normalized)) return 'oil_bottle';
    return 'oils_sauces';
  }

  if (categoryId === 'baking') {
    if (/frische hefe|frischhefe/.test(normalized)) return 'fresh_yeast';
    if (/trockenhefe/.test(normalized)) return 'dry_yeast';
    if (/hefe/.test(normalized)) return 'fresh_yeast';
    if (/backpulver|natron/.test(normalized)) return 'baking_powder';
    if (/speisestarke|speisestaerke|kartoffelstarke|kartoffelstaerke/.test(normalized)) return 'starch_packet';
    if (/zucker|stevia/.test(normalized)) return 'sugar_bag';
    if (/mandel|haselnuss|walnuss|pekannuss|cashew/.test(normalized)) return 'nuts_bowl';
    if (/kakao|kuverture|schokotropfen|backschokolade/.test(normalized)) return 'chocolate_bar';
    if (/vanille|zimt|lebkuchen|gelatine|agar|kokosraspel|rosine|sultanine/.test(normalized)) return 'spice_grinder';
    return 'flour_bag';
  }

  if (categoryId === 'bakery_fitness') {
    if (/reiswaffel|maiswaffel/.test(normalized)) return 'rice_cakes';
  if (/zewa smart|kuchenrolle|kuechenrolle|papierrolle/.test(normalized)) return 'paper_towels';
    if (/knusperbrot|knackebrot|knäckebrot|cracker/.test(normalized)) return 'knusperbrot';
    if (/musliriegel|muesliriegel|proteinriegel|hafer-riegel|nussriegel/.test(normalized)) return 'muesli_bar_new';
    if (/haferflocken|musli|muesli/.test(normalized)) return 'oats_bowl';
    if (/honig|ahornsirup/.test(normalized)) return 'honey_jar';
    if (/marmelade|konfiture|konfituere|fruchtaufstrich/.test(normalized)) return 'pickles';
    if (/erdnussbutter|mandelmus|erdnusscreme|tahini/.test(normalized)) return 'nuts_bowl';
    if (/toast/.test(normalized)) return 'toast';
    if (/croissant/.test(normalized)) return 'croissant';
    if (/baguette|ciabatta|fladenbrot/.test(normalized)) return 'baguette';
    if (/brotchen|broetchen|laugen|brezel|burger buns|hotdog/.test(normalized)) return 'rolls';
    return 'bread';
  }

  if (categoryId === 'milk') {
    if (/schmand/.test(normalized)) return 'schmand_cup';
    if (/saure sahne/.test(normalized)) return 'soured_cream_cup';
    if (/creme fraiche|creme legere|mascarpone|ricotta|kefir|quark/.test(normalized)) return 'quark_cup';
    if (/joghurt|jogurt|skyr|pudding|milchreis/.test(normalized)) return 'yogurt_cup';
    if (/butter|margarine/.test(normalized)) return 'butter_block';
    if (/eier|(^| )ei( |$)/.test(normalized)) return 'eggs_new';
    if (/sahne/.test(normalized)) return 'cream_carton';
    return 'milk_bottle';
  }

  if (categoryId === 'milk_uncooled') {
    if (/hafer|mandel|soja|kokosdrink|reisdrink/.test(normalized)) return 'oat_drink';
    if (/kondensmilch|kaffeesahne/.test(normalized)) return 'cream_carton';
    return 'milk_carton';
  }

  if (categoryId === 'ready_chilled') {
    if (/gnocchi/.test(normalized)) return 'gnocchi';
    if (/tortellini/.test(normalized)) return 'tortellini';
    if (/ravioli/.test(normalized)) return 'ravioli';
    if (/maultasche/.test(normalized)) return 'maultaschen';
    if (/pasta|spatzle|spaetzle|schupfnudel/.test(normalized)) return 'pasta_penne';
    if (/flammkuchenboden|pizzaboden|flammkuchenteig|pizzateig|blatterteig|blaetterteig|quicheteig/.test(normalized)) return 'dough_sheet';
    if (/fertigpizza|pizza/.test(normalized)) return 'ready_meal_tray';
    if (/salat/.test(normalized)) return 'salad_mix';
    if (/kartoffelpuffer/.test(normalized)) return 'potato';
    if (/butter|margarine/.test(normalized)) return 'butter_block';
    return 'ready_meal_tray';
  }

  if (categoryId === 'pasta_rice') {
    if (/spaghetti|tagliatelle|linguine/.test(normalized)) return 'long_pasta';
    if (/lasagne/.test(normalized)) return 'lasagne_sheets';
    if (/glasnudel/.test(normalized)) return 'glass_noodles';
    if (/mie nudel/.test(normalized)) return 'asian_noodles';
    if (/reis|couscous|bulgur|quinoa|polenta|knodel|knoedel|kartoffelpuree|kartoffelpüree/.test(normalized)) return 'rice';
    if (/penne|fusilli|makkaroni|suppennudel|dinkelnudel|vollkornnudel|nudel/.test(normalized)) return 'pasta';
    return 'pasta';
  }

  if (categoryId === 'drinks') {
    if (/kaffee|espresso|kaffeepad|kaffeekapsel/.test(normalized)) return 'coffee_beans';
    if (/tee/.test(normalized)) return 'tea_cup';
    if (/wasser/.test(normalized)) return 'water_bottle';
    if (/saft|schorle|kakao getrank/.test(normalized)) return 'juice_carton';
    if (/cola/.test(normalized)) return 'cola_bottle';
    if (/bier/.test(normalized)) return 'beer_bottle';
    return 'lemonade_bottle';
  }

  if (categoryId === 'sweets') {
    if (/schokolade|duplo|hanuta|kinder riegel|kinder bueno|kinder pingui/.test(normalized)) return 'chocolate_bar';
    if (/chips|tortilla|flips|salzstange|popcorn/.test(normalized)) return 'chips';
    if (/nuss|studentenfutter/.test(normalized)) return 'nuts_bowl';
    return 'candy_gummies';
  }

  if (categoryId === 'drugstore') {
    if (/windel|baby|feuchttuch/.test(normalized)) return 'baby';
    if (/toilettenpapier/.test(normalized)) return 'toilet_paper_new';
    if (/taschentuch|kosmetiktuch/.test(normalized)) return 'tissues_box';
    return 'drugstore';
  }

  if (categoryId === 'produce') {
    if (/^knoblauch$/.test(normalized)) return 'garlic';
    if (/^feigen?$/.test(normalized)) return 'figs';
      const direct = [
      ['blueberries',['heidelbeere','blaubeere']],['tomato',['tomate']],['raspberry',['himbeere']],['strawberry',['erdbeere']],
      ['cherry_tomatoes',['cherrytomate','cocktailtomate','tomatenmix']],['banana',['banane']],['apple',['apfel']],['lemon',['zitrone']],
      ['lime',['limette']],['grapes',['traube']],['cucumber',['gurke']],['rucola',['ruccola','rucola']],['potato',['kartoffel']],
      ['carrot',['mohre','moehre','karotte']],['paprika',['paprika']],['broccoli',['brokkoli']],['cauliflower',['blumenkohl']],
      ['iceberg_lettuce',['eisbergsalat','kopfsalat','romanasalat']],['salad_mix',['salat','feldsalat']],['onion',['zwiebel','lauch','fruhlingszwiebel']],
      ['garlic',['knoblauch']],['eggplant',['aubergine']],['zucchini',['zucchini']],['mushroom',['champignon','pilz']],['ginger',['ingwer','kurkuma']]
    ];
    for (const [imageKey,terms] of direct) if (terms.some(term => normalized.includes(normalizeText(term)))) return imageKey;
    return 'produce';
  }

  // Kategorien außerhalb des normalen Supermarktstamms: möglichst semantisch passende lokale Bilder.
  const key = ` ${normalized} `;
  for (const [imageKey, terms] of RULES) {
    if (terms.some((term) => key.includes(normalizeText(term)))) return imageKey;
  }
  return 'misc';
}

function categoryImageKey(category={}) {
  const name = normalizeText(category.name || '');
  const compactName = name.replace(/\s+/g, '');
  if (['meyerhof','meyerhofbelm','meierhof','meierhofbelm','maierhof','maierhofbelm','mayerhof','mayerhofbelm'].includes(compactName)) return 'meyerhof';
  if (['rewe','rewemarkt'].includes(compactName)) return 'rewe';
  if (name.includes('joghurt')) return 'yogurt';
  if (name.includes('theke')) return 'counter';
  if (name.includes('schreib')) return 'stationery';
  if (name.includes('kinder') && name.includes('snack')) return 'sweets';
  if (name.includes('reinig')) return 'household';
  if (name.includes('papier')) return 'household';
  if (name.includes('korperpflege') || name.includes('koerperpflege')) return 'drugstore';
  return CATEGORY_IMAGE_KEYS[category.id] || 'other';
}

module.exports = { imageKeyForProduct, categoryImageKey };
