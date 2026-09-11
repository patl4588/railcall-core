(function (root) {
  'use strict';
  function create(options) {
    const app = options.model;
    const $ = s => document.querySelector(s);
    const escape = v => String(v == null ? '' : v).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const money = n => '$' + Number(n).toFixed(3);
    const places = { workspace: 'Workspace', railcall_servers: 'RailCall servers', customer_device: 'Your computer', external_provider: 'Premium API', human_review: 'Human review' };
    const icons = { execution: '↗', approval: '◎', action: '→', workflow: '◇', artifact: '▧', connection: '⇄', policy: '≡', conversation: '◯' };
    let selectedId = null, quick = 'all', limit = 20;
    const runFor = e => app.state.runs.find(r => r.id === e.run_id);
    const isPending = e => e.kind === 'approval.requested' && runFor(e)?.status === 'awaiting_demo_approval';
    function filtered() {
      const query = $('#activitySearch').value.trim().toLowerCase();
      const category = $('#activityCategory').value, location = $('#activityLocation').value;
      return app.activityEntries().reverse().filter(e => (category === 'all' || e.category === category) && (location === 'all' || e.location === location) && (quick === 'all' || quick === 'pending' && isPending(e) || quick === 'blocked' && ['action.blocked', 'action.held'].includes(e.kind)) && (!query || [e.title,e.detail,e.task_title,e.workflow_title,e.id,e.run_id,e.kind].join(' ').toLowerCase().includes(query)));
    }
    function renderMetrics() {
      const events = app.state.events, pending = app.state.runs.filter(r => r.status === 'awaiting_demo_approval').length;
      $('#activityMetrics').innerHTML = '<div><span>Recorded actions</span><strong>' + events.length + '</strong><small>Historical entries, newest first</small></div><div><span>Workspace runs</span><strong>' + app.state.runs.length + '</strong><small>Across ' + app.state.workflows.length + ' saved workflows</small></div><button data-activity-action="pending"><span>Needs review now</span><strong>' + pending + '</strong><small>Open outstanding approvals ↗</small></button><div><span>Sample usage total</span><strong>' + money(app.state.runs.reduce((n,r) => n + r.cost_usd,0)) + '</strong><small>Counted once per processing step</small></div>';
    }
    function render() {
      renderMetrics();
      const entries = filtered();
      if (!entries.some(e => e.id === selectedId)) selectedId = entries[0]?.id || null;
      document.querySelectorAll('[data-activity-filter]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.activityFilter === quick)));
      $('#activityResultCount').textContent = entries.length + ' matching events';
      $('#activityEmpty').hidden = entries.length > 0;
      $('#activityMore').hidden = entries.length <= limit;
      $('#activityRows').innerHTML = entries.slice(0,limit).map(e => '<tr class="' + (e.id === selectedId ? 'selected' : '') + '"><td><time datetime="' + e.created_at + '">' + new Date(e.created_at).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit',second:'2-digit'}) + '</time><small>#' + String(e.sequence).padStart(3,'0') + '</small></td><td><button class="a-event-select" data-activity-event="' + e.id + '" aria-pressed="' + String(e.id === selectedId) + '"><span class="a-event-icon ' + e.category + '">' + icons[e.category] + '</span><span><b>' + escape(e.title) + '</b><small>' + (isPending(e) ? 'Needs review now' : escape(e.kind.replaceAll('.',' / '))) + '</small></span></button></td><td><b>' + escape(e.workflow_title || e.task_title) + '</b><small>' + (e.workflow_version ? 'v' + e.workflow_version + ' · ' : '') + (e.run_id || e.task_id || 'Workspace') + '</small></td><td><span>' + places[e.location] + '</span><small>' + (typeof e.cost_usd === 'number' ? money(e.cost_usd) : '—') + '</small></td><td><span class="a-event-status">' + escape(isPending(e) ? 'Needs review' : e.status) + '</span><small>Unsigned sample</small></td></tr>').join('');
      renderDetail(entries.find(e => e.id === selectedId));
    }
    function pair(k,v) { return '<div><dt>' + k + '</dt><dd>' + escape(v) + '</dd></div>'; }
    function renderDetail(e) {
      if (!e) { $('#activityInspector').innerHTML = '<p>Select an event to see what happened and its linked evidence.</p>'; return; }
      const r = runFor(e);
      const status = isPending(e) ? 'Needs review now' : e.status;
      $('#activityInspector').innerHTML = '<header><span>EVENT DETAIL</span><code>#' + String(e.sequence).padStart(3,'0') + '</code></header><span class="a-detail-icon ' + e.category + '">' + icons[e.category] + '</span><h2>' + escape(e.title) + '</h2><span class="a-event-status">' + escape(status) + '</span><h3>What happened</h3><p>' + escape(e.detail) + '</p>' + (r ? '<div class="a-current-outcome"><small>Run outcome now</small><b>' + (r.status === 'awaiting_demo_approval' ? 'Waiting for review' : r.status === 'cancelled_preview' ? 'Stopped · action blocked' : 'Completed · preview') + '</b></div>' : '') + '<dl class="st-details">' + pair('Recorded',new Date(e.created_at).toLocaleString()) + pair('Actor',e.actor) + pair('Signer','None · unsigned preview') + (r ? pair('Approval',r.approval.decision) : '') + pair('Location',places[e.location]) + pair('Event',e.id) + pair('Conversation',e.task_id || 'Workspace') + (e.run_id ? pair('Run',e.run_id) : '') + (typeof e.cost_usd === 'number' ? pair('Step cost',money(e.cost_usd)) : '') + '</dl><div class="a-detail-actions">' + (isPending(e) ? '<button class="primary" data-activity-review="' + r.id + '">Review proposed action →</button>' : '') + (r ? '<button class="secondary" data-activity-open-run="' + e.id + '">Look under the hood ↗</button><button class="text-button" data-receipt="' + r.id + '">Open run receipt →</button>' : (e.category === 'artifact' ? '<button class="secondary" data-artifact-task="' + e.task_id + '">Open in Anything builder →</button>' : '<button class="secondary" data-task="' + e.task_id + '">Open conversation →</button>')) + (e.workflow_version_id ? '<button class="text-button" data-event-fingerprint="' + e.id + '"># Exact workflow fingerprint</button>' : '') + '</div><div class="a-evidence-note"><b>Evidence status: unsigned preview</b><p>This is a historical sample record. It has not been signed by a production executor or synchronized with the local Studio.</p></div>';
    }
    function clear() { quick = 'all'; limit = 20; $('#activitySearch').value = ''; $('#activityCategory').value = 'all'; $('#activityLocation').value = 'all'; }
    function exportLedger() {
      const events = filtered(), runIds = new Set(events.map(e => e.run_id).filter(Boolean)), versionIds = new Set(events.map(e => e.workflow_version_id).filter(Boolean));
      const ledger = { schema: 'railcall.preview.activity-ledger.v1', exported_at: new Date().toISOString(), scope: 'This browser session; current filters', filters: { query: $('#activitySearch').value, category: $('#activityCategory').value, location: $('#activityLocation').value, attention: quick }, verification: { status: 'unsigned_preview', production_attestation: false }, events: events.slice().reverse(), artifact_versions: (app.state.artifacts || []).flatMap(a => a.versions).filter(v => events.some(e => e.artifact_version_id === v.version_id)), runs: app.state.runs.filter(r => runIds.has(r.id)), workflow_versions: app.state.workflows.flatMap(w => w.versions).filter(v => versionIds.has(v.version_id)), filtered_step_cost_usd: Number(events.reduce((n,e) => n + (e.cost_usd || 0),0).toFixed(6)) };
      const url = URL.createObjectURL(new Blob([JSON.stringify(ledger,null,2)], {type:'application/json'}));
      const a = document.createElement('a'); a.href = url; a.download = 'railcall-workspace-ledger.json'; a.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
      options.toast('Exported matching events with their runs and workflow versions.');
    }
    $('#activityView').addEventListener('click', event => {
      const b = event.target.closest('button'); if (!b) return;
      if (b.dataset.activityEvent) { selectedId = b.dataset.activityEvent; render(); const row = document.querySelector('[data-activity-event="' + selectedId + '"]'); if(row)row.focus({preventScroll:true}); if(window.matchMedia('(max-width: 850px)').matches)$('#activityInspector').scrollIntoView({block:'start'}); }
      if (b.dataset.activityFilter) { quick = b.dataset.activityFilter; limit = 20; render(); }
      if (b.dataset.activityOpenRun) { const e = app.state.events.find(item => item.id === b.dataset.activityOpenRun); if(e)options.openRun(e.run_id,e.step_index); }
      if (b.dataset.activityReview) options.review(b.dataset.activityReview);
      if (b.dataset.activityAction === 'more') { limit += 20; render(); }
      if (b.dataset.activityAction === 'clear') { clear(); render(); }
      if (b.dataset.activityAction === 'pending') { clear(); quick = 'pending'; render(); }
      if (b.dataset.activityAction === 'export') exportLedger();
    });
    $('#activitySearch').addEventListener('input', () => {limit=20;render();});
    ['#activityCategory','#activityLocation'].forEach(s => $(s).addEventListener('change', () => {limit=20;render();}));
    return { render, reset: clear, openRun: id => { clear(); $('#activitySearch').value = id; render(); } };
  }
  root.RailCallActivity = { create };
})(globalThis);
