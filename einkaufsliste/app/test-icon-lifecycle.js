const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'icon-lifecycle-'));
process.env.DATA_DIR = dir;
process.env.DATA_FILE = path.join(dir,'shopping-list.json');
process.env.BACKUP_DIR = path.join(dir,'backups');
fs.writeFileSync(path.join(dir,'options.json'), JSON.stringify({gemini_api_key:'test-only'}));
const app = require('./server');
let calls=0;
global.fetch=async(url)=>{
 if(String(url).includes('ecb.europa.eu')) return {ok:true,text:async()=>`<Cube time="2026-09-10"><Cube currency="USD" rate="1.1550"/></Cube>`};
 calls++;
 const b=Buffer.alloc(5000); b.set([137,80,78,71,13,10,26,10]);
 return {ok:true,json:async()=>({outputs:[{type:'image',data:b.toString('base64')}],usage:{total_input_tokens:100,total_output_tokens:1120,total_thought_tokens:20,output_tokens_by_modality:[{modality:'image',tokens:1120}]}})};
};
const product=name=>app.publicState().products.find(p=>p.name===name && !p.sourceTag);
test.after(()=>fs.rmSync(dir,{recursive:true,force:true}));

test('approved local icons exist and skip generation',()=>{
 for(const file of Object.values(require('./processed-icons.json')))
  assert.ok(fs.existsSync(path.join(__dirname,'assets/product-images',file)),file);
 const before=calls;
 app.addEntry('Apfel');
 assert.equal(calls,before);
 assert.equal(product('Apfel').iconEditStatus,'processed');
});

test('existing unprocessed master articles generate exactly once when used and then stay processed',async()=>{
 const before=calls;
 assert.equal(product('Rucola').iconEditStatus,'unprocessed');
 const first=app.addEntry('Rucola');
 assert.equal(first.createdProduct,false);
 await app.processCreatedProduct(first);
 assert.equal(product('Rucola').iconEditStatus,'processed');
 assert.equal(product('Rucola').imageSource,'gemini');
 assert.equal(calls,before+1);
 const duplicate=app.addEntry('2 Rucola');
 assert.equal(duplicate.duplicate,true);
 await app.processCreatedProduct(duplicate);
 assert.equal(product('Rucola').iconEditStatus,'processed');
 assert.equal(calls,before+1);
});

test('unprocessed category variant reuses an already processed sibling without another Gemini call',async()=>{
 const source=product('Rucola');
 assert.equal(source.iconEditStatus,'processed');
 const target={id:'product-rucola-firma-test',key:'rucola firma',name:'Rucola',categoryId:'firma-test',aliases:['rucola'],sourceTag:'category:firma-test',imageSource:'catalog',iconEditStatus:'unprocessed'};
 const list={products:[source,target],categories:[{id:'produce',name:'Obst und Gemüse'},{id:'firma-test',name:'Firma (extra Rechnung)'}]};
 const before=calls;
 await app.ensureProductImageOnUse(target,list);
 assert.equal(target.iconEditStatus,'processed');
 assert.equal(target.imageSource,'inherited');
 assert.equal(target.imageInheritedFromProductId,source.id);
 assert.equal(calls,before);
});

test('a newly generated image is propagated to all unprocessed variants of the same base article',async()=>{
 const source={id:'product-testzucker-normal',key:'testzucker',name:'Testzucker',categoryId:'baking',aliases:['testzucker'],imageSource:'catalog',iconEditStatus:'unprocessed'};
 const target={id:'product-testzucker-firma',key:'testzucker firma',name:'Testzucker',categoryId:'firma-test',aliases:['testzucker'],sourceTag:'category:firma-test',imageSource:'catalog',iconEditStatus:'unprocessed'};
 const list={products:[source,target],categories:[{id:'baking',name:'Backzutaten'},{id:'firma-test',name:'Firma (extra Rechnung)'}]};
 const before=calls;
 await app.ensureProductImageOnUse(source,list);
 assert.equal(calls,before+1);
 assert.equal(source.iconEditStatus,'processed');
 assert.equal(source.imageSource,'gemini');
 assert.equal(target.iconEditStatus,'processed');
 assert.equal(target.imageSource,'inherited');
 assert.equal(target.imageInheritedFromProductId,source.id);
});

test('quantity and known catalog classification survive existing-master reuse',()=>{
 const r=app.addEntry('Gemüse 1,65 kg');
 assert.equal(r.createdProduct,false);
 assert.equal(r.entry.quantity,null);
 assert.equal(r.entry.productDetail,'1,65 kg');
 assert.equal(product('Gemüse').categoryId,'produce');
});

test('interrupted processing is reset during migration',()=>{
 const s=app.initialState();s.products[0].iconEditStatus='processing';
 s.lists[0].products=s.products;
 assert.equal(app.migrateState(s).products[0].iconEditStatus,'unprocessed');
});

test('catalog upgrade retains IDs favorites recent and user quantities',()=>{
 const s=app.initialState();const p=s.products.find(p=>p.name==='Hefe');p.favorite=true;p.useCount=9;s.lists[0].products=s.products;
 const e={id:'preserved-entry',productId:p.id,productKey:p.key,name:p.name,quantity:{value:1.65,unit:'kg',userEdited:true},categoryId:p.categoryId};
 s.lists[0].entries=[e];s.lists[0].recent=[{...e,id:'preserved-recent'}];
 const migrated=app.migrateState(s);
 assert.deepEqual(migrated.entries,[e]);assert.equal(migrated.recent[0].id,'preserved-recent');
 assert.equal(migrated.products.find(x=>x.id===p.id).favorite,true);
 assert.equal(migrated.products.find(x=>x.id===p.id).useCount,9);
});

test('manual product icon upload stays local and does not add Gemini usage',()=>{
 const p=product('Rucola');
 const beforeCalls=calls;
 const beforeUsage=app.publicState().geminiImageUsage.totalImages;
 const b=Buffer.alloc(5000);b.set([137,80,78,71,13,10,26,10]);
 const saved=app.saveUploadedProductImage(p.id,'data:image/png;base64,'+b.toString('base64'));
 assert.equal(saved.imageSource,'upload');
 assert.equal(saved.iconEditStatus,'processed');
 assert.ok(saved.generatedImage.startsWith('generated-product-images/'));
 assert.ok(fs.existsSync(path.join(dir,saved.generatedImage.replace('generated-product-images/','product-images/'))));
 assert.equal(calls,beforeCalls);
 assert.equal(app.publicState().geminiImageUsage.totalImages,beforeUsage);
});

test('manual category icon upload stays local and does not add Gemini usage',()=>{
 const c=app.publicState().categories.find(c=>c.id==='produce');
 const beforeCalls=calls;
 const beforeUsage=app.publicState().geminiImageUsage.totalImages;
 const b=Buffer.alloc(5000);b.set([137,80,78,71,13,10,26,10]);
 const saved=app.saveUploadedCategoryImage(c.id,'data:image/png;base64,'+b.toString('base64'));
 assert.equal(saved.imageSource,'upload');
 assert.ok(saved.generatedImage.startsWith('generated-category-images/'));
 assert.ok(fs.existsSync(path.join(dir,saved.generatedImage.replace('generated-category-images/','category-images/'))));
 assert.equal(calls,beforeCalls);
 assert.equal(app.publicState().geminiImageUsage.totalImages,beforeUsage);
});

test('manual icon upload rejects invalid image bytes',()=>{
 const b=Buffer.alloc(5000,7);
 assert.throws(()=>app.decodeUploadedIcon('data:image/png;base64,'+b.toString('base64')),/gültiges PNG/);
});
