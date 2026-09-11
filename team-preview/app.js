(function () {
  "use strict";

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

  const surfaces = {
    chat: { title: "New task", eyebrow: "Workspace" },
    builder: { title: "Workflow builder", eyebrow: "Build" },
    studio: { title: "Studio", eyebrow: "Observe" },
  };

  const receipts = [
    { id: "rcpt_8F24", icon: "↗", task: "Support summary + fixes", detail: "Chat · 3,412 tokens", models: ["L", "A"], status: "Complete", type: "complete", cost: "$0.041", when: "2 min ago", saved: "76%", policy: "Balanced", hash: "ed25519:7ca1e6cf25a419bb8720f1b30d884e991a231e09", steps: [["Request classified", "RailCall router · routine analysis", "$0.0002"], ["Issues summarized", "Llama 3.3 70B · confidence 81%", "$0.013"], ["Fixes quality-checked", "Astra · escalation threshold met", "$0.028"]] },
    { id: "rcpt_7C19", icon: "◇", task: "Qualify new lead", detail: "Builder · Lead follow-up", models: ["L"], status: "Complete", type: "complete", cost: "$0.006", when: "18 min ago", saved: "91%", policy: "Cost saver", hash: "ed25519:f6b9c2787ad6ed41a0e60a95648931b77c500293", steps: [["Lead received", "HubSpot connector · read", "$0.000"], ["Fit scored: 88", "Llama 3.3 70B · confidence 93%", "$0.004"], ["Draft created", "Llama 3.3 70B", "$0.002"]] },
    { id: "rcpt_6D02", icon: "✓", task: "Send follow-up email", detail: "Builder · Approval gate", models: ["C"], status: "Needs approval", type: "approval", cost: "$0.019", when: "1 hr ago", saved: "48%", policy: "Balanced", hash: "ed25519:09d43e3f2068c61f47b8bd79c19da43db7eb3192", steps: [["Draft generated", "Claude · brand voice requested", "$0.019"], ["Approval requested", "Waiting on workspace owner", "$0.000"]] },
    { id: "rcpt_5A77", icon: "≋", task: "Compare launch plans", detail: "Chat · 2 documents", models: ["L"], status: "Complete", type: "complete", cost: "$0.009", when: "Yesterday", saved: "86%", policy: "Balanced", hash: "ed25519:458fd78f1cf0caa6b518f8d55b14065baf26405d", steps: [["Documents parsed", "Local document reader", "$0.000"], ["Differences analyzed", "Llama 3.3 70B", "$0.009"]] },
    { id: "rcpt_4B11", icon: "!", task: "Update CRM records", detail: "Builder · 12 records", models: ["L"], status: "Blocked", type: "failed", cost: "$0.002", when: "Mon", saved: "—", policy: "Strict", hash: "ed25519:b27d6e0934061ad39398b7833c4df405076168e8", steps: [["Change proposed", "Llama 3.3 70B", "$0.002"], ["Policy check blocked", "Missing CRM write approval", "$0.000"]] },
  ];

  const connections = [
    { name: "Gmail", mark: "M", cls: "gmail", account: "patrick@company.com", copy: "Draft and send approved customer email." },
    { name: "HubSpot", mark: "H", cls: "hubspot", account: "RailCall Demo", copy: "Read leads and write approved updates." },
    { name: "Slack", mark: "S", cls: "slack", account: "Acme workspace", copy: "Read channels and send approved messages." },
    { name: "Google Drive", mark: "D", cls: "drive", account: "My Drive", copy: "Use selected files as governed context." },
    { name: "Local runtime", mark: "R", cls: "local", account: "Not connected", copy: "Offload eligible work to your own hardware.", action: "Set up desktop" },
    { name: "GitHub", mark: "G", cls: "github", account: "patrick/railcall", copy: "Inspect repositories and propose changes." },
  ];

  function navigate(name) {
    if (!surfaces[name]) return;
    $$(".surface").forEach((el) => { el.hidden = el.dataset.surface !== name; el.classList.toggle("is-active", el.dataset.surface === name); });
    $$("[data-nav]").forEach((el) => el.classList.toggle("is-active", el.dataset.nav === name && el.classList.contains("nav-item")));
    $("#pageTitle").textContent = surfaces[name].title;
    $("#pageEyebrow").textContent = surfaces[name].eyebrow;
    $(".sidebar").classList.remove("is-open");
  }

  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function sendMessage(text) {
    const input = $("#chatInput");
    const prompt = (text || input.value).trim();
    if (!prompt) return;
    navigate("chat");
    $("#welcomeBlock").hidden = true;
    const conversation = $("#conversation");
    conversation.insertAdjacentHTML("beforeend", `<article class="message user"><span class="message-avatar">PL</span><div><div class="message-head"><b>You</b><small>now</small></div><div class="message-body"><p>${escapeHtml(prompt)}</p></div></div></article>`);
    conversation.insertAdjacentHTML("beforeend", `<article class="message assistant is-typing"><span class="message-avatar">R</span><div><div class="message-head"><b>RailCall</b><small>routing…</small></div><div class="typing-dots"><i></i><i></i><i></i></div></div></article>`);
    input.value = "";
    resizeInput();
    $("#chatScroll").scrollTop = $("#chatScroll").scrollHeight;
    $("#costPreview").textContent = "Routing…";

    window.setTimeout(() => {
      const typing = $(".message.is-typing");
      if (typing) typing.remove();
      conversation.insertAdjacentHTML("beforeend", `<article class="message assistant"><span class="message-avatar">R</span><div><div class="message-head"><b>RailCall</b><small>just now</small></div><div class="message-body"><p>I mapped this into a practical first pass. The highest-leverage move is to start with the routine analysis on our low-cost Llama pool, then ask a premium model to review only the parts where confidence drops.</p><ul><li><b>Start:</b> collect and structure the relevant context.</li><li><b>Route:</b> keep repeatable work on Llama; escalate ambiguous reasoning.</li><li><b>Control:</b> require approval before any external action.</li><li><b>Inspect:</b> write one receipt with the full model and cost trace.</li></ul><div class="route-receipt-inline"><span class="mini-model llama">L</span><span><b>Completed with Llama 3.3</b><small>No premium escalation needed · receipt rcpt_8F25</small></span><strong>$0.006</strong></div></div></div></article><div class="savings-nudge"><span class="local-icon">⌄</span><span><b>This task could run locally for about $0.001.</b><small>The web route stayed inexpensive. Desktop can take it further.</small></span><button type="button" data-open-install>See how</button></div>`);
      $("#costPreview").textContent = "Last run $0.006";
      $("#chatScroll").scrollTop = $("#chatScroll").scrollHeight;
    }, 950);
  }

  function resizeInput() {
    const input = $("#chatInput");
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    const chars = input.value.trim().length;
    $("#costPreview").textContent = chars > 170 ? "Est. $0.01–$0.03" : "Est. < $0.01";
  }

  function renderReceipts() {
    const body = $("#receiptRows");
    body.innerHTML = receipts.map((receipt, index) => `<tr data-receipt="${receipt.id}" class="${index === 0 ? "is-selected" : ""}"><td><div class="task-cell"><span>${receipt.icon}</span><span><b>${receipt.task}</b><small>${receipt.detail}</small></span></div></td><td><div class="model-stack">${receipt.models.map((m) => `<span class="mini-model ${m === "A" ? "astra" : "llama"}">${m}</span>`).join("")}</div></td><td><span class="status-pill ${receipt.type}">${receipt.status}</span></td><td class="cost-cell">${receipt.cost}</td><td class="when-cell">${receipt.when}</td></tr>`).join("");
    showReceipt(receipts[0].id);
  }

  function showReceipt(id) {
    const receipt = receipts.find((item) => item.id === id) || receipts[0];
    $$("#receiptRows tr").forEach((row) => row.classList.toggle("is-selected", row.dataset.receipt === receipt.id));
    $("#receiptDetail").innerHTML = `<div class="detail-head"><span><small>${receipt.id}</small><b>${receipt.task}</b></span><span class="verified">✓ SIGNED</span></div><div class="detail-summary"><div><small>Total cost</small><b>${receipt.cost}</b></div><div><small>Saved</small><b>${receipt.saved}</b></div><div><small>Policy</small><b>${receipt.policy}</b></div></div><div class="trace-title">Execution trace</div><div class="trace-list">${receipt.steps.map((step) => `<div class="trace-step"><span>✓</span><div><b>${step[0]}</b><small>${step[1]}</small></div><em>${step[2]}</em></div>`).join("")}</div><div class="hash-box">${receipt.hash}</div><button class="detail-action" type="button">Verify receipt integrity</button>`;
  }

  function renderConnections() {
    $("#connectionGrid").innerHTML = connections.map((connection) => `<article class="connection-card"><div class="connection-top"><span class="connection-logo ${connection.cls}">${connection.mark}</span><span><b>${connection.name}</b><small>${connection.account}</small></span>${connection.cls === "local" ? "" : '<i class="connected-dot" title="Connected"></i>'}</div><p>${connection.copy}</p><button type="button" ${connection.cls === "local" ? "data-open-install" : ""}>${connection.action || "Manage connection"}</button></article>`).join("");
  }

  function openModal(modal) {
    modal.hidden = false;
    document.body.style.overflow = "hidden";
    const close = $("[data-close-modal]", modal);
    if (close) close.focus();
  }

  function closeModals() {
    $$(".modal-backdrop").forEach((modal) => { modal.hidden = true; });
    document.body.style.overflow = "";
  }

  function testWorkflow() {
    const button = $("#testWorkflow");
    const nodes = $$(".flow-node");
    const status = $("#flowStatus");
    button.disabled = true;
    button.textContent = "Running…";
    status.innerHTML = "<span></span><b>Test running</b><small>Following the governed route</small>";
    nodes.forEach((node) => node.classList.remove("is-running", "is-complete"));
    nodes.forEach((node, index) => {
      window.setTimeout(() => {
        if (index > 0) nodes[index - 1].classList.replace("is-running", "is-complete");
        node.classList.add("is-running");
      }, index * 430);
    });
    window.setTimeout(() => {
      nodes[nodes.length - 1].classList.replace("is-running", "is-complete");
      status.innerHTML = "<span></span><b>Test complete</b><small>5 steps · $0.012 · receipt written</small>";
      button.disabled = false;
      button.textContent = "▶ Test again";
      $("#toast").classList.add("is-visible");
      window.setTimeout(() => $("#toast").classList.remove("is-visible"), 5000);
    }, nodes.length * 430 + 250);
  }

  document.addEventListener("click", (event) => {
    const nav = event.target.closest("[data-nav]");
    if (nav) navigate(nav.dataset.nav);
    const prompt = event.target.closest("[data-prompt]");
    if (prompt) sendMessage(prompt.dataset.prompt);
    if (event.target.closest("[data-open-install]")) openModal($("#installModal"));
    if (event.target.closest("[data-open-usage]")) openModal($("#usageModal"));
    if (event.target.closest("[data-open-why]")) openModal($("#whyModal"));
    if (event.target.closest("[data-reload-studio]")) {
      const frame = $("#localStudioFrame");
      frame.src = frame.src;
    }
    if (event.target.closest("[data-close-modal]")) closeModals();
    if (event.target.classList.contains("modal-backdrop")) closeModals();
    const studioTab = event.target.closest("[data-studio-tab]");
    if (studioTab) {
      $$("[data-studio-tab]").forEach((tab) => tab.classList.toggle("is-active", tab === studioTab));
      $$("[data-studio-panel]").forEach((panel) => { panel.hidden = panel.dataset.studioPanel !== studioTab.dataset.studioTab; panel.classList.toggle("is-active", !panel.hidden); });
    }
    const receiptRow = event.target.closest("[data-receipt]");
    if (receiptRow) showReceipt(receiptRow.dataset.receipt);
    const node = event.target.closest("[data-node]");
    if (node) $$(".flow-node").forEach((item) => item.classList.toggle("is-selected", item === node));
    const toggle = event.target.closest(".toggle");
    if (toggle) { toggle.classList.toggle("is-on"); toggle.setAttribute("aria-pressed", String(toggle.classList.contains("is-on"))); }
  });

  $("#sendButton").addEventListener("click", () => sendMessage());
  $("#chatInput").addEventListener("input", resizeInput);
  $("#chatInput").addEventListener("keydown", (event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); sendMessage(); } });
  $("#testWorkflow").addEventListener("click", testWorkflow);
  $("#builderChat").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("#builderChatInput");
    const change = input.value.trim();
    if (!change) return;
    const status = $("#flowStatus");
    status.innerHTML = "<span></span><b>Updating workflow…</b><small>RailCall is applying your instruction</small>";
    input.value = "";
    window.setTimeout(() => {
      status.innerHTML = `<span></span><b>Workflow updated</b><small>${escapeHtml(change.slice(0, 42))}${change.length > 42 ? "…" : ""}</small>`;
      $("#toast").innerHTML = '<span>✓</span><div><b>Workflow updated</b><small>Your change is ready to test</small></div><button type="button" data-nav="builder">View</button>';
      $("#toast").classList.add("is-visible");
      window.setTimeout(() => $("#toast").classList.remove("is-visible"), 3500);
    }, 700);
  });
  $(".mobile-menu").addEventListener("click", () => $(".sidebar").classList.toggle("is-open"));
  const receiptSearch = $("#receiptSearch");
  if (receiptSearch) receiptSearch.addEventListener("input", (event) => {
    const term = event.target.value.toLowerCase();
    $$("#receiptRows tr").forEach((row) => { row.hidden = !row.textContent.toLowerCase().includes(term); });
  });
  document.addEventListener("keydown", (event) => { if (event.key === "Escape") closeModals(); if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") { event.preventDefault(); navigate("chat"); $("#chatInput").focus(); } });

  const studioFrame = $("#localStudioFrame");
  if (studioFrame) studioFrame.addEventListener("load", () => {
    const status = $(".local-studio-status b");
    if (status) status.textContent = "Connected locally";
  });
})();
