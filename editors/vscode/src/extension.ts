import * as vscode from "vscode";

import { VsCodeCliAgentProvider } from "./agent/agentProvider";
import {
  type BridgeNotification,
  ProtocolError,
  booleanParam,
  numberParam,
  stringParam,
} from "./bridge/messages";
import { BridgeServer, type BridgeServerOptions } from "./bridge/server";
import { EditorActions } from "./editor/editorActions";
import { SemanticSelectionService } from "./editor/semanticSelection";
import { RequestCoordinator } from "./request/requestCoordinator";
import { ReviewNavigator } from "./review/reviewNavigator";
import { StatusPresenter } from "./ui/status";

let runtime: ExtensionRuntime | undefined;

function bridgeOptions(): BridgeServerOptions {
  const configuration = vscode.workspace.getConfiguration("gazemotion.bridge");
  return {
    host: configuration.get<string>("host", "127.0.0.1"),
    port: configuration.get<number>("port", 8765),
    sessionToken: configuration.get<string>("sessionToken", ""),
    maxMessageBytes: configuration.get<number>("maxMessageBytes", 262_144),
  };
}

class ExtensionRuntime implements vscode.Disposable {
  private bridge: BridgeServer | undefined;
  private paused = false;
  private readonly output = vscode.window.createOutputChannel("GazeMotion", {
    log: true,
  });
  private readonly status = new StatusPresenter();
  private readonly selection = new SemanticSelectionService((message) =>
    this.report(message),
  );
  private readonly editor = new EditorActions((message) =>
    this.report(message),
  );
  private readonly review = new ReviewNavigator((message) =>
    this.report(message),
  );
  private readonly agent = new VsCodeCliAgentProvider(this.output);
  private readonly requests = new RequestCoordinator(
    this.selection,
    this.review,
    this.agent,
    this.output,
    (message) => this.report(message),
  );

  public constructor(context: vscode.ExtensionContext) {
    context.subscriptions.push(
      this.output,
      this.status,
      this.selection,
      this.review,
      vscode.commands.registerCommand("gazemotion.startBridge", () =>
        this.startBridge(),
      ),
      vscode.commands.registerCommand("gazemotion.stopBridge", () =>
        this.stopBridge(),
      ),
      vscode.commands.registerCommand("gazemotion.nextChange", () =>
        this.review.navigate(1),
      ),
      vscode.commands.registerCommand("gazemotion.previousChange", () =>
        this.review.navigate(-1),
      ),
      vscode.commands.registerCommand("gazemotion.cancel", () => {
        this.selection.cancel();
        this.requests.cancel();
      }),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("gazemotion.bridge")) {
          void this.restartBridge();
        }
      }),
    );
  }

  private report(message: string): void {
    this.output.info(message);
    this.status.setDetail(message);
    this.bridge?.sendStatus(message);
  }

  private async dispatch(notification: BridgeNotification): Promise<void> {
    if (
      this.paused &&
      !["control.pause", "request.cancel", "selection.cancel"].includes(
        notification.method,
      )
    ) {
      return;
    }
    switch (notification.method) {
      case "review.navigate":
        await this.review.navigate(
          numberParam(notification.params, "direction"),
        );
        return;
      case "editor.scroll":
        await this.editor.scroll(numberParam(notification.params, "lines"));
        return;
      case "selection.arm":
        this.selection.arm(numberParam(notification.params, "timeoutMs"));
        return;
      case "selection.cancel":
        this.selection.cancel();
        return;
      case "request.preview":
        this.requests.preview(stringParam(notification.params, "transcript"));
        return;
      case "request.submit":
        await this.requests.submit();
        return;
      case "request.cancel":
        this.requests.cancel();
        return;
      case "control.pause":
        this.paused = booleanParam(notification.params, "paused");
        this.status.setPaused(this.paused);
        if (this.paused) {
          this.selection.cancel();
        }
        return;
      default:
        throw new ProtocolError(
          `Unsupported bridge method '${notification.method}'`,
        );
    }
  }

  public async startBridge(): Promise<void> {
    if (this.bridge !== undefined) {
      return;
    }
    const bridge = new BridgeServer(
      bridgeOptions(),
      (notification) => this.dispatch(notification),
      (connected, detail) => {
        this.output.info(detail);
        this.status.setBridge(connected, detail);
      },
    );
    this.bridge = bridge;
    try {
      await bridge.start();
    } catch (error: unknown) {
      this.bridge = undefined;
      const detail =
        error instanceof Error ? error.message : "unknown bridge error";
      this.output.error(detail);
      this.status.setBridge(false, detail);
      void vscode.window.showErrorMessage(
        `GazeMotion bridge could not start: ${detail}`,
      );
    }
  }

  public async stopBridge(): Promise<void> {
    const bridge = this.bridge;
    this.bridge = undefined;
    if (bridge !== undefined) {
      await bridge.stop();
    }
  }

  private async restartBridge(): Promise<void> {
    await this.stopBridge();
    await this.startBridge();
  }

  public dispose(): void {
    void this.stopBridge();
  }
}

export async function activate(
  context: vscode.ExtensionContext,
): Promise<void> {
  runtime = new ExtensionRuntime(context);
  context.subscriptions.push(runtime);
  await runtime.startBridge();
}

export async function deactivate(): Promise<void> {
  const active = runtime;
  runtime = undefined;
  if (active !== undefined) {
    await active.stopBridge();
  }
}
