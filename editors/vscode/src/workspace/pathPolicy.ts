import * as path from "node:path";

const EXCLUDED_SEGMENTS = new Set([
  ".git",
  ".hg",
  ".svn",
  ".venv",
  "venv",
  "env",
  "node_modules",
  "dist",
  "build",
  "coverage",
  "vendor",
  "__pycache__",
]);
const BINARY_EXTENSIONS = new Set([
  ".7z",
  ".a",
  ".avi",
  ".bin",
  ".bmp",
  ".bz2",
  ".class",
  ".dll",
  ".dylib",
  ".exe",
  ".gif",
  ".gz",
  ".ico",
  ".jar",
  ".jpeg",
  ".jpg",
  ".mov",
  ".mp3",
  ".mp4",
  ".o",
  ".onnx",
  ".pdf",
  ".png",
  ".pyc",
  ".so",
  ".tar",
  ".wav",
  ".webp",
  ".zip",
]);

export const WORKSPACE_FILE_EXCLUDE =
  "**/{.git,.hg,.svn,.venv,venv,node_modules,dist,build,coverage,vendor,__pycache__}/**";

export function normalizeRelativePath(value: string): string {
  const normalized = value.trim().replaceAll("\\", "/");
  if (
    normalized.length === 0 ||
    normalized.length > 500 ||
    normalized.startsWith("/") ||
    /^[A-Za-z]:/u.test(normalized)
  ) {
    throw new Error("Workspace path must be a bounded relative path");
  }
  const segments = normalized.split("/");
  if (
    segments.some(
      (segment) => segment === "" || segment === "." || segment === "..",
    )
  ) {
    throw new Error("Workspace path contains an unsafe segment");
  }
  return segments.join("/");
}

export function isExcludedWorkspacePath(relativePath: string): boolean {
  const normalized = relativePath.replaceAll("\\", "/");
  const segments = normalized.split("/");
  const base = (segments.at(-1) ?? "").toLowerCase();
  if (
    segments.some((segment) => EXCLUDED_SEGMENTS.has(segment.toLowerCase()))
  ) {
    return true;
  }
  if (
    base.startsWith(".env") ||
    [
      ".netrc",
      ".npmrc",
      ".pypirc",
      "authorized_keys",
      "id_dsa",
      "id_ed25519",
      "id_rsa",
    ].includes(base) ||
    /(?:credential|credentials|secret|secrets)(?:\.|$)/iu.test(base) ||
    /(?:^|\.)(?:pem|key|p12|pfx|jks|keystore)$/iu.test(base)
  ) {
    return true;
  }
  return BINARY_EXTENSIONS.has(path.posix.extname(base));
}
