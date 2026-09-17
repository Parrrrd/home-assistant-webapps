const { normalizeText } = require('./core');
const { inferVisual } = require('./visual');

function keyFor(name){return normalizeText(name).replace(/\s+/g,'-').replace(/[^a-z0-9-]/g,'').replace(/-+/g,'-').replace(/^-|-$/g,'')||'artikel';}
function rows(categoryId, names){return names.map(name=>({id:`product-${keyFor(name)}`,key:keyFor(name),name,categoryId,icon:'📦',aliases:[name.toLowerCase()],...inferVisual(name,categoryId)}));}

const groups = {
  produce: [
    'Mango','Ananas','Kiwi','Limette','Mandarinen','Clementinen','Pfirsiche','Nektarinen','Pflaumen','Aprikosen','Granatapfel','Wassermelone','Honigmelone','Galiamelone','Himbeeren','Brombeeren','Johannisbeeren','Stachelbeeren','Preiselbeeren','Feigen frisch','Datteln frisch','Kaki','Maracuja','Passionsfrucht','Grapefruit','Pomelo','Rhabarber','Aubergine','Blumenkohl','Rosenkohl','Grünkohl','Wirsing','Weißkohl','Rotkohl','Chinakohl','Pak Choi','Lauch','Frühlingszwiebeln','Sellerie','Knollensellerie','Fenchel','Radieschen','Rettich','Rote Bete','Süßkartoffeln','Kürbis','Hokkaido','Butternut-Kürbis','Spargel','Grüne Bohnen','Zuckerschoten','Erbsen frisch','Maiskolben','Chili','Ingwer','Kurkuma frisch','Petersilie','Schnittlauch','Basilikum','Koriander','Minze','Dill','Rosmarin','Thymian','Feldsalat','Rucola','Eisbergsalat','Kopfsalat','Romanasalat','Tomatenmix','Cherrytomaten','Cocktailtomaten','Snackgurken'
  ],
  vegetarian: [
    'Tempeh','Seitan','Räuchertofu','Tofu mediterran','Tofu geräuchert','Vegane Nuggets','Vegane Burger','Vegane Frikadellen','Vegane Cevapcici','Vegane Mortadella','Vegane Lyoner','Vegane Leberwurst','Vegane Teewurst','Vegane Fleischwurst','Vegane Bolognese','Vegane Mayo','Vegane Sahne','Vegane Crème fraîche','Sojajoghurt','Haferjoghurt','Kichererbsen','Weiße Bohnen','Kidneybohnen','Schwarze Bohnen','Belugalinsen','Rote Linsen','Grüne Linsen','Couscous-Salat vegetarisch','Bulgur-Salat vegetarisch','Veggie-Gyros'
  ],
  bakery_fitness: [
    'Vollkornbrot','Mehrkornbrot','Roggenbrot','Dinkelbrot','Eiweißbrot','Knäckebrot','Toast Vollkorn','Sandwichtoast','Burger Buns','Hotdog-Brötchen','Laugenbrezeln','Laugenstangen','Ciabatta','Fladenbrot','Wraps','Tortilla-Wraps','Pita','Naan','Zwieback','Reiswaffeln','Maiswaffeln','Müsliriegel','Hafer-Riegel','Nussriegel','Protein-Cookie','Proteinpudding','Proteindrink','Erdnussbutter','Mandelmus','Honig','Marmelade','Konfitüre','Fruchtaufstrich','Erdnusscreme','Tahini','Ahornsirup'
  ],
  baking: [
    'Weizenmehl Type 405','Weizenmehl Type 550','Weizenmehl Type 1050','Dinkelmehl Type 630','Dinkelmehl Type 1050','Roggenmehl Type 1150','Vollkornmehl','Hartweizengrieß','Weichweizengrieß','Paniermehl','Semmelbrösel','Natron','Trockenhefe','Frische Hefe','Vanilleextrakt','Vanillepaste','Vanilleschote','Backkakao','Kakaopulver','Speisestärke Mais','Kartoffelstärke','Gelatine','Agar Agar','Kuvertüre Zartbitter','Kuvertüre Vollmilch','Kuvertüre Weiß','Schokotropfen','Backschokolade','Mandeln gemahlen','Mandeln gehobelt','Haselnüsse gemahlen','Walnüsse','Pekannüsse','Cashewkerne','Kokosraspeln','Rosinen','Sultaninen','Zimt','Lebkuchengewürz','Puderzucker','Rohrzucker','Brauner Zucker','Hagelzucker','Sahnesteif'
  ],
  milk: [
    'Vollmilch frisch','Fettarme Milch frisch','Buttermilch','Kefir','Naturjoghurt','Griechischer Joghurt','Fruchtjoghurt','Vanillejoghurt','Joghurt 0,1 %','Joghurt 1,5 %','Skyr natur','Magerquark','Speisequark 20 %','Speisequark 40 %','Schmand','Saure Sahne','Crème légère','Kochsahne 15 %','Schlagsahne','Sprühsahne','Milchreis gekühlt','Pudding Vanille','Pudding Schokolade','Protein-Joghurt','Protein-Quark','Mascarpone','Ricotta','Buttermilch Drink'
  ],
  canned: [
    'Passierte Tomaten','Gehackte Tomaten','Geschälte Tomaten','Tomaten in Stücken','Mais Dose','Kidneybohnen Dose','Weiße Bohnen Dose','Kichererbsen Dose','Erbsen Dose','Möhren Dose','Erbsen und Möhren','Linsen Dose','Thunfisch in Öl','Thunfisch im eigenen Saft','Sardinen','Makrelenfilet Dose','Champignons Dose','Mandarinen Dose','Pfirsiche Dose','Ananas Dose','Kokosmilch Dose','Ravioli Dose','Linsensuppe Dose','Erbsensuppe Dose','Gulaschsuppe Dose','Eingelegte Jalapeños','Eingelegte Peperoni','Oliven grün','Oliven schwarz','Kapern','Artischockenherzen','Rote Bete Glas','Sauerkraut Glas','Rotkohl Glas','Apfelmus Glas'
  ],
  pasta_rice: [
    'Spaghetti','Penne','Fusilli','Tagliatelle','Linguine','Makkaroni','Lasagneplatten','Suppennudeln','Dinkelnudeln','Vollkornnudeln','Glasnudeln','Mie-Nudeln','Reis Basmati','Reis Jasmin','Langkornreis','Milchreis trocken','Risottoreis','Wildreis','Naturreis','Couscous','Bulgur','Quinoa','Polenta','Kartoffelpüree Pulver','Semmelknödel','Kartoffelknödel'
  ],
  oils_sauces: [
    'Sonnenblumenöl','Rapsöl','Kokosöl','Sesamöl','Balsamico','Balsamico Bianco','Apfelessig','Weißweinessig','Rotweinessig','Sojasauce hell','Sojasauce dunkel','Teriyakisauce','Sweet-Chili-Sauce','Sriracha','BBQ-Sauce','Cocktailsauce','Remoulade','Aioli','Curryketchup','Tomatenketchup','Mayonnaise leicht','Senf mittelscharf','Dijon-Senf','Honigsenf','Pesto Rosso','Pesto Genovese','Ajvar','Sambal Oelek','Tahini Sauce','Erdnusssauce','Currypaste rot','Currypaste grün','Bratensauce','Sauce Hollandaise','Salatdressing Joghurt','Salatdressing Kräuter'
  ],
  cheese: [
    'Gouda jung','Gouda mittelalt','Gouda gerieben','Emmentaler','Emmentaler gerieben','Mozzarella Kugel','Mozzarella gerieben','Büffelmozzarella','Parmesan Stück','Parmesan gerieben','Grana Padano','Feta Schafskäse','Hirtenkäse','Frischkäse natur','Frischkäse Kräuter','Körniger Frischkäse','Camembert','Brie','Blauschimmelkäse','Cheddar','Cheddar Scheiben','Toastkäse','Scheibenkäse','Raclettekäse','Ziegenkäse','Halloumi'
  ],
  household: [
    'Müllbeutel 10 l','Müllbeutel 25 l','Müllbeutel 60 l','Müllbeutel 120 l','Gefrierbeutel 1 l','Gefrierbeutel 3 l','Frischhaltefolie','Backpapier Bögen','Alufolie extra stark','Küchenrolle','Spülschwämme','Topfreiniger','Spülbürste','Geschirrtücher','Mikrofasertücher','Allzwecktücher','Spülmaschinentabs','Spülmaschinenpulver','Spülmaschinen-Klarspüler','Spülmaschinensalz','Handspülmittel','Allzweckreiniger','Badreiniger','Glasreiniger','Küchenreiniger','WC-Reiniger','Entkalker','Rohrreiniger','Bodenreiniger','Waschmittel Color','Waschmittel Vollwaschmittel','Feinwaschmittel','Wollwaschmittel','Weichspüler','Fleckenspray','Wäsche-Desinfektion'
  ],
  milk_uncooled: [
    'H-Milch 1,5 %','H-Milch 3,5 %','Laktosefreie H-Milch','Haferdrink','Haferdrink Barista','Mandeldrink','Sojadrink','Kokosdrink','Reisdrink','Kondensmilch 4 %','Kondensmilch 7,5 %','Kaffeesahne 10 %','Kaffeesahne 12 %','Milchpulver','Kaffeeweißer'
  ],
  ready_chilled: [
    'Butter gesalzen','Margarine','Halbfettmargarine','Flammkuchenteig','Pizzateig','Blätterteig','Quicheteig','Frische Gnocchi','Frische Tortellini','Frische Ravioli','Maultaschen vegetarisch','Maultaschen Fleisch','Fertigsalat','Kartoffelsalat','Nudelsalat','Fertigpizza gekühlt','Frische Pasta','Käsespätzle gekühlt','Schupfnudeln','Kartoffelpuffer gekühlt'
  ],
  frozen: [
    'TK-Heidelbeeren','TK-Himbeeren','TK-Erdbeeren','TK-Beerenmix','TK-Mango','TK-Kirschen','TK-Spinat','TK-Brokkoli','TK-Blumenkohl','TK-Erbsen','TK-Bohnen','TK-Mais','TK-Gemüsemix','TK-Wokgemüse','TK-Suppengemüse','TK-Kräuter','TK-Pommes','TK-Kroketten','TK-Rösti','TK-Kartoffelspalten','TK-Pizza Margherita','TK-Pizza Salami','TK-Flammkuchen','TK-Fischstäbchen','TK-Lachs','TK-Garnelen','TK-Hähnchen','TK-Nuggets','TK-Baguettes','TK-Brötchen'
  ],
  meat: [
    'Hähnchenbrust','Hähnchengeschnetzeltes','Hähnchenschenkel','Putenbrust','Putengeschnetzeltes','Rinderhack','Gemischtes Hackfleisch','Schweinehack','Rindersteak','Schweineschnitzel','Nackensteak','Bratwurst','Bockwurst','Wiener Würstchen','Fleischwurst','Kochschinken','Rohschinken','Krustenschinken','Serrano-Schinken','Salami Scheiben','Bacon Würfel','Bacon Scheiben','Leberwurst fein','Teewurst','Mortadella','Geflügelaufschnitt','Schinkenwürfel','Gulasch','Rouladen','Frikadellen'
  ],
  drinks: [
    'Mineralwasser still','Mineralwasser medium','Mineralwasser classic','Apfelsaft naturtrüb','Orangensaft','Multivitaminsaft','Traubensaft','Kirschsaft','Apfelschorle','Cola Zero','Cola','Fanta','Sprite','Orangenlimonade','Zitronenlimonade','Eistee Pfirsich','Eistee Zitrone','Energy-Drink Zero','Kaffee Bohnen','Kaffee gemahlen','Espresso Bohnen','Kaffeepads','Kaffeekapseln','Schwarzer Tee','Grüner Tee','Früchtetee','Kräutertee','Kakao Getränk','Malzbier','Alkoholfreies Bier'
  ],
  sweets: [
    'Vollmilchschokolade','Zartbitterschokolade','Weiße Schokolade','Schokoriegel','Kinder Riegel','Kinder Bueno','Kinder Pingui','Duplo','Hanuta','Gummibärchen','Lakritz','Bonbons','Hustenbonbons','Karamellbonbons','Kekse Butter','Cookies','Waffeln','Prinzenrolle','Chips Paprika','Chips Salz','Tortilla Chips','Erdnussflips','Salzstangen','Popcorn','Nüsse geröstet','Studentenfutter','Marshmallows','Eiswaffeln'
  ],
  drugstore: [
    'Shampoo sensitiv','Shampoo Kinder','Spülung Haare','Haarkur','Duschgel sensitiv','Duschgel Kinder','Flüssigseife','Handseife','Intimwaschlotion','Deo Spray','Deo Roller','Rasierschaum','Rasiergel','Einwegrasierer','Zahnpasta sensitiv','Zahnpasta Kinder','Zahnbürste weich','Zahnbürstenköpfe','Zahnseide','Interdentalbürsten','Mundspülung','Toilettenpapier','Taschentücher Box','Taschentücher Packung','Kosmetiktücher','Wattepads','Wattestäbchen','Tampons normal','Tampons super','Binden','Slipeinlagen','Windeln Größe 4','Windeln Größe 5','Feuchttücher','Babyshampoo','Babyduschgel','Sonnencreme','Handcreme','Bodylotion','Lippenpflege'
  ],
  ice_cream: [
    'Vanilleeis','Schokoladeneis','Erdbeereis','Stracciatellaeis','Ben & Jerry’s','Magnum Mandel','Magnum Classic','Cornetto','Wassereis','Sorbet Zitrone','Sorbet Mango','Eiswürfel Beutel'
  ]
};

const extras = Object.entries(groups).flatMap(([category,names])=>rows(category,names.slice(0,18)));
const seen = new Set();
module.exports = extras.filter(item=>{if(seen.has(item.key))return false;seen.add(item.key);return true;});
