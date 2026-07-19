import { randomBytes } from "node:crypto";

import * as vscode from "vscode";

import type { VoiceState } from "../voice/protocol";

export type SidebarRequestAction =
  "openChanges" | "apply" | "cancel" | "undo" | "clearMemory";

export type SidebarAction =
  | SidebarRequestAction
  | "toggleControls"
  | "testTracking"
  | "calibrate"
  | "showDiagnostics"
  | "configureBackboard"
  | "configureElevenLabs"
  | "configureElevenLabsVoice"
  | "testElevenLabsVoice";

interface HistoryEntry {
  readonly kind: "request" | "answer" | "edit" | "error";
  readonly text: string;
}

interface SidebarState {
  readonly controlsRunning: boolean;
  readonly controlsStarting: boolean;
  readonly backboardStatus: string;
  readonly elevenLabsStatus: string;
  readonly elevenLabsVoiceStatus: string;
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
  controlsRunning: false,
  controlsStarting: false,
  backboardStatus: "Checking…",
  elevenLabsStatus: "Checking…",
  elevenLabsVoiceStatus: "Checking…",
  voiceState: "paused",
  detail: "Controls are off. Start them here or use the keyboard shortcut.",
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
        ![
          "openChanges",
          "apply",
          "cancel",
          "undo",
          "clearMemory",
          "toggleControls",
          "testTracking",
          "calibrate",
          "showDiagnostics",
          "configureBackboard",
          "configureElevenLabs",
          "configureElevenLabsVoice",
          "testElevenLabsVoice",
        ].includes(String(message.action))
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

  public setVoiceLevel(level: number, dbfs: number): void {
    const boundedLevel = Math.max(0, Math.min(1, level));
    const boundedDbfs = Math.max(-100, Math.min(0, dbfs));
    void this.view?.webview.postMessage({
      type: "voiceLevel",
      level: boundedLevel,
      dbfs: boundedDbfs,
    });
  }

  public setControls(running: boolean): void {
    this.state = {
      ...this.state,
      controlsRunning: running,
      controlsStarting: false,
      voiceState: running ? "ready" : "paused",
      detail: running
        ? "Controls are on. Say “Chudvis” to begin."
        : "Controls are off. Start them here or use the keyboard shortcut.",
      partial: "",
    };
    void this.publish();
    if (!running) {
      this.setVoiceLevel(0, -100);
    }
  }

  public setStarting(starting: boolean): void {
    this.state = {
      ...this.state,
      controlsRunning: false,
      controlsStarting: starting,
      voiceState: starting ? "connecting" : "paused",
      detail: starting
        ? "Starting camera, microphone, and backend…"
        : "Controls are off. Start them here or use the keyboard shortcut.",
      partial: "",
    };
    void this.publish();
  }

