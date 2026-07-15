import * as vscode from 'vscode';
import { RailCallSidebarProvider } from './sidebarProvider';
import { RailCallReceiptsProvider } from './receiptsProvider';
import { getEditorContext } from './contextProvider';
import { syncSettings, fetchStationVersion } from './apiClient';

// Station tag this extension build was validated against. Update when we cut a new
// station release. Mismatch with the running station triggers a warning banner.
const EXPECTED_STATION_TAG = 'station-v0.5';

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
    context.subscriptions.push(
        vscode.window.registerTreeDataProvider('railcall.receipts', receiptsProvider),
        { dispose: () => receiptsProvider.dispose() },
        vscode.commands.registerCommand('railcall.refreshReceipts', () => receiptsProvider.refresh()),
        vscode.commands.registerCommand('railcall.openReceipt', async (filePath: string) => {
            if (!filePath) { return; }
            try {
                const doc = await vscode.workspace.openTextDocument(vscode.Uri.file(filePath));
                await vscode.window.showTextDocument(doc, { preview: true });
            } catch (e: any) {
                vscode.window.showWarningMessage(`RailCall: could not open receipt — ${e.message}`);
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
        const today = receiptsProvider.todayCount();
        const total = receiptsProvider.totalCount();
        const receiptLabel = today > 0 ? ` · ${today} today` : total > 0 ? ` · ${total} total` : '';
        stationStatus.text = `RailCall ${running}${receiptLabel}${warn ? ' $(warning)' : ''}`;
    };

    // Refresh the status bar count whenever the tree fires a change (fs.watch → debounce → refresh).
    let stationLabel: string | null = null;
    let stationWarn = false;
    context.subscriptions.push(
        receiptsProvider.onDidChangeTreeData(() => refreshStatusBar(stationLabel, stationWarn)),
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
