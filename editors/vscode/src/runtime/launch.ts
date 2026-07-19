import { join } from "node:path";

export type RuntimeMode = "calibrate" | "diagnostics" | "ide";

export interface RuntimeBridgeSettings {
  readonly host: string;
  readonly port: number;
  readonly sessionToken: string;
}

export interface RuntimeLaunchSettings {
  readonly mode: RuntimeMode;
  readonly preview: boolean;
  readonly voice: boolean;
  readonly uvExecutable: string;
  readonly pythonVersion: string;
  readonly extraArguments: readonly string[];
  readonly bridge: RuntimeBridgeSettings | undefined;
}

export interface RuntimeLaunchPlan {
  readonly command: string;
  readonly args: readonly string[];
  readonly cwd: string;
  readonly environment: Readonly<Record<string, string>>;
}

function chudvisArguments(settings: RuntimeLaunchSettings): string[] {
  if (settings.mode === "calibrate") {
    return ["calibrate", ...settings.extraArguments];
  }
  if (settings.mode === "diagnostics") {
    return ["test", "--ide", ...settings.extraArguments];
  }
  const args = ["ide"];
  if (settings.preview) {
    args.push("--preview");
  }
  if (!settings.voice) {
    args.push("--no-voice");
  }
  return [...args, ...settings.extraArguments];
}

export function runtimeLaunchPlan(
  platform: NodeJS.Platform,
  runtimeRoot: string,
  environmentRoot: string,
  settings: RuntimeLaunchSettings,
): RuntimeLaunchPlan {
  const runtimeArgs = chudvisArguments(settings);
  const bridgeEnvironment: Record<string, string> = {};
  if (settings.mode === "ide" && settings.bridge !== undefined) {
    bridgeEnvironment.CHUDVIS_IDE_HOST = settings.bridge.host;
    bridgeEnvironment.CHUDVIS_IDE_PORT = String(settings.bridge.port);
    bridgeEnvironment.CHUDVIS_IDE_SESSION_TOKEN = settings.bridge.sessionToken;
  }
  if (platform === "win32") {
    return {
      command: "powershell.exe",
      args: [
        "-NoLogo",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        join(runtimeRoot, "scripts", "chudvis-windows.ps1"),
        ...runtimeArgs,
      ],
      cwd: runtimeRoot,
      environment: {
        CHUDVIS_UV: settings.uvExecutable,
        CHUDVIS_WINDOWS_PYTHON: settings.pythonVersion,
        ...bridgeEnvironment,
      },
    };
  }
  return {
    command: settings.uvExecutable,
    args: [
      "run",
      "--python",
      settings.pythonVersion,
      "--extra",
      "voice",
      "chudvis",
      ...runtimeArgs,
    ],
    cwd: runtimeRoot,
    environment: {
      UV_PROJECT_ENVIRONMENT: join(environmentRoot, "venv"),
      ...bridgeEnvironment,
    },
  };
}
