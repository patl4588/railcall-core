(function(global){
'use strict';
const escape=s=>String(s==null?'':s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const root=document.createElement('section');root.id='monitorView';root.hidden=true;root.className='monitor-view';document.querySelector('#integrationsView').before(root);
const nav=document.createElement('button');nav.className='nav';nav.dataset.view='monitor';nav.innerHTML='<span aria-hidden="true">≋</span><span class="sidebar-label">Monitor</span><small>Workflow runs</small>';document.querySelector('.sidebar nav [data-view="activity"]').before(nav);
global.RailCallMonitor={create({model:app}){
 let tab='runs',query='';
 const status=r=>r.status==='awaiting_demo_approval'?'Needs approval':r.status==='cancelled_preview'?'Stopped':'Completed';
 function render(){
 const runs=app.state.runs.filter(r=>r.workflow_snapshot),pending=runs.filter(r=>r.status==='awaiting_demo_approval');
 root.innerHTML='<header class="monitor-heading"><div><p class="eyebrow">WORKFLOW MONITOR</p><h1>Follow the work. Catch what needs you.</h1><p>Run status and approvals here. Full execution evidence in Studio.</p></div><button class="secondary" data-view="activity">Open Studio · all activity ↗</button></header><div class="monitor-metrics"><button data-monitor-tab="runs"><b>'+runs.length+'</b><span>Workflow runs</span></button><button data-monitor-tab="approvals"><b>'+pending.length+'</b><span>Need your approval</span></button><div><b>'+runs.filter(r=>r.status==='completed_preview').length+'</b><span>Completed</span></div><div><b>'+runs.filter(r=>r.status==='cancelled_preview').length+'</b><span>Stopped</span></div></div><div class="monitor-toolbar"><nav aria-label="Workflow operations">'+['runs','approvals','schedules'].map(t=>'<button data-monitor-tab="'+t+'" aria-pressed="'+(tab===t)+'">'+({runs:'Runs',approvals:'Approvals',schedules:'Schedules & triggers'}[t])+'</button>').join('')+'</nav><label>Find a workflow<input id="monitorSearch" type="search" value="'+escape(query)+'" placeholder="Name or run ID"></label></div><div id="monitorResults"></div><footer class="monitor-footer"><p>Monitor shows the same run records as Studio. Sample execution only; triggers do not run in the background.</p><button class="text-button" data-view="library">Open workflow library →</button></footer>';
 renderRows();
 }
 function renderRows(){
 const runs=app.state.runs.filter(r=>r.workflow_snapshot).slice().reverse().filter(r=>(tab!=='approvals'||r.status==='awaiting_demo_approval')&&(!query||(r.title+' '+r.id).toLowerCase().includes(query.toLowerCase())));
 const results=root.querySelector('#monitorResults');
 if(tab==='schedules'){
 const workflows=app.state.workflows.filter(w=>{const v=w.versions.at(-1);return v&&(!query||v.name.toLowerCase().includes(query.toLowerCase()));});
 results.innerHTML='<p class="monitor-note">Saved trigger definitions. Open a workflow to edit its trigger and save a new version.</p>'+ (workflows.length?'<div class="monitor-table-wrap"><table><thead><tr><th>Workflow</th><th>Saved trigger</th><th>Execution</th><th>Manage</th></tr></thead><tbody>'+workflows.map(w=>{const v=w.versions.at(-1);return '<tr><td><b>'+escape(v.name)+'</b><small>v'+v.version+'</small></td><td>'+escape(v.trigger||'On demand')+'</td><td><span class="monitor-status">Not scheduled · preview</span></td><td><button class="secondary" data-workflow-fingerprint="'+escape(w.id)+'">Open workflow →</button></td></tr>';}).join('')+'</tbody></table></div>':'<div class="monitor-empty"><h2>No saved triggers yet.</h2><p>Save a workflow version to see its trigger here.</p><button class="secondary" data-view="library">Open library</button></div>');
 return;
 }
 results.innerHTML=runs.length?'<div class="monitor-table-wrap"><table><thead><tr><th>Workflow / run</th><th>Status</th><th>Compute / cost</th><th>Next action</th></tr></thead><tbody>'+runs.map(r=>'<tr><td><b>'+escape(r.title)+'</b><small>'+escape(r.id)+' · '+new Date(r.created_at).toLocaleString()+'</small></td><td><span class="monitor-status '+(r.status==='awaiting_demo_approval'?'needs-review':'')+'">'+status(r)+'</span><small>'+(r.seeded_example?'Sample workflow':'Preview run')+'</small></td><td>'+ (r.mode==='desktop'?'Your computer':'RailCall servers')+'<small>$'+Number(r.cost_usd).toFixed(3)+' · sample charges</small></td><td>'+(r.status==='awaiting_demo_approval'?'<button class="primary" data-approve-run="'+escape(r.id)+'">Review action →</button>':'')+'<button class="text-button" data-inspect-run="'+escape(r.id)+'">Inspect in Studio ↗</button></td></tr>').join('')+'</tbody></table></div>':'<div class="monitor-empty"><h2>'+(tab==='approvals'?'No approvals waiting.':'No matching workflow runs.')+'</h2><p>'+(tab==='approvals'?'New approval requests appear here when a workflow pauses for review.':'Create and test a workflow from Chat to see it here.')+'</p><button class="secondary" data-view="chat">Open Chat & build</button></div>';
 }
 root.addEventListener('click',e=>{const b=e.target.closest('[data-monitor-tab]');if(b){tab=b.dataset.monitorTab;render();}});
 root.addEventListener('input',e=>{if(e.target.id==='monitorSearch'){query=e.target.value;renderRows();}});
 return {render};
}};
})(globalThis);
