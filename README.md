# Card Game Builder

Creates and bundles pre-modded versions of Multiplayer and Pokermon.

## Multiplayer (MP)

Includes [Multiplayer](https://github.com/Balatro-Multiplayer/BalatroMultiplayer), which adds online competitive play. Create or join a lobby to play against other players.

## Pokermon (PK)

Includes [Pokermon](https://github.com/InertSteak/Pokermon), which adds Pokémon-themed Jokers and new content. Build your run around a team of Pokémon Jokers.

## Development

This is a scripts-only Python project. Install its dependencies with `uv sync`, then run scripts directly, for example `uv run python scripts/builder.py --help`.

Run the checks with `uv run python -m unittest discover -s tests -v`, `uv run ruff check scripts tests`, and `uv run ty check scripts tests`. Native installer tests require macOS and Clang.

Republishing an existing stream version replaces its assets and moves its Git tag to the build commit recorded in the release notes.
