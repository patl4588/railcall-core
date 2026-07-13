import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { sendChat, checkServerHealth, sendToDiscord, webSearch, ChatMessage, Receipt } from './apiClient';
import { EditorContext, getEditorContext, getWorkspaceRoot, getWorkspaceTree, findAndReadFile, extractFileMentions } from './contextProvider';

// Fast path: unambiguous slash commands (no round-trip needed)
function detectSlashCommand(text: string): { intent: 'discord' | 'search'; content: string } | null {
    const t = text.trim();
    const d = t.match(/^\/discord\s+(.+)$/i);
    if (d) { return { intent: 'discord', content: d[1].trim() }; }
    const s = t.match(/^\/search\s+(.+)$/i);
    if (s) { return { intent: 'search', content: s[1].trim() }; }
    return null;
}

// Heuristic: is this message worth running through the AI classifier?
function mightBeIntent(text: string): boolean {
    return /\b(discord|slack|webhook|search|google|look\s?up|send|post|push|share|dispatch|deliver)\b/i.test(text);
}

// AI classifier system prompt — the AI acts as the "regex" but with real understanding
const CLASSIFIER_PROMPT = `You are an intent classifier for a VS Code coding assistant.

The assistant has these actions:
- discord_send: send a message to Discord (webhook is already configured)
- web_search: run a web search
- chat: regular coding chat / questions about code

Classify the user's message. Reply with ONLY a JSON object, no markdown, no prose:
{"intent": "discord_send" | "web_search" | "chat", "content": "string or null", "needs_composition": true | false}

- "content": for discord_send/web_search, what the user wants sent/searched (their words, verbatim). For chat, null.
- "needs_composition": true if content references files, workspace, analysis ("all bugs in X", "summary of Y", "folder structure"), false if it's a literal message ready to send.

Examples:
"hello world" → {"intent":"chat","content":null,"needs_composition":false}
"send hi team to discord" → {"intent":"discord_send","content":"hi team","needs_composition":false}
"send Unresolved Bugs Summary to discord" → {"intent":"discord_send","content":"Unresolved Bugs Summary","needs_composition":true}
"share the folder structure on discord" → {"intent":"discord_send","content":"folder structure","needs_composition":true}
"post it to discord" → {"intent":"discord_send","content":"the previous message","needs_composition":true}
"search for React 19 features" → {"intent":"web_search","content":"React 19 features","needs_composition":false}
"what's in package.json?" → {"intent":"chat","content":null,"needs_composition":false}
"fix the bug in this function" → {"intent":"chat","content":null,"needs_composition":false}`;

interface Classification {
    intent: 'discord_send' | 'web_search' | 'chat';
    content: string | null;
    needs_composition: boolean;
}

interface PendingAction {
    type: 'discord' | 'search';
    payload: string;
}

