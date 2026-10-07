#!/usr/bin/env bash
# One container = one game instance. Started and killed by spelunky2rl's DockerLauncher.
#   env:    PORT (required)   TCP port on 127.0.0.1 where Python waits for the Lua mod
#           DISPLAYNUM        X display for this instance's Xvfb (unique per host: --network host
#                             shares X's abstract sockets between containers)
#           RENDERER          "cpu" forces lavapipe; anything else lets Vulkan pick (GPU if passed in)
#           SCREEN            WxH of the Xvfb screen, which the game fills (default 640x360)
#           SPELUNKY2RL_CAPTURE_LAYER=1, SPELUNKY2RL_CAPTURE=<file>
#                             optional, the Vulkan layer copies every presented frame to <file>
#   mounts: /game (ro)        the user's Spelunky 2 folder
#           /cache (rw)       optional, Playlunky's converted-assets cache shared between instances
#           /opt/mod/lua      optional dev mount over the bundled Lua mod
#           /capture (rw)     optional, where SPELUNKY2RL_CAPTURE points (with render)
set -euo pipefail
: "${PORT:?PORT is required}"
DISPLAYNUM="${DISPLAYNUM:-99}"
SCREEN="${SCREEN:-640x360}"
[ -f /game/Spel2.exe ] || { echo "spelunky2rl: no Spel2.exe in /game; mount your Spelunky 2 folder there" >&2; exit 2; }

# Per-instance game dir: symlinks to the read-only game, real files for what we provide or the game writes
I=/run/inst
mkdir -p "$I/Mods/Packs"
for f in /game/*; do
    case "$(basename "$f")" in
        steam_api64.dll|steam_appid.txt|steam_settings|playlunky.ini|local.cfg|Mods) ;;
        spelunky.log|full_output.log) ;;
        settings.cfg|savegame.sav|input.cfg) cp "$f" "$I/" ;;
        *) ln -s "$f" "$I/" ;;
    esac
done
A=/opt/assets
ln -s "$A/steam_api64.dll" "$I/steam_api64.dll"
echo 418530 > "$I/steam_appid.txt"
mkdir -p "$I/steam_settings" && echo 418530 > "$I/steam_settings/steam_appid.txt"
# local.cfg holds the video settings: a borderless window filling the Xvfb screen and drawn at its
# size whatever resolutionx/y say (fullscreen under Wine+Xvfb leaves the Vulkan surface at 1x1 and
# every frame black; a framed window leaves a black band where the title bar would be), no vsync,
# no audio
cp "$A/config/playlunky.ini" "$A/config/local.cfg" "$I/"
# Playlunky runs the pack's main.lua (patched to allow it, see docker/playlunky-patch.md) and writes
# inside mod folders; the pack only holds lua/ so there is nothing for it to convert
ln -s /opt/mod "$I/Mods/Packs/spelunky2rl"
echo spelunky2rl > "$I/Mods/Packs/load_order.txt"
[ -d /cache ] && ln -s /cache "$I/Mods/Packs/.db"

if [ "${RENDERER:-auto}" = cpu ]; then
    # lavapipe; the manifest name varies between distributions (lvp_icd.json, lvp_icd.x86_64.json)
    LVP="$(ls /usr/share/vulkan/icd.d/lvp_icd*.json | head -n1)"
    export VK_DRIVER_FILES="$LVP" VK_ICD_FILENAMES="$LVP"
fi
Xvfb ":$DISPLAYNUM" -screen 0 "${SCREEN}x24" -nolisten tcp >/dev/null 2>&1 &
export DISPLAY=":$DISPLAYNUM" Spelunky_RL_Port="$PORT"
echo "spelunky2rl: port=$PORT display=:$DISPLAYNUM vulkan=$(vulkaninfo --summary 2>/dev/null | grep -m1 deviceName | cut -d= -f2 | xargs)"

cd "$A/playlunky"
wine playlunky_launcher.exe '--exe_dir=Z:\run\inst'
# The launcher exits as soon as Spel2.exe is running; keep the container alive with the game
wineserver -w
