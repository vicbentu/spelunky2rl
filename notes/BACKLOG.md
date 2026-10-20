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
- [2026-10-04 20:39 @188a940] `manual_control=True` no sirve con el launcher de Docker: el mod solo deja de escribir la
  entrada del agente (`input.lua`) para que el juego lea el teclado, pero el contenedor corre el
  juego en un Xvfb que nadie ve y al que no llega ninguna tecla; el jugador se queda quieto.
  `examples/manual_control.py` y `getting-started.md` (l. 198-222) prometen jugar con el teclado.
  Arreglarlo (VNC con `x11vnc` al Xvfb) o quitar la opción.
- [2026-10-07 14:57 @463aef0] `envs/get_to_exit.py`: `min_dist_to_goal` y `no_improve_counter` solo se reinician al
  acabar el episodio (`done or truncated`), no en `reset()`. Si se llama a `reset()` a mitad de un
  episodio (p. ej. evaluaciones con un límite de pasos propio, o `AsyncVectorEnv` tras un error), el
  episodio siguiente arrastra el mínimo y el contador del anterior y se trunca antes de 200 pasos sin
  mejorar. Visto al repetir 500 pasos con `reset(seed=3)` dos veces en el mismo entorno: la segunda
  tanda se truncó en el paso 199. Arreglo: reiniciarlos en `reset` (o en `gamestate_to_observation`
  del primer estado) y un test unitario.
- [2026-10-07 23:09 @ab0152c] `tests/integration/test_game.py::test_parallel_envs[4]` (4 `GetToExit` sin render en
  `AsyncVectorEnv`, 500 pasos) falló 2 veces de 46.
  - El primer fallo fue en la suite completa: `TimeoutError: No response from the Spelunky Lua
    script in 60.0 s` en un `step` de uno de los workers.
  - El segundo fue el test solo, a los 20 s (lo que dura uno que pasa). No se guardó qué assert falló.
  - Los dos fueron en las primeras ejecuciones tras reconstruir la imagen `0.1.3.dev0` (paso 6 de
    "Velocidad y render").
  - Después, 0 fallos de 35: 10 con el mod de `ab0152c` montado con `SPELUNKY2RL_DEV_MOD`, 10 con el
    nuevo y 15 más.
  - Sin render, el mod nuevo hace lo mismo que el de `ab0152c`.
  - Para reproducirlo, repetir el test con `-rA` guardando la salida, y mirar si es un cuelgue del
    juego (Spel2.exe vivo pero sin responder) o la muerte de Spel2.exe a mitad (ver la idea de los
    arranques que mueren).

- [2026-10-13 15:09 @e791351] `DockerLauncher` deja directorios `spelunky2rl-capture-*` en `/dev/shm` cuando el proceso
  muere sin llegar a `stop()` (workers `daemon` de un entrenamiento matado): el 2026-10-13 había 15, de
  los que solo 7 eran de contenedores vivos (los más viejos del 2026-10-09). Cada uno guarda un frame
  por slot (2 MB × 6 a 960x540 con `rgb_array_list`) en RAM hasta reiniciar. Ideas: borrarlo desde el
  propio contenedor al salir (`entrypoint.sh`, trap), o limpiar al arrancar los que no monte ningún
  contenedor vivo. Creación y borrado en `engine/launchers/docker.py` (`mkdtemp` en `start`,
  `rmtree` en `stop`).
- [2026-10-16 11:46 @f465d05] Con `renderer="cpu"`, lavapipe (Mesa 26.0.8 en la imagen) pierde un `llvmpipe_resource` de
  0x220 B por command buffer, ~0,53 KB por present en un arena de glibc (~530 MB por millón de pasos
  por juego): `handle_vertex_buffers2` (`src/gallium/frontends/lavapipe/lvp_execute.c:1112`) crea un
  recurso temporal en cada bind de vertex buffer con tamaño explícito y `lvp_execute_cmds` no
  libera el último al acabar (`:5394-5420`). Lo dispara DXVK; `vkcube` no pierde nada. Medido con un
  tracer de malloc por `LD_PRELOAD` (scratchpad de la sesión del 2026-10-16, `forensics/mtrace/` y
  `bisect/mt/`). No encarece el paso: 3 juegos en lockstep con `cpu_threads=4` y el `msvcp140` del
  juego, 10,0 → 9,9 ms por paso de 10k a 410k pasos por juego, con +233 MiB por juego. Falta: mirar
  si Mesa main lo arregla (si no, reportarlo).