export class RailCallSidebarProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private _messages: ChatMessage[] = [];
    private _busy = false;
    private _pending: PendingAction | null = null;
    private readonly _extensionUri: vscode.Uri;

    constructor(extensionUri: vscode.Uri) {
        this._extensionUri = extensionUri;
    }

    resolveWebviewView(webviewView: vscode.WebviewView, _ctx: vscode.WebviewViewResolveContext, _token: vscode.CancellationToken) {
        this._view = webviewView;
        webviewView.webview.options = {
            enableScripts: true,
            localResourceRoots: [vscode.Uri.joinPath(this._extensionUri, 'media')],
        };
        webviewView.webview.html = this._getHtml(webviewView.webview);

        const editorListener = vscode.window.onDidChangeActiveTextEditor(() => this._updateCtxHint());
        webviewView.onDidDispose(() => { editorListener.dispose(); this._view = undefined; });
        setTimeout(() => this._updateCtxHint(), 300);

        webviewView.webview.onDidReceiveMessage(async (msg) => {
            switch (msg.type) {
                case 'userMessage':      await this._dispatch(msg.text); break;
                case 'confirmAction':    await this._confirmPending(); break;
                case 'cancelAction':     this._cancelPending(); break;
                case 'insertAtCursor':   await this._insertAtCursor(msg.code); break;
                case 'replaceSelection': await this._replaceSelection(msg.code); break;
                case 'clearHistory':     this._messages = []; this._pending = null; break;
                case 'checkServer':
                    const healthy = await checkServerHealth();
                    this._post({ type: 'serverStatus', healthy });
                    break;
            }
        });
    }

    sendUserMessage(prompt: string, ctx?: EditorContext) {
        if (!this._view) { return; }
        this._post({ type: 'injectUserMessage', text: prompt });
        this._dispatch(prompt, ctx);
    }

    private async _dispatch(text: string, ctx?: EditorContext) {
        if (this._busy) { return; }

        // ── FAST PATH: unambiguous slash commands ─────────────────────────
        const slash = detectSlashCommand(text);
        if (slash) {
            if (slash.intent === 'discord') {
                return this._routeDiscord(slash.content, /*needsCompose=*/false, ctx);
            }
            return this._routeSearch(slash.content);
        }

        // ── AI CLASSIFIER: for anything that might be an intent ────────────
        if (mightBeIntent(text)) {
            this._busy = true;
            this._stepsBegin();
            const classifyStep = this._stepStart('Understanding your request...');
            let classification: Classification | null = null;
            try {
                classification = await this._classifyIntent(text);
            } catch {
                // Classifier failed — fall through to chat
            }

            if (classification && classification.intent === 'discord_send') {
                this._stepDone(classifyStep, `Intent: send to Discord${classification.needs_composition ? ' (AI compose)' : ''}`);
                this._stepsEnd();
                this._busy = false;
                return this._routeDiscord(classification.content ?? text, classification.needs_composition, ctx);
            }
            if (classification && classification.intent === 'web_search') {
                this._stepDone(classifyStep, `Intent: web search`);
                this._stepsEnd();
                this._busy = false;
                return this._routeSearch(classification.content ?? text);
            }
            this._stepDone(classifyStep, 'Intent: regular chat');
            this._stepsEnd();
            this._busy = false;
        }

        // ── Default: AI chat ────────────────────────────────────────────────
        await this._handleChatMessage(text, ctx);
    }

    // Ask the AI to classify what the user wants (structured JSON output).
    private async _classifyIntent(text: string): Promise<Classification | null> {
        // Include recent conversation so pronouns like "post it" resolve correctly.
        const recent = this._messages.filter(m => m.role !== 'system').slice(-4);
        const history = recent.length
            ? '\n\nRecent conversation:\n' + recent.map(m => `${m.role.toUpperCase()}: ${m.content.slice(0, 300)}`).join('\n')
            : '';

        const result = await sendChat([
            { role: 'system', content: CLASSIFIER_PROMPT + history },
            { role: 'user', content: text },
        ]);

        const reply = (result.reply || '').trim();
        // The model sometimes wraps JSON in ``` fences — strip them
        const jsonMatch = reply.match(/\{[\s\S]*\}/);
        if (!jsonMatch) { return null; }
        try {
            const parsed = JSON.parse(jsonMatch[0]);
            if (parsed && typeof parsed.intent === 'string') {
                return parsed as Classification;
            }
        } catch { /* invalid JSON */ }
        return null;
    }

    // Route a Discord send — with or without AI composition
    private async _routeDiscord(rawContent: string, needsCompose: boolean, ctx?: EditorContext) {
        const editorCtx = ctx ?? getEditorContext();
        const workspaceRoot = getWorkspaceRoot();

        if (needsCompose) {
            this._busy = true;
            this._post({ type: 'thinking', value: true });
            try {
                const composed = await this._composeDiscordMessage(rawContent, workspaceRoot, editorCtx);
                this._pending = { type: 'discord', payload: composed };
                this._post({ type: 'preview', action: 'discord', label: 'Send to Discord', detail: composed });
            } catch (e: any) {
                this._post({ type: 'error', text: e.message });
            } finally {
                this._busy = false;
                this._post({ type: 'thinking', value: false });
            }
        } else {
            this._pending = { type: 'discord', payload: rawContent };
            this._post({ type: 'preview', action: 'discord', label: 'Send to Discord', detail: rawContent });
        }
    }

    private _routeSearch(query: string) {
        this._pending = { type: 'search', payload: query };
        this._post({ type: 'preview', action: 'search', label: 'Web search', detail: query });
    }

    private async _handleChatMessage(text: string, ctx?: EditorContext) {
        this._busy = true;
        this._stepsBegin();

        try {
            const editorCtx = ctx ?? getEditorContext();
            const workspaceRoot = getWorkspaceRoot();

            const parts: string[] = [
                'You are a coding assistant embedded in VS Code with full workspace access. ' +
                'Be concise. Use fenced code blocks for all code.\n\n' +
                'IMPORTANT: You cannot execute actions directly. The extension has its own action layer ' +
                '(Discord send, web search, workflow execution) that handles real execution via preview → confirm → receipt. ' +
                'NEVER claim you sent a Discord message, made an HTTP call, ran a workflow, or triggered any side effect. ' +
                'If the user wants to send something, tell them to say "send X to discord" and the extension will handle it. ' +
                'Do not fabricate receipts, delivery confirmations, or "✅ Sent" messages.',
            ];

            // Step: workspace context
            if (workspaceRoot) {
                const wsStep = this._stepStart(`Loading workspace: ${workspaceRoot.split('/').pop()}`);
                const tree = getWorkspaceTree(workspaceRoot);
                parts.push(`\nWorkspace: ${workspaceRoot}\nFile tree:\n${tree}`);
                this._stepDone(wsStep, `Workspace loaded: ${workspaceRoot.split('/').pop()}`);
            }

            // Step: active file
            if (editorCtx) {
                const fStep = this._stepStart(`Attaching active file: ${editorCtx.fileName}`);
                parts.push(`\nActive file: ${editorCtx.filePath} (${editorCtx.language}, ${editorCtx.totalLines} lines, cursor line ${editorCtx.cursorLine})`);
                if (editorCtx.selectedText) {
                    parts.push(`\nSelected text:\n\`\`\`${editorCtx.language}\n${editorCtx.selectedText}\n\`\`\``);
                    this._stepDone(fStep, `Attached selection from ${editorCtx.fileName}`);
                } else {
                    parts.push(`\nFile content:\n\`\`\`${editorCtx.language}\n${editorCtx.fileContent}\n\`\`\``);
                    this._stepDone(fStep, `Attached ${editorCtx.fileName} (${editorCtx.totalLines} lines)`);
                }
            }

            // Step: file mentions with success/failure feedback
            const mentions = extractFileMentions(text);
            const missing: string[] = [];
            for (const name of mentions) {
                const rStep = this._stepStart(`Reading ${name}`);
                const content = findAndReadFile(name, workspaceRoot);
                if (content !== null) {
                    parts.push(`\nContent of ${name}:\n\`\`\`\n${content}\n\`\`\``);
                    this._stepDone(rStep, `Read ${name} (${(content.length / 1024).toFixed(1)} KB)`);
                } else {
                    this._stepFail(rStep, `${name} not found`);
                    missing.push(name);
                }
            }
            if (missing.length > 0) {
                parts.push(`\n⚠️ CRITICAL: These files were NOT read: ${missing.join(', ')}. ` +
                           `You MUST tell the user the file could not be found. Do NOT invent, guess, or fabricate their contents. ` +
                           `Do NOT compute values based on data you don't have.`);
            }

            // Step: dispatch to model
            const aiStep = this._stepStart('Sending to AI...');
            this._post({ type: 'thinking', value: true });

            const systemMsg: ChatMessage = { role: 'system', content: parts.join('\n') };
            const history = this._messages.filter(m => m.role !== 'system');
            this._messages = [systemMsg, ...history, { role: 'user', content: text }];

            let result;
            try {
                result = await sendChat(this._messages);
            } catch (e: any) {
                const msg = e?.message ?? String(e);
                const isOffline = /ECONNREFUSED|connect/i.test(msg);
                const isTimeout = /timed? ?out|ETIMEDOUT/i.test(msg);
                this._stepFail(aiStep, isTimeout ? 'AI request timed out (120s)' : isOffline ? 'Studio server unreachable' : 'AI request failed');
                this._stepsEnd();
                this._post({
                    type: 'error',
                    text: isOffline
                        ? 'RailCall Studio is not running. Start it with: railcall studio'
                        : isTimeout
                            ? 'AI took too long to respond. Try a shorter message, or add a faster API key (Groq is quick).'
                            : msg,
                });
                return;
            }

            let reply = result.reply ?? 'No response.';
            // Detect fallback-to-hosted (means all user keys failed) via structured field OR message
            const isHostedError = !!result.hosted_error
                || (result.hosted && !result.provider)
                || /hosted engine.*failed|HTTP 4\d\d.*refunded|no provider (?:configured|available)|api key/i.test(reply);
            if (isHostedError) {
                this._stepFail(aiStep, 'No working API key');
                reply = '⚠️ No working API key configured.\n\n' +
                        'Open **RailCall settings** (`Cmd+,` → search "RailCall"), add a **Groq** key (free at console.groq.com) ' +
                        'or Anthropic key, then run **RailCall: Sync API Keys to Studio**.';
            } else {
                this._stepDone(aiStep, `Answered by ${result.provider ?? 'AI'}`);
            }

            this._stepsEnd();
            this._messages.push({ role: 'assistant', content: reply });
            this._post({ type: 'assistantMessage', text: reply, provider: isHostedError ? undefined : result.provider });
        } finally {
            this._busy = false;
            this._post({ type: 'thinking', value: false });
        }
    }

    private async _composeDiscordMessage(raw: string, workspaceRoot: string | null, editorCtx: EditorContext | null): Promise<string> {
        this._stepsBegin();
        try {
            const iStep = this._stepStart('Detected Discord send with AI composition');
            this._stepDone(iStep, 'Intent: Discord send + AI compose');

            const ctxParts: string[] = [
                'You compose concise, clear Discord messages based on the user\'s request and any provided file content. ' +
                'Return ONLY the final message text — no quotes, no prefix, no explanation, no markdown headers.',
            ];

            // Read mentioned files with per-file status
            const mentions = extractFileMentions(raw);
            const missing: string[] = [];
            let readAny = false;
            for (const name of mentions) {
                const rStep = this._stepStart(`Reading ${name}`);
                const content = findAndReadFile(name, workspaceRoot);
                if (content) {
                    ctxParts.push(`\nContent of ${name}:\n${content}`);
                    this._stepDone(rStep, `Read ${name} (${(content.length / 1024).toFixed(1)} KB)`);
                    readAny = true;
                } else {
                    this._stepFail(rStep, `${name} not found`);
                    missing.push(name);
                }
            }

            // If the user's request references files but ALL are missing, refuse to compose.
            // Otherwise the AI will hallucinate the file contents.
            if (mentions.length > 0 && !readAny) {
                this._stepsEnd();
                throw new Error(
                    `Cannot compose: the file(s) you mentioned were not found — ` +
                    missing.map(m => `\`${m}\``).join(', ') +
                    `. Check the path (paths with spaces need to be exact) or open the file in VS Code and I'll pick it up automatically.`
                );
            }
            // Tell the AI explicitly which files failed so it doesn't invent them
            if (missing.length > 0) {
                ctxParts.push(`\n⚠️ These files were NOT found and MUST NOT be referenced in your reply: ${missing.join(', ')}`);
            }

            // Workspace tree if referenced
            if (workspaceRoot && /folder|tree|struct|workspace|director/i.test(raw)) {
                const wStep = this._stepStart('Attaching workspace tree');
                ctxParts.push(`\nWorkspace tree:\n${getWorkspaceTree(workspaceRoot)}`);
                this._stepDone(wStep, 'Workspace tree attached');
            }

            // Active file if referenced
            if (editorCtx && /active.?file|current.?file|open.?file/i.test(raw)) {
                const fStep = this._stepStart(`Attaching ${editorCtx.fileName}`);
                ctxParts.push(`\nActive file (${editorCtx.fileName}):\n${editorCtx.fileContent.slice(0, 3000)}`);
                this._stepDone(fStep, `Attached ${editorCtx.fileName}`);
            }

            const cStep = this._stepStart('Asking AI to compose the message...');
            let result;
            try {
                result = await sendChat([
                    { role: 'system', content: ctxParts.join('\n') },
                    { role: 'user', content: `Compose a Discord message for: ${raw}` },
                ]);
            } catch (e: any) {
                const msg = e?.message ?? String(e);
                const isTimeout = /timed? ?out|ETIMEDOUT/i.test(msg);
                this._stepFail(cStep, isTimeout ? 'AI timed out' : 'AI request failed');
                this._stepsEnd();
                throw new Error(isTimeout
                    ? 'AI took too long. Try a shorter request, or add a faster provider (Groq).'
                    : msg);
            }

            if (!result.reply
                || result.hosted_error
                || (result.hosted && !result.provider)
                || /hosted engine.*failed|HTTP 4\d\d|refunded|no provider|api key/i.test(result.reply)) {
                this._stepFail(cStep, 'No working API key');
                this._stepsEnd();
                throw new Error(
                    'No working API key configured. Open RailCall settings (Cmd+, → search "RailCall"), ' +
                    'add a Groq key (free at console.groq.com) or Anthropic key, then run "RailCall: Sync API Keys to Studio".'
                );
            }

            this._stepDone(cStep, `Composed by ${result.provider ?? 'AI'}`);
            this._stepsEnd();
            return result.reply.trim();
        } catch (e) {
            this._stepsEnd();
            throw e;
        }
    }

    private async _confirmPending() {
        if (!this._pending || this._busy) { return; }
        const action = this._pending;
        this._pending = null;
        this._post({ type: 'previewDismiss' });
        this._busy = true;
        this._post({ type: 'thinking', value: true });
        try {
            if (action.type === 'discord') {
                const result = await sendToDiscord(action.payload);
                if (result.ok && result.receipt) {
                    this._post({ type: 'receipt', receipt: result.receipt });
                } else {
                    this._post({ type: 'error', text: result.error ?? 'Discord send failed' });
                }
            } else if (action.type === 'search') {
                const result = await webSearch(action.payload);
                if (result.ok && result.results.length > 0) {
                    this._post({ type: 'searchResults', query: action.payload, results: result.results });
                } else {
                    this._post({ type: 'assistantMessage', text: `No results found for "${action.payload}".`, provider: 'web' });
                }
            }
        } catch (e: any) {
            this._post({ type: 'error', text: e.message });
        } finally {
            this._busy = false;
            this._post({ type: 'thinking', value: false });
        }
    }

    private _cancelPending() {
        this._pending = null;
        this._post({ type: 'previewDismiss' });
        this._post({ type: 'assistantMessage', text: 'Action cancelled.', provider: undefined });
    }

    private async _insertAtCursor(code: string) {
        const editor = vscode.window.activeTextEditor;
        if (!editor) { vscode.window.showWarningMessage('No active editor.'); return; }
        await editor.edit(b => b.insert(editor.selection.active, code));
    }

    private async _replaceSelection(code: string) {
        const editor = vscode.window.activeTextEditor;
        if (!editor) { vscode.window.showWarningMessage('No active editor.'); return; }
        if (editor.selection.isEmpty) { vscode.window.showWarningMessage('No text selected.'); return; }
        await editor.edit(b => b.replace(editor.selection, code));
    }

    private _updateCtxHint() {
        const root = getWorkspaceRoot();
        const ctx = getEditorContext();
        const hint = ctx ? ctx.fileName : (root ? root.split('/').pop() ?? '' : '');
        this._post({ type: 'ctxHint', text: hint });
    }

    private _post(msg: object) { this._view?.webview.postMessage(msg); }

    // ── Live step tracking (Claude Code style) ─────────────────────────────
    private _stepCounter = 0;
    private _stepStart(text: string): string {
        const id = 'step-' + (++this._stepCounter);
        this._post({ type: 'step', id, text, status: 'running' });
        return id;
    }
    private _stepDone(id: string, text?: string) {
        this._post({ type: 'step', id, text, status: 'done' });
    }
    private _stepFail(id: string, text?: string) {
        this._post({ type: 'step', id, text, status: 'failed' });
    }
    private _stepsBegin() { this._post({ type: 'stepsBegin' }); }
    private _stepsEnd()   { this._post({ type: 'stepsEnd' }); }

    private _getHtml(webview: vscode.Webview): string {
        const nonce = crypto.randomBytes(16).toString('hex');
        const cssUri = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'sidebar.css'));
        const jsUri  = webview.asWebviewUri(vscode.Uri.joinPath(this._extensionUri, 'media', 'sidebar.js'));
        return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width,initial-scale=1"/>
  <meta http-equiv="Content-Security-Policy"
        content="default-src 'none'; style-src 'nonce-${nonce}' ${cssUri}; script-src 'nonce-${nonce}' ${jsUri}; img-src data:;"/>
  <link rel="stylesheet" href="${cssUri}" nonce="${nonce}"/>
</head>
<body>
  <div id="header">
    <span id="logo">◆ RAILCALL</span>
    <span id="server-dot" title="Checking…"></span>
    <button id="clear-btn" title="Clear conversation">↺</button>
  </div>
  <div id="messages" role="log" aria-live="polite">
    <div class="msg assistant"><div class="bubble">Ask about your code, search the web, or send to Discord. Right-click any selection for Explain / Fix / Refactor.</div></div>
  </div>
  <div id="thinking-bar" hidden>
    <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    <span class="thinking-label">thinking…</span>
  </div>
  <div id="input-area">
    <textarea id="input" placeholder="Ask… or /search query or send X to discord" rows="3"></textarea>
    <div id="input-row">
      <span id="ctx-hint"></span>
      <button id="send-btn">Send ↵</button>
    </div>
  </div>
  <script nonce="${nonce}" src="${jsUri}"></script>
</body>
</html>`;
    }
}
