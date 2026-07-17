import * as vscode from 'vscode';
import { RailCallSidebarProvider } from './sidebarProvider';
import { RailCallReceiptsProvider } from './receiptsProvider';
import { RailCallStagingsProvider, readSessionToken, StagingRecord, WorkflowStagingRecord } from './stagingsProvider';
import { getEditorContext } from './contextProvider';
import { syncSettings, fetchStationVersion, approveStaging, applyWorkflow } from './apiClient';

// Station tag this extension build was validated against. Update when we cut a new
// station release. Mismatch with the running station triggers a warning banner.
const EXPECTED_STATION_TAG = 'station-v0.13';

interface StagingItemLike { s?: StagingRecord }
interface WorkflowItemLike { w?: WorkflowStagingRecord }

async function doSyncKeys(silent = false) {
    const cfg = vscode.workspace.getConfiguration('railcall');
    const settings = {
        discord_webhook: cfg.get<string>('discordWebhookUrl', ''),
        slack_webhook:   cfg.get<string>('slackWebhookUrl', ''),
        groq_key:        cfg.get<string>('groqApiKey', ''),
        anthropic_key:   cfg.get<string>('anthropicApiKey', ''),
        openai_key:      cfg.get<string>('openaiApiKey', ''),
    };
    // Only sync if at least one value is set
    const hasValues = Object.values(settings).some(v => v && v.length > 0);
    if (!hasValues) { return; }
    try {
        const result = await syncSettings(settings);
        if (!silent && result.updated.length > 0) {
            vscode.window.showInformationMessage(`RailCall: synced ${result.updated.join(', ')} to Studio.`);
        }
    } catch (e: any) {
        if (!silent) { vscode.window.showWarningMessage(`RailCall: could not sync keys — ${e.message}`); }
    }
}

