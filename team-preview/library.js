(function(root){
  'use strict';
  function create(options){
    const app=options.model,$=s=>document.querySelector(s);
    const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let selectedId=null, selectedVersion=null, tab='visual', search='',origin='all';
    const latest=w=>w.versions[w.versions.length-1];
    const runsFor=w=>app.state.runs.filter(r=>r.workflow_id===w.id);
    const status=w=>{const runs=runsFor(w);return runs.some(r=>r.status==='awaiting_demo_approval')?'Needs review':runs.length?runs.at(-1).status==='cancelled_preview'?'Stopped':'Completed':'Not run';};
    function render(){
      const w=app.state.workflows.find(w=>w.id===selectedId);
      $('#libraryListPane').hidden=!!w;$('#libraryDetailPane').hidden=!w;
      if(w){renderDetail(w);return;}
      const items=app.state.workflows.filter(w=>{const v=latest(w),example=!!v.provenance;return (origin==='all'||origin==='examples'&&example||origin==='created'&&!example)&&[v.name,v.id,v.provenance?.publisher||''].join(' ').toLowerCase().includes(search);}).sort((a,b)=>latest(a).name.localeCompare(latest(b).name));
      $('#libraryCount').textContent=items.length+' workflows';
      $('#libraryRows').innerHTML=items.map(w=>{const v=latest(w),s=status(w),r=runsFor(w).at(-1);return '<tr><td><button class="lib-name" data-library-open="'+w.id+'"><span class="lib-glyph">◇</span><span><b>'+esc(v.name)+'</b><small>'+esc(v.id)+' · '+(v.provenance?'Studio example':'Created here')+'</small></span></button></td><td><span class="lib-status '+(s==='Needs review'?'waiting':'')+'">'+s+'</span><small>'+v.steps.length+' steps · '+(r?runsFor(w).length+' runs':'No run yet')+'</small></td><td><button class="lib-version" data-library-version="'+w.id+'" title="Version history and workflow fingerprint"># v'+v.version+'</button><small>'+esc(v.trigger)+'</small></td><td class="lib-row-actions"><button class="primary" data-library-run="'+w.id+'">▷ Run</button><button class="secondary" data-library-open="'+w.id+'">Visual</button><button class="text-button" data-library-edit="'+w.id+'">Edit</button></td></tr>';}).join('');
      $('#libraryEmpty').hidden=items.length>0;
      $('#libraryStarters').innerHTML=app.catalog.filter(p=>p.category==='workflows').map(p=>'<div class="lib-starter"><span class="lib-glyph">◇</span><div><b>'+esc(p.name)+'</b><small>Built-in preview template · no public package installation</small></div><button class="secondary" data-library-template="'+p.id+'">Add to library</button></div>').join('');
    }
    function renderDetail(w){
      const v=w.versions.find(v=>v.version_id===selectedVersion)||latest(w);selectedVersion=v.version_id;
      $('#libraryDetailHeading').innerHTML='<button class="text-button" data-library-back>← All workflows</button><div class="lib-detail-title"><div><p class="eyebrow">WORKFLOW / '+esc(v.provenance?'STUDIO EXAMPLE':'YOUR WORKSPACE')+'</p><h1>'+esc(v.name)+'</h1><p>'+esc(v.id)+' · v'+v.version+' · unsigned preview</p></div><div class="lib-detail-actions"><button class="secondary" data-library-edit="'+w.id+'">Edit draft</button><button class="primary" data-library-run="'+w.id+'" data-library-run-version="'+v.version_id+'">▷ Run v'+v.version+'</button></div></div>';
      document.querySelectorAll('[data-library-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.libraryTab===tab)));
      const allRuns=runsFor(w),runs=allRuns.filter(r=>r.workflow_version_id===v.version_id);
      let html='';
      if(tab==='visual')html='<div class="lib-visual-layout"><div class="lib-flow"><header><h2>Workflow visual</h2><span>Saved v'+v.version+' · read-only</span></header><ol>'+v.steps.map((s,i)=>'<li><span class="lib-step-number">'+String(i+1).padStart(2,'0')+'</span><div><small>'+esc(s.kind.toUpperCase())+'</small><h3>'+esc(s.title)+'</h3><p>'+esc(s.detail)+'</p></div></li>').join('')+'</ol></div><aside class="lib-summary"><h2>Run settings</h2><dl><dt>Trigger</dt><dd>'+esc(v.trigger)+'</dd><dt>Source</dt><dd>'+esc(v.source.replace('_preview',' sample'))+'</dd><dt>Premium review</dt><dd>'+(v.premium?'Enabled in this version':'Not enabled')+'</dd><dt>External actions</dt><dd>Human approval required</dd><dt>Saved version</dt><dd>v'+v.version+' · '+esc(v.version_id)+'</dd></dl><button class="secondary" data-library-tab="versions"># Versions & fingerprint</button><button class="text-button" data-library-tab="runs">Look under the hood →</button><p class="quiet">A visual explains the workflow. A run record shows what actually happened. These preview runs remain unsigned samples.</p></aside></div>';
      if(tab==='versions')html='<section class="lib-box"><header><h2>Saved versions</h2><span>'+w.versions.length+' immutable snapshots</span></header><div class="lib-version-list">'+w.versions.slice().reverse().map(x=>'<button data-library-select-version="'+x.version_id+'" class="'+(x.version_id===v.version_id?'selected':'')+'"><b>Version '+x.version+'</b><span>'+esc(x.name)+'</span><small>'+x.steps.length+' steps · '+(x.premium?'Premium review':'Standard checks')+'</small><span>'+(x.version_id===v.version_id?'Selected':'Inspect →')+'</span></button>').join('')+'</div><div class="lib-hash"><h3># Fingerprint of v'+v.version+'</h3><code id="libraryHash">Computing SHA-256…</code><p>Identifies this exact saved definition. It is not an executor signature or proof that a run happened.</p></div></section>';
      if(tab==='runs')html='<section class="lib-box"><header><h2>Runs of v'+v.version+'</h2><span>'+runs.length+' records · '+allRuns.length+' across all versions</span></header>'+(runs.length?'<div class="lib-run-list">'+runs.slice().reverse().map(r=>'<div><div><b>'+esc(r.id)+'</b><small>'+esc(r.created_at)+' · '+esc(r.mode)+' · $'+r.cost_usd.toFixed(3)+'</small></div><span class="lib-status">'+(r.status==='awaiting_demo_approval'?'Needs review':r.status==='cancelled_preview'?'Stopped':'Completed')+'</span><button class="secondary" data-ledger-run="'+r.id+'">Actions & ledger</button><button class="text-button" data-inspect-run="'+r.id+'">Inspect run ↗</button></div>').join('')+'</div>':'<div class="lib-empty"><h3>No runs of this version.</h3><p>Run v'+v.version+' to create a sample execution record. Other versions keep their own history.</p></div>')+'</section>';
      if(tab==='access')html='<section class="lib-box"><header><h2>Permissions & origin</h2><span>Bound to v'+v.version+'</span></header><dl class="lib-access"><dt>Origin</dt><dd>'+esc(v.provenance?v.provenance.publisher:'Created in this preview workspace')+'</dd><dt>Access</dt><dd>Read selected sample input. Draft output only. Any sample send requires review.</dd><dt>Approval</dt><dd>'+esc(v.steps.find(s=>s.kind==='approval')?.detail||'No external action')+'</dd><dt>Package installation</dt><dd>None. Built-in examples are not installed Marketplace modules.</dd><dt>Cryptographic evidence</dt><dd>Content fingerprints are computed here. Real local or hosted executors must sign production run receipts.</dd></dl><div class="lib-bottom-links"><button class="text-button" data-dialog="marketplace">Open public Marketplace →</button><button class="text-button" data-action="ownership">Creator record / optional NFT →</button></div></section>';
      $('#libraryDetailContent').innerHTML=html;
      if(tab==='versions'){const expected=selectedVersion;crypto.subtle.digest('SHA-256',new TextEncoder().encode(app.canonical(v))).then(buffer=>{if(selectedVersion===expected&&tab==='versions'&&$('#libraryHash'))$('#libraryHash').textContent=Array.from(new Uint8Array(buffer),b=>b.toString(16).padStart(2,'0')).join('');}).catch(()=>{if($('#libraryHash'))$('#libraryHash').textContent='Fingerprint unavailable in this browser.';});}
    }
    function open(id,section='visual'){const w=app.state.workflows.find(w=>w.id===id);if(!w)return;selectedId=id;selectedVersion=latest(w).version_id;tab=section;app.state.activeId=w.taskId;render();}
    $('#libraryView').addEventListener('click',event=>{const b=event.target.closest('button');if(!b)return;try{
      if(b.hasAttribute('data-library-back')){selectedId=null;render();}
      if(b.dataset.libraryOpen)open(b.dataset.libraryOpen);
      if(b.dataset.libraryVersion)open(b.dataset.libraryVersion,'versions');
      if(b.dataset.libraryTab){tab=b.dataset.libraryTab;render();}
      if(b.dataset.librarySelectVersion){selectedVersion=b.dataset.librarySelectVersion;render();}
      if(b.dataset.libraryEdit){const w=app.state.workflows.find(w=>w.id===b.dataset.libraryEdit);app.state.activeId=w.taskId;options.navigate('builder');}
      if(b.dataset.libraryRun){const w=app.state.workflows.find(w=>w.id===b.dataset.libraryRun);app.state.activeId=w.taskId;options.run(b.dataset.libraryRunVersion||latest(w).version_id);}
      if(b.dataset.libraryTemplate){const v=app.usePackage(b.dataset.libraryTemplate);options.refresh();open(v.id);options.toast('Built-in example added to this preview library. Nothing was installed or run.');}
    }catch(e){options.toast(e.message);}});
    $('#librarySearch').addEventListener('input',e=>{search=e.target.value.toLowerCase().trim();render();});
    $('#libraryOrigin').addEventListener('change',e=>{origin=e.target.value;render();});
    return {render,open,reset:()=>{selectedId=null;tab='visual';}};
  }
  root.RailCallLibrary={create};
})(globalThis);
