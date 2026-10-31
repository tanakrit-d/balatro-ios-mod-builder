# iOS Mod Bundler

Creates and bundles pre-modded versions of Multiplayer and Pokermon.

| Mod | PvP Legacy | PvP | Pokermon | Description |
| --- | :---: | :---: | :---: | --- |
| Steamodded | ✓ | ✓ | ✓ | Loads mods and provides shared mod APIs. |
| [Mobile Mod Menu](static-mods/common/BalatroMobileMenuMod) | ✓ | ✓ | ✓ | Adds mobile settings, readable fonts, and tutorial controls. |
| [Sticky Fingers](static-mods/common/sticky-fingers) | ✓ | ✓ | ✓ | Adds touch controls for moving and using cards. |
| [SetFPS](static-mods/common/SetFPS) | ✓ | ✓ | ✓ | Lets you choose the frame-rate cap. |
| [Player Name](static-mods/common/PlayerName) | ✓ | ✓ | ✓ | Renames the active profile and synchronizes supported multiplayer names. |
| Multiplayer 0.5.5 | ✓ | — | — | Provides the archived multiplayer experience. |
| Multiplayer PvP | — | ✓ | — | Adds competitive multiplayer games. |
| MultiplayerAPI | — | ✓ | — | Handles multiplayer accounts, connections, and lobbies. |
| Pokermon | — | — | ✓ | Adds Pokémon-themed Jokers and other content. |

All streams also include Lovely, the runtime injector used to apply mod patches.

## Multiplayer (PvP) (Legacy)

Includes the original [Multiplayer 0.5.5](https://github.com/Balatro-Multiplayer/BalatroMultiplayerPvP/tree/v0.5.5). This archived version is separate from Multiplayer PvP and does not receive mod updates.

## Multiplayer (PvP)

Includes the mobile branches of [Multiplayer PvP](https://github.com/tanakrit-d/BalatroMultiplayerPvP/tree/mobile) and [MultiplayerAPI](https://github.com/tanakrit-d/BalatroMultiplayerAPI/tree/mobile), with Steam-free login for custom Community servers and native iOS TLS support.

Set the bundled server defaults in [`mod-configs/multiplayer/MultiplayerAPI/config.lua`](mod-configs/multiplayer/MultiplayerAPI/config.lua). Existing Steamodded saved settings on a device take precedence.

Rename the active profile through its name field or **Mods → Player Name → Config**, using the device keyboard. Its name also applies to supported multiplayer mods; leave your lobby before renaming.

## Pokermon (PK)

Includes [Pokermon](https://github.com/InertSteak/Pokermon), which adds Pokémon-themed Jokers and new content. Build your run around a team of Pokémon Jokers.
