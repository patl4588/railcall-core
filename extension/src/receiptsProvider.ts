import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

interface ReceiptRecord {
    filePath: string;
    mtimeMs: number;
    provider: string;
    outcome: string;         // "success" | "refused" | "failed" | "…"
    mode: string;            // "dry" | "live" | ""
    approvedAt?: string;
    signed: boolean;
    schema?: string;
}

type Node = BucketNode | ReceiptNode;

class BucketNode extends vscode.TreeItem {
    kind = 'bucket' as const;
    constructor(label: string, public receipts: ReceiptRecord[]) {
        super(`${label} (${receipts.length})`, vscode.TreeItemCollapsibleState.Expanded);
        this.contextValue = 'railcall.bucket';
    }
}

class ReceiptNode extends vscode.TreeItem {
    kind = 'receipt' as const;
    constructor(public r: ReceiptRecord) {
        const time = new Date(r.mtimeMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
        const provider = r.provider.charAt(0).toUpperCase() + r.provider.slice(1);
        super(`${provider} · ${r.outcome} · ${time}`, vscode.TreeItemCollapsibleState.None);
        this.description = r.mode ? `(${r.mode})` : undefined;
        this.tooltip = [
            `Provider: ${r.provider}`,
            `Outcome:  ${r.outcome}`,
            `Mode:     ${r.mode || '—'}`,
            `Signed:   ${r.signed ? 'yes' : 'no'}`,
            r.approvedAt ? `Approved: ${r.approvedAt}` : '',
            `File:     ${r.filePath}`,
        ].filter(Boolean).join('\n');
        this.iconPath = new vscode.ThemeIcon(
            r.outcome === 'success' || r.outcome === 'approved' ? 'pass'
            : r.outcome === 'refused' || r.outcome === 'blocked' ? 'circle-slash'
            : r.outcome === 'failed' || r.outcome === 'error' ? 'error'
            : 'circle-outline'
        );
        this.command = {
            command: 'railcall.openReceipt',
            title: 'Open Receipt',
            arguments: [r.filePath],
        };
        this.contextValue = 'railcall.receipt';
    }
}

const MAX_RECEIPTS = 100;

export class RailCallReceiptsProvider implements vscode.TreeDataProvider<Node> {
    private _onDidChange = new vscode.EventEmitter<Node | undefined>();
    readonly onDidChangeTreeData = this._onDidChange.event;

    private _watchers: fs.FSWatcher[] = [];
    private _vscWatchers: vscode.FileSystemWatcher[] = [];
    private _pollTimer?: NodeJS.Timeout;
    private _debounce?: NodeJS.Timeout;
    private _cachedReceipts: ReceiptRecord[] = [];
    private _lastSignature = '';

    constructor() {
        this._rearmWatchers();
        this._startPolling();
        vscode.workspace.onDidChangeConfiguration(e => {
            if (e.affectsConfiguration('railcall.receiptsDir')) {
                this._rearmWatchers();
                this.refresh();
            }
        });
    }

    dispose() {
        this._watchers.forEach(w => { try { w.close(); } catch { /* ignore */ } });
        this._watchers = [];
        this._vscWatchers.forEach(w => { try { w.dispose(); } catch { /* ignore */ } });
        this._vscWatchers = [];
        if (this._pollTimer) { clearInterval(this._pollTimer); this._pollTimer = undefined; }
    }

    refresh() {
        this._cachedReceipts = loadAllReceipts();
        this._onDidChange.fire(undefined);
    }

    /** Number of receipts approved today — used by the status bar. */
    todayCount(): number {
        if (this._cachedReceipts.length === 0) { this._cachedReceipts = loadAllReceipts(); }
        const startOfDay = new Date(); startOfDay.setHours(0, 0, 0, 0);
        return this._cachedReceipts.filter(r => r.mtimeMs >= startOfDay.getTime()).length;
    }

    totalCount(): number {
        if (this._cachedReceipts.length === 0) { this._cachedReceipts = loadAllReceipts(); }
        return this._cachedReceipts.length;
    }

    getTreeItem(el: Node): vscode.TreeItem { return el; }

    getChildren(el?: Node): Node[] {
        if (el && el.kind === 'bucket') { return el.receipts.map(r => new ReceiptNode(r)); }
        if (el) { return []; }

        const receipts = this._cachedReceipts.length ? this._cachedReceipts : (this._cachedReceipts = loadAllReceipts());
        if (receipts.length === 0) {
            const empty = new vscode.TreeItem('No airlock receipts yet', vscode.TreeItemCollapsibleState.None);
            empty.description = 'run any governed RailCall action to see it here';
            empty.iconPath = new vscode.ThemeIcon('shield');
            return [empty as unknown as Node];
        }

        const now = new Date();
        const startOfToday = new Date(now); startOfToday.setHours(0, 0, 0, 0);
        const startOfYesterday = new Date(startOfToday); startOfYesterday.setDate(startOfYesterday.getDate() - 1);

        const today: ReceiptRecord[] = [];
        const yesterday: ReceiptRecord[] = [];
        const earlier: ReceiptRecord[] = [];
        for (const r of receipts) {
            if (r.mtimeMs >= startOfToday.getTime()) { today.push(r); }
            else if (r.mtimeMs >= startOfYesterday.getTime()) { yesterday.push(r); }
            else { earlier.push(r); }
        }
        const buckets: BucketNode[] = [];
        if (today.length)     { buckets.push(new BucketNode('Today', today)); }
        if (yesterday.length) { buckets.push(new BucketNode('Yesterday', yesterday)); }
        if (earlier.length)   { buckets.push(new BucketNode('Earlier', earlier)); }
        return buckets;
    }