  public setServiceStatus(
    backboardStatus: string,
    elevenLabsStatus: string,
    elevenLabsVoiceStatus: string,
  ): void {
    this.state = {
      ...this.state,
      backboardStatus: backboardStatus.slice(0, 200),
      elevenLabsStatus: elevenLabsStatus.slice(0, 200),
      elevenLabsVoiceStatus: elevenLabsVoiceStatus.slice(0, 200),
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
    const shortcut = process.platform === "darwin" ? "Cmd+Alt+G" : "Ctrl+Alt+G";
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
    .microphone { align-items: center; display: grid; gap: 4px 8px; grid-template-columns: auto 1fr auto; margin: 10px 0 2px; }
    .microphone-label, .microphone-value { color: var(--vscode-descriptionForeground); font-size: .82em; }
    .microphone-meter { background: var(--vscode-progressBar-background); border-radius: 3px; height: 7px; min-width: 60px; overflow: hidden; }
    .microphone-fill { background: var(--vscode-charts-green); height: 100%; transform: scaleX(0); transform-origin: left; transition: transform 80ms linear; width: 100%; }
    .label { font-size: .9em; margin-top: 12px; }
    .content { overflow-wrap: anywhere; white-space: pre-wrap; }
    .partial { color: var(--vscode-descriptionForeground); font-style: italic; }
    .target { border-left: 2px solid var(--vscode-focusBorder); padding-left: 8px; }
    .actions { display: flex; flex-wrap: wrap; gap: 6px; margin: 14px 0; }
    .controls { display: grid; grid-template-columns: 1fr 1fr; margin: 12px 0 16px; }
    .controls .primary { grid-column: 1 / -1; }
    button { background: var(--vscode-button-secondaryBackground); border: 1px solid transparent; color: var(--vscode-button-secondaryForeground); cursor: pointer; padding: 4px 9px; }
    button:hover { background: var(--vscode-button-secondaryHoverBackground); }
    button.primary { background: var(--vscode-button-background); color: var(--vscode-button-foreground); }
    button.primary:hover { background: var(--vscode-button-hoverBackground); }
    button:disabled { cursor: default; opacity: .45; }
    details { border-top: 1px solid var(--vscode-sideBarSectionHeader-border); margin-top: 14px; padding-top: 8px; }
    summary { cursor: pointer; font-weight: 600; }
    table { border-collapse: collapse; margin-top: 8px; width: 100%; }
    th, td { border-top: 1px solid var(--vscode-sideBarSectionHeader-border); padding: 7px 4px; text-align: left; vertical-align: top; }
    thead th { border-top: 0; color: var(--vscode-descriptionForeground); font-size: .78em; padding-top: 2px; text-transform: uppercase; }
    tbody th { font-size: .82em; width: 34%; }
    .default { color: var(--vscode-descriptionForeground); display: block; font-size: .88em; font-weight: 400; }
    .guide-action { display: grid; gap: 1px; }
    .guide-action + .guide-action { margin-top: 7px; }
    .guide-action strong, .guide-action kbd { color: var(--vscode-foreground); font-size: .9em; }
    .guide-action span, .service-note { color: var(--vscode-descriptionForeground); }
    .service-table tbody th { width: 38%; }
    .service-status { color: var(--vscode-descriptionForeground); overflow-wrap: anywhere; }
    .service-actions { margin: 9px 0 6px; }
    .service-note { font-size: .88em; margin: 7px 0 0; }
    kbd { background: var(--vscode-keybindingLabel-background); border: 1px solid var(--vscode-keybindingLabel-border); border-bottom-color: var(--vscode-keybindingLabel-bottomBorder); border-radius: 3px; box-shadow: inset 0 -1px 0 var(--vscode-widget-shadow); font-family: var(--vscode-editor-font-family); padding: 1px 4px; width: fit-content; }
    .history { margin: 8px 0; padding-left: 18px; }
  </style>
</head>
<body>
  <div id="stateRow" class="state paused"><span class="dot" aria-hidden="true"></span><strong id="state">Off</strong></div>
  <div id="detail" class="muted"></div>
  <div class="microphone">
    <span class="microphone-label">Mic</span>
    <div id="microphoneMeter" class="microphone-meter" role="meter" aria-label="Microphone input level" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div id="microphoneFill" class="microphone-fill"></div></div>
    <span id="microphoneValue" class="microphone-value">No signal</span>
  </div>
  <div class="actions controls" aria-label="Chudvis controls">
    <button id="toggleControls" class="primary">Start Controls</button><button id="testTracking">Test Tracking</button><button id="calibrate">Recalibrate Gaze</button>
  </div>
  <div class="actions"><button id="showDiagnostics">Open Live Diagnostics</button></div>
  <details open>
    <summary>AI and voice setup</summary>
    <table class="service-table">
      <tbody>
        <tr><th scope="row">Backboard</th><td id="backboardStatus" class="service-status">Checking…</td></tr>
        <tr><th scope="row">ElevenLabs</th><td id="elevenLabsStatus" class="service-status">Checking…</td></tr>
        <tr><th scope="row">Spoken feedback</th><td id="elevenLabsVoiceStatus" class="service-status">Checking…</td></tr>
      </tbody>
    </table>
    <div class="actions service-actions">
      <button id="configureBackboard">Set Backboard Key</button><button id="configureElevenLabs">Set ElevenLabs Key</button><button id="configureElevenLabsVoice">Choose Voice Preset</button><button id="testElevenLabsVoice">Test Voice</button>
    </div>
    <p class="service-note">Keys are kept in VS Code secure storage. Workspace .env files are not loaded.</p>
  </details>
  <details open>
    <summary>Controls by hand</summary>
    <table class="guide-table">
      <thead><tr><th scope="col">Hand / input</th><th scope="col">Actions</th></tr></thead>
      <tbody>
        <tr>
          <th scope="row">No hand<span class="default">keyboard, eyes, voice</span></th>
          <td>
            <div class="guide-action"><kbd>${shortcut}</kbd><span>Start or stop all controls.</span></div>
            <div class="guide-action"><strong>Look at a target</strong><span>Move the pointer with gaze.</span></div>
            <div class="guide-action"><strong>Say “Chudvis,” then speak</strong><span>Try “open test.py,” “go to a symbol,” create a file, ask, or request an edit.</span></div>
          </td>
        </tr>
        <tr>
          <th scope="row">Editor hand<span class="default">right by default</span></th>
          <td>
            <div class="guide-action"><strong>Quick pinch</strong><span>Click and select the target symbol.</span></div>
            <div class="guide-action"><strong>Hold an open palm, then move it</strong><span>Continuously scroll the active editor.</span></div>
            <div class="guide-action"><strong>Hold thumbs-up</strong><span>Approve an edit or use fallback dictation.</span></div>
          </td>
        </tr>
        <tr>
          <th scope="row">Navigator hand<span class="default">left by default</span></th>
          <td><div class="guide-action"><strong>Hold an open palm, then move it</strong><span>Previous or next captured change.</span></div></td>
        </tr>
        <tr>
          <th scope="row">Either hand</th>
          <td><div class="guide-action"><strong>Hold an open palm still</strong><span>Cancel a request, or pause and resume.</span></div></td>
        </tr>
      </tbody>
    </table>
  </details>
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
    const renderVoiceLevel = (rawLevel, rawDbfs) => {
      const level = Math.max(0, Math.min(1, Number(rawLevel) || 0));
      const dbfs = Math.max(-100, Math.min(0, Number(rawDbfs) || -100));
      const percent = Math.round(level * 100);
      document.getElementById('microphoneFill').style.transform = 'scaleX(' + level + ')';
      document.getElementById('microphoneMeter').setAttribute('aria-valuenow', String(percent));
      document.getElementById('microphoneValue').textContent = dbfs <= -99 ? 'No signal' : Math.round(dbfs) + ' dBFS';
    };
    for (const action of ['openChanges', 'apply', 'cancel', 'undo', 'clearMemory', 'toggleControls', 'testTracking', 'calibrate', 'showDiagnostics', 'configureBackboard', 'configureElevenLabs', 'configureElevenLabsVoice', 'testElevenLabsVoice']) {
      document.getElementById(action).addEventListener('click', () => vscode.postMessage({ action }));
    }
    window.addEventListener('message', (event) => {
      if (!event.data) return;
      if (event.data.type === 'voiceLevel') {
        renderVoiceLevel(event.data.level, event.data.dbfs);
        return;
      }
      if (event.data.type !== 'state') return;
      const state = event.data.state;
      const visibleState = state.controlsStarting ? 'Activating CHUD…' : state.controlsRunning ? state.voiceState[0].toUpperCase() + state.voiceState.slice(1) : 'Off';
      document.getElementById('state').textContent = visibleState;
      document.getElementById('stateRow').className = 'state ' + (state.controlsStarting ? 'connecting' : state.controlsRunning ? state.voiceState : 'paused');
      document.getElementById('detail').textContent = state.detail;
      document.getElementById('toggleControls').textContent = state.controlsRunning || state.controlsStarting ? 'Stop Controls' : 'Start Controls';
      document.getElementById('backboardStatus').textContent = state.backboardStatus;
      document.getElementById('elevenLabsStatus').textContent = state.elevenLabsStatus;
      document.getElementById('elevenLabsVoiceStatus').textContent = state.elevenLabsVoiceStatus;
      if (!state.controlsRunning) renderVoiceLevel(0, -100);
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
