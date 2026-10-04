# Preguntas — para ti

Nada de lo que hay aquí bloquea el trabajo. *Para responder*: no lo decidí; lo que depende de ello está
aparcado y el resto sigue. *Decidido sin ti*: lo elegí y lo apliqué; se mantiene salvo que digas otra
cosa, y cada entrada da cómo deshacerlo. Respondes en el chat o con una línea `**Answer:** …` bajo la
entrada; las respondidas se aplican y se borran, el porqué va en un párrafo `Decided:` del commit que las
aplica. `@sha` es el commit en que estaba el código al escribir la entrada.

## Para responder

## Decidido sin ti

### overlunky-whip-pinned-by-hash · [2026-09-28 13:18 @4a2a9cf] Overlunky: build "whip" fijada por hash, no por versión

Overlunky solo publica una build continua (`whip`) que se reemplaza en el mismo URL.
`docker/versions.env` fija su sha256 (build del 2026-09-16). Cuando upstream la cambie, el build de la
imagen fallará en el checksum a propósito.

Coste: reconstruir la imagen en el futuro exige actualizar el hash (y probar). Las imágenes ya publicadas
no se ven afectadas.

Para cambiarlo: alojar una copia del zip (release propia en este repo) y apuntar `OVERLUNKY_URL` ahí.

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
