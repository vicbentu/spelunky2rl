-- The agent's actions as game input.
local M = {}

-- The last six values of an action, in this order
local buttons = {
    BUTTON.JUMP,
    BUTTON.WHIP,
    BUTTON.BOMB,
    BUTTON.ROPE,
    BUTTON.RUN,
    BUTTON.DOOR,
}

local agent_input = nil  -- INPUTS applied every frame until the next step; nil = leave input alone
local manual_control = false  -- a person plays: the agent's actions are ignored

function M.set_manual_control(enabled)
    manual_control = enabled
end

-- Hold `action` from the next frame on. It is {x, y, jump, whip, bomb, rope, run, door}:
-- x and y are 0, 1, 2 for left/down, nothing, right/up; the buttons are 0 or 1.
function M.hold(action)
    if manual_control then
        return
    end
    local first_button = #action - #buttons
    local mask = 0
    for i, button in ipairs(buttons) do
        if action[first_button + i] == 1 then
            mask = mask | button
        end
    end
    agent_input = buttons_to_inputs(action[1] - 1, action[2] - 1, mask)
end

-- Stop writing the input.
function M.release()
    agent_input = nil
end

-- From ON.PRE_UPDATE (session.on_pre_update). The agent's input, written before every logic frame (also the ones run by
-- update_state()). steal_input/send_input used to do this, but overlunky deprecates them as
-- crash-prone, and the input was silently ignored in ~40% of episodes (the player never moved).
function M.apply()
    if agent_input ~= nil and not manual_control then
        state.player_inputs.player_slot_1.buttons_gameplay = agent_input
        state.player_inputs.player_slot_1.buttons = agent_input
    end
end

return M
