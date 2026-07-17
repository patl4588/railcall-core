import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

export interface StagingRecord {
    filePath: string;
    stagingId: string;      // "stg_abcd…"
    provider: string;       // "slack" | "discord" | …
    verb: string;           // "message_post" | …
    actionClass: string;    // "reversible" | "irreversible" | ""
    createdAt?: string;
    policyDecision: string; // "require_human" | "auto_approve" | …
    mtimeMs: number;
    ws: string;             // workspace this staging lives under
}

/** A dynamically-composed workflow staged over MCP (workflow_mcp.stage_workflow),
 *  awaiting a human's blast-radius approval. Lives in <ws>/wf_mcp_staged/. */
export interface WorkflowStagingRecord {
    filePath: string;
    consentToken: string;   // "wfc_…"
    workflowId: string;
    title?: string;
    nodeCount: number;
    systemsTouched: string[];
    irreversible: string[];
    egressDomains: string[];
    spendCents: number;
    policyWorst: string;    // "auto_approve" | "require_human" | "block"
    createdAt?: string;
    mtimeMs: number;
    ws: string;
}

type Node = StagingNode | WorkflowStagingNode | vscode.TreeItem;

class StagingNode extends vscode.TreeItem {
    kind = 'staging' as const;
    constructor(public s: StagingRecord) {
        const time = new Date(s.mtimeMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const provider = s.provider.charAt(0).toUpperCase() + s.provider.slice(1);
        const verb = s.verb || '(unknown verb)';
        super(`${provider} · ${verb} · ${time}`, vscode.TreeItemCollapsibleState.None);
        this.description = s.actionClass ? `(${s.actionClass})` : undefined;
        this.tooltip = [
            `Provider:   ${s.provider}`,
            `Verb:       ${s.verb}`,
            `Class:      ${s.actionClass || '—'}`,
            `Policy:     ${s.policyDecision}`,
            s.createdAt ? `Created:    ${s.createdAt}` : '',
            `Staging id: ${s.stagingId}`,
            `File:       ${s.filePath}`,
        ].filter(Boolean).join('\n');
        this.iconPath = new vscode.ThemeIcon('watch');  // waiting-for-human vibe
        this.command = {
            command: 'railcall.openStaging',
            title: 'Open Staging',
            arguments: [s.filePath],
        };
        this.contextValue = 'railcall.staging';
    }
}

class WorkflowStagingNode extends vscode.TreeItem {
    kind = 'workflow' as const;
    constructor(public w: WorkflowStagingRecord) {
        const time = new Date(w.mtimeMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const label = w.title || w.workflowId;
        super(`⚙ ${label} · ${w.nodeCount} nodes · ${time}`, vscode.TreeItemCollapsibleState.None);
        // The blast radius is the whole point — surface the sharpest fact inline.
        const irr = w.irreversible.length;
        this.description = irr > 0
            ? `⚠ ${irr} irreversible`
            : (w.systemsTouched.length ? w.systemsTouched.join(', ') : 'no external effects');
        this.tooltip = new vscode.MarkdownString([
            `**Dynamic workflow** — ${label}`,
            '',
            `- **Nodes:** ${w.nodeCount}`,
            `- **Systems touched:** ${w.systemsTouched.join(', ') || '—'}`,
            `- **Irreversible actions:** ${irr > 0 ? w.irreversible.map(s => '`' + s + '`').join(', ') : 'none'}`,
            `- **Egress hosts:** ${w.egressDomains.join(', ') || '—'}`,
            `- **Spend:** ${w.spendCents > 0 ? '$' + (w.spendCents / 100).toFixed(2) : '$0.00'}`,
            `- **Policy floor:** ${w.policyWorst}`,
            `- **Consent token:** ${w.consentToken}`,
            '',
            `Use the ▶ button to approve this blast radius and run the workflow.`,
        ].join('\n'));
        this.iconPath = new vscode.ThemeIcon(
            irr > 0 ? 'warning' : 'run-all',
            irr > 0 ? new vscode.ThemeColor('list.warningForeground') : undefined,
        );
        this.command = {
            command: 'railcall.openStaging',
            title: 'Open Workflow Staging',
            arguments: [w.filePath],
        };
        this.contextValue = 'railcall.workflowStaging';
    }
}

const MAX_STAGINGS = 100;

export class RailCallStagingsProvider implements vscode.TreeDataProvider<Node> {
    private _onDidChange = new vscode.EventEmitter<Node | undefined>();
    readonly onDidChangeTreeData = this._onDidChange.event;

