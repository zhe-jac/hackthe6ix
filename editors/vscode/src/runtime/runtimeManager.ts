import { type ChildProcess, spawn } from "node:child_process";
import { existsSync, readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve } from "node:path";

import * as vscode from "vscode";

import {
  type RuntimeBridgeSettings,
  type RuntimeLaunchSettings,
  type RuntimeMode,
  runtimeLaunchPlan,
} from "./launch";

type RuntimeStateListener = (detail: string) => void;
type RuntimeExitListener = (mode: RuntimeMode, code: number | null) => void;

export interface CalibrationQuality {
  readonly medianErrorPx: number;
  readonly p95ErrorPx: number;
  readonly poor: boolean;
}

function boundedArguments(value: readonly string[]): readonly string[] {
  if (
    value.length > 32 ||
    value.some((item) => item.length > 1_000 || item.includes("\0"))
  ) {
    throw new Error("Chudvis runtime arguments exceed the safety limit");
  }
  return value;
}

export class ChudvisRuntimeManager implements vscode.Disposable {
  private child: ChildProcess | undefined;
  private mode: RuntimeMode | undefined;
  private bridge: RuntimeBridgeSettings | undefined;
  private stopping = false;

  public constructor(
    private readonly context: vscode.ExtensionContext,
    private readonly output: vscode.OutputChannel,
    private readonly onState: RuntimeStateListener,
    private readonly onExit: RuntimeExitListener,
  ) {}

  public get running(): boolean {
    return this.child !== undefined;
  }

  public get activeMode(): RuntimeMode | undefined {
    return this.mode;
  }

  public calibrationReady(): boolean {
    const extraArguments = this.settings("ide", undefined).extraArguments;
    if (extraArguments.includes("--profile")) {
      return true;
    }
    return existsSync(
      join(homedir(), ".config", "chudvis", "calibration.json"),
    );
  }

  public calibrationQuality(): CalibrationQuality | undefined {
    try {
      const value: unknown = JSON.parse(
        readFileSync(
          join(homedir(), ".config", "chudvis", "calibration.json"),
          "utf8",
        ),
      );
      if (typeof value !== "object" || value === null || Array.isArray(value)) {
        return undefined;
      }
      const profile = value as Record<string, unknown>;
      const medianErrorPx = profile.validation_median_error_px;
      const p95ErrorPx = profile.validation_p95_error_px;
      const width = profile.screen_width;
      const height = profile.screen_height;
      if (
        typeof medianErrorPx !== "number" ||
        typeof p95ErrorPx !== "number" ||
        typeof width !== "number" ||
        typeof height !== "number" ||
        !Number.isFinite(medianErrorPx) ||
        !Number.isFinite(p95ErrorPx) ||
        !Number.isFinite(width) ||
        !Number.isFinite(height)
      ) {
        return undefined;
      }
      const diagonal = Math.hypot(width, height);
      return {
        medianErrorPx,
        p95ErrorPx,
        poor: medianErrorPx > diagonal * 0.06 || p95ErrorPx > diagonal * 0.18,
      };
    } catch {
      return undefined;
    }
  }

  private settings(
    mode: RuntimeMode,
    bridge: RuntimeBridgeSettings | undefined,
  ): RuntimeLaunchSettings {
    const configuration = vscode.workspace.getConfiguration("chudvis.runtime");
    const uvExecutable = configuration.get<string>("uvExecutable", "uv").trim();
    const pythonVersion = configuration
      .get<string>("pythonVersion", "3.12")
      .trim();
    if (uvExecutable.length === 0 || pythonVersion.length === 0) {
      throw new Error(
        "Chudvis runtime uvExecutable and pythonVersion must not be empty",
      );
    }
    return {
      mode,
      preview: configuration.get<boolean>("preview", false),
      voice: configuration.get<boolean>("voice", true),
      uvExecutable,
      pythonVersion,
      extraArguments: boundedArguments(
        configuration.get<readonly string[]>("extraArguments", []),
      ),
      bridge,
    };
  }

  private runtimeRoot(): string {
    const configured = vscode.workspace
      .getConfiguration("chudvis.runtime")
      .get<string>("sourceRoot", "")
      .trim();
    return configured.length === 0
      ? this.context.asAbsolutePath("runtime")
      : resolve(configured);
  }

