import * as vscode from "vscode";

import {
  isExcludedWorkspacePath,
  normalizeRelativePath,
  WORKSPACE_FILE_EXCLUDE,
} from "./pathPolicy";

export {
  isExcludedWorkspacePath,
  normalizeRelativePath,
  WORKSPACE_FILE_EXCLUDE,
} from "./pathPolicy";

export interface SafeWorkspaceFile {
  readonly folder: vscode.WorkspaceFolder;
  readonly uri: vscode.Uri;
  readonly relativePath: string;
}

export class SafeWorkspace {
  public async resolveFile(relativePath: string): Promise<SafeWorkspaceFile> {
    const normalized = normalizeRelativePath(relativePath);
    if (isExcludedWorkspacePath(normalized)) {
      throw new Error(
        `Workspace path '${normalized}' is excluded from Chudvis`,
      );
    }
    const folders = vscode.workspace.workspaceFolders ?? [];
    const matches: SafeWorkspaceFile[] = [];
    for (const folder of folders) {
      const prefix = `${folder.name}/`;
      const folderRelative = normalized.startsWith(prefix)
        ? normalized.slice(prefix.length)
        : normalized;
      if (
        folderRelative.length === 0 ||
        isExcludedWorkspacePath(folderRelative)
      ) {
        continue;
      }
      const uri = vscode.Uri.joinPath(folder.uri, ...folderRelative.split("/"));
      try {
        const stat = await vscode.workspace.fs.stat(uri);
        if (
          (stat.type & vscode.FileType.File) !== 0 &&
          (stat.type & vscode.FileType.SymbolicLink) === 0
        ) {
          matches.push({ folder, uri, relativePath: normalized });
        }
      } catch {
        // A missing candidate in one workspace root is expected.
      }
    }
    if (matches.length === 0) {
      throw new Error(`Workspace file '${normalized}' does not exist`);
    }
    if (matches.length > 1) {
      throw new Error(
        `Workspace file '${normalized}' is ambiguous across roots`,
      );
    }
    const match = matches[0];
    if (match === undefined) {
      throw new Error("Workspace file resolution failed");
    }
    return match;
  }

  public async readText(
    relativePath: string,
    startLine?: number,
    endLine?: number,
  ): Promise<{ readonly path: string; readonly content: string }> {
    const file = await this.resolveFile(relativePath);
    const stat = await vscode.workspace.fs.stat(file.uri);
    if (stat.size > 512 * 1024) {
      throw new Error(
        `Workspace file '${file.relativePath}' exceeds the read limit`,
      );
    }
    const bytes = await vscode.workspace.fs.readFile(file.uri);
    if (bytes.includes(0)) {
      throw new Error(
        `Workspace file '${file.relativePath}' appears to be binary`,
      );
    }
    const content = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
    const lines = content.split(/\r\n|\r|\n/u);
    const start = Math.max(0, Math.trunc(startLine ?? 1) - 1);
    const end = Math.min(lines.length, Math.trunc(endLine ?? lines.length));
    if (end < start || end - start > 500) {
      throw new Error("Workspace line range is invalid or exceeds 500 lines");
    }
    const selected = lines.slice(start, end).join("\n");
    if (selected.length > 64_000) {
      throw new Error("Workspace read result exceeds 64,000 characters");
    }
    return { path: file.relativePath, content: selected };
  }

  public async listFiles(pattern = "**/*"): Promise<readonly string[]> {
    const boundedPattern = pattern.trim();
    if (boundedPattern.length === 0 || boundedPattern.length > 200) {
      throw new Error("Workspace file pattern is invalid");
    }
    const uris = await vscode.workspace.findFiles(
      boundedPattern,
      WORKSPACE_FILE_EXCLUDE,
      201,
    );
    return uris
      .map((uri) => vscode.workspace.asRelativePath(uri, false))
      .filter((relative) => !isExcludedWorkspacePath(relative))
      .slice(0, 200);
  }

  public async findSymbols(query: string): Promise<readonly object[]> {
    const normalized = query.trim();
    if (normalized.length === 0 || normalized.length > 200) {
      throw new Error("Workspace symbol query is invalid");
    }
    const symbols = await vscode.commands.executeCommand<
      vscode.SymbolInformation[] | undefined
    >("vscode.executeWorkspaceSymbolProvider", normalized);
    return (symbols ?? []).slice(0, 50).map((symbol) => ({
      name: symbol.name,
      kind: vscode.SymbolKind[symbol.kind],
      path: vscode.workspace.asRelativePath(symbol.location.uri, false),
      line: symbol.location.range.start.line + 1,
    }));
  }
}
