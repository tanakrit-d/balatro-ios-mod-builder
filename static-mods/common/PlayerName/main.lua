-- Native input only: do not activate Balatro's virtual/controller keyboard or
-- feed printable key names back into its separate Shift/case handling.
do
    local mod = SMODS.current_mod
    local names = assert(SMODS.load_file('names.lua', mod.id))()
    local utf8 = require('utf8')
    local editor
    local sync_timer = 0
    names.install()

    local function refresh_text()
        editor.display = editor.value:sub(1, editor.cursor) .. '|'
            .. editor.composition .. editor.value:sub(editor.cursor + 1)
    end

    local function stop_input()
        if not editor then return end
        local old = editor
        editor = nil
        love.keyboard.setTextInput(old.text_input)
        love.keyboard.setKeyRepeat(old.key_repeat)
    end

    local function focus_input()
        if not editor then return end
        local w, h = love.graphics.getDimensions()
        -- The panel sits at the top; tell SDL where input is displayed so it
        -- can keep it above the native keyboard, including in landscape.
        love.keyboard.setTextInput(true, 0, 0, w, math.floor(h * 0.35))
    end
    G.FUNCS.player_name_focus = focus_input

    G.FUNCS.player_name_cancel = function()
        local back = editor and editor.back
        stop_input()
        G.FUNCS.exit_overlay_menu()
        if back and G.FUNCS[back] then G.FUNCS[back]() end
    end

    G.FUNCS.player_name_save = function()
        if not editor then return end
        local index, profile = names.active()
        if index ~= editor.profile_index or profile ~= editor.profile then
            editor.message = 'Active profile changed. Cancel and reopen.'
            return
        end
        if not names.can_edit() then
            editor.message = 'Leave the lobby before changing your name.'
            return
        end
        if editor.composition ~= '' then
            editor.message = 'Finish typing before saving.'
            return
        end
        local value, err = names.validate(editor.value)
        if not value then
            editor.message = err
            return
        end
        local previous = profile.name
        profile.name = value
        local ok = pcall(function()
            G:save_settings()
            G.FILE_HANDLER.force = true
        end)
        if not ok then
            profile.name = previous
            editor.message = 'Could not save your name. Please try again.'
            return
        end
        stop_input()
        G.FUNCS.exit_overlay_menu()
        -- Do not reopen the profile selector here: it rereads profile.jkr and
        -- could replace the name before Balatro's queued save has been written.
        names.sync()
    end

    local function open_editor(back)
        if not names.can_edit() then return end
        stop_input()
        local index, profile = names.active()
        local value = profile.name or ('P' .. tostring(index))
        -- Existing config can predate this editor; discard malformed UTF-8.
        if type(value) ~= 'string' or not utf8.len(value) then value = '' end
        editor = {
            value = value, cursor = #value, composition = '', display = '',
            profile_index = index, profile = profile, back = back,
            message = 'Active profile only. Online play may reconnect.',
            text_input = love.keyboard.hasTextInput(),
            key_repeat = love.keyboard.hasKeyRepeat(),
        }
        refresh_text()
        local function text_row(text, scale)
            return { n = G.UIT.R, config = { align = 'cm', padding = 0.03 }, nodes = {
                { n = G.UIT.T, config = { text = text, scale = scale, colour = G.C.UI.TEXT_LIGHT } },
            } }
        end
        -- A compact panel at the top leaves room for the landscape keyboard.
        G.FUNCS.overlay_menu({ definition = {
            n = G.UIT.ROOT,
            config = { align = 'tm', minw = G.ROOM.T.w, minh = G.ROOM.T.h,
                padding = 0.08, colour = G.C.L_BLACK },
            nodes = {
                text_row('Player name - Profile ' .. tostring(index), 0.4),
                { n = G.UIT.R, config = { align = 'cm', minw = 7, minh = 0.6,
                    colour = G.C.BLACK, r = 0.1, button = 'player_name_focus' }, nodes = {
                    { n = G.UIT.O, config = { object = DynaText({
                        string = {{ ref_table = editor, ref_value = 'display' }},
                        colours = {G.C.WHITE}, scale = 0.45, silent = true,
                    }) } },
                } },
                { n = G.UIT.R, config = { align = 'cm', padding = 0.03 }, nodes = {
                    { n = G.UIT.O, config = { object = DynaText({
                        string = {{ ref_table = editor, ref_value = 'message' }},
                        colours = {G.C.WHITE}, scale = 0.3, silent = true,
                    }) } },
                } },
                { n = G.UIT.R, config = { align = 'cm' }, nodes = {
                    { n = G.UIT.C, config = { align = 'cm', padding = 0.04 }, nodes = {
                        UIBox_button({ label = {'Cancel'}, button = 'player_name_cancel', minw = 2.5, minh = 0.5, scale = 0.35 }),
                    } },
                    { n = G.UIT.C, config = { align = 'cm', padding = 0.04 }, nodes = {
                        UIBox_button({ label = {'Save'}, button = 'player_name_save', minw = 2.5, minh = 0.5, scale = 0.35 }),
                    } },
                } },
            },
        } })
        editor.overlay = G.OVERLAY_MENU
        G.CONTROLLER.text_input_hook = nil
        love.keyboard.setKeyRepeat(true)
        focus_input()
    end

    G.FUNCS.player_name_open = function() open_editor('openModUI_' .. mod.id) end
    G.FUNCS.player_name_profile = function() open_editor('profile_select') end
    G.FUNCS.player_name_pvp = function() open_editor('openModUI_MultiplayerPvP') end

    -- Standard SMODS entry point; no dependency on either multiplayer mod.
    mod.config_tab = function()
        local index, profile = names.active()
        return { n = G.UIT.ROOT, config = { align = 'cm', padding = 0.1, colour = G.C.CLEAR }, nodes = {
            { n = G.UIT.R, config = { align = 'cm' }, nodes = {
                { n = G.UIT.T, config = { text = 'Profile ' .. tostring(index or '') .. ': '
                    .. tostring(profile and profile.name or ''), scale = 0.4, colour = G.C.UI.TEXT_LIGHT } },
            } },
            UIBox_button({ label = { names.in_lobby() and 'Leave lobby to rename' or 'Rename active profile' },
                button = names.can_edit() and 'player_name_open' or 'nil', minw = 6, scale = 0.4 }),
            { n = G.UIT.R, config = { align = 'cm' }, nodes = {
                { n = G.UIT.T, config = { text = 'Maximum 16 bytes; case is preserved.', scale = 0.3, colour = G.C.UI.TEXT_LIGHT } },
            } },
            { n = G.UIT.R, config = { align = 'cm' }, nodes = {
                { n = G.UIT.O, config = { object = DynaText({
                    string = {{ ref_table = names, ref_value = 'status' }},
                    colours = {G.C.WHITE}, scale = 0.3, silent = true,
                }) } },
            } },
        } }
    end

    -- Route the active profile and PvP's existing username field to this one
    -- editor. Unrelated inputs and inactive profiles keep their behavior.
    local create_input = create_text_input
    function create_text_input(args)
        local _, profile = names.active()
        if profile and args and args.ref_table == profile and args.ref_value == 'name' then
            return UIBox_button({ label = { tostring(profile.name or 'Rename profile') },
                button = 'player_name_profile', minw = 4, scale = 0.4 })
        end
        local pvp = names.pvp()
        if profile and pvp and pvp.LOBBY and args and args.ref_table == pvp.LOBBY
            and args.ref_value == 'username' then
            return UIBox_button({ label = { tostring(profile.name or 'Rename profile') },
                button = 'player_name_pvp', minw = 4, scale = 0.4 })
        end
        return create_input(args)
    end

    local textinput = love.textinput
    love.textinput = function(text)
        if not editor then
            if textinput then return textinput(text) end
            return
        end
        text = text:gsub('%c', '')
        if not utf8.len(text) then return end
        local value = editor.value:sub(1, editor.cursor) .. text .. editor.value:sub(editor.cursor + 1)
        -- One global limit, checked before insertion; never split UTF-8.
        if #value > names.limit then
            editor.message = 'Name too long (maximum 16 bytes).'
            return
        end
        editor.value = value
        editor.cursor = editor.cursor + #text
        editor.composition = ''
        editor.message = 'Active profile only. Online play may reconnect.'
        refresh_text()
    end

    local textedited = love.textedited
    love.textedited = function(text, start, length)
        if not editor then
            if textedited then return textedited(text, start, length) end
            return
        end
        editor.composition = text
        refresh_text()
    end

    local keypressed = love.keypressed
    love.keypressed = function(key, ...)
        if not editor then
            if keypressed then return keypressed(key, ...) end
            return
        end
        if key == 'escape' then return G.FUNCS.player_name_cancel() end
        if key == 'return' or key == 'kpenter' then
            -- Done dismisses the keyboard; Save is always explicit.
            love.keyboard.setTextInput(false)
            return
        end
        if editor.composition ~= '' then return end
        local value, cursor = editor.value, editor.cursor
        if key == 'backspace' and cursor > 0 then
            local previous = utf8.offset(value, -1, cursor + 1)
            editor.value = value:sub(1, previous - 1) .. value:sub(cursor + 1)
            editor.cursor = previous - 1
        elseif key == 'delete' and cursor < #value then
            local following = utf8.offset(value, 2, cursor + 1) or (#value + 1)
            editor.value = value:sub(1, cursor) .. value:sub(following)
        elseif key == 'left' and cursor > 0 then
            editor.cursor = utf8.offset(value, -1, cursor + 1) - 1
        elseif key == 'right' and cursor < #value then
            editor.cursor = (utf8.offset(value, 2, cursor + 1) or (#value + 1)) - 1
        elseif key == 'home' then
            editor.cursor = 0
        elseif key == 'end' then
            editor.cursor = #value
        end
        refresh_text()
    end

    local update = love.update
    love.update = function(dt, ...)
        local result = update(dt, ...)
        local index, profile = names.active()
        if editor and (G.OVERLAY_MENU ~= editor.overlay or not names.can_edit()
            or editor.profile_index ~= index or editor.profile ~= profile) then
            if G.OVERLAY_MENU == editor.overlay then G.FUNCS.exit_overlay_menu() end
            stop_input()
        end
        sync_timer = sync_timer - (dt or 0)
        if not editor and sync_timer <= 0 then
            sync_timer = 1
            names.sync()
        end
        return result
    end

    local focus = love.focus
    love.focus = function(focused)
        if editor and not focused then love.keyboard.setTextInput(false) end
        if focus then return focus(focused) end
    end
end
