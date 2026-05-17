# Decision log

## 2026-05-16 — Initial DOS GODS project shape

- Keep the same editor-project architecture as the earlier DOS reverse-engineering tools.
- Start with a standalone **Graphics Viewer** tab.
- Reserve a separate **Level Viewer** tab rather than mixing level and graphics work.
- Keep `formats/` parser-only, `render/` image-only, and `gui/` presentation-only.
- Bundle the provided DOS GODS data under `game_data/Gods/`.
- Treat the packed `P*` resources as first-class original inputs, not pre-extracted fixtures.

## 2026-05-16 — Compression and graphics strategy

- Use PKWARE DCL Implode decompression for packed GODS resources.
- Decode `.PI1` directly as 320×200 4-plane palette images.
- Parse paired `.DAT` files as atlas rectangle tables to make graphics inspection immediately useful.

## 2026-05-16 — First Level Viewer

- Port the `PLEV*.MAP` structure into a standalone Python parser.
- Render full layer-A maps from the original packed DOS files.
- Expose layer-B values as optional overlays instead of prematurely interpreting every value.
- Add click-to-inspect tile coordinates and raw A/B cell values, because this will be useful for later RE work and editor tooling.
- Show map items and puzzle records in the parsed-details panel, but keep their richer semantic interpretation for a later pass.

## 2026-05-16 — Shared DOS XTRA bank per level

- The DOS maps require extra tile ids above the 120 tiles present in `PBITS*.PI1`.
- The archive has only one `PXTRA*` tile bank per level, not one per A/B half.
- Use exact `PXTRA{level}{world}` when present, otherwise fall back to the single `PXTRA{level}*.PI1` available for that level.
- This matches all eight packed DOS maps without missing layer-A tile ids.

## 2026-05-16 — PALFILS logic overlays

- Port the fixed PALFILS section layout from Kroah's viewer into a standalone Python parser.
- Treat DOS `PALFILS.0YX` as structurally compatible after all eight files unpack to the expected 8,760-byte layout.
- Decode layer-B event cells as `value - 3` PALFILS event indices and show acronyms in the map overlay.
- Add separate overlay toggles for enemy-wave origins, switches, teleport targets, trapdoors, moving blocks, and hints.
- Keep moving-block rendering deliberately schematic for now: rectangles, target points, and lines, not full sprite/action simulation.

- **v4:** Added an editor-facing `LogicGraph` layer instead of baking all PALFILS relationships
  straight into the renderer. This follows the useful principle seen in Gods Deluxe and Kroah's
  recursive event view: the editor should understand GODS as a network of triggers, puzzles, and
  effects, not just as independent overlay markers.


## 2026-05-16 — Physical puzzle-effect targets

- Extend the editor-facing `LogicGraph` from abstract trigger chains to concrete spatial consequences.
- Reuse geometry conventions verified in Kroah's viewer for doors, backdoors, backdoor teleport destinations, and destruction areas.
- Keep the raw puzzle record untouched while exposing editor-centric target points for:
  - spawned objects / weapons
  - open / close doors
  - backdoor teleports and world-complete exits
  - type-4 destruction areas
  - trapdoors
- Draw these target markers automatically when selected-event logic links are shown, even if the corresponding broad overlay category is hidden.
- The next UX improvement should be reverse selection: click the physical target and inspect what triggers it.

## 2026-05-16 — Mechanism View, not a second logic model

- Add a separate **Mechanism view** tab that translates decoded graph components into human-readable
  trigger / condition / consequence stories.
- Do **not** build a parallel bespoke mechanism model yet; derive the narrative directly from
  `LogicGraph` edges so the story remains faithful to the same source as map arrows and inspectors.
- Support every already-unified selection entry point: event, map item, logic target, enemy wave,
  and flying path.
- Truncate very large recursive components in the prose view while leaving the full technical detail
  available in the Logic Inspector.

## 2026-05-16 — Completion pass before cleanup

- Model GODS' chest-key relationship explicitly in `LogicGraph`; do not treat it as a puzzle-condition proxy.
- Model `RevealClues` as a source-to-hint binding by exact X match, matching the historical viewer.
- Add player starts as explicit editor navigation markers, keeping their provenance clear.
- Prefer ghost overlays for puzzle-spawned objects/weapons over forcing the user to select every puzzle target manually.
- Add selected moving-block action-route preview without attempting full runtime simulation.
- Add diagnostics as an informational cleanup tool. Do not escalate stale/unbound rows to hard parser errors unless the decoded data is actually inconsistent.

## 2026-05-17 — Write-back must start as an auditable patch plan

We intentionally avoided jumping directly from read-only reverse-engineering to "save modified GODS
files". The first edit-mode implementation is a byte-accurate `WriteBackPlan` against unpacked
payloads. It validates overlap and before-bytes, can preview patched map payloads, and leaves PKWARE
recompression/file replacement for the next milestone. This keeps future editing debuggable and
prevents opaque corruption.
