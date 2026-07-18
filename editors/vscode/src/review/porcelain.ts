export function parsePorcelain(output: string): string[] {
  const entries = output.split("\0");
  const paths: string[] = [];
  for (let index = 0; index < entries.length; index += 1) {
    const entry = entries[index];
    if (entry === undefined || entry.length < 4) {
      continue;
    }
    const status = entry.slice(0, 2);
    paths.push(entry.slice(3));
    if (status.includes("R") || status.includes("C")) {
      index += 1;
    }
  }
  return paths;
}
