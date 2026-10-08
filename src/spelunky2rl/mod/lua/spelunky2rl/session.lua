-- The exchange with Python, driven by the game's logic frames (ON.POST_UPDATE).
--
-- Python sends a command and waits for one game state. The mod takes the command, lets the game
-- run the frames it needs, sends the state and holds the game until the next command arrives.
--
-- With render, only the last frame of a command is drawn (with render_all, every frame, one per turn
-- of the game loop), and the state is sent once it has been (ON.PRE_GAME_LOOP of the next turn) with
-- the count of frames drawn so far: the Vulkan layer counts the frames it copies the same way, so
-- Python knows which images are the command's and which one is the state's.
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
local render = false
local render_all = false            -- with render: draw every frame, not only the last one
local fast_forwarding = false       -- inside our own update_state() calls
local layout = nil                  -- of the states of this episode, sent with the reset answer
local drawn = 0                     -- frames drawn since the mod loaded
local pending = nil                 -- with render: `drawn` when the last frame of `command` ran
local undrawn = nil                 -- with render_all: `drawn` when the last logic frame ran

-- The frames of `command` have run: send the state it is waiting for.
local function answer()
    if command.command == "step" then
        protocol.send_state({drawn = drawn}, observations.collect())

    elseif command.command == "reset" then
        -- only now, with the level loaded, are there a player and entities to change
        control.destroy_entities(command.ent_types_to_destroy)
        control.set_start_values(command)
        protocol.send_state({layout = layout, drawn = drawn}, observations.collect())
    end
end

-- `n` logic frames without drawing. update_state() fires PRE_UPDATE and POST_UPDATE (the input and
-- update() below) as a real frame does; the flag keeps the nested update() calls from starting
-- their own loop, which used to recurse state_updates deep.
local function run_logic_frames(n)
    fast_forwarding = true
    for _ = 1, n do
        update_state()
    end
    fast_forwarding = false
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
        render = command.render
        render_all = render and command.render_all or false
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

    -- with render only the last frame is drawn: the game runs that one, the others are logic only
    if render and not render_all then
        run_logic_frames(frames_left - 1)
    end
end

-- Answer `command` and take the next one.
local function next_command()
    answer()
    command = protocol.receive()
    start()
end

local function update()
    if pending then return end  -- ON.PRE_UPDATE skips these updates; just in case
    control.disable_pause()
    undrawn = drawn

    frames_left = frames_left - 1
    if frames_left <= 0 then
        if render then
            pending = drawn  -- answered in M.on_pre_game_loop, once this frame is drawn
            return
        end
        next_command()
    end

    -- Speedup without render: state_updates extra logic frames per real frame
    if speedup and not fast_forwarding then
        run_logic_frames(state_updates)
    end
end

-- An error in here would otherwise only reach the game's console, and Python would wait for an
-- answer until its timeout. Send it instead (Python raises it as a RuntimeError) and exit: after an
-- error the state of the mod cannot be trusted, and exiting is what losing the connection does too.
local function guarded(f)
    local ok, trace = xpcall(f, debug.traceback)
    if not ok then
        print("spelunky2rl: " .. tostring(trace))
        pcall(protocol.send, {error = tostring(trace)})  -- the socket itself may be what failed
        os.exit()
    end
end

-- ON.POST_UPDATE
function M.on_post_update()
    guarded(update)
end

-- ON.PRE_GAME_LOOP, the first callback after the last turn's frame was presented
function M.on_pre_game_loop()
    if pending and drawn > pending then
        pending = nil
        guarded(next_command)
    end
end

-- ON.PRE_UPDATE, before every logic frame (also the ones run by update_state()). While the answer
-- waits for the drawing the game must not move on: true skips the update. With render_all, neither
-- while the last frame waits for its drawing: with the speedhack the game runs several updates per
-- drawing. Otherwise, the agent's input. One callback for all: it runs ~200 times per real frame
-- without render.
function M.on_pre_update()
    if pending or (render_all and undrawn == drawn) then return true end
    input.apply()
end

-- ON.RENDER_POST_HUD, once per frame drawn
function M.on_render()
    drawn = drawn + 1
end

return M
