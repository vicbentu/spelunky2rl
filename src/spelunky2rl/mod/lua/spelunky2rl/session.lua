-- The exchange with Python, driven by the game's logic frames (ON.POST_UPDATE).
--
-- Python sends a command and waits for one game state. The mod takes the command, lets the game
-- run the frames it needs, sends the state and holds the game until the next command arrives.
local protocol = require("spelunky2rl.protocol")
local control = require("spelunky2rl.control")
local input = require("spelunky2rl.input")
local observations = require("spelunky2rl.observations")
local pathfinding = require("spelunky2rl.pathfinding")

local M = {}

local RESET_FRAMES = 60  -- given to the game to load the level before the first state is sent

local command = {command = "pass"}  -- the last message from Python; "pass" until the first one
local frames_left = 0               -- frames to run before `command` is answered
local speedup = false
local state_updates = 0
local fast_forwarding = false       -- inside our own update_state() calls
local layout = nil                  -- of the states of this episode, sent with the reset answer

-- The frames of `command` have run: send the state it is waiting for.
local function answer()
    if command.command == "step" then
        protocol.send_state({}, observations.collect())

    elseif command.command == "reset" then
        -- only now, with the level loaded, are there a player and entities to change
        control.destroy_entities(command.ent_types_to_destroy)
        control.set_start_values(command)
        protocol.send_state({layout = layout}, observations.collect())
    end
end

-- `command` has just arrived: start it.
local function start()
    if command.command == "reset" then
        input.release()
        pathfinding.reset()
        layout = observations.configure(command.fields)
        control.start_level(command.seed, command.world, command.level, command.theme)
        frames_left = RESET_FRAMES

        speedup = command.speedup
        state_updates = command.state_updates
        control.apply_options(command)
        input.set_manual_control(command.manual_control)

    elseif command.command == "step" then
        frames_left = command.frames
        if #players ~= 0 then
            input.hold(command.input)
        end

    elseif command.command == "close" then
        input.release()
        control.set_speedup(false)
        os.exit()
    end
end

local function update()
    control.disable_pause()

    frames_left = frames_left - 1
    if frames_left <= 0 then
        answer()
        command = protocol.receive()
        start()
    end

    -- Speedup: simulate state_updates extra logic frames per rendered frame. update_state() fires
    -- POST_UPDATE again (this same function, which also runs the protocol above); the flag keeps
    -- those nested calls from starting their own loop, which used to recurse state_updates deep.
    if speedup and not fast_forwarding then
        fast_forwarding = true
        for _ = 1, state_updates do
            update_state()
        end
        fast_forwarding = false
    end
end

-- An error in here would otherwise only reach the game's console, and Python would wait for an
-- answer until its timeout. Send it instead (Python raises it as a RuntimeError) and exit: after an
-- error the state of the mod cannot be trusted, and exiting is what losing the connection does too.
function M.on_post_update()
    local ok, trace = xpcall(update, debug.traceback)
    if not ok then
        print("spelunky2rl: " .. tostring(trace))
        pcall(protocol.send, {error = tostring(trace)})  -- the socket itself may be what failed
        os.exit()
    end
end

return M
