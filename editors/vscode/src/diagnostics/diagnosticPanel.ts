import { randomBytes } from "node:crypto";

import * as vscode from "vscode";

import { DiagnosticLog } from "./diagnosticLog";

export class DiagnosticPanel implements vscode.Disposable {
  private panel: vscode.WebviewPanel | undefined;
  private subscription: vscode.Disposable | undefined;

  public constructor(
    private readonly diagnostics: DiagnosticLog,
    private readonly followInTerminal: () => Promise<void> | void,
  ) {}

  public show(): void {
    if (this.panel !== undefined) {
      this.panel.reveal(vscode.ViewColumn.Beside);
      this.publishSnapshot();
      return;
    }
    const panel = vscode.window.createWebviewPanel(
      "chudvis.diagnostics",
      "Chudvis Diagnostics",
      vscode.ViewColumn.Beside,
      { enableScripts: true, retainContextWhenHidden: true },
    );
    this.panel = panel;
    panel.webview.html = this.html();
    this.subscription = this.diagnostics.onEvent((event) => {
      void panel.webview.postMessage({ type: "event", event });
    });
    panel.onDidDispose(() => {
      this.subscription?.dispose();
      this.subscription = undefined;
      this.panel = undefined;
    });
    panel.webview.onDidReceiveMessage((message: unknown) => {
      void this.handleMessage(message);
    });
    this.publishSnapshot();
  }

  private publishSnapshot(): void {
    void this.panel?.webview.postMessage({
      type: "snapshot",
      events: this.diagnostics.snapshot,
      filePath: this.diagnostics.filePath,
      includeModelPayloads: this.diagnostics.includeModelPayloads,
    });
  }

  private async handleMessage(message: unknown): Promise<void> {
    if (
      typeof message !== "object" ||
      message === null ||
      Array.isArray(message)
    ) {
      return;
    }
    const action = (message as Record<string, unknown>).action;
    switch (action) {
      case "ready":
        this.publishSnapshot();
        return;
      case "clear":
        await this.diagnostics.clear();
        this.publishSnapshot();
        return;
      case "follow":
        await this.followInTerminal();
        return;
      case "output":
        this.diagnostics.showOutput();
        return;
      case "reveal":
        await this.diagnostics.flush();
        await vscode.commands.executeCommand(
          "revealFileInOS",
          vscode.Uri.file(this.diagnostics.filePath),
        );
        return;
      case "payloads": {
        const enabled = (message as Record<string, unknown>).enabled;
        if (typeof enabled === "boolean") {
          await this.diagnostics.setIncludeModelPayloads(enabled);
          this.publishSnapshot();
        }
      }
    }
  }

