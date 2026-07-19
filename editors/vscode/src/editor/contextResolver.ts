import * as vscode from "vscode";

import type {
  SelectionContext,
  SemanticSelectionService,
} from "./semanticSelection";

export type EditTargetKind =
  | "gesture-selection"
  | "manual-selection"
  | "named-symbol"
  | "cursor-symbol"
  | "active-file";

export interface ResolvedEditTarget extends SelectionContext {
  readonly kind: EditTargetKind;
  readonly relativePath: string;
  readonly languageId: string;
  readonly source: string;
  readonly imports: string;
  readonly label: string;
}

interface FlatSymbol {
  readonly name: string;
  readonly kind: vscode.SymbolKind;
  readonly range: vscode.Range;
}

function flattenSymbols(
  symbols: readonly vscode.DocumentSymbol[],
): FlatSymbol[] {
  const flattened: FlatSymbol[] = [];
  const visit = (symbol: vscode.DocumentSymbol): void => {
    flattened.push({
      name: symbol.name,
      kind: symbol.kind,
      range: symbol.range,
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

function rangeSize(document: vscode.TextDocument, range: vscode.Range): number {
  return document.offsetAt(range.end) - document.offsetAt(range.start);
}

function explicitSymbol(instruction: string): string | undefined {
  const match =
    /\b(?:function|class)\s+[`"']?([\p{L}_$][\p{L}\p{N}_$.-]*)/iu.exec(
      instruction,
    );
  return match?.[1];
}

function collectImports(document: vscode.TextDocument): string {
  const lines: string[] = [];
  const limit = Math.min(document.lineCount, 200);
  let multiline = false;
  for (let line = 0; line < limit; line += 1) {
    const text = document.lineAt(line).text;
    const beginsImport =
      /^\s*(?:import\b|from\b.+\bimport\b|using\b|#include\b|package\b|require\s*\()/u.test(
        text,
      );
    if (beginsImport || multiline) {
      lines.push(text);
      const trimmed = text.trimEnd();
      multiline =
        /(?:\\|,|\(|\{|\[)$/u.test(trimmed) ||
        (multiline && !/[;)}\]]$/u.test(trimmed));
    }
  }
  return lines.join("\n").slice(0, 32_000);
}

export class EditContextResolver {
  public constructor(
    private readonly semanticSelection: SemanticSelectionService,
  ) {}

  public async resolve(instruction: string): Promise<ResolvedEditTarget> {
    const editor = vscode.window.activeTextEditor;
    if (editor === undefined) {
      throw new Error("Open a text editor before asking Chudvis to edit code");
    }
    const document = editor.document;
    const gesture = this.semanticSelection.context();
    if (gesture?.uri.toString() === document.uri.toString()) {
      return this.target(
        document,
        gesture.range,
        "gesture-selection",
        gesture.symbolName,
      );
    }
    if (!editor.selection.isEmpty) {
      return this.target(
        document,
        new vscode.Range(editor.selection.start, editor.selection.end),
        "manual-selection",
      );
    }

    const provided = await vscode.commands.executeCommand<
      vscode.DocumentSymbol[] | undefined
    >("vscode.executeDocumentSymbolProvider", document.uri);
    const symbols = flattenSymbols(provided ?? []);
    const named = explicitSymbol(instruction);
    if (named !== undefined) {
      const matches = symbols.filter(
        (symbol) =>
          symbol.name.localeCompare(named, undefined, {
            sensitivity: "accent",
          }) === 0,
      );
      if (matches.length === 1 && matches[0] !== undefined) {
        return this.target(
          document,
          matches[0].range,
          "named-symbol",
          matches[0].name,
        );
      }
      if (matches.length > 1) {
        throw new Error(
          `More than one symbol named '${named}' exists in the active file`,
        );
      }
    }

    const cursor = editor.selection.active;
    const enclosing = symbols
      .filter((symbol) => symbol.range.contains(cursor))
      .sort(
        (left, right) =>
          rangeSize(document, left.range) - rangeSize(document, right.range),
      )[0];
    if (enclosing !== undefined) {
      return this.target(
        document,
        enclosing.range,
        "cursor-symbol",
        enclosing.name,
      );
    }
    const end = document.positionAt(document.getText().length);
    return this.target(
      document,
      new vscode.Range(new vscode.Position(0, 0), end),
      "active-file",
    );
  }

  private target(
    document: vscode.TextDocument,
    range: vscode.Range,
    kind: EditTargetKind,
    symbolName?: string,
  ): ResolvedEditTarget {
    const source = document.getText(range);
    if (source.length > 200_000) {
      throw new Error(
        "The resolved edit target is too large for voice editing; select a smaller symbol",
      );
    }
    const relativePath = vscode.workspace.asRelativePath(document.uri, false);
    const label =
      symbolName === undefined
        ? relativePath
        : `${symbolName} in ${relativePath}`;
    return {
      uri: document.uri,
      range,
      documentVersion: document.version,
      symbolName,
      kind,
      relativePath,
      languageId: document.languageId,
      source,
      imports: collectImports(document),
      label,
    };
  }
}
