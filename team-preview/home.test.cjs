// Local, source-level interactions: no browser automation or network.
const assert=require('node:assert/strict');
const vm=require('node:vm');
const fs=require('node:fs');
function node(dataset={}){return {dataset,attributes:{},textContent:'',checked:false,hidden:false,listeners:{},selected:false,
  classList:{toggle(name,on){this[name]=on;}},setAttribute(k,v){this.attributes[k]=v;},addEventListener(k,f){this.listeners[k]=f;},
  querySelector(){return this.status||(this.status=node());}};}
const routes=['local','team','web'].map(routeExample=>node({routeExample}));
const destinations=['local','team','web','premium'].map(routeNode=>node({routeNode}));
const theater=['studio','workflows','receipts'].map(theater=>node({theater}));
const ids=Object.fromEntries(['routePremium','routeEyebrow','routeTitle','routeDescription','theaterStudio','theaterWorkflows','theaterReceipts'].map(id=>['#'+id,node()]));
const ctx={document:{querySelector:id=>ids[id],querySelectorAll:s=>({'[data-route-example]':routes,'[data-route-node]':destinations,'[data-theater]':theater}[s])}};
vm.runInNewContext(fs.readFileSync('home.js','utf8'),ctx);
routes[1].listeners.click();
assert.match(ids['#routeTitle'].textContent,/team server/);
assert.equal(destinations[1].classList['is-selected'],true);
assert.equal(destinations[3].classList['is-selected'],false);
ids['#routePremium'].checked=true;ids['#routePremium'].listeners.change();
assert.equal(destinations[3].classList['is-selected'],true);
assert.match(ids['#routeDescription'].textContent,/content leaves this compute boundary/);
routes[2].listeners.click();assert.match(ids['#routeDescription'].textContent,/metered/);
ids['#routePremium'].checked=false;routes[0].listeners.click();
assert.match(ids['#routeDescription'].textContent,/charges are \$0/);
assert.equal(destinations[3].classList['is-selected'],false);
theater[1].listeners.click();
assert.equal(ids['#theaterWorkflows'].hidden,false);assert.equal(ids['#theaterStudio'].hidden,true);
assert.equal(theater[1].attributes['aria-pressed'],'true');
theater[2].listeners.click();assert.equal(ids['#theaterReceipts'].hidden,false);assert.equal(ids['#theaterWorkflows'].hidden,true);
theater[0].listeners.click();assert.equal(ids['#theaterStudio'].hidden,false);assert.equal(ids['#theaterReceipts'].hidden,true);
const html=fs.readFileSync('index.html','utf8');
for(const service of ['uptime','routing','ledger','library']){
  const visual=require('./railhub-visuals.js').render(service);
  assert.equal(html.split(visual).length-1,2,'matching native service visual on home and in app');
  assert.match(visual,/role="img"/);
  assert.match(visual,/Example/);
  assert.doesNotMatch(visual,/<img/);
}
assert.equal(require('./railhub-visuals.js').render('__proto__'),'');
assert.doesNotMatch(html,/src=".\/assets\/railhub-.*\.png"/);
assert.doesNotMatch(html,/intelligence-hero-v1|optical fibers|sculpture/,'rejected generated artwork is not used');
assert.match(html,/hero-intelligence[\s\S]*?assets\/current-workspace.png/,'hero uses the current web workspace screenshot');
for(const asset of ['current-workspace.png','hero-workspace.png','real-workflow-library.png','real-studio-receipt.png'])assert.ok(fs.existsSync('assets/'+asset));
console.log('Passed: three compute routes, explicit premium boundary, suite theater, and four product-native service visuals in home/app.');
