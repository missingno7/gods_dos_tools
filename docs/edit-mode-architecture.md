# v18 edit-mode architecture

This pass does **not** turn the viewer into a file-writing editor yet. It creates the missing
architectural boundary required to do that safely.

## New layers

### `LevelDocument`

`gods_tools.model.document.LevelDocument` is the immutable editor-facing snapshot of one decoded
DOS GODS level. It holds:

- map payload,
- PALFILS payload,
- object/weapon tables,
- sprite bank,
- flying-path data,
- derived logic graph,
- diagnostics.

The Tkinter screen still keeps a light `LoadedLevel` wrapper for the current rendered image, but all
source truth now lives in the document.

### `EntityIndex`

`gods_tools.model.entities.EntityIndex` gives the browser and future tools one normalized index over
selectable entities:

- events,
- puzzles,
- switches,
- teleports,
- hardcoded teleport destinations,
- objective locations,
- player start,
- hints,
- trapdoors,
- moving blocks,
- enemy waves,
- flying paths,
- physical logic targets,
- map items.

The Level Viewer Entity Browser is now populated from this index rather than reconstructing each
category independently in the GUI.

### `EditSession` and `WriteBackPlan`

`gods_tools.edit.session.EditSession` is the first edit-mode nucleus. It keeps:

- an immutable `LevelDocument`,
- an auditable `WriteBackPlan` of in-place raw byte patches.

The plan validates:

- no length-changing edits,
- no overlapping patches,
- expected `before` bytes match before application.

Prepared safe patch primitives:

1. move an existing map item by patching its `x/y` words,
2. change one layer-A tile byte,
3. change one layer-B byte for future collision/event work.

This deliberately stops before PKWARE recompression and on-disk replacement. The next save-back
milestone can add repacking only after byte-patch previews and roundtrip parsers are trusted.

## GUI exposure

The Level Viewer now has an **Edit prep** tab. It shows:

- decoded source sizes,
- stable payload offsets,
- prepared edit primitives,
- the current write-back patch plan,
- unified entity-index counts.

This keeps the editor honest about its current state: structurally edit-ready, not yet a save-back
editor.
