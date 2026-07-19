import * as path from "node:path";

import * as vscode from "vscode";

import type { BridgeServer } from "../bridge/server";
import { EditContextResolver } from "../editor/contextResolver";
import {
  type AppliedEditResult,
  EditService,
  type ValidatedEditPlan,
} from "../edits/editService";
import type {
  ModelProvider,
  PendingModelEdit,
} from "../model/backboardProvider";
import { WorkspaceTools } from "../model/workspaceTools";
import { EditReviewPresenter } from "../review/editReview";
import { ReviewNavigator } from "../review/reviewNavigator";
import { ChudvisSidebar, type SidebarAction } from "../ui/chudvisSidebar";
import type { StatusPresenter } from "../ui/status";
import {
  SafeWorkspace,
  WORKSPACE_FILE_EXCLUDE,
} from "../workspace/safeWorkspace";
import type { ChudvisInbound, VoiceState } from "../voice/protocol";
import { routeVoiceRequest } from "../voice/router";

interface PendingReview {
  readonly model: PendingModelEdit;
  readonly plan: ValidatedEditPlan;
}

interface FlatSymbol {
  readonly name: string;
  readonly detail: string;
  readonly uri: vscode.Uri;
  readonly range: vscode.Range;
}

function flattenDocumentSymbols(
  document: vscode.TextDocument,
  symbols: readonly vscode.DocumentSymbol[],
): readonly FlatSymbol[] {
  const flattened: FlatSymbol[] = [];
  const visit = (symbol: vscode.DocumentSymbol): void => {
    flattened.push({
      name: symbol.name,
      detail: vscode.SymbolKind[symbol.kind],
      uri: document.uri,
      range: symbol.selectionRange,
    });
    for (const child of symbol.children) {
      visit(child);
    }
  };
  for (const symbol of symbols) {
    visit(symbol);
  }
  return flattened;
}

function fallbackFailureSummary(): string {
  return "I couldn't apply that edit safely.";
}

export class ChudvisCoordinator implements vscode.Disposable {
  private readonly workspace = new SafeWorkspace();
  private readonly tools = new WorkspaceTools(this.workspace);
  private readonly edits = new EditService(this.workspace);
  private readonly contextResolver: EditContextResolver;
  private activeRequestId: string | undefined;
  private pending: PendingReview | undefined;
  private readonly completed: string[] = [];

  public constructor(
    selection: ConstructorParameters<typeof EditContextResolver>[0],
    private readonly provider: ModelProvider,
    private readonly review: ReviewNavigator,
    private readonly editReview: EditReviewPresenter,
    private readonly sidebar: ChudvisSidebar,
    private readonly status: StatusPresenter,
    private readonly output: vscode.LogOutputChannel,
    private readonly bridge: () => BridgeServer | undefined,
    private readonly report: (message: string) => void,
  ) {
    this.contextResolver = new EditContextResolver(selection);
  }

  public async handleInbound(message: ChudvisInbound): Promise<void> {
    switch (message.method) {
      case "voice.state":
        if (
          message.requestId !== undefined &&
          this.activeRequestId !== undefined &&
          message.requestId !== this.activeRequestId
        ) {
          return;
        }
        if (
          message.requestId !== undefined &&
          ["connecting", "listening"].includes(message.state)
        ) {
          this.activeRequestId = message.requestId;
        }
        this.presentVoiceState(message.state, message.detail);
        if (message.state === "ready") {
          this.activeRequestId = undefined;
        }
        return;
      case "voice.partial":
        if (
          this.activeRequestId !== undefined &&
          message.requestId !== this.activeRequestId
        ) {
          return;
        }
        this.activeRequestId = message.requestId;
        this.sidebar.setPartial(message.text);
        return;
      case "voice.request":
        if (
          this.activeRequestId !== undefined &&
          message.requestId !== this.activeRequestId
        ) {
          return;
        }
        this.activeRequestId = message.requestId;
        this.sidebar.beginRequest(message.transcript);
        await this.processRequest(message.requestId, message.transcript);
        return;
      case "edit.approve":
        if (this.pending?.model.requestId === message.requestId) {
          await this.applyPending();
        }
        return;
      case "edit.cancel":
        if (this.activeRequestId === message.requestId) {
          await this.cancel(false);
        }
    }
  }

