import * as vscode from 'vscode';
import * as crypto from 'crypto';
import { sendChat, checkServerHealth, sendToDiscord, sendToSlack, sendToTeams, sendToWebhook, sendToGSheets, sendToGDocs, sendToTelegram, sendToResend, sendToNotion, createGithubIssue, webSearch, fetchChannels, fetchRegistry, ChatMessage, Receipt, ChannelInfo, RegistryEntry } from './apiClient';
import { EditorContext, getEditorContext, getWorkspaceRoot, getWorkspaceTree, findAndReadFile, extractFileMentions } from './contextProvider';

// Fast path: unambiguous slash commands (no round-trip needed)
type SendIntent = 'discord' | 'slack' | 'teams' | 'webhook' | 'gsheets' | 'gdocs' | 'telegram' | 'email' | 'notion' | 'github' | 'search';
function detectSlashCommand(text: string): { intent: SendIntent; content: string; channel?: string } | null {
    const t = text.trim();
    // Match /<target> <channel> <message>  where target is a messaging integration
    const withChannel = t.match(/^\/(discord|slack|teams|webhook|gsheets|gdocs|telegram|tg|email|resend|notion|github|gh)\s+([A-Za-z0-9_-]+)\s+(.+)$/i);
    if (withChannel) {
        const raw = withChannel[1].toLowerCase();
        const intent = (raw === 'tg' ? 'telegram' :
                        raw === 'resend' ? 'email' :
                        raw === 'gh' ? 'github' : raw) as SendIntent;
        return { intent, channel: withChannel[2], content: withChannel[3].trim() };
    }
    const d = t.match(/^\/discord\s+(.+)$/i);
    if (d) { return { intent: 'discord', content: d[1].trim() }; }
    const sl = t.match(/^\/slack\s+(.+)$/i);
    if (sl) { return { intent: 'slack', content: sl[1].trim() }; }
    const tm = t.match(/^\/teams\s+(.+)$/i);
    if (tm) { return { intent: 'teams', content: tm[1].trim() }; }
    const wh = t.match(/^\/webhook\s+(.+)$/i);
    if (wh) { return { intent: 'webhook', content: wh[1].trim() }; }
    const gs = t.match(/^\/gsheets?\s+(.+)$/i);
    if (gs) { return { intent: 'gsheets', content: gs[1].trim() }; }
    const gd = t.match(/^\/gdocs?\s+(.+)$/i);
    if (gd) { return { intent: 'gdocs', content: gd[1].trim() }; }
    const tg = t.match(/^\/(?:telegram|tg)\s+(.+)$/i);
    if (tg) { return { intent: 'telegram', content: tg[1].trim() }; }
    const em = t.match(/^\/(?:email|resend|mail)\s+(.+)$/i);
    if (em) { return { intent: 'email', content: em[1].trim() }; }
    const no = t.match(/^\/notion\s+(.+)$/i);
    if (no) { return { intent: 'notion', content: no[1].trim() }; }
    const gh = t.match(/^\/(?:github|gh)\s+(.+)$/i);
    if (gh) { return { intent: 'github', content: gh[1].trim() }; }
    const s = t.match(/^\/search\s+(.+)$/i);
    if (s) { return { intent: 'search', content: s[1].trim() }; }
    return null;
}

// Heuristic: is this message worth running through the AI classifier?
function mightBeIntent(text: string): boolean {
    return /\b(discord|slack|teams|msteams|webhook|zapier|make\.com|n8n|sheet|spreadsheet|gsheets|doc|gdocs|telegram|tg|email|mail|resend|inbox|notify|notion|github|gh|issue|bug|repo|repository|search|google|look\s?up|find|browse|check|verify|latest|news|is\s+\w+\s+(?:a|real|live)|(?:on|in|from|via)\s+(?:the\s+)?(?:web|internet|online)|send|post|push|share|dispatch|deliver|append|log|record|ping|write\s+to|add\s+to|file|open|create)\b/i.test(text);
}