  private html(): string {
    const nonce = randomBytes(16).toString("hex");
    const csp = [
      "default-src 'none'",
      `script-src 'nonce-${nonce}'`,
      `style-src 'nonce-${nonce}'`,
    ].join("; ");
    return `<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta http-equiv="Content-Security-Policy" content="${csp}">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style nonce="${nonce}">
    :root { color-scheme: light dark; }
    body { color: var(--vscode-foreground); background: var(--vscode-editor-background); font: var(--vscode-font-weight) var(--vscode-font-size)/1.45 var(--vscode-font-family); margin: 0; }
    header { background: var(--vscode-sideBar-background); border-bottom: 1px solid var(--vscode-panel-border); padding: 12px 16px; position: sticky; top: 0; z-index: 2; }
    h1 { font-size: 1.15rem; margin: 0 0 10px; }
    .toolbar { align-items: center; display: flex; flex-wrap: wrap; gap: 7px; }
    button, input, select { background: var(--vscode-input-background); border: 1px solid var(--vscode-input-border, transparent); color: var(--vscode-input-foreground); font: inherit; padding: 4px 8px; }
    button { background: var(--vscode-button-secondaryBackground); color: var(--vscode-button-secondaryForeground); cursor: pointer; }
    button:hover { background: var(--vscode-button-secondaryHoverBackground); }
    input[type="search"] { min-width: 220px; }
    label { align-items: center; display: inline-flex; gap: 5px; }
    .path { color: var(--vscode-descriptionForeground); font-family: var(--vscode-editor-font-family); font-size: .82rem; margin-top: 8px; overflow-wrap: anywhere; }
    #events { display: grid; gap: 1px; }
    article { border-bottom: 1px solid var(--vscode-panel-border); display: grid; grid-template-columns: 100px 120px minmax(150px, 1fr) 3fr; padding: 8px 16px; }
    article:hover { background: var(--vscode-list-hoverBackground); }
    time, .category, .request { color: var(--vscode-descriptionForeground); }
    .category { text-transform: uppercase; }
    .name { font-weight: 600; }
    pre { font-family: var(--vscode-editor-font-family); font-size: .86rem; margin: 5px 0 0; overflow: auto; white-space: pre-wrap; }
    .body { min-width: 0; }
    .empty { color: var(--vscode-descriptionForeground); padding: 36px 16px; text-align: center; }
    @media (max-width: 800px) { article { grid-template-columns: 90px 100px 1fr; } .body { grid-column: 1 / -1; margin-top: 5px; } }
  </style>
</head>
<body>
  <header>
    <h1>Chudvis Diagnostics</h1>
    <div class="toolbar">
      <select id="category" aria-label="Category"><option value="">All categories</option></select>
      <input id="search" type="search" placeholder="Filter events or payloads" aria-label="Filter diagnostics">
      <label><input id="paused" type="checkbox">Pause live view</label>
      <button id="clear">Clear</button><button id="follow">Follow in Terminal</button><button id="output">Show Output</button><button id="reveal">Reveal JSONL</button>
      <label title="Prompts, transcripts, source context, tool calls, and responses may contain sensitive workspace data."><input id="payloads" type="checkbox">Capture exact model payloads</label>
    </div>
    <div id="path" class="path"></div>
  </header>
  <main id="events"><div class="empty">Waiting for diagnostic events…</div></main>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    let events = [];
    let queued = [];
    const eventsNode = document.getElementById('events');
    const categoryNode = document.getElementById('category');
    const searchNode = document.getElementById('search');
    const pausedNode = document.getElementById('paused');
    const render = () => {
      const category = categoryNode.value;
      const query = searchNode.value.trim().toLowerCase();
      const filtered = events.filter((event) => {
        if (category && event.category !== category) return false;
        return !query || JSON.stringify(event).toLowerCase().includes(query);
      }).slice().reverse();
      if (!filtered.length) {
        const empty = document.createElement('div'); empty.className = 'empty'; empty.textContent = 'No matching diagnostic events.'; eventsNode.replaceChildren(empty); return;
      }
      eventsNode.replaceChildren(...filtered.map((event) => {
        const row = document.createElement('article');
        const time = document.createElement('time'); time.textContent = new Date(event.timestamp).toLocaleTimeString(); time.dateTime = event.timestamp;
        const category = document.createElement('div'); category.className = 'category'; category.textContent = event.category;
        const name = document.createElement('div'); name.className = 'name'; name.textContent = event.name;
        const body = document.createElement('div'); body.className = 'body';
        if (event.requestId) { const request = document.createElement('div'); request.className = 'request'; request.textContent = 'request ' + event.requestId; body.append(request); }
        if (event.data !== undefined) { const data = document.createElement('pre'); data.textContent = JSON.stringify(event.data, null, 2); body.append(data); }
        row.append(time, category, name, body); return row;
      }));
    };
    const refreshCategories = () => {
      const selected = categoryNode.value;
      const categories = [...new Set(events.map((event) => event.category))].sort();
      categoryNode.replaceChildren(new Option('All categories', ''), ...categories.map((value) => new Option(value, value)));
      categoryNode.value = categories.includes(selected) ? selected : '';
    };
    for (const id of ['clear', 'follow', 'output', 'reveal']) document.getElementById(id).addEventListener('click', () => vscode.postMessage({ action: id }));
    document.getElementById('payloads').addEventListener('change', (event) => vscode.postMessage({ action: 'payloads', enabled: event.target.checked }));
    categoryNode.addEventListener('change', render); searchNode.addEventListener('input', render);
    pausedNode.addEventListener('change', () => { if (!pausedNode.checked && queued.length) { events.push(...queued); queued = []; refreshCategories(); render(); } });
    window.addEventListener('message', (message) => {
      const value = message.data;
      if (!value) return;
      if (value.type === 'snapshot') { events = value.events || []; queued = []; document.getElementById('path').textContent = value.filePath || ''; document.getElementById('payloads').checked = value.includeModelPayloads === true; refreshCategories(); render(); }
      if (value.type === 'event') { if (pausedNode.checked) queued.push(value.event); else { events.push(value.event); if (events.length > 1000) events.shift(); refreshCategories(); render(); } }
    });
    vscode.postMessage({ action: 'ready' });
  </script>
</body>
</html>`;
  }

  public dispose(): void {
    this.subscription?.dispose();
    this.panel?.dispose();
    this.subscription = undefined;
    this.panel = undefined;
  }
}