  public async handleLegacyRequest(transcript: string): Promise<void> {
    const requestId = `legacy-${Date.now().toString(36)}`;
    this.activeRequestId = requestId;
    this.sidebar.beginRequest(transcript);
    await this.processRequest(requestId, transcript);
  }

  private presentVoiceState(state: VoiceState, detail: string): void {
    this.status.setVoiceState(state, detail);
    this.sidebar.setVoiceState(state, detail);
  }

  private async processRequest(
    requestId: string,
    transcript: string,
  ): Promise<void> {
    try {
      const route = routeVoiceRequest(transcript);
      switch (route.kind) {
        case "open":
          await this.openFile(route.query);
          this.complete(requestId, "succeeded");
          return;
        case "symbol":
          await this.goToSymbol(route.query);
          this.complete(requestId, "succeeded");
          return;
        case "references":
          if (route.query !== undefined) {
            await this.goToSymbol(route.query);
          }
          await vscode.commands.executeCommand(
            "editor.action.referenceSearch.trigger",
          );
          this.report("Showing symbol references");
          this.complete(requestId, "succeeded");
          return;
        case "undo":
          await this.undo();
          this.complete(requestId, "succeeded");
          return;
        case "cancel":
          await this.cancel(false);
          this.complete(requestId, "cancelled");
          return;
        case "question":
          await this.answer(requestId, route.instruction);
          return;
        case "edit":
          await this.edit(requestId, route.instruction);
      }
    } catch (error: unknown) {
      if (this.completed.includes(requestId)) {
        return;
      }
      const detail =
        error instanceof Error ? error.message : "Chudvis request failed";
      this.output.error(detail);
      this.sidebar.setError(detail);
      void vscode.window.showErrorMessage(`Chudvis: ${detail}`);
      this.complete(requestId, "failed");
    }
  }

  private async answer(requestId: string, instruction: string): Promise<void> {
    this.presentVoiceState("understanding", "Answering without editing");
    const target = await this.contextResolver.resolve(instruction);
    this.sidebar.setTarget(target.label);
    await this.provider.answer(instruction, target, (chunk) =>
      this.sidebar.appendAnswer(chunk),
    );
    this.sidebar.finishAnswer();
    this.report("Chudvis answer is ready in the sidebar");
    this.complete(requestId, "succeeded");
  }

  private async edit(requestId: string, instruction: string): Promise<void> {
    this.presentVoiceState("editing", "Resolving a bounded edit target");
    const target = await this.contextResolver.resolve(instruction);
    this.sidebar.setTarget(target.label);
    const model = await this.provider.startEdit(
      requestId,
      instruction,
      target,
      this.tools,
    );
    let plan: ValidatedEditPlan;
    try {
      plan = await this.edits.validate(requestId, target, model.proposal);
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "Edit validation failed";
      try {
        await this.provider.finishEdit(model, {
          success: false,
          applied: false,
          error: detail.slice(0, 500),
        });
      } catch {
        // Validation remains authoritative even if Backboard cannot accept the result.
      }
      throw error;
    }
    this.editReview.prepare(plan);
    if (plan.requiresApproval) {
      this.pending = { model, plan };
      this.sidebar.setApprovalPending(true);
      this.bridge()?.sendNotification("edit.approvalRequested", {
        requestId,
        files: plan.files,
        changeCount: plan.changeCount,
      });
      await this.editReview.openChanges();
      this.report(
        "Chudvis proposal expands beyond the target and needs approval",
      );
      return;
    }
    await this.apply(model, plan);
  }

