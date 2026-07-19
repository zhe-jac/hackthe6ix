import { randomBytes } from "node:crypto";

import * as vscode from "vscode";

import type { VoiceState } from "../voice/protocol";

export type SidebarAction =
  "openChanges" | "apply" | "cancel" | "undo" | "clearMemory";

interface HistoryEntry {
  readonly kind: "request" | "answer" | "edit" | "error";
  readonly text: string;
}

interface SidebarState {
  readonly voiceState: VoiceState;
  readonly detail: string;
  readonly partial: string;
  readonly transcript: string;
  readonly answer: string;
  readonly target: string;
  readonly summary: string;
  readonly approvalPending: boolean;
  readonly canUndo: boolean;
  readonly history: readonly HistoryEntry[];
}

const INITIAL_STATE: SidebarState = {
  voiceState: "ready",
  detail: "Say “Chudvis” to begin",
  partial: "",
  transcript: "",
  answer: "",
  target: "",
  summary: "",
  approvalPending: false,
  canUndo: false,
  history: [],
};

export class ChudvisSidebar
  implements vscode.WebviewViewProvider, vscode.Disposable
{
  public static readonly viewType = "chudvis.sidebar";

  private view: vscode.WebviewView | undefined;
  private state: SidebarState = INITIAL_STATE;

  public constructor(
    private readonly onAction: (action: SidebarAction) => void,
  ) {}

  public resolveWebviewView(view: vscode.WebviewView): void {
    this.view = view;
    view.webview.options = { enableScripts: true, localResourceRoots: [] };
    view.webview.html = this.html();
    view.webview.onDidReceiveMessage((message: unknown) => {
      if (
        typeof message !== "object" ||
        message === null ||
        Array.isArray(message) ||
        !("action" in message) ||
        !["openChanges", "apply", "cancel", "undo", "clearMemory"].includes(
          String(message.action),
        )
      ) {
        return;
      }
      this.onAction(message.action as SidebarAction);
    });
    void this.publish();
  }

  public setVoiceState(state: VoiceState, detail = ""): void {
    this.state = {
      ...this.state,
      voiceState: state,
      detail: detail || this.defaultDetail(state),
      partial: state === "listening" ? this.state.partial : "",
    };
    void this.publish();
  }

  public setPartial(text: string): void {
    this.state = { ...this.state, partial: text.slice(0, 16_000) };
    void this.publish();
  }

  public beginRequest(transcript: string): void {
    const bounded = transcript.slice(0, 16_000);
    this.state = {
      ...this.state,
      transcript: bounded,
      partial: "",
      answer: "",
      target: "",
      summary: "",
      approvalPending: false,
      history: this.addHistory("request", bounded),
    };
    void this.publish();
  }

  public setTarget(label: string): void {
    this.state = { ...this.state, target: label.slice(0, 1_000) };
    void this.publish();
  }

  public appendAnswer(chunk: string): void {
    this.state = {
      ...this.state,
      answer: `${this.state.answer}${chunk}`.slice(0, 64_000),
    };
    void this.publish();
  }

  public finishAnswer(): void {
    if (this.state.answer.length > 0) {
      this.state = {
        ...this.state,
        history: this.addHistory("answer", this.state.answer),
      };
      void this.publish();
    }
  }

  public setApprovalPending(pending: boolean): void {
    this.state = { ...this.state, approvalPending: pending };
    void this.publish();
  }

  public setSummary(summary: string, canUndo: boolean): void {
    const bounded = summary.slice(0, 2_000);
    this.state = {
      ...this.state,
      summary: bounded,
      approvalPending: false,
      canUndo,
      history: this.addHistory("edit", bounded),
    };
    void this.publish();
  }

  public setError(detail: string): void {
    const bounded = detail.slice(0, 2_000);
    this.state = {
      ...this.state,
      voiceState: "error",
      detail: bounded,
      approvalPending: false,
      history: this.addHistory("error", bounded),
    };
    void this.publish();
  }

  public setCanUndo(canUndo: boolean): void {
    this.state = { ...this.state, canUndo };
    void this.publish();
  }

  private addHistory(
    kind: HistoryEntry["kind"],
    text: string,
  ): readonly HistoryEntry[] {
    return [...this.state.history, { kind, text: text.slice(0, 4_000) }].slice(
      -20,
    );
  }

  private defaultDetail(state: VoiceState): string {
    const details: Readonly<Record<VoiceState, string>> = {
      ready: "Say “Chudvis” to begin",
      connecting: "Connecting to realtime transcription",
      listening: "Listening for one request",
      understanding: "Routing your request",
      editing: "Preparing a bounded code change",
      speaking: "Speaking the edit summary",
      error: "Chudvis encountered an error",
      paused: "Voice activation is paused",
    };
    return details[state];
  }

  private async publish(): Promise<void> {
    await this.view?.webview.postMessage({ type: "state", state: this.state });
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
    body { color: var(--vscode-foreground); background: var(--vscode-sideBar-background); font: var(--vscode-font-weight) var(--vscode-font-size)/1.45 var(--vscode-font-family); margin: 0; padding: 12px; }
    .state { align-items: center; display: flex; gap: 8px; margin-bottom: 10px; }
    .dot { background: var(--vscode-descriptionForeground); border-radius: 50%; height: 9px; width: 9px; }
    .listening .dot { background: var(--vscode-charts-yellow); box-shadow: 0 0 0 3px color-mix(in srgb, var(--vscode-charts-yellow) 25%, transparent); }
    .error .dot { background: var(--vscode-errorForeground); }
    .muted, .label { color: var(--vscode-descriptionForeground); }
    .label { font-size: .9em; margin-top: 12px; }
    .content { overflow-wrap: anywhere; white-space: pre-wrap; }
    .partial { color: var(--vscode-descriptionForeground); font-style: italic; }
    .target { border-left: 2px solid var(--vscode-focusBorder); padding-left: 8px; }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0; }
    button { background: var(--vscode-button-secondaryBackground); border: 1px solid transparent; color: var(--vscode-button-secondaryForeground); cursor: pointer; padding: 4px 9px; }
    button:hover { background: var(--vscode-button-secondaryHoverBackground); }
    button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
    button.primary:hover { background: var(--vscode-button-hoverBackground); }
    button:disabled { cursor: default; opacity: .45; }
    details { border-top: 1px solid var(--vscode-sideBarSectionHeader-border); margin-top: 14px; padding-top: 8px; }
    .history { margin: 8px 0; padding-left: 18px; }
  </style>
</head>
<body>
  <div id="stateRow" class="state"><span class="dot" aria-hidden="true"></span><strong id="state">Ready</strong></div>
  <div id="detail" class="muted"></div>
  <div id="partialLabel" class="label" hidden>Live transcript</div><div id="partial" class="content partial"></div>
  <div id="transcriptLabel" class="label" hidden>Request</div><div id="transcript" class="content"></div>
  <div id="targetLabel" class="label" hidden>Resolved target</div><div id="target" class="content target"></div>
  <div id="answerLabel" class="label" hidden>Answer</div><div id="answer" class="content"></div>
  <div id="summaryLabel" class="label" hidden>Latest change</div><div id="summary" class="content"></div>
  <div class="actions" aria-label="Chudvis actions">
    <button id="openChanges">Open Changes</button><button id="apply" class="primary">Apply</button><button id="cancel">Cancel</button><button id="undo">Undo</button><button id="clearMemory">Clear Memory</button>
  </div>
  <details><summary>Session history</summary><ol id="history" class="history"></ol></details>
  <script nonce="${nonce}">
    const vscode = acquireVsCodeApi();
    const ids = ['partial', 'transcript', 'target', 'answer', 'summary'];
    for (const action of ['openChanges', 'apply', 'cancel', 'undo', 'clearMemory']) {
      document.getElementById(action).addEventListener('click', () => vscode.postMessage({ action }));
    }
    window.addEventListener('message', (event) => {
      if (!event.data || event.data.type !== 'state') return;
      const state = event.data.state;
      document.getElementById('state').textContent = state.voiceState[0].toUpperCase() + state.voiceState.slice(1);
      document.getElementById('stateRow').className = 'state ' + state.voiceState;
      document.getElementById('detail').textContent = state.detail;
      for (const id of ids) {
        const value = String(state[id] || '');
        document.getElementById(id).textContent = value;
        document.getElementById(id + 'Label').hidden = value.length === 0;
      }
      document.getElementById('apply').disabled = !state.approvalPending;
      document.getElementById('undo').disabled = !state.canUndo;
      document.getElementById('openChanges').disabled = !state.approvalPending && !state.canUndo;
      const history = document.getElementById('history');
      history.replaceChildren(...state.history.map((entry) => {
        const item = document.createElement('li'); item.textContent = entry.kind + ': ' + entry.text; return item;
      }));
    });
  </script>
</body>
</html>`;
  }

  public dispose(): void {
    this.view = undefined;
  }
}
