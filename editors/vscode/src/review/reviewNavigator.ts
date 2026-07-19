import * as vscode from "vscode";

import { collectGitChanges } from "./gitChanges";

interface ChangeRecord {
  readonly uri: vscode.Uri;
  readonly ranges: vscode.Range[];
}

interface ReviewEntry {
  readonly uri: vscode.Uri;
  readonly range: vscode.Range;
}

const IGNORED_SEGMENTS = new Set([".git", ".venv", "node_modules", "dist"]);

function isReviewable(uri: vscode.Uri): boolean {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (folder === undefined) {
    return false;
  }
  const relative = vscode.workspace.asRelativePath(uri, false);
  return !relative
    .split(/[\\/]/u)
    .some((segment) => IGNORED_SEGMENTS.has(segment));
}

export class ReviewNavigator implements vscode.Disposable {
  private readonly records = new Map<string, ChangeRecord>();
  private readonly disposables: vscode.Disposable[] = [];
  private readonly decoration = vscode.window.createTextEditorDecorationType({
    isWholeLine: true,
    backgroundColor: new vscode.ThemeColor("diffEditor.insertedLineBackground"),
    overviewRulerColor: new vscode.ThemeColor(
      "editorOverviewRuler.addedForeground",
    ),
    overviewRulerLane: vscode.OverviewRulerLane.Right,
  });
  private recording = false;
  private cursor = -1;

  public constructor(private readonly status: (message: string) => void) {
    this.disposables.push(
      vscode.workspace.onDidChangeTextDocument((event) => {
        if (!this.recording || !isReviewable(event.document.uri)) {
          return;
        }
        for (const change of event.contentChanges) {
          const addedLines = change.text.split(/\r\n|\r|\n/u).length - 1;
          const endLine = Math.min(
            Math.max(
              change.range.end.line,
              change.range.start.line + addedLines,
            ),
            Math.max(event.document.lineCount - 1, 0),
          );
          this.track(
            event.document.uri,
            new vscode.Range(
              change.range.start.line,
              0,
              endLine,
              Number.MAX_SAFE_INTEGER,
            ),
          );
        }
      }),
    );
    const watcher = vscode.workspace.createFileSystemWatcher("**/*");
    this.disposables.push(
      watcher,
      watcher.onDidCreate((uri) => this.trackExternal(uri)),
      watcher.onDidChange((uri) => this.trackExternal(uri)),
      watcher.onDidDelete((uri) => this.trackExternal(uri)),
    );
  }

  public beginSession(): void {
    this.records.clear();
    this.cursor = -1;
    this.recording = true;
    this.status("Recording files changed by this agent request");
  }

  public finishSession(): void {
    this.recording = false;
  }

  private trackExternal(uri: vscode.Uri): void {
    if (
      this.recording &&
      isReviewable(uri) &&
      !this.records.has(uri.toString())
    ) {
      this.records.set(uri.toString(), { uri, ranges: [] });
    }
  }

  private track(uri: vscode.Uri, range: vscode.Range): void {
    const key = uri.toString();
    const existing = this.records.get(key);
    if (existing === undefined) {
      this.records.set(key, { uri, ranges: [range] });
    } else if (existing.ranges.length < 100) {
      existing.ranges.push(range);
    }
  }

  private async entries(): Promise<ReviewEntry[]> {
    if (this.records.size === 0) {
      for (const uri of await collectGitChanges()) {
        if (isReviewable(uri)) {
          this.records.set(uri.toString(), { uri, ranges: [] });
        }
      }
      for (const document of vscode.workspace.textDocuments) {
        if (document.isDirty && isReviewable(document.uri)) {
          this.records.set(document.uri.toString(), {
            uri: document.uri,
            ranges: [],
          });
        }
      }
    }
    const entries: ReviewEntry[] = [];
    const records = [...this.records.values()].sort((left, right) =>
      left.uri.toString().localeCompare(right.uri.toString()),
    );
    for (const record of records) {
      if (record.ranges.length === 0) {
        entries.push({ uri: record.uri, range: new vscode.Range(0, 0, 0, 0) });
      } else {
        for (const range of record.ranges) {
          entries.push({ uri: record.uri, range });
        }
      }
    }
    return entries;
  }

  public async navigate(direction: number): Promise<void> {
    const entries = await this.entries();
    if (entries.length === 0) {
      this.status("No captured or source-control changes to review");
      return;
    }
    const step = direction < 0 ? -1 : 1;
    this.cursor = (this.cursor + step + entries.length) % entries.length;
    const entry = entries[this.cursor];
    if (entry === undefined) {
      return;
    }
    try {
      const document = await vscode.workspace.openTextDocument(entry.uri);
      const editor = await vscode.window.showTextDocument(document, {
        preview: false,
        preserveFocus: false,
      });
      const range = document.validateRange(entry.range);
      editor.revealRange(
        range,
        vscode.TextEditorRevealType.InCenterIfOutsideViewport,
      );
      editor.setDecorations(this.decoration, [range]);
      const file = vscode.workspace.asRelativePath(entry.uri, false);
      this.status(`Review ${this.cursor + 1}/${entries.length}: ${file}`);
    } catch {
      this.status(
        "Changed file is no longer available; move to the next change",
      );
    }
  }

  public dispose(): void {
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
    this.decoration.dispose();
  }
}
