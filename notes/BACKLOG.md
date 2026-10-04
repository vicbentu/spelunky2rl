# Backlog

Todo lo no empezado: `- [ts @sha] contexto suficiente para retomarlo en frío`. El sha es el commit en que
estaba el código al escribirlo (`git show <sha>:<ruta>`). *Next* es lo elegido, en orden; lo primero es lo
que pasa a `PLAN.md` cuando acabe el objetivo en marcha. Después, según cuánto se sabe: Bugs (algo está
mal), Improvements (se sabe exactamente qué hacer, solo falta el cuándo), Ideas (vale la pena mirarlo; aún
no se sabe si ni cómo). Se borran al hacerlas o descartarlas (git es el archivo).

## Next

- [2026-09-28 12:53 @f5809d2] Reentrenar `get_to_exit` con el contrato corregido (terminated/truncated, seed
  reproducible, entrada en `PRE_UPDATE`); el primer intento (`~/Desktop/tmp/spelunky2rl-runs/train_2026-09-28/`, 0 % de
  éxito a 2,6 M pasos, 333 pasos/s) se hizo antes de arreglar la entrada.
- [2026-09-28 12:53 @f5809d2] Comparar con los modelos de mayo de 2025: no están en esta máquina, hay que
  copiarlos desde el PC de Windows.
- [2026-09-28 13:53 @ce9dcf6] `examples/record_video.py` de punta a punta con un modelo entrenado (último
  pendiente de headless/render).
- [2026-09-30 00:20 @222ac52] Publicar la imagen del juego (tag `v<versión>` →
  `.github/workflows/docker.yml`); pendiente de push, ver `Q/game-image-unpublished` en `QUESTIONS.md`.

## Bugs

- [2026-09-28 13:53 @ce9dcf6] La interfaz de Overlunky (barra de menú + línea de contadores
  "FRAME/START/TOTAL…", ~40 px arriba) sale en los frames de `render()`. Probado sin éxito:
  `draw_hud/draw_hotbar/draw_script_messages = 0` y `tabs_open = []` en `overlunky.ini`; un `imgui.ini`
  propio; F11 (`hide_ui`) con `xdotool windowfocus key F11`; `imgui_playlunky.ini` con la ventana en
  `Pos=-5000,-5000` y `Collapsed=1` hace que el juego caiga con un page fault. `hide_ui` solo se cambia
  con la tecla (`src/injected/ui.cpp` de overlunky). Vías sin probar: recortar las filas superiores en
  `X11FrameSource`, pedir upstream una opción de ini, o capturar dentro del juego (Fase 6 del plan
  antiguo, ver Ideas).
- [2026-09-30 00:17 @222ac52] `main.lua`: `count_dead_enemies` solo mira la capa frontal (enemigos
  muertos en la capa trasera no cuentan). Hoy `dead_enemies` en `spelunky2rl/observations.lua`.
- [2026-10-01 20:52 @2880e06] `main.lua`, `pf_refresh`: `get_entities_by(0, MASK.FLOOR, 0)` solo lee la
  capa frontal (0 = `LAYER.FRONT`). Con el jugador en la capa trasera, `pf_tile_lookup[1]` no existe y
  `map_info` sale todo a 0; `dist_to_goal` se busca en el tablero de la capa frontal. Leído en el
  código, sin reproducir (entrar por una puerta a la capa trasera y mirar `map_info`). Mismo origen que
  el de `count_dead_enemies`. Hoy `refresh` en `spelunky2rl/pathfinding.lua`.
- [2026-10-03 14:05 @766e650] Suite de integración: un `ConnectionResetError: [Errno 104]` en 1 de 6
  ejecuciones completas (`pytest tests/integration` con `SPELUNKY2RL_DEV_MOD`, árbol con los arreglos
  de `dist_to_goal` sin commitear); esa ejecución tardó 256 s en vez de ~89 s y las cinco siguientes
  pasaron 7/7. No guardé qué test fue ni la salida del juego. `ConnectionResetError` es el proceso del
  juego muerto, no un error de Lua (eso sería `RuntimeError`). Para cazarlo: repetir la suite en bucle
  guardando la salida completa y `launcher.diagnostics()` del entorno que falle.

## Improvements

- [2026-09-28 12:53 @abf1a96] Comprobar la versión de `Spel2.exe` al arrancar y fallar con un mensaje
  claro si no es la que soportan las versiones fijadas de Playlunky/Overlunky (hoy una actualización del
  juego rompe los offsets y el síntoma es que el mod no carga: timeout sin explicación). `spelunky2rl
  doctor` ya calcula el hash de build (`15a31692700c3c94` en esta máquina): guardar la lista de hashes
  soportados junto a las versiones fijadas de la imagen, comprobarla antes de lanzar y en `doctor`, y
  decir en el error qué build tiene el usuario y cuál espera la imagen. Venía de la tabla de riesgos
  del plan de retoma.
