import * as vscode from 'vscode';
import * as fs from 'fs';
import * as path from 'path';

export interface EditorContext {
    fileName: string;
    filePath: string;
    language: string;
    selectedText: string;
    fileContent: string;
    cursorLine: number;
    totalLines: number;
}

const MAX_FILE_CHARS = 40_000;
const IGNORE_DIRS = new Set([
    'node_modules', '.git', '__pycache__', '.venv', 'venv',
    'dist', 'out', 'build', '.next', '.cache', 'coverage',
]);

export function getWorkspaceRoot(): string | null {
    // 1. Explicit workspace folder
    const folder = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath;
    if (folder) { return folder; }
    // 2. Fallback: directory of the active file
    const file = vscode.window.activeTextEditor?.document.fileName;
    if (file) { return path.dirname(file); }
    return null;
}

export function getEditorContext(): EditorContext | null {
    const editor = vscode.window.activeTextEditor;
    if (!editor) { return null; }

    const doc = editor.document;
    const sel = editor.selection;
    const selectedText = sel.isEmpty ? '' : doc.getText(sel);
    const fullText = doc.getText();
    const fileContent = fullText.length > MAX_FILE_CHARS
        ? fullText.slice(0, MAX_FILE_CHARS) + '\n... [truncated]'
        : fullText;

    return {
        fileName: path.basename(doc.fileName),
        filePath: doc.fileName,
        language: doc.languageId,
        selectedText,
        fileContent,
        cursorLine: sel.active.line + 1,
        totalLines: doc.lineCount,
    };
}

export function getWorkspaceTree(root: string, depth = 0, maxDepth = 2): string {
    if (depth > maxDepth) { return ''; }
    const lines: string[] = [];
    try {
        const entries = fs.readdirSync(root, { withFileTypes: true });
        for (const e of entries) {
            if (e.name.startsWith('.')) { continue; }
            if (IGNORE_DIRS.has(e.name)) { continue; }
            const indent = '  '.repeat(depth);
            if (e.isDirectory()) {
                lines.push(`${indent}${e.name}/`);
                const sub = getWorkspaceTree(path.join(root, e.name), depth + 1, maxDepth);
                if (sub) { lines.push(sub); }
            } else {
                lines.push(`${indent}${e.name}`);
            }
        }
    } catch { /* unreadable */ }
    return lines.join('\n');
}

export function findAndReadFile(name: string, workspaceRoot: string | null): string | null {
    // Expand ~ to home
    const expanded = name.startsWith('~/')
        ? path.join(process.env.HOME || process.env.USERPROFILE || '', name.slice(2))
        : name;

    // Absolute path — read directly, ignore workspaceRoot
    if (path.isAbsolute(expanded)) {
        if (fs.existsSync(expanded) && fs.statSync(expanded).isFile()) {
            return readSafe(expanded);
        }
        return null;
    }

    if (!workspaceRoot) { return null; }

    // Relative path from workspace root
    const direct = path.join(workspaceRoot, expanded);
    if (fs.existsSync(direct) && fs.statSync(direct).isFile()) {
        return readSafe(direct);
    }

    // Bare filename: recursive search
    const base = path.basename(expanded);
    if (base === expanded) {
        return searchFile(base, workspaceRoot, 0);
    }
    return null;
}

function readSafe(p: string): string | null {
    try {
        const content = fs.readFileSync(p, 'utf8');
        return content.length > MAX_FILE_CHARS
            ? content.slice(0, MAX_FILE_CHARS) + '\n...[truncated]'
            : content;
    } catch { return null; }
}

function searchFile(name: string, dir: string, depth: number): string | null {
    if (depth > 3) { return null; }
    try {
        const entries = fs.readdirSync(dir, { withFileTypes: true });
        for (const e of entries) {
            if (IGNORE_DIRS.has(e.name) || e.name.startsWith('.')) { continue; }
            if (e.isFile() && e.name === name) {
                return readSafe(path.join(dir, e.name));
            }
            if (e.isDirectory()) {
                const found = searchFile(name, path.join(dir, e.name), depth + 1);
                if (found !== null) { return found; }
            }
        }
    } catch { /* skip */ }
    return null;
}

// Explicit known extensions — controls both the path detector and token check.
const EXT_LIST = 'js|ts|jsx|tsx|md|py|json|yaml|yml|sh|txt|toml|go|rs|rb|java|cs|cpp|c|h|env|sql|html|css|vue|svelte|csv|tsv|log|xml|ini|conf';
const KNOWN_EXTS = new RegExp('\\.(' + EXT_LIST + ')$', 'i');

// Absolute/home paths — allow spaces inside path segments (e.g. "demo folder/foo.csv")
const ABS_PATH_RE = new RegExp('(?:~?/[^\\n\\r\'"`]+?\\.(?:' + EXT_LIST + '))(?=\\s|$|[.,;:!?)])', 'gi');

export function extractFileMentions(text: string): string[] {
    const results = new Set<string>();

    // 1. Absolute paths (may contain spaces) — /Users/foo/bar folder/x.csv or ~/foo/x.md
    const absMatches = text.match(ABS_PATH_RE) ?? [];
    for (const m of absMatches) {
        results.add(m.trim());
    }

    // 2. Whitespace-safe tokens ending in a known extension (relative paths + bare names)
    const tokens = text.match(/[^\s"'`<>()[\]{},;]+/g) ?? [];
    for (const token of tokens) {
        if (KNOWN_EXTS.test(token)) {
            if (/^[\d.]+$/.test(token)) { continue; }       // version strings
            if (token.startsWith('http')) { continue; }     // URLs
            // Skip if this token is a fragment already covered by an absolute path
            let covered = false;
            for (const abs of results) {
                if (abs.endsWith(token)) { covered = true; break; }
            }
            if (!covered) { results.add(token); }
        }
    }

    return [...results];
}
