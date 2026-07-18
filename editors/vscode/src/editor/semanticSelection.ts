import * as vscode from "vscode";

export interface SelectionContext {
  readonly uri: vscode.Uri;
  readonly range: vscode.Range;
  readonly documentVersion: number;
  readonly symbolName: string | undefined;
}

interface SymbolRange {
  readonly name: string;
  readonly range: vscode.Range;
}

function isDocumentSymbol(
  symbol: vscode.DocumentSymbol | vscode.SymbolInformation,
): symbol is vscode.DocumentSymbol {
  return "range" in symbol && "children" in symbol;
}

function flattenSymbols(
  symbols: readonly (vscode.DocumentSymbol | vscode.SymbolInformation)[],
): SymbolRange[] {
  const flattened: SymbolRange[] = [];
  const visit = (
    symbol: vscode.DocumentSymbol | vscode.SymbolInformation,
  ): void => {
    if (isDocumentSymbol(symbol)) {
      flattened.push({ name: symbol.name, range: symbol.range });
      for (const child of symbol.children) {
        visit(child);
      }
    } else {
      flattened.push({ name: symbol.name, range: symbol.location.range });
    }
  };
  for (const symbol of symbols) {
    visit(symbol);
  }
  return flattened;
}

function rangeSize(range: vscode.Range): number {
  const lines = range.end.line - range.start.line;
  return lines * 1_000_000 + range.end.character - range.start.character;
}

export class SemanticSelectionService implements vscode.Disposable {
  private armedUntil = 0;
  private armTimer: NodeJS.Timeout | undefined;
  private current: SelectionContext | undefined;
  private readonly listener: vscode.Disposable;
  private readonly decoration = vscode.window.createTextEditorDecorationType({
    backgroundColor: new vscode.ThemeColor(
      "editor.wordHighlightStrongBackground",
    ),
    border: "1px solid",
    borderColor: new vscode.ThemeColor("focusBorder"),
    isWholeLine: false,
  });

  public constructor(private readonly status: (message: string) => void) {
    this.listener = vscode.window.onDidChangeTextEditorSelection((event) => {
      if (
        event.kind !== vscode.TextEditorSelectionChangeKind.Mouse ||
        Date.now() > this.armedUntil
      ) {
        return;
      }
      this.clearArm();
      const position = event.selections[0]?.active;
      if (position !== undefined) {
        void this.snap(event.textEditor, position);
      }
    });
  }

  public arm(timeoutMs: number): void {
    this.clearArm();
    const bounded = Math.max(100, Math.min(5_000, Math.trunc(timeoutMs)));
    this.armedUntil = Date.now() + bounded;
    this.armTimer = setTimeout(() => {
      this.clearArm();
      this.status("Semantic selection expired");
    }, bounded);
    this.status("Semantic selection armed");
  }

  public cancel(): void {
    this.clearArm();
  }

  private clearArm(): void {
    this.armedUntil = 0;
    if (this.armTimer !== undefined) {
      clearTimeout(this.armTimer);
      this.armTimer = undefined;
    }
  }

  private async snap(
    editor: vscode.TextEditor,
    position: vscode.Position,
  ): Promise<void> {
    const document = editor.document;
    const provided = await vscode.commands.executeCommand<
      vscode.DocumentSymbol[] | vscode.SymbolInformation[] | undefined
    >("vscode.executeDocumentSymbolProvider", document.uri);
    const candidates = flattenSymbols(provided ?? [])
      .filter((symbol) => symbol.range.contains(position))
      .sort((left, right) => rangeSize(left.range) - rangeSize(right.range));
    const selected = candidates[0];
    const range = selected?.range ?? document.lineAt(position.line).range;
    editor.selection = new vscode.Selection(range.start, range.end);
    editor.revealRange(
      range,
      vscode.TextEditorRevealType.InCenterIfOutsideViewport,
    );
    editor.setDecorations(this.decoration, [range]);
    this.current = {
      uri: document.uri,
      range,
      documentVersion: document.version,
      symbolName: selected?.name,
    };
    const label = selected?.name ?? `line ${range.start.line + 1}`;
    this.status(`Selected ${label}`);
  }

  public context(): SelectionContext | undefined {
    const current = this.current;
    if (current === undefined) {
      return undefined;
    }
    const document = vscode.workspace.textDocuments.find(
      (candidate) => candidate.uri.toString() === current.uri.toString(),
    );
    if (
      document !== undefined &&
      document.version !== current.documentVersion
    ) {
      return undefined;
    }
    return current;
  }

  public dispose(): void {
    this.clearArm();
    this.listener.dispose();
    this.decoration.dispose();
  }
}
