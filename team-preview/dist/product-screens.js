(function () {
  'use strict';
  const $=s=>document.querySelector(s),all=s=>Array.from(document.querySelectorAll(s));
  const dialog=$('#screenViewer'),stage=$('#screenViewerStage'),canvas=$('#screenViewerCanvas'),crop=$('#screenViewerCrop'),image=$('#screenViewerImage'),zoom=$('#screenViewerZoom'),action=$('#screenViewerAction');
  const screens={
    workspace:{title:'The RailCall workspace',width:1600,height:1000,view:'chat',action:'Open Chat',hint:'Chat, build, and compare compute in one workspace.',note:'Actual web preview capture. The responses, costs, and savings shown are illustrative.'},
    studio:{title:'Studio',width:1322,height:922,view:'builder',action:'Open Builder & Studio',hint:'See the steps, connections, and controls behind the work.',note:'Actual public Studio v1.5.15 capture. Open the workspace to try the unified Builder.'},
    workflows:{title:'Your workflow library',width:1290,height:881,view:'library',action:'Open workflow library',hint:'Keep workflows organized, inspect versions, and run them again.',note:'Actual Studio library from the recorded product demonstration. The web library contains sample workflows.'},
    receipts:{title:'Cryptographic receipts',width:1840,height:590,view:'activity',action:'Inspect actions & receipts',hint:'Follow the execution record, integrity hash, and verification controls.',note:'A signed receipt from an earlier recorded Studio demo—not a signature for this web preview.'}
  };
  const sources={workspace:{src:"./assets/current-workspace.png",alt:"RailCall workspace"},studio:{src:"https://railcall.ai/home/studio-builder.png",alt:"Local RailCall Studio"},workflows:{src:"./assets/real-workflow-library.png",alt:"Workflow library"},receipts:{src:"./assets/real-studio-receipt.png",alt:"Recorded Studio receipt"}};
  let current='workspace';
  function resize(){
    const s=screens[current],choice=zoom.value;
    const fit=Math.min(Math.max(1,stage.clientWidth-32),Math.max(1,stage.clientHeight-32)*s.width/s.height,s.width);
    canvas.style.width=(choice==='fit'?fit:s.width*Number(choice))+'px';
    $('#screenViewerHint').textContent=choice==='fit'?s.hint:'Scroll horizontally or vertically to inspect the original capture.';
  }
  function select(key){
    if(!Object.prototype.hasOwnProperty.call(screens,key))return;
    current=key;const s=screens[key],source=sources[key];
    $('#screenViewerTitle').textContent=s.title;$('#screenViewerNote').textContent=s.note;
    $('#screenViewerError').hidden=true;canvas.hidden=false;
    crop.className='screen-crop screen-crop-'+key;image.alt=source.alt;image.src=source.src;
    action.dataset.view=s.view;action.textContent=s.action+' ↗';
    all('[data-screen-select]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.screenSelect===key)));
    zoom.value='fit';stage.scrollTop=0;stage.scrollLeft=0;resize();
  }
  all('[data-screen]').forEach(button=>button.addEventListener('click',()=>{
    dialog.showModal();document.body.classList.add('screen-viewer-open');select(button.dataset.screen);
  }));
  all('[data-screen-select]').forEach(button=>{
    button.addEventListener('click',()=>select(button.dataset.screenSelect));
    button.addEventListener('keydown',event=>{
      const keys=Object.keys(screens),i=keys.indexOf(current);let next;
      if(event.key==='ArrowRight')next=keys[(i+1)%keys.length];
      if(event.key==='ArrowLeft')next=keys[(i+keys.length-1)%keys.length];
      if(event.key==='Home')next=keys[0];if(event.key==='End')next=keys[keys.length-1];
      if(next){event.preventDefault();select(next);$('[data-screen-select="'+next+'"]').focus();}
    });
  });
  $('#screenViewerClose').addEventListener('click',()=>dialog.close());
  action.addEventListener('click',()=>dialog.close()); // The existing controller handles navigation after this.
  dialog.addEventListener('close',()=>document.body.classList.remove('screen-viewer-open'));
  dialog.addEventListener('click',event=>{if(event.target===dialog){const r=dialog.getBoundingClientRect();if(event.clientX<r.left||event.clientX>r.right||event.clientY<r.top||event.clientY>r.bottom)dialog.close();}});
  zoom.addEventListener('change',()=>{resize();stage.scrollTop=0;stage.scrollLeft=0;});
  image.addEventListener('error',()=>{canvas.hidden=true;$('#screenViewerError').hidden=false;});
  window.addEventListener('resize',()=>{if(dialog.open)resize();});
})();