// AI classifier system prompt — the AI acts as the "regex" but with real understanding
const CLASSIFIER_PROMPT = `You are an intent classifier for a VS Code coding assistant.

The assistant has these actions:
- discord_send: send a message to Discord
- slack_send: send a message to Slack
- teams_send: send a message to Microsoft Teams
- webhook_send: send to a generic outgoing webhook (Zapier, Make, n8n, custom endpoints)
- gsheets_send: append a row to a Google Sheet (via Apps Script webhook)
- gdocs_send: append a paragraph to a Google Doc (via Apps Script webhook)
- telegram_send: send a Telegram message via bot to a configured chat
- email_send: send an email via Resend (uses configured from-address / recipient)
- notion_send: append a paragraph to a Notion page
- github_issue: open (file, create) a GitHub issue on a configured repo — content should be the issue title or a short "title: description" phrase
- web_search: run a web search
- chat: regular coding chat / questions about code

Classify the user's message. Reply with ONLY a JSON object, no markdown, no prose:
{"intent": "discord_send" | "slack_send" | "teams_send" | "webhook_send" | "gsheets_send" | "gdocs_send" | "telegram_send" | "email_send" | "notion_send" | "github_issue" | "web_search" | "chat", "content": "string or null", "needs_composition": true | false, "channel": "string or null"}

- "content": for discord_send/slack_send/web_search, what the user wants sent/searched (their words, verbatim). For chat, null.
- "needs_composition": true if content references files, workspace, analysis ("all bugs in X", "summary of Y", "folder structure"), false if it's a literal message ready to send.
- "channel": for discord_send/slack_send, the channel name the user named (e.g. "deploys", "alerts"). Null if they did not name a channel. NEVER invent a channel name — only use one from the "Available channels" list if provided below.

CHANNEL EXTRACTION RULES:
- If the user says "in <name>", "to <name>", "on <name>", "via <name>", "into <name>", "in the <name> channel", "on the <name> channel", or "#<name>", and <name> matches one of the Available channels below, extract it as "channel" and REMOVE it from "content".
- If the message names a channel that exists in only ONE platform's list (e.g. only slack has "deploys"), pick that platform.
- If a channel name exists in BOTH platforms and the user did not name the platform explicitly, prefer the intent implied by keywords (discord/slack) or the most recent conversation context. If both platforms have "alerts" and no other hint, default to discord.
- NEVER invent a channel that's not in the Available list.
- If the user names a channel that's NOT in the Available list, still return channel with the name they used — the server will refuse and show the correct list.

Examples:
"hello world" → {"intent":"chat","content":null,"needs_composition":false,"channel":null}
"send hi team to discord" → {"intent":"discord_send","content":"hi team","needs_composition":false,"channel":null}
"send hello in alerts" (both have alerts) → {"intent":"discord_send","content":"hello","needs_composition":false,"channel":"alerts"}
"send hello to alerts" → {"intent":"discord_send","content":"hello","needs_composition":false,"channel":"alerts"}
"send welcome to default on discord" → {"intent":"discord_send","content":"welcome","needs_composition":false,"channel":"default"}
"post deploy done in slack #deploys" → {"intent":"slack_send","content":"deploy done","needs_composition":false,"channel":"deploys"}
"share the file tree in discord alerts" → {"intent":"discord_send","content":"file tree","needs_composition":true,"channel":"alerts"}
"send the folder tree to the alerts channel on slack" → {"intent":"slack_send","content":"folder tree","needs_composition":true,"channel":"alerts"}
"send Unresolved Bugs Summary to discord" → {"intent":"discord_send","content":"Unresolved Bugs Summary","needs_composition":true,"channel":null}
"post it to discord" → {"intent":"discord_send","content":"the previous message","needs_composition":true,"channel":null}
"ping the team on slack" → {"intent":"slack_send","content":"team ping","needs_composition":false,"channel":null}
"send hello to teams" → {"intent":"teams_send","content":"hello","needs_composition":false,"channel":null}
"post deploy done in teams dev" → {"intent":"teams_send","content":"deploy done","needs_composition":false,"channel":"dev"}
"fire the zapier webhook" → {"intent":"webhook_send","content":"trigger","needs_composition":false,"channel":null}
"send this to my n8n workflow" → {"intent":"webhook_send","content":"payload","needs_composition":true,"channel":null}
"push it to make.com" → {"intent":"webhook_send","content":"the previous message","needs_composition":true,"channel":null}
"send status to webhook prod" → {"intent":"webhook_send","content":"status","needs_composition":false,"channel":"prod"}
"log this to my sheet" → {"intent":"gsheets_send","content":"the previous message","needs_composition":true,"channel":null}
"append 'deploy done' to gsheets" → {"intent":"gsheets_send","content":"deploy done","needs_composition":false,"channel":null}
"log the workspace tree to sheet metrics" → {"intent":"gsheets_send","content":"workspace tree","needs_composition":true,"channel":"metrics"}
"add this to the standup doc" → {"intent":"gdocs_send","content":"the previous message","needs_composition":true,"channel":"standup"}
"append 'reviewed the PR' to my journal doc" → {"intent":"gdocs_send","content":"reviewed the PR","needs_composition":false,"channel":"journal"}
"send hello to telegram" → {"intent":"telegram_send","content":"hello","needs_composition":false,"channel":null}
"ping the team on telegram" → {"intent":"telegram_send","content":"team ping","needs_composition":false,"channel":"team"}
"send deploy status via telegram alerts" → {"intent":"telegram_send","content":"deploy status","needs_composition":true,"channel":"alerts"}
"tg family: dinner in 30" → {"intent":"telegram_send","content":"dinner in 30","needs_composition":false,"channel":"family"}
"email me the deploy summary" → {"intent":"email_send","content":"deploy summary","needs_composition":true,"channel":null}
"send X by email" → {"intent":"email_send","content":"X","needs_composition":false,"channel":null}
"mail the invoice to sami via alerts" → {"intent":"email_send","content":"invoice","needs_composition":true,"channel":"alerts"}
"resend onboarding: welcome to the team" → {"intent":"email_send","content":"welcome to the team","needs_composition":false,"channel":"onboarding"}
"notify me by email about this" → {"intent":"email_send","content":"the previous message","needs_composition":true,"channel":null}
"append this to my standup page in notion" → {"intent":"notion_send","content":"the previous message","needs_composition":true,"channel":"standup"}
"log deploy done to notion" → {"intent":"notion_send","content":"deploy done","needs_composition":false,"channel":null}
"add this to notion journal" → {"intent":"notion_send","content":"the previous message","needs_composition":true,"channel":"journal"}
"write the bug summary to notion" → {"intent":"notion_send","content":"bug summary","needs_composition":true,"channel":null}
"file an issue on github: crash on login page" → {"intent":"github_issue","content":"crash on login page","needs_composition":false,"channel":null}
"open a github issue about the memory leak in worker.ts" → {"intent":"github_issue","content":"memory leak in worker.ts","needs_composition":true,"channel":null}
"create a bug on the core repo: sidebar dot never turns green" → {"intent":"github_issue","content":"sidebar dot never turns green","needs_composition":false,"channel":"core"}
"gh new issue in frontend: dropdown flickers on hover" → {"intent":"github_issue","content":"dropdown flickers on hover","needs_composition":false,"channel":"frontend"}
"file a bug for this stack trace on github" → {"intent":"github_issue","content":"the previous message","needs_composition":true,"channel":null}
"search for React 19 features" → {"intent":"web_search","content":"React 19 features","needs_composition":false,"channel":null}
"find sami.benchaalia.com in the web" → {"intent":"web_search","content":"sami.benchaalia.com","needs_composition":false,"channel":null}
"can you find X on the web" → {"intent":"web_search","content":"X","needs_composition":false,"channel":null}
"look up how React 19 handles suspense" → {"intent":"web_search","content":"how React 19 handles suspense","needs_composition":false,"channel":null}
"google claude api pricing" → {"intent":"web_search","content":"claude api pricing","needs_composition":false,"channel":null}
"is XYZ.com a real domain" → {"intent":"web_search","content":"XYZ.com","needs_composition":false,"channel":null}
"what's the latest on GPT-5" → {"intent":"web_search","content":"latest GPT-5 news","needs_composition":false,"channel":null}
"check if 'example.com' exists online" → {"intent":"web_search","content":"example.com","needs_composition":false,"channel":null}
"search the web for X" → {"intent":"web_search","content":"X","needs_composition":false,"channel":null}
"find me info about X online" → {"intent":"web_search","content":"X","needs_composition":false,"channel":null}
"what's in package.json?" → {"intent":"chat","content":null,"needs_composition":false,"channel":null}`;

