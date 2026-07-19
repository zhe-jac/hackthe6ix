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
import { BackboardProvider } from "./model/backboardProvider";
import { ChudvisCoordinator } from "./request/chudvisCoordinator";
import { RequestCoordinator } from "./request/requestCoordinator";
import { EditReviewPresenter } from "./review/editReview";
import { ReviewNavigator } from "./review/reviewNavigator";
import { ChudvisSidebar } from "./ui/chudvisSidebar";
import { StatusPresenter } from "./ui/status";
import { parseChudvisInbound } from "./voice/protocol";

let runtime: ExtensionRuntime | undefined;

function bridgeOptions(): BridgeServerOptions {
  const configuration = vscode.workspace.getConfiguration("chudvis.bridge");
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
  private readonly output = vscode.window.createOutputChannel("Chudvis", {
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
  private readonly editReview = new EditReviewPresenter((message) =>
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
  private readonly provider: BackboardProvider;
  private readonly sidebar: ChudvisSidebar;
  private readonly chudvis: ChudvisCoordinator;

  public constructor(private readonly context: vscode.ExtensionContext) {
    this.provider = new BackboardProvider(context, this.output);
    const holder: { coordinator?: ChudvisCoordinator } = {};
    this.sidebar = new ChudvisSidebar((action) => {
      if (holder.coordinator !== undefined) {
        void holder.coordinator.handleAction(action);
      }
    });
    const coordinator = new ChudvisCoordinator(
      this.selection,
      this.provider,
      this.review,
      this.editReview,
      this.sidebar,
      this.status,
      this.output,
      () => this.bridge,
      (message) => this.report(message),
    );
    holder.coordinator = coordinator;
    this.chudvis = coordinator;
    context.subscriptions.push(
      this.output,
      this.status,
      this.selection,
      this.review,
      this.editReview,
      this.sidebar,
      this.chudvis,
      vscode.window.registerWebviewViewProvider(
        ChudvisSidebar.viewType,
        this.sidebar,
      ),
      vscode.commands.registerCommand("chudvis.startBridge", () =>
        this.startBridge(),
      ),
      vscode.commands.registerCommand("chudvis.stopBridge", () =>
        this.stopBridge(),
      ),
      vscode.commands.registerCommand("chudvis.nextChange", () =>
        this.chudvis.navigateReview(1),
      ),
      vscode.commands.registerCommand("chudvis.previousChange", () =>
        this.chudvis.navigateReview(-1),
      ),
      vscode.commands.registerCommand("chudvis.cancel", () => {
        this.selection.cancel();
        this.requests.cancel();
        void this.chudvis.cancel(true);
      }),
      vscode.commands.registerCommand("chudvis.configureBackboardKey", () =>
        this.provider.configureApiKey(),
      ),
      vscode.commands.registerCommand("chudvis.clearBackboardKey", () =>
        this.provider.clearApiKey(),
      ),
      vscode.commands.registerCommand("chudvis.clearEditingMemory", () =>
        this.chudvis.handleAction("clearMemory"),
      ),
      vscode.commands.registerCommand("chudvis.undo", () =>
        this.chudvis.handleAction("undo"),
      ),
      vscode.commands.registerCommand("chudvis.openChanges", () =>
        this.chudvis.handleAction("openChanges"),
      ),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("chudvis.bridge")) {
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
    const voice = parseChudvisInbound(notification);
    if (voice !== undefined) {
      await this.chudvis.handleInbound(voice);
      return;
    }
    if (
      this.paused &&
      ![
        "control.pause",
        "request.cancel",
        "selection.cancel",
        "edit.cancel",
      ].includes(notification.method)
    ) {
      return;
    }
    switch (notification.method) {
      case "review.navigate":
        await this.chudvis.navigateReview(
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
        if (
          vscode.workspace
            .getConfiguration("chudvis")
            .get<string>("provider", "backboard") === "legacy-vscode-cli"
        ) {
          await this.requests.submit();
        } else {
          await this.chudvis.handleLegacyRequest(this.requests.consume());
        }
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
    const disclosed = this.context.globalState.get<boolean>(
      "chudvis.cloudDisclosureAccepted",
      false,
    );
    if (!disclosed) {
      const accepted = await vscode.window.showInformationMessage(
        "Chudvis sends microphone audio only after the wake word to ElevenLabs, and sends the resolved source/context to Backboard for questions and edits.",
        { modal: true },
        "Continue",
      );
      if (accepted !== "Continue") {
        this.status.setDetail(
          "Cloud disclosure not accepted; bridge not started",
        );
        return;
      }
      await this.context.globalState.update(
        "chudvis.cloudDisclosureAccepted",
        true,
      );
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
        `Chudvis bridge could not start: ${detail}`,
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