- [2026-09-28 15:38 @9f537a6] Resolución de `render()` configurable (hoy fija en 640x360). La deciden dos
  cosas que deben coincidir: el tamaño de pantalla de Xvfb (`docker/entrypoint.sh` y `WineLauncher`,
  `640x360x24`) y `local.cfg` (`engine/launchers/config/local.cfg`: ventana `window_mode=2` al
  `window_scale=100` % de la pantalla; `resolutionx/y`). Propuesta: parámetro `render_resolution=(w, h)`
  → variable `RESOLUTION` al contenedor → el entrypoint arranca Xvfb a ese tamaño y escribe `local.cfg`
  a juego. Sin probar: que `window_scale=100` llene pantallas mayores (sí lo hace a 640x360) y el coste
  de render (GPU poco; con `renderer="cpu"` crece con los píxeles). Solo afecta con `render_enabled`.
- [2026-09-30 22:59 @df58df3] Ruta del juego permanente y configurable desde el CLI. Hoy solo existe
  `game_dir=` o `SPELUNKY2RL_GAME_DIR` (resuelto en `make_launcher`, `engine/launchers/__init__.py`); no
  hay fichero de configuración y el `export` se pierde al cerrar la terminal (`docs/getting-started.md`
  dice "once", lo que es engañoso). Propuesta: `spelunky2rl config set game-dir <ruta>` (valida
  `Spel2.exe` como `doctor`) que escribe `~/.config/spelunky2rl/config.toml` (`XDG_CONFIG_HOME`),
  `config get/show`, y `make_launcher`/`doctor` lo leen como último recurso: `game_dir=` > variable de
  entorno > fichero. Podría cubrir también `launcher`, `image` y `renderer`. Actualizar la guía y
  `doctor` (que diga de dónde sale cada valor).
- [2026-10-01 20:52 @2880e06] `main.lua`, `get_info`: `powerups[value-545+1] = 1` usa el id numérico de
  `ITEM_POWERUP_PASTE`. Usar `ENT_TYPE.ITEM_POWERUP_PASTE` e ignorar los ids fuera de 545-562: hoy uno
  fuera de rango escribiría fuera de las 18 posiciones y `json.encode` dejaría de mandar una lista de 18.
  Hoy `read_player` en `spelunky2rl/observations.lua` (`FIRST_POWERUP`).
- [2026-10-01 22:06 @c8443f9] `main.lua`: la línea `package.path = "lua/?.lua;" .. package.path` parece no hacer nada.
  Con un submódulo de prueba, `require("spelunky2rl.probe")` resolvió *antes* de esa línea (lo resuelve
  el `require` de Overlunky, relativo a la carpeta del script), `lua/` no existe respecto al directorio
  de trabajo del juego (`io.open("lua/spelunky2rl/probe.lua")` da `nil`) y luasocket carga su DLL con
  `package.loadlib` y la ruta de `script_path.lua`. Quitarla y pasar
  `tests/integration`. Solo probado bajo Wine en Docker; no la quité en la reorganización porque no
  puedo probarlo en Windows nativo.
- [2026-10-03 22:25 @e9148d6] Al publicar en PyPI, en el mismo commit que prepara la versión y justo antes de crear el tag: subir a
  `0.1.1` `__version__` (`src/spelunky2rl/version.py`) y `MOD_VERSION`
  (`src/spelunky2rl/mod/lua/spelunky2rl/protocol.lua:8`; solo sale en el mensaje de error de
  `check_hello`). `v0.1.0` ya existe y es anterior a la licencia MIT. El tag `v0.1.1` dispara
  `docker.yml` (imagen `spelunky2rl-game:0.1.1`, que es la que pide `DEFAULT_IMAGE` en
  `engine/launchers/docker.py`) y `pypi.yml`: los dos workflows comprueban que tag y versión coinciden.

## Ideas

- [2026-09-28 13:53 @ce9dcf6] Con `renderer="cpu"` (lavapipe) cada contenedor usa ~2,8 GiB de RAM frente
  a ~1 GiB con GPU: con 16 instancias, ~45 GiB frente a ~16, lo que limita cuántas caben en una máquina
  sin GPU. Mirar de dónde sale (hilos de llvmpipe por contenedor, `LP_NUM_THREADS`; cachés de shaders de
  DXVK/Mesa) y si se puede bajar sin perder pasos/s. Sin investigar.
- [2026-10-01 00:53 @4cdc78a] Revisar el mecanismo de velocidad (`speedup` + `state_updates`), hecho a
  mano en su día. Hoy: `set_speedhack(100)` y, en cada `POST_UPDATE` del motor, `update_state()`
  `state_updates` veces (final de `on_post_update` en `spelunky2rl/session.lua`; solo con `speedup=True`). La idea es amortizar
  el coste fijo de cada frame del motor (`Present` de DXVK, UI de Overlunky, bucle de Wine), que
  `render=False` no quita: solo evita dibujar nivel y HUD (+18 % a `state_updates=0`). Sin medir:
  pasos/s con `render=False` y `state_updates` = 0/10/50/200, ni si hay una vía mejor (p. ej. un
  bucle propio de `update_state()` mientras Python manda pasos, sin volver al motor, o quitar el
  speedhack si `state_updates` ya lo cubre). Si `state_updates` alto es siempre mejor, quizá no debería
  ser un parámetro del usuario.