  private async applyPending(): Promise<void> {
    const pending = this.pending;
    if (pending === undefined) {
      return;
    }
    this.pending = undefined;
    this.sidebar.setApprovalPending(false);
    await this.apply(pending.model, pending.plan);
  }

  private async apply(
    model: PendingModelEdit,
    plan: ValidatedEditPlan,
  ): Promise<void> {
    let applied: AppliedEditResult;
    try {
      this.review.beginSession();
      try {
        applied = await this.edits.apply(plan);
      } finally {
        this.review.finishSession();
      }
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "Edit application failed";
      try {
        await this.provider.finishEdit(model, {
          success: false,
          applied: false,
          error: detail.slice(0, 500),
        });
      } catch {
        // Local edit safety does not depend on accepting a remote tool result.
      }
      this.complete(model.requestId, "failed", fallbackFailureSummary());
      throw error;
    }
    this.editReview.markApplied();
    let spokenSummary: string | undefined;
    try {
      spokenSummary = await this.provider.finishEdit(model, {
        success: true,
        applied: true,
        files: applied.files,
        changeCount: applied.changeCount,
      });
    } catch (error: unknown) {
      this.output.warn(
        `Backboard summary unavailable after successful edit: ${error instanceof Error ? error.message : "unknown error"}`,
      );
    }
    const summary = spokenSummary ?? applied.summary;
    this.sidebar.setSummary(summary, true);
    this.report(summary);
    this.complete(model.requestId, "succeeded", summary);
    void Promise.resolve(
      vscode.window.showInformationMessage(
        `Chudvis: ${summary}`,
        "Open Changes",
        "Undo",
      ),
    )
      .then(async (action) => {
        if (action === "Open Changes") {
          await this.editReview.openChanges();
        } else if (action === "Undo") {
          await this.undo();
        }
      })
      .catch((error: unknown) => {
        this.output.warn(
          `Chudvis completion action failed: ${error instanceof Error ? error.message : "unknown error"}`,
        );
      });
  }

