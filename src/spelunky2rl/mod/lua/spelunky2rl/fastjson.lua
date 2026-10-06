-- JSON encoder for the messages to Python. Decodes to the same values as Overlunky's json.encode
-- (rxi json.lua), but lists of numbers go through table.concat in C: the observation fields are big
-- lists of numbers and rxi's encoder takes ~0.4 us per number (4x slower on a 161x121 map).
-- Two differences: a whole float in a list is written "3.0" (Python gets 3.0, not 3), and integers
-- in a list keep all their digits (rxi rounds them to 14).
local concat, format, find, gsub, next, type, tostring = table.concat, string.format, string.find, string.gsub, next, type, tostring
local huge = math.huge

local M = {}

local escapes = {
    ['"'] = '\\"', ["\\"] = "\\\\", ["\b"] = "\\b", ["\f"] = "\\f",
    ["\n"] = "\\n", ["\r"] = "\\r", ["\t"] = "\\t",
}
local function escape_char(c)
    return escapes[c] or format("\\u%04x", c:byte())
end

local function encode_string(s)
    return '"' .. gsub(s, '[%c"\\]', escape_char) .. '"'
end

local encode

local function encode_number(n)
    if n ~= n or n == huge or n == -huge then
        error("unexpected number value '" .. tostring(n) .. "'")
    end
    return format("%.14g", n)
end

local function encode_list(list, n)
    -- Fast path: every element a number. table.concat writes integers as "3" and floats with
    -- "%.14g" (plus ".0" when the float is whole); anything that is not a plain number shows up as a
    -- character outside [0-9.eE+-,] (a string, "inf", "nan") and takes the slow path.
    local ok, joined = pcall(concat, list, ",", 1, n)
    if ok and not find(joined, "[^%d%.eE+%-,]") then
        return "[" .. joined .. "]"
    end
    local parts = {}
    for i = 1, n do
        parts[i] = encode(list[i])
    end
    return "[" .. concat(parts, ",") .. "]"
end

function encode(value)
    local kind = type(value)
    if kind == "table" then
        local n = #value
        if n > 0 or next(value) == nil then
            return encode_list(value, n)
        end
        local parts = {}
        for k, v in next, value do
            if type(k) ~= "string" then
                error("invalid table: mixed or invalid key types")
            end
            parts[#parts + 1] = encode_string(k) .. ":" .. encode(v)
        end
        return "{" .. concat(parts, ",") .. "}"
    elseif kind == "number" then
        return encode_number(value)
    elseif kind == "string" then
        return encode_string(value)
    elseif kind == "boolean" then
        return value and "true" or "false"
    elseif value == nil then
        return "null"
    end
    error("unexpected type '" .. kind .. "'")
end

M.encode = encode

return M
