# DOS GODS reverse-engineering toolkit

Python/Tkinter project for exploring the **DOS version of GODS**.

## Current milestone

The project follows the same structure as the other DOS editor projects:

- bundled `game_data/Gods/`
- modular parser / renderer / GUI split
- **Graphics Viewer** for packed PI1 screens and DAT atlases
- first real **Level Viewer** for packed DOS map files and PALFILS logic overlays

### Implemented now

- PKWARE DCL Implode decompression for DOS GODS `P*` resources
- `.PI1` decode into 320×200 indexed images with the embedded 16-color palette
- paired `.DAT` atlas parsing for sprite/tile crop rectangles
- **Graphics Viewer**:
  - PI1 screen preview
  - DAT atlas contact sheet
  - raw decompressed metadata
- **Level Viewer**:
  - parses `PLEV1A.MAP` … `PLEV4B.MAP`
  - renders the full 128×64 map at 32×16 tiles = **4096×1024 px**
  - uses `PBITS*` map tiles plus the shared per-level `PXTRA*` tile bank
  - optional overlays for layer-B collision, decoded event cells, item markers, puzzle markers, raster background, and grid
  - real map-item sprite rendering from the original shared sprite bank
  - PALFILS logic overlays for walking/intelligent enemy wave origins, switches, teleports, trapdoors, moving blocks, and hints
  - click-to-inspect map cell coordinates and raw layer A/B values
  - parsed details panel for map items, puzzle strings, and puzzle records
  - **Logic inspector** for selected map events, recursive trigger chains, and physical puzzle-effect targets:
    - spawned objects / weapons
    - open / close doors
    - backdoor teleports and world-complete exits
    - resolved type-4 destructable-object destruction targets
    - trapdoors
  - **Entity browser** for jumping through level logic without hunting manually in the map:
    - events, puzzles, switches, teleports, trapdoors, moving blocks
    - enemy waves and physical logic targets
    - map items with object/weapon names
    - click an entity to select it, center the map, and trace its logic component
- batch export scripts for graphics and level map PNGs

## Run

```bash
python -m pip install -r requirements.txt
python run_editor.py
```

Optional external data path:

```bash
python run_editor.py --game-dir "C:/Games/GODS"
```

## Batch export

Graphics sheets and atlas sheets:

```bash
python tools/export_graphics.py
```

Rendered level maps:

```bash
python tools/export_levels.py
```

With overlays:

```bash
python tools/export_levels.py --collision --events --items --puzzles --waves --switches --teleports --trapdoors --moving-blocks --hints --grid
# rendered map item sprites are enabled by default; use --no-item-sprites to hide them
```

## Tests

```bash
PYTHONPATH=. pytest -q
```

## Project layout

```text
gods_tools/
  formats/   pure parsers and decompression
  render/    Pillow render helpers
  gui/       Tkinter UI panels
docs/        RE notes and decisions
tools/       export helpers
tests/       smoke tests
game_data/   provided DOS GODS files
```

## Next phase

The Level Viewer now has a first proper **logic navigation loop**: click in the map, or pick an
entity in the browser, and the editor selects it, centers the view, and traces the relevant graph
component. The next natural targets are:

- keep refining enemy-wave semantics and DOS enemy-info / sprite identity
- give selected entity rows richer structured details beyond the text inspector
- refine teleport/backdoor relation drawing into clearer multi-hop graph semantics
- turn the now-working overlay presets into a cleaner editor-mode toolbar as the GUI matures
- keep testing DOS-specific differences against Kroah's Amiga/ST assumptions


### Logic inspector

The **Level Viewer** now has a **Logic inspector** tab. Enable the event overlay, click a yellow
map event cell, and the viewer will:

- show the decoded event type and parameter,
- list direct and incoming relations,
- draw selected event links over the map,
- optionally recurse through `TriggerEvent` chains and event-dependent puzzle conditions.

This is the first step toward an editor that treats GODS level logic as a navigable trigger graph,
not just as raw tables.

### v9 additions

- flying-wave `.PAT` decoder for `PGOD01.PAT` … `PGOD04.PAT`, including absolute and trigger-relative path semantics,
- Level Viewer overlay for the **actual flight polylines** at map event cells that spawn flying waves,
- one-click overlay presets: **Clean**, **Objects**, **Puzzle**, **Enemy**, **Full RE**,
- flying-wave rows in the Entity Browser now show path type and node count when the `.PAT` bank is available.


### v10 additions

- enemy-wave `reward` fields are decoded in editor terms:
  - `0..10` = weapon reward,
  - `11+` = object reward,
  - `0xFF` / `0xFFFF` = no reward depending on record width;
- Entity Browser wave rows show human-readable reward descriptions from `POBJECTS.*` / `PWEAPONS.*`;
- **Wave reward previews** overlay draws the rewarded item near walking/intelligent wave spawns and near the resolved first point of map-triggered flying-wave paths;
- **Flying paths** now have their own Entity Browser group. Selecting a path filters the map to that path and shows which flying-wave definitions and event cells use it;
- `tools/export_levels.py` gained `--flying-paths` and `--wave-rewards`.

Reward previews are width-aware: they use the decoded enemy dimensions from the lifted Kroah enemy-info tables and follow the same centering rule as the original viewer.

### v11 enemy layer

The Level Viewer can now draw decoded enemy sprites for walking, intelligent walking,
intelligent flying, and event-triggered flying waves. Enable **Enemy sprites** or use
the **Enemy** preset. The Entity Browser and flying-path inspector now display enemy
sprite IDs, dimensions, and decoded action-category names. Reward previews use enemy
width-aware placement.

