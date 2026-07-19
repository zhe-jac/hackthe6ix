import * as path from "node:path";

import * as vscode from "vscode";

import type { ValidatedEditPlan } from "../edits/editService";

interface ReviewEntry {
  readonly title: string;
  readonly left: vscode.Uri;
  readonly right: vscode.Uri;
  readonly range: vscode.Range;
}

export interface EditReviewPresentation {
  readonly active: boolean;
  prepare(plan: ValidatedEditPlan): void;
  markApplied(): void;
  openChanges(): Promise<void>;
  navigate(direction: number): Promise<void>;
  clear(): void;
}

class SnapshotProvider implements vscode.TextDocumentContentProvider {
  private readonly documents = new Map<string, string>();
  private totalCharacters = 0;

  public set(uri: vscode.Uri, content: string): void {
    if (content.length > 512 * 1024) {
      throw new Error("Chudvis review snapshot exceeds the size limit");
    }
    this.documents.set(uri.toString(), content);
    this.totalCharacters += content.length;
    if (this.totalCharacters > 4 * 1024 * 1024) {
      this.clear();
      throw new Error("Chudvis review session exceeds the size limit");
    }
  }

  public provideTextDocumentContent(uri: vscode.Uri): string {
    const content = this.documents.get(uri.toString());
    if (content === undefined) {
      throw new Error("Chudvis review snapshot has expired");
    }
    return content;
  }

  public clear(): void {
    this.documents.clear();
    this.totalCharacters = 0;
  }
}

export class EditReviewPresenter
  implements EditReviewPresentation, vscode.Disposable
{
  private readonly original = new SnapshotProvider();
  private readonly proposed = new SnapshotProvider();
  private readonly disposables: vscode.Disposable[];
  private entries: readonly ReviewEntry[] = [];
  private cursor = -1;
  private plan: ValidatedEditPlan | undefined;
  private applied = false;

  public constructor(private readonly status: (message: string) => void) {
    this.disposables = [
      vscode.workspace.registerTextDocumentContentProvider(
        "chudvis-original",
        this.original,
      ),
      vscode.workspace.registerTextDocumentContentProvider(
        "chudvis-proposed",
        this.proposed,
      ),
    ];
  }

  public get active(): boolean {
    return this.entries.length > 0;
  }

  public prepare(plan: ValidatedEditPlan): void {
    this.clear();
    this.plan = plan;
    const entries: ReviewEntry[] = [];
    for (const [index, document] of plan.reviewDocuments.entries()) {
      const basename = path.posix.basename(
        document.relativePath.replaceAll("\\", "/"),
      );
      const originalUri = vscode.Uri.from({
        scheme: "chudvis-original",
        path: `/${plan.requestId}/${index}/${basename}`,
      });
      const proposedUri = vscode.Uri.from({
        scheme: "chudvis-proposed",
        path: `/${plan.requestId}/${index}/${basename}`,
      });
      this.original.set(originalUri, document.originalText);
      this.proposed.set(proposedUri, document.proposedText);
      const ranges =
        document.ranges.length > 0
          ? document.ranges
          : [new vscode.Range(0, 0, 0, 0)];
      for (const range of ranges) {
        entries.push({
          title: `Chudvis: ${document.relativePath}`,
          left: originalUri,
          right: proposedUri,
          range,
        });
      }
    }
    this.entries = entries;
    this.cursor = 0;
    this.applied = false;
  }

  public markApplied(): void {
    const plan = this.plan;
    if (plan === undefined) {
      return;
    }
    const byPath = new Map(
      plan.reviewDocuments.map((document) => [
        document.relativePath,
        document.uri,
      ]),
    );
    this.entries = this.entries.map((entry) => {
      const pathLabel = entry.title.slice("Chudvis: ".length);
      return { ...entry, right: byPath.get(pathLabel) ?? entry.right };
    });
    this.applied = true;
  }

  public async openChanges(): Promise<void> {
    if (this.entries.length === 0) {
      throw new Error("There are no Chudvis changes to review");
    }
    if (this.cursor < 0) {
      this.cursor = 0;
    }
    await this.openEntry(this.entries[this.cursor]);
  }

  public async navigate(direction: number): Promise<void> {
    if (this.entries.length === 0) {
      this.status("No Chudvis proposal or applied edit is available to review");
      return;
    }
    const step = direction < 0 ? -1 : 1;
    this.cursor =
      (this.cursor + step + this.entries.length) % this.entries.length;
    await this.openEntry(this.entries[this.cursor]);
  }

  private async openEntry(entry: ReviewEntry | undefined): Promise<void> {
    if (entry === undefined) {
      return;
    }
    await vscode.commands.executeCommand(
      "vscode.diff",
      entry.left,
      entry.right,
      entry.title,
      { preview: false, selection: entry.range },
    );
    const phase = this.applied ? "applied change" : "proposal";
    this.status(`Reviewing ${phase} ${this.cursor + 1}/${this.entries.length}`);
  }

  public clear(): void {
    this.entries = [];
    this.cursor = -1;
    this.plan = undefined;
    this.applied = false;
    this.original.clear();
    this.proposed.clear();
  }

  public dispose(): void {
    this.clear();
    for (const disposable of this.disposables) {
      disposable.dispose();
    }
  }
}
