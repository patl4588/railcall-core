(function () {
  'use strict';
  const scenarios = {
    local: {eyebrow:'LOCAL-FIRST EXAMPLE', title:'Your computer can handle this.', description:'A compatible local model prepares the brief. No hosted model request is needed, so hosted AI charges are $0.', status:'Selected · stays local'},
    team: {eyebrow:'ORGANIZATION CAPACITY EXAMPLE', title:'Your laptop is busy. An approved team server is ready.', description:'The same task moves to available capacity inside the approved organization pool. Your data policy stays in force; infrastructure and Railhub service costs are separate.', status:'Selected · approved team pool'},
    web: {eyebrow:'HOSTED OPEN-MODEL EXAMPLE', title:'No local setup? Start on RailCall servers.', description:'A RailCall-hosted open model handles the brief. Hosted compute is metered; the preview uses sample credit and pricing is not final.', status:'Selected · RailCall hosted'}
  };
  let selected = 'local';
  const premium = document.querySelector('#routePremium');
  function renderRoute() {
    const route = scenarios[selected];
    document.querySelectorAll('[data-route-example]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.routeExample === selected)));
    document.querySelectorAll('[data-route-node]').forEach(node => {
      const key=node.dataset.routeNode;
      node.classList.toggle('is-selected', key === selected || (key === 'premium' && premium.checked));
      node.querySelector('.route-status').textContent = key === selected ? route.status : key === 'premium' ? (premium.checked ? 'Approved review · paid API' : 'Off · your choice') : key === 'team' ? 'Not selected · Railhub setup' : 'Not selected';
    });
    document.querySelector('#routeEyebrow').textContent=route.eyebrow;
    document.querySelector('#routeTitle').textContent=route.title;
    document.querySelector('#routeDescription').textContent=route.description + (premium.checked ? ' You also approved a separate premium review: selected content leaves this compute boundary for that provider, and API charges apply.' : '');
  }
  document.querySelectorAll('[data-route-example]').forEach(b => b.addEventListener('click', () => {selected=b.dataset.routeExample; renderRoute();}));
  premium.addEventListener('change', renderRoute);

  const heroScreens = {
    workspace: {src:'./assets/current-workspace.png', crop:'workspace', width:1600, height:1000, title:'The whole product. One workspace.', meta:'Actual interactive web preview · sample costs', action:'Open Chat ↗', view:'chat', label:'Expand RailCall workspace preview', alt:'RailCall web workspace with Chat, Builder, Studio, the workflow library, and the ongoing local-compute savings calculator'},
    studio: {src:'https://railcall.ai/home/studio-builder.png', crop:'studio', width:1322, height:922, title:'Studio: build, then see the work.', meta:'Actual Studio v1.5.15 · public product capture', action:'Open Builder & Studio ↗', view:'builder', label:'Expand Studio preview', alt:'Actual RailCall Studio builder with workflow steps, connected tools, and execution controls'},
    workflows: {src:'./assets/real-workflow-library.png', crop:'workflows', width:1920, height:1080, title:'Workflows: organized once. Ready again.', meta:'Actual workflow library · recorded product demonstration', action:'Open workflow library ↗', view:'library', label:'Expand workflow library preview', alt:'Actual RailCall Studio workflow library, organized as rows with run, visual, and publish controls'},
    receipts: {src:'./assets/real-studio-receipt.png', crop:'receipts', width:1920, height:1080, title:'Cryptographic receipts: see what happened.', meta:'Recorded Studio receipt · separate from this web preview', action:'Inspect actions & receipts ↗', view:'activity', label:'Expand cryptographic receipt preview', alt:'Recorded RailCall Studio web-fetch receipt showing the integrity hash, signature, key identifier, and verification controls'}
  };
  const heroImage = document.querySelector('#heroPreviewImage');
  if (heroImage) {
    const heroCrop = document.querySelector('#heroPreviewCrop');
    const heroScreen = document.querySelector('#heroPreviewScreen');
    const heroTitle = document.querySelector('#heroPreviewTitle');
    const heroMeta = document.querySelector('#heroPreviewMeta');
    const heroAction = document.querySelector('#heroPreviewAction');
    function selectHeroScreen(key) {
      const screen = heroScreens[key];
      if (!screen) return;
      heroImage.src = screen.src; heroImage.alt = screen.alt; heroImage.width = screen.width; heroImage.height = screen.height;
      heroCrop.className = 'screen-crop screen-crop-' + screen.crop;
      heroScreen.dataset.screen = key; heroScreen.setAttribute('aria-label', screen.label);
      heroTitle.textContent = screen.title; heroMeta.textContent = screen.meta;
      heroAction.textContent = screen.action; heroAction.dataset.view = screen.view;
      document.querySelectorAll('[data-hero-screen]').forEach(button => {
        const active = button.dataset.heroScreen === key;
        button.classList.toggle('is-selected', active);
        if (button.getAttribute('role') === 'tab') button.setAttribute('aria-selected', String(active));
      });
    }
    document.querySelectorAll('[data-hero-screen]').forEach(button => button.addEventListener('click', () => selectHeroScreen(button.dataset.heroScreen)));
  }

  document.querySelectorAll('[data-theater]').forEach(button => button.addEventListener('click', () => {
    document.querySelectorAll('[data-theater]').forEach(b => b.setAttribute('aria-pressed',String(b===button)));
    ['Studio','Workflows','Receipts'].forEach(name => document.querySelector('#theater'+name).hidden=name.toLowerCase()!==button.dataset.theater);
  }));
})();
