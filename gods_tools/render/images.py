from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from PIL import Image, ImageDraw

from gods_tools.formats.atlas_dat import AtlasDat, AtlasRecord
from gods_tools.formats.pi1 import Pi1Image


@dataclass(frozen=True)
class AtlasSheet:
    image: Image.Image
    tile_positions: dict[int, tuple[int, int, int, int]]


def render_pi1(pi1: Pi1Image) -> Image.Image:
    return pi1.to_pillow()


def crop_atlas_record(sheet: Image.Image, record: AtlasRecord) -> Image.Image:
    return sheet.crop((record.x, record.y, record.x + record.width, record.y + record.height))


def build_atlas_contact_sheet(
    sheet: Image.Image,
    atlas: AtlasDat,
    columns: int = 8,
    padding: int = 8,
    label_height: int = 14,
) -> AtlasSheet:
    if not atlas.records:
        blank = Image.new("RGB", (320, 80), "black")
        draw = ImageDraw.Draw(blank)
        draw.text((10, 10), "No atlas records", fill="white")
        return AtlasSheet(blank, {})

    crops = [crop_atlas_record(sheet, record).convert("RGB") for record in atlas.records]
    cell_width = max(crop.width for crop in crops) + padding * 2
    cell_height = max(crop.height for crop in crops) + padding * 2 + label_height
    rows = ceil(len(crops) / columns)

    out = Image.new("RGB", (columns * cell_width, rows * cell_height), "black")
    draw = ImageDraw.Draw(out)
    positions: dict[int, tuple[int, int, int, int]] = {}

    for record, crop in zip(atlas.records, crops):
        col = record.index % columns
        row = record.index // columns
        cell_x = col * cell_width
        cell_y = row * cell_height
        crop_x = cell_x + padding
        crop_y = cell_y + padding + label_height
        out.paste(crop, (crop_x, crop_y))
        draw.text((cell_x + padding, cell_y + 2), f"#{record.index}", fill="white")
        positions[record.index] = (
            crop_x,
            crop_y,
            crop_x + crop.width,
            crop_y + crop.height,
        )

    return AtlasSheet(out, positions)
