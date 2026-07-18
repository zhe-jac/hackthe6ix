import * as vscode from "vscode";

export class EditorActions {
  public constructor(private readonly status: (message: string) => void) {}

  public async scroll(lines: number): Promise<void> {
    if (vscode.window.activeTextEditor === undefined) {
      this.status("Scroll ignored: no text editor is active");
      return;
    }
    const bounded = Math.max(-200, Math.min(200, Math.trunc(lines)));
    if (bounded === 0) {
      return;
    }
    await vscode.commands.executeCommand("editorScroll", {
      to: bounded > 0 ? "down" : "up",
      by: "line",
      value: Math.abs(bounded),
      revealCursor: false,
    });
  }
}
