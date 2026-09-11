// Bounded source-controller checks; no browser or network.
const assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
const keys=['workspace','studio','workflows','receipts'],nodes=new Map(),classes=new Set();
function node(id){if(nodes.has(id))return nodes.get(id);const n={dataset:{},style:{},attributes:{},listeners:{},hidden:false,open:false,value:'fit',clientWidth:1200,clientHeight:600,
addEventListener(k,fn){this.listeners[k]=fn;},setAttribute(k,v){this.attributes[k]=v;},getAttribute(){return './assets/test.png';},focus(){this.focused=true;},showModal(){this.open=true;},close(){this.open=false;this.listeners.close?.();}};nodes.set(id,n);return n;}
const launch=keys.map(key=>Object.assign(node('launch-'+key),{dataset:{screen:key}})),nav=keys.map(key=>Object.assign(node('[data-screen-select="'+key+'"]'),{dataset:{screenSelect:key}}));
const events={},document={querySelector:node,querySelectorAll:s=>s==='[data-screen]'?launch:s==='[data-screen-select]'?nav:[],body:{classList:{add:k=>classes.add(k),remove:k=>classes.delete(k)}}};
vm.runInNewContext(fs.readFileSync('product-screens.js','utf8'),{document,window:{addEventListener:(k,f)=>events[k]=f}});
const dialog=node('#screenViewer'),zoom=node('#screenViewerZoom'),canvas=node('#screenViewerCanvas');
for(let i=0;i<keys.length;i++){
 launch[i].listeners.click();assert.equal(dialog.open,true);assert.ok(classes.has('screen-viewer-open'));
 assert.equal(nav[i].attributes['aria-pressed'],'true');assert.equal(node('#screenViewerAction').dataset.view,['chat','builder','library','activity'][i]);
 assert.ok(parseFloat(canvas.style.width)<=1168);zoom.value='1';zoom.listeners.change();assert.equal(canvas.style.width,[1600,1322,1290,1840][i]+'px');
}
nav[3].listeners.keydown({key:'ArrowRight',preventDefault(){}});assert.equal(nav[0].attributes['aria-pressed'],'true');assert.equal(nav[0].focused,true);
zoom.value='2';zoom.listeners.change();assert.equal(canvas.style.width,'3200px');
node('#screenViewerImage').listeners.error();assert.equal(canvas.hidden,true);assert.equal(node('#screenViewerError').hidden,false);
nav[1].listeners.click();assert.equal(canvas.hidden,false);assert.equal(node('#screenViewerError').hidden,true);assert.equal(zoom.value,'fit');
node('#screenViewerAction').listeners.click();assert.equal(dialog.open,false);assert.equal(classes.size,0);
launch[0].listeners.click();node('#screenViewerClose').listeners.click();assert.equal(dialog.open,false);
const html=fs.readFileSync('index.html','utf8');assert.equal((html.match(/data-screen="/g)||[]).length,4);assert.match(html,/aria-labelledby="screenViewerTitle"/);
console.log('Passed: four expandable screens, fit and native-resolution zoom, matching workspace destinations, keyboard navigation, image-failure recovery, and scroll-lock cleanup.');
