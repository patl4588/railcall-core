(function(root){
  'use strict';
  function create(){
    const $=s=>document.querySelector(s);
    const esc=v=>String(v==null?'':v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let catalog=null, loading=null, type='all';
    const listingUrl=slug=>'https://railcall.ai/marketplace/'+slug.split('/').map(encodeURIComponent).join('/')+'/';
    function price(item){
      if(item.price_cents===0)return 'Free';
      if(!Number.isFinite(item.price_cents))return 'See listing';
      const amount=new Intl.NumberFormat('en-US',{style:'currency',currency:item.currency||'USD',maximumFractionDigits:2}).format(item.price_cents/100);
      return amount+(item.pricing_model==='subscription'?' / '+(item.billing_interval||'subscription'): '');
    }
    function render(){
      document.querySelectorAll('[data-market-type]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.marketType===type)));
      if(!catalog)return;
      const query=$('#marketSearch').value.toLowerCase().trim(),category=$('#marketCategory').value;
      const list=catalog.items.filter(p=>(type==='all'||p.type===type)&&(category==='all'||category===p.category)&&(!query||[p.title,p.slug,p.seller,...p.providers].join(' ').toLowerCase().includes(query)));
      const sort=$('#marketSort').value;
      if(sort==='name')list.sort((a,b)=>a.title.localeCompare(b.title));
      if(sort==='price')list.sort((a,b)=>(a.price_cents??Infinity)-(b.price_cents??Infinity));
      if(sort==='downloads')list.sort((a,b)=>b.downloads-a.downloads);
      $('#marketCount').textContent=list.length+' of '+catalog.items.length+' public listings';
      $('#marketCards').innerHTML=list.map(p=>'<article class="mp-card"><div class="mp-card-top"><span class="mp-type">'+esc(p.type==='workflow'?'◇ Workflow':'⊞ Module')+'</span><span>'+esc(p.category)+'</span></div><h3>'+esc(p.title)+'</h3><p class="mp-byline">By '+esc(p.seller)+' · v'+esc(p.version)+'</p><div class="mp-providers">'+p.providers.slice(0,5).map(n=>'<span>'+esc(n)+'</span>').join('')+(p.providers.length>5?'<span>+'+(p.providers.length-5)+'</span>':'')+'</div><p class="mp-effect">'+(p.effects?'External effects declared · review before use':'Review commands and permissions on the listing')+'</p><footer><strong>'+esc(price(p))+'</strong><a href="'+listingUrl(p.slug)+'" target="_blank" rel="noopener noreferrer">View listing ↗</a></footer></article>').join('');
      $('#marketEmpty').hidden=list.length>0;
    }
    async function enter(){
      if(catalog){render();return;}
      $('#marketCount').textContent='Loading public catalog snapshot…';
      try{
        if(!loading)loading=fetch('./public-catalog.json').then(r=>{if(!r.ok)throw Error('Catalog unavailable');return r.json();});
        catalog=await loading;
        catalog={...catalog,items:catalog.items.map(item=>({...item,version:String(item.version).replace(/^v/i,'')}))};
        const date=new Date(catalog.captured_at).toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
        $('#marketSnapshot').textContent='Public catalog snapshot · '+date+' · Prices and availability may change.';
        $('#marketCategory').innerHTML='<option value="all">All departments</option>'+[...new Set(catalog.items.map(p=>p.category))].sort().map(c=>'<option value="'+esc(c)+'">'+esc(c)+'</option>').join('');
        render();
      }catch(error){loading=null;$('#marketCount').textContent='The catalog snapshot could not load. Open the live Marketplace below.';}
    }
    $('#marketplaceView').addEventListener('click',event=>{const b=event.target.closest('[data-market-type]');if(b){type=b.dataset.marketType;render();}});
    ['#marketSearch','#marketCategory','#marketSort'].forEach(s=>$(s).addEventListener(s==='#marketSearch'?'input':'change',render));
    return {enter,setType:value=>{type=['module','workflow'].includes(value)?value:'all';render();}};
  }
  root.RailCallMarketplace={create};
})(globalThis);
