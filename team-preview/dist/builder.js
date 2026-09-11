(function(root){
  'use strict';
  const esc=value=>String(value==null?'':value).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function content(d){
    const notes=d.notes.length?'<section><h2>Build notes</h2><ul>'+d.notes.map(n=>'<li>'+esc(n)+'</li>').join('')+'</ul></section>':'';
    if(d.kind==='website')return '<article class="artifact-page"><header><span>'+esc(d.title.slice(0,30))+'</span><span>Page draft</span></header><div class="artifact-page-hero"><small>YOUR NEXT IDEA</small><h1>'+esc(d.title)+'</h1><p>'+esc(d.brief)+'</p><span class="artifact-example-cta">Get started · example CTA</span></div><div class="artifact-page-features"><div><h2>A clear purpose</h2><p>Explain the problem this page helps solve.</p></div><div><h2>A useful result</h2><p>Show people what they can do next.</p></div><div><h2>A simple next step</h2><p>Replace this starter copy before publishing.</p></div></div>'+notes+'</article>';
    if(d.kind==='app')return '<article class="artifact-app"><small>INTERACTIVE APP STARTER</small><h1>'+esc(d.title)+'</h1><p>'+esc(d.brief)+'</p><div class="artifact-app-summary"><b>'+d.items.filter(i=>i.done).length+' / '+d.items.length+'</b><span>example tasks complete</span></div><div class="artifact-task-list">'+d.items.map((item,index)=>'<button data-artifact-item="'+index+'" aria-pressed="'+item.done+'"><span aria-hidden="true">'+(item.done?'✓':'○')+'</span><span>'+esc(item.text)+'</span><small>'+(item.done?'Done':'To do')+'</small></button>').join('')+'</div>'+notes+'</article>';
    return '<article class="artifact-document"><small>PROJECT BRIEF / DRAFT</small><h1>'+esc(d.title)+'</h1><section><h2>Objective</h2><p>'+esc(d.brief)+'</p></section><section><h2>Proposed approach</h2><ol><li>Clarify the audience and intended outcome.</li><li>Define the smallest useful deliverable.</li><li>Review the draft with the people who will use it.</li></ol></section><section><h2>Decisions to confirm</h2><p>Owner, scope, timing, and acceptance criteria.</p></section>'+notes+'</article>';
  }
  function source(d){
    if(d.kind==='document')return '# '+d.title+'\n\n## Objective\n'+d.brief+'\n\n## Proposed approach\n1. Clarify the audience and intended outcome.\n2. Define the smallest useful deliverable.\n3. Review the draft with its users.\n\n## Decisions to confirm\nOwner, scope, timing, and acceptance criteria.\n'+(d.notes.length?'\n## Build notes\n'+d.notes.map(n=>'- '+n).join('\n'):'');
    const body=content(d).replace(/<button\b[^>]*>/g,'<div class="task">').replace(/<\/button>/g,'</div>');
    return '<!doctype html>\n<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'+esc(d.title)+'</title><style>body{font:16px/1.7 system-ui,sans-serif;max-width:960px;margin:40px auto;padding:24px;color:#26262c}h1{font-size:clamp(32px,6vw,58px);line-height:1.15}header,.task{display:flex;justify-content:space-between;gap:20px;padding:16px 0;border-bottom:1px solid #ddd}small{color:#666}.artifact-page-hero{padding:60px 0}.artifact-example-cta{display:inline-block;background:#d6004a;color:white;padding:10px 18px;border-radius:6px}.artifact-page-features{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:28px}section{margin-top:28px}</style></head><body>'+body+'<footer><p>RailCall template draft. Exported snapshot; sample controls are not connected to services.</p></footer></body></html>';
  }
  function create(options){
    const app=options.model,$=s=>document.querySelector(s);let mode='workflow',tab='preview';
    function render(){
      $('#workflowBuilderPane').hidden=mode!=='workflow';$('#anythingBuilderPane').hidden=mode!=='anything';
      document.querySelectorAll('[data-build-mode]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.buildMode===mode)));
      const a=app.artifactForTask(),d=a&&a.draft;
      $('#artifactChat').innerHTML=a?a.messages.map(m=>'<div class="builder-chat-message '+m.role+'"><b>'+(m.role==='user'?'You':'Builder · template preview')+'</b><p>'+esc(m.text)+'</p></div>').join(''):'<div class="builder-chat-message assistant"><b>Anything builder</b><p>Describe an idea, then build alongside its preview. Start with a page, a small app, or a document.</p></div>';
      $('#artifactTitle').disabled=!d;$('#artifactSave').disabled=!d;$('#artifactExport').disabled=!d;
      if(document.activeElement!==$('#artifactTitle'))$('#artifactTitle').value=d?d.title:'';
      $('#artifactVersion').textContent=a?(a.versions.length?'Saved v'+a.versions.length+' · editing draft':'Unsaved draft'):'No draft yet';
      if(d)$('#artifactType').value=d.kind;
      $('#artifactCanvas').innerHTML=d?content(d):'<div class="artifact-empty"><span>▧</span><h2>Your idea, taking shape.</h2><p>Describe it in the build chat. The preview and source live here, alongside your conversation.</p><small>Templates demonstrate the intended product flow.</small></div>';
      $('#artifactSource').textContent=d?source(d):'Create a draft to inspect its source.';
      $('#artifactCanvas').hidden=tab!=='preview';$('#artifactSource').hidden=tab!=='source';
      document.querySelectorAll('[data-artifact-tab]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.artifactTab===tab)));
    }
    function build(text,kind=$('#artifactType').value){if(!text.trim())return;app.draftArtifact(kind,text);$('#artifactInput').value='';tab='preview';options.refresh();}
    $('#artifactForm').addEventListener('submit',e=>{e.preventDefault();build($('#artifactInput').value);});
    $('#artifactTitle').addEventListener('change',e=>{app.updateArtifactTitle(e.target.value);options.refresh();});
    $('#builderView').addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;try{
      if(b.dataset.buildMode){mode=b.dataset.buildMode;render();}
      if(b.dataset.artifactTab){tab=b.dataset.artifactTab;render();}
      if(b.dataset.artifactExample){const examples={website:'Create a product launch page for a simpler workday',app:'Build a simple project planner for our team',document:'Draft a team project brief for the next product release'};build(examples[b.dataset.artifactExample],b.dataset.artifactExample);}
      if(b.hasAttribute('data-artifact-item')){app.toggleArtifactItem(Number(b.dataset.artifactItem));options.refresh();}
      if(b.dataset.artifactAction==='save'){const v=app.saveArtifact();options.refresh();options.toast('Saved artifact v'+v.version+' in this preview session.');}
      if(b.dataset.artifactAction==='export'){const a=app.artifactForTask();if(!a)return;const isDoc=a.draft.kind==='document';const href=URL.createObjectURL(new Blob([source(a.draft)],{type:isDoc?'text/markdown':'text/html'}));const link=document.createElement('a');link.href=href;link.download='railcall-'+a.id+(isDoc?'.md':'.html');link.click();setTimeout(()=>URL.revokeObjectURL(href),1000);options.toast('Exported the current template draft. Nothing was deployed.');}
    }catch(error){options.toast(error.message);}});
    return {render,setMode:value=>{mode=value==='anything'?'anything':'workflow';render();}};
  }
  root.RailCallBuilder={create};
  if(typeof module!=='undefined'&&module.exports)module.exports={source,content};
})(globalThis);
