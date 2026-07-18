#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${WSL_DISTRO_NAME:-}" && ! -e /proc/sys/fs/binfmt_misc/WSLInterop ]]; then
    echo "This launcher must be run from WSL." >&2
    exit 2
fi

if ! command -v powershell.exe >/dev/null 2>&1; then
    echo "Windows PowerShell interop is unavailable in this WSL session." >&2
    exit 2
fi

if ! command -v wslpath >/dev/null 2>&1; then
    echo "wslpath is unavailable; cannot translate the launcher path for Windows." >&2
    exit 2
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
windows_launcher="$(wslpath -w "$script_dir/gazemotion-windows.ps1")"

exec powershell.exe \
    -NoLogo \
    -NoProfile \
    -NonInteractive \
    -ExecutionPolicy Bypass \
    -File "$windows_launcher" \
    "$@"
