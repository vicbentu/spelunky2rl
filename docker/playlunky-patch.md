# The one-byte Playlunky patch

`fetch_assets.sh` changes one byte of `playlunky64.dll` (offset `PLAYLUNKY_PATCH_OFFSET` in
`versions.env`). This file says why, and how to find the byte again when Playlunky is bumped.

## Why

The Lua mod is *unsafe* (`meta.unsafe = true` in `main.lua`): it needs `os` and luasocket's
`package.loadlib` to talk to Python. The game's script engine (`spel2.dll`) only exposes those to
scripts that declare `meta.unsafe`, so the mod cannot pretend to be safe.

Playlunky runs the pack's `main.lua`, but in `ScriptManager::CommitScripts`
(`source/playlunky/mod/script_manager.cpp`) it does:

```cpp
mod.Unsafe = meta.unsafe;
mod.OnlineSafe = meta.online_safe;
if (meta.unsafe)
    mod.ScriptEnabled = false;          // only a checkbox in the in-game Options menu turns it on
else
    SpelunkyScript_SetEnabled(mod.Script.get(), mod.ScriptEnabled);
```

That choice is not saved anywhere and no ini setting changes it. Before, the mod was run by
Overlunky instead (`enable_unsafe_scripts = 1` in `overlunky.ini`), but Overlunky draws its own UI
(menu bar, counters) into every frame and only hides it with an F11 keypress. Building Playlunky
ourselves needs MSVC (its CI only builds on Windows), so we patch the released binary instead.

## What

The `je` after `cmp byte [rdx+0x40],0` (`meta.unsafe`) becomes a `jmp`, so the `else` branch always
runs and the mod stays enabled:

```
80 7a 40 00     cmp    byte [rdx+0x40], 0
74 10           je     <else>              ->  eb 10   jmp <else>
```

`fetch_assets.sh` checks those 5 bytes before patching and fails the build if they are not there.
It also writes `playlunky/PATCHED`, which the wine launcher requires (an old `setup_wine.sh` install
would otherwise start a game whose mod never loads).

## Redoing it for a new Playlunky

With the new `playlunky64.dll` (from the release zip) and binutils' `objdump`:

1. Find the import slot of `SpelunkyScript_SetEnabled` (imported from `spel2.dll`). The first column
   is its address relative to the image base `0x180000000`:

   ```sh
   objdump -p playlunky64.dll | grep SpelunkyScript_SetEnabled
   #   00564018  <none>  00a5  ?SpelunkyScript_SetEnabled@@...   -> slot 0x180564018
   ```

2. Disassemble, find the thunk that jumps through that slot, and the code that calls the thunk:

   ```sh
   objdump -d --no-show-raw-insn playlunky64.dll > pl.dis
   grep -n '# 0x180564018' pl.dis           # jmp *...(%rip) at the thunk, e.g. 18054bffb
   grep -n '0x18054bffb' pl.dis             # its callers
   ```

3. One caller is the lambda above, short and easy to recognise: it copies two bytes of the meta
   (`movzbl 0x40(%rcx)`, `movzbl 0x41(%rdx)`), then `cmpb $0x0,0x40(%rdx)` and a `je` to a block
   that ends in `jmp <thunk>`. The fall-through stores `movb $0x0,...` (`ScriptEnabled = false`).
4. Turn the `je` address into a file offset:
   `offset = address - 0x180000000 - .text VMA offset + .text file offset`, from
   `objdump -h playlunky64.dll` (in v0.19.0: `0x18007bf40 - 0x180001000 + 0x400 = 0x7b340`).
5. Put it in `PLAYLUNKY_PATCH_OFFSET`, rebuild the image and run `tests/integration`: if the mod
   does not connect (startup timeout), the patch is wrong.

If the compiler changed the code shape (e.g. `jne` around the store, or a different register), patch
whatever makes the `else` branch always run; update the 5-byte check in `fetch_assets.sh` to match.

## Getting rid of it

The clean fix is upstream: an ini setting in Playlunky that lets unsafe script mods start enabled
(as Overlunky's `enable_unsafe_scripts`). Once a release has it, drop the patch and set it in
`playlunky.ini`.
