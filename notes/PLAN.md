# Plan — Velocidad y render: el usuario elige qué quiere, el motor cómo

> [2026-10-07 13:13] Hoy la velocidad y el render se controlan con tres parámetros enganchados entre sí (`speedup`,
> `state_updates`, `render_enabled`): lo rápido no es lo que sale por defecto (`speedup=True` sin
> `state_updates` da ~550 pasos/s en vez de ~1.600), hay combinaciones rotas que nada impide
> (`render_enabled=True` con `state_updates>0` devuelve imágenes de pasos anteriores) y con render se
> dibujan los 6 frames de cada paso aunque el agente solo vea el último. Objetivo: el usuario decide
> `speedup` (por defecto `True`) y `render_mode` (`None`, `"rgb_array"` para entrenar con imágenes,
> `"rgb_array_list"` para grabar todos los frames); `state_updates` desaparece del API y el motor lo
> elige. Hecho cuando las cuatro filas de la tabla de abajo funcionan como dice, cada imagen corresponde
> al estado que la acompaña, y docs, ejemplos y tests están al día.

## Estado actual

- `speedup` y `state_updates` son opciones de reset (`_game_reset` en `engine/core.py`, por defecto
  `False` y `0`); van en el mensaje `reset`. `render_enabled` / `render_mode` son de `__init__`; van
  en el mismo mensaje como `"render"`.
- En Lua (`spelunky2rl/control.lua`, `spelunky2rl/session.lua`):
  - `speedup=True` → `set_speedhack(100)` (el reloj del juego a 100x) y activa el bucle de
    `state_updates`. Con `speedup=False` `state_updates` se ignora en silencio.
  - `state_updates=N` → en cada `POST_UPDATE` real, N llamadas a `update_state()`: frames de lógica
    sin dibujar ni `Present`. Cada una vuelve a disparar `POST_UPDATE` (la misma `update()`, que
    descuenta `frames_left` y hace el protocolo), así que **un paso es el mismo tiempo de juego con
    cualquier N**.
  - `render=False` → `control.skip_render` devuelve `true` en `ON.RENDER_PRE_GAME` y
    `ON.RENDER_PRE_HUD` (no dibuja nivel ni HUD). El `Present` sigue; su coste depende del tamaño de
    pantalla, por eso sin render la pantalla es de 160x90 (`HIDDEN_SCREEN`, commit 51ba379).
- El estado se manda en `POST_UPDATE` del último frame del paso y el mod espera ahí el siguiente
  comando (`protocol.receive()` en `update()`). El juego dibuja y presenta ese frame **después** de
  `POST_UPDATE`, o sea después de que llegue el siguiente comando: es probable que `render()` devuelva
  hoy la imagen del frame anterior al estado (sin comprobar; paso 4).
- `render()` captura el Xvfb desde Python con mss (`engine/frames/x11.py`): 0,05 ms a 160x90,
  0,6 ms a 640x360. No es el cuello de botella; dibujar sí.

## Medidas de partida (2026-10-07, Ryzen 9 7900X + RTX 3060, `GetToExit`, una instancia)

Sin render (pantalla 160x90), `speedup=True`, pasos/s:

| `state_updates` | 0 | 1 | 5 | 10 | 50 | 200 | 1000 |
|---|---|---|---|---|---|---|---|
| GPU | 568 | 738 | 1.063 | 1.268 | 1.513 | 1.561–1.581 | 1.593–1.599 |
| CPU | 519 | 721 | 1.085 | 1.241 | 1.483 | 1.538–1.583 | 1.567–1.609 |

El techo (~1.600) es el intercambio con Python (~0,6 ms/paso). GPU y CPU iguales (rangos de 3 pasadas
se solapan).

Con render, `state_updates=0`, ms por paso (`render()` aparte): 160x90 GPU 2,0 / CPU 8,9; 320x180
2,1 / 9,3; 640x360 2,1 / 12,9; 1280x720 2,9 / 25,4. Con CPU dibujar es casi todo el paso.

VRAM: ~1,75 GiB por instancia con GPU, con o sin render y a cualquier resolución. Con 8 instancias la
VRAM (12 GiB) se llena y siguen funcionando (desborda a memoria del sistema; coste sin medir).

Scripts de medida en `~/Desktop/tmp/spelunky/render-bench/`: `nbench.py <renderer> <N>...` (pasos/s
por `state_updates`), `capture.py <w> <h> <renderer>` (paso vs `render()`), `vram.py <n> <on|off> <w>
<h>`; `bench.py` y `probe.py` cambian la pantalla parcheando el entrypoint del contenedor (de antes de
`render_resolution=`, que ya lo hace). Ejecutar con `.venv/bin/python` y `SPELUNKY2RL_GAME_DIR`.

## Objetivo

