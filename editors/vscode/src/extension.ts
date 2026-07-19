import * as vscode from "vscode";
import { createHash } from "node:crypto";

import { VsCodeCliAgentProvider } from "./agent/agentProvider";
import {
  type BridgeNotification,
  ProtocolError,
  booleanParam,
  numberParam,
  stringParam,
} from "./bridge/messages";
import { BridgeServer, type BridgeServerOptions } from "./bridge/server";
import { DiagnosticLog } from "./diagnostics/diagnosticLog";
import { DiagnosticPanel } from "./diagnostics/diagnosticPanel";
import { EditorActions } from "./editor/editorActions";
import { SemanticSelectionService } from "./editor/semanticSelection";
import { BackboardProvider } from "./model/backboardProvider";
import { ChudvisCoordinator } from "./request/chudvisCoordinator";
import { RequestCoordinator } from "./request/requestCoordinator";
import { EditReviewPresenter } from "./review/editReview";
import { ReviewNavigator } from "./review/reviewNavigator";
import { type RuntimeBridgeSettings, type RuntimeMode } from "./runtime/launch";
import { ChudvisRuntimeManager } from "./runtime/runtimeManager";
import { ChudvisSidebar } from "./ui/chudvisSidebar";
import { StatusPresenter } from "./ui/status";
import {
  ELEVENLABS_VOICE_PRESETS,
  getElevenLabsVoicePreset,
  isElevenLabsVoicePresetId,
  resolveElevenLabsPresetVoiceIds,
  type ElevenLabsVoicePresetId,
} from "./voice/elevenLabsVoicePresets";
import { parseChudvisInbound } from "./voice/protocol";

let runtime: ExtensionRuntime | undefined;
const ELEVENLABS_SECRET_KEY = "chudvis.elevenLabsApiKey";
const ELEVENLABS_ENVIRONMENT_KEY = "ELEVENLABS_API_KEY";
const ELEVENLABS_PRESET_VOICE_IDS_KEY =
  "chudvis.elevenLabsNamedPresetVoiceIdsV1";
const ELEVENLABS_ACCOUNT_FINGERPRINT_KEY =
  "chudvis.elevenLabsAccountFingerprint";
const DEFAULT_ELEVENLABS_VOICE_ID = "";
const DEFAULT_ELEVENLABS_VOICE_PRESET: ElevenLabsVoicePresetId = "chud";

type CachedElevenLabsPresetVoiceIds = Readonly<
  Partial<Record<ElevenLabsVoicePresetId, string>>
>;

function bridgeOptions(): BridgeServerOptions {
  const configuration = vscode.workspace.getConfiguration("chudvis.bridge");
  return {
    host: configuration.get<string>("host", "127.0.0.1"),
    port: configuration.get<number>("port", 8765),
    sessionToken: configuration.get<string>("sessionToken", ""),
    maxMessageBytes: configuration.get<number>("maxMessageBytes", 262_144),
  };
}

function addressIsInUse(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "code" in error &&
    error.code === "EADDRINUSE"
  );
}

class ExtensionRuntime implements vscode.Disposable {
  private bridge: BridgeServer | undefined;
  private controlsStarting = false;
  private paused = false;
  private readonly output = vscode.window.createOutputChannel("Chudvis", {
    log: true,
  });
  private readonly diagnostics: DiagnosticLog;
  private readonly diagnosticPanel: DiagnosticPanel;
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
  private readonly perception: ChudvisRuntimeManager;

