-- spelunky2rl: lets a Python process drive Spelunky 2 as a reinforcement learning environment.
-- This file only hooks the modules in spelunky2rl/ to the game; what each hook does is in them.
meta.unsafe = true
require("os")
package.path = "lua/?.lua;" .. package.path

local protocol = require("spelunky2rl.protocol")
local session = require("spelunky2rl.session")
local control = require("spelunky2rl.control")
local input = require("spelunky2rl.input")
local observations = require("spelunky2rl.observations")
local pathfinding = require("spelunky2rl.pathfinding")

protocol.connect()

set_post_entity_spawn(function(tile)
    tile:set_pre_destroy(pathfinding.mark_dirty)
    pathfinding.mark_dirty()
end, SPAWN_TYPE.ANY, MASK.FLOOR)

set_callback(session.on_pre_game_loop, ON.PRE_GAME_LOOP)
set_callback(session.on_post_update, ON.POST_UPDATE)
set_callback(session.on_render, ON.RENDER_POST_HUD)
set_callback(observations.on_transition, ON.TRANSITION)
set_callback(control.skip_render, ON.RENDER_PRE_GAME)
set_callback(control.skip_render, ON.RENDER_PRE_HUD)
set_callback(session.on_pre_update, ON.PRE_UPDATE)
