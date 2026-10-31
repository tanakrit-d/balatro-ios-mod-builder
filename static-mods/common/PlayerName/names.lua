-- Profile names are the source of truth. Multiplayer configs are only mirrors;
-- never copy a mod-wide username back into another Balatro save profile.
local names = { limit = 16, status = 'Names follow the active profile.' }
local utf8 = require('utf8')

function names.active()
    local index = G and G.SETTINGS and G.SETTINGS.profile
    return index, G and G.PROFILES and G.PROFILES[index]
end

function names.validate(value)
    if type(value) ~= 'string' or not utf8.len(value) then return nil, 'Enter a valid name.' end
    value = value:gsub('%c', ''):match('^%s*(.-)%s*$')
    if value == '' then return nil, 'Enter a name first.' end
    if #value > names.limit then return nil, 'Name too long (maximum 16 bytes).' end
    return value
end

local function integration(id, global)
    local mod = SMODS.Mods and SMODS.Mods[id]
    if mod and mod.can_load and not mod.disabled and mod == global then return mod end
end

function names.pvp()
    return integration('MultiplayerPvP', PVP)
end

function names.api()
    return integration('MultiplayerAPI', MPAPI)
end

function names.in_lobby()
    local api, pvp = names.api(), names.pvp()
    if api and type(api.get_current_lobby) == 'function' then
        local ok, lobby = pcall(api.get_current_lobby)
        if not ok or lobby then return true end
    end
    return pvp and pvp.LOBBY and not not (pvp.LOBBY.code and pvp.LOBBY.code ~= '') or false
end

function names.can_edit()
    local _, profile = names.active()
    return profile and G.STAGES and G.STAGE == G.STAGES.MAIN_MENU and not names.in_lobby()
end

local function persist(mod, key, value)
    if type(mod.config) ~= 'table' then return false end
    if mod.config[key] == value then return true end
    local old = mod.config[key]
    mod.config[key] = value
    -- Respect a mod's custom saver when supplied (documented Mod Object API).
    local save = mod.save_mod_config or SMODS.save_mod_config
    local ok, saved = pcall(save, mod)
    if not ok or saved == false then
        mod.config[key] = old
        return false
    end
    return true
end

local function sync_pvp(value)
    local pvp = names.pvp()
    if not pvp then return true end
    if not persist(pvp, 'username', value) then return false end
    -- Modern PvP gets peer names from API lobby data. Its local name is still
    -- used by the config UI and as a fallback; do not send legacy network messages.
    if pvp.LOBBY then pvp.LOBBY.username = value end
    return true
end

local busy_api
local hooked_api
function names.install()
    local api = names.api()
    if not api or api == hooked_api or type(api.connect) ~= 'function' then return end
    hooked_api = api
    local connect = api.connect
    api.connect = function(...)
        -- Seed the login before it starts, rather than briefly logging in with
        -- the preceding profile's name and reconnecting a second time.
        local index, profile = names.active()
        local value = profile and names.validate(profile.name or ('P' .. tostring(index)))
        if value and not names.in_lobby() then pcall(persist, api, 'mobile_display_name', value) end
        return connect(...)
    end
end

local function sync_api(value)
    local api = names.api()
    if not api then return true end
    local conn = api._internal and api._internal.conn
    local steam = api.networking and api.networking.steam
    -- A local name cannot change a Steam persona or an Official-server account.
    if not conn or type(conn.is_official_server) ~= 'function'
        or conn.is_official_server() or conn.force_steam_login or conn.dev_identity
        or (steam and type(steam.available) == 'function' and steam.available()) then
        return true, 'Steam/Official online names are managed externally.'
    end
    if not persist(api, 'mobile_display_name', value) then return false end
    if type(api.is_connected) ~= 'function' or not api.is_connected() then return true end
    local state = api.connection_state
    if not state then return true end
    if busy_api == api then return true, 'Updating online name...' end
    if state.use_discord_name then
        local set_display = api._internal.set_use_discord_name
        if type(set_display) ~= 'function' then return true, 'Online name currently uses Discord.' end
        busy_api = api
        local ok = pcall(set_display, false, function(err)
            busy_api = nil
            if err then names.status = 'Profile saved; online name update will retry.' end
        end)
        if not ok then busy_api = nil; return false end
        return true, 'Updating online name...'
    end
    if state.steam_name ~= value then
        if type(api.reconnect) ~= 'function' then return true, 'Online name applies at next login.' end
        -- Reauthenticate with the same device identity. Calling session_init on
        -- an existing socket would reset that session's integrity/mod report.
        api.reconnect()
    end
    return true
end

function names.sync()
    names.install()
    if not names.can_edit() then return end
    local index, profile = names.active()
    local value, err = names.validate(profile.name or ('P' .. tostring(index)))
    if not value then names.status = err; return end
    local pvp_ok, pvp_saved = pcall(sync_pvp, value)
    local api_ok, api_saved, note = pcall(sync_api, value)
    if not pvp_ok or not pvp_saved or not api_ok or not api_saved then
        names.status = 'Profile saved; multiplayer sync will retry.'
    else
        names.status = note or 'Names follow the active profile.'
    end
end

return names