  public constructor(private readonly context: vscode.ExtensionContext) {
    this.diagnostics = new DiagnosticLog(context);
    this.diagnosticPanel = new DiagnosticPanel(this.diagnostics, () =>
      this.followDiagnostics(),
    );
    this.provider = new BackboardProvider(
      context,
      this.output,
      this.diagnostics,
    );
    const holder: { coordinator?: ChudvisCoordinator } = {};
    this.sidebar = new ChudvisSidebar((action) => {
      switch (action) {
        case "toggleControls":
          void this.toggleControls();
          return;
        case "testTracking":
          void this.startRuntimeMode("diagnostics");
          return;
        case "calibrate":
          void this.startRuntimeMode("calibrate");
          return;
        case "showDiagnostics":
          this.diagnosticPanel.show();
          return;
        case "configureBackboard":
          void this.configureBackboardApiKey();
          return;
        case "configureElevenLabs":
          void this.configureElevenLabsApiKey();
          return;
        case "configureElevenLabsVoice":
          void this.configureElevenLabsVoice();
          return;
        case "testElevenLabsVoice":
          this.testElevenLabsVoice();
          return;
      }
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
      this.diagnostics,
    );
    holder.coordinator = coordinator;
    this.chudvis = coordinator;
    this.perception = new ChudvisRuntimeManager(
      context,
      this.output,
      (detail) => this.report(detail),
      (mode, code) => this.runtimeExited(mode, code),
      () => this.secretRuntimeEnvironment(),
    );
    context.subscriptions.push(
      this.output,
      this.diagnosticPanel,
      this.diagnostics,
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
        this.startBridge(true),
      ),
      vscode.commands.registerCommand("chudvis.stopBridge", () =>
        this.stopEverything(),
      ),
      vscode.commands.registerCommand("chudvis.toggle", () =>
        this.toggleControls(),
      ),
      vscode.commands.registerCommand("chudvis.start", () =>
        this.startControls(true),
      ),
      vscode.commands.registerCommand("chudvis.stop", () =>
        this.stopControls(),
      ),
      vscode.commands.registerCommand("chudvis.calibrate", () =>
        this.startRuntimeMode("calibrate"),
      ),
      vscode.commands.registerCommand("chudvis.testTracking", () =>
        this.startRuntimeMode("diagnostics"),
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
        this.configureBackboardApiKey(),
      ),
      vscode.commands.registerCommand("chudvis.clearBackboardKey", () =>
        this.clearBackboardApiKey(),
      ),
      vscode.commands.registerCommand("chudvis.configureElevenLabsKey", () =>
        this.configureElevenLabsApiKey(),
      ),
      vscode.commands.registerCommand("chudvis.clearElevenLabsKey", () =>
        this.clearElevenLabsApiKey(),
      ),
      vscode.commands.registerCommand("chudvis.configureElevenLabsVoice", () =>
        this.configureElevenLabsVoice(),
      ),
      vscode.commands.registerCommand("chudvis.testElevenLabsVoice", () =>
        this.testElevenLabsVoice(),
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
      vscode.commands.registerCommand("chudvis.showDiagnostics", () =>
        this.diagnosticPanel.show(),
      ),
      vscode.commands.registerCommand("chudvis.followDiagnostics", () =>
        this.followDiagnostics(),
      ),
      vscode.workspace.onDidChangeConfiguration((event) => {
        if (event.affectsConfiguration("chudvis.bridge")) {
          void this.restartBridge();
        }
        if (
          event.affectsConfiguration("chudvis.runtime") &&
          this.perception.running
        ) {
          void this.perception.restart();
        }
        if (event.affectsConfiguration("chudvis.elevenLabs")) {
          void this.refreshServiceStatus();
        }
      }),
      this.perception,
    );
  }

  private runtimeExited(mode: RuntimeMode, code: number | null): void {
    this.setControlsRunning(false);
    if (code !== 0) {
      return;
    }
    if (mode === "calibrate") {
      this.report("Gaze calibration completed; Chudvis controls are stopped");
      const quality = this.perception.calibrationQuality();
      if (quality?.poor === true) {
        void vscode.window
          .showWarningMessage(
            `Gaze calibration quality is low (median ${quality.medianErrorPx.toFixed(0)} px, p95 ${quality.p95ErrorPx.toFixed(0)} px). Recalibrate before starting Chudvis.`,
            "Recalibrate Gaze",
          )
          .then((action) => {
            if (action === "Recalibrate Gaze") {
              void this.startRuntimeMode("calibrate");
            }
          });
      } else {
        const shortcut =
          process.platform === "darwin" ? "Cmd+Alt+G" : "Ctrl+Alt+G";
        void vscode.window.showInformationMessage(
          `Gaze calibration is ready. Press ${shortcut} to start Chudvis.`,
        );
      }
    } else if (mode === "diagnostics") {
      this.report("Tracking diagnostics closed; Chudvis controls are stopped");
    }
  }

  private report(message: string): void {
    this.output.info(message);
    this.diagnostics.record("status", "reported", { message });
    this.status.setDetail(message);
    this.bridge?.sendStatus(message);
  }

  private async savedElevenLabsApiKey(): Promise<string | undefined> {
    const value = await this.context.secrets.get(ELEVENLABS_SECRET_KEY);
    const key = value?.trim();
    return key === undefined || key.length === 0 ? undefined : key;
  }

  private inheritedElevenLabsApiKey(): string | undefined {
    const key = process.env[ELEVENLABS_ENVIRONMENT_KEY]?.trim();
    return key === undefined || key.length === 0 ? undefined : key;
  }

  private async secretRuntimeEnvironment(): Promise<
    Readonly<Record<string, string>>
  > {
    const key = await this.savedElevenLabsApiKey();
    const configuration =
      vscode.workspace.getConfiguration("chudvis.elevenLabs");
    const environment: Record<string, string> = {
      CHUDVIS_ELEVENLABS_TTS_ENABLED: String(
        configuration.get<boolean>("ttsEnabled", true),
      ),
      CHUDVIS_ELEVENLABS_VOICE_ID: configuration
        .get<string>("voiceId", DEFAULT_ELEVENLABS_VOICE_ID)
        .trim(),
    };
    if (key !== undefined) {
      environment[ELEVENLABS_ENVIRONMENT_KEY] = key;
    }
    return environment;
  }

  private async refreshServiceStatus(): Promise<void> {
    try {
      const [backboardConfigured, savedElevenLabs] = await Promise.all([
        this.provider.hasApiKey(),
        this.savedElevenLabsApiKey(),
      ]);
      const elevenLabsStatus =
        savedElevenLabs !== undefined
          ? "Key saved securely"
          : this.inheritedElevenLabsApiKey() !== undefined
            ? "Using VS Code host environment"
            : "Not configured";
      const voiceConfiguration =
        vscode.workspace.getConfiguration("chudvis.elevenLabs");
      const ttsEnabled = voiceConfiguration.get<boolean>("ttsEnabled", true);
      const presetId = this.configuredElevenLabsVoicePreset();
      const preset = getElevenLabsVoicePreset(presetId);
      const voiceId = voiceConfiguration
        .get<string>("voiceId", DEFAULT_ELEVENLABS_VOICE_ID)
        .trim();
      const presetVoiceId = this.elevenLabsPresetVoiceIds()[presetId];
      const voiceStatus = !ttsEnabled
        ? "Disabled"
        : voiceId.length > 0 && voiceId === presetVoiceId
          ? `Enabled · ${preset.label}`
          : `${preset.label} · resolves on first use`;
      this.sidebar.setServiceStatus(
        backboardConfigured ? "Key saved securely" : "Not configured",
        elevenLabsStatus,
        voiceStatus,
      );
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "secure storage unavailable";
      this.output.warn(`Could not read service credentials: ${detail}`);
      this.sidebar.setServiceStatus(
        "Status unavailable",
        "Status unavailable",
        "Status unavailable",
      );
    }
  }

  private async configureBackboardApiKey(): Promise<boolean> {
    try {
      const configured = await this.provider.configureApiKey();
      if (configured) {
        this.report("Backboard API key validated and saved securely");
        void vscode.window.showInformationMessage(
          "Backboard is configured for Chudvis voice actions, questions, and code edits.",
        );
      }
      return configured;
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "Backboard setup failed";
      this.report(detail);
      void vscode.window.showErrorMessage(`Chudvis Backboard setup: ${detail}`);
      return false;
    } finally {
      await this.refreshServiceStatus();
    }
  }

  private async clearBackboardApiKey(): Promise<void> {
    await this.provider.clearApiKey();
    await this.refreshServiceStatus();
    this.report("Backboard API key removed from VS Code secure storage");
  }

  private async configureElevenLabsApiKey(
    selectDefaultVoiceAfterSave = true,
  ): Promise<boolean> {
    const key = await vscode.window.showInputBox({
      title: "Configure ElevenLabs API key",
      prompt:
        'Stored securely by VS Code and passed only to Chudvis. The account must contain voices named exactly "CHUD" and "JARVIS".',
      password: true,
      ignoreFocusOut: true,
      validateInput: (value) =>
        value.trim().length < 8
          ? "Enter a valid ElevenLabs API key"
          : undefined,
    });
    if (key === undefined) {
      return false;
    }
    await this.context.secrets.store(ELEVENLABS_SECRET_KEY, key.trim());
    await this.synchronizeElevenLabsAccount(key.trim());
    await this.refreshServiceStatus();
    this.report("ElevenLabs API key saved securely for the native runtime");
    if (selectDefaultVoiceAfterSave) {
      try {
        await this.activateElevenLabsVoicePreset(
          DEFAULT_ELEVENLABS_VOICE_PRESET,
          key.trim(),
        );
      } catch (error: unknown) {
        const detail =
          error instanceof Error ? error.message : "voice lookup failed";
        this.report(`ElevenLabs default voice setup failed: ${detail}`);
        void vscode.window.showErrorMessage(
          `The ElevenLabs key was saved, but Chudvis could not select the default CHUD voice: ${detail}`,
        );
        return false;
      }
    }
    return true;
  }

  private async clearElevenLabsApiKey(): Promise<void> {
    await this.context.secrets.delete(ELEVENLABS_SECRET_KEY);
    await this.refreshServiceStatus();
    const inherited = this.inheritedElevenLabsApiKey() !== undefined;
    this.report(
      inherited
        ? "Saved ElevenLabs key removed; the VS Code host environment key remains active"
        : "ElevenLabs API key removed from VS Code secure storage",
    );
  }

  private async effectiveElevenLabsApiKey(): Promise<string | undefined> {
    return (
      (await this.savedElevenLabsApiKey()) ?? this.inheritedElevenLabsApiKey()
    );
  }

  private configuredElevenLabsVoicePreset(): ElevenLabsVoicePresetId {
    const value = vscode.workspace
      .getConfiguration("chudvis.elevenLabs")
      .get<unknown>("voicePreset", DEFAULT_ELEVENLABS_VOICE_PRESET);
    return isElevenLabsVoicePresetId(value)
      ? value
      : DEFAULT_ELEVENLABS_VOICE_PRESET;
  }

  private elevenLabsPresetVoiceIds(): CachedElevenLabsPresetVoiceIds {
    const value = this.context.globalState.get<unknown>(
      ELEVENLABS_PRESET_VOICE_IDS_KEY,
    );
    if (typeof value !== "object" || value === null || Array.isArray(value)) {
      return {};
    }
    const record = value as Record<string, unknown>;
    const result: Partial<Record<ElevenLabsVoicePresetId, string>> = {};
    for (const preset of ELEVENLABS_VOICE_PRESETS) {
      const voiceId = record[preset.id];
      if (
        typeof voiceId === "string" &&
        voiceId.length > 0 &&
        voiceId.length <= 100
      ) {
        result[preset.id] = voiceId;
      }
    }
    return result;
  }

  private async synchronizeElevenLabsAccount(apiKey: string): Promise<void> {
    const fingerprint = createHash("sha256")
      .update(apiKey)
      .digest("hex")
      .slice(0, 24);
    const previous = this.context.globalState.get<string>(
      ELEVENLABS_ACCOUNT_FINGERPRINT_KEY,
    );
    if (previous !== undefined && previous !== fingerprint) {
      await this.context.globalState.update(
        ELEVENLABS_PRESET_VOICE_IDS_KEY,
        {},
      );
      await vscode.workspace
        .getConfiguration("chudvis.elevenLabs")
        .update("voiceId", "", vscode.ConfigurationTarget.Global);
    }
    if (previous !== fingerprint) {
      await this.context.globalState.update(
        ELEVENLABS_ACCOUNT_FINGERPRINT_KEY,
        fingerprint,
      );
    }
  }

  private async activateElevenLabsVoicePreset(
    presetId: ElevenLabsVoicePresetId,
    apiKey: string,
  ): Promise<void> {
    await this.synchronizeElevenLabsAccount(apiKey);
    const preset = getElevenLabsVoicePreset(presetId);
    const voiceIds = await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: "Finding the CHUD and JARVIS voices in ElevenLabs…",
        cancellable: false,
      },
      () => resolveElevenLabsPresetVoiceIds(apiKey),
    );
    await this.context.globalState.update(
      ELEVENLABS_PRESET_VOICE_IDS_KEY,
      voiceIds,
    );
    const voiceId = voiceIds[presetId];

