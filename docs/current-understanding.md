# Current understanding — DOS GODS

## Packed resource layer

The DOS distribution uses `P*` prefixed resources. These are directly compressed with
**PKWARE Data Compression Library (DCL) Implode** streams.

Confirmed examples:

- `PLEV1A.MAP` unpacks from 6,061 bytes to 21,868 bytes.
- `PALWAYS1.PI1` unpacks from 17,822 bytes to 32,034 bytes.

The Python project uses `dclimplode` for this layer.

## Graphics sheets: `.PI1`

Unpacked `.PI1` payloads are exactly **32,034 bytes**:

- 2 bytes: resolution word
- 32 bytes: 16 big-endian palette words
- 32,000 bytes: 320×200, 4-plane bitmap

This matches the classic low-resolution DEGAS-style `.PI1` layout.

## Atlas metadata: `.DAT`

Paired sprite-sheet metadata files such as:

- `PALWAYS1.DAT`
- `PLEVEL1A.DAT`
- `POBJ1.DAT`

unpack to:

- 2-byte big-endian record count
- `count × 10` bytes of records

Each record currently parses as:

```text
u16 width_minus_one
u16 height_minus_one
u16 unknown
u16 x
u16 y
```

The first matched sheets show `unknown == 0` for the observed graphics atlas files.

Examples:

- `PALWAYS1.DAT`: 39 records
- `PLEVEL1A.DAT`: 60 records
- `POBJ1.DAT`: 161 records

The GUI uses these rectangles to build a quick atlas contact sheet.

## DOS level maps: `PLEV*.MAP`

The packed DOS maps now parse cleanly in Python. The unpacked size varies only with the
raster-palette length:

- 21,868 bytes for raster palette size 20
- 21,870 bytes for raster palette size 21
- 21,874 bytes for raster palette size 23
- 21,834 bytes for raster palette size 3

The map structure matches the layout seen in Kroah's viewer source:

```text
u16 raster_color_count
u16 raster_height
u16[raster_color_count] raster_palette
u8[128 * 64] layer_a
u8[128 * 64] layer_b
200 × { u16 pixel_x, u16 pixel_y, u16 object_or_weapon_id }
40 puzzle-string pointers + fixed puzzle-string text area
100 × 24-byte puzzle records
```

The Level Viewer renders layer A as a 128×64 map of 32×16 cells, producing a
**4096×1024 px** level image. Layer B is currently exposed as overlays:

- `0` empty
- `1` impassable / wall-style overlay
- `2` stairs-style overlay
- `>=3` event-related cell references, decoded as PALFILS event index `value - 3` when the matching `PALFILS.0YX` file is available

## Important DOS tile-bank discovery

The DOS maps use tile ids above 120 in **every** map half. A single `PBITS*.PI1`
contains 120 regular 32×16 map tiles, so these ids require an extra bank.

The DOS data set provides only one `PXTRA` image per level:

- `PXTRA1B.PI1`
- `PXTRA2A.PI1`
- `PXTRA3A.PI1`
- `PXTRA4B.PI1`

Empirically, that single extra bank must be shared by **both A and B halves of the same level**:

- `PLEV1A` and `PLEV1B` both use `PXTRA1B`
- `PLEV2A` and `PLEV2B` both use `PXTRA2A`
- `PLEV3A` and `PLEV3B` both use `PXTRA3A`
- `PLEV4A` and `PLEV4B` both use `PXTRA4B`

This resolves all observed layer-A tile ids: the renderer loads 240 tile slots per map
and currently finds **no missing tile ids** across all eight maps.

This is also a useful warning that Kroah's Amiga/ST-oriented filename selection logic
cannot be copied blindly for the DOS resource layout.

## PALFILS level logic

The packed DOS logic files `PALFILS.0A1` … `PALFILS.0B4` unpack to **8,760 bytes** each.
That exactly matches the structure used by Kroah's viewer, including the final 80 zero bytes:

