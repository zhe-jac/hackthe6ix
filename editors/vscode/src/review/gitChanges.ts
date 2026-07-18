import { execFile } from "node:child_process";
import { promisify } from "node:util";

import * as vscode from "vscode";

import { wslDistribution } from "../platform/wslPaths";
import { parsePorcelain } from "./porcelain";

const execFileAsync = promisify(execFile);

export async function collectGitChanges(): Promise<vscode.Uri[]> {
  const results: vscode.Uri[] = [];
  for (const folder of vscode.workspace.workspaceFolders ?? []) {
    let command: string;
    let args: string[];
    if (folder.uri.scheme === "file") {
      command = "git";
      args = ["-C", folder.uri.fsPath];
    } else {
      const distribution = wslDistribution(folder.uri.authority);
      if (folder.uri.scheme !== "vscode-remote" || distribution === undefined) {
        continue;
      }
      command = "wsl.exe";
      args = ["-d", distribution, "--", "git", "-C", folder.uri.path];
    }
    args.push("status", "--porcelain=v1", "-z", "--untracked-files=all");
    if (command === "wsl.exe" && process.platform !== "win32") {
      continue;
    }
    try {
      const { stdout } = await execFileAsync(command, args, {
        encoding: "utf8",
        maxBuffer: 4 * 1024 * 1024,
        windowsHide: true,
      });
      for (const path of parsePorcelain(stdout)) {
        results.push(vscode.Uri.joinPath(folder.uri, path));
      }
    } catch {
      // A workspace folder does not have to be a Git repository.
    }
  }
  return results;
}
