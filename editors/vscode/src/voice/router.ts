import type { VoiceEditorCommand } from "./editorCommandCatalog";

export type VoiceRoute =
  | { readonly kind: "open"; readonly query: string }
  | { readonly kind: "createMany"; readonly paths: readonly string[] }
  | { readonly kind: "symbol"; readonly query: string }
  | { readonly kind: "references"; readonly query: string | undefined }
  | { readonly kind: "undo" }
  | { readonly kind: "cancel" }
  | { readonly kind: "question"; readonly instruction: string }
  | { readonly kind: "edit"; readonly instruction: string }
  | {
      readonly kind: "editorCommand";
      readonly command: VoiceEditorCommand;
    }
  | {
      readonly kind: "unsupported";
      readonly instruction: string;
      readonly reason: string;
    };

interface VoiceRoutingFunction {
  readonly type: "function";
  readonly function: {
    readonly name: string;
    readonly description: string;
    readonly parameters: Readonly<Record<string, unknown>>;
  };
}

const BASE_VOICE_ROUTING_TOOLS: readonly VoiceRoutingFunction[] = [
  {
    type: "function",
    function: {
      name: "open_workspace_file",
      description:
        "Open an existing workspace file. Convert spoken punctuation in the requested filename into a concise file query.",
      parameters: {
        type: "object",
        properties: { query: { type: "string", minLength: 1 } },
        required: ["query"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "create_workspace_files",
      description:
        "Create one or more new empty text files. Supply clean workspace-relative paths with their intended extensions. Do not use this for a request that also asks to add or change file contents; use edit_workspace instead.",
      parameters: {
        type: "object",
        properties: {
          paths: {
            type: "array",
            minItems: 1,
            maxItems: 20,
            items: { type: "string", minLength: 1 },
          },
        },
        required: ["paths"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "go_to_workspace_symbol",
      description:
        "Navigate to an existing function, class, method, variable, or other code symbol.",
      parameters: {
        type: "object",
        properties: { query: { type: "string", minLength: 1 } },
        required: ["query"],
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "show_symbol_references",
      description:
        "Show references for the current symbol or for a specifically named symbol.",
      parameters: {
        type: "object",
        properties: { query: { type: "string", minLength: 1 } },
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "undo_last_edit",
      description: "Undo the last edit applied by Chudvis.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "cancel_current_request",
      description: "Cancel the current request or pending edit.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "answer_workspace_question",
      description:
        "Answer an informational question about the current code or workspace without editing it.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "edit_workspace",
      description:
        "Carry out a request that adds, removes, fixes, refactors, or otherwise changes workspace file contents. Also use this when creating requested content inside an existing empty file.",
      parameters: {
        type: "object",
        properties: {},
        additionalProperties: false,
      },
    },
  },
  {
    type: "function",
    function: {
      name: "unsupported_request",
      description:
        "Use only when the request has no matching Chudvis action or is too unclear to execute safely.",
      parameters: {
        type: "object",
        properties: { reason: { type: "string", minLength: 1 } },
        required: ["reason"],
        additionalProperties: false,
      },
    },
  },
];

export function voiceRoutingTools(
  editorCommands: readonly VoiceEditorCommand[],
): readonly VoiceRoutingFunction[] {
  if (editorCommands.length === 0) {
    return BASE_VOICE_ROUTING_TOOLS;
  }
  const commandSummary = editorCommands
    .map(
      (command) =>
        `${command.id}: ${command.title}. ${command.description}${
          command.requiresConfirmation ? " Requires user confirmation." : ""
        }`,
    )
    .join("\n");
  const unsupportedTool = BASE_VOICE_ROUTING_TOOLS.at(-1);
  if (unsupportedTool === undefined) {
    throw new Error("The voice-routing tool catalog is empty");
  }
  return [
    ...BASE_VOICE_ROUTING_TOOLS.slice(0, -1),
    {
      type: "function",
      function: {
        name: "execute_editor_command",
        description: [
          "Execute an eligible no-argument VS Code command. Use this for editor and workbench UI actions that do not match a more specific Chudvis action.",
          commandSummary,
        ].join("\n"),
        parameters: {
          type: "object",
          properties: {
            command: {
              type: "string",
              enum: editorCommands.map((command) => command.id),
            },
          },
          required: ["command"],
          additionalProperties: false,
        },
      },
    },
    unsupportedTool,
  ];
}

function argumentsObject(value: unknown): Readonly<Record<string, unknown>> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error("The model returned invalid voice-action arguments");
  }
  return value as Readonly<Record<string, unknown>>;
}

function requiredString(
  argumentsValue: Readonly<Record<string, unknown>>,
  field: string,
): string {
  const value = argumentsValue[field];
  if (typeof value !== "string") {
    throw new Error(`The model voice action is missing '${field}'`);
  }
  const trimmed = value.trim();
  if (trimmed.length === 0 || trimmed.length > 500) {
    throw new Error(`The model voice action has an invalid '${field}'`);
  }
  return trimmed;
}

function optionalString(
  argumentsValue: Readonly<Record<string, unknown>>,
  field: string,
): string | undefined {
  return argumentsValue[field] === undefined
    ? undefined
    : requiredString(argumentsValue, field);
}

function requiredPaths(
  argumentsValue: Readonly<Record<string, unknown>>,
): readonly string[] {
  const value = argumentsValue.paths;
  if (!Array.isArray(value) || value.length === 0 || value.length > 20) {
    throw new Error("The model voice action has invalid 'paths'");
  }
  return value.map((path, index) => {
    if (typeof path !== "string") {
      throw new Error(`The model voice action path ${index + 1} is invalid`);
    }
    const trimmed = path.trim();
    if (trimmed.length === 0 || trimmed.length > 500) {
      throw new Error(`The model voice action path ${index + 1} is invalid`);
    }
    return trimmed;
  });
}

export function voiceRouteFromToolCall(
  name: string,
  argumentsValue: unknown,
  instruction: string,
  editorCommands: readonly VoiceEditorCommand[] = [],
): VoiceRoute {
  const args = argumentsObject(argumentsValue);
  switch (name) {
    case "open_workspace_file":
      return { kind: "open", query: requiredString(args, "query") };
    case "create_workspace_files":
      return { kind: "createMany", paths: requiredPaths(args) };
    case "go_to_workspace_symbol":
      return { kind: "symbol", query: requiredString(args, "query") };
    case "show_symbol_references":
      return { kind: "references", query: optionalString(args, "query") };
    case "undo_last_edit":
      return { kind: "undo" };
    case "cancel_current_request":
      return { kind: "cancel" };
    case "answer_workspace_question":
      return { kind: "question", instruction };
    case "edit_workspace":
      return { kind: "edit", instruction };
    case "execute_editor_command": {
      const commandId = requiredString(args, "command");
      const command = editorCommands.find(
        (candidate) => candidate.id === commandId,
      );
      if (command === undefined) {
        throw new Error(
          `The model selected ineligible editor command '${commandId}'`,
        );
      }
      return { kind: "editorCommand", command };
    }
    case "unsupported_request":
      return {
        kind: "unsupported",
        instruction,
        reason: requiredString(args, "reason"),
      };
    default:
      throw new Error(`The model selected unknown voice action '${name}'`);
  }
}
