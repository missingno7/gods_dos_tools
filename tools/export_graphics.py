from __future__ import annotations

import argparse
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gods_tools.formats.atlas_dat import load_packed_atlas_dat
from gods_tools.formats.pi1 import load_packed_pi1
from gods_tools.formats.resources import discover_graphics_resources
from gods_tools.render.images import build_atlas_contact_sheet, render_pi1


def main() -> None:
    parser = argparse.ArgumentParser(description="Export unpacked GODS PI1 sheets and atlas contact sheets.")
    parser.add_argument("--game-dir", type=Path, default=Path("game_data/Gods"))
    parser.add_argument("--out", type=Path, default=Path("exports/graphics"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    resources = discover_graphics_resources(args.game_dir)

    for resource in resources:
        pi1 = load_packed_pi1(resource.pi1_path)
        image = render_pi1(pi1).convert("RGB")
        image.save(args.out / f"{resource.pi1_path.stem}.png")

        if resource.dat_path is not None:
            atlas = load_packed_atlas_dat(resource.dat_path)
            contact = build_atlas_contact_sheet(image, atlas).image
            contact.save(args.out / f"{resource.pi1_path.stem}__atlas.png")

    print(f"Exported {len(resources)} graphics resources to {args.out}")


if __name__ == "__main__":
    main()
