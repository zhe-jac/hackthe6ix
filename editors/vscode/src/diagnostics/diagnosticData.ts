const MAX_VALUE_DEPTH = 12;
const REDACTED = "[redacted]";
const SECRET_FIELD =
  /(?:api[-_]?key|authorization|password|secret|session[-_]?token)/iu;

export function redactDiagnosticValue(value: unknown, depth = 0): unknown {
  if (depth > MAX_VALUE_DEPTH) {
    return "[maximum depth]";
  }
  if (Array.isArray(value)) {
    return value.map((item) => redactDiagnosticValue(item, depth + 1));
  }
  if (typeof value !== "object" || value === null) {
    return value;
  }
  const result: Record<string, unknown> = {};
  for (const [key, item] of Object.entries(value)) {
    result[key] = SECRET_FIELD.test(key)
      ? REDACTED
      : redactDiagnosticValue(item, depth + 1);
  }
  return result;
}

export function summarizeDiagnosticPayload(value: unknown): unknown {
  if (value === undefined) {
    return undefined;
  }
  const serialized = JSON.stringify(redactDiagnosticValue(value));
  if (Array.isArray(value)) {
    return {
      captured: false,
      type: "array",
      items: value.length,
      characters: serialized.length,
    };
  }
  if (typeof value === "object" && value !== null) {
    return {
      captured: false,
      type: "object",
      fields: Object.keys(value),
      characters: serialized.length,
    };
  }
  return { captured: false, type: typeof value, characters: serialized.length };
}
