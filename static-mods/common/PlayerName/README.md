# Player Name

Rename the **active Balatro profile** using the device keyboard. Open its name field in the profile selector, or **Mods → Player Name → Config**.

Names preserve case and share one 16-byte limit. ASCII names can contain 16 characters; other scripts may use more bytes per character. Oversized input is rejected without splitting characters. Existing longer names are left alone until edited.

MultiplayerPvP and MultiplayerAPI are optional. Installed, enabled integrations follow the active profile, including after a profile switch. Renaming leaves other profiles and their progress alone. Leave your lobby before renaming; changes detected during a lobby wait until you leave. Online synchronization may reconnect using the same device account.

MultiplayerAPI name changes apply to Steam-free Community login. Its Discord-name preference is turned off when synchronizing so the profile name is visible. Steam personas and Official-server names remain externally managed. A profile switch changes the name, not the multiplayer account or its progress.

The active profile and PvP's username fields open this same editor. Other text fields retain their existing input behavior. Tap the name field to reopen a dismissed keyboard. Return hides the keyboard; Save commits the name and Cancel discards the edit.

This is a standalone Steamodded mod with no multiplayer dependency or Lovely patches. It uses the documented [Mod Object API](https://docs.smods.dev/API%20Documentation/The-Mod-Object/) for its config tab, integration availability and custom config saving, and the [UI API](https://docs.smods.dev/Guides/UI-Guide/) for the editor. Balatro provides profile storage; no second copy of profile names is kept in a mod-wide config.