    private _vscWatchers: vscode.FileSystemWatcher[] = [];
    private _fsWatchers: fs.FSWatcher[] = [];
    private _pollTimer?: NodeJS.Timeout;
    private _debounce?: NodeJS.Timeout;
    private _cache: StagingRecord[] = [];
    private _wfCache: WorkflowStagingRecord[] = [];
    private _lastSignature = '';

    constructor() {
        this._rearmWatchers();
        this._startPolling();
    }

    dispose() {
        this._vscWatchers.forEach(w => { try { w.dispose(); } catch { /* ignore */ } });
        this._vscWatchers = [];
        this._fsWatchers.forEach(w => { try { w.close(); } catch { /* ignore */ } });
        this._fsWatchers = [];
        if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = undefined; }
    }

    refresh() {
        this._cache = loadAllStagings();
        this._wfCache = loadAllWorkflowStagings();
        this._onDidChange.fire(undefined);
    }

    pendingCount(): number {
        if (this._cache.length === 0) { this._cache = loadAllStagings(); }
        if (this._wfCache.length === 0) { this._wfCache = loadAllWorkflowStagings(); }
        return this._cache.length + this._wfCache.length;
    }

    getTreeItem(el: Node): vscode.TreeItem { return el; }

    getChildren(el?: Node): Node[] {
        if (el) { return []; }
        const stagings = this._cache.length ? this._cache : (this._cache = loadAllStagings());
        const workflows = this._wfCache.length ? this._wfCache : (this._wfCache = loadAllWorkflowStagings());
        if (stagings.length === 0 && workflows.length === 0) {
            const empty = new vscode.TreeItem('No pending approvals', vscode.TreeItemCollapsibleState.None);
            empty.description = 'staged actions awaiting a human will appear here';
            empty.iconPath = new vscode.ThemeIcon('check-all');
            return [empty];
        }
        // Workflows first — they're the bigger decision (a whole blast radius).
        return [
            ...workflows.map(w => new WorkflowStagingNode(w)),
            ...stagings.map(s => new StagingNode(s)),
        ];
    }

    private _rearmWatchers() {
        this._vscWatchers.forEach(w => { try { w.dispose(); } catch { /* ignore */ } });
        this._vscWatchers = [];
        this._fsWatchers.forEach(w => { try { w.close(); } catch { /* ignore */ } });
        this._fsWatchers = [];

        for (const dir of watchDirs()) {
            const glob = dir.endsWith('wf_mcp_staged') ? 'wfc_*.json' : 'stg_*.json';
            try {
                const pattern = new vscode.RelativePattern(vscode.Uri.file(dir), glob);
                const vw = vscode.workspace.createFileSystemWatcher(pattern);
                vw.onDidCreate(() => this._scheduleRefresh());
                vw.onDidChange(() => this._scheduleRefresh());
                vw.onDidDelete(() => this._scheduleRefresh());
                this._vscWatchers.push(vw);
            } catch { /* pattern rejected — fall through */ }

            try {
                if (!fs.existsSync(dir)) { continue; }
                const w = fs.watch(dir, { persistent: false }, () => this._scheduleRefresh());
                w.on('error', () => { /* dropped; poll will re-read */ });
                this._fsWatchers.push(w);
            } catch { /* per-dir failure — skip */ }
        }
    }

