import * as vscode from "vscode";

import type { ResolvedEditTarget } from "../editor/contextResolver";
import { SafeWorkspace } from "../workspace/safeWorkspace";
import type { EditProposal, ProposedTextEdit } from "./proposal";
import {
  assertNonOverlapping,
  matchesUndoGuard,
  uniqueTextRange,
} from "./textValidation";

const DEFAULT_MAX_CHANGE_CHARACTERS = 100_000;
const MAX_EXPANDED_FILES = 3;

export interface ValidatedOperation {
  readonly proposal: ProposedTextEdit;
  readonly uri: vscode.Uri;
  readonly relativePath: string;
  readonly range: vscode.Range;
  readonly startOffset: number;
  readonly endOffset: number;
  readonly documentVersion: number;
  readonly withinTarget: boolean;
}

export interface ReviewDocument {
  readonly uri: vscode.Uri;
  readonly relativePath: string;
  readonly originalText: string;
  readonly proposedText: string;
  readonly ranges: readonly vscode.Range[];
}

export interface ValidatedEditPlan {
  readonly requestId: string;
  readonly target: ResolvedEditTarget;
  readonly operations: readonly ValidatedOperation[];
  readonly reviewDocuments: readonly ReviewDocument[];
  readonly files: readonly string[];
  readonly changeCount: number;
  readonly totalChangeCharacters: number;
  readonly requiresApproval: boolean;
}

export interface AppliedEditResult {
  readonly files: readonly string[];
  readonly changeCount: number;
  readonly summary: string;
}

export interface CodeEditService {
  readonly canUndo: boolean;
  validate(
    requestId: string,
    target: ResolvedEditTarget,
    proposal: EditProposal,
  ): Promise<ValidatedEditPlan>;
  apply(plan: ValidatedEditPlan): Promise<AppliedEditResult>;
  undo(): Promise<readonly string[]>;
}

interface UndoDocument {
  readonly uri: vscode.Uri;
  readonly relativePath: string;
  readonly originalText: string;
  readonly appliedText: string;
  readonly appliedVersion: number;
}

interface UndoRecord {
  readonly documents: readonly UndoDocument[];
}

interface DocumentGroup {
  readonly document: vscode.TextDocument;
  readonly relativePath: string;
  readonly originalText: string;
  readonly operations: ValidatedOperation[];
}

function applyOperations(
  text: string,
  operations: readonly ValidatedOperation[],
): string {
  let result = text;
  const descending = [...operations].sort(
    (left, right) => right.startOffset - left.startOffset,
  );
  for (const operation of descending) {
    result =
      result.slice(0, operation.startOffset) +
      operation.proposal.replacementText +
      result.slice(operation.endOffset);
  }
  return result;
}

function resultRanges(
  proposedText: string,
  operations: readonly ValidatedOperation[],
): readonly vscode.Range[] {
  const positionAt = (offset: number): vscode.Position => {
    const prefix = proposedText.slice(
      0,
      Math.max(0, Math.min(offset, proposedText.length)),
    );
    const lines = prefix.split(/\r\n|\r|\n/u);
    return new vscode.Position(lines.length - 1, lines.at(-1)?.length ?? 0);
  };
  let delta = 0;
  return [...operations]
    .sort((left, right) => left.startOffset - right.startOffset)
    .map((operation) => {
      const start = operation.startOffset + delta;
      const end = start + operation.proposal.replacementText.length;
      delta +=
        operation.proposal.replacementText.length -
        (operation.endOffset - operation.startOffset);
      return new vscode.Range(positionAt(start), positionAt(end));
    });
}

export class EditService implements CodeEditService {
  private undoRecord: UndoRecord | undefined;

  public constructor(private readonly workspace: SafeWorkspace) {}

  public get canUndo(): boolean {
    return this.undoRecord !== undefined;
  }