- [2026-10-16 11:46 @f465d05] El array del registro de Lua gana ~1 entrada (valor 1) por paso con render: 50.835 a los 50k
  pasos y 96.585 a los 95k (heap walk del 2026-10-16), con o sin el overlay de Playlunky. Algo hace
  `luaL_ref` sin `luaL_unref` en cada paso (Overlunky, sol2 o una llamada del mod): ~28 B por paso,
  no explica la deriva. Para encontrarlo: `#debug.getregistry()` antes y después de cada llamada
  que hace el mod en un paso (`observations.collect`, `input.apply`, `update_state`...).

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
- [2026-10-16 02:07 @1ef894b] From "Rendimiento": `benchmarks/throughput.py` parte el paso en send, game, frame y python,
  pero `game` junta el mod, los frames de lógica y el dibujo. Medido aparte: el intercambio con Python
  42 µs (`ping`), los 6 frames de lógica sin dibujar ~0,5 ms, dibujar el nivel ~0,4 ms y el callback
  `RENDER_POST_HUD` ~0,15 ms. Para tenerlo en el benchmark: una opción de reset `profile=True` con la que
  el mod añade a la cabecera de cada estado duraciones medidas con `get_performance_counter()` (el QPC
  real, sin el speedhack): desde que recibe el comando hasta acabar `run_logic_frames`, hasta
  `pending = drawn`, hasta `RENDER_POST_HUD`, hasta el `PRE_GAME_LOOP` que contesta, y `collect()`;
  el motor las deja en `info["timing"]` y el benchmark las suma. La capa de captura puede escribir
  sus tiempos (`clock_gettime(CLOCK_MONOTONIC)`, comparables con los de Python) en los 32 bytes libres
  de la cabecera de cada slot (`capture.c`, `SLOT_SIZE`).
- [2026-10-19 12:36 @f3709dc] From "Quitar el launcher wine": desde que se quitó `engine/assemble.py`, nada en el paquete lee
  `mod/` ni `engine/launchers/config/` en tiempo de ejecución; el `Dockerfile` los copia del árbol de
  fuentes (`COPY src/spelunky2rl/mod/lua/` y `COPY src/spelunky2rl/engine/launchers/config/`). El wheel
  los sigue llevando por `[tool.setuptools.package-data]` en `pyproject.toml`, y tres tests unitarios
  leen `mod/` del paquete instalado con `files("spelunky2rl")`: `test_package_ships_the_mod_and_entity_names`
  (`tests/unit/test_engine.py`, comprueba justo que el wheel lleva el mod), `tests/unit/test_startup.py`
  (l. 18) y `tests/unit/test_lua_pathfinding.py` (l. 10). El CI instala el paquete sin `-e`, así que
  un `pytest` local (editable) no ve que fallan. Para quitarlos de `package-data`: apuntar esos tests al
  árbol de fuentes (`Path(__file__).resolve().parents[2] / "src/spelunky2rl/mod/lua"`), quitar del
  primero las comprobaciones del mod, mover `playlunky.ini`/`local.cfg` a `docker/config/` (junto a
  `nvidia_icd.json`), reconstruir la imagen y pasar `tests/unit` con una instalación no editable y
  `tests/integration`.