  private async openFile(query: string): Promise<void> {
    const normalized = query.toLowerCase().replace(/^['"]|['"]$/gu, "");
    const uris = await vscode.workspace.findFiles(
      "**/*",
      WORKSPACE_FILE_EXCLUDE,
      1_001,
    );
    const candidates = uris
      .map((uri) => ({
        uri,
        relative: vscode.workspace.asRelativePath(uri, false),
      }))
      .filter(({ relative }) => {
        const lower = relative.toLowerCase();
        return (
          lower === normalized ||
          path.posix.basename(lower) === normalized ||
          lower.includes(normalized)
        );
      })
      .slice(0, 100);
    if (candidates.length === 0) {
      throw new Error(`No workspace file matches '${query}'`);
    }
    let selected = candidates[0];
    if (candidates.length > 1) {
      const picked = await vscode.window.showQuickPick(
        candidates.map((candidate) => ({
          label: path.posix.basename(candidate.relative.replaceAll("\\", "/")),
          description: candidate.relative,
          candidate,
        })),
        { title: `Open file matching “${query}”`, ignoreFocusOut: true },
      );
      selected = picked?.candidate;
    }
    if (selected === undefined) {
      throw new Error("File selection was cancelled");
    }
    await vscode.window.showTextDocument(
      await vscode.workspace.openTextDocument(selected.uri),
    );
    this.report(`Opened ${selected.relative}`);
  }

  private async goToSymbol(query: string): Promise<void> {
    const normalized = query.trim().toLowerCase();
    let candidates: readonly FlatSymbol[] = [];
    const document = vscode.window.activeTextEditor?.document;
    if (document !== undefined) {
      const symbols = await vscode.commands.executeCommand<
        vscode.DocumentSymbol[] | undefined
      >("vscode.executeDocumentSymbolProvider", document.uri);
      candidates = flattenDocumentSymbols(document, symbols ?? []).filter(
        (symbol) => symbol.name.toLowerCase().includes(normalized),
      );
    }
    if (candidates.length === 0) {
      const workspaceSymbols = await vscode.commands.executeCommand<
        vscode.SymbolInformation[] | undefined
      >("vscode.executeWorkspaceSymbolProvider", query);
      candidates = (workspaceSymbols ?? []).slice(0, 100).map((symbol) => ({
        name: symbol.name,
        detail: vscode.workspace.asRelativePath(symbol.location.uri, false),
        uri: symbol.location.uri,
        range: symbol.location.range,
      }));
    }
    if (candidates.length === 0) {
      throw new Error(`No symbol matches '${query}'`);
    }
    let selected =
      candidates.find(
        (candidate) => candidate.name.toLowerCase() === normalized,
      ) ?? candidates[0];
    if (candidates.length > 1) {
      const picked = await vscode.window.showQuickPick(
        candidates.map((candidate) => ({
          label: candidate.name,
          description: candidate.detail,
          candidate,
        })),
        { title: `Go to symbol matching “${query}”`, ignoreFocusOut: true },
      );
      selected = picked?.candidate;
    }
    if (selected === undefined) {
      throw new Error("Symbol selection was cancelled");
    }
    const editor = await vscode.window.showTextDocument(
      await vscode.workspace.openTextDocument(selected.uri),
    );
    editor.selection = new vscode.Selection(
      selected.range.start,
      selected.range.start,
    );
    editor.revealRange(
      selected.range,
      vscode.TextEditorRevealType.InCenterIfOutsideViewport,
    );
    this.report(`Opened symbol ${selected.name}`);
  }

  public async handleAction(action: SidebarAction): Promise<void> {
    try {
      switch (action) {
        case "openChanges":
          await this.editReview.openChanges();
          return;
        case "apply":
          await this.applyPending();
          return;
        case "cancel":
          await this.cancel(true);
          return;
        case "undo":
          await this.undo();
          return;
        case "clearMemory":
          await this.provider.clearEditingMemory();
          this.report("Chudvis editing memory cleared");
      }
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "Chudvis action failed";
      this.sidebar.setError(detail);
      void vscode.window.showErrorMessage(`Chudvis: ${detail}`);
    }
  }

  public async cancel(notifyPython: boolean): Promise<void> {
    const requestId = this.activeRequestId;
    const pending = this.pending;
    this.pending = undefined;
    this.sidebar.setApprovalPending(false);
    this.editReview.clear();
    if (requestId !== undefined) {
      if (notifyPython) {
        this.bridge()?.sendNotification("voice.cancel", { requestId });
      }
      this.complete(requestId, "cancelled");
    } else if (notifyPython) {
      this.bridge()?.sendNotification("voice.cancel");
    }
    await this.provider.cancel();
    if (pending !== undefined) {
      try {
        await this.provider.finishEdit(pending.model, {
          success: false,
          applied: false,
          rejected: true,
        });
      } catch {
        // Rejection is local and remains effective if the provider is unavailable.
      }
    }
    this.report("Chudvis request cancelled");
  }

  public async undo(): Promise<void> {
    const files = await this.edits.undo();
    this.sidebar.setCanUndo(false);
    this.report(
      `Undid the latest Chudvis edit in ${files.length} file${files.length === 1 ? "" : "s"}`,
    );
  }

  public async navigateReview(direction: number): Promise<void> {
    if (this.editReview.active) {
      await this.editReview.navigate(direction);
    } else {
      await this.review.navigate(direction);
    }
  }

  private complete(
    requestId: string,
    status: "succeeded" | "failed" | "cancelled",
    spokenSummary = "",
  ): void {
    if (this.completed.includes(requestId)) {
      return;
    }
    this.completed.push(requestId);
    if (this.completed.length > 32) {
      this.completed.shift();
    }
    const params: Record<string, unknown> = { requestId, status };
    if (spokenSummary.length > 0) {
      params.spokenSummary = spokenSummary.slice(0, 160);
    }
    this.bridge()?.sendNotification("voice.complete", params);
  }

  public dispose(): void {
    void this.provider.cancel();
  }
}
