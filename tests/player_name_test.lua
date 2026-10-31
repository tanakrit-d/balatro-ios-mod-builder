local root = 'static-mods/common/PlayerName/'
local function equal(a, b, message) assert(a == b, (message or '') .. ': ' .. tostring(a) .. ' ~= ' .. tostring(b)) end
local saves, stored = {}, {}
local mod = { id = 'PlayerName', can_load = true }
SMODS = {
    current_mod = mod, Mods = {},
    save_mod_config = function(target)
        saves[target.id] = (saves[target.id] or 0) + 1
        stored[target.id] = { username = target.config.username, mobile_display_name = target.config.mobile_display_name }
        return true
    end,
    load_file = function(name) return loadfile(root .. name) end,
}
G = {
    STAGE = 1, STAGES = { MAIN_MENU = 1 }, SETTINGS = { profile = 1 },
    PROFILES = { { name = 'Alice', wins = 12 }, { name = 'Bob', wins = 42 } },
}
local names = dofile(root .. 'names.lua')
local official, steam, connected, lobby, reconnects = false, false, true, nil, 0
local function integrations(pvp, api)
    PVP = pvp and { id = 'MultiplayerPvP', can_load = true, config = { username = 'Guest' }, LOBBY = { username = 'Guest' } } or nil
    MPAPI = api and {
        id = 'MultiplayerAPI', can_load = true, config = { mobile_display_name = 'Guest' },
        networking = { steam = { available = function() return steam end } },
        connection_state = { steam_name = 'Guest', use_discord_name = false },
        _internal = { conn = { is_official_server = function() return official end } },
        get_current_lobby = function() return lobby end,
        is_connected = function() return connected end,
        reconnect = function() reconnects = reconnects + 1; connected = false end,
        connect = function() connected = true end,
    } or nil
    SMODS.Mods.MultiplayerPvP, SMODS.Mods.MultiplayerAPI = PVP, MPAPI
    if MPAPI then
        MPAPI._internal.set_use_discord_name = function(value, cb)
            MPAPI.connection_state.use_discord_name = value; cb(nil)
        end
    end
end

-- Every optional-mod combination, plus startup with neither global available.
for _, pair in ipairs({{false, false}, {true, false}, {false, true}, {true, true}}) do
    integrations(pair[1], pair[2]); connected = true
    names.sync()
    if PVP then equal(PVP.config.username, 'Alice'); equal(PVP.LOBBY.username, 'Alice') end
    if MPAPI then equal(MPAPI.config.mobile_display_name, 'Alice') end
    equal(G.PROFILES[2].name, 'Bob'); equal(G.PROFILES[2].wins, 42)
end

integrations(true, true); connected = true
names.sync()
G.SETTINGS.profile = 2
connected = true
names.sync()
equal(PVP.config.username, 'Bob'); equal(MPAPI.config.mobile_display_name, 'Bob')
equal(G.PROFILES[1].name, 'Alice'); equal(G.PROFILES[1].wins, 12)
G.SETTINGS.profile = 1
lobby = {}
local before = reconnects
names.sync()
equal(PVP.config.username, 'Bob'); equal(MPAPI.config.mobile_display_name, 'Bob'); equal(reconnects, before)
lobby = nil; connected = true
names.sync()
equal(MPAPI.config.mobile_display_name, 'Alice')
PVP.LOBBY.code = 'ABCDEF'; G.SETTINGS.profile = 2
names.sync(); equal(PVP.config.username, 'Alice')
PVP.LOBBY.code = nil
names.sync(); equal(PVP.config.username, 'Bob')

-- Login receives the active profile name before authentication begins.
G.SETTINGS.profile = 1
MPAPI.connect()
equal(MPAPI.config.mobile_display_name, 'Alice')

-- Disabled integrations and incompatible API shapes do not affect the profile.
PVP.can_load, MPAPI.can_load = false, false
PVP.config.username, MPAPI.config.mobile_display_name = 'Disabled', 'Disabled'
names.sync(); equal(PVP.config.username, 'Disabled'); equal(MPAPI.config.mobile_display_name, 'Disabled')
PVP.can_load, MPAPI.can_load = true, true
MPAPI._internal = nil
names.sync(); equal(G.PROFILES[1].name, 'Alice')
integrations(true, true)
official = true; names.sync(); equal(MPAPI.config.mobile_display_name, 'Guest')
official, steam = false, true
names.sync(); equal(MPAPI.config.mobile_display_name, 'Guest')
steam = false

-- Respect custom savers; a failed integration save is isolated and retried.
PVP.save_mod_config = function() return false end
names.sync(); equal(PVP.config.username, 'Alice') -- already synchronized above
PVP.config.username = 'Old'
names.sync(); equal(PVP.config.username, 'Old'); equal(G.PROFILES[1].name, 'Alice')
PVP.save_mod_config = nil
names.sync(); equal(PVP.config.username, 'Alice')
connected = true
MPAPI.connection_state.steam_name = 'Alice'
MPAPI.connection_state.use_discord_name = true
names.sync(); equal(MPAPI.connection_state.use_discord_name, false)

equal(names.validate('1234567890123456'), '1234567890123456')
equal(names.validate('12345678901234567'), nil)
equal(names.validate(string.rep('é', 8)), string.rep('é', 8))
equal(names.validate(string.rep('é', 9)), nil)
equal(names.validate('\255'), nil)
equal(names.validate('  Alice\n '), 'Alice')

