# Preguntas — para ti

Nada de lo que hay aquí bloquea el trabajo. *Para responder*: no lo decidí; lo que depende de ello está
aparcado y el resto sigue. *Decidido sin ti*: lo elegí y lo apliqué; se mantiene salvo que digas otra
cosa, y cada entrada da cómo deshacerlo. Respondes en el chat o con una línea `**Answer:** …` bajo la
entrada; las respondidas se aplican y se borran, el porqué va en un párrafo `Decided:` del commit que las
aplica. `@sha` es el commit en que estaba el código al escribir la entrada.

## Para responder

## Decidido sin ti

### wine-prefix-per-instance · [2026-09-28 13:18 @4a2a9cf] El modo `wine` copia el prefijo por instancia (~1,2 GB cada uno)

`WineLauncher` reserva "slots" con un bloqueo y copia el prefijo base la primera vez
(`cp --reflink=auto`, gratis en btrfs/xfs). Con un prefijo compartido, 1 de 4 instancias fallaba.

Coste: disco la primera vez en ext4. Solo afecta al modo sin Docker.

Para cambiarlo: borrar `~/.local/share/spelunky2rl/wine/prefixes/`; o investigar el fallo con prefijo
compartido.

### lua-tests-skipped-in-ci · [2026-10-01 21:59 @3d4af91] Los tests del BFS en Lua se saltan en CI

`tests/unit/test_lua_pathfinding.py` ejecuta `pathfinding.distance_field` con el intérprete `lua5.4` o
`lua` del sistema (aquí Lua 5.3.6: 3 tests pasan). El plan los daba como opcionales, "solo si el
intérprete está disponible en CI". Los runners `ubuntu-latest` no traen Lua.

Elegí escribirlos con `skipif` y no tocar el CI: en local se ejecutan y en CI aparecen como saltados.

Descartado:
- Instalar Lua en el CI: los tests correrían en cada PR; a cambio, un `apt-get` más en el job de tests
  por 3 tests de una función que solo cambia si se toca el pathfinding.
- No escribir los tests: nada que mantener, pero el BFS solo quedaría cubierto por la traza, que
  necesita el juego.

Para cambiarlo: añadir `- run: sudo apt-get install -y lua5.4` antes de `pytest` en
`.github/workflows/ci.yml`; o borrar el fichero de tests.

### render-fps-per-mode · [2026-10-07 23:03 @ab0152c] `render_fps` es 60/k con `"rgb_array"` y 60 con `"rgb_array_list"`; se graba con `save_video`

El paso 6 del plan suponía que `gymnasium.wrappers.RecordVideo` con `"rgb_array_list"` graba los k
frames de cada paso. No es así: en Gymnasium 1.3 (`RecordVideo._capture_frame`) guarda solo el último
de cada lista. Medido con 50 pasos de k=6 a 320x180: `RecordVideo` sobre `"rgb_array_list"` da 51
frames a 60 FPS (0,85 s, el juego 6 veces acelerado). La herramienta de Gymnasium para guardar todos
los frames de `"rgb_array_list"` es `gymnasium.utils.save_video.save_video(env.render(), carpeta,
fps=env.metadata["render_fps"])`: 301 frames a 60 FPS (5,02 s, a la velocidad del juego).

Antes, `metadata["render_fps"]` era 60 en todo caso. Con `"rgb_array"`, `RecordVideo` graba un frame
por paso, así que el vídeo salía 6 veces acelerado.

Elegí que `render_fps` sea lo que de verdad devuelve `render()`:
- 60 con `"rgb_array_list"` (todos los frames);
- 60/`frames_per_step` con `"rgb_array"` (10 con k=6; `RecordVideo` da 51 frames a 10 FPS, 5,1 s).

Se fija por instancia en `__init__`; el de la clase sigue en 60.

El criterio del paso 6 queda así:
- `save_video` con `"rgb_array_list"` escribe un vídeo de 60 FPS con 6 frames por paso;
- `RecordVideo` con `"rgb_array"` escribe uno a tiempo real.

`examples/record_video.py` usa `"rgb_array_list"` y OpenCV, como antes, a 60 FPS.

Descartado:
- `render_fps` = 60 siempre: es lo de antes, y con `RecordVideo` el vídeo sale acelerado k veces.
- Que `render()` en modo lista devuelva un solo frame para que `RecordVideo` lo entienda: va contra
  la convención de Gymnasium (`RenderCollection`, `save_video`).

Coste si me equivoco: quien grabe con `RecordVideo` sobre `"rgb_array"` y esperara el vídeo acelerado
lo verá ahora a tiempo real. Si se cambia `frames_per_step` después de crear el entorno, `render_fps`
no se actualiza.

Para cambiarlo: borrar las tres líneas `if self.render_mode == "rgb_array": self.metadata = …` en
`SpelunkyRLEngine.__init__` (`engine/core.py`) y `test_render_fps_is_that_of_what_render_returns`.
