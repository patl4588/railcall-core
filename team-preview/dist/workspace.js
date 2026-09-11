(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const app = RailCallModel.createModel();
  let studio, activity, marketplace, library, integrations, builder, economics, monitor;
  let view = "chat", receiptId = null, pendingId = null, busy = false, toastTimer, samplePromise;
  const escape = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
  const money = (n) => "$" + Number(n).toFixed(3);
  const sourceName = (s) => ({ sample: "Sample records", hubspot_preview: "HubSpot sample", gmail_preview: "Gmail sample" })[s] || "Sample records";
  const locationName = (s) => ({ customer_device: "Your computer", railcall_servers: "RailCall servers", external_provider: "External model API" })[s];
  const latest = () => app.runForTask().slice(-1)[0];
  const selectedRun = () => app.state.runs.find((r) => r.id === receiptId) || latest();
  const statusName = (s) => ({ awaiting_demo_approval: "Needs review · demo", completed_preview: "Completed · preview", cancelled_preview: "Cancelled · preview" })[s] || s;
  function toast(message) { clearTimeout(toastTimer); $("#toast").textContent = message; $("#toast").hidden = false; toastTimer = setTimeout(() => $("#toast").hidden = true, 4000); }
  function message(role, text, runId) { app.active().messages.push({ role: role, text: text, runId: runId || null }); }
  const views = ["home", "chat", "builder", "studio", "activity", "library", "studioMap", "marketplace", "integrations", "railhub", "agents", "monitor"];
  function navigate(name, updateHistory = true) {
    if (!views.includes(name)) return;
    const changed = view !== name;
    view = name;
    document.body.classList.toggle("is-home", name === "home");
    if (name === "studio") studio.enter();
    if (name === "monitor") app.seedStudioExamples();
    if (name === "activity") { app.seedStudioExamples(); if (activity && updateHistory) activity.reset(); }
    if (name === "marketplace") marketplace.enter();
    if (name === "library") { app.seedStudioExamples(); if (library && updateHistory) library.reset(); }
    document.title = name === "railhub" ? "Railhub — Organization services in RailCall" : name === "home" ? "RailCall — One workspace. Your choice of compute." : "RailCall — " + ({activity:"Studio · actions & ledger",studio:"Studio · run details",studioMap:"Studio sections",library:"Workflow library",marketplace:"Marketplace",chat:"Chat",builder:"Builder"}[name] || "Workspace");
    if (name !== "railhub") document.body.classList.remove("standalone");
    if (updateHistory && !document.body.classList.contains("standalone")) { const url = new URL(location.href); url.searchParams.delete("page"); if (name === "home") url.searchParams.delete("view"); else url.searchParams.set("view", name); const next = url.pathname + url.search; if (next !== location.pathname + location.search || location.hash) history.pushState(null, "", next); }
    views.forEach((v) => $("#" + v + "View").hidden = v !== name);
    $$(".nav,.market-entry,.library-nav-link").forEach((b) => { const isCurrent = b.dataset.view === name || (["studio","studioMap"].includes(name) && b.dataset.view === "activity"); b.classList.toggle("active", isCurrent); if(isCurrent)b.setAttribute("aria-current", "page");else b.removeAttribute("aria-current"); });
    $(".sidebar").classList.remove("open"); render();
    if (changed) {
      window.scrollTo(0, 0);
      const target = name === "chat" ? $("#chatInput") : name === "home" ? $("#heroInput") : $("#" + name + "View");
      if (target && updateHistory) { if (!target.matches("input,textarea")) target.setAttribute("tabindex", "-1"); target.focus({preventScroll:true}); }
    }
  }
  async function startFromHome(prompt) {
    const text = String(prompt || "").trim();
    if (!text || busy) return;
    if (app.active().messages.length || app.active().draft) app.newTask();
    receiptId = null;
    navigate("chat");
    await send(text);
  }
  function render() {
    const t = app.active(), runs = app.runForTask(), version = app.latestVersion();
    $("#contextTitle").textContent = t.title;
    $("#contextMeta").textContent = "One task · " + runs.length + " run" + (runs.length === 1 ? "" : "s") + (version ? " · workflow v" + version.version : "");
    if (view === "activity") { $("#contextTitle").textContent = "All actions & ledger"; $("#contextMeta").textContent = "Workspace-wide · " + app.state.events.length + " historical events"; }
    if (view === "marketplace") { $("#contextTitle").textContent = "Public Marketplace"; $("#contextMeta").textContent = "Real modules & workflows · railcall.ai"; }
    if (view === "library") { $("#contextTitle").textContent = "Workflow library"; $("#contextMeta").textContent = "Workspace · saved workflows and versions"; }
    if (view === "studioMap") { $("#contextTitle").textContent = "Studio sections"; $("#contextMeta").textContent = "Build · Run · Trust · System"; }
    if (view === "integrations") { $("#contextTitle").textContent = "Integrations"; $("#contextMeta").textContent = "Tools & data · no accounts connected"; }
    $("#creditValue").textContent = money(app.credit());
    if (view === "agents") { $("#contextTitle").textContent = "Monitored agents"; $("#contextMeta").textContent = "Teach · test · approve · improve"; }
    $("#computePill").textContent = app.state.mode === "hosted" ? "RailCall servers ⌄" : "Desktop scenario ⌄";
    $("#composerCost").textContent = "Sample run: " + money(app.route(app.state.mode, t.premium, t.source).reduce((a,s) => a + s.cost_usd, 0));
    $("#workflowCount").textContent = app.state.workflows.length;
    $("#workflowLibrary").innerHTML = app.state.workflows.length ? app.state.workflows.map((w) => { const v = w.versions.slice(-1)[0]; return '<div class="workflow-library-row"><button class="library-item" data-workflow="' + w.id + '"><b>◇ ' + escape(v.name) + '</b><small>v' + v.version + ' · Run or edit</small></button><button class="workflow-fingerprint" data-workflow-fingerprint="' + w.id + '" title="Workflow fingerprint — look under the hood" aria-label="Inspect fingerprint of ' + escape(v.name) + '">#</button></div>'; }).join("") : "<p>Save work worth repeating. It will live here.</p>";
    $("#taskLibrary").innerHTML = app.state.tasks.map((task) => '<button class="library-item ' + (task.id === t.id ? "active" : "") + '" data-task="' + task.id + '"><b>' + escape(task.title) + '</b><small>' + task.runIds.length + ' sample runs</small></button>').join("");
    $("#welcome").hidden = t.messages.length > 0;
    $("#messages").innerHTML = t.messages.map((m) => {
      const r = app.state.runs.find((item) => item.id === m.runId);
      return '<article class="message ' + m.role + '"><span class="avatar">' + (m.role === "user" ? "You" : "R") + '</span><div><header>' + (m.role === "user" ? "You" : "RailCall · sample response") + '</header><p>' + escape(m.text) + '</p>' + (r ? runChip(r) : "") + (m.role === "assistant" && r ? '<div class="message-actions"><button class="secondary" data-action="make">Make reusable →</button><button class="secondary" data-inspect-run="' + r.id + '">Look under the hood ↗</button></div><small class="hood-chat-hint">Check the steps, transactions, costs, and receipts behind this result.</small>' : "") + '</div></article>';
    }).join("");
    if (app.artifactForTask() || t.draft) $("#messages").insertAdjacentHTML("beforeend", '<div class="message-actions"><button class="secondary" data-view="builder">Open Canvas · inspect your draft →</button></div>');
    if (version) $("#messages").insertAdjacentHTML("beforeend", '<div class="dark-callout"><h3>' + escape(version.name) + ' · v' + version.version + '</h3><p>Ready to use from this conversation.</p><div class="message-actions"><button class="secondary" data-action="run-saved">Run saved workflow</button><button class="secondary" data-view="builder">Edit in Builder</button></div></div>');
    const r = latest();
    if (economics) economics.render();
    renderBuilder();
    if (view === "studio") studio.render();
    if (view === "activity") activity.render();
    if (view === "library") library.render();
    if (view === "integrations") integrations.render();
    if (view === "monitor") { $("#contextTitle").textContent = "Workflow Monitor"; $("#contextMeta").textContent = "Runs · approvals · schedules"; monitor.render(); }
    $$(".compute-option").forEach((b) => { b.classList.toggle("selected", b.dataset.mode === app.state.mode); b.setAttribute("aria-pressed", String(b.dataset.mode === app.state.mode)); });
    $("#computePremium").checked = t.premium;
    renderCompute();
    if ($("#usageDialog").open) renderUsage();
  }
  function runChip(r) { return '<button class="run-chip" data-receipt="' + r.id + '"><span><b>' + statusName(r.status) + '</b><small>' + r.id + ' · ' + (r.mode === "desktop" ? 'Desktop scenario' : 'RailCall servers scenario') + '</small></span><b>' + money(r.cost_usd) + ' <span class="run-receipt-link">↗</span></b></button>'; }
  function renderBuilder() {
    const t = app.active(), d = t.draft;
    $("#builderEmpty").hidden = true; $("#builderContent").hidden = false;
    $("#workflowChat").innerHTML = (t.builderMessages || []).length ? t.builderMessages.map(m => '<div class="builder-chat-message ' + m.role + '"><b>' + (m.role === "user" ? "You" : "Workflow builder · preview") + '</b><p>' + escape(m.text) + '</p></div>').join("") : '<div class="builder-chat-message assistant"><b>Workflow builder</b><p>' + (d ? "The steps from this task are on the canvas. Tell me what you want to change." : "What should this workflow do? Describe its input, the steps, and the outcome. We can add tools and approval points as you go.") + '</p></div>';
    $("#workflowName").disabled = !d; $("#testWorkflow").disabled = !d; $("#saveWorkflow").disabled = !d;
    if (builder) builder.render();
    if (!d) {
      $("#workflowName").value = ""; $("#versionLabel").textContent = "Start with the workflow chat";
      $("#steps").innerHTML = '<div class="builder-canvas-empty"><span>◇</span><h3>Your workflow starts here.</h3><p>Describe the process in chat. Its steps appear on this canvas, ready to inspect and refine.</p></div>';
      $("#editLog").textContent = ""; $("#builderEstimate").textContent = "No draft or run yet.";
      $("#connectionNote").textContent = sourceName(t.source) + " · no live account connected";
      $("#triggerLabel").textContent = "On demand"; $("#premiumReview").checked = t.premium;
      return;
    }
    if (document.activeElement !== $("#workflowName")) $("#workflowName").value = d.name;
    const v = app.latestVersion();
    $("#versionLabel").textContent = v ? "Latest saved: v" + v.version + " · editing draft" : "Draft · not saved";
    $("#steps").innerHTML = d.steps.map((step, i) => '<article class="step"><small>' + String(i + 1).padStart(2, "0") + " / " + escape(step.kind.toUpperCase()) + '</small><b>' + escape(step.title) + '</b><p>' + escape(step.detail) + '</p>' + (step.kind === "source" ? '<button class="text-button" data-dialog="connections">Choose source & permissions →</button>' : step.kind === "model" || step.kind === "review" ? '<button class="text-button" data-dialog="compute">Inspect route →</button>' : "") + '</article>').join("");
    $("#premiumReview").checked = d.premium;
    $("#triggerLabel").textContent = d.trigger;
    $("#connectionNote").textContent = sourceName(d.source) + " · read sample input / draft output";
    $("#builderEstimate").textContent = "Sample model charges: " + money(app.route(app.state.mode, d.premium, d.source).reduce((s,r) => s + r.cost_usd, 0)) + " per run. Drafts require review before a sample send.";
    $("#editLog").textContent = t.edits.length ? "Applied to draft: " + t.edits[t.edits.length - 1] : "";
  }
  function editWorkflow(text) {
    const prompt = String(text || "").trim(); if (!prompt) return;
    const t = app.active(); t.builderMessages = t.builderMessages || [];
    t.builderMessages.push({role:"user",text:prompt});
    if (!t.draft) { app.prepare(prompt); app.makeDraft(); }
    else app.edit(prompt);
    t.builderMessages.push({role:"assistant",text:"Updated the starter workflow: " + t.draft.steps.length + " steps. Inspect the canvas, choose its sample source, and save a version when ready. No live action has run."});
    $("#editInput").value = ""; render();
  }
  function responseText() {
    const kind = app.active().kind;
    if (kind === "support") return "In the sample inbox, three issues repeat: slow onboarding, billing confusion, and missing delivery updates.\n\nThe brief recommends a first-week checklist, clearer invoice descriptions, and a delivery-status message. I drafted the summary for review; nothing has been sent.\n\nIf this becomes weekly work, keep these steps as a workflow.";
    if (kind === "leads") return "The sample lead list has two strong fits and one that needs more context. I drafted a follow-up for the strong fits and kept the uncertain record in a review queue.\n\nSave the steps if you want to run the same qualification and follow-up process again.";
    return "RailCall is designed to bring models, relevant web information, and your connected knowledge together. Instead of asking one LLM to do everything, it matches each step to a model, tool, or source suited to the job.\n\nQuality sets the bar. The aim is better-informed answers with less waiting and less paid compute. Keep eligible work on your computer; use specialist or premium routes when needed and approved.\n\nChat for everyday help, build what you need, and save repeatable work as a workflow. Studio shows the actions, routes, costs, and available evidence. This is a sample explanation—not live inference or web research.";
  }
  async function send(prompt) {
    if (busy || !prompt.trim()) return;
    const t = app.active(); app.recordRequest(prompt); message("user", prompt);
    if (/^run\b/i.test(prompt) && app.latestVersion()) { $("#chatInput").value = ""; execute(true); return; }
    busy = true; $("#chatInput").value = ""; render();
    try {
      const r = app.run();
      if (/\b(build|create|make|design|draft)\b/i.test(prompt) && /\b(website|web page|landing page|app|document|project brief)\b/i.test(prompt)) {
        const kind = /\b(app|application)\b/i.test(prompt) ? "app" : /\b(document|brief)\b/i.test(prompt) ? "document" : "website";
        app.draftArtifact(kind, prompt);
        builder.setMode("anything");
        message("assistant", "I prepared a " + kind + " starter from your request. Open Canvas to inspect, edit, or export it. This preview uses a template, not a live model.", r.id);
      } else if (/\b(automate|automation)\b/i.test(prompt) || (/\b(workflow)\b/i.test(prompt) && /\b(build|create|make|design|draft)\b/i.test(prompt))) {
        app.makeDraft(); builder.setMode("workflow");
        message("assistant", "I prepared a reusable workflow from this request. Open Canvas to inspect its steps, then test and save it. No external action has run.", r.id);
      } else message("assistant", responseText(), r.id);
    } finally { busy = false; render(); }
    $("#chatInput").focus();
  }
  function execute(saved) {
    const r = app.run({ saved: saved, workflow: true });
    receiptId = r.id; pendingId = r.id;
    message("assistant", "The " + (saved ? "saved workflow v" + r.workflow_version : "draft test") + " prepared its sample output. Review the proposed send here before the preview completes.", r.id);
    render(); toast("Sample run is waiting for review.");
    showApproval(r.id);
  }
  function renderCompute() {
    const premium = app.active().premium;
    const comparison = app.compareCosts(premium, app.active().source);
    const hosted = comparison.online_usd, desktop = comparison.local_usd;
    $("#computeComparison").innerHTML = '<div class="comparison"><div><small>RailCall server scenario</small><b>' + money(hosted) + '</b></div><div><small>Desktop cloud charges</small><b>' + money(desktop) + '</b></div><div><small>Cloud-charge reduction</small><b>' + Math.round((hosted - desktop) / hosted * 100) + '%</b></div></div><p>' + (premium ? "Premium review still costs $0.024 in this example. Moving the open-model step locally reduces total cloud charges by 20%, not 90%." : "This routine example has no paid escalation. Its cloud model charge can fall to zero when handled locally; operating the device still has a cost.") + '</p>';
  }
  function renderReceipt() {
    const r = selectedRun();
    if (!r) { $("#receiptContent").innerHTML = '<h2>No run yet.</h2><p>Ask something in Chat or test a workflow to create a sample run record.</p>'; return; }
    receiptId = r.id;
    $("#receiptContent").innerHTML = '<p class="eyebrow">Studio / run receipt</p><h2>' + escape(r.title) + '</h2><span class="status">Unsigned preview record</span><div class="record-grid"><div><small>Conversation</small><b>' + r.task_id + '</b></div><div><small>Run</small><b>' + r.id + '</b></div><div><small>Workflow version</small><b>' + (r.workflow_version ? "v" + r.workflow_version + " · " + r.workflow_version_id : r.workflow_id ? "Unsaved draft snapshot" : "Conversation only") + '</b></div><div><small>Sample cost / tokens</small><b>' + money(r.cost_usd) + " / " + r.tokens.toLocaleString() + '</b></div></div><ol class="record-list">' + r.steps.map((s) => '<li><div><b>' + s.step + '</b><small>' + locationName(s.location) + (s.model ? " · " + escape(s.model) : "") + '</small><small>' + escape(s.reason) + '</small></div><b>' + money(s.cost_usd) + '</b></li>').join("") + '</ol><p>Approval: <b>' + r.approval.decision + '</b> · ' + statusName(r.status) + '. No real external action occurred.</p><div class="message-actions"><button class="secondary" data-action="export-receipt">Export sample JSON</button><button class="text-button" data-dialog="proof">Try cryptographic verification →</button>' + (r.status === "awaiting_demo_approval" ? '<button class="primary" data-approve-run="' + r.id + '">Review proposed action</button>' : "") + '</div><p class="quiet">These costs and execution events are simulated. The hosted executor and local Studio have not signed or received this record.</p>';
  }
  function renderConnections() {
    $("#connectionsContent").innerHTML = '<p>Source for <b>' + escape(app.active().title) + '</b>. Used in Chat, Builder, and this task’s run snapshots.</p>' + ["sample", "hubspot_preview", "gmail_preview"].map((s) => '<button class="connection-choice ' + (s === app.active().source ? "selected" : "") + '" data-source="' + s + '"><b>' + sourceName(s) + '</b><small>Read example records · draft only · no live account access</small></button>').join("");
  }
  function showApproval(runId) {
    const r = app.state.runs.find((x) => x.id === runId) || app.runForTask().slice().reverse().find((x) => x.status === "awaiting_demo_approval");
    pendingId = r ? r.id : null;
    $("#approvalContent").innerHTML = r ? '<p><b>' + escape(r.title) + '</b> · ' + r.id + '</p><div class="dark-callout"><h3>Proposed sample message</h3><p>' + escape(app.trace(r.id).find(step => step.kind === "approval")?.draft || "No proposed external action.") + '</p></div><p>Destination: sample team inbox<br>Source: ' + sourceName(r.workflow_snapshot.source) + '<br>Execution: ' + locationName(r.mode === "hosted" ? "railcall_servers" : "customer_device") + '</p>' + (r.status === "awaiting_demo_approval" ? '<div class="message-actions"><button class="primary" data-decision="approve">Approve sample action</button><button class="secondary" data-decision="reject">Reject sample action</button></div>' : '<span class="status">' + statusName(r.status) + '</span>') + '<p class="quiet">This approval changes the demonstration record only. It cannot authorize a real send in local Studio.</p>' : '<p>No action needs review for this task. Test a workflow to see approval appear in context.</p>';
    openDialog("approval");
  }
  function renderUsage() {
    const spent = 50 - app.credit();
    $("#usageContent").innerHTML = '<div class="comparison"><div><small>Remaining</small><b>' + money(app.credit()) + '</b></div><div><small>Sample charges</small><b>' + money(spent) + '</b></div><div><small>Runs</small><b>' + app.state.runs.length + '</b></div></div><p>The sample balance uses the same run records shown in Chat and Studio. Moving between screens never charges a second time.</p>';
  }
  async function showOwnership() {
    const v = app.latestVersion();
    if (!v) { toast("Save a workflow version first to preview its creator record."); return; }
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(app.canonical(v)));
    const hex = Array.from(new Uint8Array(hash), (b) => b.toString(16).padStart(2, "0")).join("");
    $("#ownershipContent").innerHTML = '<div class="record-grid"><div><small>Workflow</small><b>' + escape(v.name) + '</b></div><div><small>Version</small><b>v' + v.version + ' · ' + v.version_id + '</b></div><div><small>Creator</small><b>Team preview · unverified</b></div><div><small>Token state</small><b>Not minted</b></div></div><small>SHA-256 of this saved version</small><code class="hash">' + hex + '</code><p>This digest identifies the preview package. Production publishing would attach selected creator metadata, license terms, and an optional token reference to that version.</p>';
    openDialog("ownership");
  }
  async function showFingerprint(version, runId) {
    if (!version) { toast("Save a workflow version first to inspect its fingerprint."); return; }
    const snapshot = JSON.parse(JSON.stringify(version));
    const hash = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(app.canonical(snapshot)));
    const hex = Array.from(new Uint8Array(hash), b => b.toString(16).padStart(2, "0")).join("");
    const related = runId ? app.state.runs.find(r => r.id === runId) : app.state.runs.slice().reverse().find(r => r.workflow_version_id === snapshot.version_id);
    $("#fingerprintContent").innerHTML = '<h2>' + escape(snapshot.name) + '</h2><div class="record-grid"><div><small>Exact workflow version</small><b>' + (snapshot.version ? 'v' + snapshot.version : 'Unsaved run snapshot') + '</b></div><div><small>Record</small><b>' + escape(snapshot.version_id || snapshot.id) + '</b></div></div><span class="st-section-label">SHA-256 / CONTENT FINGERPRINT</span><code class="hash">' + hex + '</code><p>This fingerprint identifies this exact saved definition, including its steps and policy. Changing the content or version changes the fingerprint.</p><div class="message-actions">' + (related ? '<button class="primary" data-inspect-run="' + related.id + '" data-studio-transactions="true">Look under the hood · check transactions ↗</button>' : '<button class="secondary" data-workflow="' + snapshot.id + '">Use this workflow in Chat →</button>') + (related ? '<button class="secondary" data-ledger-run="' + related.id + '">All actions for this run →</button>' : '') + '</div><p class="quiet">A content hash is not an executor signature or proof that a run occurred. Signed run receipts provide separate execution evidence. This preview computes the fingerprint locally and does not register it on a blockchain.</p>';
    openDialog("fingerprint");
  }
  function showService(service) {
    const details = {
      uptime: { name: "24/7 uptime", body: "Keep approved work running independently of a person's desktop. Managed execution, monitoring, durable schedules, retries, and failover support continuity. Actual availability commitments and service levels must be defined before launch.", action: "Explore hosted execution", note: "Opens the hosted scenario. No always-on service is provisioned." },
      routing: { name: "Internal capacity routing", body: "Pool approved computers and servers inside your organization. Route each step by data policy, model capability, available memory, queue depth, and cost. External fallback should require explicit permission; work must never silently cross an organization's boundary.", action: "Explore routing controls", note: "Shows sample compute controls. Live organization pools, availability checks, and routing enforcement are not connected." },
      ledger: { name: "Centralized cryptographic ledger", body: "Give agencies one place to inspect signed receipts across connected executors. Link each record to its task, workflow version, policy, approvals, and measured usage. Verify signers and show missing or unverifiable evidence alongside valid records.", action: "View session audit ledger", note: "This example aggregates the same sample runs already visible in Chat and Studio. It does not certify production audit completeness." },
      library: { name: "Centralized workflow library", body: "Give an organization one catalog of approved workflow versions. Teams can bring in Marketplace packages, adapt them in Builder, review changes, and run the approved version from Chat. Ownership, permissions, and version history travel with the package.", action: "View session workflow library", note: "Shows workflows saved in this preview session. No package is published to an organization." }
    }[service];
    if (!details) return;
    $("#serviceContent").innerHTML = RailCallServiceVisuals.render(service, true) + '<h2>' + details.name + '</h2><p>' + details.body + '</p><div class="dark-callout"><h3>Part of your existing work.</h3><p>The same task, workflow version, and run evidence — coordinated across your organization.</p></div><span class="service-status">Service concept · pricing and availability to be defined</span><div class="message-actions"><button class="primary" data-try-service="' + service + '">' + details.action + '</button><a class="text-button" href="https://railhub.ai/" target="_blank" rel="noopener noreferrer">Visit Railhub.ai ↗</a></div><p class="quiet">' + details.note + '</p>';
    openDialog("service");
  }
  async function verify(tamper) {
    $("#verifyResult").textContent = "Checking signature…";
    try {
      if (!samplePromise) samplePromise = fetch("./signed-specimen.json").then((r) => { if (!r.ok) throw new Error("Could not load specimen."); return r.json(); });
      const specimen = await samplePromise;
      const payload = JSON.parse(JSON.stringify(specimen.payload));
      if (tamper) payload.cost_usd = "0.999";
      const bytes = (hex) => Uint8Array.from(hex.match(/.{2}/g), (s) => parseInt(s, 16));
      const key = await crypto.subtle.importKey("raw", bytes(specimen.public_key_hex), { name: "Ed25519" }, false, ["verify"]);
      const ok = await crypto.subtle.verify("Ed25519", key, bytes(specimen.signature_hex), new TextEncoder().encode(app.canonical(payload)));
      $("#verifyResult").textContent = ok ? "Valid signature for the original specimen. Signer: demonstration key; execution evidence: synthetic." : "Verification failed: the changed cost no longer matches the signature.";
    } catch (e) { samplePromise = null; $("#verifyResult").textContent = "Verification unavailable in this browser. No validity claim was made. " + e.message; }
  }
  function openDialog(name) {
    if (name === "connections") { $$("dialog[open]").forEach(d => d.close()); navigate("integrations"); return; }
    if (name === "ledger") { $$("dialog[open]").forEach(d => d.close()); navigate("activity"); return; }
    if (name === "marketplace") { $$("dialog[open]").forEach(d => d.close()); navigate("marketplace"); return; }
    if (name === "sharedLibrary") { $$("dialog[open]").forEach(d => d.close()); navigate("library"); return; }
    if (name === "connections") renderConnections();
    if (name === "compute") renderCompute();
    if (name === "usage") renderUsage();
    if (name === "receipt") renderReceipt();
    if (name === "schedule") { if (!app.active().draft) { toast("Make this conversation reusable before configuring its trigger."); return; } $("#scheduleInput").value = app.active().draft.trigger; }
    $$("dialog[open]").forEach((d) => d.close());
    const dialog = $("#" + name + "Dialog");
    if (dialog) dialog.showModal();
  }
  function download(value, filename) {
    const href = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
    const a = document.createElement("a"); a.href = href; a.download = filename; a.click(); setTimeout(() => URL.revokeObjectURL(href), 1000);
  }
  document.addEventListener("click", async (event) => {
    if (event.target.closest("[data-home]")) { event.preventDefault(); navigate("home"); return; }
    const button = event.target.closest("button");
    if (!button) return;
    try {
      if (button.dataset.view) navigate(button.dataset.view);
      if (button.dataset.integrationOpen) integrations.open(button.dataset.integrationOpen);
      if (button.dataset.libraryEdit) builder.setMode("workflow");
      if (button.dataset.artifactTask) { if (app.state.tasks.some(t=>t.id===button.dataset.artifactTask)) { app.state.activeId=button.dataset.artifactTask; navigate("builder"); builder.setMode("anything"); } }
      if (button.dataset.startPrompt) await startFromHome(button.dataset.startPrompt);
      if (button.dataset.dialog) openDialog(button.dataset.dialog);
      if (button.dataset.task) { app.state.activeId = button.dataset.task; receiptId = null; navigate("chat"); }
      if (button.dataset.workflow) { const w = app.state.workflows.find((x) => x.id === button.dataset.workflow); app.state.activeId = w.taskId; receiptId = null; $$("dialog[open]").forEach((d) => d.close()); navigate("chat"); }
      if (button.dataset.prompt) { navigate("chat"); await send(button.dataset.prompt); }
      if (button.dataset.receipt) { receiptId = button.dataset.receipt; openDialog("receipt"); }
      if (button.dataset.ledgerRun) { $$("dialog[open]").forEach(d => d.close()); navigate("activity"); activity.openRun(button.dataset.ledgerRun); }
      if (button.dataset.inspectRun) { const r = app.state.runs.find((item) => item.id === button.dataset.inspectRun); if (r) { $$("dialog[open]").forEach(d => d.close()); app.state.activeId = r.task_id; navigate("studio"); studio.openRun(r.id); if (button.dataset.studioTransactions) studio.showTransactions(); } }
      if (button.dataset.workflowFingerprint) { navigate("library"); library.open(button.dataset.workflowFingerprint, "versions"); }
      if (button.dataset.fingerprintRun) { const r = app.state.runs.find(item => item.id === button.dataset.fingerprintRun); if (r) await showFingerprint(r.workflow_snapshot, r.id); }
      if (button.dataset.eventFingerprint) { const event = app.state.events.find(item => item.id === button.dataset.eventFingerprint); const w = event && app.state.workflows.find(item => item.id === event.workflow_id); const version = w && w.versions.find(item => item.version_id === event.workflow_version_id); if (version) await showFingerprint(version, event.run_id); }
      if (button.dataset.approveRun) showApproval(button.dataset.approveRun);
      if (button.dataset.catalog) { openDialog("marketplace"); marketplace.setType(button.dataset.catalog === "modules" ? "module" : "workflow"); }
      if (button.dataset.service) showService(button.dataset.service);
      if (button.dataset.tryService) {
        const service = button.dataset.tryService;
        $$("dialog[open]").forEach((d) => d.close());
        if (service === "ledger") openDialog("ledger");
        else if (service === "library") openDialog("sharedLibrary");
        else { if (service === "uptime") app.setMode("hosted"); openDialog("compute"); }
        toast("Exploring the service scenario. No subscription started.");
      }
      if (button.dataset.edit) { editWorkflow(button.dataset.edit); toast("Draft updated. Saved versions stay unchanged."); }
      if (button.dataset.source) { app.setSource(button.dataset.source); render(); renderConnections(); toast("Sample source updated for this task. No account connected."); }
      if (button.dataset.mode) { app.setMode(button.dataset.mode); render(); }
      if (button.dataset.decision) { const r = app.decide(pendingId, button.dataset.decision); const owner = app.state.tasks.find((task) => task.id === r.task_id); owner.messages.push({ role: "assistant", text: button.dataset.decision === "approve" ? "The sample action was approved and its run record updated. No real message was sent." : "The sample action was rejected. The run record keeps that decision.", runId: r.id }); $$("dialog[open]").forEach((d) => d.close()); render(); }
      switch (button.dataset.action) {
        case "new-workflow": app.newTask(); navigate("chat"); $("#chatInput").value = "Create a workflow to "; $("#chatInput").focus(); break;
        case "new": app.newTask(); receiptId = null; navigate("chat"); break;
        case "menu": $(".sidebar").classList.toggle("open"); break;
        case "toggle-sidebar": {
          const collapsed = $(".shell").classList.toggle("sidebar-collapsed");
          button.setAttribute("aria-expanded", String(!collapsed));
          button.setAttribute("aria-label", collapsed ? "Expand sidebar" : "Collapse sidebar");
          button.title = collapsed ? "Expand sidebar" : "Collapse sidebar";
          button.textContent = collapsed ? "›" : "‹";
          break;
        }
        case "make": app.makeDraft(); builder.setMode("workflow"); message("assistant", "Workflow draft prepared. Open Canvas to inspect its steps, test it, and save a version."); render(); break;
        case "save": { const v = app.save(); message("assistant", "Saved " + v.name + " as workflow v" + v.version + ". Run it from this conversation or edit the next version in Builder."); render(); toast("Saved v" + v.version + ". Available from Chat."); break; }
        case "test": execute(false); break;
        case "run-saved": execute(true); break;
        case "receipt": receiptId = latest() ? latest().id : null; openDialog("receipt"); break;
        case "approval": showApproval(); break;
        case "ownership": await showOwnership(); break;
        case "fingerprint": await showFingerprint(app.latestVersion()); break;
        case "visit-hub": $$("dialog[open]").forEach((d) => d.close()); navigate("railhub"); break;
        case "export-receipt": { const r = selectedRun(); if (r) download(r, r.receipt_id + ".json"); break; }
        case "close": button.closest("dialog").close(); break;
        case "verify": await verify(false); break;
        case "tamper": await verify(true); break;
        case "desktop-instructions": $("#desktopInstructions").hidden = !$("#desktopInstructions").hidden; break;
        case "open-local": $("#studioFrame").src = "http://127.0.0.1:8799/v2"; $("#studioFrame").hidden = false; $("#studioHelp").hidden = true; $("#studioStatus").textContent = "Local frame requested · authentication not verified"; break;
      }
    } catch(e) { toast(e.message); }
  });
  $("#chatForm").addEventListener("submit", (e) => { e.preventDefault(); send($("#chatInput").value); });
  $("#heroForm").addEventListener("submit", (e) => { e.preventDefault(); startFromHome($("#heroInput").value); });
  $("#heroInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); startFromHome(e.currentTarget.value); } });
  $("#chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing && e.keyCode !== 229) { e.preventDefault(); send(e.currentTarget.value); } });
  $("#editForm").addEventListener("submit", (e) => { e.preventDefault(); editWorkflow($("#editInput").value); });
  $("#workflowName").addEventListener("change", (e) => { if (app.active().draft) { app.renameDraft(e.target.value); render(); } });
  ["#premiumReview", "#computePremium"].forEach((s) => $(s).addEventListener("change", (e) => { app.setPremium(e.target.checked); render(); }));
  $("#scheduleForm").addEventListener("submit", (e) => { e.preventDefault(); if (app.active().draft) app.setTrigger($("#scheduleInput").value); $("#scheduleDialog").close(); render(); toast("Trigger applied to the draft. Save a new version to keep it."); });
  document.addEventListener("keydown", (e) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); navigate("chat"); $("#chatInput").focus(); } });
  studio = RailCallStudio.create({ model: app, renderWorkspace: render, navigate, toast, openDialog, showApproval, inspectReceipt: (id) => { receiptId = id; openDialog("receipt"); }, run: (id) => { app.state.activeId = app.state.runs.find((r) => r.id === id).task_id; const r = app.run({ replayRunId: id }); message("assistant", "Replayed the selected run’s exact workflow and input snapshot. No external action occurred.", r.id); render(); return r; } });
  activity = RailCallActivity.create({ model: app, openRun: (id, step) => { const r = app.state.runs.find(item => item.id === id); if (!r) return; app.state.activeId = r.task_id; navigate("studio"); studio.openRun(id); if (step !== null) studio.openStep(step); }, review: showApproval, toast });
  marketplace = RailCallMarketplace.create();
  integrations = RailCallIntegrations.create({model:app,chooseSample:source=>{app.setSource(source);render();toast("Sample source updated for this task. No account connected.");}});
  builder = RailCallBuilder.create({model:app,refresh:render,toast});
  library = RailCallLibrary.create({ model: app, navigate, refresh: render, toast, run: versionId => { const r = app.run({ versionId }); message("assistant", "Sample workflow v" + r.workflow_version + " is ready for review. No external action occurred.", r.id); navigate("studio"); studio.openRun(r.id); toast("Review the proposed action in Studio."); } });
  economics = RailCallEconomics.create({model:app});
  monitor = typeof RailCallMonitor !== "undefined" ? RailCallMonitor.create({model:app}) : null;
  function restoreRoute() {
    const params = new URLSearchParams(location.search);
    if (params.get("page") === "railhub") { document.body.classList.add("standalone"); navigate("railhub", false); return; }
    document.body.classList.remove("standalone");
    const requested = params.get("view");
    navigate(views.includes(requested) ? requested : "home", false);
  }
  window.addEventListener("popstate", restoreRoute);
  restoreRoute();
})();
