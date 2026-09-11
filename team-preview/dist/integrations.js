(function (root) {
  'use strict';
  const studioDocs = 'https://railcall.ai/docs/studio/';
  const publicDirectory = 'https://railcall.ai/integrations/';
  const listing = slug => 'https://railcall.ai/marketplace/' + slug.split('/').map(encodeURIComponent).join('/') + '/';
  const featured = [
    { id: 'slack', name: 'Slack', mark: 'SL', category: 'Communication', type: 'Direct connector', summary: 'Send reviewed updates to configured webhook destinations.', access: ['Choose a destination webhook', 'Review the message before sending'], boundary: 'The configured Slack endpoint receives approved message content. Webhook secrets belong in the executing Station, not this page.', url: studioDocs },
    { id: 'discord', name: 'Discord', mark: 'DC', category: 'Communication', type: 'Direct connector', summary: 'Deliver reviewed messages through a configured webhook.', access: ['Select a webhook destination', 'Inspect the proposed outbound message'], boundary: 'Discord receives the message sent to the configured webhook. A send approval does not cover unrelated reads or model requests.', url: studioDocs },
    { id: 'hubspot', name: 'HubSpot', mark: 'HS', category: 'CRM', type: 'Marketplace module', summary: 'Create contacts and attach notes to contacts.', access: ['Review contact fields', 'Review contact notes before writing'], boundary: 'The configured HubSpot account receives contact and note data. Credential permissions must be reviewed during real setup.', url: listing('sami666/hubspot'), sample: 'hubspot_preview' },
    { id: 'salesforce', name: 'Salesforce', mark: 'SF', category: 'CRM', type: 'Marketplace module', summary: 'Work with contacts, leads, opportunities, and cases.', access: ['Review the published command list', 'Limit object and field access for the task'], boundary: 'Salesforce receives requests and selected CRM data. The module listing describes additional operations; review each before enabling it.', url: listing('sami666/salesforce') },
    { id: 'notion', name: 'Notion', mark: 'N', category: 'Knowledge', type: 'Marketplace module', summary: 'Read pages and databases; review proposed edits.', access: ['Select shared pages and databases', 'Review creates, updates, and comments'], boundary: 'Notion receives selected page and database requests. Access depends on the resources shared with the configured integration.', url: listing('jarvis/notion-workspace') },
    { id: 'google-sheets', name: 'Google Sheets', mark: 'GS', category: 'Documents', type: 'Marketplace module', summary: 'Read spreadsheet metadata and append rows.', access: ['Select the spreadsheet', 'Review rows before appending'], boundary: 'Google receives spreadsheet requests and appended values. The published module does not establish support for arbitrary cell editing.', url: listing('sami666/google-sheets') },
    { id: 'google-drive', name: 'Google Drive', mark: 'GD', category: 'Documents', type: 'Direct connector', summary: 'Explore documented file and document access.', access: ['Review supported read operations during setup', 'Limit access to required files'], boundary: 'Google receives file requests. The catalog describes read capability; this preview does not establish write support or granted permissions.', url: publicDirectory },
    { id: 'github', name: 'GitHub', mark: 'GH', category: 'Development', type: 'Marketplace module', summary: 'Inspect repository work and review proposed changes.', access: ['Select repositories and required operations', 'Review writes to issues, pull requests, or files'], boundary: 'GitHub receives repository requests and changes. Review the public module commands and token permissions before setup.', url: listing('guardedops/github-operations') },
    { id: 'airtable', name: 'Airtable', mark: 'AT', category: 'CRM', type: 'Direct connector', summary: 'Work with records in a configured base.', access: ['Select a base and relevant tables', 'Review permitted read and write operations'], boundary: 'Airtable receives record requests and changes. The public catalog documents this connector; no base is connected here.', url: publicDirectory },
    { id: 'stripe', name: 'Stripe', mark: 'S', category: 'Finance', type: 'Marketplace module', summary: 'Review invoices, subscriptions, and proposed billing operations.', access: ['Review the command and affected billing records', 'Require explicit approval for financial writes'], boundary: 'Stripe receives configured billing requests. Listing availability is not proof of a successful production-money operation; this preview cannot move money.', url: listing('dave/stripe-invoicing') },
    { id: 'smtp', name: 'Email · SMTP', mark: '@', category: 'Communication', type: 'Direct connector', summary: 'Send mail through your configured SMTP service.', access: ['Review recipients, subject, and body', 'Approve the proposed send'], boundary: 'The configured mail provider and recipients receive the email. SMTP credentials belong in the executing runtime.', url: publicDirectory },
    { id: 'webhooks', name: 'Webhooks', mark: 'WH', category: 'Automation', type: 'Direct connector', summary: 'Receive events and dispatch approved payloads.', access: ['Verify the destination and payload', 'Review inbound authentication and outbound policy'], boundary: 'Configured endpoints receive requests. Opening this directory does not create an inbound endpoint or background trigger.', url: studioDocs }
  ];
  const snapshot = root.RailCallIntegrationCatalog || (typeof require === 'function' ? require('./integration-catalog.js') : []);
  const catalog = snapshot.map(item => {
    const detail=featured.find(p=>p.name===item.name);
    const reachable=item.type==='Reachable app';
    return {
      mark:item.name.replace(/[^a-z0-9 ]/gi,'').split(' ').map(s=>s[0]).join('').slice(0,2).toUpperCase(),
      access: reachable ? ['Choose and configure a supported bridge, automation platform, or API route', 'Review both the intermediary and destination permissions'] : ['Review the connector or module operations before setup', 'Grant only the access this task needs; review external writes'],
      boundary: reachable ? 'This is a reachable catalog entry, not a native connector or an authorized account. The chosen bridge and destination service may receive selected data. Specific capabilities and permissions must be confirmed during setup.' : item.name==='Ollama · local' ? 'A configured local Ollama endpoint can process model inputs on your computer. Review endpoint location, model compatibility, and network policy during setup.' : 'The configured destination receives the requests and data your workflow sends. Review endpoint location, permissions, credentials, and any third-party charges before enabling a real connection.',
      ...item,
      ...(detail?.sample ? {sample:detail.sample} : {}),
      ...(detail ? {access:detail.access, boundary:detail.boundary, moduleUrl:detail.url!==publicDirectory && detail.url!==studioDocs ? detail.url : null} : {})
    };
  });
  function create(options) {
    const app = options.model, $ = s => document.querySelector(s);
    const esc = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    let selected = 'hubspot', limit = 50;
    function render() {
      const query = $('#integrationSearch').value.trim().toLowerCase();
      const type = $('#integrationType').value;
      const items = catalog.filter(p => (type === 'all' || p.type === type) && [p.name, p.category, p.summary].join(' ').toLowerCase().includes(query));
      if (!items.some(p => p.id === selected)) selected = items[0]?.id || null;
      $('#integrationTask').textContent = 'Task: ' + app.active().title;
      $('#integrationSource').textContent = ({sample:'Sample records',hubspot_preview:'HubSpot sample',gmail_preview:'Gmail sample'}[app.active().source] || 'Sample records') + ' · no account connected';
      $('#integrationCount').textContent = Math.min(limit,items.length) + ' shown · ' + items.length + ' of ' + catalog.length + ' entries';
      $('#integrationMore').hidden = items.length <= limit;
      $('#integrationEmpty').hidden = items.length > 0;
      $('#integrationList').innerHTML = items.slice(0,limit).map(p => '<button class="in-row' + (selected === p.id ? ' selected' : '') + '" data-integration="' + p.id + '" aria-pressed="' + String(selected === p.id) + '"><span class="in-mark" aria-hidden="true">' + (p.logo ? '<img src="'+p.logo+'" alt="" width="23" height="23" loading="lazy">' : esc(p.mark)) + '</span><span class="in-row-content"><b>' + esc(p.name) + '</b><small>' + esc(p.summary) + '</small></span><span class="in-row-meta"><span>' + esc(p.type) + '</span><small>Not connected</small></span><span aria-hidden="true">›</span></button>').join('');
      document.querySelectorAll('.in-samples [data-source]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.source === app.active().source)));
      const p = catalog.find(p => p.id === selected);
      if (!p) { $('#integrationDetail').innerHTML = '<h2>Choose a tool</h2><p>Its capabilities and setup information appear here.</p>'; return; }
      $('#integrationDetail').innerHTML = '<header><span class="in-mark" aria-hidden="true">' + p.mark + '</span><div><h2>' + esc(p.name) + '</h2><span>' + esc(p.category) + ' · ' + esc(p.type) + '</span></div></header><span class="in-state">Not connected · setup required</span><p>' + esc(p.summary) + '</p><h3>Review access</h3><ul>' + p.access.map(a => '<li>' + esc(a) + '</li>').join('') + '</ul><h3>Where data goes</h3><p>' + esc(p.boundary) + '</p><dl><dt>Account / workspace</dt><dd>None authorized</dd><dt>Credentials</dt><dd>Not collected by this preview</dd><dt>Connection test</dt><dd>Not run</dd><dt>Revoke access</dt><dd>Manage tokens or app access with the provider during real setup.</dd></dl><a class="secondary" href="' + p.url + '" target="_blank" rel="noopener noreferrer">' + (p.type === 'Marketplace extension' ? 'Review public module' : p.type === 'Reachable app' ? 'Review route in public directory' : 'View public connector') + ' ↗</a>' + (p.moduleUrl ? '<a class="text-button" href="'+p.moduleUrl+'" target="_blank" rel="noopener noreferrer">Also available in Marketplace ↗</a>' : '') + (p.sample ? '<button class="primary" data-integration-sample="' + p.sample + '">Use sample data in this task</button>' : '') + '<small class="in-setup-note">Setup happens outside this prototype. Browsing a tool or choosing sample data grants no access.</small>';
    }
    $('#integrationsView').addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      if (button.dataset.integration) {
        selected = button.dataset.integration; render();
        const heading = $('#integrationDetail').querySelector('h2'); heading.setAttribute('tabindex','-1'); heading.focus({preventScroll:true});
      }
      if (button.dataset.integrationSample) options.chooseSample(button.dataset.integrationSample);
    });
    $('#integrationSearch').addEventListener('input', () => {limit=50;render();});
    $('#integrationType').addEventListener('change', () => {limit=50;render();});
    $('#integrationMore').addEventListener('click', () => {limit+=50;render();});
    return { render, open: id => { if (catalog.some(p => p.id === id)) { selected = id; $('#integrationSearch').value = ''; $('#integrationType').value = 'all'; render(); } } };
  }
  root.RailCallIntegrations = { create, catalog };
  if (typeof module !== 'undefined' && module.exports) module.exports = { catalog };
})(globalThis);
