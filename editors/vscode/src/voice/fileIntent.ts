import * as path from "node:path";

const FORMAT_EXTENSIONS: Readonly<Record<string, string>> = {
  css: ".css",
  html: ".html",
  javascript: ".js",
  json: ".json",
  markdown: ".md",
  python: ".py",
  text: ".txt",
  typescript: ".ts",
  yaml: ".yaml",
  yml: ".yml",
};

function stripOuterQuotes(value: string): string {
  const trimmed = value.trim();
  const first = trimmed[0];
  const last = trimmed.at(-1);
  return trimmed.length >= 2 &&
    first === last &&
    ['"', "'", "`"].includes(first ?? "")
    ? trimmed.slice(1, -1).trim()
    : trimmed;
}

function normalizeSpokenPath(value: string): string {
  let normalized = stripOuterQuotes(value)
    .replace(/[!?,;:]+$/gu, "")
    .trim();
  if (normalized.endsWith(".")) {
    normalized = normalized.slice(0, -1).trimEnd();
  }
  return normalized
    .replace(/\s+dot\s+(?:p\s*y|pie|pi)\b/giu, ".py")
    .replace(/\s+dot\s+(?:m\s*d|markdown)\b/giu, ".md")
    .replace(/\s+dot\s+(?:t\s*s|typescript)\b/giu, ".ts")
    .replace(/\s+dot\s+(?:j\s*s|javascript)\b/giu, ".js")
    .replace(/\s+dot\s+(?:j\s*son|json)\b/giu, ".json")
    .replace(/\s+dot\s+(?:y\s*a\s*m\s*l|yaml)\b/giu, ".yaml")
    .replace(/\s+dot\s+(?:h\s*t\s*m\s*l|html)\b/giu, ".html")
    .replace(/\s+dot\s+(?:c\s*s\s*s|css)\b/giu, ".css")
    .replace(/\s+dot\s+/giu, ".")
    .replace(/\s+(?:forward\s+)?slash\s+/giu, "/")
    .replace(/\s+backslash\s+/giu, "/")
    .replace(/\s*\/\s*/gu, "/")
    .replace(/\s*\.\s*/gu, ".")
    .replace(/\s+/gu, " ")
    .trim();
}

export function normalizeSpokenFileQuery(value: string): string {
  return normalizeSpokenPath(value).toLowerCase();
}

export function requestedFilePath(
  format: string | undefined,
  value: string,
): string {
  const requested = normalizeSpokenPath(value);
  const extension =
    format === undefined ? undefined : FORMAT_EXTENSIONS[format.toLowerCase()];
  if (
    extension !== undefined &&
    path.posix.extname(requested.replaceAll("\\", "/")).length === 0
  ) {
    return `${requested}${extension}`;
  }
  return requested;
}

function editDistance(left: string, right: string): number {
  let previous = Array.from({ length: right.length + 1 }, (_, index) => index);
  for (let leftIndex = 1; leftIndex <= left.length; leftIndex += 1) {
    const current = [leftIndex];
    for (let rightIndex = 1; rightIndex <= right.length; rightIndex += 1) {
      const diagonal = previous[rightIndex - 1] ?? rightIndex - 1;
      const substitution =
        diagonal + (left[leftIndex - 1] === right[rightIndex - 1] ? 0 : 1);
      current[rightIndex] = Math.min(
        (previous[rightIndex] ?? rightIndex) + 1,
        (current[rightIndex - 1] ?? leftIndex) + 1,
        substitution,
      );
    }
    previous = current;
  }
  return previous[right.length] ?? left.length;
}

export function fileMatchScore(
  spokenQuery: string,
  candidatePath: string,
): number | undefined {
  const query = normalizeSpokenFileQuery(spokenQuery).replaceAll("\\", "/");
  const candidate = candidatePath.toLowerCase().replaceAll("\\", "/");
  const queryBase = path.posix.basename(query);
  const candidateBase = path.posix.basename(candidate);
  if (query.length === 0 || query.length > 500) {
    return undefined;
  }
  if (candidate === query) {
    return 0;
  }
  if (candidateBase === queryBase) {
    return 1;
  }
  if (candidate.endsWith(`/${query}`)) {
    return 2;
  }
  if (candidateBase.includes(queryBase)) {
    return 10 + candidateBase.length - queryBase.length;
  }
  if (candidate.includes(query)) {
    return 30 + candidate.length - query.length;
  }
  const distance = editDistance(queryBase, candidateBase);
  const maximumDistance = Math.max(
    1,
    Math.floor(Math.max(queryBase.length, candidateBase.length) * 0.22),
  );
  return distance <= maximumDistance ? 100 + distance : undefined;
}