export function activate(context: vscode.ExtensionContext) {
    const provider = new RailCallSidebarProvider(context.extensionUri);

    context.subscriptions.push(
        vscode.window.registerWebviewViewProvider('railcall.sidebar', provider, {
            webviewOptions: { retainContextWhenHidden: true },
        })
    );

    const receiptsProvider = new RailCallReceiptsProvider();
    const stagingsProvider = new RailCallStagingsProvider();
    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('railcall.receipts', receiptsProvider),
        vscode.window.registerTreeDataProvider('railcall.stagings', stagingsProvider),
        { dispose: () => receiptsProvider.dispose() },
        { dispose: () => stagingsProvider.dispose() },
        vscode.commands.registerCommand('railcall.refreshReceipts', () => receiptsProvider.refresh()),
        vscode.commands.registerCommand('railcall.refreshStagings', () => stagingsProvider.refresh()),
        vscode.commands.registerCommand('railcall.openReceipt', async (filePath: string) => {
            if (!filePath) { return; }
            try {
                const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
                await vscode.window.showTextDocument(doc, { preview: true });
            } catch (e: any) {
                vscode.window.showWarningMessage(`RailCall: could not open receipt — ${e.message}`);
            }
        }),
        vscode.commands.registerCommand('railcall.openStaging', async (filePath: string) => {
            if (!filePath) { return; }
            try {
                // Code patches stage with a unified diff for the approver — render it
                // as a real diff document instead of raw staging JSON. Anything without
                // a diff_preview falls back to the JSON file.
                const raw = JSON.parse(require('fs').readFileSync(filePath, 'utf8'));
                const diff: string | undefined = raw?.plan?.diff_preview;
                if (diff && typeof diff === 'string' && diff.length > 0) {
                    const header =
                        `# RailCall staged ${raw.provider} · ${raw.verb} — ${raw.staging_id}\n` +
                        `# reason: ${raw.plan?.reason ?? ''}\n` +
                        `# policy: ${raw.policy?.decision ?? '?'} · files: ${raw.plan?.file_count ?? '?'}\n` +
                        `# Approve with the ✓ button in the RailCall Pending Approvals tree.\n\n`;
                    const doc = await vscode.workspace.openTextDocument({
                        content: header + diff, language: 'diff',
                    });
                    await vscode.window.showTextDocument(doc, { preview: true });
                    return;
                }
                const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
                await vscode.window.showTextDocument(doc, { preview: true });
            } catch (e: any) {
                vscode.window.showWarningMessage(`RailCall: could not open staging — ${e.message}`);
            }
        }),
        vscode.commands.registerCommand('railcall.approveStaging', async (arg: StagingItemLike | undefined) => {
            const s = arg?.s;
            if (!s) {
                vscode.window.showWarningMessage('RailCall: use the ✓ button next to a pending approval.');
                return;
            }
            const tok = readSessionToken();
            if (!tok) {
                vscode.window.showWarningMessage(
                    'RailCall: cannot approve — station is not running or session_token is not on disk. Start the station and retry.',
                );
                return;
            }
            // Confirm before firing the live send — the receipt stamps this decision
            // as approval_channel="vscode_chat", so the human clicking here is
            // named in the signed audit trail. Better to double-click than surprise.
            const confirm = await vscode.window.showWarningMessage(
                `Approve ${s.provider} · ${s.verb}? This fires the staged action.`,
                { modal: true },
                'Approve',
            );
            if (confirm !== 'Approve') { return; }
            try {
                const res = await approveStaging(s.provider, s.stagingId, tok, 'vscode_chat');
                if (!res.ok) {
                    vscode.window.showErrorMessage(`RailCall approve failed: ${res.error ?? 'unknown error'}`);
                } else {
                    vscode.window.showInformationMessage(
                        `RailCall: ${s.provider} · ${s.verb} → ${res.outcome ?? 'approved'}`,
                    );
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`RailCall approve failed: ${e.message}`);
            } finally {
                // Regardless of outcome, refresh both trees — staging file is gone,
                // a receipt should have appeared (or the error left both intact).
                stagingsProvider.refresh();
                receiptsProvider.refresh();
            }
        }),
        vscode.commands.registerCommand('railcall.approveWorkflow', async (arg: WorkflowItemLike | undefined) => {
            const w = arg?.w;
            if (!w) {
                vscode.window.showWarningMessage('RailCall: use the ▶ button next to a staged workflow.');
                return;
            }
            const tok = readSessionToken();
            if (!tok) {
                vscode.window.showWarningMessage(
                    'RailCall: cannot run — station is not running or session_token is not on disk.',
                );
                return;
            }
            // The blast radius IS the decision — spell it out in the modal so the
            // human approves the aggregate consequence, not just a name.
            const irr = w.irreversible.length;
            const detail = [
                `${w.nodeCount} nodes · systems: ${w.systemsTouched.join(', ') || 'none'}`,
                irr > 0 ? `⚠ ${irr} IRREVERSIBLE: ${w.irreversible.join(', ')}` : 'no irreversible actions',
                w.egressDomains.length ? `egress: ${w.egressDomains.join(', ')}` : '',
                w.spendCents > 0 ? `spend: $${(w.spendCents / 100).toFixed(2)}` : 'no spend',
            ].filter(Boolean).join('\n');
            const confirm = await vscode.window.showWarningMessage(
                `Run workflow "${w.title || w.workflowId}"? This approves its whole blast radius.`,
                { modal: true, detail },
                'Approve & Run',
            );
            if (confirm !== 'Approve & Run') { return; }
            try {
                const res = await applyWorkflow(w.consentToken, tok, 'vscode_chat');
                if (res.timedOut) {
                    // The one-time token may already be consumed server-side — do NOT
                    // imply nothing ran, and warn against a blind re-approve.
                    vscode.window.showWarningMessage(
                        'RailCall: the workflow request timed out, but it may still be running on the station. ' +
                        'Check the Receipts view before re-approving — the consent token is single-use.',
                    );
                } else if (!res.ok) {
                    vscode.window.showErrorMessage(`RailCall workflow failed: ${res.error ?? 'unknown error'}`);
                } else {
                    // The mode is load-bearing honesty: a "mock" run fired NO external
                    // effects even though the human approved the blast radius.
                    const mode = res.mode ?? 'mock';
                    const modeNote = mode === 'live'
                        ? ' (live — external effects fired)'
                        : ' (mock — no external effects; set RAILCALL_MCP_ALLOW_LIVE=1 on the station to run live)';
                    const msg = `RailCall: workflow "${res.workflow_id ?? w.workflowId}" → ${res.outcome ?? 'done'}${modeNote}`;
                    if (res.signed === false) {
                        vscode.window.showWarningMessage(msg + ' — ⚠ receipt is UNSIGNED and will not verify offline.');
                    } else if (mode === 'live') {
                        vscode.window.showInformationMessage(msg);
                    } else {
                        vscode.window.showWarningMessage(msg);
                    }
                }
            } catch (e: any) {
                vscode.window.showErrorMessage(`RailCall workflow failed: ${e.message}`);
            } finally {
                stagingsProvider.refresh();
                receiptsProvider.refresh();
            }
        }),
    );

    const stationStatus = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 100);
    stationStatus.text = 'RailCall';
    stationStatus.tooltip = 'RailCall station: checking…';
    stationStatus.command = 'railcall.focus';
    stationStatus.show();
    context.subscriptions.push(stationStatus);

    const refreshStatusBar = (versionLabel: string | null, warn: boolean) => {
        const running = versionLabel ?? 'checking…';
        const pending = stagingsProvider.pendingCount();
        // Pending approvals win the label — they need a human right now. Receipts
        // (today / total) are the fallback story once the queue is drained.
        let statusLabel = '';
        if (pending > 0) {
            statusLabel = ` · $(watch) ${pending} pending`;
        } else {
            const today = receiptsProvider.todayCount();
            const total = receiptsProvider.totalCount();
            statusLabel = today > 0 ? ` · ${today} today` : total > 0 ? ` · ${total} total` : '';
        }
        stationStatus.text = `RailCall ${running}${statusLabel}${warn ? ' $(warning)' : ''}`;
    };

    // Refresh the status bar count whenever either tree fires a change.
    let stationLabel: string | null = null;
    let stationWarn = false;
    context.subscriptions.push(
        receiptsProvider.onDidChangeTreeData(() => refreshStatusBar(stationLabel, stationWarn)),
        stagingsProvider.onDidChangeTreeData(() => refreshStatusBar(stationLabel, stationWarn)),
    );

    setTimeout(async () => {
        const ver = await fetchStationVersion();
        if (!ver) {
            stationLabel = null;
            stationWarn = true;
            stationStatus.tooltip = `RailCall: station daemon not reachable. Extension expects ${EXPECTED_STATION_TAG}.`;
            refreshStatusBar(stationLabel, stationWarn);
            return;
        }
        stationLabel = ver.release_tag ?? 'pre-v0.5';
        stationWarn = !!(ver.release_tag && ver.release_tag !== EXPECTED_STATION_TAG);
        stationStatus.tooltip = `RailCall station: ${stationLabel}\nExtension built against: ${EXPECTED_STATION_TAG}`;
        refreshStatusBar(stationLabel, stationWarn);
        if (stationWarn) {
            const cmd = 'curl -fsSL https://railcall.ai/install.sh | bash';
            vscode.window.showWarningMessage(
                `RailCall: running station is ${stationLabel}, extension expects ${EXPECTED_STATION_TAG}. Re-install the station to match.`,
                'Copy Re-install Command',
            ).then(choice => {
                if (choice === 'Copy Re-install Command') {
                    vscode.env.clipboard.writeText(cmd);
                    vscode.window.showInformationMessage('RailCall: re-install command copied to clipboard.');
                }
            });
        }
    }, 2_500);

    // Ensure the initial count lands in the status bar without waiting for the version probe.
    setTimeout(() => refreshStatusBar(stationLabel, stationWarn), 400);

    // Sync keys silently on startup
    setTimeout(() => doSyncKeys(true), 2_000);

    // Auto-sync when settings change
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(e => {
            const cfg = vscode.workspace.getConfiguration('railcall');
            if (e.affectsConfiguration('railcall') && cfg.get<boolean>('autoSyncKeys', true)) {
                doSyncKeys(true);
            }
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('railcall.syncKeys', () => doSyncKeys(false))
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('railcall.focus', () => {
            vscode.commands.executeCommand('workbench.view.extension.railcall-sidebar');
        })
    );

    context.subscriptions.push(
        vscode.commands.registerCommand('railcall.moveToRight', () => {
            vscode.commands.executeCommand('workbench.action.moveSideBarToRight');
        })
    );

    const codeCommands: [string, string][] = [
        ['railcall.explain',  'Explain this code in detail:'],
        ['railcall.fix',      'Find and fix any bugs or issues in this code:'],
        ['railcall.refactor', 'Refactor this code for clarity and best practices:'],
    ];

    for (const [cmd, prefix] of codeCommands) {
        context.subscriptions.push(
            vscode.commands.registerCommand(cmd, () => {
                const ctx = getEditorContext();
                if (!ctx) { vscode.window.showWarningMessage('RailCall: open a file first.'); return; }
                const code = ctx.selectedText || ctx.fileContent;
                const prompt = `${prefix}\n\n\`\`\`${ctx.language}\n${code}\n\`\`\``;
                provider.sendUserMessage(prompt, ctx);
                vscode.commands.executeCommand('workbench.view.extension.railcall-sidebar');
            })
        );
    }

    context.subscriptions.push(
        vscode.commands.registerCommand('railcall.generate', () => {
            const ctx = getEditorContext();
            const editor = vscode.window.activeTextEditor;
            if (!ctx || !editor) { vscode.window.showWarningMessage('RailCall: open a file first.'); return; }
            const line = editor.selection.active.line;
            const commentLine = editor.document.lineAt(Math.max(0, line - 1)).text.trim();
            const prompt = commentLine
                ? `Generate ${ctx.language} code for: ${commentLine}`
                : `Generate ${ctx.language} code at cursor position in ${ctx.fileName}`;
            provider.sendUserMessage(prompt, ctx);
            vscode.commands.executeCommand('workbench.view.extension.railcall-sidebar');
        })
    );
}

export function deactivate() {}