```text
0x0000  100 × 8-byte flying-wave records
0x0320  4-byte events header + 253 × 4-byte event records
0x0718  100 × 16-byte walking-wave records
0x0D58   50 × 22-byte intelligent flying-wave records
0x11A4   50 × 22-byte intelligent walking-wave records
0x15F0   64 × 6-byte switch records
0x1770   30 × 6-byte teleport records
0x1824   20 × 6-byte trapdoor records
0x189C   25 × 28-byte moving-block records
0x1B58   40 hint X-values + 40 fixed 40-byte hint strings
0x21E8   80 trailing zero bytes
```

This is strong evidence that the DOS logic layer is essentially the same as the Amiga/ST
layout documented by the older viewer. The Python Level Viewer now parses this file and can
render optional overlays for:

- decoded layer-B event labels, e.g. `WW`, `P`, `MB0`, `G`
- walking and intelligent wave spawn markers
- switches
- teleport target rectangles
- trapdoors and their open/closed state
- moving block positions, target points, and rough path lines
- hint X-lines

`POBJECTS.*` and `PWEAPONS.*` are now parsed for item names/types and are used together with the shared
`PALWAYS*`, `PGODFONT`, `POBJ1`, and `POBJ2` sprite bank to render real item sprites on the map.
`PGOD0?.PAT` is now decoded and used for flying-path visualization.

## Logic graph layer — v4

The DOS `PALFILS.*` relationship layer now has a small editor-facing graph model in
`gods_tools/formats/logic.py`. It is intentionally independent from Tkinter rendering so it
can later be reused by a real editor/write-back workflow.

Decoded relations currently include:

- map event cell → event record target
  - walking wave
  - intelligent walking wave
  - intelligent flying wave
  - puzzle record
  - moving block action