- [2026-10-20 20:28 @60da7ee] Antes de publicar 0.1.5, poner al día cifras de `docs/getting-started.md` que no dicen con qué
  imagen se midieron:
  - **"Long runs"**: sus ms son de la 0.1.4, con el texto de versión de Playlunky. Sin el texto, un
    paso es ~6 % más rápido: 1,56-1,59 ms frente a 1,45-1,49 ms (3 juegos en la GPU a la vez, uno por
    proceso, 2026-10-20).
  - **La columna "as up to 0.1.3" de esa tabla**: corrió con `gpu_memory_mb=512`, y la 0.1.3 no tenía
    límite. Con la imagen actual ya no se reproduce: sin el texto, el `msvcp140` de Wine no pierde
    memoria.
  - **"10 and 15 games gave the same ~720 steps/s"** (l. 274-276): se midió el 2026-10-16 con la imagen
    `:0.1.3` y el límite de VRAM. Coincide con la velocidad de la 0.1.5, pero no lo dice.
  Arreglo: volver a medir "Long runs" con `benchmarks/throughput.py drift --envs 5` en la imagen
  0.1.5, comparando contra la 0.1.3 publicada, y anotar la imagen y la versión en cada cifra.

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
  entrenamiento (otro repo, `examples/` fuera del paquete sin extras, o borrarlas), y si sobran extras. Repasar también tests que ya
  no sirvan.
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
- [2026-10-08 12:12 @e791351] Al ver por primera vez un objeto, enemigo, etc. el juego desbloquea su entrada del diario y
  muestra un aviso en pantalla. Con observaciones de píxeles (`render()`) ese aviso tapa parte de la vista y
  ensucia lo que ve el agente; además, depende de la partida guardada, así que el mismo nivel no se ve
  igual entre ejecuciones o máquinas. Idea: una opción (o el comportamiento por defecto) para empezar con
  el diario entero desbloqueado, o para suprimir el aviso desde el mod. Mirar qué permite la API de
  scripts de Playlunky (escribir el progreso del diario en la partida guardada, o desactivar/ocultar el
  aviso cada frame, como ya hace `control.lua` con `game_manager.journal_ui.state`) y si tener todo
  desbloqueado cambia algo más del juego.
- [2026-10-15 12:17 @e791351] Con lavapipe un frame de 128x72 cuesta ~13,6 ms de CPU con `cpu_threads=1` (2,9 ms de espera con
  los 24 hilos por defecto, pero ~25 ms de CPU repartidos: 6,2 cores para ~250 frames/s); es casi todo el paso
  (el juego y el intercambio con Python ~1 ms). Demasiado para tan pocos píxeles, pero no es la resolución
  interna: `resolution_scale=50` en `local.cfg` apenas cambia nada (266 frente a 252 pasos/s, y la imagen se
  emborrona), quitar el HUD tampoco (259), y `vfx=0` o `1` son más lentos que el `2` actual (156). Hilos del
  proceso: casi todo `llvmpipe-*`; `dxvk-*` y el hilo del juego, poco. Siguiente paso: un perfil con
  `perf record -g` del `Spel2.exe` (necesita root: aquí `perf_event_paranoid=4`) para ver si son shaders de
  pantalla completa, muchas capas o algo fijo de DXVK. Scripts y medidas en `~/Desktop/tmp/spelunky/cpu_threads/`
  (`bench.py`, `results.jsonl`, `threads.py`).
- [2026-10-16 00:39 @8051c4f] En la GPU pasa lo mismo que en lavapipe: con 15-20 juegos a 128x72 los pasos/s se
  quedan en ~3.300 con la GPU al 91-94 % (`benchmarks/throughput.py scale`), ~0,27 ms de GPU por
  frame, ya con 5 juegos. Es el siguiente límite tras la VRAM. Mirar con `DXVK_HUD` o Nsight qué
  pases dibuja el juego por frame (¿iluminación o render targets a tamaño fijo?) y si 640x360 cuesta
  lo mismo en GPU (en lavapipe casi: 252 frente a 179 pasos/s).
- [2026-10-16 00:39 @8051c4f] Por paso con render, en el mod: el callback `ON.RENDER_POST_HUD` que cuenta los frames
  cuesta ~0,15 ms (un juego en GPU: 1,0 → 0,79 ms por paso sin él y sin la capa de captura), y los dos
  `RENDER_PRE_*` que solo hacen falta sin render ~0,05 ms. Contar en `ON.POST_GAME_LOOP` (sin contexto
  de render) da un frame de más al arrancar (la captura va uno por detrás): averiguar en qué vuelta
  del bucle no se presenta y si se puede compensar, y registrar los `RENDER_PRE_*` solo sin render.
