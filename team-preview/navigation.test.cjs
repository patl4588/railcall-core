// Source-level controller checks; no browser automation or network requests.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { createModel } = require('./model.js');

function harness(path = '/') {
  const nodes = new Map(), handlers = {}, windowHandlers = {}, calls = [];
  const classes = () => { const items = new Set(); return {add:x=>items.add(x),remove:x=>items.delete(x),contains:x=>items.has(x),toggle:(x,on)=>{const yes=on===undefined?!items.has(x):on;yes?items.add(x):items.delete(x);return yes;}}; };
  function node(selector) {
    if (nodes.has(selector)) return nodes.get(selector);
    const n = {value:['#integrationType','#activityCategory','#activityLocation'].includes(selector)?'all':'',hidden:false,checked:false,open:false,textContent:'',innerHTML:'',dataset:{},attributes:{},listeners:{},classList:classes(),
      addEventListener(type,fn){this.listeners[type]=fn;},setAttribute(k,v){this.attributes[k]=v;},removeAttribute(k){delete this.attributes[k];},
      insertAdjacentHTML(_,s){this.innerHTML+=s;},matches(s){return /Input$/.test(selector)&&s==='input,textarea';},focus(){document.activeElement=this;},
      showModal(){this.open=true;},close(){this.open=false;},querySelector(s){return node(selector+' '+s);}};
    nodes.set(selector,n);return n;
  }
  const document={body:node('body'),activeElement:null,querySelector:node,querySelectorAll:()=>[],addEventListener:(type,fn)=>handlers[type]=fn};
  let url=new URL(path,'https://example.test');
  const location={get href(){return url.href;},get pathname(){return url.pathname;},get search(){return url.search;},get hash(){return url.hash;}};
  const history={pushState:(_,__,next)=>{calls.push(next);url=new URL(next,url);},replaceState:(_,__,next)=>{url=new URL(next,url);}};
  const model=createModel();
  const moduleStub={create:()=>({render(){},enter(){},reset(){},openRun(){},openStep(){},showTransactions(){},setType(){},open(){}})};
  const context={document,location,history,URL,URLSearchParams,TextEncoder,console,crypto:require('node:crypto').webcrypto,setTimeout:()=>1,clearTimeout(){},
    window:{scrollTo(){},addEventListener:(name,fn)=>windowHandlers[name]=fn},RailCallModel:{createModel:()=>model},
    RailCallStudio:moduleStub,RailCallActivity:moduleStub,RailCallMarketplace:moduleStub,RailCallLibrary:moduleStub};
  vm.createContext(context);
  vm.runInContext(fs.readFileSync('integration-catalog.js','utf8'),context);
  vm.runInContext(fs.readFileSync('railhub-visuals.js','utf8'),context);
  vm.runInContext(fs.readFileSync('integrations.js','utf8'),context);
  vm.runInContext(fs.readFileSync('builder.js','utf8'),context);
  vm.runInContext(fs.readFileSync('economics.js','utf8'),context);
  vm.runInContext(fs.readFileSync('workspace.js','utf8'),context);
  async function click(dataset) {
    const button={dataset,attributes:{},textContent:'',title:'',setAttribute(k,v){this.attributes[k]=v;},closest:()=>null};
    await handlers.click({target:{closest:selector=>selector==='button'?button:null}});
    return button;
  }
  return {model,node,document,location,calls,click,async submit(text){node('#heroInput').value=text;node('#heroForm').listeners.submit({preventDefault(){}});await Promise.resolve();},backTo(next){url=new URL(next,url);windowHandlers.popstate();}};
}