### v12 unified map selection and enemy inspector

- clicking an enemy sprite in the rendered map now selects the underlying wave definition, not just the tile below it;
- the **Enemy Wave Inspector** shows category, count, HP, reward, sprite metadata, path details for ordinary flying waves, and all triggering events/cells;
- Entity Browser enemy rows now open the same inspector as map clicks, so list navigation and direct spatial interaction are unified;
- map hover text previews whether the cursor is over an enemy wave, a logic target, or plain tile space before clicking.

### v14 logic closure additions

- PALFILS teleport rows are now classified as **bound** vs. **unbound / likely stale** instead of treating every nonzero row as live.
- The editor exposes **Hardcoded teleport destinations** extracted from unpacked DOS `GAME.EXE` for Levels 1–2.
- The editor exposes **Intelligent-enemy objective locations** extracted from unpacked DOS `GAME.EXE` for Levels 1–4.
- Teleport table targets, hardcoded teleport destinations, and objective locations all have their own overlay/browser presentation.
- `tools/analyze_logic_catalog.py` now reports the teleport-row binding split and the number of executable-derived special logic points.

### v15 map object inspector

- clicking a real map item sprite now selects the underlying item slot before falling back to nearby trigger/logic markers;
- the **Object Inspector** shows raw item ID, object/weapon metadata, sprite bounds, effect/value fields, and editor-facing roles;
- switches expose their exact PALFILS switch-state binding;
- teleport stones expose their bound teleport table destinations or explicitly note that they may use hardcoded teleport sequencing;
- destructable items, inventory-condition sources, switches, and teleport stones now expose their connected logic subgraph directly from the item selection;
- Entity Browser **Map items** rows open the same Object Inspector as a direct map click, matching the unified enemy workflow.

### v16 mechanism view

- Added a dedicated **Mechanism view** tab next to the low-level Logic Inspector.
- The tab narrates the same decoded graph as a designer-facing story:
  - entry trigger events and map cells,
  - direct event actions,
  - puzzle conditions,
  - puzzle effects and chained events,
  - switch/teleport physical bindings.
- Mechanism stories work for selected events, map items, logic targets, enemy waves, and flying paths.
- Large recursive components are summarized rather than flooding the view with every row; the Logic Inspector remains the exhaustive raw-edge companion.

### v17 completion pass

- Added explicit **chest key → chest** graph bindings across map items, puzzle-spawned objects, and wave rewards.
- Added **Reveal Clues → Hint** links by the original matching-X rule.
- Added a **Player start** overlay and Entity Browser entry.
- Added **Hidden spawned object/weapon previews** so puzzle-spawned items can be reviewed without selecting each puzzle.
- Added **Selected moving-block action preview** to visualize the decoded movement route for a selected MB event/block.
- Added a dedicated **Diagnostics** tab plus richer `tools/analyze_logic_catalog.py` reporting.

### v18 editor-core cleanup and write-back preparation

- Added an immutable `LevelDocument` as the decoded source-of-truth boundary beneath the GUI.
- Added a normalized `EntityIndex`; the Entity Browser is now populated from this shared model instead of rebuilding every category ad hoc in the Tkinter panel.
- Added `EditSession` + `WriteBackPlan` scaffolding for safe future edit mode:
  - exact raw byte patches,
  - overlap checks,
  - precondition checks against the original payload,
  - preview application to unpacked map data.
- Prepared first in-place edit primitives:
  - move an existing map item,
  - change one Layer A tile byte,
  - change one Layer B byte.
- Added an **Edit prep** tab that documents payload offsets, current patch plan, prepared edit primitives, and entity-index totals.
- Added `docs/edit-mode-architecture.md` and tests for the new document/index/patch layers.

This milestone is intentionally **pre-save-back**. It makes the editor structurally ready for a real
write-back mode without prematurely introducing recompression or on-disk mutation.


## v19 UX pass: scoped logic overlay and browser sync

This version starts moving the most cluttered logic presentation out of the baked bitmap and into a real canvas overlay layer:

- selected logic links are drawn as screen-space canvas overlays (labels stay readable across zoom levels),
- logic scope is selectable: `Selected`, `One hop`, `Full`,
- global / non-spatial logic points are no longer drawn as misleading map-space lines,
- double-clicking a rendered entity also selects and scrolls to the same entity in Entity Browser.

The rest of the map renderer still uses the existing PIL-based overlay pass, but the logic-selection presentation now sits on a safer path toward a fully decoupled editor overlay system.


## v20 overlay architecture pass

This pass extends the canvas-overlay approach beyond the selected logic graph:

- most semantic markers now render as real canvas overlays instead of being baked into the bitmap,
- ambient overlays are intentionally quieter (mostly shapes without labels),
- selection-specific context still gets the richer labels/relationship view,
- the left panel is split into tabs (`Browse`, `Overlays`, `Status`),
- overlay controls are grouped into cards like `Map items`, `Enemies and paths`, and `Mechanisms and navigation`.

Dense image-like layers (tiles, sprites, hidden spawned sprite previews, reward previews, collision fill, grid) still use the existing render pass.


## v21 layout cleanup

This pass tightens the Level Viewer layout and text-overlay consistency:

- level-map selection is now a compact top-bar dropdown instead of a left-panel list,
- overlay presets live inside the `Overlays` tab, alongside the grouped overlay controls,
- enemy labels such as `WW`, `IW`, `IF`, and dynamic `FW/E` labels are rendered through the canvas overlay layer instead of being baked into the bitmap sprite render.
