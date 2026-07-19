import { cpSync, mkdirSync, rmSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const extensionRoot = join(dirname(fileURLToPath(import.meta.url)), "..");
const repositoryRoot = join(extensionRoot, "..", "..");
const runtimeRoot = join(extensionRoot, "runtime");

rmSync(runtimeRoot, { force: true, recursive: true });
mkdirSync(join(runtimeRoot, "scripts"), { recursive: true });

for (const file of ["pyproject.toml", "README.md", "config.example.json"]) {
  cpSync(join(repositoryRoot, file), join(runtimeRoot, file));
}
cpSync(join(repositoryRoot, "src"), join(runtimeRoot, "src"), {
  filter: (source) =>
    basename(source) !== "__pycache__" && !source.endsWith(".pyc"),
  recursive: true,
});
cpSync(
  join(repositoryRoot, "scripts", "chudvis-windows.ps1"),
  join(runtimeRoot, "scripts", "chudvis-windows.ps1"),
);
