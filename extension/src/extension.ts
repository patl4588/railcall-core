import * as vscode from 'vscode';
import { RailCallSidebarProvider } from './sidebarProvider';
import { getEditorContext } from './contextProvider';
import { syncSettings } from './apiClient';

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