  public async start(
    mode: RuntimeMode = "ide",
    bridge?: RuntimeBridgeSettings,
  ): Promise<void> {
    if (this.child !== undefined && this.mode === mode) {
      return;
    }
    await this.stop();

    const runtimeRoot = this.runtimeRoot();
    if (!existsSync(join(runtimeRoot, "pyproject.toml"))) {
      throw new Error(
        `Chudvis packaged runtime was not found at ${runtimeRoot}. Reinstall the extension or configure chudvis.runtime.sourceRoot.`,
      );
    }
    const plan = runtimeLaunchPlan(
      process.platform,
      runtimeRoot,
      this.context.globalStorageUri.fsPath,
      this.settings(mode, bridge),
    );
    const environment = { ...process.env, ...plan.environment };
    this.stopping = false;
    this.mode = mode;
    this.bridge = bridge;
    this.onState(
      mode === "ide"
        ? process.platform === "win32"
          ? "Starting Windows-native gaze, gesture, and voice runtime"
          : "Starting gaze, gesture, and voice runtime"
        : mode === "calibrate"
          ? "Opening gaze calibration"
          : "Opening safe two-hand tracking diagnostics",
    );
    this.output.appendLine(
      `[runtime] Starting ${mode} from ${runtimeRoot} with ${plan.command}`,
    );

    const child = spawn(plan.command, [...plan.args], {
      cwd: plan.cwd,
      env: environment,
      detached: process.platform !== "win32",
      shell: false,
      windowsHide: true,
      stdio: ["ignore", "pipe", "pipe"],
    });
    this.child = child;
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      this.output.append(chunk);
    });
    child.stderr.on("data", (chunk: string) => {
      this.output.append(chunk);
    });
    child.once("error", (error) => {
      if (this.child === child) {
        this.child = undefined;
        this.mode = undefined;
        this.bridge = undefined;
      }
      const detail = `Chudvis runtime could not start: ${error.message}`;
      this.output.appendLine(`[runtime] ${detail}`);
      this.onState(detail);
      this.onExit(mode, null);
      void vscode.window
        .showErrorMessage(detail, "Show Output")
        .then((action) => {
          if (action === "Show Output") {
            this.output.show(true);
          }
        });
    });
    child.once("exit", (code) => {
      if (this.child !== child) {
        return;
      }
      const exitedMode = this.mode ?? mode;
      const expected = this.stopping;
      this.child = undefined;
      this.mode = undefined;
      this.bridge = undefined;
      this.stopping = false;
      this.output.appendLine(
        `[runtime] ${exitedMode} exited${code === null ? "" : ` with code ${code}`}`,
      );
      this.onExit(exitedMode, code);
      if (!expected && code !== 0) {
        const detail =
          "Chudvis perception runtime stopped unexpectedly. Open the Chudvis output for details.";
        this.onState(detail);
        void vscode.window
          .showErrorMessage(detail, "Show Output", "Calibrate Gaze")
          .then((action) => {
            if (action === "Show Output") {
              this.output.show(true);
            } else if (action === "Calibrate Gaze") {
              void vscode.commands.executeCommand("chudvis.calibrate");
            }
          });
      }
    });
  }

  public async restart(): Promise<void> {
    const mode = this.mode;
    const bridge = this.bridge;
    if (mode === undefined) {
      return;
    }
    await this.stop();
    await this.start(mode, bridge);
  }

  public async stop(): Promise<void> {
    const child = this.child;
    if (child === undefined) {
      return;
    }
    this.stopping = true;
    this.child = undefined;
    this.mode = undefined;
    this.bridge = undefined;
    await new Promise<void>((resolveStop) => {
      const finish = (): void => resolveStop();
      child.once("exit", finish);
      if (process.platform === "win32" && child.pid !== undefined) {
        const killer = spawn(
          "taskkill.exe",
          ["/pid", String(child.pid), "/t", "/f"],
          { shell: false, windowsHide: true, stdio: "ignore" },
        );
        killer.once("error", () => {
          child.kill();
          setTimeout(finish, 250);
        });
        killer.once("exit", () => {
          setTimeout(finish, 250);
        });
      } else if (child.pid !== undefined) {
        try {
          process.kill(-child.pid, "SIGTERM");
        } catch {
          child.kill("SIGTERM");
        }
        setTimeout(finish, 1_500);
      } else {
        child.kill();
        setTimeout(finish, 250);
      }
    });
    this.stopping = false;
  }

  public dispose(): void {
    void this.stop();
  }
}
