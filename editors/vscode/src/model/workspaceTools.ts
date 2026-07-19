import type { WorkspaceToolExecutor } from "./backboardProvider";
import { SafeWorkspace } from "../workspace/safeWorkspace";

function argumentsObject(value: unknown): Readonly<Record<string, unknown>> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("Tool arguments must be an object");
  }
  return value as Readonly<Record<string, unknown>>;
}

function requiredString(
  args: Readonly<Record<string, unknown>>,
  name: string,
  maximum: number,
): string {
  const value = args[name];
  if (
    typeof value !== "string" ||
    value.trim().length === 0 ||
    value.length > maximum
  ) {
    throw new Error(`Tool argument '${name}' is invalid`);
  }
  return value;
}

function optionalLine(
  args: Readonly<Record<string, unknown>>,
  name: string,
): number | undefined {
  const value = args[name];
  if (value === undefined) {
    return undefined;
  }
  if (
    !Number.isInteger(value) ||
    typeof value !== "number" ||
    value < 1 ||
    value > 1_000_000
  ) {
    throw new Error(`Tool argument '${name}' is invalid`);
  }
  return value;
}

export class WorkspaceTools implements WorkspaceToolExecutor {
  public constructor(private readonly workspace: SafeWorkspace) {}

  public async execute(
    name: string,
    argumentsValue: unknown,
  ): Promise<unknown> {
    try {
      const args = argumentsObject(argumentsValue);
      switch (name) {
        case "read_workspace_file":
          return await this.workspace.readText(
            requiredString(args, "path", 500),
            optionalLine(args, "startLine"),
            optionalLine(args, "endLine"),
          );
        case "find_workspace_symbol":
          return {
            symbols: await this.workspace.findSymbols(
              requiredString(args, "query", 200),
            ),
          };
        case "list_workspace_files": {
          const pattern = args.pattern;
          if (
            pattern !== undefined &&
            (typeof pattern !== "string" || pattern.length > 200)
          ) {
            throw new Error("Tool argument 'pattern' is invalid");
          }
          return { files: await this.workspace.listFiles(pattern) };
        }
        default:
          return { error: `Unsupported read-only tool '${name}'` };
      }
    } catch (error: unknown) {
      return {
        error: error instanceof Error ? error.message : "Workspace tool failed",
      };
    }
  }
}