- puzzle effect `TriggerEvent` → target event (`param - 1`, matching Kroah's viewer)
- puzzle condition `EventTriggered` / `EventNotTriggered` → puzzle (`param - 1`)
- puzzle condition `SwitchOn` / `SwitchOff` → puzzle
- puzzle effect `OpenTrapdoor` / `CloseTrapdoor` → trapdoor record
- spatial puzzle-effect targets adapted from Kroah's viewer geometry:
  - `SpawnObject` / `SpawnWeapon` → item spawn point at puzzle XY
  - `OpenDoor` / `CloseDoor` → 32×48 door target centered from puzzle XY
  - `OpenBackdoorTeleport` → backdoor target plus decoded destination rectangle
  - `OpenBackdoorWorldCompleted` → world-complete backdoor target
  - `DestroyType4` → resolved target destructable map item or spawned destructable puzzle object when one sits at/near the puzzle XY; the single `PLEV3A/P27` record at `(0,0)` is now classified as an intentional **off-map / non-spatial** DestroyType4 effect rather than a failed target match

The Level Viewer exposes this through a **Logic inspector** tab. Clicking a layer-B event cell
selects it, highlights its map cells, and optionally draws its direct/recursive graph links over
the level image. The recursion follows the useful part of Kroah's "recursive events" behavior,
without tying the graph logic to one rendering backend. The viewer now also supports **reverse
inspection**: clicking a rendered physical logic target such as a door, backdoor, spawn point,
trapdoor, or destructible target selects that point and traces the upstream puzzle/event component
that controls it.

Known limitations:

- Flying-wave, checkpoint, and guardian targets are represented in the inspector but do not yet
  draw physical arrows, because they do not have one straightforward world-space target point in
  the current DOS model.
- The selected-logic overlay now shows many physical consequences of puzzles, and `DestroyType4`
  is no longer treated as a generic explosion/destruction box. It resolves to an actual type-4
  destructable map item or to a spawned type-4 puzzle object whenever the target is present. The
  odd `PLEV3A/P27` record at `(0,0)` is now treated as an off-map DestroyType4 effect, not as a
  missing in-map target.
- Backdoor teleports are visualized as both the opened backdoor and the decoded destination target;
  the graph semantics can still be polished into a clearer explicit multi-hop association.

## Entity browser — v8

The Level Viewer now has a left-side **Entity browser** in addition to direct map clicking. It is
not just a convenience list: it is an editor-facing navigation layer over the parsed GODS model.

The browser currently groups:

- active events
- puzzles
- switches
- teleports
- trapdoors
- moving blocks
- enemy waves
- physical logic targets from the `LogicGraph`
- map items with decoded object/weapon names

Selecting a row sets the same logical selection state as clicking in the rendered map, refreshes
the Logic inspector, rerenders the highlighted graph component, and centers the map on the selected
spatial entity where that makes sense. This mirrors the workflow goal borrowed from Gods Deluxe:
large GODS levels should be browsable as a structured set of mechanics, not only as pixels.

The browser also has a text filter, which already makes it useful for locating doors, spawned
objects, destructible targets, or specific indexed records while reverse-engineering.

## Flying path `.PAT` banks

- `PGOD01.PAT` … `PGOD04.PAT` unpack as path tables with a fixed 0x190-byte header.
- Each 8-byte header record carries a tag and path byte size; a negative tag terminates the list.
- Path payloads are either `absolute` (`0x2345`, map pixel X/Y) or `relative` (screen-relative signed X/Y).
- Relative paths become spatial only when anchored to an event cell that spawns a flying wave; the effective origin matches Kroah's `-160,-96` viewport offset around the trigger cell center.


## Enemy-wave rewards — v10

Kroah's viewer makes the `reward` field in the PALFILS wave records unambiguous, and the DOS data follows the same rule:

- ordinary flying and walking waves use an 8-bit reward field, where `0xFF` means none;
- intelligent flying/walking waves use a 16-bit reward field, where `0xFFFF` means none;
- active reward values `0..10` index the per-level weapon table;
- active reward values `11+` index the per-level object table as `reward - 11`.

The Python viewer now exposes this through `has_reward`, `reward_kind`, and `reward_info_index` properties on wave records. The Entity Browser uses those properties to show readable reward names, and the map renderer can draw a **Wave reward previews** overlay.

Reward-preview placement is currently semantic, not exact. Kroah's original viewer derives the exact Y placement using enemy sprite dimensions, while the DOS Python viewer has not yet lifted the PC enemy-info table from the executable. Therefore:

- walking/intelligent-wave rewards are previewed above the decoded spawn anchor;
- flying-wave rewards are previewed above the resolved first point of the `.PAT` path for each triggering event cell.

This is still useful for RE and level understanding, while leaving a clearly marked path to pixel-perfect enemy/reward composition later.

## Flying path browser — v10

Flying paths now appear as their own group in the Entity Browser. Selecting path `P#`:

- filters the rendered `.PAT` overlay to that path,
- lists the flying-wave definitions that refer to it,
- lists the map event cells that instantiate those wave/path combinations,
- keeps relative-vs-absolute semantics explicit in the inspector.

## v11: enemy entity rendering

- Enemy waves now resolve `enemy_info_index` through Kroah's decoded enemy-info tables.
- The helper tables are extracted from `Gods Viewer - v1.02/src/Resources/04 Level 1.dmp`, then mapped onto the DOS sprite bank.
- The DOS atlases in this build line up with Kroah's sprite bases using a **+2 sprite index correction**. Example: Kroah/ST sprite `448` becomes DOS sprite `450`.
- Walking/intelligent walking enemies use the same facing logic as Kroah's viewer, including the inverted facing for mouth/turret-style enemy bases `523`, `530`, and `545`.
- Ordinary flying waves render at the first `.PAT` point resolved for each event cell; walking and intelligent waves render at their own decoded spawn coordinates.
- Reward previews now use the decoded enemy width and Kroah's placement rule: horizontally centered over the enemy and immediately above it.
- This is a practical viewer/editor bridge, but it is **not yet independently re-derived from the packed DOS `GAME.EXE` enemy tables**. The physical rendering is consistent with the PC atlases and Kroah's decoded model; the remaining purity task is to recover the same table directly from unpacked DOS code/data.


## v12: unified selection and enemy-wave inspection

The Level Viewer now treats rendered enemy sprites as first-class selectable entities. A click on a walking, intelligent, or trigger-instantiated flying enemy resolves back to its wave record and opens an enemy-focused inspector. The inspector reports enemy-info metadata, count/health/reward fields, ordinary-flying `.PAT` path details, and all events/cells that trigger the wave. The Entity Browser uses the same selection path, making list-based navigation and direct map clicks equivalent. A lightweight hover readout previews enemy and logic-target selections before clicking.

## Gameplay-logic closure pass — v13

This pass moves the viewer closer to a complete **GODS logic model**, not just a trigger renderer.
The `LogicGraph` now represents all of the important relation families that were previously only
visible as raw puzzle fields:

- `Carrying` / `NotCarrying` conditions:
  - initial map objects
  - objects spawned by another puzzle
  - objects rewarded by walking / intelligent waves
  - non-spatial flying-wave rewards retained as logical nodes
- `Holding` / `NotHolding` conditions:
  - initial map weapons
  - puzzle-spawned weapons
  - wave rewards
- state conditions:
  - health thresholds
  - elapsed-time thresholds (`param × 5 seconds`)
  - score thresholds (`param × 5000`)
  - life-count thresholds
- non-spatial puzzle effects:
  - `RemoveWeapon`
  - `EnableRaster`
  - `DisableRaster`
  - `ResetGlobalTimer`

### Switch records are fully nailed down

Across all eight DOS maps, every populated PALFILS switch record has exactly one physical map item
at the same `(x,y)` and with the same object-info index:

```text
300 / 300 switch records matched exactly
```

The graph now encodes this explicitly as:

```text
physical switch item → switch-state record → puzzle conditions
```

That means a future editor can treat a visible lever/switch as the canonical user-facing entity,
while still preserving the PALFILS switch-slot identity underneath.

### Moving blocks: the suspicious raw action bytes are harmless

The moving-block records contain many odd bytes in their four action slots when inspected naively.
A full event-reference cross-check resolves the ambiguity:

- every **actually referenced** moving-block action slot decodes cleanly,
- no triggered slot uses an opaque/unknown action byte,
- all strange values occur only in **unreferenced slots**.

Referenced action semantics in the original DOS data:

```text
move_to_target_then_stop  148
Disable                    28
cycle_forward               7
```

The parser now exposes `action_kind()` and `action_description()` so event → moving-block links are
human-readable in the Logic Inspector.

### Teleport stones vs. PALFILS teleport records

Usable object effect index `17` is the **Teleport stone**. The older viewer links teleport stones to
PALFILS teleport records by **source X coordinate**, and the Python graph now models that exact rule:

```text
teleport-stone object/spawn → teleport destination record
```

A static cross-check finds direct fixed teleport-stone source matches for `12 / 54` populated
teleport records across the eight map files. The remaining populated records are intentionally kept
visible but **not speculatively linked**: the current evidence does not justify pretending they have
an in-map fixed source in the same map file. This may include dead/orphan table rows, reused logic,
or runtime patterns that need future confirmation.

### Puzzle remove flag

The high bit of the puzzle effect word is preserved as `remove_after_effect`. The original viewer's
`IsCandidateForRemove` logic suggests two editor-relevant cases:

- key-like carried items are consumed by door/backdoor/trapdoor-opening effects,
- when the remove flag is set, carried usable/pickable reward objects can be consumed.

The flag is now documented in the model and kept separate from the lower 15-bit effect index.

### Analyzer tool

`tools/analyze_logic_catalog.py` prints the complete event/condition/effect catalogue and the
cross-checks above. It is intended as a repeatable regression/RE sanity report while we refine the
editor.

## v14: remaining logic oddities closed down

### Teleport records: live bindings vs. stale table rows

The `PALFILS` teleport table is not a clean list of only live teleports. A row with
`srcPixelX != 0` is merely a *populated* row. It becomes a live stone teleport only when
some teleport-stone source in the current world resolves to that exact `srcPixelX`.

The v14 analyzer now reports:

```text
populated teleport table rows that resolve to a teleport-stone source: 12/54
populated teleport table rows with no source in this world (likely stale rows): 42
```

Those 42 rows are not a missing mechanic in the current world; they are best treated as
unbound / stale rows left in the fixed-size table. The GUI therefore labels unbound rows
as `T?` and describes them as `unbound / likely stale row` in the Entity Browser.

The stone-to-row lookup itself is still the simple original rule already visible in Kroah's
viewer: **teleport stone pixel X → teleport table `srcPixelX`**.

### Special / sequential teleport destinations

Teleport stones that do **not** resolve through a PALFILS teleport row are not undefined.
They use the game's separate hardcoded special-destination sequence. The DOS PC tables are
now extracted explicitly into `gods_tools/formats/pc_logic_tables.py`.

Verified in unpacked DOS `GAME.EXE`:

- Level 1 sequence at `0x1E606`: 8 coded destinations
- Level 2 sequence at `0x1E616`: 5 coded destinations
- plus the known additional Level 2 destination `0x202E`, kept explicit as a special patched value

The renderer and Entity Browser can now show these as **Hardcoded teleport destinations**
(`HT#`). They are intentionally rendered as destinations only: the exact runtime pairing is
sequence/order-driven rather than a direct static `srcX` association like PALFILS teleports.

For editor UX, unbound fixed teleport-stone sources are now presented as an inferred special
sequence: map-item teleport stones in item-table order, followed by puzzle-spawned teleport stones
in puzzle-table order, excluding any stone whose X coordinate already binds to a PALFILS teleport
record.  The resulting sequence is shown as `HT0`, `HT1`, ... with an explicit warning that the
destination id is not stored on the puzzle or item itself.  Example: in Level 1A/1B, I16 is the
first unbound teleport stone and resolves to `HT0`; P21 spawns OBJ54 at (814,677) and resolves to
`HT1` at (1040,624).

### Intelligent-enemy objective locations

The older viewer's white objective rectangles are also present directly in the DOS executable.
The PC tables are now extracted into `pc_logic_tables.py`:

- Level 1: 9 objective locations, table at `0x1DB00`
- Level 2: 19 objective locations, table at `0x1DB28`
- Level 3: 13 objective locations, table at `0x1DB78`
- Level 4: reuses the same table as Level 3

They are used by intelligent-walking wave objectives such as `GoToObjectiveLocation_3` and are
now available as a GUI overlay and Entity Browser group.

### Checkpoint and guardian event slots

`Checkpoint` and `LoadGuardian` are now structurally clear:

- there is one stored event record of each type per world;
- both use `param = 0` in the original data;
- many map event cells can point to the generic checkpoint event record;
- guardian trigger cells point to the generic guardian-load event record.

The event parameter is therefore not selecting a checkpoint or guardian variant. The level/world
context and the trigger cell position are the meaningful data visible in the map layer. The
remaining runtime handler behavior is an executable-code question, not an unresolved PALFILS/map
format question.

### Enemy rewards: data model closed, final runtime timing still marked

The reward field interpretation is fully closed at the data-model level:

- `0..10` = weapon reward;
- `11+` = object reward (`reward - 11`);
- `0xFF` / `0xFFFF` = no reward.

The renderer uses the original viewer's spatial centering rule for preview placement. The exact
*runtime timing* of when a wave's reward is dropped is deliberately kept as a separate behavior
question. The data and helper projects strongly support the expected `wave reward` interpretation,
but the v14 editor does not pretend it has reverse-traced the original DOS handler down to the
last branch.

## v15: concrete map-item inspector

The Level Viewer now treats initial map items as first-class selectable editor entities, not merely as
sprites painted over the tilemap. Selection is now unified for:

- direct clicks on the rendered map item sprite,
- Map-item rows in the Entity Browser.

The Object Inspector decodes:

- raw map-item slot/index and packed object-or-weapon info ID,
- object/weapon metadata from `POBJECTS.*` / `PWEAPONS.*`,
- rendered sprite box size,
- object type/value/effect semantics or weapon power/removal metadata,
- exact switch-item ↔ PALFILS switch-state binding,
- teleport stone ↔ teleport table destination binding where statically resolvable.

`LogicGraph` now groups all graph nodes that refer to the same concrete initial map-item slot. This is
important because one visible item may participate in several editor-facing roles at once:

- `switch_item`,
- `teleport_stone`,
- `map_object_source` / `map_weapon_source` for inventory predicates,
- `destructable_object` for `DestroyType4` targets.

The inspector surfaces direct links plus the recursively connected component, so a click on a switch,
teleport stone, spike, treasure, or weapon can immediately explain how that visible object participates
in the larger GODS level mechanism.

## v16: mechanism narration over the decoded graph

The editor now keeps two complementary presentations of the same level logic:

- **Logic Inspector** — low-level graph edges, raw relationship detail, precise graph traversal.
- **Mechanism View** — a designer-facing explanation of the selected connected component.

Mechanism View is intentionally *derived* from `LogicGraph`; it is not a second, hand-maintained
interpretation layer. This keeps the readable story and the on-map links synchronized.

For a selected event, map item, physical logic target, enemy wave, or flying path, the tab reports:

- which map-triggered events enter the component,
- which events directly spawn waves / activate blocks / evaluate puzzles,
- which puzzle conditions gate the behavior,
- what the puzzle changes when satisfied,
- which physical switch or teleport bindings are part of the same mechanism.

This is the first read-only step toward the eventual Gods-Deluxe-style association workflow. Before
editing links, the tool can now explain them as compact level-design mechanisms rather than forcing
the user to manually read every graph edge.

## v17: completion pass before cleanup

The viewer/editor now closes the remaining practical presentation gaps identified in the Kroah-viewer audit:

- **Chest-key links:** object-info indices `18..23` are chest keys, `12..17` are chests, and the original key/chest mapping formula is modeled as graph bindings. The graph includes sources from initial map items, puzzle spawns, and wave rewards.
- **Reveal Clues hints:** usable object effect `18` links to the hint record whose X coordinate matches the clue object's X coordinate, mirroring the older viewer's `GetHintAt(pixelX)` behavior.
- **Player start:** a start marker and browser entry are exposed. The start positions match the identical ST/Amiga viewer dump values used by Kroah's viewer; they are kept as explicit editor tables for navigation.
- **Hidden spawned items:** `SpawnObject` and `SpawnWeapon` puzzle effects can be shown as ghost sprites without selecting a mechanism first.
- **Moving-block action preview:** a selected moving-block event or moving-block point now draws the decoded route for the referenced action slot, rather than only showing all target coordinates schematically.
- **Diagnostics:** the editor exposes a dedicated diagnostics tab for non-fatal cleanup findings such as stored events without a decoded entry point, active puzzles without a decoded CheckPuzzle inbound link, unbound teleport rows, and unused moving-block action slots.

## v18 editor architecture cleanup

The data model has been split into three explicit layers:

1. **Decoded source truth** — immutable `LevelDocument`.
2. **Normalized editor navigation** — `EntityIndex` over decoded entities.
3. **Future mutation boundary** — `EditSession` and `WriteBackPlan`.

The Level Viewer remains fully read-only from the user's perspective, but can now prepare auditable
raw byte patches against the unpacked map payload. This is the correct staging point before adding
real recompression/save-back.