(async()=>{
  const h=harness();
  assert.equal(h.document.body.classList.contains('is-home'),true);
  assert.equal(h.document.activeElement,null,'initial homepage does not force the keyboard open');
  await h.submit('Summarize support issues <script>alert(1)</script>');
  assert.equal(h.location.search,'?view=chat');
  assert.equal(h.document.body.classList.contains('is-home'),false);
  assert.match(h.model.active().messages[0].text,/<script>/,'exact prompt retained as data');
  assert.doesNotMatch(h.node('#messages').innerHTML,/<script>/,'prompt is escaped in rendered output');
  assert.doesNotMatch(h.location.href,/support|script/,'prompt does not enter URLs');
  assert.doesNotMatch(h.node('#messages').innerHTML,/run-cost-comparison|Download free/,'no savings promotion interrupts the answer');
  assert.match(h.node('#activityPanel').innerHTML,/Online compute/);
  assert.match(h.node('#activityPanel').innerHTML,/On your computer/);
  assert.match(h.node('#activityPanel').innerHTML,/>\$0\.006</);
  assert.match(h.node('#activityPanel').innerHTML,/>\$0\.000</);
  assert.match(h.node('#activityPanel').innerHTML,/https:\/\/railcall\.ai\/downloads\/chat\//);
  assert.match(h.node('#activityPanel').innerHTML,/Download free/);
  assert.match(h.node('#activityPanel').innerHTML,/Browser storage is unavailable/);
  h.node('#activityPanel').listeners.click({target:{closest:()=>({dataset:{econScope:'request'}})}});
  assert.match(h.node('#activityPanel').innerHTML,/Latest request in this conversation/);
  h.node('#activityPanel').listeners.change({target:{hasAttribute:()=>true,value:'100'}});
  assert.match(h.node('#activityPanel').innerHTML,/>\$0\.600</,'editable hourly estimate uses the request savings');
  h.node('#activityPanel').listeners.click({target:{closest:()=>({dataset:{econScope:'lifetime'}})}});
  assert.match(h.node('#activityPanel').innerHTML,/Storage unavailable · this session only/);
  const taskId=h.model.active().id,firstCount=h.model.state.tasks.length;
  await h.click({view:'home'});
  await h.click({view:'chat'});
  assert.equal(h.model.active().id,taskId,'returning to the workspace retains the task');
  await h.click({view:'home'});
  await h.submit('Qualify new leads');
  assert.equal(h.model.state.tasks.length,firstCount+1,'new homepage request starts a separate conversation');
  assert.notEqual(h.model.active().id,taskId);
  await h.click({view:'integrations'});
  assert.match(h.node('#integrationList').innerHTML,/HubSpot/);
  assert.match(h.node('#integrationCount').textContent,/454/);
  h.node('#integrationSearch').value='Zernio';h.node('#integrationSearch').listeners.input();
  assert.match(h.node('#integrationList').innerHTML,/Zernio/);
  assert.match(h.node('#integrationDetail').innerHTML,/Marketplace extension/);
  h.node('#integrationSearch').value='';h.node('#integrationType').value='Reachable app';h.node('#integrationType').listeners.change();
  assert.match(h.node('#integrationCount').textContent,/50 shown · 412 of 454/);
  h.node('#integrationMore').listeners.click();
  assert.match(h.node('#integrationCount').textContent,/100 shown/);
  h.node('#integrationSearch').value='nonexistenttest';h.node('#integrationSearch').listeners.input();
  assert.equal(h.node('#integrationEmpty').hidden,false);
  h.node('#integrationSearch').value='';h.node('#integrationType').value='all';h.node('#integrationType').listeners.change();
  await h.click({source:'hubspot_preview'});
  assert.equal(h.model.active().source,'hubspot_preview');
  assert.match(h.node('#integrationSource').textContent,/no account connected/);
  assert.ok(h.model.state.events.some(e=>e.category==='connection'));
  const collapsed=await h.click({action:'toggle-sidebar'});
  assert.equal(h.node('.shell').classList.contains('sidebar-collapsed'),true);
  assert.equal(collapsed.attributes['aria-expanded'],'false');
  await h.click({action:'toggle-sidebar'});
  assert.equal(h.node('.shell').classList.contains('sidebar-collapsed'),false);
  const count=h.model.state.tasks.length;
  h.node('#heroInput').listeners.keydown({key:'Enter',isComposing:true,currentTarget:{value:'Unfinished'},preventDefault(){throw Error('IME submission blocked incorrectly');}});
  assert.equal(h.model.state.tasks.length,count);
  h.backTo('/?view=builder');assert.equal(h.node('#builderView').hidden,false);
  h.node('#editInput').value='Create a weekly support report';
  h.node('#editForm').listeners.submit({preventDefault(){}});
  assert.ok(h.model.active().draft);
  assert.match(h.node('#workflowChat').innerHTML,/weekly support report/);
  h.node('#builderView').listeners.click({target:{closest:()=>({dataset:{buildMode:'anything'},hasAttribute:()=>false})}});
  assert.equal(h.node('#anythingBuilderPane').hidden,false);
  h.node('#artifactType').value='app';h.node('#artifactInput').value='Build a project planner';
  h.node('#artifactForm').listeners.submit({preventDefault(){}});
  assert.equal(h.model.artifactForTask().draft.kind,'app');
  assert.match(h.node('#artifactCanvas').innerHTML,/project planner/);
  h.backTo('/');assert.equal(h.document.body.classList.contains('is-home'),true);
  for(const name of ['chat','builder','studio','activity','library','studioMap','marketplace','integrations','railhub']){
    const route=harness('/?view='+name);assert.equal(route.node('#'+name+'View').hidden,false,name+' direct route');
  }
  const hub=harness('/?page=railhub');await hub.click({view:'chat'});
  assert.equal(hub.calls[0],'/?view=chat','standalone exit keeps the original history entry');
  console.log('Passed: homepage handoff, safe prompt rendering, task preservation, direct routes, sample integrations, collapsible sidebar, and IME input.');
})().catch(e=>{console.error(e);process.exitCode=1;});
