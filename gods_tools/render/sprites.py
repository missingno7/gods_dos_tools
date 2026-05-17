from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from gods_tools.formats.atlas_dat import load_packed_atlas_dat
from gods_tools.formats.pi1 import Pi1Image, load_packed_pi1

OBJECT_SPRITE_INDEX_BASE = 170
WEAPON_SPRITE_INDEX_BASE = 302


@dataclass(frozen=True)
class SpriteBank:
    sprites: tuple[Image.Image, ...]
    palette_source: Path | None

    def sprite(self, sprite_index: int) -> Image.Image | None:
        if 0 <= sprite_index < len(self.sprites):
            return self.sprites[sprite_index]
        return None

    def object_sprite(self, object_info_index: int) -> Image.Image | None:
        return self.sprite(OBJECT_SPRITE_INDEX_BASE + object_info_index)

    def weapon_sprite(self, weapon_info_index: int) -> Image.Image | None:
        return self.sprite(WEAPON_SPRITE_INDEX_BASE + weapon_info_index)


def _rgba_sprite_sheet(pi1: Pi1Image, palette_words: tuple[int, ...] | None) -> Image.Image:
    words = palette_words or pi1.palette_words
    palette: list[tuple[int, int, int]] = []
    for word in words:
        palette.append(
            (
                ((word >> 8) & 0x7) * 255 // 7,
                ((word >> 4) & 0x7) * 255 // 7,
                (word & 0x7) * 255 // 7,
            )
        )
    while len(palette) < 16:
        palette.append((0, 0, 0))

    rgba = bytearray()
    for value in pi1.pixels:
        r, g, b = palette[value]
        alpha = 0 if value == 0 else 255
        rgba.extend((r, g, b, alpha))
    return Image.frombytes("RGBA", (pi1.width, pi1.height), bytes(rgba))


def _append_sheet_sprites(
    sprites: list[Image.Image],
    pi1_path: Path,
    palette_words: tuple[int, ...] | None,
) -> None:
    dat_path = pi1_path.with_suffix(".DAT")
    if not dat_path.exists():
        return
    pi1 = load_packed_pi1(pi1_path)
    dat = load_packed_atlas_dat(dat_path)
    sheet = _rgba_sprite_sheet(pi1, palette_words)
    for record in dat.records:
        sprites.append(sheet.crop((record.x, record.y, record.x + record.width, record.y + record.height)))


def _palette_reference(game_dir: Path, level: int) -> tuple[tuple[int, ...] | None, Path | None]:
    # Kroah's viewer uses level ?B palette for the shared sprite atlases, even while inspecting half A.
    candidates = [game_dir / f"PLEVEL{level}B.PI1", game_dir / f"PLEVEL{level}A.PI1"]
    for path in candidates:
        if path.exists():
            pi1 = load_packed_pi1(path)
            return pi1.palette_words, path
    return None, None


def load_level_sprite_bank(game_dir: str | Path, level: int, world: str) -> SpriteBank:
    game_dir = Path(game_dir)
    palette_words, palette_path = _palette_reference(game_dir, level)

    sprites: list[Image.Image] = []
    for stem in ("PALWAYS1", "PALWAYS2", "PALWAYS3", "PGODFONT", "POBJ1", "POBJ2"):
        _append_sheet_sprites(sprites, game_dir / f"{stem}.PI1", palette_words)

    # Keep complete sprite numbering available for later enemy inspectors and thumbnails.
    for stem in (f"PLEVEL{level}A", f"PLEVEL{level}B"):
        _append_sheet_sprites(sprites, game_dir / f"{stem}.PI1", palette_words)

    return SpriteBank(sprites=tuple(sprites), palette_source=palette_path)
