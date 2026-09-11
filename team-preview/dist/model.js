(function (root) {
  "use strict";
  function createModel() {
    let sequence = 0;
    const id = (type) => type + "_" + String(++sequence).padStart(4, "0");
    const copy = (value) => JSON.parse(JSON.stringify(value));
    const state = { tasks: [], workflows: [], artifacts: [], runs: [], events: [], activeId: null, mode: "hosted" };
    const catalog = [
      { id: "support-brief", category: "workflows", icon: "▤", name: "Weekly support brief", description: "Turn recurring issues into a short brief and proposed fixes, ready for review.", prompt: "Summarize this week's support issues and draft three fixes.", permissions: ["Read selected support records", "Draft a team update", "Require approval before any send"], publisher: "Built-in Studio example", version: "1.0", license: "Preview definition only" },
      { id: "lead-followup", category: "workflows", icon: "↗", name: "Thoughtful lead follow-up", description: "Qualify a lead list, draft personal follow-ups, and keep a person in control.", prompt: "Qualify new leads and draft a personal follow-up.", permissions: ["Read selected lead records", "Draft follow-up messages", "Require approval before any send"], publisher: "Built-in Studio example", version: "1.0", license: "Preview definition only" },
      { id: "team-brief", category: "workflows", icon: "◇", name: "Project update to team brief", description: "Collect a project's updates and prepare a repeatable, reviewable team summary.", prompt: "Prepare a project brief with progress, open questions, and next steps.", permissions: ["Read selected project notes", "Draft a team brief", "Require approval before sharing"], publisher: "Built-in Studio example", version: "1.0", license: "Preview definition only" },
      { id: "short-summary", category: "modules", icon: "≋", name: "Concise summary", description: "Add a clear length constraint to the model step in your current workflow.", instruction: "Keep the summary under 100 words", permissions: ["Use the current workflow's selected input", "Modify draft output only"], publisher: "Built-in Studio example", version: "1.0", license: "Preview definition only" },
      { id: "manager-review", category: "modules", icon: "✓", name: "Manager review", description: "Require a manager to review the proposed action before the workflow proceeds.", instruction: "Add a manager approval before sending", permissions: ["Pause the workflow for review", "Record the approval decision"], publisher: "Built-in Studio example", version: "1.0", license: "Preview definition only" }
    ];
    const active = () => state.tasks.find((t) => t.id === state.activeId);
    function recordEvent(fields) {
      const task = active();
      const event = Object.freeze({ id: id("event"), sequence: state.events.length + 1, created_at: new Date().toISOString(), task_id: task ? task.id : null, task_title: task ? task.title : "Workspace", workflow_id: task ? task.workflowId || (task.draft && task.draft.id) : null, workflow_version_id: null, workflow_version: null, workflow_title: task && task.draft ? task.draft.name : null, run_id: null, receipt_id: null, step_index: null, category: "change", status: "recorded", actor: "Preview user", location: "workspace", cost_usd: null, tokens: 0, simulated: true, integrity_status: "unsigned_preview", ...copy(fields) });
      state.events.push(event); return event;
    }
    function recordRunEvent(run, fields) {
      return recordEvent({ task_id: run.task_id, task_title: run.title, workflow_id: run.workflow_id, workflow_title: run.workflow_snapshot ? run.workflow_snapshot.name : null, workflow_version_id: run.workflow_version_id, workflow_version: run.workflow_version, run_id: run.id, receipt_id: run.receipt_id, location: run.mode === "desktop" ? "customer_device" : "railcall_servers", actor: "Preview executor", ...fields });
    }
    function activityEntries() { return copy(state.events); }
    function newTask() {
      const task = { id: id("task"), title: "New conversation", kind: "general", messages: [], draft: null, workflowId: null, runIds: [], edits: [], premium: false, source: "sample", trigger: "On demand in Chat" };
      state.tasks.push(task); state.activeId = task.id;
      recordEvent({ category: "conversation", kind: "conversation.created", title: "Conversation started", detail: "A new conversation was created in this preview workspace." });
      return task;
    }
    function classify(prompt) { return /lead|follow.up|qualify/i.test(prompt) ? "leads" : /support|inbox|ticket|issue/i.test(prompt) ? "support" : "general"; }
    function prepare(prompt) {
      const task = active();
      task.kind = classify(prompt);
      task.title = task.kind === "support" ? "Support brief" : task.kind === "leads" ? "Lead follow-up" : prompt.slice(0, 55);
      // Premium routing is a per-task permission, not inferred from a keyword.
      task.prompt = prompt;
      const request = recordEvent({ category: "conversation", kind: "conversation.requested", title: "Request added to conversation", detail: prompt });
      task.latest_request = { id: request.id, text: prompt };
      return task;
    }
    function recordRequest(prompt) {
      const t = active();
      if (!t.prompt) return prepare(prompt);
      const request = recordEvent({ category: "conversation", kind: "conversation.requested", title: "Follow-up request added", detail: prompt });
      t.latest_request = { id: request.id, text: prompt };
      return t;
    }
    function makeDraft() {
      const t = active();
      if (t.draft) return t.draft;
      const lead = t.kind === "leads";
      t.draft = {
        id: id("workflow"), task_id: t.id, name: t.title, instruction: t.prompt || "Prepare a useful brief.",
        trigger: t.trigger, source: t.source, premium: t.premium,
        steps: [
          { kind: "source", title: lead ? "Read new leads" : "Read the selected context", detail: "Use sample records for this preview." },
          { kind: "model", title: lead ? "Qualify and draft follow-up" : "Summarize and draft next steps", detail: t.prompt || "Prepare a useful brief." },
          { kind: "review", title: "Check the result", detail: "Check the required fields and supporting context." },
          { kind: "approval", title: "Review before sending", detail: "A person decides whether the proposed action may proceed." },
          { kind: "action", title: lead ? "Send the follow-up" : "Share the brief", detail: "Sample email action; no message will be sent." }
        ]
      };
      recordEvent({ category: "workflow", kind: "workflow.draft_created", title: "Reusable workflow drafted", detail: "Created a draft from this conversation. Nothing has been executed or published." });
      return t.draft;
    }
    function save() {
      const t = active(), draft = makeDraft();
      let w = state.workflows.find((item) => item.id === draft.id);
      if (!w) { w = { id: draft.id, taskId: t.id, versions: [] }; state.workflows.push(w); }
      const version = { ...copy(draft), version: w.versions.length + 1, version_id: id("version") };
      w.versions.push(version); t.workflowId = w.id;
      recordEvent({ category: "workflow", kind: "workflow.version_saved", title: "Workflow v" + version.version + " saved", detail: "Saved " + version.name + " with " + version.steps.length + " steps, its source, trigger, and review policy. Earlier versions stay unchanged.", workflow_id: w.id, workflow_title: version.name, workflow_version: version.version, workflow_version_id: version.version_id });
      return copy(version);
    }
    function latestVersion(task = active()) {
      const w = state.workflows.find((item) => item.id === task.workflowId);
      return w ? copy(w.versions[w.versions.length - 1]) : null;
    }
    function usePackage(packageId) {
      const item = catalog.find((p) => p.id === packageId);
      if (!item) throw new Error("Package not found.");
      const provenance = { catalog_id: item.id, publisher: item.publisher, version: item.version, license: item.license, verified: false };
      if (item.category === "workflows") {
        newTask(); prepare(item.prompt); active().title = item.name;
        const draft = makeDraft(); draft.provenance = provenance;
        const version = save();
        recordEvent({ category: "workflow", kind: "example.workflow_loaded", title: "Built-in example loaded", detail: "Loaded " + item.name + " as a Studio demonstration. This is not a Marketplace package or installation.", workflow_version: version.version, workflow_version_id: version.version_id });
        return version;
      }
      if (!active().draft) throw new Error("Open a workflow in Builder before adding a module.");
      const draft = active().draft;
      if ((draft.modules || []).some((m) => m.catalog_id === item.id)) throw new Error("This module is already in the draft.");
      edit(item.instruction); draft.modules = [...(draft.modules || []), provenance];
      recordEvent({ category: "workflow", kind: "example.instruction_added", title: "Example instruction added", detail: "Added the built-in " + item.name + " instruction to the draft. No public package was installed." });
      return copy(draft);
    }
    function route(mode, premium, source) {
      return [
        { step: "Read context", executor: "deterministic", location: mode === "desktop" ? "customer_device" : "railcall_servers", model: null, cost_usd: 0, input_tokens: 0, output_tokens: 0, reason: "Structured input needs no model.", source: source },
        { step: "Create result", executor: "open_model", location: mode === "desktop" ? "customer_device" : "railcall_servers", model: "Llama · example eligible model", cost_usd: mode === "desktop" ? 0 : 0.006, input_tokens: 900, output_tokens: 240, reason: "Sample routine task assigned to an eligible open model." },
        { step: "Review", executor: premium ? "premium_api" : "deterministic", location: premium ? "external_provider" : mode === "desktop" ? "customer_device" : "railcall_servers", model: premium ? "Approved premium model · example" : null, cost_usd: premium ? 0.024 : 0, input_tokens: premium ? 1140 : 0, output_tokens: premium ? 160 : 0, reason: premium ? "Premium review enabled by the user in this scenario." : "Required-field check; no additional model call." }
      ];
    }
    function compareCosts(premium, source) {
      const sum = steps => Number(steps.reduce((total, step) => total + step.cost_usd, 0).toFixed(6));
      const online = sum(route("hosted", premium, source)), local = sum(route("desktop", premium, source));
      const savings = Number((online - local).toFixed(6));
      return { online_usd: online, local_usd: local, savings_usd: savings,
        premium_usd: sum(route("desktop", premium, source).filter(step => step.executor === "premium_api")),
        reduction_percent: online > 0 ? Math.round(savings / online * 100) : 0,
        basis: "Illustrative cloud model charges for the same input and premium policy; hardware, electricity, and setup excluded." };
    }
    function run(options = {}) {
      const original = options.replayRunId ? state.runs.find(r => r.id === options.replayRunId) : null;
      if (options.replayRunId && !original) throw new Error("The original run was not found.");
      const t = original ? state.tasks.find(task => task.id === original.task_id) : active();
      const version = original ? original.workflow_version ? copy(original.workflow_snapshot) : null : options.versionId ? copy(state.workflows.find(w => w.id === t.workflowId)?.versions.find(v => v.version_id === options.versionId) || null) : options.saved ? latestVersion(t) : null;
      if (options.versionId && !version) throw new Error("That saved version does not belong to this workflow.");
      if (options.saved && !version) throw new Error("Save a workflow first.");
      const snapshot = original ? copy(original.workflow_snapshot) : version || (options.workflow ? copy(makeDraft()) : null);
      const premium = snapshot ? snapshot.premium : t.premium;
      const executionMode = original ? original.mode : state.mode;
      const steps = original ? copy(original.steps) : route(executionMode, premium, snapshot ? snapshot.source : t.source);
      const r = {
        id: id("run"), receipt_id: id("receipt"), task_id: t.id, workflow_id: snapshot ? snapshot.id : null,
        workflow_version: version ? version.version : null, workflow_version_id: version ? version.version_id : null,
        workflow_snapshot: snapshot, title: original ? original.title : snapshot ? snapshot.name : t.title, mode: executionMode, context_kind: original ? original.context_kind : t.kind,
        request_id: original ? original.request_id : t.latest_request ? t.latest_request.id : null,
        input_snapshot: original ? copy(original.input_snapshot) : { prompt: t.latest_request ? t.latest_request.text : t.prompt || "", source: steps[0].source },
        replay_of: original ? original.id : null,
        status: snapshot ? "awaiting_demo_approval" : "completed_preview",
        steps: steps, cost_usd: Number(steps.reduce((sum, s) => sum + s.cost_usd, 0).toFixed(6)),
        cost_comparison: Object.freeze(original ? copy(original.cost_comparison) : compareCosts(premium, snapshot ? snapshot.source : t.source)),
        tokens: steps.reduce((sum, s) => sum + s.input_tokens + s.output_tokens, 0),
        approval: snapshot ? { required: true, decision: "pending" } : { required: false, decision: "not_applicable" },
        simulated: true, real_send_performed: false, signature: null, signer: null,
        integrity_status: "unsigned_preview", created_at: new Date().toISOString()
      };
      state.runs.push(r); t.runIds.push(r.id);
      recordRunEvent(r, { category: "execution", kind: "run.started", title: "Run started", detail: "Started the sample " + (snapshot ? "workflow" : "conversation") + " execution with a captured route and policy.", status: "started" });
      steps.forEach((step, index) => recordRunEvent(r, { category: "execution", kind: "step.completed", title: step.step, detail: step.reason, status: "completed", step_index: index, location: step.location, cost_usd: step.cost_usd, tokens: step.input_tokens + step.output_tokens }));
      if (snapshot) {
        recordRunEvent(r, { category: "approval", kind: "approval.requested", title: "Approval requested", detail: "The proposed sample message needs a person's approval before the action may proceed.", status: "requested", location: "human_review" });
        recordRunEvent(r, { category: "action", kind: "action.held", title: "Proposed action held", detail: "The sample send was not executed. It is waiting for the approval gate.", status: "held" });
      } else recordRunEvent(r, { category: "execution", kind: "run.completed", title: "Conversation result ready", detail: "The sample response completed. No external action was requested.", status: "completed" });
      return r;
    }
    function decide(runId, decision) {
      const r = state.runs.find((item) => item.id === runId);
      if (!r || r.status !== "awaiting_demo_approval") throw new Error("No pending approval for this run.");
      if (!["approve", "reject"].includes(decision)) throw new Error("Invalid decision.");
      r.approval = { required: true, decision: decision, actor: "demo_reviewer", decided_at: new Date().toISOString() };
      r.status = decision === "approve" ? "completed_preview" : "cancelled_preview";
      recordRunEvent(r, { category: "approval", kind: "approval." + (decision === "approve" ? "approved" : "rejected"), title: decision === "approve" ? "Action approved" : "Action rejected", detail: "The demo reviewer " + (decision === "approve" ? "approved" : "rejected") + " the proposed sample action. This decision does not authorize a real send.", status: decision === "approve" ? "approved" : "rejected", actor: "Demo reviewer", location: "human_review" });
      recordRunEvent(r, { category: "action", kind: decision === "approve" ? "action.simulated" : "action.blocked", title: decision === "approve" ? "Sample action completed" : "Action blocked", detail: decision === "approve" ? "The approved action was simulated. No email or external message was sent." : "The rejected action did not execute. The original request and rejection remain in the ledger.", status: decision === "approve" ? "completed" : "blocked" });
      recordRunEvent(r, { category: "execution", kind: decision === "approve" ? "run.completed" : "run.cancelled", title: decision === "approve" ? "Run completed" : "Run stopped", detail: "Run closed with review decision: " + decision + ". Prior events are retained.", status: decision === "approve" ? "completed" : "stopped" });
      return r;
    }
    function edit(text) {
      const t = active(), d = makeDraft();
      if (/friday/i.test(text)) { d.trigger = "Every Friday at 4 PM · America/New_York"; t.trigger = d.trigger; }
      else if (/approval|manager/i.test(text)) { const gate = d.steps.find((s) => s.kind === "approval"); gate.title = "Manager approval"; gate.detail = text; }
      else if (/100 words|shorter|concise/i.test(text)) { d.instruction += "\n" + text; d.steps.find((s) => s.kind === "model").detail = d.instruction; }
      else { d.steps.splice(d.steps.length - 2, 0, { kind: "instruction", title: "Additional instruction", detail: text }); }
      t.edits.push(text);
      recordEvent({ category: "workflow", kind: "workflow.draft_edited", title: "Workflow draft changed", detail: text + ". This modifies the draft only; saved versions and past runs are unchanged." });
      return d;
    }
    function renameDraft(name) {
      const d = makeDraft(), previous = d.name, next = name.trim() || "Untitled workflow";
      if (previous === next) return;
      d.name = next;
      recordEvent({ category: "workflow", kind: "workflow.renamed", title: "Workflow draft renamed", detail: "Renamed draft from " + previous + " to " + next + ". Saved versions are unchanged." });
    }
    function setSource(value) {
      if (!["sample", "hubspot_preview", "gmail_preview"].includes(value)) throw new Error("Unknown sample source.");
      const t = active(); const previous = t.source; t.source = value;
      if (t.draft) { t.draft.source = value; t.draft.steps[0].detail = value === "sample" ? "Use sample records for this preview." : "Sample " + value.replace("_preview", "") + " records · preview permission only"; }
      if (previous !== value) recordEvent({ category: "connection", kind: "connection.selected", title: "Sample source changed", detail: "Source changed from " + previous + " to " + value + ". No live account was connected." });
    }
    function setPremium(on) { const t = active(), previous = t.premium; t.premium = Boolean(on); if (t.draft) t.draft.premium = t.premium; if (previous !== t.premium) recordEvent({ category: "policy", kind: "policy.premium_changed", title: "Premium review " + (t.premium ? "enabled" : "disabled"), detail: "Changed the premium-review setting for the task and draft. Saved versions retain their original policy." }); }
    function setMode(value) { if (!["hosted", "desktop"].includes(value)) throw new Error("Unknown compute mode."); const previous = state.mode; state.mode = value; if (previous !== value) recordEvent({ category: "policy", kind: "policy.compute_changed", title: "Execution scenario changed", detail: "Changed future sample execution from " + previous + " to " + value + ". No device was paired or server provisioned." }); }
    function setTrigger(value) { if (!["On demand in Chat", "Every Friday at 4 PM · America/New_York", "On a new record · webhook"].includes(value)) throw new Error("Unknown trigger."); const t = active(), previous = t.trigger; t.trigger = value; if (t.draft) t.draft.trigger = value; if (previous !== value) recordEvent({ category: "workflow", kind: "workflow.trigger_changed", title: "Workflow trigger changed", detail: "Draft trigger set to: " + value + ". No live scheduler or webhook was created." }); }
    function credit() { return Number((50 - state.runs.reduce((sum, r) => sum + r.cost_usd, 0)).toFixed(6)); }
    function runForTask() { return state.runs.filter((r) => r.task_id === state.activeId); }
    function seedStudioExamples() {
      if (state.runs.length || state.studioExamplesLoaded) return;
      const previousTask = state.activeId, previousMode = state.mode;
      const examples = [
        { packageId: "support-brief", source: "gmail_preview", mode: "hosted", premium: false, decision: null },
        { packageId: "lead-followup", source: "hubspot_preview", mode: "hosted", premium: true, decision: "approve" },
        { packageId: "team-brief", source: "sample", mode: "desktop", premium: false, decision: "reject" }
      ];
      examples.forEach((example) => {
        usePackage(example.packageId); setSource(example.source); setMode(example.mode); setPremium(example.premium);
        if (example.packageId === "support-brief") edit("Run every Friday at 4 PM");
        save();
        const r = run({ saved: true }); r.seeded_example = true;
        if (example.decision) decide(r.id, example.decision);
        active().messages.push({ role: "user", text: active().prompt, runId: null }, { role: "assistant", text: "Studio example: this workflow prepared sample output for review. Its steps, policy, and receipt are available in Studio. No external action occurred.", runId: r.id });
      });
      state.activeId = previousTask; state.mode = previousMode; state.studioExamplesLoaded = true;
    }
    function trace(runId) {
      const r = state.runs.find((item) => item.id === runId);
      if (!r) return [];
      const steps = r.workflow_snapshot ? r.workflow_snapshot.steps : [
        { kind: "source", title: "Read context", detail: "Use the conversation's sample context." },
        { kind: "model", title: "Create result", detail: "Prepare the sample response." },
        { kind: "review", title: "Check result", detail: "Check the required fields." }
      ];
      const lead = r.context_kind === "leads", support = r.context_kind === "support";
      const result = lead ? "Two leads are a strong fit. A third needs more context. Draft a personal next-step message for the qualified leads and hold the uncertain record for review." : support ? "Three recurring themes: slow onboarding, billing confusion, and missing delivery updates. Next steps: a first-week checklist, clearer invoice descriptions, and a delivery-status message." : "Project brief: the initial workspace is ready for review. Next steps are to validate the workflow, review the proposed output, and agree on the next version.";
      return steps.map((step, index) => {
        const routeIndex = { source: 0, model: 1, review: 2 }[step.kind];
        const routeStep = routeIndex === undefined ? null : r.steps[routeIndex];
        const waiting = r.approval.decision === "pending", rejected = r.approval.decision === "reject";
        let status = "completed", detail = step.detail, output = result;
        if (step.kind === "source") output = lead ? "3 sample lead records loaded. Fields: organization, need, team size, and contact permission." : support ? "Sample inbox loaded. Three recurring support themes with example context; no live mailbox access." : "Sample project notes loaded. Fields: progress, open questions, and next steps.";
        if (step.kind === "review") output = routeStep && routeStep.executor === "premium_api" ? "Example premium review: supporting context checked; uncertain conclusions kept for human review." : "Required fields are present. Proposed output remains a draft until the approval gate passes.";
        if (step.kind === "instruction") output = "Saved instruction: " + step.detail;
        if (step.kind === "approval") { status = waiting ? "waiting" : rejected ? "rejected" : "completed"; output = waiting ? "A reviewer must approve the proposed message before the sample action can proceed." : rejected ? "Rejected by the demo reviewer. The downstream action was blocked." : "Approved by the demo reviewer. Decision retained in this run record."; }
        if (step.kind === "action") { status = waiting ? "blocked" : rejected ? "skipped" : "completed"; output = waiting ? "Not executed. Waiting for the approval gate." : rejected ? "Not executed. The reviewer rejected this sample action." : "Sample action completed. No email or external message was actually sent."; }
        return { id: r.id + ":" + index, index, kind: step.kind, title: step.title, detail, status, cost: routeStep ? routeStep.cost_usd : 0, tokens: routeStep ? routeStep.input_tokens + routeStep.output_tokens : 0, route: routeStep, output, draft: result };
      });
    }
    function artifactForTask() { return state.artifacts.find(a => a.task_id === active().id) || null; }
    function draftArtifact(kind, brief) {
      if (!["website", "app", "document"].includes(kind) || !String(brief).trim()) throw new Error("Choose a type and describe your build.");
      let a = artifactForTask();
      if (!a) { a = { id: id("artifact"), task_id: active().id, draft: null, versions: [], messages: [] }; state.artifacts.push(a); }
      const text = String(brief).trim();
      if (!a.draft || a.draft.kind !== kind) a.draft = {kind, title:text.replace(/^(build|create|make|design|draft)\s+(me\s+)?(a|an|the)?\s*/i, "").slice(0,90), brief:text, notes:[], items:[{text:"Outline the idea",done:false},{text:"Review the first draft",done:false},{text:"Share with the team",done:false}]};
      else a.draft.notes.push(text);
      if (active().title === "New conversation") active().title = a.draft.title.slice(0,55);
      a.messages.push({role:"user",text});
      a.messages.push({role:"assistant",text:a.draft.notes.length ? "Added that instruction to your build brief. This template preview does not generate new code with AI; you can edit the title and inspect or export the current draft." : "Your " + kind + " starter is ready to explore. Edit its title, inspect the source, or save a version. This is a template-based preview, not live AI generation."});
      recordEvent({category:"artifact",kind:"artifact.drafted",title:"Artifact draft updated",detail:text,workflow_id:null,workflow_title:null,artifact_id:a.id});
      return a;
    }
    function updateArtifactTitle(title) {
      const a=artifactForTask();if(!a)throw new Error("Create an artifact first.");
      a.draft.title=String(title).trim()||"Untitled build";
      recordEvent({category:"artifact",kind:"artifact.renamed",title:"Artifact title changed",detail:a.draft.title,workflow_id:null,workflow_title:null,artifact_id:a.id});
    }
    function saveArtifact() {
      const a=artifactForTask();if(!a)throw new Error("Create an artifact first.");
      const v={...copy(a.draft),version:a.versions.length+1,version_id:id("artifact_version")};a.versions.push(v);
      recordEvent({category:"artifact",kind:"artifact.version_saved",title:"Artifact v"+v.version+" saved",detail:v.title+" · "+v.kind+" · template preview",workflow_id:null,workflow_title:null,artifact_id:a.id,artifact_version_id:v.version_id});return copy(v);
    }
    function toggleArtifactItem(index) {
      const a=artifactForTask(),item=a&&a.draft.items[index];if(!item)throw new Error("Example item not found.");item.done=!item.done;
      recordEvent({category:"artifact",kind:"artifact.example_interacted",title:"App example updated",detail:item.text+": "+(item.done?"complete":"open"),workflow_id:null,workflow_title:null,artifact_id:a.id});
    }
    function canonical(value) {
      if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
      if (value && typeof value === "object") return "{" + Object.keys(value).sort().map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
      return JSON.stringify(value);
    }
    newTask();
    return { state, catalog, active, newTask, prepare, recordRequest, makeDraft, save, latestVersion, usePackage, route, compareCosts, run, decide, edit, renameDraft, setSource, setPremium, setMode, setTrigger, credit, runForTask, seedStudioExamples, trace, canonical, activityEntries, artifactForTask, draftArtifact, updateArtifactTitle, saveArtifact, toggleArtifactItem };
  }
  if (typeof module !== "undefined" && module.exports) module.exports = { createModel };
  else root.RailCallModel = { createModel };
})(typeof globalThis !== "undefined" ? globalThis : this);
