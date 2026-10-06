#!/usr/bin/env bash
# Download and verify the pinned game-side assets (not the game) into OUT_DIR:
#   OUT_DIR/playlunky/          playlunky_launcher.exe and its DLLs, playlunky64.dll patched (see
#                               docker/playlunky-patch.md) and a PATCHED marker for the wine launcher
#   OUT_DIR/steam_api64.dll     Goldberg emulator, replaces the game's Steam API
#   OUT_DIR/dxvk/x64/           DXVK DLLs for the Wine prefix
# Used by the Dockerfile and by scripts/setup_wine.sh. Needs curl, unzip, tar, xz, sha256sum.
set -euo pipefail
OUT="${1:?usage: fetch_assets.sh OUT_DIR}"
HERE="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=versions.env
source "$HERE/versions.env"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$OUT"

fetch() {  # fetch URL SHA256 -> path of the verified file
    local file="$TMP/$(basename "$1")"
    curl -fsSL --retry 3 -o "$file" "$1"
    echo "$2  $file" | sha256sum -c --quiet - >&2 || { echo "checksum mismatch for $1" >&2; exit 1; }
    echo "$file"
}

mkdir -p "$OUT/playlunky"
unzip -qo "$(fetch "$PLAYLUNKY_URL" "$PLAYLUNKY_SHA256")" -d "$OUT/playlunky"
# je -> jmp: Playlunky enables our mod although it is unsafe (docker/playlunky-patch.md)
DLL="$OUT/playlunky/playlunky64.dll"
# the 5 bytes ending at the offset: cmp byte [rdx+0x40],0 (meta.unsafe); je
code() { od -An -tx1 -j "$((PLAYLUNKY_PATCH_OFFSET - 4))" -N5 "$DLL" | tr -d ' \n'; }
[ "$(code)" = 807a400074 ] || { echo "playlunky64.dll: unexpected code at $PLAYLUNKY_PATCH_OFFSET; redo docker/playlunky-patch.md" >&2; exit 1; }
printf '\xeb' | dd of="$DLL" bs=1 seek="$((PLAYLUNKY_PATCH_OFFSET))" conv=notrunc status=none
[ "$(code)" = 807a4000eb ]
echo "playlunky64.dll patched at $PLAYLUNKY_PATCH_OFFSET, see docker/playlunky-patch.md" > "$OUT/playlunky/PATCHED"

tar xJf "$(fetch "$SEVENZIP_URL" "$SEVENZIP_SHA256")" -C "$TMP" 7zz
"$TMP/7zz" e -y -o"$OUT" "$(fetch "$GBE_URL" "$GBE_SHA256")" 'release/regular/x64/steam_api64.dll' >/dev/null

mkdir -p "$OUT/dxvk"
tar xzf "$(fetch "$DXVK_URL" "$DXVK_SHA256")" -C "$TMP"
cp -r "$TMP"/dxvk-*/x64 "$OUT/dxvk/"

echo "assets ready in $OUT" >&2