interface Classification {
    intent: 'discord_send' | 'slack_send' | 'teams_send' | 'webhook_send' | 'gsheets_send' | 'gdocs_send' | 'telegram_send' | 'email_send' | 'notion_send' | 'github_issue' | 'web_search' | 'registry_send' | 'chat';
    content: string | null;
    needs_composition: boolean;
    channel?: string | null;
    // v1-§5: set when intent === 'registry_send' — a provider from the live
    // registry that has no native extension send path (yet)
    provider?: string | null;
}

interface PendingAction {
    type: 'discord' | 'slack' | 'teams' | 'webhook' | 'gsheets' | 'gdocs' | 'telegram' | 'email' | 'notion' | 'github' | 'search';
    payload: string;         // for messaging: the message text; for github: the issue body
    title?: string;          // github only: issue title
    channel?: string;
}

export class RailCallSidebarProvider implements vscode.WebviewViewProvider {
    private _view?: vscode.WebviewView;
    private _messages: ChatMessage[] = [];
    private _busy = false;
    private _pending: PendingAction | null = null;
    private _channelCache: Record<string, ChannelInfo> = {};
    // v1-§5: live integration registry from the daemon (same 60s poll as
    // channels). Empty against an old daemon — every hardcoded path unchanged.
    private _registryCache: RegistryEntry[] = [];
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
        // Cache available Slack/Discord channels so the classifier can pick smartly
        this._refreshChannels();
        setInterval(() => this._refreshChannels(), 60_000);

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
            if (slash.intent === 'discord') { return this._routeSend('discord', slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'slack')   { return this._routeSend('slack',   slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'teams')   { return this._routeSend('teams',   slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'webhook') { return this._routeSend('webhook', slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'gsheets') { return this._routeSend('gsheets', slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'gdocs')   { return this._routeSend('gdocs',   slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'telegram'){ return this._routeSend('telegram', slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'email')   { return this._routeSend('email',    slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'notion')  { return this._routeSend('notion',   slash.content, false, ctx, slash.channel); }
            if (slash.intent === 'github')  { return this._routeGithub(slash.content, false, ctx, slash.channel); }
            return this._routeSearch(slash.content);
        }

        // ── v1-§5: dynamic slash matching from the LIVE registry ──────────
        // A slash the hardcoded matcher doesn't know (e.g. /linear, /sms,
        // /charge) resolves against the daemon's registry catalog.
        const dyn = text.trim().match(/^\/([a-z0-9_-]+)\s*(.*)$/i);
        if (dyn) {
            const tokn = dyn[1].toLowerCase();
            const entry = this._registryExtras().find(
                e => e.provider === tokn || (e.slash || '').replace(/^\//, '') === tokn);
            if (entry) { return this._routeRegistryInfo(entry, dyn[2] || ''); }
        }

        // ── AI CLASSIFIER: for anything that might be an intent ────────────
        if (mightBeIntent(text) || this._registryKeywordHit(text)) {
            this._busy = true;
            this._stepsBegin();
            const classifyStep = this._stepStart('Understanding your request...');
            let classification: Classification | null = null;
            try {
                classification = await this._classifyIntent(text);
            } catch {
                // Classifier failed — fall through to chat
            }

            const intentPlatformMap: Record<string, 'discord' | 'slack' | 'teams' | 'webhook' | 'gsheets' | 'gdocs' | 'telegram' | 'email' | 'notion'> = {
                discord_send: 'discord', slack_send: 'slack',
                teams_send: 'teams',     webhook_send: 'webhook',
                gsheets_send: 'gsheets', gdocs_send: 'gdocs',
                telegram_send: 'telegram', email_send: 'email',
                notion_send: 'notion',
            };
            const platform = classification ? intentPlatformMap[classification.intent] : undefined;
            if (classification && platform) {
                let msgContent = classification.content ?? text;
                let channel = classification.channel ?? null;
                if (!channel) {
                    const extracted = this._extractChannelFromContent(msgContent, platform);
                    if (extracted.channel) { msgContent = extracted.content; channel = extracted.channel; }
                }
                const chLabel = channel ? ` #${channel}` : '';
                const platformLabel = platform === 'teams' ? 'Teams' :
                                      platform === 'webhook' ? 'webhook' :
                                      platform.charAt(0).toUpperCase() + platform.slice(1);
                this._stepDone(classifyStep, `Intent: send to ${platformLabel}${chLabel}${classification.needs_composition ? ' (AI compose)' : ''}`);
                this._stepsEnd();
                this._busy = false;
                return this._routeSend(platform, msgContent, classification.needs_composition, ctx, channel ?? undefined);
            }
            if (classification && classification.intent === 'github_issue') {
                let content = classification.content ?? text;
                let channel = classification.channel ?? null;
                if (!channel) {
                    const extracted = this._extractChannelFromContent(content, 'github');
                    if (extracted.channel) { content = extracted.content; channel = extracted.channel; }
                }
                const chLabel = channel ? ` #${channel}` : '';
                this._stepDone(classifyStep, `Intent: GitHub issue${chLabel}${classification.needs_composition ? ' (AI compose)' : ''}`);
                this._stepsEnd();
                this._busy = false;
                return this._routeGithub(content, classification.needs_composition, ctx, channel ?? undefined);
            }
            if (classification && classification.intent === 'web_search') {
                this._stepDone(classifyStep, `Intent: web search`);
                this._stepsEnd();
                this._busy = false;
                return this._routeSearch(classification.content ?? text);
            }
            // v1-§5: the classifier recognized a registry-only provider
            if (classification && classification.intent === 'registry_send' && classification.provider) {
                const entry = this._registryExtras().find(e => e.provider === classification!.provider);
                this._stepDone(classifyStep, `Intent: ${classification.provider} (registry)`);
                this._stepsEnd();
                this._busy = false;
                if (entry) { return this._routeRegistryInfo(entry, classification.content ?? ''); }
            }
            this._stepDone(classifyStep, 'Intent: regular chat');
            this._stepsEnd();
            this._busy = false;
        }

        // ── Default: AI chat ────────────────────────────────────────────────
        await this._handleChatMessage(text, ctx);
    }

    private async _refreshChannels() {
        try {
            this._channelCache = await fetchChannels();
        } catch { /* studio may not be running yet */ }
        try {
            this._registryCache = await fetchRegistry();
        } catch { /* old daemon (no /api/registry) — hardcoded paths still work */ }
    }

    // Registry entries with NO native extension send path — the hardcoded
    // platforms keep their fast path; these get the honest registry route.
    private _registryExtras(): RegistryEntry[] {
        const native = new Set(['discord', 'slack', 'teams', 'webhook', 'gsheets', 'gdocs', 'telegram', 'email', 'resend', 'notion', 'github']);
        return this._registryCache.filter(e => e.ready && !native.has(e.provider));
    }

    private _registryKeywordHit(text: string): RegistryEntry | null {
        const t = text.toLowerCase();
        for (const e of this._registryExtras()) {
            if (t.includes(e.provider)) { return e; }
        }
        for (const e of this._registryExtras()) {
            if ((e.keywords || []).some(k => t.includes(k))) { return e; }
        }
        return null;
    }

    // Honest handling for a registry-only provider: the extension does NOT fake
    // a send it has no path for. It shows what the provider is, the exact args,
    // and the three surfaces where the governed send runs TODAY. When the
    // station exposes /api/integration/* to the extension, this becomes a real
    // stage→approve flow with no changes anywhere else.
    private _routeRegistryInfo(entry: RegistryEntry, rest: string) {
        const args = (entry.args || []).map(a => `${a}=…`).join(' ');
        const lines = [
            `**${entry.icon} ${entry.provider}** · ${entry.verb} · \`${entry.action_class}\``,
            '',
            `This integration is live in your RailCall registry, and every send runs the governed airlock (dry-run plan → policy gate → your approval → signed receipt). It runs from:`,
            '',
            `- **Studio composer** — type \`${entry.slash} ${args}\``,
            `- **Terminal** — \`railcall send ${entry.provider} ${args}\``,
            `- **MCP** (Claude Desktop / VS Code MCP) — tools \`${entry.mcp_tool}_plan\` / \`${entry.mcp_tool}_apply\``,
            '',
            `Native sidebar sends for ${entry.provider} arrive when the station exposes the registry airlock to this extension.`,
        ];
        if (rest && rest.trim()) {
            lines.push('', `Your draft is preserved: \`${rest.trim().slice(0, 200)}\``);
        }
        this._post({ type: 'assistantMessage', text: lines.join('\n'), provider: undefined });
    }

    // Post-classifier safety net: if the classifier missed the channel but the
    // content still contains a trailing "in/to/on <known_channel>" phrase,
    // extract it here so the AI never has to be perfect.
    private _extractChannelFromContent(content: string, platform: 'discord' | 'slack' | 'teams' | 'webhook' | 'gsheets' | 'gdocs' | 'telegram' | 'email' | 'notion' | 'github'): { content: string; channel: string | null } {
        const cacheKey = platform === 'teams' ? 'msteams' : platform === 'email' ? 'resend' : platform;
        const known = this._channelCache[cacheKey]?.channels ?? [];
        if (!content || known.length === 0) { return { content, channel: null }; }
        // Sort longer names first so "deploys-prod" beats "deploys"
        const sorted = [...known].sort((a, b) => b.length - a.length);
        for (const ch of sorted) {
            const esc = ch.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            const patterns = [
                new RegExp(`\\s+(?:in|to|on|via|into|through)\\s+the\\s+${esc}(?:\\s+channel)?\\s*$`, 'i'),
                new RegExp(`\\s+(?:in|to|on|via|into|through)\\s+#?${esc}\\s*$`, 'i'),
                new RegExp(`\\s+#${esc}\\s*$`, 'i'),
            ];
            for (const p of patterns) {
                if (p.test(content)) {
                    return { content: content.replace(p, '').trim(), channel: ch };
                }
            }
        }
        return { content, channel: null };
    }

    // Ask the AI to classify what the user wants (structured JSON output).
    private async _classifyIntent(text: string): Promise<Classification | null> {
        // Include recent conversation so pronouns like "post it" resolve correctly.
        const recent = this._messages.filter(m => m.role !== 'system').slice(-4);
        const history = recent.length
            ? '\n\nRecent conversation:\n' + recent.map(m => `${m.role.toUpperCase()}: ${m.content.slice(0, 300)}`).join('\n')
            : '';

        // Inject available channels so the classifier can extract them from user phrasing
        let channelCtx = '';
        for (const [iid, info] of Object.entries(this._channelCache)) {
            if (info.configured) {
                channelCtx += `\n\nAvailable ${iid} channels: ${info.channels.join(', ')}`;
                if (info.default) { channelCtx += ` (default: ${info.default})`; }
            }
        }
        // v1-§5: dynamic classifier context from the LIVE registry — providers
        // beyond the hardcoded list classify as registry_send with a provider
        // name, so new engine integrations are recognized with zero edits here.
        let registryCtx = '';
        const extras = this._registryExtras();
        if (extras.length) {
            registryCtx = '\n\nAdditional registered platforms (classify these as {"intent":"registry_send","provider":"<name>"} with the same content/needs_composition rules):\n'
                + extras.map(e => `- ${e.provider}: ${e.verb} (keywords: ${(e.keywords || []).join(', ')})`).join('\n');
        }
        const promptWithCtx = CLASSIFIER_PROMPT + registryCtx + channelCtx + history;

        const result = await sendChat([
            { role: 'system', content: promptWithCtx },
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

    private _channelLabel(kind: string, channel?: string): string {
        // Look up cache under the same key the /api/channels endpoint uses.
        // teams → msteams, email → resend (both stored under their platform id).
        const cacheKey = kind === 'teams' ? 'msteams' : kind === 'email' ? 'resend' : kind;
        const info = this._channelCache[cacheKey];
        const resolved = channel ?? info?.default ?? undefined;
        return resolved ? ` #${resolved}` : '';
    }

    private _platformDisplay(kind: 'discord' | 'slack' | 'teams' | 'webhook' | 'gsheets' | 'gdocs' | 'telegram' | 'email' | 'notion' | 'github'): string {
        return kind === 'teams' ? 'Teams' :
               kind === 'webhook' ? 'webhook' :
               kind === 'gsheets' ? 'Google Sheets' :
               kind === 'gdocs' ? 'Google Docs' :
               kind === 'telegram' ? 'Telegram' :
               kind === 'email' ? 'Email' :
               kind === 'notion' ? 'Notion' :
               kind === 'github' ? 'GitHub' :
               kind.charAt(0).toUpperCase() + kind.slice(1);
    }

    // Generic send router — used by all messaging integrations.
    // Preserves the compose → preview → confirm → receipt flow.
    private async _routeSend(
        kind: 'discord' | 'slack' | 'teams' | 'webhook' | 'gsheets' | 'gdocs' | 'telegram' | 'email' | 'notion',
        rawContent: string,
        needsCompose: boolean,
        ctx?: EditorContext,
        channel?: string,
    ) {
        const editorCtx = ctx ?? getEditorContext();
        const workspaceRoot = getWorkspaceRoot();
        const label = `Send to ${this._platformDisplay(kind)}${this._channelLabel(kind, channel)}`;

        if (needsCompose) {
            this._busy = true;
            this._post({ type: 'thinking', value: true });
            try {
                const composed = await this._composeDiscordMessage(rawContent, workspaceRoot, editorCtx);
                this._pending = { type: kind, payload: composed, channel };
                this._post({ type: 'preview', action: kind, label, detail: composed });
            } catch (e: any) {
                this._post({ type: 'error', text: e.message });
            } finally {
                this._busy = false;
                this._post({ type: 'thinking', value: false });
            }
        } else {
            this._pending = { type: kind, payload: rawContent, channel };
            this._post({ type: 'preview', action: kind, label, detail: rawContent });
        }
    }

    private _routeSearch(query: string) {
        this._pending = { type: 'search', payload: query };
        this._post({ type: 'preview', action: 'search', label: 'Web search', detail: query });
    }

    // GitHub is title-based. If needsCompose, ask the AI to draft a title + body
    // (returned as "TITLE\n---\nBODY") from the user's request and any file context.
    // If not, use the raw content as the title with an empty body (users can slash and
    // pass a rich body via /github <repo> <title> --- <body> if they include the ---).
    private async _routeGithub(rawContent: string, needsCompose: boolean, ctx?: EditorContext, channel?: string) {
        const editorCtx = ctx ?? getEditorContext();
        const workspaceRoot = getWorkspaceRoot();
        const repoLabel = channel ? ` #${channel}` : this._channelLabel('github');
        const label = `File GitHub issue${repoLabel}`;

        const splitTitleBody = (raw: string): { title: string; body: string } => {
            const idx = raw.indexOf('\n---\n');
            if (idx > 0) {
                return { title: raw.slice(0, idx).trim(), body: raw.slice(idx + 5).trim() };
            }
            const nl = raw.indexOf('\n');
            if (nl > 0) {
                return { title: raw.slice(0, nl).trim(), body: raw.slice(nl + 1).trim() };
            }
            return { title: raw.trim(), body: '' };
        };

        if (needsCompose) {
            this._busy = true;
            this._post({ type: 'thinking', value: true });
            try {
                const composed = await this._composeGithubIssue(rawContent, workspaceRoot, editorCtx);
                const { title, body } = splitTitleBody(composed);
                this._pending = { type: 'github', payload: body, title, channel };
                const detail = title + (body ? '\n\n' + body : '');
                this._post({ type: 'preview', action: 'github', label, detail });
            } catch (e: any) {
                this._post({ type: 'error', text: e.message });
            } finally {
                this._busy = false;
                this._post({ type: 'thinking', value: false });
            }
        } else {
            const { title, body } = splitTitleBody(rawContent);
            this._pending = { type: 'github', payload: body, title, channel };
            const detail = title + (body ? '\n\n' + body : '');
            this._post({ type: 'preview', action: 'github', label, detail });
        }
    }

    private async _composeGithubIssue(raw: string, workspaceRoot: string | null, editorCtx: EditorContext | null): Promise<string> {
        this._stepsBegin();
        try {
            const iStep = this._stepStart('Detected GitHub issue with AI composition');
            this._stepDone(iStep, 'Intent: GitHub issue + AI compose');

            const ctxParts: string[] = [
                'You draft high-signal GitHub issues. Given the user\'s request and any workspace context, ' +
                'produce a short, imperative title and a clear body with reproduction steps and expected/actual behavior when relevant. ' +
                'Return ONLY this exact format (no markdown fences, no prose before/after):\n' +
                '<one-line title>\n---\n<multi-line body>',
            ];

            const mentions = extractFileMentions(raw);
            for (const name of mentions) {
                const rStep = this._stepStart(`Reading ${name}`);
                const content = findAndReadFile(name, workspaceRoot);
                if (content) {
                    ctxParts.push(`\nContent of ${name}:\n${content}`);
                    this._stepDone(rStep, `Read ${name} (${(content.length / 1024).toFixed(1)} KB)`);
                } else {
                    this._stepFail(rStep, `${name} not found`);
                }
            }
            if (editorCtx && /active.?file|current.?file|open.?file|selection/i.test(raw)) {
                ctxParts.push(`\nActive file (${editorCtx.fileName}):\n${editorCtx.fileContent.slice(0, 3000)}`);
            }

            const cStep = this._stepStart('Asking AI to draft the issue...');
            let result;
            try {
                result = await sendChat([
                    { role: 'system', content: ctxParts.join('\n') },
                    { role: 'user', content: `Draft a GitHub issue for: ${raw}` },
                ]);
            } catch (e: any) {
                const msg = e?.message ?? String(e);
                this._stepFail(cStep, /timed? ?out/i.test(msg) ? 'AI timed out' : 'AI request failed');
                this._stepsEnd();
                throw new Error(msg);
            }
            if (!result.reply) {
                this._stepFail(cStep, 'No reply');
                this._stepsEnd();
                throw new Error('AI returned no reply.');
            }
            this._stepDone(cStep, `Drafted by ${result.provider ?? 'AI'}`);
            this._stepsEnd();
            return result.reply.trim();
        } catch (e) {
            this._stepsEnd();
            throw e;
        }
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
                'IMPORTANT: You cannot execute actions yourself, but the extension around you CAN. ' +
                'The extension exposes: Discord/Slack/Teams/Telegram send, generic webhook, Google Sheets/Docs append, Notion append, GitHub issue creation, and real web search (DuckDuckGo + AI). ' +
                'The extension routes messaging + search intents automatically — the user does NOT need to say slash-commands. ' +
                'When the user asks you to do any of these, do NOT refuse or explain that you cannot. ' +
                'Instead, tell them to rephrase so the extension will pick it up. Examples:\n' +
                '  - "search for X" or "look up X" or "find X on the web" → extension runs a web search\n' +
                '  - "send X to discord/slack/teams/telegram" → extension shows a preview + sends\n' +
                '  - "append X to gsheets/gdocs" → extension appends via Apps Script\n' +
                'NEVER claim you sent a message, made an HTTP call, ran a workflow, or performed a web search yourself. ' +
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
            if (action.type === 'discord' || action.type === 'slack' || action.type === 'teams' ||
                action.type === 'webhook' || action.type === 'gsheets' || action.type === 'gdocs' ||
                action.type === 'telegram' || action.type === 'email' || action.type === 'notion') {
                const sender =
                    action.type === 'discord'  ? sendToDiscord :
                    action.type === 'slack'    ? sendToSlack :
                    action.type === 'teams'    ? sendToTeams :
                    action.type === 'webhook'  ? sendToWebhook :
                    action.type === 'gsheets'  ? sendToGSheets :
                    action.type === 'gdocs'    ? sendToGDocs :
                    action.type === 'telegram' ? sendToTelegram :
                    action.type === 'email'    ? sendToResend :
                                                 sendToNotion;
                const result = await sender(action.payload, action.channel);
                if (result.ok && result.receipt) {
                    this._post({ type: 'receipt', receipt: result.receipt });
                } else {
                    this._post({ type: 'error', text: result.error ?? `${action.type} send failed` });
                }
            } else if (action.type === 'github') {
                const title = action.title ?? action.payload;
                const body  = action.title ? action.payload : '';
                const result = await createGithubIssue(title, body, action.channel);
                if (result.ok && result.receipt) {
                    this._post({ type: 'receipt', receipt: result.receipt });
                } else {
                    this._post({ type: 'error', text: result.error ?? 'GitHub issue failed' });
                }
            } else if (action.type === 'search') {
                const result = await webSearch(action.payload);
                if (result.ok && result.results.length > 0) {
                    this._post({ type: 'searchResults', query: action.payload, results: result.results, poweredBy: result.powered_by });
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
    <textarea id="input" placeholder="Ask… or /discord /slack /teams /tg /email /notion /github /webhook /gsheets /gdocs /search" rows="3"></textarea>
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
