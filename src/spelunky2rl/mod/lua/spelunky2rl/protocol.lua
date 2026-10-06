-- The connection to Python over TCP (engine/protocol.py on the other side): Python sends one JSON
-- object per line; the mod answers with a JSON header line, followed by the packed game state when
-- the header says how many bytes it has (`state`).
local socket = require("luasocket.socket")

local M = {}

-- Keep in sync with PROTOCOL_VERSION in engine/protocol.py and __version__ in version.py
local PROTOCOL_VERSION = 2
local MOD_VERSION = "0.1.3.dev0"

local client = nil

-- Connect to the port where Python listens and say hello.
function M.connect()
    local port = tonumber(os.getenv("Spelunky_RL_Port"))

    client = socket.tcp()
    local success, err = client:connect("127.0.0.1", port)
    if not success then
        error("Failed to connect: " .. tostring(err))
    end
    client:setoption("tcp-nodelay", true)  -- one small message each way per step: never wait to batch
    M.send({hello = {protocol = PROTOCOL_VERSION, mod = MOD_VERSION}})
end

function M.send(message)
    client:send(json.encode(message) .. "\n")
end

-- A game state: `header` (a table) gets its size as `state`, and the bytes go right after it.
function M.send_state(header, state)
    header.state = #state
    client:send(json.encode(header) .. "\n" .. state)
end

-- The next message from Python. Blocks the game until it arrives.
function M.receive()
    local line, err = client:receive("*l")
    if not line then
        -- Python side is gone: nothing will ever drive this instance again
        print("spelunky2rl: connection lost (" .. tostring(err) .. "), exiting")
        os.exit()
    end
    return json.decode(line)
end

return M