- [2026-10-01 00:55 @7ce4428] Estandarizar el contrato de datos Python ↔ Lua (opciones y observación).
  Es un cambio de protocolo (subir `PROTOCOL_VERSION`). Hoy: las opciones de `reset` son una lista fija
  en `_game_reset` (`engine/core.py`; un nombre desconocido es `TypeError`); `data_to_send` es una lista
  de strings sin validar (`map_info`, `entity_info`, `dist_to_goal`, y `custom_info`, que siempre manda
  `""`); `step` lo lee con `getattr(self, "data_to_send", [])` y `reset` con `self.data_to_send`;
  `basic_info` va entero en cada paso aunque el entorno no lo use; formatos fijos (`map_info` 11x21,
  `entity_info` de 7 campos) sin parámetros ni descripción formal. Ideas: esquema único de opciones y
  campos (con valores por defecto y validación en Python), pedir solo los campos que usa la
  observación, tamaños configurables, documentar el formato. Medir antes: coste por campo en Lua
  (`map_info` +150 µs/paso, `entity_info` +110 µs, `dist_to_goal` ~0) y en `json.encode`.
  Relacionado: el protocolo binario, más abajo.
- [2026-09-30 00:20 @222ac52] Protocolo binario (`string.pack` / `numpy.frombuffer`): techo estimado
  15-25 % en entornos con `map_info`; hoy no compensa: ~92 % del paso es esperar al juego (medido en
  7dc9904). Mirar de nuevo si el mecanismo de velocidad (arriba) cambia ese reparto.
- [2026-09-28 14:02 @996066a] Render por memoria compartida con número de secuencia, solo si se quieren
  píxeles como observación (hoy `render()` lee el Xvfb con mss).
- [2026-09-28 14:02 @996066a] Captura dentro del juego enganchando `IDXGISwapChain::Present`, mismo caso
  que el anterior; también quitaría la barra de Overlunky de los frames (ver Bugs).
- [2026-10-01 20:52 @2880e06] `reset` en `main.lua`: espera fija de 60 frames tras el `warp` antes de
  aplicar `destroy_entities`/`set_start_values` y mandar el estado. Si a los 60 frames no hay jugador,
  `set_start_values` indexa `players[1]` (`nil`) y falla. Mirar si se puede esperar a que el nivel esté
  cargado (`state.screen == SCREEN.LEVEL` y `#players > 0`) en vez de contar frames, y cuánto acorta el
  reset. De paso, revisar qué estado no se reinicia en `reset`: `transition`
  y los últimos valores del jugador. Hoy `RESET_FRAMES`, `start` y `answer` en `spelunky2rl/session.lua`.
- [2026-10-01 21:00 @2880e06] `get_to_exit` corta el episodio con -5 si la distancia mínima a la salida
  no mejora en 200 pasos (`envs/get_to_exit.py`, `no_improve_counter`; 20 s de juego con
  `frames_per_step=6`). `dist_to_goal` es una BFS en 4 direcciones por celdas no sólidas
  (`distance_field` en `spelunky2rl/pathfinding.lua`): mide como si el jugador volara, así que el mínimo puede
  alcanzarse al pie de un pozo que no se puede subir. Si el camino real es un rodeo de más de 200 pasos,
  el entorno lo corta y el agente no puede aprenderlo. La recompensa por acercarse (`*0.1` sobre la
  diferencia de distancias) no es el problema: es una diferencia de potencial y no cambia la política
  óptima. Mirar solo si el reentrenamiento (ver Next) se atasca: contar cuántos episodios acaban por
  este corte y dónde está el jugador.
- [2026-10-03 22:25 @e9148d6] Limpieza de lo que no es la librería. El paquete son los entornos Gymnasium; entrenar, evaluar y
  grabar vídeo son demos que en algún momento se quitarán o se irán a otro sitio, y sus dependencias
  (torch, stable-baselines3, sb3-contrib, opencv, tensorboard) no deben pesar sobre la librería.
  Inventario: `examples/train_get_to_exit.py`, `evaluate_model.py`, `record_video.py` y
  `benchmark_performance.py` importan SB3 (este solo `SubprocVecEnv`); `manual_control.py` no. Extras
  `train`, `video` y `all` en `pyproject.toml`; menciones en `examples/README.md` (incl. `tensorboard
  --logdir`), `docs/getting-started.md` l. 36 (`[train]`) y `docs/architecture.md` l. 608. Los tests
  (`tests/unit`, `tests/integration`) no importan nada de eso. Decidir: qué demos quedan (¿solo
  `manual_control` y un benchmark sin SB3, con el `VectorEnv` de Gymnasium?), adónde van las de
  entrenamiento (otro repo, `examples/` fuera del paquete sin extras, o borrarlas tras el
  reentrenamiento de Next, que hoy las usa), y si sobran extras. Repasar también tests y scripts
  (`scripts/`, `feasibility/`) que ya no sirvan.
