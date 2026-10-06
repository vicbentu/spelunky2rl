# The Spelunky 2 runtime for spelunky2rl, minus the game itself: Wine + DXVK, Xvfb, Playlunky
# (patched, see docker/playlunky-patch.md), the Goldberg Steam emulator and the Lua mod. The user mounts their game at /game.
# Build from the repo root:  docker build -f docker/Dockerfile -t ghcr.io/vicbentu/spelunky2rl-game:<version> .

FROM ubuntu:26.04 AS fetch
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates unzip xz-utils \
    && rm -rf /var/lib/apt/lists/*
COPY docker/versions.env docker/fetch_assets.sh /tmp/
RUN /tmp/fetch_assets.sh /opt/assets

FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      wine wine64 xvfb mesa-vulkan-drivers libvulkan1 vulkan-tools \
    && rm -rf /var/lib/apt/lists/*
# wineserver is not on PATH in Ubuntu's packaging
ENV WINEPREFIX=/opt/prefix WINEDEBUG=-all PATH=/usr/lib/x86_64-linux-gnu/wine:$PATH

COPY --from=fetch /opt/assets /opt/assets
# Prefix baked into the image; each container gets its own copy-on-write view of it.
# DXVK (not wined3d, which renders wrong colours) and no audio driver. No crash dialog: winedbg
# would wait on it forever with the game dead, and Python would only notice at startup_timeout.
RUN (Xvfb :1 -nolisten tcp & sleep 1; DISPLAY=:1 wineboot -i; wineserver -w) \
 && cp /opt/assets/dxvk/x64/*.dll "$WINEPREFIX/drive_c/windows/system32/" \
 && for d in d3d11 dxgi d3d10core d3d9 d3d8; do \
      wine reg add 'HKCU\Software\Wine\DllOverrides' /v $d /d native /f; done \
 && wine reg add 'HKCU\Software\Wine\Drivers' /v Audio /d '' /f \
 && wine reg add 'HKCU\Software\Wine\WineDbg' /v ShowCrashDialog /t REG_DWORD /d 0 /f \
 && wineserver -w && rm -rf /opt/assets/dxvk /tmp/.X1-lock /tmp/.X11-unix

# The NVIDIA container runtime injects the driver libraries but not the Vulkan ICD manifest
COPY docker/config/nvidia_icd.json /usr/share/vulkan/icd.d/nvidia_icd.json
COPY src/spelunky2rl/engine/launchers/config/ /opt/assets/config/
COPY src/spelunky2rl/mod/lua/ /opt/mod/lua/
COPY docker/entrypoint.sh /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