  public async validate(
    requestId: string,
    target: ResolvedEditTarget,
    proposal: EditProposal,
  ): Promise<ValidatedEditPlan> {
    const targetDocument = await vscode.workspace.openTextDocument(target.uri);
    if (targetDocument.version !== target.documentVersion) {
      throw new Error(
        "The resolved edit target changed while Chudvis was working",
      );
    }
    const groups = new Map<string, DocumentGroup>();
    const operations: ValidatedOperation[] = [];
    let totalChangeCharacters = 0;

    for (const proposed of proposal.edits) {
      const file = await this.workspace.resolveFile(proposed.path);
      const document = await vscode.workspace.openTextDocument(file.uri);
      const original = document.getText();
      if (original.includes("\0")) {
        throw new Error(
          `Chudvis cannot edit binary file '${file.relativePath}'`,
        );
      }
      if (original.length > 512 * 1024) {
        throw new Error(
          `Chudvis cannot edit oversized file '${file.relativePath}'`,
        );
      }
      if (proposed.originalText === proposed.replacementText) {
        throw new Error(
          `Proposed edit in '${file.relativePath}' does not change the text`,
        );
      }
      let match: { readonly startOffset: number; readonly endOffset: number };
      try {
        match = uniqueTextRange(original, proposed.originalText);
      } catch {
        throw new Error(
          `originalText in '${file.relativePath}' must occur exactly once`,
        );
      }
      const { startOffset, endOffset } = match;
      const range = new vscode.Range(
        document.positionAt(startOffset),
        document.positionAt(endOffset),
      );
      const sameDocument = file.uri.toString() === target.uri.toString();
      const targetStart = targetDocument.offsetAt(target.range.start);
      const targetEnd = targetDocument.offsetAt(target.range.end);
      const withinTarget =
        sameDocument && startOffset >= targetStart && endOffset <= targetEnd;
      const operation: ValidatedOperation = {
        proposal: proposed,
        uri: file.uri,
        relativePath: file.relativePath,
        range,
        startOffset,
        endOffset,
        documentVersion: document.version,
        withinTarget,
      };
      operations.push(operation);
      totalChangeCharacters +=
        proposed.originalText.length + proposed.replacementText.length;
      const key = file.uri.toString();
      const group = groups.get(key);
      if (group === undefined) {
        groups.set(key, {
          document,
          relativePath: file.relativePath,
          originalText: original,
          operations: [operation],
        });
      } else {
        group.operations.push(operation);
      }
    }

    const configuredLimit = vscode.workspace
      .getConfiguration("chudvis.edits")
      .get<number>("maxChangeCharacters", DEFAULT_MAX_CHANGE_CHARACTERS);
    const maximum = Math.max(1_000, Math.min(250_000, configuredLimit));
    if (totalChangeCharacters > maximum) {
      throw new Error(
        "The requested change is too large for Chudvis; use a full coding agent",
      );
    }
    if (groups.size > MAX_EXPANDED_FILES) {
      throw new Error(
        "Chudvis voice edits are limited to three files; use a full coding agent",
      );
    }

    for (const group of groups.values()) {
      assertNonOverlapping(group.operations, group.relativePath);
    }

    const reviewDocuments = [...groups.values()].map(
      (group): ReviewDocument => {
        const proposedText = applyOperations(
          group.originalText,
          group.operations,
        );
        return {
          uri: group.document.uri,
          relativePath: group.relativePath,
          originalText: group.originalText,
          proposedText,
          ranges: resultRanges(proposedText, group.operations),
        };
      },
    );
    const files = reviewDocuments.map((document) => document.relativePath);
    return {
      requestId,
      target,
      operations,
      reviewDocuments,
      files,
      changeCount: operations.length,
      totalChangeCharacters,
      requiresApproval: operations.some((operation) => !operation.withinTarget),
    };
  }

  public async apply(plan: ValidatedEditPlan): Promise<AppliedEditResult> {
    for (const review of plan.reviewDocuments) {
      const document = await vscode.workspace.openTextDocument(review.uri);
      const expectedVersion = plan.operations.find(
        (operation) => operation.uri.toString() === review.uri.toString(),
      )?.documentVersion;
      if (
        document.version !== expectedVersion ||
        document.getText() !== review.originalText
      ) {
        throw new Error(
          `'${review.relativePath}' changed during Chudvis review`,
        );
      }
    }

    const edit = new vscode.WorkspaceEdit();
    for (const operation of plan.operations) {
      edit.replace(
        operation.uri,
        operation.range,
        operation.proposal.replacementText,
      );
    }
    if (!(await vscode.workspace.applyEdit(edit))) {
      throw new Error("VS Code could not apply the Chudvis edit atomically");
    }

    const undoDocuments: UndoDocument[] = [];
    for (const review of plan.reviewDocuments) {
      const document = await vscode.workspace.openTextDocument(review.uri);
      if (document.getText() !== review.proposedText) {
        throw new Error(
          `Applied content for '${review.relativePath}' did not match the proposal`,
        );
      }
      undoDocuments.push({
        uri: review.uri,
        relativePath: review.relativePath,
        originalText: review.originalText,
        appliedText: review.proposedText,
        appliedVersion: document.version,
      });
    }
    this.undoRecord = { documents: undoDocuments };
    return {
      files: plan.files,
      changeCount: plan.changeCount,
      summary: deterministicEditSummary(plan),
    };
  }

  public async undo(): Promise<readonly string[]> {
    const record = this.undoRecord;
    if (record === undefined) {
      throw new Error("There is no Chudvis edit to undo");
    }
    const documents: vscode.TextDocument[] = [];
    for (const expected of record.documents) {
      const document = await vscode.workspace.openTextDocument(expected.uri);
      if (
        !matchesUndoGuard(
          document.getText(),
          document.version,
          expected.appliedText,
          expected.appliedVersion,
        )
      ) {
        throw new Error(
          `'${expected.relativePath}' changed after the Chudvis edit; Undo was refused`,
        );
      }
      documents.push(document);
    }
    const edit = new vscode.WorkspaceEdit();
    for (let index = 0; index < record.documents.length; index += 1) {
      const expected = record.documents[index];
      const document = documents[index];
      if (expected !== undefined && document !== undefined) {
        edit.replace(
          expected.uri,
          new vscode.Range(
            new vscode.Position(0, 0),
            document.positionAt(document.getText().length),
          ),
          expected.originalText,
        );
      }
    }
    if (!(await vscode.workspace.applyEdit(edit))) {
      throw new Error("VS Code could not undo the Chudvis edit atomically");
    }
    this.undoRecord = undefined;
    return record.documents.map((document) => document.relativePath);
  }
}

export function deterministicEditSummary(plan: ValidatedEditPlan): string {
  if (plan.target.symbolName !== undefined && plan.files.length === 1) {
    return `Updated ${plan.target.symbolName} in ${plan.files[0] ?? "the active file"}.`.slice(
      0,
      160,
    );
  }
  const files = plan.files.length;
  const changes = plan.changeCount;
  return `Applied ${changes} ${changes === 1 ? "change" : "changes"} across ${files} ${files === 1 ? "file" : "files"}.`;
}
