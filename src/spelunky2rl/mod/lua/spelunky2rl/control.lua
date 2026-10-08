-- What the mod changes in the game: which level is played, how the player starts it, game options.
local M = {}

local PAUSE_FLAG = 1 << 19  -- level flag 20: without it the game cannot be paused
local render_enabled = true

-- Theme of the first level of each world. Worlds 2 and 4 also have an alternative
-- (Volcana, Temple) that can be requested explicitly with the `theme` reset option.
local world_themes = {
    THEME.DWELLING, THEME.JUNGLE, THEME.OLMEC, THEME.TIDE_POOL,
    THEME.ICE_CAVES, THEME.NEO_BABYLON, THEME.SUNKEN_CITY, THEME.COSMIC_OCEAN,
}

local function theme_for(world, level)
    if world == 6 and level == 4 then return THEME.TIAMAT end
    if world == 7 and level == 4 then return THEME.HUNDUN end
    return world_themes[world] or THEME.DWELLING
end

-- Start a seeded run with one player and warp to world-level. The level is not there yet when
-- this returns: the game loads it over the next frames.
function M.start_level(seed, world, level, theme)
    -- the death screen opens the journal and warp() leaves it open: the new level would stay paused
    game_manager.journal_ui.state = 0
    state.quest_flags = 1
    set_adventure_seed(seed, seed)
    play_adventure()

    state.items.player_count = 1
    state.items.player_select[1].activated = true
    state.items.player_select[1].character = ENT_TYPE.CHAR_ANA_SPELUNKY

    warp(world, level, theme or theme_for(world, level))
end

-- Health and inventory the player starts with (hp, bombs, ropes, gold). Needs the player, so the
-- level has to be loaded.
function M.set_start_values(options)
    players[1].health = options.hp
    players[1].inventory.bombs = options.bombs
    players[1].inventory.ropes = options.ropes
    players[1].inventory.money = options.gold
end

-- Kill every entity of the given types.
function M.destroy_entities(entity_types)
    if #entity_types == 0 then
        return
    end
    for _, uid in ipairs(get_entities_by_type(entity_types)) do
        kill_entity(uid)
    end
end

-- 100x the game's clock, so that it runs as fast as the machine allows, or back to real time.
-- Only needed with render: without it the state_updates loop already runs past the 60 FPS cap.
function M.set_speedup(enabled)
    set_speedhack(enabled and 100 or 1)
end

-- The game options of a reset message. vsync, audio, time_ghost and render keep their current value
-- when the message does not carry them.
function M.apply_options(options)
    if options.vsync ~= nil then set_setting(GAME_SETTING.VSYNC, options.vsync and 1 or 0) end
    if options.audio ~= nil then set_setting(GAME_SETTING.MASTER_ENABLED, options.audio and 1 or 0) end
    if options.time_ghost ~= nil then set_time_ghost_enabled(options.time_ghost) end
    if options.render ~= nil then
        render_enabled = options.render
    end
    M.set_speedup(options.speedup and render_enabled)
    god(options.god_mode and true or false)
end

-- The game must never sit in the pause menu: called on every frame.
function M.disable_pause()
    set_level_flags(get_level_flags() & ~PAUSE_FLAG)
end

-- ON.RENDER_PRE_GAME and ON.RENDER_PRE_HUD. Headless: skip drawing the level and the HUD when
-- nobody looks at the frames.
function M.skip_render()
    if not render_enabled then return true end
end

return M
