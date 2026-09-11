(function (root) {
  'use strict';
  function create(options) {
    const app = options.model;
    const $ = selector => document.querySelector(selector);
    const escape = value => String(value == null ? '' : value).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);
    const money = value => '$' + Number(value).toFixed(3);
    const locations = { customer_device: 'Your computer', railcall_servers: 'RailCall servers', external_provider: 'Premium API' };
    const sources = { sample: 'Sample records', gmail_preview: 'Gmail sample', hubspot_preview: 'HubSpot sample' };
    const icons = { source: '▤', model: '✦', review: '✓', approval: '◎', action: '↗', instruction: '≡' };
    const runStatus = r => r.status === 'awaiting_demo_approval' ? 'Needs approval' : r.status === 'cancelled_preview' ? 'Stopped by reviewer' : 'Completed';
    const statusClass = r => r.status === 'awaiting_demo_approval' ? 'waiting' : r.status === 'cancelled_preview' ? 'stopped' : 'complete';
    let selectedId = null, selectedStep = 0, inspectorTab = 'output', filter = 'all';
    const selected = () => app.state.runs.find(r => r.id === selectedId);
    function select(id, notify = true, resetFilter = true) {
      const r = app.state.runs.find(item => item.id === id);
      if (!r) return;
      if (resetFilter) filter = 'all';
      selectedId = r.id; app.state.activeId = r.task_id;
      const pendingStep = app.trace(r.id).findIndex(step => step.status === 'waiting');
      selectedStep = pendingStep < 0 ? Math.min(1, app.trace(r.id).length - 1) : pendingStep;
      inspectorTab = 'output';
      if (notify) { options.renderWorkspace(); const item = document.querySelector('[data-st-run="' + id + '"]'); if (item) item.focus({ preventScroll: true }); }
    }
    function enter() {
      app.seedStudioExamples();
      const current = app.runForTask().slice(-1)[0];
      const fallback = app.state.runs.find(r => r.status === 'awaiting_demo_approval') || app.state.runs.slice(-1)[0];
      const next = current || fallback;
      if (next && (!selected() || selected().task_id !== app.state.activeId || selected().id !== next.id)) select(next.id, false);
      if (selected()) app.state.activeId = selected().task_id;
    }
    function renderMetrics() {
      const runs = app.state.runs, waiting = runs.filter(r => r.status === 'awaiting_demo_approval').length;
      $('#studioMetrics').innerHTML = '<div><span>Workspace runs</span><strong>' + runs.length.toString().padStart(2, '0') + '</strong><small>Across ' + app.state.workflows.length + ' saved workflows</small></div><button data-st-filter="waiting" class="st-attention-metric"><span>Needs your review</span><strong>' + waiting.toString().padStart(2, '0') + '<i>↗</i></strong><small>' + (waiting ? 'Paused before an external action' : 'No approvals waiting') + '</small></button><div><span>Example model usage</span><strong>' + runs.reduce((n, r) => n + r.tokens, 0).toLocaleString() + '<em> tokens</em></strong><small>Open models + selected premium steps</small></div><button data-dialog="usage"><span>Sample cost</span><strong>' + money(runs.reduce((n, r) => n + r.cost_usd, 0)) + '</strong><small>Inspect the same usage ledger ↗</small></button>';
    }
    function renderList() {
      const runs = app.state.runs.slice().reverse().filter(r => filter === 'all' || r.status === 'awaiting_demo_approval');
      document.querySelectorAll('.st-run-filters [data-st-filter]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.stFilter === filter)));
      $('#studioRunList').innerHTML = runs.length ? runs.map(r => '<button class="st-run-item ' + (r.id === selectedId ? 'selected' : '') + '" data-st-run="' + r.id + '" aria-pressed="' + String(r.id === selectedId) + '"><div><span class="st-run-glyph ' + statusClass(r) + '">' + (r.status === 'awaiting_demo_approval' ? 'Ⅱ' : r.status === 'cancelled_preview' ? '−' : '✓') + '</span><small>' + new Date(r.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) + '</small></div><b>' + escape(r.title) + '</b><span class="st-run-state ' + statusClass(r) + '">' + runStatus(r) + '</span><footer><small>' + (r.workflow_version ? 'v' + r.workflow_version : 'Conversation') + ' · ' + (r.mode === 'desktop' ? 'Desktop' : 'Hosted') + '</small><small>' + money(r.cost_usd) + '</small></footer></button>').join('') : '<div class="st-list-empty"><span>✓</span><b>All clear.</b><p>No runs need review.</p><button class="text-button" data-st-filter="all">Show all runs</button></div>';
    }
    function render() {
      if (!selected() && app.state.runs.length) select(app.state.runs.slice(-1)[0].id, false);
      if (filter === 'waiting' && (!selected() || selected().status !== 'awaiting_demo_approval')) {
        const waiting = app.state.runs.slice().reverse().find(r => r.status === 'awaiting_demo_approval');
        if (waiting) select(waiting.id, false, false);
      }
      renderMetrics(); renderList();
      const reviewEmpty = filter === 'waiting' && !app.state.runs.some(r => r.status === 'awaiting_demo_approval');
      $('.st-main').hidden = reviewEmpty;
      $('.st-inspector').hidden = reviewEmpty;
      $('#studioReviewEmpty').hidden = !reviewEmpty;
      document.querySelector('[data-st-action="rerun"]').disabled = reviewEmpty || !selected();
      if (reviewEmpty) return;
      const r = selected();
      if (!r) return;
      const trace = app.trace(r.id);
      selectedStep = Math.max(0, Math.min(selectedStep, trace.length - 1));
      const node = trace[selectedStep], version = r.workflow_snapshot;
      $('#studioRunHeading').innerHTML = '<div class="st-run-meta"><span class="st-state ' + statusClass(r) + '">' + runStatus(r) + '</span><code>' + r.id + '</code></div><h2>' + escape(r.title) + '</h2><div class="st-run-subtitle"><span>' + (r.workflow_version ? 'Workflow v' + r.workflow_version : version ? 'Draft test' : 'Conversation') + '</span><span>' + (version ? escape(version.trigger) : 'Asked in Chat') + '</span></div><div class="st-run-links"><button data-st-action="chat">Open conversation ↗</button><button data-st-action="builder">' + (version ? 'Edit in Builder' : 'Make reusable') + ' ↗</button>' + (version ? '<button class="st-hash-button" data-fingerprint-run="' + r.id + '" title="Fingerprint of the exact workflow version used by this run"># Workflow fingerprint</button>' : '') + '</div>';
      $('#studioTrace').innerHTML = trace.map((step, i) => '<div class="st-trace-row ' + step.status + '"><span class="st-track-point">' + (step.status === 'completed' ? '✓' : step.status === 'waiting' ? 'Ⅱ' : '−') + '</span><button class="st-node ' + (i === selectedStep ? 'selected' : '') + '" data-st-step="' + i + '" aria-pressed="' + String(i === selectedStep) + '"><span class="st-node-icon ' + step.kind + '">' + (icons[step.kind] || '◇') + '</span><span class="st-node-copy"><small>' + String(i + 1).padStart(2, '0') + ' / ' + escape(step.kind.toUpperCase()) + '</small><b>' + escape(step.title) + '</b><span>' + (step.route ? (step.route.model ? escape(step.route.model.split(' · ')[0]) + ' · ' : '') + locations[step.route.location] : step.kind === 'approval' ? 'Human review · ' + (r.approval.decision === 'pending' ? 'action paused' : r.approval.decision) : step.kind === 'action' ? 'Sample action · ' + (step.status === 'completed' ? 'no real send' : 'not executed') : 'Saved workflow instruction') + '</span></span><span class="st-node-end">' + (step.cost ? money(step.cost) : step.kind === 'approval' ? step.status === 'waiting' ? 'Review' : 'Recorded' : step.kind === 'action' ? step.status === 'completed' ? 'Done' : 'Held' : 'No charge') + '<i>›</i></span></button></div>').join('');
      $('#studioRunFooter').innerHTML = '<div><span class="st-evidence-icon">▥</span><div><b>Evidence attached to this run</b><p>' + r.steps.length + ' routing records · ' + (r.approval.required ? 'approval ' + r.approval.decision : 'no external action') + ' · unsigned sample</p></div><button class="text-button" data-st-action="receipt">Inspect ↗</button></div><button class="st-ledger-link" data-ledger-run="' + r.id + '">Every action for this run <span>Open workspace ledger ↗</span></button>';
      $('#studioStepNumber').textContent = String(selectedStep + 1).padStart(2, '0') + ' / ' + String(trace.length).padStart(2, '0');
      $('#studioStepHeading').innerHTML = '<span class="st-node-icon ' + node.kind + '">' + (icons[node.kind] || '◇') + '</span><h3>' + escape(node.title) + '</h3><span class="st-detail-status ' + node.status + '">' + ({ completed: 'Completed · sample', waiting: 'Waiting for your decision', blocked: 'Blocked by approval', rejected: 'Rejected by reviewer', skipped: 'Not executed' })[node.status] + '</span>';
      document.querySelectorAll('[data-st-tab]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.stTab === inspectorTab)));
      renderInspector(r, node);
    }
    function pair(label, value) { return '<div><dt>' + label + '</dt><dd>' + escape(value) + '</dd></div>'; }
    function renderInspector(r, node) {
      let html = '';
      if (inspectorTab === 'output') {
        if (node.kind === 'approval') {
          html = '<div class="st-inspector-note ' + (node.status === 'waiting' ? 'amber' : '') + '"><b>' + (node.status === 'waiting' ? 'This proposed send waits for approval.' : node.status === 'rejected' ? 'The action was stopped.' : 'Your decision is recorded.') + '</b><p>' + escape(node.output) + '</p></div><span class="st-section-label">PROPOSED MESSAGE</span><div class="st-draft-output"><div><span>To</span><b>Sample team inbox</b></div><p>' + escape(node.draft) + '</p></div>';
          if (node.status === 'waiting') html += '<div class="st-approval-actions"><button class="primary" data-st-decision="approve">✓ Approve sample</button><button class="secondary" data-st-decision="reject">Reject</button></div><p class="st-footnote">Updates this preview record only. No real message is sent.</p>';
          else html += '<dl class="st-details">' + pair('Reviewer', 'Demo reviewer') + pair('Decision', r.approval.decision) + '</dl>';
        } else {
          html = '<span class="st-section-label">' + (node.kind === 'source' ? 'INPUT CONTEXT' : node.kind === 'action' ? 'ACTION RESULT' : 'STEP OUTPUT') + '</span><div class="st-output-paper"><p>' + escape(node.output) + '</p></div>';
          if (node.route) html += '<dl class="st-details">' + pair('Executor', locations[node.route.location]) + pair('Model', node.route.model || 'Deterministic step') + pair('Sample charge', money(node.cost)) + pair('Example tokens', node.tokens.toLocaleString()) + '</dl><div class="st-route-reason"><b>Why this route?</b><p>' + escape(node.route.reason) + '</p><button class="text-button" data-dialog="compute">Routing controls →</button></div>';
          if (node.kind === 'action' && node.status === 'blocked') html += '<button class="primary" data-st-action="approval-step">Review the approval gate →</button>';
        }
      } else if (inspectorTab === 'receipt') {
        html = '<span class="st-section-label">TRANSACTIONS FOR THIS RUN</span><p class="st-transaction-intro">Follow the processing steps and proposed action. Every item belongs to this same run.</p><ol class="st-transactions">' + r.steps.map((s, i) => '<li><span>' + String(i + 1).padStart(2, '0') + '</span><div><b>' + escape(s.step) + '</b><small>' + locations[s.location] + '</small></div><strong>' + money(s.cost_usd) + '</strong></li>').join('') + (r.approval.required ? '<li><span>04</span><div><b>Approval & action</b><small>' + (r.approval.decision === 'pending' ? 'Awaiting review · not sent' : r.approval.decision === 'reject' ? 'Rejected · action blocked' : 'Approved · sample action only') + '</small></div><strong>—</strong></li>' : '') + '</ol><div class="st-transaction-total"><span>Sample run total</span><b>' + money(r.cost_usd) + '</b></div><p class="st-footnote">Simulated usage records, not on-chain transfers or payments. No real action or charge occurred.</p><div class="st-inspector-note"><b>Unsigned preview evidence</b><p>No production executor has signed these example transactions.</p></div><dl class="st-details">' + pair('Receipt', r.receipt_id) + pair('Conversation', r.task_id) + pair('Workflow version', r.workflow_version_id || 'Not a saved version') + pair('Selected step', node.id) + '</dl><button class="secondary st-full-width" data-st-action="export">Export transactions & receipt ↓</button><div class="st-signature-card"><span>⌁</span><b>Try a real signature check</b><p>Verify a signed example, then change its cost to see the signature fail.</p><button class="text-button" data-dialog="proof">Open verification lab →</button></div>';
      } else {
        const version = r.workflow_snapshot;
        const source = r.steps[0].source;
        html = '<span class="st-section-label">POLICY USED FOR THIS RUN</span><dl class="st-details">' + pair('Input permission', 'Read selected sample records') + pair('Source', sources[source] || 'Sample records') + pair('External action', r.approval.required ? 'Approval required before send' : 'No external action') + pair('Premium API', r.steps.some(s => s.executor === 'premium_api') ? 'Enabled for the review step' : 'Not enabled') + pair('Execution', r.mode === 'desktop' ? 'Desktop scenario' : 'RailCall server scenario') + pair('Trigger', version ? version.trigger : 'Asked in Chat') + '</dl><div class="st-inspector-note"><b>A saved snapshot.</b><p>Editing the draft will not rewrite the version or policy this run used.</p></div><button class="secondary st-full-width" data-st-action="builder">Edit the next version →</button>';
      }
      $('#studioInspectorBody').innerHTML = html;
    }
    function exportRun(r) {
      const url = URL.createObjectURL(new Blob([JSON.stringify(r, null, 2)], { type: 'application/json' }));
      const a = document.createElement('a'); a.href = url; a.download = r.receipt_id + '.json'; a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    }
    $('#studioView').addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button) return;
      try {
        if (button.dataset.stRun) select(button.dataset.stRun);
        if (button.dataset.stFilter) { filter = button.dataset.stFilter; if (filter === 'waiting') { const waiting = app.state.runs.slice().reverse().find(r => r.status === 'awaiting_demo_approval'); if (waiting) select(waiting.id, false, false); } options.renderWorkspace(); }
        if (button.dataset.stStep !== undefined) {
          selectedStep = Number(button.dataset.stStep); inspectorTab = 'output'; render();
          const focus = document.querySelector('[data-st-step="' + selectedStep + '"]'); if (focus) focus.focus({ preventScroll: true });
          if (window.matchMedia('(max-width: 620px)').matches) $('.st-inspector').scrollIntoView({ behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
        }
        if (button.dataset.stTab) { inspectorTab = button.dataset.stTab; render(); document.querySelector('[data-st-tab="' + inspectorTab + '"]').focus({ preventScroll: true }); }
        const r = selected();
        if (!r) return;
        if (button.dataset.stDecision) {
          app.decide(r.id, button.dataset.stDecision);
          const owner = app.state.tasks.find(t => t.id === r.task_id);
          owner.messages.push({ role: 'assistant', text: 'Studio review: sample action ' + (button.dataset.stDecision === 'approve' ? 'approved' : 'rejected') + '. The same run record has been updated; no external action occurred.', runId: r.id });
          options.renderWorkspace(); options.toast(button.dataset.stDecision === 'approve' ? 'Sample approved. Receipt and conversation updated.' : 'Sample rejected. Downstream action blocked.');
        }
        if (button.dataset.stAction === 'chat') { app.state.activeId = r.task_id; options.navigate('chat'); }
        if (button.dataset.stAction === 'builder') { app.state.activeId = r.task_id; app.makeDraft(); options.navigate('builder'); }
        if (button.dataset.stAction === 'receipt') options.inspectReceipt(r.id);
        if (button.dataset.stAction === 'transactions') { inspectorTab = 'receipt'; render(); const tab = document.querySelector('[data-st-tab="receipt"]'); tab.focus({ preventScroll: true }); if (window.matchMedia('(max-width: 620px)').matches) $('.st-inspector').scrollIntoView({ block: 'start' }); }
        if (button.dataset.stAction === 'export') exportRun(r);
        if (button.dataset.stAction === 'approval-step') { selectedStep = app.trace(r.id).findIndex(n => n.kind === 'approval'); inspectorTab = 'output'; render(); }
        if (button.dataset.stAction === 'rerun') { const next = options.run(r.id); filter = 'all'; select(next.id); options.toast('New sample run created. Review its result here.'); }
      } catch (error) { options.toast(error.message); }
    });
    return { enter, render, openRun: select, openStep: index => { selectedStep = index; inspectorTab = 'output'; render(); }, showTransactions: () => { inspectorTab = 'receipt'; render(); } };
  }
  root.RailCallStudio = { create };
})(globalThis);
