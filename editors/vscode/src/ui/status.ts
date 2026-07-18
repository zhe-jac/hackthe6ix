import * as vscode from "vscode";

export class StatusPresenter implements vscode.Disposable {
  private readonly item = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Left,
    50,
  );
  private bridgeConnected = false;
  private detail = "Starting bridge";
  private paused = false;

  public constructor() {
    this.item.command = "gazemotion.startBridge";
    this.item.name = "GazeMotion";
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

  private render(): void {
    const connection = this.bridgeConnected
      ? "$(radio-tower)"
      : "$(debug-disconnect)";
    const mode = this.paused
      ? "Paused"
      : this.bridgeConnected
        ? "Ready"
        : "Waiting";
    this.item.text = `${connection} GazeMotion: ${mode}`;
    this.item.tooltip = this.detail;
    this.item.backgroundColor = this.paused
      ? new vscode.ThemeColor("statusBarItem.warningBackground")
      : undefined;
  }

  public dispose(): void {
    this.item.dispose();
  }
}
