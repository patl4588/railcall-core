(function(root){
  'use strict';
  const fields=['count','online','local','saved','premium'];
  const blank=()=>({count:0,online:0,local:0,saved:0,premium:0});
  const empty=()=>({...blank(),builds:0,types:{chat:blank(),workflow:blank()}});
  const round=n=>Number(n.toFixed(6));
  const sum=(a,b)=>{fields.forEach(k=>a[k]=round(a[k]+b[k]));return a;};
  function summarize(runs,builds=0){
    const total=empty();total.builds=builds;
    runs.forEach(run=>{
      const c=run.cost_comparison;if(!c)return;
      const value={count:1,online:c.online_usd,local:c.local_usd,saved:run.mode==='desktop'?c.savings_usd:0,premium:c.premium_usd};
      sum(total,value);sum(total.types[run.workflow_snapshot?'workflow':'chat'],value);
    });
    return total;
  }
  function valid(value){
    const validRow=r=>r&&fields.every(k=>Number.isFinite(r[k])&&r[k]>=0)&&Number.isInteger(r.count);
    return validRow(value)&&Number.isInteger(value.builds)&&value.builds>=0&&value.types&&validRow(value.types.chat)&&validRow(value.types.workflow);
  }
  function createTracker(storage,sessionId){
    const prefix='railcall.savings.v1.',key=prefix+sessionId;let last='',available=Boolean(storage);
    return {update(current){
      const result=empty();sum(result,current);result.builds=current.builds;sum(result.types.chat,current.types.chat);sum(result.types.workflow,current.types.workflow);
      if(storage)try{
        const payload=JSON.stringify({version:1,totals:current});
        if((current.count||current.builds)&&payload!==last){storage.setItem(key,payload);last=payload;}
        for(let i=0;i<storage.length;i++){
          const itemKey=storage.key(i);if(!itemKey||itemKey===key||!itemKey.startsWith(prefix))continue;
          let row;try{row=JSON.parse(storage.getItem(itemKey));}catch{continue;}
          if(row?.version!==1||!valid(row.totals))continue;
          sum(result,row.totals);result.builds+=row.totals.builds;sum(result.types.chat,row.totals.types.chat);sum(result.types.workflow,row.totals.types.workflow);
        }
        available=true;
      }catch{available=false;}
      return {totals:available?result:current,available};
    }};
  }
  function create({model:app}){
    const panel=document.querySelector('#activityPanel'),money=n=>'$'+Number(n).toFixed(3),download='https://railcall.ai/downloads/chat/';
    let storage;try{storage=typeof localStorage==='undefined'?null:localStorage;}catch{storage=null;}
    const sessionId=typeof crypto.randomUUID==='function'?crypto.randomUUID():Date.now()+'-'+Math.random().toString(36).slice(2);
    const tracker=createTracker(storage,sessionId);let scope='session',rate=20;
    let expanded=typeof window.matchMedia==='function'?window.matchMedia('(min-width:1101px)').matches:true;
    const helps=new Set();
    function render(){
      const session=summarize(app.state.runs,app.state.artifacts.length);
      const history=tracker.update(session);
      const latest=app.runForTask().slice(-1)[0];
      const total=scope==='request'?summarize(latest?[latest]:[]):scope==='lifetime'?history.totals:session;
      const potential=round(total.online-total.local);
      const current=app.compareCosts(app.active().premium,app.active().source);
      const perRequest=total.count?potential/total.count:current.savings_usd;
      const hourly=perRequest*rate;
      const desc=scope==='request'?'Latest request in this conversation':scope==='lifetime'?(history.available?'Since tracking began on this browser':'Storage unavailable · this session only'):'All sample runs in this page session';
      const help=(id,title,body)=>'<details class="ec-help" data-help="'+id+'"'+(helps.has(id)?' open':'')+'><summary>'+title+'</summary>'+body+'</details>';
      const typeRow=(label,row)=>'<div class="ec-type"><span><b>'+label+'</b><small>'+row.count+' sample run'+(row.count===1?'':'s')+'</small></span><strong>'+money(row.online-row.local)+'</strong><a href="'+download+'" target="_blank" rel="noopener noreferrer" aria-label="Download RailCall for '+label+'">Download ↗</a></div>';
      panel.classList.add('compute-sidebar');
      panel.innerHTML='<details class="ec-panel" data-economics-panel'+(expanded?' open':'')+'><summary><span><b>Your compute advantage</b><small>Live preview calculator</small></span><span class="ec-summary-value">'+money(potential)+' <i>⌄</i></span></summary><div class="ec-body">'+
        '<div class="ec-tabs" aria-label="Savings period">'+[['request','Request'],['session','Session'],['lifetime','Lifetime']].map(([id,label])=>'<button data-econ-scope="'+id+'" aria-pressed="'+(scope===id)+'">'+label+'</button>').join('')+'</div>'+
        '<div class="ec-total" aria-live="polite"><span>Potential local savings</span><strong>'+money(potential)+'</strong><small>'+desc+'</small></div>'+
        '<div class="ec-comparison"><div><span>Online compute</span><b>'+money(total.online)+'</b></div><div><span>On your computer</span><b>'+money(total.local)+'</b></div></div>'+
        '<div class="ec-saved"><span>Saved in local scenarios</span><b>'+money(total.saved)+'</b></div>'+
        '<p class="ec-caption">'+(total.count?total.count+' run'+(total.count===1?'':'s')+' · same workload and premium policy. Potential savings include the local-scenario savings above.':'No run in this selection yet. Send a request to start tracking.')+'</p>'+
        '<a class="ec-download" href="'+download+'" target="_blank" rel="noopener noreferrer">↓ Download free <span>Use your own compute ↗</span></a>'+
        '<section class="ec-hourly"><div><span>Projected savings / hour</span><strong>'+money(hourly)+'</strong></div><label>At <input data-hourly-rate type="number" min="1" max="10000" step="1" value="'+rate+'" aria-label="Requests per hour for savings projection"> requests / hour</label><p class="ec-caption">'+(total.count?'Based on this selection’s average savings per run.':'Based on the current sample route.')+' A projection—not money saved while idle.</p></section>'+
        '<section class="ec-types"><h3>Potential savings by work type</h3>'+typeRow('Chat',total.types.chat)+typeRow('Workflows',total.types.workflow)+'<div class="ec-type"><span><b>Anything builds</b><small>'+total.builds+' build'+(total.builds===1?'':'s')+' · not metered</small></span><strong>—</strong><a href="'+download+'" target="_blank" rel="noopener noreferrer" aria-label="Download RailCall for anything builds">Download ↗</a></div></section>'+
        '<div class="ec-benefits">'+
        help('cost','Why local compute costs less','<p>Your hardware handles eligible model work, avoiding the hosted serving charge. Premium APIs and connected services can still cost money.</p><p>Premium API charges in this selection: <b>'+money(total.premium)+'</b>. These stay in the local comparison.</p><button class="text-button" data-dialog="compute">Compare routing options →</button>')+
        help('control','What you control locally','<p>Choose compatible models, keep files and credentials in your runtime, and decide which tools or external routes may access your data. Local execution does not prevent an approved connector from sending data out.</p><button class="text-button" data-dialog="connections">Sources & permissions →</button>')+
        help('build','Build beyond a chat answer','<p>Make pages, apps, documents, and reusable workflows. Bring your models and tools, keep versions, and inspect actions in Studio. Hardware, model capabilities, licenses, and setup still apply.</p><button class="text-button" data-view="builder">Open Builder →</button>')+
        help('numbers','How these numbers are calculated','<p>Each run keeps its original online/local comparison. Switching settings does not rewrite earlier runs. The hourly estimate is savings per request multiplied by your chosen rate.</p><p>All figures are illustrative model/serving charges—not invoices, verified real-world savings, or total ownership costs. Hardware and electricity are excluded. The 90% local-handling target is not used in these calculations.</p><button class="text-button" data-view="activity">See the run ledger →</button>')+
        '</div><p class="ec-storage">'+(history.available?'Lifetime totals are saved on this browser only; they are not account-wide. Only aggregate demo counts and amounts are stored—no prompts or answers. Clearing site data resets them.':'Browser storage is unavailable. Only this session is counted.')+'</p></div></details>';
    }
    panel.addEventListener('click',event=>{const b=event.target.closest('[data-econ-scope]');if(b){scope=b.dataset.econScope;render();}});
    panel.addEventListener('change',event=>{if(event.target.hasAttribute('data-hourly-rate')){const n=Number(event.target.value);rate=Number.isFinite(n)?Math.max(1,Math.min(10000,Math.round(n))):20;render();}});
    panel.addEventListener('toggle',event=>{if(event.target.hasAttribute('data-economics-panel'))expanded=event.target.open;else if(event.target.dataset.help)event.target.open?helps.add(event.target.dataset.help):helps.delete(event.target.dataset.help);},true);
    window.addEventListener('storage',event=>{if(!event.key||event.key.startsWith('railcall.savings.v1.'))render();});
    return {render};
  }
  root.RailCallEconomics={create,summarize,createTracker};
  if(typeof module!=='undefined'&&module.exports)module.exports={summarize,createTracker};
})(globalThis);