    private _rearmWatchers() {
        // tear down existing watchers (both flavors) before re-arming
        this._watchers.forEach(w => { try { w.close(); } catch { /* ignore */ } });
        this._watchers = [];
        this._vscWatchers.forEach(w => { try { w.dispose(); } catch { /* ignore */ } });
        this._vscWatchers = [];

        for (const dir of receiptDirs()) {
            // VS Code's watcher is the primary — same code path Source Control uses.
            // It survives editor sleep/wake and works reliably across platforms.
            // RelativePattern with a file URI base watches arbitrary absolute paths.
            try {
                const pattern = new vscode.RelativePattern(vscode.Uri.file(dir), '*.json');
                const vw = vscode.workspace.createFileSystemWatcher(pattern);
                vw.onDidCreate(() => this._scheduleRefresh());
                vw.onDidChange(() => this._scheduleRefresh());
                vw.onDidDelete(() => this._scheduleRefresh());
                this._vscWatchers.push(vw);
            } catch { /* pattern rejected — fall through to fs.watch */ }

            // Legacy fs.watch as a belt-and-suspenders backup for cases where the
            // VS Code watcher never arms (e.g., directory created after activation).
            try {
                if (!fs.existsSync(dir)) { continue; }
                const w = fs.watch(dir, { persistent: false }, () => this._scheduleRefresh());
                w.on('error', () => { /* watch dropped; poll will re-read */ });
                this._watchers.push(w);
            } catch { /* ignore per-dir failures */ }
        }
    }

    private _startPolling() {
        // Insurance policy — if both watchers miss an event, this catches it
        // within 5s. Cheap: only re-reads if the directory signature changed.
        if (this._pollTimer) { clearInterval(this._pollTimer); }
        this._pollTimer = setInterval(() => this._pollTick(), 5_000);
    }

    private _pollTick() {
        const sig = dirSignature();
        if (sig === this._lastSignature) { return; }
        this._lastSignature = sig;
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

/** Ordered list of directories to scan, deduped, existing-only not enforced. */
function receiptDirs(): string[] {
    const cfg = vscode.workspace.getConfiguration('railcall').get<string>('receiptsDir', '').trim();
    const ws = process.env.RAILCALL_WS;
    const home = os.homedir();
    const candidates = [
        cfg && expandHome(cfg),
        ws && path.join(ws, 'receipts', 'capoff'),
        ws && path.join(ws, 'receipts'),
        path.join(home, '.railcall', 'workspace', 'receipts', 'capoff'),
        path.join(home, '.railcall', 'workspace', 'receipts'),
        path.join(home, '.railcall', 'receipts'),
        // Studio (installed station) writes receipts here — different WS than the airlock CLI.
        path.join(home, '.railcall', 'station', '.railcall_workspace', 'receipts', 'capoff'),
        path.join(home, '.railcall', 'station', '.railcall_workspace', 'receipts'),
    ].filter((x): x is string => Boolean(x));
    return Array.from(new Set(candidates));
}

function expandHome(p: string): string {
    return p.startsWith('~') ? path.join(os.homedir(), p.slice(1)) : p;
}

function loadAllReceipts(): ReceiptRecord[] {
    const seenBasenames = new Set<string>();
    const out: ReceiptRecord[] = [];
    for (const dir of receiptDirs()) {
        let names: string[];
        try { names = fs.readdirSync(dir); } catch { continue; }
        for (const name of names) {
            if (!name.endsWith('.json')) { continue; }
            if (seenBasenames.has(name)) { continue; }
            const full = path.join(dir, name);
            let st: fs.Stats;
            try { st = fs.statSync(full); } catch { continue; }
            if (!st.isFile()) { continue; }
            let parsed: Record<string, unknown> = {};
            try { parsed = JSON.parse(fs.readFileSync(full, 'utf8')); } catch { continue; }

            const provider = str(parsed.provider);
            const outcome  = str(parsed.outcome) || str(parsed.result_status);
            // The HUD only surfaces airlock-shaped receipts — records with a real
            // provider AND outcome. Legacy schemas (companion_*, railcall_audit_*)
            // are internal audit records users shouldn't have to interpret.
            if (!provider || !outcome) { continue; }

            seenBasenames.add(name);
            out.push({
                filePath: full,
                mtimeMs: st.mtimeMs,
                provider,
                outcome,
                mode: str(parsed.mode) || (parsed.dry_run === true ? 'dry' : parsed.dry_run === false ? 'live' : ''),
                approvedAt: str(parsed.approved_at) || str(parsed.timestamp) || undefined,
                signed: Boolean(parsed.signature),
                schema: str(parsed.schema) || undefined,
            });
        }
    }
    out.sort((a, b) => b.mtimeMs - a.mtimeMs);
    return out.slice(0, MAX_RECEIPTS);
}

function str(v: unknown): string {
    return typeof v === 'string' ? v : '';
}

/** Cheap fingerprint of every watched receipts dir: file count + newest mtime.
 *  Used by the polling fallback to skip work when nothing changed. */
function dirSignature(): string {
    const parts: string[] = [];
    for (const dir of receiptDirs()) {
        try {
            const names = fs.readdirSync(dir).filter(n => n.endsWith('.json'));
            let newest = 0;
            for (const n of names) {
                try { newest = Math.max(newest, fs.statSync(path.join(dir, n)).mtimeMs); } catch { /* ignore */ }
            }
            parts.push(`${dir}:${names.length}:${newest}`);
        } catch { /* dir missing — skip */ }
    }
    return parts.join('|');
}
