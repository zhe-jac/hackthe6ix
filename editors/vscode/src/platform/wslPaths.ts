export function wslDistribution(authority: string): string | undefined {
  let decoded: string;
  try {
    decoded = decodeURIComponent(authority);
  } catch {
    return undefined;
  }
  if (!decoded.toLowerCase().startsWith("wsl+")) {
    return undefined;
  }
  const distribution = decoded.slice(4);
  if (
    distribution.length === 0 ||
    distribution.includes("/") ||
    distribution.includes("\\") ||
    distribution.includes("\0") ||
    distribution === "." ||
    distribution === ".."
  ) {
    return undefined;
  }
  return distribution;
}

export function wslUncPath(
  authority: string,
  posixPath: string,
): string | undefined {
  const distribution = wslDistribution(authority);
  if (distribution === undefined || !posixPath.startsWith("/")) {
    return undefined;
  }
  const windowsPath = posixPath.replaceAll("/", "\\");
  return `\\\\wsl.localhost\\${distribution}${windowsPath}`;
}
