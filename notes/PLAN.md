# Plan — Contrato de observaciones configurable y en binario

> [2026-10-06 12:01] Hoy el mod manda cada estado como JSON y Python no puede elegir más que qué campos
> quiere (`data_to_send`), sin parámetros ni validación. Pasar a: Python pide los campos con sus
> parámetros en el `reset`, Lua contesta con la plantilla (nombre, tipo, forma de cada campo) y cada
> estado viaja como un bloque binario que Python lee con numpy. Por qué: con observaciones grandes
> codificar en texto domina el paso (161x121: ~3,0 ms en JSON frente a ~0,35 ms en binario, medido con
> `~/Desktop/tmp/spelunky/bench4.py`), y la configurabilidad futura necesita una plantilla de todas
> formas. Hecho cuando el protocolo 2 funciona contra el juego real, los entornos y tests pasan, la
> vista es configurable y la documentación describe el formato.

## Diseño

**Mensajes.** Python → Lua sigue en JSON (pequeños). Lua → Python: toda respuesta es una línea JSON
de cabecera; si lleva `"state": N`, detrás van N bytes. `hello` y `error` siguen siendo solo la línea.
- `reset`: Python manda `"fields": [{"name": "map_info", "width": 21, "height": 11}, ...]`. La
  respuesta lleva `"layout"` y el primer estado.
- `step`: ya no lleva `data_to_send`; los campos quedan fijados en el `reset`.

**Plantilla (`layout`)**, en el orden del bloque binario, little-endian:
- `{"name": "basic_info", "record": [["x", "<f8"], ..., ["powerups", "u1", 18]]}` → un dict de
  escalares de Python (`.item()`: `bool`, `int`, `float`) y listas, como hoy.
- `{"name": "map_info", "dtype": "<i4", "shape": [11, 21]}` → array numpy.
- `{"name": "entity_info", "dtype": "<f8", "shape": [-1, 7]}` → `-1`: un `uint32` con el número de
  filas va delante.
- `{"name": "dist_to_goal", "dtype": "<i4", "shape": []}` → escalar de Python.
Python comprueba que el bloque se consume entero; si no, `ProtocolError`.

**Campos y parámetros** en un solo sitio de Python (`engine/fields.py`): nombre → parámetros con
valor por defecto y validación. `map_info` y `entity_info`: `width`, `height` impares ≥ 1 (vista
centrada en el jugador; por defecto 21x11). `dist_to_goal` sin parámetros. `custom_info` se quita
(siempre mandaba `""`). `data_to_send` admite la lista de nombres de hoy o un dict
`{"map_info": {"width": 41, "height": 21}}`. Un nombre o parámetro desconocido es un error al crear
el entorno.

**Lo que no cambia:** las claves y tipos de `basic_info` y `dist_to_goal`; los valores (float64, sin
pérdida respecto al JSON); la vista por defecto; los entornos existentes (como mucho, ajustes donde
traten `map_info`/`entity_info` como listas).

**Pruebas:** `FakeLua` (tests/unit) codifica con la misma plantilla; tests de ida y vuelta del
decodificador y de validación de campos; la suite de integración contra el juego.

## 1. Python: campos, plantilla y marco binario  ·  done [2026-10-06 12:07]
Criterio: `engine/fields.py` y el decodificador en `engine/protocol.py`; `FakeLua` habla el protocolo
2; `pytest tests/unit` en verde con tests nuevos de ida y vuelta y de validación.
Verificado con: `.venv/bin/python -m pytest tests/unit -q` → `99 passed`.

## 2. Lua: plantilla y empaquetado binario  ·  done [2026-10-06 12:07]
Criterio: `observations.lua` configura los campos en el `reset` y empaqueta el estado;
`PROTOCOL_VERSION = 2` en los dos lados.
Verificado con: `SPELUNKY2RL_GAME_DIR=~/Desktop/tmp/spelunky2-clean
SPELUNKY2RL_DEV_MOD=$PWD/src/spelunky2rl/mod/lua SPELUNKY2RL_IMAGE=ghcr.io/vicbentu/spelunky2rl-game:0.1.1
.venv/bin/python -m pytest tests/integration` → todo en verde, más un test nuevo con vista no
por defecto. Resultado: `9 passed` (incluye `test_a_wider_view_holds_the_default_one`).

## 3. Documentación y medida  ·  pending
Criterio: `docs/architecture.md` (protocolo) y `docs/environments.md` (`data_to_send` con
parámetros) describen el formato nuevo; medido el coste por paso antes y después con el juego real;
borradas del backlog las entradas que esto cierra (binario y contrato).
