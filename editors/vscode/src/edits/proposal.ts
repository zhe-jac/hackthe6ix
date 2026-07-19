export interface ProposedTextEdit {
  readonly path: string;
  readonly originalText: string;
  readonly replacementText: string;
  readonly reason: string;
}

export interface EditProposal {
  readonly edits: readonly ProposedTextEdit[];
}

function record(
  value: unknown,
  label: string,
): Readonly<Record<string, unknown>> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function boundedString(
  value: unknown,
  label: string,
  maximum: number,
  allowEmpty: boolean,
): string {
  if (
    typeof value !== "string" ||
    value.length > maximum ||
    (!allowEmpty && value.length === 0)
  ) {
    throw new Error(`${label} is invalid`);
  }
  return value;
}

export function parseEditProposal(value: unknown): EditProposal {
  const root = record(value, "propose_edits arguments");
  const rawEdits = root.edits;
  if (
    !Array.isArray(rawEdits) ||
    rawEdits.length === 0 ||
    rawEdits.length > 100
  ) {
    throw new Error("propose_edits must contain between 1 and 100 edits");
  }
  const edits = rawEdits.map((rawEdit, index): ProposedTextEdit => {
    const edit = record(rawEdit, `edit ${index + 1}`);
    return {
      path: boundedString(edit.path, `edit ${index + 1} path`, 500, false),
      originalText: boundedString(
        edit.originalText,
        `edit ${index + 1} originalText`,
        100_000,
        true,
      ),
      replacementText: boundedString(
        edit.replacementText,
        `edit ${index + 1} replacementText`,
        100_000,
        true,
      ),
      reason: boundedString(
        edit.reason,
        `edit ${index + 1} reason`,
        2_000,
        false,
      ),
    };
  });
  return { edits };
}
