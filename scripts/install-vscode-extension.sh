#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
project_root="$(cd -- "$script_dir/.." && pwd)"
extension_dir="$project_root/editors/vscode"

(
    cd "$extension_dir"
    npm ci
    npm run verify
    npm run package
)

if [[ -n "${WSL_DISTRO_NAME:-}" || -e /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    if ! command -v powershell.exe >/dev/null 2>&1; then
        echo "Windows PowerShell interop is unavailable in this WSL session." >&2
        exit 2
    fi
    if ! command -v wslpath >/dev/null 2>&1; then
        echo "wslpath is unavailable; cannot locate the Windows installer." >&2
        exit 2
    fi
    windows_installer="$(wslpath -w "$script_dir/install-vscode-extension.ps1")"
    exec powershell.exe \
        -NoLogo \
        -NoProfile \
        -NonInteractive \
        -ExecutionPolicy Bypass \
        -File "$windows_installer"
fi

if ! command -v code >/dev/null 2>&1; then
    echo "VS Code CLI was not found on PATH." >&2
    exit 2
fi
exec code --install-extension "$extension_dir/gazemotion-vscode.vsix" --force