| Caso | `speedup` | `render_mode` | El motor hace |
|---|---|---|---|
| Entrenar sin imágenes | `True` (defecto) | `None` | N alto (200 salvo que el paso 1 diga otra cosa), pantalla 160x90, sin dibujar |
| Entrenar con imágenes | `True` | `"rgb_array"` | en cada paso, los frames 1..k-1 solo lógica y el k-ésimo dibujado; `render()` → ese frame |
| Grabar | `True` | `"rgb_array_list"` | los k frames dibujados y capturados uno a uno; `render()` → lista de los frames desde la última llamada |
| Mirar en vivo (futuro, sin visor hoy) | `False` | cualquiera | tiempo real, N=0 |

(k = `frames_per_step`.) `render_enabled=True` sigue siendo alias de `render_mode="rgb_array"`.
`"rgb_array_list"` es la convención de Gymnasium: `RecordVideo` la entiende y graba a
`metadata["render_fps"]` = 60, fluido.

Comportamientos que no cambian: el contenido de los estados, `frames_per_step`, la semántica de las
acciones (una acción mantenida k frames), `render_resolution`, la API de `reset`/`step` salvo
`state_updates` y el defecto de `speedup`.

Cambios incompatibles (van en las notas de la release): `speedup` pasa a `True` por defecto;
`state_updates` deja de existir (pasarlo da `TypeError` con un mensaje que explique por qué y qué
hacer); con render, la imagen de `render()` puede cambiar un frame si el paso 4 confirma el desfase.

## 1. ¿Sobra el speedhack?  ·  pending
Con `state_updates` alto, el juego solo hace un frame real cada 1+N frames de lógica; aunque esperase a
los 60 FPS el techo sería 60·(1+N)/k pasos/s (≈2.000 con N=200, k=6), por encima del de ~1.600. Medir
con una copia del mod en el scratchpad (`SPELUNKY2RL_DEV_MOD`) donde `set_speedup` llame a
`set_speedhack(1)`: pasos/s sin render con N = 200 y 1000, GPU y CPU, 3 pasadas por caso, frente al mod
normal. Y con render (`state_updates=0`, 160x90): ahí sí debería hacer falta (cada frame es real).
Criterio: tabla medida en el commit que cierra el paso y decisión escrita en un `Decided:`: si sin
speedhack se pierde < 3 % sin render, `speedup` solo controla N y el speedhack queda para el render;
si no, se queda como está. El mod normal no cambia en este paso salvo que la decisión lo pida.

## 2. Mismo resultado con cualquier N  ·  pending
Precondición para que el motor elija N por su cuenta: la dinámica no puede depender de N. Con
`god_mode=True`, misma semilla y la misma secuencia de 500 acciones (fija, de un `np.random` con
semilla), comparar los estados con N=0 y N=200 campo a campo. Comprobar antes N=0 contra N=0: si el
juego no es determinista ni así, comparar en su lugar la posición del jugador tras secuencias cortas
(p. ej. 10 pasos a la derecha) y documentar por qué. Mirar también que `input.apply` (`ON.PRE_UPDATE`)
corre en los frames de `update_state()`: si no, la acción solo se aplicaría en los frames reales.
Criterio: test de integración nuevo en `tests/integration/test_game.py` que lo comprueba y pasa.
Si falla, parar: el resto del plan depende de esto (va a QUESTIONS con lo encontrado).

## 3. `speedup=True` por defecto; `state_updates` lo elige el motor  ·  pending
- `engine/core.py`: quitar `state_updates` de `_game_reset`; `speedup` por defecto `True`. El mensaje
  `reset` sigue llevando `state_updates` (el protocolo no cambia): `STATE_UPDATES` (constante, valor
  del paso 1) si `speedup` y sin render, si no 0. Pasar `state_updates=` da `TypeError` explicando
  que ya no existe y que el motor lo fija (antes de la comprobación genérica de opciones
  desconocidas, en `__init__` y en `reset`).
- Lua: lo que decida el paso 1 sobre el speedhack (si nada, no se toca).
- Quitarlo de ejemplos y docs: `examples/benchmark_performance.py`, `train_get_to_exit.py`,
  `evaluate_model.py`, `record_video.py` (`speedup=False` "real-time looks better" ya no tiene
  sentido: el vídeo va a fps fijos), `manual_control.py` (se queda con `speedup=False`),
  `envs/template_environment.py`, `docs/getting-started.md` (sección de velocidad: la tabla de
  "Medidas de partida" sustituye a "Above `state_updates≈50`…"), `docs/environments.md`,
  `docs/architecture.md` (sección del mecanismo de velocidad), `tests/integration/test_game.py`
  (`FAST`).
