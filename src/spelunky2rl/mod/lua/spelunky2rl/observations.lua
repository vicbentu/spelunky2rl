-- What the mod tells Python about the game: the player, the level and what is around the player.
--
-- Python picks the fields at each reset (configure); every state is then packed in binary as the
-- layout returned by configure says (read by StateLayout in engine/protocol.py).
local util = require("spelunky2rl.util")
local pathfinding = require("spelunky2rl.pathfinding")

local M = {}

local round, safe = util.round, util.safe
local pack, unpack, concat = string.pack, table.unpack, table.concat

local FACING_LEFT = 1 << 16
local FIRST_POWERUP = 545  -- ENT_TYPE.ITEM_POWERUP_PASTE; the 18 powerups have consecutive ids

-- The last values read from the player. While there is no player they stay as they were and only
-- health goes to 0.
local last = {
    x = 0, y = 0, layer = 0,
    vel_x = 0, vel_y = 0,
    health = 0, money = 0, bombs = 0, ropes = 0,
    face_left = 0,
    holding_type = 0,
    back_item = 0,
    powerups = {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0},  -- 0 = not, 1 = yes
    char_state = 0,
    can_jump = false,
}

local win = 0  -- 1 from the moment the level is left until it has been reported once

local function is_entity(uid)
    return uid ~= -1 and uid ~= 0 and uid ~= nil
end

local function read_player(player)
    last.x, last.y, last.layer = get_position(player.uid)
    last.vel_x, last.vel_y = get_velocity(player.uid)
    last.health = player.health
    last.money = player.inventory.money
    last.bombs = player.inventory.bombs
    last.ropes = player.inventory.ropes
    last.face_left = (player.flags & FACING_LEFT) ~= 0

    last.holding_type = 0
    if is_entity(player.holding_uid) then
        last.holding_type = get_entity_type(player.holding_uid)
    end
    last.back_item = 0
    local back_uid = player:worn_backitem()
    if is_entity(back_uid) then
        last.back_item = get_entity_type(back_uid)
    end

    last.powerups = {0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0}
    for _, powerup in ipairs(player:get_powerups()) do
        if powerup ~= 0 then
            last.powerups[powerup - FIRST_POWERUP + 1] = 1
        end
    end

    last.char_state = player.state
    last.can_jump = player:can_jump()
end

local function dead_enemies()
    local count = 0
    for _, uid in ipairs(get_entities_by(0, MASK.MONSTER, LAYER.FRONT)) do
        if get_entity(uid).health <= 0 then
            count = count + 1
        end
    end
    return count
end

-- Everything but floor, liquid and decoration whose hitbox touches the view around (x, y), half_x
-- tiles to each side and half_y up and down, each as
-- {dx, dy, vel_x, vel_y, type, face_left 0/1, type of what it holds}
local function entity_info(x, y, layer, half_x, half_y)
    local mask = 0xFFFFFFFF & ~(MASK.DECORATION | MASK.BG | MASK.SHADOW | MASK.FLOOR | MASK.LIQUID | MASK.FX)
    local view = AABB:new(round(x - half_x), round(y + half_y), round(x + half_x), round(y - half_y))
    local info = {}
    for _, uid in ipairs(get_entities_overlapping_hitbox(0, mask, view, layer)) do
        local entity = get_entity(uid)
        local entity_x, entity_y = get_position(uid)
        local vel_x, vel_y = get_velocity(uid)
        local face_left = (entity.flags & FACING_LEFT) ~= 0

        local holding_type = 0
        if is_entity(entity.holding_uid) then
            holding_type = get_entity_type(entity.holding_uid)
        end

        table.insert(info, {
            safe(entity_x - x, 0), safe(entity_y - y, 0),
            safe(vel_x, 0), safe(vel_y, 0),
            safe(get_entity_type(uid), 0),
            face_left and 1 or 0,
            safe(holding_type, 0),
        })
    end
    return info
end