    private _startPolling() {
        // Fallback poll: covers dirs that appear after activation and platforms
        // where fs.watch misses events. Cheap — only re-reads on signature drift.
        if (this._pollTimer) { clearInterval(this._pollTimer); }
        this._pollTimer = setInterval(() => this._pollTick(), 5_000);
    }

    private _pollTick() {
        const sig = dirSignature();
        if (sig === this._lastSignature) { return; }
        this._lastSignature = sig;
        // Directory list may have grown (new provider staged its first delta) —
        // re-arm the watchers so subsequent events flow through the fast path.
        this._rearmWatchers();
        this.refresh();
    }

    private _scheduleRefresh() {
        if (this._debounce) { clearTimeout(this._debounce); }
        this._debounce = setTimeout(() => {
            this._lastSignature = dirSignature();
            this.refresh();
        }, 250);
    }
}

/** Ordered list of workspace roots the station may be using. */
function workspaceRoots(): string[] {
    const ws = process.env.RAILCALL_WS;
    const home = os.homedir();
    const candidates = [
        ws,
        path.join(home, '.railcall', 'workspace'),
        path.join(home, '.railcall', 'station', '.railcall_workspace'),
    ].filter((x): x is string => Boolean(x));
    return Array.from(new Set(candidates));
}

/** Every `<ws>/<provider>_staging` directory that exists right now. Discovery is
 *  by suffix so a new provider (added engine-side) shows up with zero extension
 *  edits — same principle as the receipts-dir scan. */
function stagingDirs(): string[] {
    const out: string[] = [];
    for (const ws of workspaceRoots()) {
        let entries: string[];
        try { entries = fs.readdirSync(ws); } catch { continue; }
        for (const name of entries) {
            if (!name.endsWith('_staging')) { continue; }
            const full = path.join(ws, name);
            try {
                if (fs.statSync(full).isDirectory()) { out.push(full); }
            } catch { /* ignore */ }
        }
    }
    return out;
}

/** Staging dirs to watch: every `*_staging` dir plus the dynamic-workflow
 *  `wf_mcp_staged` dir. */
function watchDirs(): string[] {
    const out = stagingDirs();
    for (const ws of workspaceRoots()) {
        const wfDir = path.join(ws, 'wf_mcp_staged');
        try {
            if (fs.statSync(wfDir).isDirectory()) { out.push(wfDir); }
        } catch { /* not present yet */ }
    }
    return out;
}

function loadAllStagings(): StagingRecord[] {
    const seen = new Set<string>();
    const out: StagingRecord[] = [];
    for (const ws of workspaceRoots()) {
        let entries: string[];
        try { entries = fs.readdirSync(ws); } catch { continue; }
        for (const dirName of entries) {
            if (!dirName.endsWith('_staging')) { continue; }
            const dir = path.join(ws, dirName);
            let names: string[];
            try { names = fs.readdirSync(dir); } catch { continue; }
            for (const name of names) {
                if (!name.startsWith('stg_') || !name.endsWith('.json')) { continue; }
                const key = dirName + '/' + name;
                if (seen.has(key)) { continue; }
                const full = path.join(dir, name);
                let st: fs.Stats;
                try { st = fs.statSync(full); } catch { continue; }
                if (!st.isFile()) { continue; }
                let raw: unknown;
                try { raw = JSON.parse(fs.readFileSync(full, 'utf8')); } catch { continue; }
                // literal null / array / non-object would throw on property access
                if (!raw || typeof raw !== 'object' || Array.isArray(raw)) { continue; }
                const parsed = raw as Record<string, unknown>;
                const provider = str(parsed.provider);
                const stagingId = str(parsed.staging_id);
                if (!provider || !stagingId) { continue; }
                seen.add(key);
                out.push({
                    filePath: full,
                    stagingId,
                    provider,
                    verb: str(parsed.verb),
                    actionClass: str(parsed.action_class),
                    createdAt: str(parsed.created) || undefined,
                    policyDecision: str((parsed.policy as any)?.decision) || 'require_human',
                    mtimeMs: st.mtimeMs,
                    ws,
                });
            }
        }
    }
    out.sort((a, b) => b.mtimeMs - a.mtimeMs);
    return out.slice(0, MAX_STAGINGS);
}

/** Dynamic workflows staged over MCP: <ws>/wf_mcp_staged/wfc_*.json. */
function loadAllWorkflowStagings(): WorkflowStagingRecord[] {
    const out: WorkflowStagingRecord[] = [];
    const seen = new Set<string>();   // dedupe across aliased workspace roots
    for (const ws of workspaceRoots()) {
        const dir = path.join(ws, 'wf_mcp_staged');
        let names: string[];
        try { names = fs.readdirSync(dir); } catch { continue; }
        for (const name of names) {
            if (!name.startsWith('wfc_') || !name.endsWith('.json')) { continue; }
            const full = path.join(dir, name);
            let st: fs.Stats;
            try { st = fs.statSync(full); } catch { continue; }
            if (!st.isFile()) { continue; }
            let parsed: unknown;
            try { parsed = JSON.parse(fs.readFileSync(full, 'utf8')); } catch { continue; }
            // A body of literal `null`, an array, or a non-object must be skipped —
            // property access on it would throw and freeze the whole tree.
            if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) { continue; }
            const p = parsed as Record<string, unknown>;
            const token = str(p.consent_token);
            if (token && seen.has(token)) { continue; }
            const wf = (p.workflow as Record<string, unknown>) || {};
            const blast = ((p.plan as Record<string, unknown>)?.blast_radius as Record<string, unknown>) || {};
            const wfId = str(wf.id);
            if (!token || !wfId) { continue; }
            seen.add(token);
            out.push({
                filePath: full,
                consentToken: token,
                workflowId: wfId,
                title: str(wf.title) || undefined,
                nodeCount: Array.isArray(wf.nodes) ? wf.nodes.length : 0,
                systemsTouched: strArr(blast.systems_touched),
                irreversible: strArr(blast.irreversible),
                egressDomains: strArr(blast.egress_domains),
                spendCents: typeof blast.spend_cents === 'number' ? blast.spend_cents : 0,
                policyWorst: str(blast.requires) || 'require_human',
                createdAt: str(p.created) || undefined,
                mtimeMs: st.mtimeMs,
                ws,
            });
        }
    }
    out.sort((a, b) => b.mtimeMs - a.mtimeMs);
    return out.slice(0, MAX_STAGINGS);
}

