# Backlog

Todo lo no empezado: `- [ts @sha] contexto suficiente para retomarlo en frío`. El sha es el commit en que
estaba el código al escribirlo (`git show <sha>:<ruta>`). Por secciones, según cuánto se sabe: Bugs (algo está mal),
Improvements (se sabe exactamente qué hacer, solo falta el cuándo), Ideas (vale la pena mirarlo; aún no se
sabe si ni cómo). Se borran al hacerlas o descartarlas (git es el archivo).

## Bugs

- [2026-09-30 00:17 @222ac52] `main.lua`: `count_dead_enemies` solo mira la capa frontal (enemigos
  muertos en la capa trasera no cuentan). Hoy `dead_enemies` en `spelunky2rl/observations.lua`.
- [2026-10-01 20:52 @2880e06] `main.lua`, `pf_refresh`: `get_entities_by(0, MASK.FLOOR, 0)` solo lee la
  capa frontal (0 = `LAYER.FRONT`). Con el jugador en la capa trasera, `pf_tile_lookup[1]` no existe y
  `map_info` sale todo a 0; `dist_to_goal` se busca en el tablero de la capa frontal. Leído en el
  código, sin reproducir (entrar por una puerta a la capa trasera y mirar `map_info`). Mismo origen que
  el de `count_dead_enemies`. Hoy `refresh` en `spelunky2rl/pathfinding.lua`.
- [2026-10-04 20:39 @188a940] `manual_control=True` no sirve con los launchers actuales: el mod solo deja de escribir la
  entrada del agente (`input.lua`) para que el juego lea el teclado, pero `docker` y `wine` corren el
  juego en un Xvfb que nadie ve y al que no llega ninguna tecla; el jugador se queda quieto.
  `examples/manual_control.py` y `getting-started.md` (l. 198-222) prometen jugar con el teclado.
  Arreglarlo (VNC con `x11vnc` al Xvfb, o en `wine` usar el `DISPLAY` del host) o quitar la opción.
- [2026-10-07 14:57 @463aef0] `envs/get_to_exit.py`: `min_dist_to_goal` y `no_improve_counter` solo se reinician al
  acabar el episodio (`done or truncated`), no en `reset()`. Si se llama a `reset()` a mitad de un
  episodio (p. ej. evaluaciones con un límite de pasos propio, o `AsyncVectorEnv` tras un error), el
  episodio siguiente arrastra el mínimo y el contador del anterior y se trunca antes de 200 pasos sin
  mejorar. Visto al repetir 500 pasos con `reset(seed=3)` dos veces en el mismo entorno: la segunda
  tanda se truncó en el paso 199. Arreglo: reiniciarlos en `reset` (o en `gamestate_to_observation`
  del primer estado) y un test unitario.

## Improvements

- [2026-09-28 12:53 @abf1a96] Comprobar la versión de `Spel2.exe` al arrancar y fallar con un mensaje
  claro si no es la que soporta la versión fijada de Playlunky (hoy una actualización del
  juego rompe los offsets y el síntoma es que el mod no carga: timeout sin explicación). `spelunky2rl
  doctor` ya calcula el hash de build (`15a31692700c3c94` en esta máquina): guardar la lista de hashes
  soportados junto a las versiones fijadas de la imagen, comprobarla antes de lanzar y en `doctor`, y
  decir en el error qué build tiene el usuario y cuál espera la imagen. Venía de la tabla de riesgos
  del plan de retoma.
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
  el `require` del motor de scripts, relativo a la carpeta del script), `lua/` no existe respecto al directorio
  de trabajo del juego (`io.open("lua/spelunky2rl/probe.lua")` da `nil`) y luasocket carga su DLL con
  `package.loadlib` y la ruta de `script_path.lua`. Quitarla y pasar
  `tests/integration`. Solo probado bajo Wine en Docker; no la quité en la reorganización porque no
  puedo probarlo en Windows nativo.

## Ideas

- [2026-09-28 13:53 @ce9dcf6] Con `renderer="cpu"` (lavapipe) cada contenedor usa ~2,8 GiB de RAM frente
  a ~1 GiB con GPU: con 16 instancias, ~45 GiB frente a ~16, lo que limita cuántas caben en una máquina
  sin GPU. Mirar de dónde sale (hilos de llvmpipe por contenedor, `LP_NUM_THREADS`; cachés de shaders de
  DXVK/Mesa) y si se puede bajar sin perder pasos/s. Sin investigar.
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
  óptima. Mirar solo si un entrenamiento (en `spelunky2rl-experiments`) se atasca: contar cuántos episodios acaban por
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
  entrenamiento (otro repo, `examples/` fuera del paquete sin extras, o borrarlas), y si sobran extras. Repasar también tests y scripts
  (`scripts/`) que ya no sirvan.
- [2026-10-06 12:09 @dbca4b8] Con vistas grandes el paso lo domina recoger `map_info` en Lua, no la comunicación (ya en
  binario). Medido con `GetToExit` y `map_info` + `entity_info` + `dist_to_goal` (speedup,
  `state_updates=50`): 21x11 0,52 ms/paso, 81x41 0,95, 161x121 2,46; de esos ~1,9 ms extra, empaquetar
  y leer son ~0,35 y recorrer las casillas en `map_info` (`observations.lua`) ~0,9. Idea: el mapa de
  tiles solo cambia cuando `pathfinding` lo marca sucio; mandar el nivel entero solo entonces (o los
  cambios) y que Python recorte la vista con numpy, así el tamaño de la vista no cuesta nada por paso.
  Cambia el protocolo (un campo que no llega en cada estado). Solo vale la pena si alguien usa vistas
  grandes. Script: `~/Desktop/tmp/spelunky/steps_wide.py`.
- [2026-10-06 15:58 @792f303] Spel2.exe muere al arrancar en ~1 % de los arranques (3 de 320 con 8 en paralelo; 3 de
  ~320 también en la suite, en serie), antes de que el mod conecte: page fault `execute access to
  0000000000000000` o `read access` en `6FFFF36F....` (una DLL de Wine), justo tras crear el swapchain
  de DXVK (`Image count: 3`), o sin mensaje. Desde que la imagen no muestra el diálogo de crash de
  winedbg el contenedor sale y `_launch_and_accept` relanza en segundos: cuesta ~10 s y solo falla si
  pasa `max_launch_attempts` (3) veces seguidas. Causa sin investigar (¿la inyección de
  Playlunky compitiendo con el arranque? medido cuando también se inyectaba Overlunky); el backtrace de winedbg no llega a la salida del
  contenedor, probar con `WINEDEBUG=+seh`. Scripts en `~/Desktop/tmp/spelunky/connreset/` (`stress.py`
  N_WORKERS N_ARRANQUES, `capture_plugin.py` guarda la salida de cada contenedor, `crashes.sh`).
