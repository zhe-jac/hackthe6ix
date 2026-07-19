import * as vscode from "vscode";

import type { VoiceState } from "../voice/protocol";

export class StatusPresenter implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    50,
  );
  private bridgeConnected = false;
  private detail = "Starting bridge";
  private paused = false;
  private voiceState: VoiceState | undefined;

  public constructor() {
    this.item.command = "chudvis.startBridge";
    this.item.name = "Chudvis";
    this.item.show();
    this.render();
  }

  public setBridge(connected: boolean, detail: string): void {
    this.bridgeConnected = connected;
    this.detail = detail;
    this.render();
  }

  public setPaused(paused: boolean): void {
    this.paused = paused;
    this.render();
  }

  public setDetail(detail: string): void {
    this.detail = detail;
    this.render();
  }

  public setVoiceState(state: VoiceState, detail = ""): void {
    this.voiceState = state;
    if (detail.length > 0) {
      this.detail = detail;
    }
    this.render();
  }

  private render(): void {
    const connection = this.bridgeConnected
      ? "$(radio-tower)"
      : "$(debug-disconnect)";
    const voiceLabels: Readonly<Record<VoiceState, string>> = {
      ready: "Ready",
      connecting: "Connecting…",
      listening: "Listening…",
      understanding: "Understanding…",
      editing: "Editing…",
      speaking: "Speaking…",
      error: "Error",
      paused: "Paused",
    };
    const mode = this.paused
      ? "Paused"
      : this.voiceState === undefined
        ? this.bridgeConnected
          ? "Ready"
          : "Waiting"
        : voiceLabels[this.voiceState];
    this.item.text = `${connection} Chudvis: ${mode}`;
    this.item.tooltip = this.detail;
    this.item.backgroundColor =
      this.voiceState === "error"
        ? new vscode.ThemeColor("statusBarItem.errorBackground")
        : this.paused || this.voiceState === "listening"
          ? new vscode.ThemeColor("statusBarItem.warningBackground")
          : undefined;
  }

  public dispose(): void {
    this.item.dispose();
  }
}