-- Types of the floor tiles around (x, y), 0 where there is none: rows from top to bottom, half_y
-- above and below the player's, of half_x columns to each side
local function map_info(x, y, layer, half_x, half_y)
    local tile_ids = pathfinding.tile_ids()

    local first_x, last_x = round(x - half_x), round(x + half_x)
    local first_y, last_y = round(y - half_y), round(y + half_y)

    local rows = {}
    for tile_y = last_y, first_y, -1 do
        local row = {}
        for tile_x = first_x, last_x do
            local id = 0
            local layer_ids = tile_ids[layer]
            if layer_ids and layer_ids[tile_y] and layer_ids[tile_y][tile_x] then
                id = layer_ids[tile_y][tile_x]
            end
            row[#row + 1] = id
        end
        rows[#rows + 1] = row
    end
    return rows
end

-- Binary layout. Each value is a numpy dtype for Python and its string.pack format here; all
-- little-endian, no padding.
local FORMATS = {["<f8"] = "d", ["<i4"] = "i4", ["?"] = "B", ["u1"] = "B"}

-- basic_info, always sent first: {key, dtype[, count]}. Booleans go as one byte, 0 or 1.
local BASIC = {
    {"x", "<f8"}, {"y", "<f8"}, {"x_rest", "<f8"}, {"y_rest", "<f8"}, {"layer", "<i4"},
    {"health", "<i4"}, {"bombs", "<i4"}, {"ropes", "<i4"}, {"money", "<i4"},
    {"vel_x", "<f8"}, {"vel_y", "<f8"}, {"face_left", "?"}, {"powerups", "u1", 18},
    {"holding_type_player", "<i4"}, {"back_item", "<i4"}, {"char_state", "<i4"}, {"can_jump", "?"},
    {"world", "<i4"}, {"level", "<i4"}, {"theme", "<i4"}, {"time", "<i4"}, {"win", "<i4"},
    {"dead_enemies", "<i4"},
}
local BASIC_FORMAT = "<"
for _, entry in ipairs(BASIC) do
    BASIC_FORMAT = BASIC_FORMAT .. string.rep(FORMATS[entry[2]], entry[3] or 1)
end

local ENTITY_FORMAT = "<ddddddd"

-- The fields of the last reset, in the order they are packed: {name, half_x, half_y}
local fields = {}

-- Set the fields every state carries from now on, as Python sends them: {{name = ..., width = ...,
-- height = ...}, ...}. Returns the layout of those states (see StateLayout in engine/protocol.py).
function M.configure(requested)
    fields = {}
    local layout = {{name = "basic_info", record = BASIC}}
    for _, field in ipairs(requested) do
        local name = field.name
        local half_x, half_y = 0, 0
        if field.width then half_x, half_y = (field.width - 1) // 2, (field.height - 1) // 2 end
        if name == "map_info" then
            layout[#layout + 1] = {name = name, dtype = "<i4", shape = {2 * half_y + 1, 2 * half_x + 1}}
        elseif name == "entity_info" then
            layout[#layout + 1] = {name = name, dtype = "<f8", shape = {-1, 7}}
        elseif name == "dist_to_goal" then
            layout[#layout + 1] = {name = name, dtype = "<i4", shape = {}}
        else
            error("unknown field: " .. tostring(name))
        end
        fields[#fields + 1] = {name, half_x, half_y}
    end
    return layout
end

local function pack_basic(x, y, layer)
    local values = {
        x, y, x - math.floor(x), y - math.floor(y), layer,
        last.health, last.bombs, last.ropes, last.money,
        last.vel_x, last.vel_y, last.face_left and 1 or 0,
    }
    for i = 1, 18 do
        values[#values + 1] = last.powerups[i]
    end
    local rest = {
        last.holding_type, last.back_item, last.char_state, last.can_jump and 1 or 0,
        state.world, state.level, state.theme, state.time_level, win, dead_enemies(),
    }
    for _, value in ipairs(rest) do
        values[#values + 1] = value
    end
    return pack(BASIC_FORMAT, unpack(values))
end

local row_formats = {}  -- string.pack format of a map row, by width

local function pack_map(rows)
    local parts = {}
    for i, row in ipairs(rows) do
        local width = #row
        local format = row_formats[width]
        if not format then
            format = "<" .. string.rep("i4", width)
            row_formats[width] = format
        end
        parts[i] = pack(format, unpack(row))
    end
    return concat(parts)
end

local function pack_entities(entities)
    local parts = {pack("<I4", #entities)}
    for i, e in ipairs(entities) do
        parts[i + 1] = pack(ENTITY_FORMAT, e[1], e[2], e[3], e[4], e[5], e[6], e[7])
    end
    return concat(parts)
end

-- The game state to send to Python, packed: basic_info, then the fields of the last configure.
function M.collect()
    if #players ~= 0 then
        read_player(players[1])
    else
        last.health = 0
    end

    local x, y, layer = last.x, last.y, last.layer
    local parts = {pack_basic(x, y, layer)}
    win = 0

    for _, field in ipairs(fields) do
        local name, half_x, half_y = field[1], field[2], field[3]
        if name == "map_info" then
            parts[#parts + 1] = pack_map(map_info(x, y, layer, half_x, half_y))
        elseif name == "entity_info" then
            parts[#parts + 1] = pack_entities(entity_info(x, y, layer, half_x, half_y))
        elseif name == "dist_to_goal" then
            parts[#parts + 1] = pack("<i4", pathfinding.distance(x, y))
        end
    end

    return concat(parts)
end

-- ON.TRANSITION: the player left the level through the exit.
function M.on_transition()
    win = 1
end

return M
