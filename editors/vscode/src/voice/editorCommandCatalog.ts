export interface VoiceEditorCommand {
  readonly id: string;
  readonly title: string;
  readonly description: string;
  readonly requiresConfirmation: boolean;
}

interface CommandContribution {
  readonly id: string;
  readonly title: string;
  readonly category: string | undefined;
}

const MAX_ADDITIONAL_COMMANDS = 50;
const MAX_COMMAND_ID_LENGTH = 200;
const MAX_COMMAND_LABEL_LENGTH = 200;

export const SAFE_BUILT_IN_EDITOR_COMMANDS: readonly VoiceEditorCommand[] = [
  {
    id: "workbench.action.openSettings",
    title: "Open Settings",
    description: "Open the graphical VS Code Settings editor.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.showCommands",
    title: "Show Command Palette",
    description: "Open the VS Code Command Palette.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.quickOpen",
    title: "Quick Open",
    description: "Open the VS Code Quick Open picker.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.terminal.new",
    title: "Create New Terminal",
    description:
      "Create and show an integrated terminal without running a shell command.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.terminal.toggleTerminal",
    title: "Toggle Terminal",
    description: "Show or hide the integrated terminal.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.view.explorer",
    title: "Show Explorer",
    description: "Open the Explorer view.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.view.search",
    title: "Show Search",
    description: "Open the Search view.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.view.scm",
    title: "Show Source Control",
    description:
      "Open the Source Control view without changing the repository.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.view.debug",
    title: "Show Run and Debug",
    description:
      "Open the Run and Debug view without starting a debug session.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.view.extensions",
    title: "Show Extensions",
    description: "Open the Extensions view without installing anything.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.actions.view.problems",
    title: "Show Problems",
    description: "Open the Problems panel.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.output.toggleOutput",
    title: "Toggle Output",
    description: "Show or hide the Output panel.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.togglePanel",
    title: "Toggle Panel",
    description: "Show or hide the bottom panel.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.toggleSidebarVisibility",
    title: "Toggle Primary Side Bar",
    description: "Show or hide the primary side bar.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.toggleAuxiliaryBar",
    title: "Toggle Secondary Side Bar",
    description: "Show or hide the secondary side bar.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.toggleZenMode",
    title: "Toggle Zen Mode",
    description: "Enter or leave Zen Mode.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.navigateBack",
    title: "Navigate Back",
    description: "Go back in editor navigation history.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.navigateForward",
    title: "Navigate Forward",
    description: "Go forward in editor navigation history.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.nextEditor",
    title: "Open Next Editor",
    description: "Move focus to the next open editor.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.previousEditor",
    title: "Open Previous Editor",
    description: "Move focus to the previous open editor.",
    requiresConfirmation: false,
  },
  {
    id: "workbench.action.files.newUntitledFile",
    title: "New Untitled File",
    description: "Open a new unsaved text editor.",
    requiresConfirmation: false,
  },
];

function recordValue(
  value: unknown,
): Readonly<Record<string, unknown>> | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? (value as Readonly<Record<string, unknown>>)
    : undefined;
}

function boundedString(value: unknown, maximum: number): string | undefined {
  if (typeof value !== "string") {
    return undefined;
  }
  const trimmed = value.trim();
  return trimmed.length > 0 && trimmed.length <= maximum ? trimmed : undefined;
}

export function commandContributionsFromManifests(
  manifests: readonly unknown[],
): readonly CommandContribution[] {
  const result: CommandContribution[] = [];
  for (const manifestValue of manifests) {
    const manifest = recordValue(manifestValue);
    const contributes = recordValue(manifest?.contributes);
    const commands = contributes?.commands;
    if (!Array.isArray(commands)) {
      continue;
    }
    for (const commandValue of commands) {
      const command = recordValue(commandValue);
      const id = boundedString(command?.command, MAX_COMMAND_ID_LENGTH);
      const title = boundedString(command?.title, MAX_COMMAND_LABEL_LENGTH);
      if (id === undefined || title === undefined) {
        continue;
      }
      result.push({
        id,
        title,
        category: boundedString(command?.category, MAX_COMMAND_LABEL_LENGTH),
      });
    }
  }
  return result;
}

export function buildVoiceEditorCommandCatalog(
  availableCommandIds: readonly string[],
  configuredAdditionalCommandIds: readonly unknown[],
  contributions: readonly CommandContribution[],
): readonly VoiceEditorCommand[] {
  const available = new Set(availableCommandIds);
  const result = SAFE_BUILT_IN_EDITOR_COMMANDS.filter((command) =>
    available.has(command.id),
  );
  const known = new Set(result.map((command) => command.id));
  const metadata = new Map(
    contributions.map((command) => [command.id, command] as const),
  );

  for (const configuredValue of configuredAdditionalCommandIds.slice(
    0,
    MAX_ADDITIONAL_COMMANDS,
  )) {
    const id = boundedString(configuredValue, MAX_COMMAND_ID_LENGTH);
    if (id === undefined || known.has(id) || !available.has(id)) {
      continue;
    }
    const contribution = metadata.get(id);
    const title = contribution?.title ?? id;
    const source = contribution?.category;
    result.push({
      id,
      title: source === undefined ? title : `${source}: ${title}`,
      description:
        "Run this user-approved installed-extension command with no arguments.",
      requiresConfirmation: true,
    });
    known.add(id);
  }

  return result;
}
