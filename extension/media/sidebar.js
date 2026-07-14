(function () {
  'use strict';
  const vscode = acquireVsCodeApi();

  const messagesEl  = document.getElementById('messages');
  const inputEl     = document.getElementById('input');
  const sendBtn     = document.getElementById('send-btn');
  const thinkingBar = document.getElementById('thinking-bar');
  const clearBtn    = document.getElementById('clear-btn');
  const serverDot   = document.getElementById('server-dot');
  const ctxHint     = document.getElementById('ctx-hint');

  // Active preview card element (only one at a time)
  var previewEl = null;
  // Active steps panel (rebuilt per user message)
  var stepsEl = null;

  vscode.postMessage({ type: 'checkServer' });

  // ── Send ────────────────────────────────────────────────────────────────────
  function sendMessage() {
    const text = inputEl.value.trim();
    if (!text || sendBtn.disabled) { return; }
    sendBtn.disabled = true;
    inputEl.value = '';
    inputEl.style.height = 'auto';
    appendUser(text);                                   // show immediately
    vscode.postMessage({ type: 'userMessage', text });
  }

  sendBtn.addEventListener('click', sendMessage);
  inputEl.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
  });
  inputEl.addEventListener('input', function () {
    inputEl.style.height = 'auto';
    inputEl.style.height = Math.min(inputEl.scrollHeight, 160) + 'px';
  });
  clearBtn.addEventListener('click', function () {
    messagesEl.innerHTML = '';
    vscode.postMessage({ type: 'clearHistory' });
    appendAssistant('Conversation cleared. How can I help?');
  });

  // ── Messages from extension host ────────────────────────────────────────────
  window.addEventListener('message', function (event) {
    const msg = event.data;
    switch (msg.type) {
      case 'injectUserMessage':
        appendUser(msg.text);
        break;
      case 'assistantMessage':
        appendAssistant(msg.text, msg.provider);
        break;
      case 'stepsBegin':
        beginSteps();
        break;
      case 'step':
        upsertStep(msg.id, msg.text, msg.status);
        break;
      case 'stepsEnd':
        endSteps();
        break;
      case 'preview':
        appendPreview(msg.action, msg.label, msg.detail);
        break;
      case 'previewDismiss':
        dismissPreview();
        break;
      case 'receipt':
        appendReceipt(msg.receipt);
        break;
      case 'searchResults':
        appendSearchResults(msg.query, msg.results, msg.poweredBy);
        break;
      case 'thinking':
        thinkingBar.hidden = !msg.value;
        sendBtn.disabled = !!msg.value;
        if (msg.value) { scrollBottom(); }
        break;
      case 'error':
        appendError(msg.text);
        break;
      case 'serverStatus':
        serverDot.className = msg.healthy ? 'online' : 'offline';
        serverDot.title = msg.healthy ? 'Studio running' : 'Studio offline — run: railcall studio';
        break;
      case 'ctxHint':
        ctxHint.textContent = msg.text || '';
        break;
    }
  });

  // ── Renderers ────────────────────────────────────────────────────────────────
  function appendUser(text) {
    const el = document.createElement('div');
    el.className = 'msg user';
    el.innerHTML = '<div class="bubble">' + escHtml(text) + '</div>';
    messagesEl.appendChild(el);
    scrollBottom();
  }

  function appendAssistant(text, provider) {
    const msgEl = document.createElement('div');
    msgEl.className = 'msg assistant';
    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    const rendered = renderMarkdown(text);
    bubble.innerHTML = rendered.html;

    rendered.codeBlocks.forEach(function (cb, i) {
      const pre = bubble.querySelector('[data-cb="' + i + '"]');
      if (!pre) { return; }
      const actions = document.createElement('div');
      actions.className = 'code-actions';

      const copyBtn = makeBtn('Copy', function () {
        copyText(cb, copyBtn);
      });
      const ins = makeBtn('Insert', function () {
        vscode.postMessage({ type: 'insertAtCursor', code: cb });
      });
      const rep = makeBtn('Replace', function () {
        vscode.postMessage({ type: 'replaceSelection', code: cb });
      });
      actions.append(copyBtn, ins, rep);
      pre.after(actions);
    });

    if (provider) {
      const badge = document.createElement('span');
      badge.className = 'provider-badge';
      badge.textContent = provider;
      bubble.appendChild(badge);
    }

    msgEl.appendChild(bubble);
    messagesEl.appendChild(msgEl);
    scrollBottom();
  }

  // ── Live steps panel (Claude Code style) ───────────────────────────────────
  function beginSteps() {
    // Create a new steps container for this turn
    stepsEl = document.createElement('div');
    stepsEl.className = 'steps-panel active';
    messagesEl.appendChild(stepsEl);
    scrollBottom();
  }

  function upsertStep(id, text, status) {
    if (!stepsEl) { beginSteps(); }
    var existing = stepsEl.querySelector('[data-step-id="' + id + '"]');
    if (existing) {
      // Update existing step in place
      existing.className = 'step step-' + status;
      var iconEl = existing.querySelector('.step-icon');
      var textEl = existing.querySelector('.step-text');
      iconEl.innerHTML = stepIcon(status);
      if (text) { textEl.textContent = text; }
      return;
    }
    // Create new step row
    var row = document.createElement('div');
    row.className = 'step step-' + status;
    row.setAttribute('data-step-id', id);
    row.innerHTML =
      '<span class="step-icon">' + stepIcon(status) + '</span>' +
      '<span class="step-text">' + escHtml(text) + '</span>';
    stepsEl.appendChild(row);
    scrollBottom();
  }

  function endSteps() {
    if (!stepsEl) { return; }
    stepsEl.classList.remove('active');
    stepsEl.classList.add('done');
    stepsEl = null;
  }

  function stepIcon(status) {
    if (status === 'running') { return '<span class="spinner"></span>'; }
    if (status === 'done')    { return '✓'; }
    if (status === 'failed')  { return '✗'; }
    return '·';
  }

  function appendPreview(action, label, detail) {
    dismissPreview(); // remove any existing preview first

    const icons = { discord: '🟣', slack: '🟠', teams: '🔵', webhook: '⚡', gsheets: '📊', gdocs: '📄', telegram: '✈️', email: '📧', notion: '🗒️', github: '🐙', search: '🔍' };
    const icon = icons[action] || '⚡';

    previewEl = document.createElement('div');
    previewEl.className = 'msg preview-card-wrap';

    previewEl.innerHTML =
      '<div class="preview-card">' +
        '<div class="preview-header">' +
          '<span class="preview-icon">' + icon + '</span>' +
          '<span class="preview-label">' + escHtml(label) + '</span>' +
        '</div>' +
        '<div class="preview-detail">' + escHtml(detail) + '</div>' +
        '<div class="preview-actions">' +
          '<button class="preview-confirm">Run</button>' +
          '<button class="preview-cancel">Cancel</button>' +
        '</div>' +
      '</div>';

    previewEl.querySelector('.preview-confirm').addEventListener('click', function () {
      vscode.postMessage({ type: 'confirmAction' });
    });
    previewEl.querySelector('.preview-cancel').addEventListener('click', function () {
      vscode.postMessage({ type: 'cancelAction' });
    });

    messagesEl.appendChild(previewEl);
    scrollBottom();
  }

  function dismissPreview() {
    if (previewEl && previewEl.parentNode) {
      previewEl.parentNode.removeChild(previewEl);
    }
    previewEl = null;
  }

  function appendReceipt(receipt) {
    const el = document.createElement('div');
    el.className = 'msg receipt';

    const ch = receipt.channel ? ' #' + receipt.channel : '';
    const icon =
      receipt.action === 'discord_send' ? '🟣 Discord' + ch :
      receipt.action === 'slack_send'   ? '🟠 Slack' + ch   :
      receipt.action === 'teams_send'   ? '🔵 Teams' + ch   :
      receipt.action === 'webhook_send' ? '⚡ Webhook' + ch :
      receipt.action === 'gsheets_send' ? '📊 Sheet' + ch   :
      receipt.action === 'gdocs_send'   ? '📄 Doc' + ch     :
      receipt.action === 'telegram_send' ? '✈️ Telegram' + ch :
      receipt.action === 'resend_send'   ? '📧 Email' + ch    :
      receipt.action === 'notion_send'   ? '🗒️ Notion' + ch  :
      receipt.action === 'github_issue'  ? '🐙 GitHub' + ch + (receipt.issue_number ? ' #' + receipt.issue_number : '') :
      '✅ Action';
    const ts   = receipt.timestamp ? new Date(receipt.timestamp).toLocaleTimeString() : '';

    el.innerHTML =
      '<div class="receipt-card">' +
        '<div class="receipt-header">' +
          '<span class="receipt-icon">' + icon + '</span>' +
          '<span class="receipt-status">' + escHtml(receipt.status || 'delivered') + '</span>' +
          (ts ? '<span class="receipt-ts">' + escHtml(ts) + '</span>' : '') +
        '</div>' +
        (receipt.message
          ? '<div class="receipt-body">' + escHtml(receipt.message) + '</div>'
          : '') +
      '</div>';

    messagesEl.appendChild(el);
    scrollBottom();
  }

  function appendSearchResults(query, results, poweredBy) {
    const el = document.createElement('div');
    el.className = 'msg search-results';
    // Honest badge — never let users mistake AI knowledge for live web results
    let badge = '';
    if (poweredBy === 'ai') {
      badge = '<span class="search-badge search-badge-ai" title="Answered by your AI. Not live web results — subject to model training cutoff.">AI · not live</span>';
    } else if (poweredBy === 'duckduckgo') {
      badge = '<span class="search-badge search-badge-web">DuckDuckGo</span>';
    } else if (poweredBy === 'ddg+ai') {
      badge = '<span class="search-badge search-badge-web">DuckDuckGo</span><span class="search-badge search-badge-ai" title="AI-supplemented — mix of live and model knowledge.">+ AI</span>';
    }
    let html = '<div class="search-card"><div class="search-header">🔍 ' + escHtml(query) + badge + '</div><div class="search-list">';
    results.forEach(function (r) {
      html += '<div class="search-item">';
      if (r.title) { html += '<div class="search-title">' + escHtml(r.title) + '</div>'; }
      if (r.snippet) { html += '<div class="search-snippet">' + escHtml(r.snippet) + '</div>'; }
      if (r.url) { html += '<div class="search-url">' + escHtml(r.url) + '</div>'; }
      html += '</div>';
    });
    html += '</div></div>';
    el.innerHTML = html;
    messagesEl.appendChild(el);
    scrollBottom();
  }

  function appendError(text) {
    const el = document.createElement('div');
    el.className = 'msg error';
    el.innerHTML = '<div class="bubble">' + escHtml(text) + '</div>';
    messagesEl.appendChild(el);
    scrollBottom();
  }

  // ── Helpers ──────────────────────────────────────────────────────────────────
  function makeBtn(label, onClick) {
    const btn = document.createElement('button');
    btn.className = 'code-btn';
    btn.textContent = label;
    btn.addEventListener('click', onClick);
    return btn;
  }

  function copyText(text, btn) {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(function () {
        btn.textContent = 'Copied!';
        setTimeout(function () { btn.textContent = 'Copy'; }, 1500);
      }).catch(function () { fallbackCopy(text, btn); });
    } else {
      fallbackCopy(text, btn);
    }
  }

  function fallbackCopy(text, btn) {
    try {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.cssText = 'position:fixed;opacity:0';
      document.body.appendChild(ta); ta.select();
      document.execCommand('copy'); document.body.removeChild(ta);
      btn.textContent = 'Copied!';
      setTimeout(function () { btn.textContent = 'Copy'; }, 1500);
    } catch (_) {}
  }

  function scrollBottom() { messagesEl.scrollTop = messagesEl.scrollHeight; }

  // ── Markdown renderer ─────────────────────────────────────────────────────────
  function renderMarkdown(text) {
    const codeBlocks = [];
    let html = '';
    const lines = text.split('\n');
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (line.startsWith('```')) {
        const lang = line.slice(3).trim();
        const codeLines = [];
        i++;
        while (i < lines.length && !lines[i].startsWith('```')) { codeLines.push(lines[i]); i++; }
        const code = codeLines.join('\n');
        const idx = codeBlocks.length;
        codeBlocks.push(code);
        const langEl = lang ? '<span class="code-lang">' + escHtml(lang) + '</span>' : '';
        html += langEl + '<pre data-cb="' + idx + '"><code>' + escHtml(code) + '</code></pre>';
      } else if (line.startsWith('### ')) { html += '<p class="md-h3">' + inlineRender(line.slice(4)) + '</p>';
      } else if (line.startsWith('## '))  { html += '<p class="md-h2">' + inlineRender(line.slice(3)) + '</p>';
      } else if (line.startsWith('# '))   { html += '<p class="md-h1">' + inlineRender(line.slice(2)) + '</p>';
      } else if (line.startsWith('- ') || line.startsWith('* ')) { html += '<p class="md-li">' + inlineRender(line.slice(2)) + '</p>';
      } else if (/^\d+\. /.test(line))   { html += '<p class="md-li">' + inlineRender(line) + '</p>';
      } else if (line.trim() === '')      { html += '<div class="md-gap"></div>';
      } else                              { html += '<p>' + inlineRender(line) + '</p>'; }
      i++;
    }
    return { html, codeBlocks };
  }

  function inlineRender(text) {
    const parts = text.split(/(`[^`]+`)/g);
    return parts.map(function (part, idx) {
      if (idx % 2 === 1) { return '<code class="inline-code">' + escHtml(part.slice(1, -1)) + '</code>'; }
      let s = escHtml(part);
      s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
      s = s.replace(/\*([^*]+)\*/g, '<em>$1</em>');
      return s;
    }).join('');
  }

  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
})();