Criterio: tests unitarios nuevos: el mensaje `reset` lleva `state_updates=STATE_UPDATES` con
`speedup=True` sin render, 0 con render y 0 con `speedup=False`; `state_updates=` da `TypeError` en
`__init__` y en `reset`. `grep -rn state_updates examples docs src/spelunky2rl/envs` no encuentra
usos de usuario. Suite unitaria e integración en verde. `GetToExit()` sin opciones da ≥ 1.500 pasos/s.
Verified with: `.venv/bin/python -m pytest tests/unit -q` y
`SPELUNKY2RL_GAME_DIR=~/Desktop/tmp/spelunky2-clean .venv/bin/python -m pytest tests/integration -q`
(con la imagen local reconstruida si cambió el mod).

## 4. ¿Qué frame hay en pantalla cuando llega el estado?  ·  pending
Sonda en una copia del mod (scratchpad, `SPELUNKY2RL_DEV_MOD`): en `ON.RENDER_POST_HUD` dibujar un
rectángulo en una esquina cuyo color codifique el contador de frames de lógica (p. ej.
`state.time_level` o un contador propio, en tres canales), y mandar ese mismo contador en el estado.
Con `render_mode="rgb_array"`, `frames_per_step` 1 y 6, decodificar el color de `render()` y
compararlo con el contador del estado. Mirar también qué callbacks corren después del `Present` (el
primero tras presentar es donde el mod puede saber que el frame ya está en pantalla:
`ON.PRE_UPDATE` del frame siguiente, `ON.GAMEFRAME`, `ON.PRE_GAME_LOOP`… según la API de Playlunky).
Criterio: anotado en este plan (sección "Estado actual") y en `docs/architecture.md` qué frame
devuelve hoy `render()` respecto al estado (mismo, anterior u otro) y en qué callback puede el mod
mandar el estado para que la imagen corresponda. Sin cambios en el código del repo.

## 5. `"rgb_array"`: dibujar solo el último frame del paso, y que sea el del estado  ·  pending
- Lua: el mod dibuja solo el frame que se va a responder (hoy `skip_render` mira un flag global;
  pasa a mirar también si es el último frame del paso, `frames_left`), y los anteriores del paso se
  hacen como lógica pura. Diseño a decidir con lo del paso 4: o bien `update_state()` k-1 veces y un
  frame real, o bien frames reales con el dibujado saltado. Lo primero ahorra también el `Present`.
- Si el paso 4 encontró desfase: mover el envío del estado al primer callback tras el `Present` del
  último frame, para que `render()` devuelva la imagen del estado. Esto cambia cuándo responde el mod;
  `PROTOCOL_VERSION` sube a 3 si cambia la forma de algún mensaje (en Lua y en `engine/protocol.py`).
- Reconstruir la imagen local (`docker build -f docker/Dockerfile -t
  ghcr.io/vicbentu/spelunky2rl-game:<versión dev> .`).
Criterio: con la sonda del paso 4, el frame de `render()` es el del estado en 50 pasos seguidos con
`frames_per_step` 1 y 6. Con CPU a 160x90 el paso con render baja de 8,9 ms (medir; se espera cerca de
los ~2 ms sin render). Test de integración que lo comprueba sin sonda (p. ej. dos `render()` tras pasos
distintos dan imágenes distintas, y el test de render existente sigue en verde). Suite completa en
verde.

## 6. `"rgb_array_list"`: todos los frames, capturados uno a uno  ·  pending
- Python no puede capturar frames intermedios por su cuenta (el juego va por delante). Sincronizar:
  con este modo, tras presentar cada frame del paso el mod manda un mensaje corto (`frame`) y espera
  un `next` de Python, que captura entre medias; el último frame del paso es el estado. Mensajes
  nuevos → `PROTOCOL_VERSION` (si no subió en el paso 5) y su descripción en `docs/architecture.md`.
- `render_mode` admite `"rgb_array_list"`; `metadata["render_modes"]` lo incluye. `render()` devuelve
  la lista de frames desde la última llamada (o desde `reset`, que la vacía y añade el suyo), como
  `gymnasium.wrappers.RenderCollection`. Con este modo N=0 siempre.
- `examples/record_video.py` pasa a usarlo (o a `gymnasium.wrappers.RecordVideo`).
Criterio: con k=6, `render()` tras un paso devuelve 6 frames; con la sonda del paso 4 sus contadores
son consecutivos y el último es el del estado. `RecordVideo` sobre el entorno escribe un vídeo de
60 FPS con 6 frames por paso. Tests unitarios (con `FakeLauncher`/`FakeLua`) del intercambio
`frame`/`next` y de la lista; test de integración que graba unos pasos. Suite completa en verde.

## 7. Docs y cierre  ·  pending
`docs/getting-started.md` (parámetros, sección de velocidad con la tabla de casos, grabación),
`docs/architecture.md` (mecanismo de velocidad, render, protocolo), `docs/environments.md`, y una nota
para la release con los cambios incompatibles.
Criterio: `grep -rn "state_updates\|render_enabled=True.*speedup=False" docs examples` sin usos
obsoletos; la tabla de "Objetivo" está en `docs/getting-started.md`; suite completa en verde.