    const configuration =
      vscode.workspace.getConfiguration("chudvis.elevenLabs");
    await configuration.update(
      "voicePreset",
      presetId,
      vscode.ConfigurationTarget.Global,
    );
    await configuration.update(
      "voiceId",
      voiceId,
      vscode.ConfigurationTarget.Global,
    );
    await configuration.update(
      "ttsEnabled",
      true,
      vscode.ConfigurationTarget.Global,
    );
    await this.refreshServiceStatus();
    if (this.perception.activeMode === "ide") {
      await this.perception.restart();
    }
    this.report(`ElevenLabs feedback voice set to ${preset.label}`);
  }

  private async configureElevenLabsVoice(): Promise<void> {
    try {
      let key = await this.effectiveElevenLabsApiKey();
      if (key === undefined) {
        if (!(await this.configureElevenLabsApiKey(false))) {
          return;
        }
        key = await this.effectiveElevenLabsApiKey();
      }
      if (key === undefined) {
        throw new Error("ElevenLabs API key is not configured");
      }
      await this.synchronizeElevenLabsAccount(key);
      const currentPreset = this.configuredElevenLabsVoicePreset();
      const knownVoiceIds = this.elevenLabsPresetVoiceIds();
      const choices = ELEVENLABS_VOICE_PRESETS.map((preset, index) => ({
        label: `${preset.id === "chud" ? "$(person)" : "$(hubot)"} ${preset.label}`,
        description: `${preset.description}${preset.id === currentPreset ? " · current" : ""}`,
        detail:
          knownVoiceIds[preset.id] === undefined
            ? `Looks up the account voice named ${preset.accountVoiceName}`
            : `Ready · account voice ${preset.accountVoiceName}`,
        preset,
        picked: index === 0,
      }));
      const selected = await vscode.window.showQuickPick(choices, {
        title: "Choose the ElevenLabs voice for Chudvis feedback",
        placeHolder: "CHUD is the default",
        ignoreFocusOut: true,
        matchOnDescription: true,
        matchOnDetail: true,
      });
      if (selected === undefined) {
        return;
      }
      await this.activateElevenLabsVoicePreset(selected.preset.id, key);
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "voice configuration failed";
      this.report(`ElevenLabs voice configuration failed: ${detail}`);
      void vscode.window.showErrorMessage(
        `Chudvis ElevenLabs voice setup: ${detail}`,
      );
    }
  }

  private testElevenLabsVoice(): void {
    const configuration =
      vscode.workspace.getConfiguration("chudvis.elevenLabs");
    if (!configuration.get<boolean>("ttsEnabled", true)) {
      void vscode.window.showWarningMessage(
        "Chudvis spoken feedback is disabled. Choose a voice to enable it.",
      );
      return;
    }
    if (
      configuration.get<string>("voiceId", DEFAULT_ELEVENLABS_VOICE_ID).trim()
        .length === 0
    ) {
      void vscode.window
        .showWarningMessage(
          "Resolve the CHUD or JARVIS account voice before testing spoken feedback.",
          "Choose Voice",
        )
        .then((action) => {
          if (action === "Choose Voice") {
            void this.configureElevenLabsVoice();
          }
        });
      return;
    }
    if (
      this.perception.activeMode !== "ide" ||
      this.bridge?.connected !== true
    ) {
      void vscode.window.showWarningMessage(
        "Start Chudvis controls before testing the ElevenLabs voice.",
      );
      return;
    }
    this.bridge.sendNotification("voice.speak", {
      text: "Chudvis voice feedback is ready.",
    });
    this.report("Testing the configured ElevenLabs feedback voice");
  }

  private async confirmElevenLabsSetup(): Promise<boolean> {
    const voiceEnabled = vscode.workspace
      .getConfiguration("chudvis.runtime")
      .get<boolean>("voice", true);
    if (!voiceEnabled) {
      return true;
    }
    const key = await this.effectiveElevenLabsApiKey();
    if (key === undefined) {
      const action = await vscode.window.showWarningMessage(
        "ElevenLabs is not configured. Wake-word realtime speech will be unavailable; gaze, gestures, and local thumbs-up dictation can still run.",
        "Set ElevenLabs Key",
        "Start with Local Fallback",
      );
      if (action === "Set ElevenLabs Key") {
        return this.configureElevenLabsApiKey();
      }
      return action === "Start with Local Fallback";
    }
    await this.synchronizeElevenLabsAccount(key);
    const voiceConfiguration =
      vscode.workspace.getConfiguration("chudvis.elevenLabs");
    if (!voiceConfiguration.get<boolean>("ttsEnabled", true)) {
      return true;
    }
    const presetId = this.configuredElevenLabsVoicePreset();
    const voiceId = voiceConfiguration
      .get<string>("voiceId", DEFAULT_ELEVENLABS_VOICE_ID)
      .trim();
    if (
      this.elevenLabsPresetVoiceIds()[presetId] === voiceId &&
      voiceId.length > 0
    ) {
      return true;
    }
    try {
      await this.activateElevenLabsVoicePreset(presetId, key);
      return true;
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "voice lookup failed";
      this.report(`ElevenLabs preset voice setup failed: ${detail}`);
      const action = await vscode.window.showWarningMessage(
        `Chudvis could not find the ${getElevenLabsVoicePreset(presetId).label} account voice. ${detail}`,
        "Start without Spoken Feedback",
      );
      if (action !== "Start without Spoken Feedback") {
        return false;
      }
      await voiceConfiguration.update(
        "ttsEnabled",
        false,
        vscode.ConfigurationTarget.Global,
      );
      await this.refreshServiceStatus();
      return true;
    }
  }

  private async dispatch(notification: BridgeNotification): Promise<void> {
    if (notification.method === "diagnostic.event") {
      this.diagnostics.recordRemote(notification.params);
      return;
    }
    if (notification.method === "runtime.ready") {
      const detail = stringParam(notification.params, "message");
      if (detail.length === 0 || detail.length > 500) {
        throw new ProtocolError("Runtime readiness detail is invalid");
      }
      if (this.perception.activeMode === "ide") {
        this.setControlsRunning(true);
        this.report(detail);
      }
      return;
    }
    const voice = parseChudvisInbound(notification);
    if (voice !== undefined) {
      if (voice.method === "voice.level") {
        this.sidebar.setVoiceLevel(voice.level, voice.dbfs);
        return;
      } else if (voice.method === "voice.partial") {
        this.diagnostics.record(
          "speech",
          "transcript.partial",
          { text: voice.text },
          voice.requestId,
        );
      } else if (voice.method === "voice.request") {
        this.diagnostics.record(
          "speech",
          "transcript.committed",
          { transcript: voice.transcript },
          voice.requestId,
        );
      } else if (voice.method === "voice.state") {
        this.diagnostics.record(
          "speech",
          "state.changed",
          { state: voice.state, detail: voice.detail },
          voice.requestId,
        );
      }
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

  public async startBridge(allowEphemeralPort = false): Promise<boolean> {
    if (this.bridge !== undefined) {
      return true;
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
        return false;
      }
      await this.context.globalState.update(
        "chudvis.cloudDisclosureAccepted",
        true,
      );
    }
    const preferred = bridgeOptions();
    const ports =
      allowEphemeralPort && preferred.port !== 0
        ? [preferred.port, 0]
        : [preferred.port];
    for (const port of ports) {
      const options = { ...preferred, port };
      const bridge = new BridgeServer(
        options,
        (notification) => this.dispatch(notification),
        (connected, detail) => {
          this.output.info(detail);
          this.status.setBridge(connected, detail);
        },
        (direction, notification, delivered) => {
          this.diagnostics.record("bridge", direction, {
            method: notification.method,
            params: notification.params,
            delivered,
          });
        },
      );
      this.bridge = bridge;
      try {
        await bridge.start();
        if (port === 0) {
          this.output.warn(
            `Configured bridge port ${preferred.port} belongs to another VS Code window; this window is using ${bridge.addressPort()}.`,
          );
        }
        return true;
      } catch (error: unknown) {
        this.bridge = undefined;
        if (addressIsInUse(error) && port === preferred.port) {
          if (allowEphemeralPort) {
            continue;
          }
          const detail = `Chudvis is active in another VS Code window on ${preferred.host}:${preferred.port}; this window is standing by`;
          this.output.info(detail);
          this.status.setBridge(false, detail);
          return false;
        }
        const detail =
          error instanceof Error ? error.message : "unknown bridge error";
        this.output.error(detail);
        this.status.setBridge(false, detail);
        void vscode.window.showErrorMessage(
          `Chudvis bridge could not start: ${detail}`,
        );
        return false;
      }
    }
    return false;
  }

  private async startControls(allowEphemeralPort = false): Promise<void> {
    if (this.controlsStarting || this.perception.activeMode === "ide") {
      return;
    }
    this.setControlsStarting(true);
    let launched = false;
    try {
      if (!this.perception.calibrationReady()) {
        const action = await vscode.window.showWarningMessage(
          "Chudvis needs a native gaze calibration before controls can start.",
          "Calibrate Gaze",
        );
        if (!this.controlsAreStarting()) {
          return;
        }
        if (action === "Calibrate Gaze") {
          await this.startRuntimeMode("calibrate");
        }
        return;
      }
      const quality = this.perception.calibrationQuality();
      if (quality?.poor === true) {
        const action = await vscode.window.showWarningMessage(
          `Current gaze calibration is low quality (median ${quality.medianErrorPx.toFixed(0)} px, p95 ${quality.p95ErrorPx.toFixed(0)} px).`,
          "Recalibrate Gaze",
          "Start Anyway",
        );
        if (!this.controlsAreStarting()) {
          return;
        }
        if (action === "Recalibrate Gaze") {
          await this.startRuntimeMode("calibrate");
        }
        if (action !== "Start Anyway") {
          return;
        }
      }
      if (
        !(await this.confirmElevenLabsSetup()) ||
        !this.controlsAreStarting()
      ) {
        return;
      }
      if (
        !(await this.startBridge(allowEphemeralPort)) ||
        !this.controlsAreStarting()
      ) {
        return;
      }
      const bridge = this.bridge;
      if (bridge === undefined) {
        throw new Error(
          "Chudvis bridge stopped before the runtime could start",
        );
      }
      const options = bridgeOptions();
      const connection: RuntimeBridgeSettings = {
        host: options.host,
        port: bridge.addressPort(),
        sessionToken: options.sessionToken,
      };
      await this.perception.start("ide", connection);
      launched = true;
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "unknown runtime error";
      this.report(detail);
      void vscode.window.showErrorMessage(detail);
    } finally {
      if (!launched) {
        this.setControlsStarting(false);
      }
    }
  }

  private async followDiagnostics(): Promise<void> {
    await this.diagnostics.flush();
    const filePath = this.diagnostics.filePath;
    const terminal =
      process.platform === "win32"
        ? vscode.window.createTerminal({
            name: "Chudvis Diagnostics",
            shellPath: "powershell.exe",
            shellArgs: [
              "-NoLogo",
              "-NoExit",
              "-Command",
              `Get-Content -LiteralPath '${filePath.replaceAll("'", "''")}' -Tail 200 -Wait`,
            ],
          })
        : vscode.window.createTerminal({
            name: "Chudvis Diagnostics",
            shellPath: process.env.SHELL ?? "/bin/sh",
            shellArgs: [
              "-lc",
              `tail -n 200 -f -- '${filePath.replaceAll("'", "'\"'\"'")}'`,
            ],
          });
    terminal.show(false);
    this.diagnostics.record("lifecycle", "terminal-follow.started", {
      logFile: filePath,
    });
  }

  private async stopControls(): Promise<void> {
    await this.perception.stop();
    this.setControlsRunning(false);
    this.report("Gaze, gesture, and voice controls stopped");
  }

  private async toggleControls(): Promise<void> {
    if (this.controlsStarting || this.perception.activeMode === "ide") {
      await this.stopControls();
    } else {
      await this.startControls(true);
    }
  }

  private async startRuntimeMode(mode: RuntimeMode): Promise<void> {
    this.setControlsRunning(false);
    try {
      await this.perception.start(mode);
    } catch (error: unknown) {
      const detail =
        error instanceof Error ? error.message : "unknown runtime error";
      this.report(detail);
      void vscode.window.showErrorMessage(detail);
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

  private async stopEverything(): Promise<void> {
    await this.perception.stop();
    this.setControlsRunning(false);
    await this.stopBridge();
  }

  private setControlsRunning(running: boolean): void {
    this.controlsStarting = false;
    this.status.setControls(running);
    this.sidebar.setControls(running);
  }

  private setControlsStarting(starting: boolean): void {
    this.controlsStarting = starting;
    this.status.setStarting(starting);
    this.sidebar.setStarting(starting);
  }

  private controlsAreStarting(): boolean {
    return this.controlsStarting;
  }

  public initialize(): void {
    this.setControlsRunning(false);
    void this.refreshServiceStatus();
    const shortcut = process.platform === "darwin" ? "Cmd+Alt+G" : "Ctrl+Alt+G";
    void vscode.window
      .showInformationMessage(
        `Chudvis is off. Press ${shortcut} to start or stop all controls.`,
        "Recalibrate Gaze",
      )
      .then((action) => {
        if (action === "Recalibrate Gaze") {
          void this.startRuntimeMode("calibrate");
        }
      });
  }

  public async shutdown(): Promise<void> {
    await this.perception.stop();
    await this.stopBridge();
  }

  public dispose(): void {
    void this.shutdown();
  }
}

export function activate(context: vscode.ExtensionContext): void {
  runtime = new ExtensionRuntime(context);
  context.subscriptions.push(runtime);
  runtime.initialize();
}

export async function deactivate(): Promise<void> {
  const active = runtime;
  runtime = undefined;
  if (active !== undefined) {
    await active.shutdown();
  }
}
