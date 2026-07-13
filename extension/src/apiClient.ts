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

export async function sendToDiscord(message: string): Promise<{ ok: boolean; receipt?: Receipt; error?: string }> {
    const { status, body } = await request('POST', `${getBase()}/api/discord/send`, JSON.stringify({ message }), 15_000);
    const result = parseJson<{ ok: boolean; receipt?: Receipt; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}

export async function webSearch(query: string): Promise<{ ok: boolean; results: SearchResult[]; error?: string }> {
    const { status, body } = await request('POST', `${getBase()}/api/web_search`, JSON.stringify({ query }), 15_000);
    const result = parseJson<{ ok: boolean; results: SearchResult[]; error?: string }>(body);
    if (status >= 400) { throw new Error(result.error ?? `Server ${status}`); }
    return result;
}
