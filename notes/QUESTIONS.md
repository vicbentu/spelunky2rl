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

### gpu-memory-default · [2026-10-16 00:39 @9243864] `gpu_memory_mb` es 512 por defecto: cada juego en GPU usa ~0,35 GB de VRAM

Cada juego cargaba en VRAM todas las texturas (~1,6 GiB sin comprimir), 1,73-1,78 GB por juego. Una
RTX 3060 de 12 GB admitía 6 juegos, o 3 junto a un DreamerV3 de 5,2 GB. Con dos entrenamientos de 5
juegos el CUDA que arranca después se quedaba sin VRAM (el error de cuBLAS). Con
`DXVK_CONFIG=dxvk.maxMemoryBudget=512` cada juego ocupa 0,31-0,38 GB (de 1 a 20 juegos) y da un 1-3 %
menos de pasos/s (5 juegos: 2.714 frente a 2.751; 10: 3.351 frente a 3.456, juegos libres).

Elegí 512 por defecto, también para quien no sepa que existe.

Descartado:
- Sin límite (lo de antes): ese 1-3 % de velocidad, a cambio de que cualquier CUDA que arranque
  después de los juegos se quede sin VRAM.
- Un presupuesto menor (256): no lo medí. Un nivel del mundo 1 dibuja ~270 MB de texturas; por debajo
  de eso DXVK movería texturas a la VRAM y de vuelta en cada frame.

Coste si me equivoco: en un mundo que dibuje más de 512 MB de texturas, o a resoluciones grandes,
el juego iría más lento que sin límite; no lo he medido fuera del mundo 1 a 128x72.

Para cambiarlo: `gpu_memory_mb=None` (sin límite) o otro número al crear el entorno; el valor por
defecto está en `SpelunkyRLEngine.__init__` (`engine/core.py`).
