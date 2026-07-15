import * as vscode from 'vscode';
import * as http from 'http';
import * as https from 'https';

export interface ChatMessage {
    role: 'user' | 'assistant' | 'system';
    content: string;
}

export interface ChatResponse {
    reply: string;
    provider?: string;
    hosted?: boolean;
    hosted_error?: number | string;
    configured?: boolean;
    error?: boolean;
}

export interface Receipt {
    action: string;
    message?: string;
    query?: string;
    results?: SearchResult[];
    timestamp?: string;
    status?: string;
}

export interface SearchResult {
    title: string;
    snippet: string;
    url: string;
}

function getBase(): string {
    return vscode.workspace.getConfiguration('railcall').get<string>('serverUrl', 'http://127.0.0.1:8799');
}

function request(method: 'GET' | 'POST', urlStr: string, body?: string, timeoutMs = 10_000): Promise<{ status: number; body: string }> {
    return new Promise((resolve, reject) => {
        const parsed = new URL(urlStr);
        const lib = parsed.protocol === 'https:' ? https : http;
        const bodyBuf = body ? Buffer.from(body, 'utf8') : undefined;
        let settled = false;

        const req = lib.request({
            hostname: parsed.hostname,
            port: parsed.port ? Number(parsed.port) : (parsed.protocol === 'https:' ? 443 : 80),
            path: parsed.pathname + parsed.search,
            method,
            headers: {
                ...(bodyBuf ? { 'Content-Type': 'application/json', 'Content-Length': bodyBuf.length } : {}),
            },
        }, (res) => {
            const chunks: Buffer[] = [];
            res.on('data', (c: Buffer) => chunks.push(c));
            res.on('end', () => {
                if (settled) { return; }
                settled = true;
                resolve({ status: res.statusCode ?? 0, body: Buffer.concat(chunks).toString('utf8') });
            });
            res.on('error', (e) => { if (!settled) { settled = true; reject(e); } });
        });

        req.on('error', (e) => { if (!settled) { settled = true; reject(e); } });
        req.setTimeout(timeoutMs, () => {
            if (!settled) { settled = true; req.destroy(new Error('Request timed out')); }
        });
        if (bodyBuf) { req.write(bodyBuf); }
        req.end();
    });
}

function parseJson<T>(raw: string): T {
    try { return JSON.parse(raw) as T; }
    catch { throw new Error(`Bad JSON from server: ${raw.slice(0, 100)}`); }
}

export async function sendChat(messages: ChatMessage[]): Promise<ChatResponse> {
    // 5 min matches server-side Ollama timeout — qwen:7b on Mac CPU can take 2-3 min for big contexts.
    const { status, body } = await request('POST', `${getBase()}/api/chat/local`, JSON.stringify({ messages }), 310_000);
    if (status < 200 || status >= 300) {
        throw new Error(`Server ${status}: ${body.slice(0, 200)}`);
    }
    return parseJson<ChatResponse>(body);
}

export async function checkServerHealth(): Promise<boolean> {
    try {
        const { status } = await request('GET', `${getBase()}/api/usage`, undefined, 3_000);
        return status >= 200 && status < 300;
    } catch { return false; }
}

export interface StationVersion {
    release_tag: string | null;
    built_at?: string;
    engine_commit?: string;
    core_commit?: string;
    note?: string;
}

export async function fetchStationVersion(): Promise<StationVersion | null> {
    try {
        const { status, body } = await request('GET', `${getBase()}/api/version`, undefined, 3_000);
        if (status < 200 || status >= 300) { return null; }
        return parseJson<StationVersion>(body);
    } catch { return null; }
}

export async function syncSettings(settings: {
    discord_webhook?: string;
    slack_webhook?: string;
    groq_key?: string;
    anthropic_key?: string;
    openai_key?: string;
}): Promise<{ ok: boolean; updated: string[] }> {
    const { body } = await request('POST', `${getBase()}/api/settings/sync`, JSON.stringify(settings), 5_000);
    return parseJson(body);
}

export async function sendToDiscord(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/discord/send`, JSON.stringify(payload), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToSlack(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/slack/send`, JSON.stringify(payload), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToTeams(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/teams/send`, JSON.stringify(payload), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToWebhook(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/webhook/send`, JSON.stringify(payload), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToGSheets(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/gsheets/send`, JSON.stringify(payload), 20_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToGDocs(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/gdocs/send`, JSON.stringify(payload), 20_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToTelegram(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/telegram/send`, JSON.stringify(payload), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToNotion(message: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/notion/send`, JSON.stringify(payload), 20_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function createGithubIssue(title: string, issueBody: string, channel?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { title, body: issueBody };
    if (channel) { payload.channel = channel; }
    const { status, body } = await request('POST', `${getBase()}/api/github/issue`, JSON.stringify(payload), 20_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function sendToResend(message: string, channel?: string, to?: string, subject?: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const payload: Record<string, string> = { message };
    if (channel) { payload.channel = channel; }
    if (to)      { payload.to      = to; }
    if (subject) { payload.subject = subject; }
    const { status, body } = await request('POST', `${getBase()}/api/resend/send`, JSON.stringify(payload), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export interface ChannelInfo {
    channels: string[];
    default: string | null;
    configured: boolean;
}

export async function fetchChannels(): Promise<Record<string, ChannelInfo>> {
    const { status, body } = await request('GET', `${getBase()}/api/channels`, undefined, 3_000);
    if (status < 200 || status >= 300) { return {}; }
    try { return parseJson<Record<string, ChannelInfo>>(body); }
    catch { return {}; }
}

// v1-§5 (soft): the live integration registry from the daemon. A new integration
// registered in the engine shows up in the extension's slash matching and
// classifier with zero extension edits. Old daemons (404) → [] and every
// hardcoded path behaves exactly as before.
export interface RegistryEntry {
    provider: string;
    verb: string;
    action_class: string;
    ready: boolean;
    slash: string;        // e.g. "/linear"
    icon: string;
    args: string[];
    keywords: string[];
    mcp_tool: string;
    note?: string;
}

export async function fetchRegistry(): Promise<RegistryEntry[]> {
    try {
        const { status, body } = await request('GET', `${getBase()}/api/registry`, undefined, 3_000);
        if (status < 200 || status >= 300) { return []; }
        const d = parseJson<{ ok?: boolean; integrations?: RegistryEntry[] }>(body);
        return d.ok && Array.isArray(d.integrations) ? d.integrations : [];
    } catch { return []; }
}

export async function webSearch(query: string): Promise<{ ok: boolean; results: SearchResult[]; powered_by?: string; error?: string }> {
    const { status, body } = await request('POST', `${getBase()}/api/web_search`, JSON.stringify({ query }), 30_000);
    const result = parseJson<{ ok: boolean; results: SearchResult[]; powered_by?: string; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}
