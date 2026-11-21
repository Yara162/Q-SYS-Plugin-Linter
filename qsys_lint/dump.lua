-- Loads a Q-SYS plugin's design-time code and prints what Designer would see as JSON:
-- PluginInfo, properties, pages, controls, and the layout of every page.
-- Usage: lua5.3 dump.lua plugin.qplug
-- The plugin is run with `Controls` unset, as Designer does, so its runtime block is skipped.
-- Nothing here talks to the network or the file system beyond reading the plugin.

local path = arg and arg[1]
if not path then io.stderr:write("usage: lua5.3 dump.lua plugin.qplug\n"); os.exit(2) end

-- ---------------------------------------------------------------- JSON (enough for this)
local function is_array(t)
    local n = 0
    for k in pairs(t) do
        if type(k) ~= "number" or k < 1 or math.floor(k) ~= k then return false end
        n = n + 1
    end
    for i = 1, n do if t[i] == nil then return false end end
    return true
end

local encode
local function esc(s)
    return (s:gsub('[%c"\\]', function(c)
        local map = { ['"'] = '\\"', ['\\'] = '\\\\', ['\n'] = '\\n', ['\r'] = '\\r', ['\t'] = '\\t' }
        return map[c] or string.format("\\u%04x", c:byte())
    end))
end
encode = function(v, seen)
    local t = type(v)
    if t == "nil" then return "null"
    elseif t == "boolean" then return tostring(v)
    elseif t == "number" then
        if v ~= v or v == math.huge or v == -math.huge then return "null" end
        if math.type and math.type(v) == "integer" then return tostring(v) end
        return string.format("%.14g", v)
    elseif t == "string" then return '"' .. esc(v) .. '"'
    elseif t == "table" then
        seen = seen or {}
        if seen[v] then return '"<cycle>"' end
        seen[v] = true
        local out = {}
        if next(v) == nil then seen[v] = nil; return "[]" end
        if is_array(v) then
            for i = 1, #v do out[#out + 1] = encode(v[i], seen) end
            seen[v] = nil
            return "[" .. table.concat(out, ",") .. "]"
        end
        local keys = {}
        for k in pairs(v) do keys[#keys + 1] = tostring(k) end
        table.sort(keys)
        for _, k in ipairs(keys) do
            local val = v[k]
            if val == nil then val = v[tonumber(k)] end
            out[#out + 1] = '"' .. esc(k) .. '":' .. encode(val, seen)
        end
        seen[v] = nil
        return "{" .. table.concat(out, ",") .. "}"
    else
        return '"<' .. t .. '>"'
    end
end

-- ---------------------------------------------------------------- load the plugin
local f = assert(io.open(path, "rb"))
local src = f:read("a")
f:close()

local env = setmetatable({}, { __index = _G })
env.Controls = nil
env.Properties = nil
env.print = function() end

local result = { errors = {} }
local function note(stage, err) table.insert(result.errors, { stage = stage, message = tostring(err) }) end

local chunk, err = load(src, "@" .. path, "t", env)
if not chunk then
    note("load", err)
    print(encode(result))
    return
end
local ok, e = pcall(chunk)
if not ok then note("load", e) end

local function call(name, ...)
    local fn = rawget(env, name)
    if type(fn) ~= "function" then return nil, false end
    local r = table.pack(pcall(fn, ...))
    if not r[1] then note(name, r[2]); return nil, true end
    return r[2], true
end

result.PluginInfo = rawget(env, "PluginInfo")
result.functions = {}
for _, n in ipairs({ "GetPrettyName", "GetProperties", "RectifyProperties", "GetControls",
                     "GetControlLayout", "GetPages", "GetComponents", "GetWiring", "GetPins" }) do
    result.functions[n] = type(rawget(env, n)) == "function"
end

-- Properties as Designer hands them to the other functions: keyed by name, each with .Value.
local propList = call("GetProperties") or {}
result.properties = propList
local props = {}
for _, p in ipairs(propList) do
    if type(p) == "table" and p.Name ~= nil then
        local copy = {}
        for k, v in pairs(p) do copy[k] = v end
        props[p.Name] = copy
    end
end
if result.functions.RectifyProperties then
    local r = call("RectifyProperties", props)
    if type(r) == "table" then props = r end
end

result.prettyName = call("GetPrettyName", props)
result.pages = call("GetPages", props) or {}
result.controls = call("GetControls", props) or {}

-- One layout per page (or one, when the plugin has no pages).
result.layouts = {}
local pageCount = math.max(1, type(result.pages) == "table" and #result.pages or 0)
for i = 1, pageCount do
    props["page_index"] = { Name = "page_index", Value = i }
    local fn = rawget(env, "GetControlLayout")
    if type(fn) == "function" then
        local okL, layout, graphics = pcall(fn, props)
        if okL then
            table.insert(result.layouts, { page = i, layout = layout or {}, graphics = graphics or {} })
        else
            note("GetControlLayout", "page " .. i .. ": " .. tostring(layout))
        end
    end
end

print(encode(result))
