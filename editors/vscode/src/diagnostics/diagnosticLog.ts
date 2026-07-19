import { promises as fs } from "node:fs";
import { dirname } from "node:path";

import * as vscode from "vscode";

import {
  redactDiagnosticValue,
  summarizeDiagnosticPayload,
} from "./diagnosticData";

const MAX_MEMORY_EVENTS = 1_000;

export interface DiagnosticEvent {
  readonly sequence: number;
  readonly timestamp: string;
  readonly category: string;
  readonly name: string;
  readonly requestId?: string;
  readonly data?: unknown;
}

export interface ModelDiagnosticEvent {
  readonly phase: "request" | "response" | "stream" | "error";
  readonly path: string;
  readonly method: string;
  readonly status?: number;
  readonly durationMs?: number;
  readonly payload?: unknown;
  readonly error?: string;
  readonly requestId?: string;
}

export class DiagnosticLog implements vscode.Disposable {
  private readonly output = vscode.window.createOutputChannel(
    "Chudvis Diagnostics",
    { log: true },
  );
  private readonly emitter = new vscode.EventEmitter<DiagnosticEvent>();
  private readonly events: DiagnosticEvent[] = [];
  private sequence = 0;
  private writeQueue: Promise<void>;
  public readonly filePath: string;

  public constructor(context: vscode.ExtensionContext) {
    this.filePath = vscode.Uri.joinPath(
      context.logUri,
      "chudvis-diagnostics.jsonl",
    ).fsPath;
    this.writeQueue = fs
      .mkdir(dirname(this.filePath), { recursive: true })
      .then(() => fs.appendFile(this.filePath, "", "utf8"));
    this.record("lifecycle", "diagnostics.started", {
      logFile: this.filePath,
      modelPayloads: this.includeModelPayloads,
    });
  }

  public get onEvent(): vscode.Event<DiagnosticEvent> {
    return this.emitter.event;
  }

  public get snapshot(): readonly DiagnosticEvent[] {
    return [...this.events];
  }

  public get includeModelPayloads(): boolean {
    return vscode.workspace
      .getConfiguration("chudvis.diagnostics")
      .get<boolean>("includeModelPayloads", false);
  }

  public async setIncludeModelPayloads(enabled: boolean): Promise<void> {
    await vscode.workspace
      .getConfiguration("chudvis.diagnostics")
      .update(
        "includeModelPayloads",
        enabled,
        vscode.ConfigurationTarget.Global,
      );
    this.record("lifecycle", "model-payload-capture.changed", { enabled });
  }

  public record(
    category: string,
    name: string,
    data?: unknown,
    requestId?: string,
  ): DiagnosticEvent {
    const event: DiagnosticEvent = {
      sequence: ++this.sequence,
      timestamp: new Date().toISOString(),
      category: category.slice(0, 80),
      name: name.slice(0, 160),
      ...(requestId === undefined
        ? {}
        : { requestId: requestId.slice(0, 100) }),
      ...(data === undefined ? {} : { data: redactDiagnosticValue(data) }),
    };
    this.events.push(event);
    if (this.events.length > MAX_MEMORY_EVENTS) {
      this.events.shift();
    }
    const line = JSON.stringify(event);
    this.output.info(line);
    this.writeQueue = this.writeQueue
      .then(() => fs.appendFile(this.filePath, `${line}\n`, "utf8"))
      .catch((error: unknown) => {
        this.output.error(
          `Could not write diagnostic JSONL: ${error instanceof Error ? error.message : "unknown file error"}`,
        );
      });
    this.emitter.fire(event);
    return event;
  }

  public recordModel(event: ModelDiagnosticEvent): DiagnosticEvent {
    const payload = this.includeModelPayloads
      ? redactDiagnosticValue(event.payload)
      : summarizeDiagnosticPayload(event.payload);
    return this.record(
      "model",
      `backboard.${event.phase}`,
      {
        path: event.path,
        method: event.method,
        status: event.status,
        durationMs: event.durationMs,
        payload,
        error: event.error,
      },
      event.requestId,
    );
  }

  public recordSensitive(
    category: string,
    name: string,
    data: unknown,
    requestId?: string,
  ): DiagnosticEvent {
    return this.record(
      category,
      name,
      this.includeModelPayloads ? data : summarizeDiagnosticPayload(data),
      requestId,
    );
  }

  public recordRemote(params: Readonly<Record<string, unknown>>): void {
    const category = params.category;
    const name = params.name;
    if (
      typeof category !== "string" ||
      category.length === 0 ||
      category.length > 80 ||
      typeof name !== "string" ||
      name.length === 0 ||
      name.length > 160
    ) {
      this.record("bridge", "diagnostic-event.rejected", {
        reason: "Invalid category or name",
      });
      return;
    }
    const requestId =
      typeof params.requestId === "string" ? params.requestId : undefined;
    this.record(category, name, params.data, requestId);
  }

  public showOutput(): void {
    this.output.show(true);
  }

  public async flush(): Promise<void> {
    await this.writeQueue;
  }

  public async clear(): Promise<void> {
    this.events.splice(0, this.events.length);
    this.output.clear();
    await this.writeQueue;
    await fs.writeFile(this.filePath, "", "utf8");
    this.writeQueue = Promise.resolve();
    this.record("lifecycle", "diagnostics.cleared", {
      logFile: this.filePath,
    });
  }

  public dispose(): void {
    this.record("lifecycle", "diagnostics.stopped");
    this.emitter.dispose();
    this.output.dispose();
  }
}
