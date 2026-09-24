#!/usr/bin/env bash
# Use native Windows Python/runtime through the existing PowerShell launcher.
set -euo pipefail
script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
if ! command -v cygpath >/dev/null 2>&1; then
    printf '%s\n' 'This launcher requires Cygwin (cygpath was not found).' >&2
    exit 1
fi
if ! command -v powershell.exe >/dev/null 2>&1; then
    printf '%s\n' 'Windows PowerShell (powershell.exe) must be on PATH.' >&2
    exit 1
fi
launcher=$(cygpath -aw "$script_dir/run_engine_windows.ps1")
exec powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "$launcher" "$@"
