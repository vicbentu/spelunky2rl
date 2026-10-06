#!/usr/bin/env bash
# Prepare the host for launcher="wine" (Linux without Docker, mostly for development).
# Installs the same pinned assets as the Docker image plus a Wine prefix with DXVK into
# ${SPELUNKY2RL_WINE_HOME:-~/.local/share/spelunky2rl/wine}.
# Needs: wine (Ubuntu: apt install wine), Xvfb, curl, unzip, xz-utils.
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
HOME_DIR="${SPELUNKY2RL_WINE_HOME:-${XDG_DATA_HOME:-$HOME/.local/share}/spelunky2rl/wine}"
for tool in wine Xvfb curl unzip; do
    command -v "$tool" >/dev/null || { echo "missing $tool" >&2; exit 1; }
done
WINESERVER="$(command -v wineserver || echo /usr/lib/x86_64-linux-gnu/wine/wineserver)"

mkdir -p "$HOME_DIR"
"$REPO/docker/fetch_assets.sh" "$HOME_DIR"

export WINEPREFIX="$HOME_DIR/prefix" WINEDEBUG=-all
if [ ! -d "$WINEPREFIX" ]; then
    Xvfb :1789 -nolisten tcp >/dev/null 2>&1 & XVFB=$!
    DISPLAY=:1789 wineboot -i
    "$WINESERVER" -w
    kill "$XVFB"
fi
cp "$HOME_DIR"/dxvk/x64/*.dll "$WINEPREFIX/drive_c/windows/system32/"
for d in d3d11 dxgi d3d10core d3d9 d3d8; do
    wine reg add 'HKCU\Software\Wine\DllOverrides' /v "$d" /d native /f >/dev/null
done
wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /d '' /f >/dev/null
# a crash dialog would keep the dead game's process alive until startup_timeout
wine reg add 'HKCU\Software\Wine\WineDbg' /v ShowCrashDialog /t REG_DWORD /d 0 /f >/dev/null
"$WINESERVER" -w
# Per-instance prefixes are copies of this one; drop stale copies so they pick up changes
rm -rf "$HOME_DIR/prefixes"
echo "Wine setup ready in $HOME_DIR. Use launcher='wine' (or SPELUNKY2RL_LAUNCHER=wine)."