-- Load the actual UI entry point with LÖVE events and minimal UI doubles.
integrations(false, false)
local native, repeat_keys, forwarded, profile_saves = false, false, 0, 0
local display, message
G.FUNCS, G.CONTROLLER, G.FILE_HANDLER = {}, {}, {}
G.UIT = { R = 1, C = 2, T = 3, O = 4, ROOT = 5 }
G.C = { UI = { TEXT_LIGHT = {} }, WHITE = {}, BLACK = {}, L_BLACK = {}, CLEAR = {} }
G.ROOM = { T = { w = 16, h = 9 } }
function G:save_settings() profile_saves = profile_saves + 1; self.FILE_HANDLER = {} end
function UIBox_button(args) return args end
function DynaText(args)
    local ref = args.string[1]
    if ref.ref_value == 'display' then display = ref.ref_table end
    if ref.ref_value == 'message' then message = ref.ref_table end
    return args
end
local plain_inputs = 0
function create_text_input(args) plain_inputs = plain_inputs + 1; return args end
G.FUNCS.overlay_menu = function(args) G.OVERLAY_MENU = args end
G.FUNCS.exit_overlay_menu = function() G.OVERLAY_MENU = nil end
G.FUNCS.profile_select = function() end
love = {
    graphics = { getDimensions = function() return 1200, 600 end },
    keyboard = {
        hasTextInput = function() return native end,
        hasKeyRepeat = function() return repeat_keys end,
        setTextInput = function(value) native = value end,
        setKeyRepeat = function(value) repeat_keys = value end,
    },
    update = function() end,
    keypressed = function() forwarded = forwarded + 1 end,
    textinput = function() forwarded = forwarded + 1 end,
}
dofile(root .. 'main.lua')
assert(mod.config_tab())
create_text_input({ ref_table = G.PROFILES[2], ref_value = 'name' })
equal(plain_inputs, 1)
local active_input = create_text_input({ ref_table = G.PROFILES[1], ref_value = 'name' })
equal(active_input.button, 'player_name_profile'); equal(plain_inputs, 1)

local function open(value)
    G.PROFILES[G.SETTINGS.profile].name = value or ''
    G.FUNCS.player_name_open()
    assert(native and repeat_keys)
end
local function cancel()
    G.FUNCS.player_name_cancel()
    assert(not native and not repeat_keys)
end
open('')
love.keypressed('a'); love.textinput('aLiCe')
equal(display.value, 'aLiCe')
love.keypressed('left'); love.textinput('X'); equal(display.value, 'aLiCXe')
love.keypressed('delete'); love.keypressed('backspace'); equal(display.value, 'aLiC')
love.keypressed('home'); love.textinput('é'); love.keypressed('backspace'); equal(display.value, 'aLiC')
love.keypressed('end'); love.textinput('e')
G.FUNCS.player_name_save()
equal(G.PROFILES[1].name, 'aLiCe'); equal(G.PROFILES[2].name, 'Bob'); equal(profile_saves, 1)
assert(not native and not repeat_keys and G.FILE_HANDLER.force)
open('Original'); love.textinput('X'); cancel(); equal(G.PROFILES[1].name, 'Original')
love.keypressed('a'); love.textinput('a'); equal(forwarded, 2)
open(''); love.textinput('   '); G.FUNCS.player_name_save()
equal(message.message, 'Enter a name first.'); equal(profile_saves, 1); cancel()
open('123456789012345'); love.textinput('é'); equal(display.value, '123456789012345'); cancel()
open('Alice'); love.textedited('名', 0, 1); G.FUNCS.player_name_save(); equal(profile_saves, 1)
love.textinput('名'); equal(display.value, 'Alice名')
love.keypressed('return'); assert(not native); equal(profile_saves, 1)
G.FUNCS.player_name_focus(); assert(native); love.focus(false); assert(not native); cancel()

-- A profile switch during editing cannot rename the newly active profile.
open('Alice'); love.textinput('X'); G.SETTINGS.profile = 2
G.FUNCS.player_name_save(); equal(G.PROFILES[2].name, 'Bob'); equal(profile_saves, 1)
love.update(1); assert(not native and not repeat_keys)
G.SETTINGS.profile = 1
open('Alice'); G.OVERLAY_MENU = {}; love.update(1); assert(not native and not repeat_keys)
open('Alice'); G.STAGE = 2; love.update(1); assert(not native and not repeat_keys); G.STAGE = 1

open('Alice')
local save = G.save_settings
G.save_settings = function() error('disk error') end
love.textinput('X'); G.FUNCS.player_name_save(); equal(G.PROFILES[1].name, 'Alice'); assert(native)
G.save_settings = save; cancel()
native, repeat_keys = true, true
open('Alice'); G.FUNCS.player_name_cancel(); assert(native and repeat_keys)
native, repeat_keys = false, false

-- Integrations loaded after this mod are picked up without a restart.
integrations(true, true); G.SETTINGS.profile = 2; connected = true
love.update(1); equal(PVP.config.username, 'Bob'); equal(MPAPI.config.mobile_display_name, 'Bob')
local pvp_input = create_text_input({ ref_table = PVP.LOBBY, ref_value = 'username' })
equal(pvp_input.button, 'player_name_pvp')
open('Bob'); lobby = {}; G.FUNCS.player_name_save(); equal(profile_saves, 1)
love.update(1); assert(not native and not repeat_keys); lobby = nil
print('Player Name profile, integration and native-input checks passed')
