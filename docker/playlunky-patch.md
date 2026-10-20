# The Playlunky patches

`fetch_assets.sh` changes two bytes of `playlunky64.dll`: one so Playlunky runs our unsafe mod
(offset `PLAYLUNKY_PATCH_OFFSET` in `versions.env`), one so it does not draw its version on screen
(`PLAYLUNKY_OVERLAY_OFFSET`). This file says why, and how to find the bytes again when Playlunky is
bumped. Building Playlunky ourselves needs MSVC (its CI only builds on Windows), so we patch the
released binary instead.

## 1. The unsafe mod runs

### Why

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
(menu bar, counters) into every frame and only hides it with an F11 keypress.

### What

The `je` after `cmp byte [rdx+0x40],0` (`meta.unsafe`) becomes a `jmp`, so the `else` branch always
runs and the mod stays enabled:

```
80 7a 40 00     cmp    byte [rdx+0x40], 0
74 10           je     <else>              ->  eb 10   jmp <else>
```

`fetch_assets.sh` checks those 5 bytes before patching and fails the build if they are not there.

### Redoing it for a new Playlunky

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

### Getting rid of it

The clean fix is upstream: an ini setting in Playlunky that lets unsafe script mods start enabled
(as Overlunky's `enable_unsafe_scripts`). Once a release has it, drop the patch and set it in
`playlunky.ini`.

## 2. No version text

### Why

Whenever a script (or level) mod is loaded, Playlunky draws "Playlunky v0.19.0" in the top-left
and bottom-left corners of every frame (`DrawVersionOverlay` in `source/playlunky/detour/imgui.cpp`,
registered with `Spelunky_SetPostRenderGame` in `source/playlunky/mod/mod_manager.cpp`; no ini
setting turns it off). In a level it is almost transparent (alpha 0.008): at 128x72 it changes 14
pixels by at most 3 per channel. On loading and menu screens (alpha 0.25) it is plainly readable.

It is not free. Each of its three texts (one `Spelunky_DrawTextSize`, two `Spelunky_DrawText`) goes
through Overlunky's `TextRenderingInfo::set_text`, which builds a
`std::wstring_convert<std::codecvt_utf8_utf16<char16_t>>`. With Wine's `msvcp140` that object
leaked (see `docs/architecture.md`), which is why the game runs with its own. With the game's own,
the three texts cost ~0.1-0.15 ms per drawn frame: one game at 128x72 on the GPU stepped 8 % slower
than with Wine's `msvcp140`, and as fast once the text was gone, with either DLL. Where the time
goes was read from the disassembly, not profiled: that DLL's `codecvt<char16_t>` constructor builds
and drops a `std::_Locinfo`, a `setlocale` round trip each time, after Playlunky has set `LC_CTYPE`
to UTF-8 (`mod_manager.cpp`).

### What

A `ret` over the first byte of `DrawVersionOverlay`, so it returns at once. It is a `void` function
without arguments. Nothing in `playlunky64.dll` calls or jumps to it: its only reference is the `lea`
that hands it to `Spelunky_SetPostRenderGame`, and `spel2.dll` calls it through that pointer after
each rendered frame. It is also the only function in Playlunky that calls `Spelunky_DrawText` or
`Spelunky_DrawTextSize`:

```
cc cc cc               int3 padding before the function
48 8b c4               mov    %rsp,%rax           ->  c3 8b c4   ret
48 89 58 08            mov    %rbx,0x8(%rax)
55                     push   %rbp
48 8d 68 a1            lea    -0x5f(%rax),%rbp
48 81 ec 00 01 00 00   sub    $0x100,%rsp
```

`fetch_assets.sh` checks those 22 bytes before patching and fails the build if they are not there.
The first 11 are a common prologue (9 functions in v0.19.0 start with them); all 22 occur once.

### Redoing it for a new Playlunky

1. Find the import slot of `Spelunky_DrawTextSize`, as for the first patch:

   ```sh
   objdump -p playlunky64.dll | grep Spelunky_DrawTextSize
   #   00563fd8  <none>  00ac  ?Spelunky_DrawTextSize@@...   -> slot 0x180563fd8
   ```

2. In `pl.dis` (from step 2 of the first patch), find its thunk and the one function that calls it
   (it also calls the `Spelunky_DrawText` thunk twice; find that one the same way):

   ```sh
   grep -n '# 0x180563fd8' pl.dis           # the thunk, e.g. 18054bf2f
   grep -n '0x18054bf2f' pl.dis             # its caller, e.g. at 18001f0bb
   ```

3. Scroll up from that call to the function's entry, right after the `int3` padding (in v0.19.0
   `18001efd0`, `mov %rsp,%rax`). Check it is what Playlunky passes to `Spelunky_SetPostRenderGame`:
   `grep -n '# 0x18001efd0' pl.dis` prints exactly one `lea ...,%rcx` (at `180071237` in v0.19.0).
4. Turn the entry into a file offset as above (in v0.19.0: `0x18001efd0 - 0x180001000 + 0x400 =
   0x1e3d0`) and put it in `PLAYLUNKY_OVERLAY_OFFSET`. If the code changed, update the 22-byte
   check in `fetch_assets.sh` (it must still match only once in the DLL).
5. Rebuild the image and run `tests/integration`; they pass with or without the text, so also check
   a frame. Take a 640x360 frame from a level with the new image, and the same frame with the
   release zip's `playlunky64.dll` with only the first patch bind-mounted over
   `/opt/assets/playlunky/playlunky64.dll` (`launcher_options={"extra_args": ["-v", ...]}`). Frames
   are deterministic, so amplified, their difference should spell "Playlunky vX.Y.Z" in the top-left
   and bottom-left corners and nothing else.

### Getting rid of it

An ini setting in Playlunky that hides the version text would replace it. So would moving the
image back to Wine's `msvcp140` once it is 10.5 or later: in Wine's source (d17412fcaa) its
`codecvt<char16_t>` no longer leaks and makes no `setlocale` round trip; its speed is not measured.