function str(v: unknown): string {
    return typeof v === 'string' ? v : '';
}

function strArr(v: unknown): string[] {
    return Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : [];
}

/** Fingerprint of every staging dir: file count + newest mtime — same pattern
 *  the receipts provider uses to skip idle poll ticks. */
function dirSignature(): string {
    const parts: string[] = [];
    for (const dir of watchDirs()) {
        const prefix = dir.endsWith('wf_mcp_staged') ? 'wfc_' : 'stg_';
        try {
            const names = fs.readdirSync(dir).filter(n => n.startsWith(prefix) && n.endsWith('.json'));
            let newest = 0;
            for (const n of names) {
                try { newest = Math.max(newest, fs.statSync(path.join(dir, n)).mtimeMs); } catch { /* ignore */ }
            }
            parts.push(`${dir}:${names.length}:${newest}`);
        } catch { /* dir missing — skip */ }
    }
    return parts.join('|');
}

/** Read the per-startup session token the station persists at `<ws>/session_token`
 *  (0600). Same trust model as the CLI's `railcall send`: same-user file read =
 *  same trust domain as the user who launched the daemon. */
export function readSessionToken(): string | null {
    for (const ws of workspaceRoots()) {
        const p = path.join(ws, 'session_token');
        try {
            const tok = fs.readFileSync(p, 'utf8').trim();
            if (tok) { return tok; }
        } catch { /* missing — try next candidate */ }
    }
    return null;
}
