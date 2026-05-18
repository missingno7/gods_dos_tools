from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox

from gods_tools.formats.compression import GodsCompressionError
from gods_tools.formats.alfils import AlfilsData, AlfilsFormatError, load_packed_alfils
from gods_tools.formats.flying_paths import FlyingPathsData, FlyingPathsFormatError, load_packed_flying_paths
from gods_tools.formats.enemy_info import EnemyInfo, get_enemy_info
from gods_tools.formats.logic import LogicGraph, LogicPoint, build_logic_graph, condition_type_name, puzzle_effect_name
from gods_tools.formats.mechanisms import (
    describe_component,
    describe_event_mechanism,
    describe_map_item_mechanism,
    describe_point_mechanism,
    merge_edges,
)
from gods_tools.formats.pc_logic_tables import objective_locations, special_teleport_destinations, player_start_location
from gods_tools.formats.levels import LevelResource, discover_level_resources
from gods_tools.formats.item_tables import (
    ItemTableFormatError,
    ObjectTable,
    WeaponTable,
    level_object_table_path,
    level_weapon_table_path,
    load_packed_object_table,
    load_packed_weapon_table,
)
from gods_tools.render.sprites import SpriteBank, load_level_sprite_bank
from gods_tools.formats.map import GodsMap, MapFormatError, MAP_CELL_HEIGHT, MAP_CELL_WIDTH, load_packed_map
from gods_tools.formats.diagnostics import LevelDiagnostics, build_level_diagnostics
from gods_tools.render.levels import LevelRenderOptions, LevelRenderResult, render_level_map
from gods_tools.model.document import LevelDocument
from gods_tools.model.entities import EntityIndex, IndexedEntity, build_entity_index
from gods_tools.edit.session import EditSession
from .image_canvas import ImageCanvas


@dataclass(frozen=True)
class EnemySelection:
    category: str  # FW / WW / IW / IF
    wave_index: int
    event_index: int | None = None
    anchor_x: int | None = None
    anchor_y: int | None = None


@dataclass(frozen=True)
class MapItemSelection:
    item_index: int


@dataclass
class LoadedLevel:
    """GUI-side render state around the immutable LevelDocument.

    The editor used to keep decoded files and presentation state in one mutable bag.
    v18 introduces a stable document/index/edit-session boundary while this small wrapper
    keeps the rest of the UI source-compatible.
    """

    document: LevelDocument
    entity_index: EntityIndex
    edit_session: EditSession
    render_result: LevelRenderResult

    @property
    def resource(self) -> LevelResource:
        return self.document.resource

    @property
    def map_data(self) -> GodsMap:
        return self.document.map_data

    @property
    def alfils_data(self) -> AlfilsData | None:
        return self.document.alfils_data

    @property
    def object_table(self) -> ObjectTable | None:
        return self.document.object_table

    @property
    def weapon_table(self) -> WeaponTable | None:
        return self.document.weapon_table

    @property
    def sprite_bank(self) -> SpriteBank | None:
        return self.document.sprite_bank

    @property
    def flying_paths(self) -> FlyingPathsData | None:
        return self.document.flying_paths

    @property
    def logic_graph(self) -> LogicGraph | None:
        return self.document.logic_graph

    @property
    def diagnostics(self) -> LevelDiagnostics | None:
        return self.document.diagnostics


class LevelViewer(ttk.Frame):
    def __init__(self, master: tk.Misc, game_dir: Path) -> None:
        super().__init__(master)
        self.game_dir = Path(game_dir)
        self.resources: list[LevelResource] = []
        self.loaded: LoadedLevel | None = None

        self.search_var = tk.StringVar()
        self.level_choice_var = tk.StringVar()
        self.entity_search_var = tk.StringVar()
        self.info_var = tk.StringVar(value="Select a level map.")
        self.inspect_var = tk.StringVar(value="Click the rendered map to inspect tile coordinates and layer values.")
        self.hover_var = tk.StringVar(value="Hover an entity in the map to preview what would be selected.")
        self.entity_refs: dict[str, tuple[str, object]] = {}
        self.context_refs: dict[str, tuple[str, object]] = {}
        self.entity_rows_by_ref: dict[tuple[str, object], tuple[str, str, str, str]] = {}
        self.entity_trees: dict[str, ttk.Treeview] = {}
        self.entity_group_frames: dict[str, ttk.Frame] = {}
        self.entity_group_buttons: dict[str, ttk.Button] = {}
        self.selected_entity_group: str | None = None
        self.puzzle_refs: dict[str, tuple[str, object]] = {}
        self._auto_enabled_flying_paths = False

        self.show_raster_var = tk.BooleanVar(value=False)
        self.show_collision_var = tk.BooleanVar(value=False)
        self.show_events_var = tk.BooleanVar(value=False)
        self.show_item_sprites_var = tk.BooleanVar(value=True)
        self.show_items_var = tk.BooleanVar(value=False)
        self.show_puzzles_var = tk.BooleanVar(value=False)
        self.show_enemy_waves_var = tk.BooleanVar(value=False)
        self.show_enemy_sprites_var = tk.BooleanVar(value=False)
        self.show_flying_paths_var = tk.BooleanVar(value=False)
        self.show_wave_rewards_var = tk.BooleanVar(value=False)
        self.show_hidden_spawned_var = tk.BooleanVar(value=False)
        self.show_switches_var = tk.BooleanVar(value=False)
        self.show_teleports_var = tk.BooleanVar(value=False)
        self.show_special_teleports_var = tk.BooleanVar(value=False)
        self.show_objective_locations_var = tk.BooleanVar(value=False)
        self.show_player_start_var = tk.BooleanVar(value=False)
        self.show_trapdoors_var = tk.BooleanVar(value=False)
        self.show_moving_blocks_var = tk.BooleanVar(value=False)
        self.show_moving_block_preview_var = tk.BooleanVar(value=True)
        self.show_hints_var = tk.BooleanVar(value=False)
        self.show_logic_links_var = tk.BooleanVar(value=True)
        self.logic_link_scope_var = tk.StringVar(value="selected")
        self.recursive_logic_links_var = tk.BooleanVar(value=True)
        self.show_grid_var = tk.BooleanVar(value=False)
        self.selected_event_index: int | None = None
        self.selected_flying_path_index: int | None = None
        self.selected_logic_point: LogicPoint | None = None
        self.selected_enemy_wave: EnemySelection | None = None
        self.selected_map_item: MapItemSelection | None = None

        self._build_ui()
        self.reload_resources()

    def _build_ui(self) -> None:
        top_bar = ttk.Frame(self, padding=(8, 8, 8, 2))
        top_bar.pack(fill=tk.X)
        ttk.Label(top_bar, text="Level").pack(side=tk.LEFT, padx=(0, 6))
        self.level_combo = ttk.Combobox(
            top_bar,
            textvariable=self.level_choice_var,
            state="readonly",
            width=34,
        )
        self.level_combo.pack(side=tk.LEFT, padx=(0, 12))
        self.level_combo.bind("<<ComboboxSelected>>", self._on_level_combo_selected)
        ttk.Label(top_bar, text="Double-click entity in map → reveal in Entity Browser", foreground="#666666").pack(side=tk.LEFT)

        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, padding=8)
        right = ttk.Frame(outer, padding=8)
        outer.add(left, weight=1)
        outer.add(right, weight=4)

        self.left_tabs = ttk.Notebook(left)
        self.left_tabs.pack(fill=tk.BOTH, expand=True)

        browse_tab = ttk.Frame(self.left_tabs, padding=8)
        context_tab = ttk.Frame(self.left_tabs, padding=8)
        puzzle_tab = ttk.Frame(self.left_tabs, padding=8)
        overlays_tab = ttk.Frame(self.left_tabs, padding=8)
        status_tab = ttk.Frame(self.left_tabs, padding=8)
        self.left_tabs.add(browse_tab, text="Browse")
        self.left_tabs.add(context_tab, text="Context")
        self.left_tabs.add(overlays_tab, text="Overlays")
        self.left_tabs.add(status_tab, text="Status")

        ttk.Label(browse_tab, text="Entity browser", font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))

        browse_pane = ttk.PanedWindow(browse_tab, orient=tk.VERTICAL)
        browse_pane.pack(fill=tk.BOTH, expand=True, pady=(0, 4))

        entity_frame = ttk.Frame(browse_pane)
        browse_pane.add(entity_frame, weight=3)
        self.entity_group_bar = ttk.Frame(entity_frame)
        self.entity_group_bar.pack(fill=tk.X, pady=(0, 4))
        self.entity_group_bar.bind("<Configure>", lambda _event: self._layout_entity_group_buttons())
        self.entity_group_stack = ttk.Frame(entity_frame)
        self.entity_group_stack.pack(fill=tk.BOTH, expand=True)
        self.entity_related_font = tkfont.Font(font="TkDefaultFont")
        self.entity_related_font.configure(weight="bold")

        property_frame = ttk.LabelFrame(browse_pane, text="Properties", padding=4)
        browse_pane.add(property_frame, weight=1)
        self.property_tree = ttk.Treeview(
            property_frame,
            columns=("value",),
            show="tree headings",
            height=7,
            selectmode="browse",
        )
        self.property_tree.heading("#0", text="Field")
        self.property_tree.heading("value", text="Value")
        self.property_tree.column("#0", width=130, stretch=False)
        self.property_tree.column("value", width=220, stretch=True)
        prop_scroll = ttk.Scrollbar(property_frame, orient=tk.VERTICAL, command=self.property_tree.yview)
        self.property_tree.configure(yscrollcommand=prop_scroll.set)
        self.property_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prop_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(context_tab, text="Selection context", font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        context_pane = ttk.PanedWindow(context_tab, orient=tk.VERTICAL)
        context_pane.pack(fill=tk.BOTH, expand=True)

        context_frame = ttk.Frame(context_pane)
        context_pane.add(context_frame, weight=3)
        self.context_tree = ttk.Treeview(
            context_frame,
            columns=("group", "detail", "pos"),
            show="tree headings",
            height=16,
            selectmode="browse",
        )
        self.context_tree.heading("#0", text="Entity")
        self.context_tree.heading("group", text="Group")
        self.context_tree.heading("detail", text="Meaning")
        self.context_tree.heading("pos", text="Pos")
        self.context_tree.column("#0", width=76, stretch=False)
        self.context_tree.column("group", width=92, stretch=False)
        self.context_tree.column("detail", width=190, stretch=True)
        self.context_tree.column("pos", width=66, stretch=False)
        context_scroll = ttk.Scrollbar(context_frame, orient=tk.VERTICAL, command=self.context_tree.yview)
        self.context_tree.configure(yscrollcommand=context_scroll.set)
        self.context_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        context_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.context_tree.bind("<<TreeviewSelect>>", self._on_context_selected)
        self.context_tree.bind("<Double-Button-1>", self._on_context_activated)

        context_prop_frame = ttk.LabelFrame(context_pane, text="Properties", padding=4)
        context_pane.add(context_prop_frame, weight=1)
        self.context_property_tree = ttk.Treeview(
            context_prop_frame,
            columns=("value",),
            show="tree headings",
            height=7,
            selectmode="browse",
        )
        self.context_property_tree.heading("#0", text="Field")
        self.context_property_tree.heading("value", text="Value")
        self.context_property_tree.column("#0", width=130, stretch=False)
        self.context_property_tree.column("value", width=220, stretch=True)
        context_prop_scroll = ttk.Scrollbar(context_prop_frame, orient=tk.VERTICAL, command=self.context_property_tree.yview)
        self.context_property_tree.configure(yscrollcommand=context_prop_scroll.set)
        self.context_property_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        context_prop_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(puzzle_tab, text="Puzzle objects", font=("", 11, "bold")).pack(anchor="w", pady=(0, 4))
        puzzle_frame = ttk.Frame(puzzle_tab)
        puzzle_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 4))
        self.puzzle_tree = ttk.Treeview(
            puzzle_frame,
            columns=("roles", "links", "pos"),
            show="tree headings",
            height=12,
            selectmode="browse",
        )
        self.puzzle_tree.heading("#0", text="Object")
        self.puzzle_tree.heading("roles", text="Meaning")
        self.puzzle_tree.heading("links", text="Puzzle links")
        self.puzzle_tree.heading("pos", text="Pos")
        self.puzzle_tree.column("#0", width=75, stretch=False)
        self.puzzle_tree.column("roles", width=230, stretch=True)
        self.puzzle_tree.column("links", width=120, stretch=True)
        self.puzzle_tree.column("pos", width=66, stretch=False)
        puzzle_scroll = ttk.Scrollbar(puzzle_frame, orient=tk.VERTICAL, command=self.puzzle_tree.yview)
        self.puzzle_tree.configure(yscrollcommand=puzzle_scroll.set)
        self.puzzle_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        puzzle_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.puzzle_tree.bind("<<TreeviewSelect>>", self._on_puzzle_entity_selected)

        puzzle_text_frame = ttk.Frame(puzzle_tab)
        puzzle_text_frame.pack(fill=tk.BOTH, expand=False)
        self.puzzle_text = tk.Text(
            puzzle_text_frame,
            wrap="word",
            height=9,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        puzzle_text_scroll = ttk.Scrollbar(puzzle_text_frame, orient=tk.VERTICAL, command=self.puzzle_text.yview)
        self.puzzle_text.configure(yscrollcommand=puzzle_text_scroll.set)
        self.puzzle_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        puzzle_text_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        ttk.Label(overlays_tab, text="Render overlays", font=("", 11, "bold")).pack(anchor="w")

        preset_card = ttk.LabelFrame(overlays_tab, text="Overlay presets", padding=8)
        preset_card.pack(fill=tk.X, pady=(6, 6))
        preset_row1 = ttk.Frame(preset_card)
        preset_row1.pack(fill=tk.X, pady=(0, 3))
        for label, preset in (("Clean", "clean"), ("Objects", "objects"), ("Puzzle", "puzzle")):
            ttk.Button(
                preset_row1,
                text=label,
                command=lambda name=preset: self._apply_overlay_preset(name),
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        preset_row2 = ttk.Frame(preset_card)
        preset_row2.pack(fill=tk.X)
        for label, preset in (("Enemy", "enemy"), ("Full RE", "full")):
            ttk.Button(
                preset_row2,
                text=label,
                command=lambda name=preset: self._apply_overlay_preset(name),
            ).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))

        display_card = ttk.LabelFrame(overlays_tab, text="Base display", padding=8)
        display_card.pack(fill=tk.X, pady=(6, 6))
        for label, variable in (("Raster background", self.show_raster_var), ("Collision B: walls / stairs", self.show_collision_var), ("Tile grid", self.show_grid_var)):
            ttk.Checkbutton(display_card, text=label, variable=variable, command=self._rerender_loaded).pack(anchor="w")

        items_card = ttk.LabelFrame(overlays_tab, text="Map items", padding=8)
        items_card.pack(fill=tk.X, pady=(0, 6))
        for label, variable in (("Map item sprites", self.show_item_sprites_var), ("Map item markers", self.show_items_var), ("Hidden spawned object/weapon previews", self.show_hidden_spawned_var), ("Puzzle markers", self.show_puzzles_var)):
            ttk.Checkbutton(items_card, text=label, variable=variable, command=self._rerender_loaded).pack(anchor="w")

        enemy_card = ttk.LabelFrame(overlays_tab, text="Enemies and paths", padding=8)
        enemy_card.pack(fill=tk.X, pady=(0, 6))
        for label, variable in (("Enemy wave spawn markers", self.show_enemy_waves_var), ("Enemy sprites", self.show_enemy_sprites_var), ("Flying wave .PAT paths", self.show_flying_paths_var), ("Wave reward previews", self.show_wave_rewards_var), ("Intelligent-enemy objective locations", self.show_objective_locations_var)):
            ttk.Checkbutton(enemy_card, text=label, variable=variable, command=self._rerender_loaded).pack(anchor="w")

        mechanism_card = ttk.LabelFrame(overlays_tab, text="Mechanisms and navigation", padding=8)
        mechanism_card.pack(fill=tk.X, pady=(0, 6))
        for label, variable in (("Event cells from layer B", self.show_events_var), ("Switch markers", self.show_switches_var), ("Teleport table targets", self.show_teleports_var), ("Hardcoded teleport destinations", self.show_special_teleports_var), ("Player start", self.show_player_start_var), ("Trapdoors", self.show_trapdoors_var), ("Moving blocks + target points", self.show_moving_blocks_var), ("Selected moving-block action preview", self.show_moving_block_preview_var), ("Hint X-lines", self.show_hints_var)):
            ttk.Checkbutton(mechanism_card, text=label, variable=variable, command=self._rerender_loaded).pack(anchor="w")

        logic_card = ttk.LabelFrame(overlays_tab, text="Logic focus", padding=8)
        logic_card.pack(fill=tk.X, pady=(0, 6))
        ttk.Checkbutton(logic_card, text="Selected event logic links", variable=self.show_logic_links_var, command=self._rerender_loaded).pack(anchor="w")
        ttk.Checkbutton(logic_card, text="Recursive event chains", variable=self.recursive_logic_links_var, command=self._rerender_loaded).pack(anchor="w")
        ttk.Label(logic_card, text="Logic scope").pack(anchor="w", pady=(6, 2))
        scope_row = ttk.Frame(logic_card)
        scope_row.pack(fill=tk.X)
        for label, value in (("Selected", "selected"), ("One hop", "one_hop"), ("Full", "full")):
            ttk.Radiobutton(scope_row, text=label, value=value, variable=self.logic_link_scope_var, command=self._rerender_loaded).pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(status_tab, textvariable=self.info_var, wraplength=340, justify=tk.LEFT).pack(fill=tk.X, anchor="nw")
        ttk.Label(status_tab, textvariable=self.inspect_var, wraplength=340, justify=tk.LEFT).pack(fill=tk.X, anchor="nw", pady=(12, 0))
        ttk.Label(status_tab, textvariable=self.hover_var, wraplength=340, justify=tk.LEFT, foreground="#666666").pack(fill=tk.X, anchor="nw", pady=(8, 0))

        self.preview_tabs = ttk.Notebook(right)
        self.preview_tabs.pack(fill=tk.BOTH, expand=True)

        render_tab = ttk.Frame(self.preview_tabs)
        logic_tab = ttk.Frame(self.preview_tabs)
        mechanism_tab = ttk.Frame(self.preview_tabs)
        diagnostics_tab = ttk.Frame(self.preview_tabs)
        edit_prep_tab = ttk.Frame(self.preview_tabs)
        raw_tab = ttk.Frame(self.preview_tabs)
        self.preview_tabs.add(render_tab, text="Rendered map")
        self.preview_tabs.add(logic_tab, text="Logic inspector")
        self.preview_tabs.add(mechanism_tab, text="Mechanism view")
        self.preview_tabs.add(diagnostics_tab, text="Diagnostics")
        self.preview_tabs.add(edit_prep_tab, text="Edit prep")
        self.preview_tabs.add(raw_tab, text="Parsed details")

        self.map_canvas = ImageCanvas(render_tab, initial_zoom=1)
        self.map_canvas.pack(fill=tk.BOTH, expand=True)
        self.map_canvas.set_click_callback(self._on_map_clicked)
        self.map_canvas.set_double_click_callback(self._on_map_double_clicked)
        self.map_canvas.set_hover_callback(self._on_map_hover)

        self.logic_text = tk.Text(
            logic_tab,
            wrap="word",
            height=20,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        logic_y = ttk.Scrollbar(logic_tab, orient=tk.VERTICAL, command=self.logic_text.yview)
        self.logic_text.configure(yscrollcommand=logic_y.set)
        self.logic_text.grid(row=0, column=0, sticky="nsew")
        logic_y.grid(row=0, column=1, sticky="ns")
        logic_tab.rowconfigure(0, weight=1)
        logic_tab.columnconfigure(0, weight=1)

        self.mechanism_text = tk.Text(
            mechanism_tab,
            wrap="word",
            height=20,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        mechanism_y = ttk.Scrollbar(mechanism_tab, orient=tk.VERTICAL, command=self.mechanism_text.yview)
        self.mechanism_text.configure(yscrollcommand=mechanism_y.set)
        self.mechanism_text.grid(row=0, column=0, sticky="nsew")
        mechanism_y.grid(row=0, column=1, sticky="ns")
        mechanism_tab.rowconfigure(0, weight=1)
        mechanism_tab.columnconfigure(0, weight=1)

        self.diagnostics_text = tk.Text(
            diagnostics_tab,
            wrap="word",
            height=20,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        diagnostics_y = ttk.Scrollbar(diagnostics_tab, orient=tk.VERTICAL, command=self.diagnostics_text.yview)
        self.diagnostics_text.configure(yscrollcommand=diagnostics_y.set)
        self.diagnostics_text.grid(row=0, column=0, sticky="nsew")
        diagnostics_y.grid(row=0, column=1, sticky="ns")
        diagnostics_tab.rowconfigure(0, weight=1)
        diagnostics_tab.columnconfigure(0, weight=1)

        self.edit_prep_text = tk.Text(
            edit_prep_tab,
            wrap="word",
            height=20,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        edit_prep_y = ttk.Scrollbar(edit_prep_tab, orient=tk.VERTICAL, command=self.edit_prep_text.yview)
        self.edit_prep_text.configure(yscrollcommand=edit_prep_y.set)
        self.edit_prep_text.grid(row=0, column=0, sticky="nsew")
        edit_prep_y.grid(row=0, column=1, sticky="ns")
        edit_prep_tab.rowconfigure(0, weight=1)
        edit_prep_tab.columnconfigure(0, weight=1)

        self.raw_text = tk.Text(
            raw_tab,
            wrap="none",
            height=20,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        raw_y = ttk.Scrollbar(raw_tab, orient=tk.VERTICAL, command=self.raw_text.yview)
        raw_x = ttk.Scrollbar(raw_tab, orient=tk.HORIZONTAL, command=self.raw_text.xview)
        self.raw_text.configure(yscrollcommand=raw_y.set, xscrollcommand=raw_x.set)
        self.raw_text.grid(row=0, column=0, sticky="nsew")
        raw_y.grid(row=0, column=1, sticky="ns")
        raw_x.grid(row=1, column=0, sticky="ew")
        raw_tab.rowconfigure(0, weight=1)
        raw_tab.columnconfigure(0, weight=1)

    def _apply_overlay_preset(self, preset: str) -> None:
        values = {
            "raster": False,
            "collision": False,
            "events": False,
            "item_sprites": True,
            "items": False,
            "puzzles": False,
            "enemy": False,
            "enemy_sprites": False,
            "flying_paths": False,
            "wave_rewards": False,
            "hidden_spawned": False,
            "switches": False,
            "teleports": False,
            "hardcoded_teleports": False,
            "objective_locations": False,
            "player_start": False,
            "trapdoors": False,
            "blocks": False,
            "block_preview": True,
            "hints": False,
            "links": False,
            "recursive": True,
            "grid": False,
        }
        if preset == "objects":
            values.update(items=True, hidden_spawned=True, switches=True, teleports=True, hardcoded_teleports=True, player_start=True, trapdoors=True, blocks=True)
        elif preset == "puzzle":
            values.update(events=True, puzzles=True, hidden_spawned=True, switches=True, teleports=True, hardcoded_teleports=True, objective_locations=True, player_start=True, trapdoors=True, blocks=True, links=True)
        elif preset == "enemy":
            values.update(events=True, enemy=True, enemy_sprites=True, flying_paths=True, wave_rewards=True, links=True)
        elif preset == "full":
            values.update(
                collision=True,
                events=True,
                items=True,
                puzzles=True,
                enemy=True,
                enemy_sprites=True,
                flying_paths=True,
                wave_rewards=True,
                hidden_spawned=True,
                switches=True,
                teleports=True,
                hardcoded_teleports=True,
                objective_locations=True,
                player_start=True,
                trapdoors=True,
                blocks=True,
                hints=True,
                links=True,
                grid=True,
            )

        self.show_raster_var.set(values["raster"])
        self.show_collision_var.set(values["collision"])
        self.show_events_var.set(values["events"])
        self.show_item_sprites_var.set(values["item_sprites"])
        self.show_items_var.set(values["items"])
        self.show_puzzles_var.set(values["puzzles"])
        self.show_enemy_waves_var.set(values["enemy"])
        self.show_enemy_sprites_var.set(values["enemy_sprites"])
        self.show_flying_paths_var.set(values["flying_paths"])
        self.show_wave_rewards_var.set(values["wave_rewards"])
        self.show_hidden_spawned_var.set(values["hidden_spawned"])
        self.show_switches_var.set(values["switches"])
        self.show_teleports_var.set(values["teleports"])
        self.show_special_teleports_var.set(values["hardcoded_teleports"])
        self.show_objective_locations_var.set(values["objective_locations"])
        self.show_player_start_var.set(values["player_start"])
        self.show_trapdoors_var.set(values["trapdoors"])
        self.show_moving_blocks_var.set(values["blocks"])
        self.show_moving_block_preview_var.set(values["block_preview"])
        self.show_hints_var.set(values["hints"])
        self.show_logic_links_var.set(values["links"])
        self.recursive_logic_links_var.set(values["recursive"])
        self.show_grid_var.set(values["grid"])
        self._rerender_loaded()

    def reload_resources(self) -> None:
        self.resources = discover_level_resources(self.game_dir)
        displays = [resource.display_name for resource in self.resources]
        self.level_combo.configure(values=displays)
        if self.resources:
            self.level_choice_var.set(displays[0])
            self._load_resource(self.resources[0])
        else:
            self.level_choice_var.set("")

    def _on_level_combo_selected(self, _event: tk.Event) -> None:
        selected = self.level_choice_var.get()
        for resource in self.resources:
            if resource.display_name == selected:
                self._load_resource(resource)
                return

    def _build_render_options(self) -> LevelRenderOptions:
        return LevelRenderOptions(
            show_raster_background=self.show_raster_var.get(),
            show_collision_overlay=self.show_collision_var.get(),
            show_event_overlay=self.show_events_var.get(),
            show_item_sprites=self.show_item_sprites_var.get(),
            show_item_markers=self.show_items_var.get(),
            show_puzzle_markers=self.show_puzzles_var.get(),
            show_enemy_wave_markers=self.show_enemy_waves_var.get(),
            show_enemy_sprites=self.show_enemy_sprites_var.get(),
            show_flying_wave_paths=self.show_flying_paths_var.get(),
            show_wave_reward_previews=self.show_wave_rewards_var.get(),
            show_hidden_spawned_items=self.show_hidden_spawned_var.get(),
            show_switch_markers=self.show_switches_var.get(),
            show_teleport_markers=self.show_teleports_var.get(),
            show_special_teleport_markers=self.show_special_teleports_var.get(),
            show_objective_location_markers=self.show_objective_locations_var.get(),
            show_player_start_marker=self.show_player_start_var.get(),
            show_trapdoor_markers=self.show_trapdoors_var.get(),
            show_moving_block_markers=self.show_moving_blocks_var.get(),
            show_moving_block_action_preview=self.show_moving_block_preview_var.get(),
            show_hint_markers=self.show_hints_var.get(),
            show_logic_links=self.show_logic_links_var.get(),
            recursive_logic_links=self.recursive_logic_links_var.get(),
            logic_link_scope=self.logic_link_scope_var.get(),
            selected_event_index=self.selected_event_index,
            selected_flying_path_index=self.selected_flying_path_index,
            selected_logic_point=self.selected_logic_point,
            show_grid=self.show_grid_var.get(),
        )

    def _load_resource(self, resource: LevelResource) -> None:
        try:
            map_data = load_packed_map(resource.map_path)
            alfils_data = load_packed_alfils(resource.alfils_path) if resource.alfils_path is not None else None
            object_path = level_object_table_path(self.game_dir, resource.level)
            weapon_path = level_weapon_table_path(self.game_dir, resource.level)
            object_table = load_packed_object_table(object_path) if object_path.exists() else None
            weapon_table = load_packed_weapon_table(weapon_path) if weapon_path.exists() else None
            sprite_bank = load_level_sprite_bank(self.game_dir, resource.level, resource.world)
            flying_paths = load_packed_flying_paths(resource.flying_paths_path) if resource.flying_paths_path is not None else None
            logic_graph = build_logic_graph(map_data, alfils_data, object_table, weapon_table) if alfils_data is not None else None
            diagnostics = build_level_diagnostics(map_data, alfils_data, logic_graph) if alfils_data is not None and logic_graph is not None else None
            self.selected_event_index = None
            self.selected_flying_path_index = None
            self.selected_logic_point = None
            self.selected_enemy_wave = None
            self.selected_map_item = None
            render_result = render_level_map(
                map_data,
                resource,
                self._build_render_options(),
                alfils_data,
                object_table,
                weapon_table,
                sprite_bank,
                flying_paths=flying_paths,
            )
        except (
            GodsCompressionError,
            MapFormatError,
            AlfilsFormatError,
            FlyingPathsFormatError,
            ItemTableFormatError,
            ValueError,
            OSError,
        ) as exc:
            messagebox.showerror(
                "GODS level viewer",
                f"Could not load {resource.map_path.name}\n\n{exc}",
            )
            return

        document = LevelDocument(
            resource=resource,
            map_data=map_data,
            alfils_data=alfils_data,
            object_table=object_table,
            weapon_table=weapon_table,
            sprite_bank=sprite_bank,
            flying_paths=flying_paths,
            logic_graph=logic_graph,
            diagnostics=diagnostics,
        )
        entity_index = build_entity_index(document)
        self.loaded = LoadedLevel(
            document=document,
            entity_index=entity_index,
            edit_session=EditSession(document),
            render_result=render_result,
        )
        self.map_canvas.set_image(render_result.image)
        self.map_canvas.set_overlay(render_result.canvas_overlay)
        self._populate_entity_tree()
        self._populate_puzzle_tree()
        self._update_info()
        self._update_logic_text()
        self._update_entity_properties()
        self._update_puzzle_text()
        self._update_diagnostics_text()
        self._update_raw_text()
        self._update_edit_prep_text()
        self.inspect_var.set("Click an event, enemy sprite, map object, or highlighted logic target; double-click also jumps to the same entity in Entity Browser.")
        self.hover_var.set("Hover an entity in the map to preview what would be selected.")

    def _rerender_loaded(self) -> None:
        if self.loaded is None:
            return
        try:
            render_result = render_level_map(
                self.loaded.map_data,
                self.loaded.resource,
                self._build_render_options(),
                self.loaded.alfils_data,
                self.loaded.object_table,
                self.loaded.weapon_table,
                self.loaded.sprite_bank,
                flying_paths=self.loaded.flying_paths,
            )
        except (GodsCompressionError, ValueError, OSError) as exc:
            messagebox.showerror("GODS level viewer", f"Could not rerender map.\n\n{exc}")
            return
        self.loaded = LoadedLevel(
            document=self.loaded.document,
            entity_index=self.loaded.entity_index,
            edit_session=self.loaded.edit_session,
            render_result=render_result,
        )
        self.map_canvas.set_image(render_result.image)
        self.map_canvas.set_overlay(render_result.canvas_overlay)
        self._update_info()
        self._update_logic_text()
        self._update_edit_prep_text()

    def _wave_reward_text(self, wave) -> str:
        if wave is None or not wave.has_reward or wave.reward_info_index is None:
            return "none"
        if wave.reward_kind == "object":
            info = self.loaded.object_table.get(wave.reward_info_index) if self.loaded is not None and self.loaded.object_table is not None else None
            name = info.full_name if info is not None else f"object {wave.reward_info_index}"
            return f"object #{wave.reward_info_index}: {name}"
        if wave.reward_kind == "weapon":
            info = self.loaded.weapon_table.get(wave.reward_info_index) if self.loaded is not None and self.loaded.weapon_table is not None else None
            name = info.full_name if info is not None else f"weapon {wave.reward_info_index}"
            return f"weapon #{wave.reward_info_index}: {name}"
        return "unknown"

    def _reward_suffix(self, wave) -> str:
        text = self._wave_reward_text(wave)
        return "" if text == "none" else f", reward={text}"

    def _enemy_info(self, wave, kind: str) -> EnemyInfo | None:
        if self.loaded is None:
            return None
        return get_enemy_info(self.loaded.resource.level, kind, wave.enemy_info_index)

    def _enemy_summary(self, wave, kind: str) -> str:
        info = self._enemy_info(wave, kind)
        if info is None:
            return f"enemy={wave.enemy_info_index}"
        sprite_index = info.sprite_index_for_facing(getattr(wave, "facing", 0))
        return (
            f"{info.display_name}, sprite={sprite_index}, "
            f"{info.width}×{info.height}px, action={info.action_type}"
        )

    def _describe_selected_flying_path(self, path_index: int) -> str:
        assert self.loaded is not None
        if self.loaded.flying_paths is None:
            return f"Flying path FP{path_index} is unavailable."
        path = self.loaded.flying_paths.get(path_index)
        if path is None:
            return f"Flying path FP{path_index} does not exist in this level bank."

        lines = [
            "Flying path inspector",
            "=====================",
            "",
            f"Path: FP{path.index}",
            f"Type: {path.kind}",
            f"Nodes: {len(path.deltas)}",
            f"Base: ({path.base_x}, {path.base_y})",
            "",
            "Flying-wave definitions using this path:",
        ]
        alfils = self.loaded.alfils_data
        graph = self.loaded.logic_graph
        if alfils is None:
            lines.append("  —")
            return "\n".join(lines)

        waves = [wave for wave in alfils.active_flying_waves if wave.flying_path_index == path.index]
        if not waves:
            lines.append("  —")
        for wave in waves:
            lines.append(
                f"  FW{wave.index}: ×{wave.enemy_count}, {self._enemy_summary(wave, 'flying')}, hp={wave.health}, reward={self._wave_reward_text(wave)}"
            )
            events = [event for event in alfils.active_events if event.event_type_index == 0 and event.param == wave.index]
            for event in events:
                cells = graph.event_cells.get(event.index, ()) if graph is not None else ()
                cell_text = ", ".join(f"{x},{y}" for x, y in cells[:4]) or "effect-only"
                if len(cells) > 4:
                    cell_text += ", …"
                lines.append(f"    triggered by E{event.index}: cells {cell_text}")
        lines.extend([
            "",
            "Map rendering:",
            "  • relative paths are drawn at each triggering event cell",
            "  • absolute paths keep their data-defined map coordinates",
            "  • reward previews are centered over the decoded enemy width, matching Kroah's placement rule",
        ])
        return "\n".join(lines)


    def _wave_from_selection(self, selection: EnemySelection):
        if self.loaded is None or self.loaded.alfils_data is None:
            return None
        alfils = self.loaded.alfils_data
        pools = {
            "FW": alfils.flying_waves,
            "WW": alfils.walking_waves,
            "IW": alfils.intel_walking_waves,
            "IF": alfils.intel_flying_waves,
        }
        pool = pools.get(selection.category)
        if pool is None or not (0 <= selection.wave_index < len(pool)):
            return None
        return pool[selection.wave_index]

    def _selection_enemy_kind(self, selection: EnemySelection) -> str:
        return "flying" if selection.category in {"FW", "IF"} else "walking"

    def _describe_selected_enemy_wave(self, selection: EnemySelection) -> str:
        assert self.loaded is not None
        wave = self._wave_from_selection(selection)
        if wave is None:
            return f"Enemy wave {selection.category}{selection.wave_index} is unavailable."
        alfils = self.loaded.alfils_data
        graph = self.loaded.logic_graph
        kind = self._selection_enemy_kind(selection)
        info = self._enemy_info(wave, kind)
        title = {
            "FW": "Flying wave",
            "WW": "Walking wave",
            "IW": "Intelligent walking wave",
            "IF": "Intelligent flying wave",
        }.get(selection.category, "Enemy wave")
        lines = [
            f"{title} {selection.category}{selection.wave_index}",
            "=" * (len(title) + len(selection.category) + len(str(selection.wave_index)) + 1),
            "",
            f"Enemy:   {self._enemy_summary(wave, kind)}",
            f"Count:   {wave.enemy_count}",
            f"Health:  {wave.health}",
            f"Reward:  {self._wave_reward_text(wave)}",
        ]
        if hasattr(wave, "facing"):
            lines.append(f"Facing:  {getattr(wave, 'facing')}")
        if info is not None:
            lines.extend([
                f"Info ID: enemy_info_index={wave.enemy_info_index}",
                f"Sprite:  DOS #{info.sprite_index_for_facing(getattr(wave, 'facing', 0))} (ST base #{info.sprite_index_st})",
                f"Bounds:  {info.width}×{info.height}px",
                f"Action:  {info.action_type}",
            ])

        if selection.category == "FW":
            path = self.loaded.flying_paths.get(wave.flying_path_index) if self.loaded.flying_paths is not None else None
            lines.extend([
                "",
                "Flying path:",
                f"  FP{wave.flying_path_index}" + (f" ({path.kind}, nodes={len(path.deltas)})" if path is not None else " (missing .PAT decode)"),
            ])
        elif selection.anchor_x is not None and selection.anchor_y is not None:
            lines.extend(["", f"Map anchor: ({selection.anchor_x}, {selection.anchor_y})"])

        lines.extend(["", "Triggering events:"])
        matching_events = []
        if alfils is not None:
            event_type = {"FW": 0, "WW": 1, "IW": 3, "IF": 4}.get(selection.category)
            if event_type is not None:
                matching_events = [
                    event for event in alfils.active_events
                    if event.event_type_index == event_type and event.param == selection.wave_index
                ]
        if not matching_events:
            lines.append("  —")
        for event in matching_events:
            cells = graph.event_cells.get(event.index, ()) if graph is not None else ()
            cells_text = ", ".join(f"({x},{y})" for x, y in cells) or "effect-only"
            lines.append(f"  E{event.index}: {self._event_action_text(event)}; cells {cells_text}")

        if selection.event_index is not None:
            lines.extend(["", f"Selected instance came from E{selection.event_index}."])

        if graph is not None and matching_events:
            event_indices = [event.index for event in matching_events]
            lines.extend(["", "Upstream/downstream logic:"])
            for event_index in event_indices[:8]:
                edges = graph.related_edges_for_event(event_index, recursive=self.recursive_logic_links_var.get())
                lines.append(f"  E{event_index}: {len(edges)} connected graph edges")
            if len(event_indices) > 8:
                lines.append(f"  ... {len(event_indices) - 8} more triggering events")

        return "\n".join(lines)

    def _select_enemy_wave(self, selection: EnemySelection, *, center: bool, status_prefix: str) -> None:
        self._clear_auto_flying_path_overlay()
        self.selected_event_index = None
        self.selected_flying_path_index = None
        self.selected_logic_point = None
        self.selected_enemy_wave = selection
        self.selected_map_item = None
        if center:
            center_x, center_y = selection.anchor_x, selection.anchor_y
            if center_x is None or center_y is None:
                if self.loaded is not None and self.loaded.alfils_data is not None and self.loaded.logic_graph is not None:
                    event_type = {"FW": 0, "WW": 1, "IW": 3, "IF": 4}.get(selection.category)
                    if event_type is not None:
                        for event in self.loaded.alfils_data.active_events:
                            if event.event_type_index != event_type or event.param != selection.wave_index:
                                continue
                            point = self.loaded.logic_graph.preferred_event_point(event.index)
                            if point is not None:
                                center_x, center_y = point.pixel_x, point.pixel_y
                                break
            if center_x is not None and center_y is not None:
                wave = self._wave_from_selection(selection)
                if wave is not None:
                    bounds = self._enemy_bounds(selection.category, wave, center_x, center_y)
                    center_x = (bounds[0] + bounds[2]) // 2
                    center_y = (bounds[1] + bounds[3]) // 2
                self.map_canvas.center_on_pixel(center_x, center_y)
        suffix = f" via E{selection.event_index}" if selection.event_index is not None else ""
        self.inspect_var.set(f"{status_prefix} enemy {selection.category}{selection.wave_index}{suffix}.")

    def _map_item_for_selection(self, selection: MapItemSelection):
        if self.loaded is None:
            return None
        items = self.loaded.map_data.items
        if not (0 <= selection.item_index < len(items)):
            return None
        item = items[selection.item_index]
        return None if item.is_empty else item

    def _map_item_sprite(self, item):
        if self.loaded is None or self.loaded.sprite_bank is None:
            return None
        if item.is_weapon:
            return self.loaded.sprite_bank.weapon_sprite(item.object_or_weapon_info_index - 192)
        return self.loaded.sprite_bank.object_sprite(item.object_or_weapon_info_index)

    def _map_item_bounds(self, item) -> tuple[int, int, int, int]:
        sprite = self._map_item_sprite(item)
        width = sprite.width if sprite is not None else 12
        height = sprite.height if sprite is not None else 12
        return (item.pixel_x, item.pixel_y, item.pixel_x + width, item.pixel_y + height)

    def _pick_map_item(self, image_x: int, image_y: int) -> MapItemSelection | None:
        if self.loaded is None:
            return None
        candidates: list[tuple[int, int, MapItemSelection]] = []
        for item in self.loaded.map_data.active_items:
            bounds = self._map_item_bounds(item)
            if not self._bbox_contains(bounds, image_x, image_y):
                continue
            x0, y0, x1, y1 = bounds
            area = max(1, (x1 - x0) * (y1 - y0))
            candidates.append((area, item.index, MapItemSelection(item.index)))
        if not candidates:
            return None
        return min(candidates, key=lambda row: (row[0], row[1]))[2]

    def _select_map_item(self, selection: MapItemSelection, *, center: bool, status_prefix: str) -> None:
        item = self._map_item_for_selection(selection)
        if item is None:
            return
        self._clear_auto_flying_path_overlay()
        self.selected_event_index = None
        self.selected_flying_path_index = None
        self.selected_enemy_wave = None
        self.selected_map_item = selection
        graph = self.loaded.logic_graph if self.loaded is not None else None
        self.selected_logic_point = graph.preferred_point_for_map_item(item.index) if graph is not None else None
        if center:
            bounds = self._map_item_bounds(item)
            self.map_canvas.center_on_pixel((bounds[0] + bounds[2]) // 2, (bounds[1] + bounds[3]) // 2)
        kind = "weapon" if item.is_weapon else "object"
        self.inspect_var.set(f"{status_prefix} map item I{item.index} ({kind}).")

    def _describe_selected_map_item(self, selection: MapItemSelection) -> str:
        assert self.loaded is not None
        item = self._map_item_for_selection(selection)
        if item is None:
            return f"Map item I{selection.item_index} is unavailable."
        graph = self.loaded.logic_graph
        sprite = self._map_item_sprite(item)
        lines = [
            f"Map item I{item.index}",
            "=" * (len(str(item.index)) + 10),
            "",
            f"Position:   ({item.pixel_x}, {item.pixel_y})",
            f"Raw ID:     {item.object_or_weapon_info_index} / 0x{item.object_or_weapon_info_index:04X}",
        ]
        if sprite is not None:
            lines.append(f"Sprite box: {sprite.width}×{sprite.height}px")

        if item.is_weapon:
            weapon_index = item.object_or_weapon_info_index - 192
            info = self.loaded.weapon_table.get(weapon_index) if self.loaded.weapon_table is not None else None
            lines.extend(["", f"Kind:       Weapon WPN{weapon_index}"])
            if info is None:
                lines.append("Metadata:   — weapon table unavailable")
            else:
                lines.extend([
                    f"Name:       {info.full_name}",
                    f"Value:      {info.value}",
                    f"Base power: {info.base_power}",
                    f"Current p.: {info.current_power}",
                    f"Facing:     {info.ingame_facing}",
                    f"Anim max:   {info.anim_index_max}",
                    f"Atlas refs: right #{info.sprite_index_first_right}, left #{info.sprite_index_first_left}",
                    f"Wall/enemy remove flags: {info.remove_on_wall_hit} / {info.remove_on_enemy_hit}",
                ])
        else:
            object_index = item.object_or_weapon_info_index
            info = self.loaded.object_table.get(object_index) if self.loaded.object_table is not None else None
            lines.extend(["", f"Kind:       Object OBJ{object_index}"])
            if info is None:
                lines.append("Metadata:   — object table unavailable")
            else:
                lines.extend([
                    f"Name:       {info.full_name}",
                    f"Type:       {info.type_name} ({info.type_index})",
                    f"Value:      {info.value}",
                    f"Table sprite index: {info.sprite_index}",
                ])
                if info.effect_name is not None:
                    lines.append(f"Usable effect: {info.effect_name} ({info.effect_index})")
                roles: list[str] = []
                if info.type_index == 3:
                    roles.append("visible switch sprite")
                if info.is_teleport_stone:
                    roles.append("teleport stone")
                if info.is_destructable:
                    roles.append("destructable type-4 target")
                if roles:
                    lines.append("Roles:      " + ", ".join(roles))

                if self.loaded.alfils_data is not None and info.type_index == 3:
                    matches = [
                        switch for switch in self.loaded.alfils_data.active_switches
                        if switch.pixel_x == item.pixel_x
                        and switch.pixel_y == item.pixel_y
                        and switch.object_info_index == object_index
                    ]
                    lines.extend(["", "Switch binding:"])
                    if matches:
                        lines.extend(
                            f"  S{switch.index}: {self._object_name(switch.object_info_index)}, pos=({switch.pixel_x}, {switch.pixel_y})"
                            for switch in matches
                        )
                    else:
                        lines.append("  — no exact PALFILS switch record")

                if self.loaded.alfils_data is not None and info.is_teleport_stone:
                    matches = [teleport for teleport in self.loaded.alfils_data.active_teleports if teleport.src_pixel_x == item.pixel_x]
                    lines.extend(["", "Teleport destinations:"])
                    if matches:
                        lines.extend(
                            f"  T{teleport.index}: source X={teleport.src_pixel_x} → marker ({teleport.marker_x}, {teleport.marker_y})"
                            for teleport in matches
                        )
                    else:
                        lines.append("  — no bound PALFILS teleport record; may use hardcoded teleport sequencing")

        lines.extend(["", "Logic graph roles:"])
        if graph is None:
            lines.append("  — PALFILS logic graph unavailable")
            return "\n".join(lines)
        points = graph.points_for_map_item(item.index)
        if points:
            for point in points:
                lines.append(f"  {point.label}: {point.kind} at ({point.pixel_x}, {point.pixel_y})")
        else:
            lines.append("  — this initial map item has no decoded direct graph role")

        direct = graph.direct_edges_for_map_item(item.index)
        lines.extend(["", "Direct logic links:"])
        if direct:
            for edge in direct:
                lines.append(f"  {edge.source.label} → {edge.target.label}: {edge.label}")
        else:
            lines.append("  —")

        related = graph.related_edges_for_map_item(item.index, recursive=self.recursive_logic_links_var.get())
        upstream_events = sorted({
            point.index
            for edge in related
            for point in (edge.source, edge.target)
            if point.kind == "event_cell" and point.index is not None
        })
        if upstream_events:
            lines.extend(["", "Connected map event indices:", "  " + ", ".join(f"E{index}" for index in upstream_events)])
        lines.extend(["", f"Visible connected logic edges ({'recursive component' if self.recursive_logic_links_var.get() else 'direct'}): {len(related)}"])
        for edge in related[:120]:
            state = ""
            if edge.positive_state is True:
                state = " [state=true]"
            elif edge.positive_state is False:
                state = " [state=false]"
            lines.append(f"  {edge.source.label} → {edge.target.label}: {edge.label}{state}")
        if len(related) > 120:
            lines.append(f"  ... {len(related) - 120} more")
        return "\n".join(lines)

    def _enemy_bounds(self, category: str, wave, anchor_x: int, anchor_y: int) -> tuple[int, int, int, int]:
        kind = "flying" if category in {"FW", "IF"} else "walking"
        info = self._enemy_info(wave, kind)
        sprite = None
        if self.loaded is not None and self.loaded.sprite_bank is not None and info is not None:
            sprite = self.loaded.sprite_bank.sprite(info.sprite_index_for_facing(getattr(wave, "facing", 0)))
        width = sprite.width if sprite is not None else (info.width if info is not None else 24)
        height = sprite.height if sprite is not None else (info.height if info is not None else 24)
        return (anchor_x, anchor_y, anchor_x + width, anchor_y + height)

    @staticmethod
    def _bbox_contains(bounds: tuple[int, int, int, int], image_x: int, image_y: int) -> bool:
        x0, y0, x1, y1 = bounds
        return x0 <= image_x < x1 and y0 <= image_y < y1

    def _pick_enemy_wave(self, image_x: int, image_y: int) -> EnemySelection | None:
        if self.loaded is None or self.loaded.alfils_data is None:
            return None
        alfils = self.loaded.alfils_data
        candidates: list[tuple[int, EnemySelection]] = []
        for category, waves in (
            ("WW", alfils.active_walking_waves),
            ("IW", alfils.active_intel_walking_waves),
            ("IF", alfils.active_intel_flying_waves),
        ):
            for wave in waves:
                bounds = self._enemy_bounds(category, wave, wave.pixel_x, wave.pixel_y)
                if not self._bbox_contains(bounds, image_x, image_y):
                    continue
                x0, y0, x1, y1 = bounds
                area = max(1, (x1 - x0) * (y1 - y0))
                candidates.append((area, EnemySelection(category, wave.index, None, wave.pixel_x, wave.pixel_y)))

        if self.loaded.flying_paths is not None:
            map_data = self.loaded.map_data
            for cell_y in range(64):
                for cell_x in range(128):
                    value = map_data.layer_b_at(cell_x, cell_y)
                    if value < 3:
                        continue
                    event_index = value - 3
                    event = alfils.event(event_index)
                    if event is None or event.event_type_index != 0:
                        continue
                    if not (0 <= event.param < len(alfils.flying_waves)):
                        continue
                    wave = alfils.flying_waves[event.param]
                    path = self.loaded.flying_paths.get(wave.flying_path_index)
                    if path is None:
                        continue
                    center_x = cell_x * MAP_CELL_WIDTH + MAP_CELL_WIDTH // 2
                    center_y = cell_y * MAP_CELL_HEIGHT + MAP_CELL_HEIGHT // 2
                    points = path.points_for_event_center(center_x, center_y)
                    if not points:
                        continue
                    anchor_x, anchor_y = points[0]
                    bounds = self._enemy_bounds("FW", wave, anchor_x, anchor_y)
                    if not self._bbox_contains(bounds, image_x, image_y):
                        continue
                    x0, y0, x1, y1 = bounds
                    area = max(1, (x1 - x0) * (y1 - y0))
                    candidates.append((area, EnemySelection("FW", wave.index, event_index, anchor_x, anchor_y)))

        if not candidates:
            return None
        return min(candidates, key=lambda row: row[0])[1]

    def _on_map_hover(self, image_x: int | None, image_y: int | None) -> None:
        if self.loaded is None or image_x is None or image_y is None:
            self.hover_var.set("Hover an entity in the map to preview what would be selected.")
            return
        enemy = self._pick_enemy_wave(image_x, image_y)
        if enemy is not None:
            suffix = f" via E{enemy.event_index}" if enemy.event_index is not None else ""
            self.hover_var.set(f"Hover: enemy {enemy.category}{enemy.wave_index}{suffix}. Click to inspect the wave.")
            return
        item = self._pick_map_item(image_x, image_y)
        if item is not None:
            raw_item = self._map_item_for_selection(item)
            label = f"I{item.item_index}"
            if raw_item is not None:
                label += " weapon" if raw_item.is_weapon else " object"
            self.hover_var.set(f"Hover: map item {label}. Click to inspect its metadata and logic role.")
            return
        logic = self.loaded.logic_graph.pick_point(image_x, image_y) if self.loaded.logic_graph is not None else None
        if logic is not None:
            self.hover_var.set(f"Hover: {logic.label} ({logic.kind}). Click to inspect its logic graph.")
            return
        self.hover_var.set("Hover: map background. Click to inspect tile/layer values.")

    def _update_logic_text(self) -> None:
        if self.loaded is None or self.loaded.logic_graph is None:
            text = (
                "No PALFILS logic graph is available for this level.\n\n"
                "Once PALFILS is loaded, click a yellow event cell in the rendered map to inspect its "
                "direct target, puzzle relations, switch/event conditions, and recursive TriggerEvent chains."
            )
        elif self.selected_enemy_wave is not None:
            text = self._describe_selected_enemy_wave(self.selected_enemy_wave)
        elif self.selected_map_item is not None:
            text = self._describe_selected_map_item(self.selected_map_item)
        elif self.selected_logic_point is not None:
            text = self.loaded.logic_graph.describe_point(
                self.selected_logic_point,
                recursive=self.recursive_logic_links_var.get(),
            )
        elif self.selected_flying_path_index is not None:
            text = self._describe_selected_flying_path(self.selected_flying_path_index)
        elif self.selected_event_index is None:
            graph = self.loaded.logic_graph
            text = (
                "Logic inspector\n"
                "===============\n\n"
                "Click an event cell, enemy sprite, map object, door/backdoor target, destructible target, spawned item, "
                "teleport-like target, or another highlighted logic point. The selected component will be traced when "
                "‘Selected event logic links’ is enabled.\n\n"
                f"Known map-triggered event indices: {len(graph.event_cells)}\n"
                f"Logic edges decoded so far: {len(graph.all_edges)}\n\n"
                "Current graph coverage:\n"
                "  • event → walking/intelligent wave, puzzle, or moving block\n"
                "  • puzzle TriggerEvent → event\n"
                "  • EventTriggered / EventNotTriggered conditions → puzzle\n"
                "  • SwitchOn / SwitchOff conditions → puzzle\n"
                "  • puzzle effects → spawned objects/weapons, doors, backdoors, destructable-object destruction\n"
                "  • trapdoor puzzle effects → trapdoor marker\n"
                "  • reverse inspection: physical target → owning puzzle/event chain\n"
            )
        else:
            text = self.loaded.logic_graph.describe_event(
                self.selected_event_index,
                recursive=self.recursive_logic_links_var.get(),
            )
            event = self.loaded.alfils_data.event(self.selected_event_index) if self.loaded.alfils_data is not None else None
            if event is not None and event.event_type_index == 0 and self.loaded.flying_paths is not None:
                if 0 <= event.param < len(self.loaded.alfils_data.flying_waves):
                    wave = self.loaded.alfils_data.flying_waves[event.param]
                    path = self.loaded.flying_paths.get(wave.flying_path_index)
                    if path is not None:
                        text += (
                            "\n\nFlying path details:"
                            f"\n  Wave: FW{wave.index}"
                            f"\n  Enemy: {self._enemy_summary(wave, 'flying')}"
                            f"\n  Path: FP{path.index} ({path.kind})"
                            f"\n  Nodes: {len(path.deltas)}"
                            f"\n  Base: ({path.base_x}, {path.base_y})"
                            f"\n  Reward: {self._wave_reward_text(wave)}"
                        )
        self.logic_text.delete("1.0", tk.END)
        self.logic_text.insert("1.0", text)
        mechanism_text = self._mechanism_text_for_selection()
        self.mechanism_text.delete("1.0", tk.END)
        self.mechanism_text.insert("1.0", mechanism_text)
        self._update_entity_properties()
        self._update_puzzle_text()
        self._update_entity_tree_highlight()

    def _mechanism_text_for_selection(self) -> str:
        if self.loaded is None or self.loaded.logic_graph is None:
            return (
                "Mechanism view\n"
                "==============\n\n"
                "No PALFILS logic graph is available for this level.\n"
                "Once logic data is loaded, select an event, map item, enemy wave, flying path, or logic target. "
                "This tab will translate the connected graph into a designer-facing story."
            )

        graph = self.loaded.logic_graph
        recursive = self.recursive_logic_links_var.get()

        if self.selected_event_index is not None:
            return describe_event_mechanism(graph, self.selected_event_index, recursive=recursive).text
        if self.selected_map_item is not None:
            return describe_map_item_mechanism(graph, self.selected_map_item.item_index, recursive=recursive).text
        if self.selected_logic_point is not None:
            return describe_point_mechanism(graph, self.selected_logic_point, recursive=recursive).text
        if self.selected_enemy_wave is not None:
            return self._describe_enemy_wave_mechanism(self.selected_enemy_wave)
        if self.selected_flying_path_index is not None:
            return self._describe_flying_path_mechanism(self.selected_flying_path_index)

        return (
            "Mechanism view\n"
            "==============\n\n"
            "Select something in the map or Entity Browser.\n\n"
            "This tab intentionally stays human-facing:\n"
            "  • what starts the mechanism,\n"
            "  • which puzzle conditions gate it,\n"
            "  • what it changes in the level,\n"
            "  • and which chained events continue the story.\n\n"
            "The adjacent Logic Inspector keeps the low-level graph/raw detail."
        )

    def _describe_enemy_wave_mechanism(self, selection: EnemySelection) -> str:
        assert self.loaded is not None
        graph = self.loaded.logic_graph
        alfils = self.loaded.alfils_data
        if graph is None or alfils is None:
            return "Enemy-wave mechanism is unavailable because PALFILS logic is missing."

        event_type = {"FW": 0, "WW": 1, "IW": 3, "IF": 4}.get(selection.category)
        matching_events = [] if event_type is None else [
            event for event in alfils.active_events
            if event.event_type_index == event_type and event.param == selection.wave_index
        ]
        edge_groups = [graph.related_edges_for_event(event.index, recursive=self.recursive_logic_links_var.get()) for event in matching_events]
        edges = merge_edges(*edge_groups) if edge_groups else ()
        event_indices = tuple(event.index for event in matching_events)
        selected_instance = f" The clicked instance came from E{selection.event_index}." if selection.event_index is not None else ""
        narrative = describe_component(
            graph,
            title=f"Mechanism behind enemy wave {selection.category}{selection.wave_index}",
            selection_summary=(
                f"Selected enemy wave {selection.category}{selection.wave_index}. "
                f"Known triggering events: {', '.join(f'E{index}' for index in event_indices) or 'none'}."
                f"{selected_instance}"
            ),
            edges=edges,
            root_events=event_indices,
        )
        return narrative.text

    def _describe_flying_path_mechanism(self, path_index: int) -> str:
        assert self.loaded is not None
        graph = self.loaded.logic_graph
        alfils = self.loaded.alfils_data
        if graph is None or alfils is None:
            return "Flying-path mechanism is unavailable because PALFILS logic is missing."
        waves = [wave for wave in alfils.active_flying_waves if wave.flying_path_index == path_index]
        wave_indices = {wave.index for wave in waves}
        matching_events = [
            event for event in alfils.active_events
            if event.event_type_index == 0 and event.param in wave_indices
        ]
        edge_groups = [graph.related_edges_for_event(event.index, recursive=self.recursive_logic_links_var.get()) for event in matching_events]
        edges = merge_edges(*edge_groups) if edge_groups else ()
        event_indices = tuple(event.index for event in matching_events)
        wave_text = ", ".join(f"FW{wave.index}" for wave in waves) or "none"
        narrative = describe_component(
            graph,
            title=f"Mechanism around flying path FP{path_index}",
            selection_summary=(
                f"Selected flying path FP{path_index}. Flying waves using it: {wave_text}. "
                f"Known triggering events: {', '.join(f'E{index}' for index in event_indices) or 'none'}."
            ),
            edges=edges,
            root_events=event_indices,
        )
        return narrative.text

    def _update_info(self) -> None:
        assert self.loaded is not None
        loaded = self.loaded
        map_data = loaded.map_data
        render = loaded.render_result
        extra_name = render.extra_bank_used.name if render.extra_bank_used is not None else "—"
        missing = ", ".join(str(value) for value in render.missing_tile_ids) if render.missing_tile_ids else "none"
        layer_b_event_cells = sum(value >= 3 for value in map_data.layer_b)
        alfils = loaded.alfils_data
        alfils_lines = [] if alfils is None else [
            f"PALFILS: {loaded.resource.alfils_path.name if loaded.resource.alfils_path is not None else '—'}",
            f"PALFILS packed / unpacked: {alfils.packed_size} / {alfils.unpacked_size} bytes",
            f"Wave rewards: {sum(w.has_reward for w in alfils.active_flying_waves) + sum(w.has_reward for w in alfils.active_walking_waves) + sum(w.has_reward for w in alfils.active_intel_flying_waves) + sum(w.has_reward for w in alfils.active_intel_walking_waves)}",
            f"Events / switches / teleports: {len(alfils.active_events)} / {len(alfils.active_switches)} / {len(alfils.active_teleports)}",
            f"Trapdoors / moving blocks / hints: {len(alfils.active_trapdoors)} / {len(alfils.active_moving_blocks)} / {len(alfils.active_hints)}",
            f"Logic graph edges: {len(loaded.logic_graph.all_edges) if loaded.logic_graph is not None else 0}",
        ]
        self.info_var.set(
            "\n".join(
                [
                    f"Map: {loaded.resource.map_path.name}",
                    f"Tile bank: {loaded.resource.bits_path.name}",
                    f"Shared XTRA bank: {extra_name}",
                    f"Packed / unpacked: {map_data.packed_size} / {map_data.unpacked_size} bytes",
                    f"Raster colors / height: {map_data.raster.color_count} / {map_data.raster.height}",
                    f"Layer A max tile: {map_data.layer_a_max_tile}",
                    f"Loaded tile slots: {render.loaded_tile_count}",
                    f"Missing tile ids: {missing}",
                    f"Active map items: {len(map_data.active_items)}",
                    f"Object / weapon tables: {len(loaded.object_table.records) if loaded.object_table is not None else 0} / {len(loaded.weapon_table.records) if loaded.weapon_table is not None else 0}",
                    f"Sprite bank entries: {len(loaded.sprite_bank.sprites) if loaded.sprite_bank is not None else 0}",
                    f"Flying path bank: {loaded.resource.flying_paths_path.name if loaded.resource.flying_paths_path is not None else '—'}",
                    f"Flying path records: {len(loaded.flying_paths.paths) if loaded.flying_paths is not None else 0}",
                    "Enemy metadata: DOS EXE-compatible table mapped to DOS sprite bank",
                    f"Active puzzle records: {len(map_data.active_puzzles)}",
                    f"Layer B event cells: {layer_b_event_cells}",
                    *alfils_lines,
                ]
            )
        )

    def _update_diagnostics_text(self) -> None:
        if self.loaded is None or self.loaded.diagnostics is None:
            text = "Level diagnostics are unavailable for this resource."
        else:
            text = self.loaded.diagnostics.render_text()
        self.diagnostics_text.delete("1.0", tk.END)
        self.diagnostics_text.insert("1.0", text)

    def _update_edit_prep_text(self) -> None:
        if self.loaded is None:
            text = "Edit mode preparation is unavailable until a level is loaded."
        else:
            index = self.loaded.entity_index
            group_counts = "\n".join(f"  • {group}: {count}" for group, count in index.counts_by_group())
            text = (
                self.loaded.edit_session.render_summary()
                + "\n\nUnified entity index\n--------------------\n"
                + f"Entities indexed: {index.count}\n"
                + (group_counts or "  —")
            )
        self.edit_prep_text.delete("1.0", tk.END)
        self.edit_prep_text.insert("1.0", text)

    def _update_raw_text(self) -> None:
        assert self.loaded is not None
        loaded = self.loaded
        map_data = loaded.map_data
        alfils = loaded.alfils_data
        lines = [
            f"Map file: {loaded.resource.map_path.name}",
            f"  packed size:   {map_data.packed_size}",
            f"  unpacked size: {map_data.unpacked_size}",
            f"  raster colors: {map_data.raster.color_count}",
            f"  raster height: {map_data.raster.height}",
            "  raster palette: " + " ".join(f"{word:04X}" for word in map_data.raster.palette_words),
            "",
            "Layer A:",
            f"  max tile id: {map_data.layer_a_max_tile}",
            f"  non-zero cells: {map_data.layer_a_nonzero_count}",
            "",
            "Layer B:",
            f"  walls (1): {sum(value == 1 for value in map_data.layer_b)}",
            f"  stairs (2): {sum(value == 2 for value in map_data.layer_b)}",
            f"  event-ish cells (>=3): {sum(value >= 3 for value in map_data.layer_b)}",
            "",
            f"Map items ({len(map_data.active_items)} active of {len(map_data.items)} slots):",
        ]
        for item in map_data.active_items[:80]:
            kind = "weapon" if item.is_weapon else "object"
            detail = ""
            if item.is_weapon and loaded.weapon_table is not None:
                info = loaded.weapon_table.get(item.object_or_weapon_info_index - 192)
                if info is not None:
                    detail = f" — {info.full_name}"
            elif item.is_object and loaded.object_table is not None:
                info = loaded.object_table.get(item.object_or_weapon_info_index)
                if info is not None:
                    detail = f" — {info.type_name}: {info.full_name}"
            lines.append(
                f"  I{item.index:03d}: ({item.pixel_x:4d}, {item.pixel_y:4d}) "
                f"id={item.object_or_weapon_info_index:04X} {kind}{detail}"
            )
        if len(map_data.active_items) > 80:
            lines.append(f"  ... {len(map_data.active_items) - 80} more item records")

        lines.extend(["", "Puzzle strings:"])
        any_strings = False
        for index, text in enumerate(map_data.puzzle_strings):
            if text:
                any_strings = True
                lines.append(f"  S{index:02d}: {text}")
        if not any_strings:
            lines.append("  —")

        lines.extend(["", f"Puzzle records ({len(map_data.active_puzzles)} appear active):"])
        for puzzle in map_data.active_puzzles[:80]:
            c0, c1, c2 = puzzle.condition_function_indices
            p0, p1, p2 = puzzle.condition_params
            lines.append(
                f"  P{puzzle.index:03d}: ({puzzle.pixel_x:4d}, {puzzle.pixel_y:4d}) "
                f"cond=[{c0}:{p0}, {c1}:{p1}, {c2}:{p2}] "
                f"effect={puzzle.effect_function_index}:{puzzle_effect_name(puzzle.effect_function_index)} param={puzzle.effect_param} "
                f"remove={int(puzzle.remove_after_effect)} string={puzzle.string_index}"
            )
        if len(map_data.active_puzzles) > 80:
            lines.append(f"  ... {len(map_data.active_puzzles) - 80} more puzzle records")

        if alfils is None:
            lines.extend(["", "PALFILS logic: — not loaded"] )
        else:
            lines.extend([
                "",
                f"PALFILS logic file: {loaded.resource.alfils_path.name if loaded.resource.alfils_path is not None else '—'}",
                f"  packed / unpacked: {alfils.packed_size} / {alfils.unpacked_size}",
                f"  active events: {len(alfils.active_events)}",
                f"  walking waves: {len(alfils.active_walking_waves)}",
                f"  intelligent flying / walking waves: {len(alfils.active_intel_flying_waves)} / {len(alfils.active_intel_walking_waves)}",
                f"  switches: {len(alfils.active_switches)}",
                f"  teleports: {len(alfils.active_teleports)}",
                f"  trapdoors: {len(alfils.active_trapdoors)}",
                f"  moving blocks: {len(alfils.active_moving_blocks)}",
                f"  hints: {len(alfils.active_hints)}",
                "",
                "Event records used by layer B cells:",
            ])
            event_indices = sorted({value - 3 for value in map_data.layer_b if value >= 3})
            for event_index in event_indices[:120]:
                event = alfils.event(event_index)
                if event is None:
                    lines.append(f"  E{event_index:03d}: — unused PALFILS slot")
                else:
                    lines.append(f"  E{event_index:03d}: {self._event_action_text(event)}")
            if len(event_indices) > 120:
                lines.append(f"  ... {len(event_indices) - 120} more event indices referenced from layer B")

            lines.extend(["", "Switches:"])
            for record in alfils.active_switches[:80]:
                lines.append(f"  S{record.index:02d}: ({record.pixel_x:4d}, {record.pixel_y:4d}) {self._object_name(record.object_info_index)}")
            if len(alfils.active_switches) > 80:
                lines.append(f"  ... {len(alfils.active_switches) - 80} more switches")

            lines.extend(["", "Teleports:"])
            for record in alfils.active_teleports:
                lines.append(f"  T{record.index:02d}: srcX={record.src_pixel_x:4d} -> ({record.normalized_dst_pixel_x:4d}, {record.normalized_dst_pixel_y:4d})")

            lines.extend(["", "Trapdoors:"])
            for record in alfils.active_trapdoors:
                state = "open" if record.is_opened else "closed"
                lines.append(f"  D{record.index:02d}: ({record.pixel_x:4d}, {record.pixel_y:4d}) {state}")

            lines.extend(["", "Moving blocks:"])
            for record in alfils.active_moving_blocks[:80]:
                target_text = ", ".join(f"{i}=({x},{y})" for i, (x, y) in enumerate(record.target_points) if not (x == 0 and y == 0)) or "—"
                lines.append(
                    f"  MB{record.index:02d}: ({record.pixel_x:4d}, {record.pixel_y:4d}) "
                    f"size={record.width_min1 + 1}x{record.height_min1 + 1} "
                    f"sprite={record.map_sprite_index_min1 + 1} actions={list(record.actions)} targets={target_text}"
                )
            if len(alfils.active_moving_blocks) > 80:
                lines.append(f"  ... {len(alfils.active_moving_blocks) - 80} more moving blocks")

            lines.extend(["", "Hints:"])
            for record in alfils.active_hints:
                lines.append(f"  H{record.index:02d}: x={record.pixel_x:4d} text={record.text!r}")

            if loaded.logic_graph is not None:
                lines.extend(["", "Logic graph summary:"])
                lines.append(f"  edge count: {len(loaded.logic_graph.all_edges)}")
                lines.append(f"  map-triggered event indices: {len(loaded.logic_graph.event_cells)}")
                if self.selected_event_index is not None:
                    lines.append(f"  selected event: E{self.selected_event_index}")
                if self.selected_logic_point is not None:
                    lines.append(f"  selected logic point: {self.selected_logic_point.label} ({self.selected_logic_point.kind})")
                if self.selected_enemy_wave is not None:
                    lines.append(f"  selected enemy wave: {self.selected_enemy_wave.category}{self.selected_enemy_wave.wave_index}")

        self.raw_text.delete("1.0", tk.END)
        self.raw_text.insert("1.0", "\n".join(lines))

    def _entity_search_matches(self, *parts: object) -> bool:
        query = self.entity_search_var.get().strip().lower()
        if not query:
            return True
        haystack = " ".join(str(part) for part in parts if part is not None).lower()
        return query in haystack

    def _insert_entity_group(self, label: str) -> str:
        tree = self.entity_trees.get(label)
        if tree is None:
            tree = self._create_entity_group_tab(label)
        return ""

    def _create_entity_group_tab(self, label: str) -> ttk.Treeview:
        frame = ttk.Frame(self.entity_group_stack)
        button = ttk.Button(
            self.entity_group_bar,
            text=label,
            command=lambda name=label: self._show_entity_group(name),
        )
        tree = ttk.Treeview(
            frame,
            columns=("detail", "pos"),
            show="tree headings",
            height=12,
            selectmode="browse",
        )
        tree.heading("#0", text="Entity")
        tree.heading("detail", text="Meaning")
        tree.heading("pos", text="Pos")
        tree.column("#0", width=82, stretch=False)
        tree.column("detail", width=185, stretch=True)
        tree.column("pos", width=66, stretch=False)
        tree.tag_configure("related", font=self.entity_related_font)
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.bind("<<TreeviewSelect>>", self._on_browser_entity_selected)
        tree.bind("<Double-Button-1>", self._on_entity_selected)
        self.entity_group_frames[label] = frame
        self.entity_group_buttons[label] = button
        self.entity_trees[label] = tree
        self._layout_entity_group_buttons()
        if self.selected_entity_group is None:
            self._show_entity_group(label)
        return tree

    def _layout_entity_group_buttons(self) -> None:
        if not hasattr(self, "entity_group_bar"):
            return
        width = max(1, self.entity_group_bar.winfo_width())
        columns = max(1, width // 108)
        for button in self.entity_group_buttons.values():
            button.grid_forget()
        for index, button in enumerate(self.entity_group_buttons.values()):
            row = index // columns
            column = index % columns
            button.grid(row=row, column=column, sticky="ew", padx=(0, 3), pady=(0, 3))
        for column in range(columns):
            self.entity_group_bar.columnconfigure(column, weight=1)

    def _show_entity_group(self, label: str) -> None:
        frame = self.entity_group_frames.get(label)
        if frame is None:
            return
        for other in self.entity_group_frames.values():
            other.pack_forget()
        frame.pack(fill=tk.BOTH, expand=True)
        self.selected_entity_group = label

    def _insert_entity(
        self,
        parent: str | ttk.Treeview,
        label: str,
        detail: str,
        position: str,
        ref_kind: str,
        ref_value: object,
    ) -> None:
        tree = parent if isinstance(parent, ttk.Treeview) else self.entity_trees.get(parent)
        if tree is None:
            return
        iid = f"entity:{len(self.entity_refs)}"
        tree.insert("", tk.END, iid=iid, text=label, values=(detail, position))
        ref = (ref_kind, ref_value)
        self.entity_refs[iid] = ref
        group = next((name for name, candidate in self.entity_trees.items() if candidate is tree), "")
        self.entity_rows_by_ref.setdefault(ref, (label, group, detail, position))

    @staticmethod
    def _position_text(x: int | None, y: int | None) -> str:
        if x is None or y is None:
            return "—"
        return f"{x},{y}"

    def _clear_auto_flying_path_overlay(self) -> None:
        if self._auto_enabled_flying_paths:
            self.show_flying_paths_var.set(False)
            self._auto_enabled_flying_paths = False

    @staticmethod
    def _role_label(kind: str) -> str:
        labels = {
            "switch_item": "physical switch",
            "switch": "switch state",
            "puzzle": "puzzle",
            "teleport_stone": "teleport stone",
            "destructable_object": "destructable target",
            "map_object_source": "object source",
            "map_weapon_source": "weapon source",
            "spawned_object": "spawned object",
            "spawned_weapon": "spawned weapon",
            "door": "door",
            "backdoor": "backdoor",
            "backdoor_destination": "backdoor destination",
            "trapdoor": "trapdoor",
            "moving_block": "moving block",
        }
        return labels.get(kind, kind.replace("_", " "))

    def _property_rows_for_selection(self) -> list[tuple[str, str, str]]:
        if self.loaded is None:
            return []
        graph = self.loaded.logic_graph
        rows: list[tuple[str, str, str]] = []

        if self.selected_map_item is not None:
            item = self._map_item_for_selection(self.selected_map_item)
            if item is None:
                return [("Selection", f"I{self.selected_map_item.item_index}", "map")]
            rows.extend([
                ("Entity", f"I{item.index}", "map"),
                ("Kind", "weapon" if item.is_weapon else "object", "map"),
                ("Position X", str(item.pixel_x), "map"),
                ("Position Y", str(item.pixel_y), "map"),
                ("Raw ID", f"{item.object_or_weapon_info_index} / 0x{item.object_or_weapon_info_index:04X}", "map"),
            ])
            sprite = self._map_item_sprite(item)
            if sprite is not None:
                rows.append(("Sprite box", f"{sprite.width}x{sprite.height}", "sprite"))
            if item.is_weapon:
                weapon_index = item.object_or_weapon_info_index - 192
                info = self.loaded.weapon_table.get(weapon_index) if self.loaded.weapon_table is not None else None
                rows.append(("Weapon", f"WPN{weapon_index}", "table"))
                if info is not None:
                    rows.extend([
                        ("Name", info.full_name, "table"),
                        ("Value", str(info.value), "table"),
                        ("Power", f"{info.base_power}/{info.current_power}", "table"),
                    ])
            else:
                object_index = item.object_or_weapon_info_index
                info = self.loaded.object_table.get(object_index) if self.loaded.object_table is not None else None
                rows.append(("Object", f"OBJ{object_index}", "table"))
                if info is not None:
                    rows.extend([
                        ("Name", info.full_name, "table"),
                        ("Type", f"{info.type_name} ({info.type_index})", "table"),
                        ("Value", str(info.value), "table"),
                    ])
                    if info.effect_name is not None:
                        rows.append(("Usable effect", f"{info.effect_name} ({info.effect_index})", "table"))
            if graph is not None:
                points = graph.points_for_map_item(item.index)
                if points:
                    rows.append(("Roles", ", ".join(self._role_label(point.kind) for point in points), "logic"))
                puzzles = sorted({
                    point.index
                    for edge in graph.related_edges_for_map_item(item.index, recursive=False)
                    for point in (edge.source, edge.target)
                    if point.kind == "puzzle" and point.index is not None
                })
                if puzzles:
                    rows.append(("Puzzle links", ", ".join(f"P{index}" for index in puzzles), "logic"))
            return rows

        if self.selected_logic_point is not None:
            point = self.selected_logic_point
            rows.extend([
                ("Entity", point.label, "logic"),
                ("Kind", self._role_label(point.kind), "logic"),
                ("Position X", str(point.pixel_x), "logic"),
                ("Position Y", str(point.pixel_y), "logic"),
            ])
            if point.index is not None:
                rows.append(("Index", str(point.index), "logic"))
            if graph is not None:
                rows.append(("Direct links", str(len(graph.direct_edges_for_point(point))), "logic"))
                puzzles = sorted({
                    other.index
                    for edge in graph.related_edges_for_point(point, recursive=False)
                    for other in (edge.source, edge.target)
                    if other.kind == "puzzle" and other.index is not None
                })
                if puzzles:
                    rows.append(("Puzzle links", ", ".join(f"P{index}" for index in puzzles), "logic"))
            return rows

        if self.selected_event_index is not None:
            event = self.loaded.alfils_data.event(self.selected_event_index) if self.loaded.alfils_data is not None else None
            rows.append(("Entity", f"E{self.selected_event_index}", "logic"))
            if event is not None:
                rows.extend([
                    ("Type", event.type_name, "PALFILS"),
                    ("Param", str(event.param), "PALFILS"),
                ])
            cells = graph.event_cells.get(self.selected_event_index, ()) if graph is not None else ()
            rows.append(("Map cells", ", ".join(f"{x},{y}" for x, y in cells[:4]) or "effect-only", "map"))
            return rows

        if self.selected_enemy_wave is not None:
            wave = self._wave_from_selection(self.selected_enemy_wave)
            rows.append(("Entity", f"{self.selected_enemy_wave.category}{self.selected_enemy_wave.wave_index}", "PALFILS"))
            if wave is not None:
                rows.extend([
                    ("Count", str(wave.enemy_count), "PALFILS"),
                    ("Health", str(wave.health), "PALFILS"),
                    ("Enemy", self._enemy_summary(wave, self._selection_enemy_kind(self.selected_enemy_wave)), "table"),
                    ("Reward", self._wave_reward_text(wave), "table"),
                ])
            return rows

        if self.selected_flying_path_index is not None:
            rows.append(("Entity", f"P{self.selected_flying_path_index}", ".PAT"))
            path = self.loaded.flying_paths.get(self.selected_flying_path_index) if self.loaded.flying_paths is not None else None
            if path is not None:
                rows.extend([
                    ("Type", path.kind, ".PAT"),
                    ("Nodes", str(len(path.deltas)), ".PAT"),
                    ("Base", f"{path.base_x},{path.base_y}", ".PAT"),
                ])
            return rows

        return [("Selection", "None", "viewer")]

    def _update_entity_properties(self) -> None:
        if not hasattr(self, "property_tree"):
            return
        self.property_tree.delete(*self.property_tree.get_children())
        if self.loaded is None:
            return
        if self.selected_event_index is not None:
            self._insert_event_properties(self.selected_event_index)
        elif self.selected_enemy_wave is not None:
            self._insert_enemy_wave_properties(self.selected_enemy_wave, title="Selected enemy wave")
        elif self.selected_map_item is not None:
            self._insert_map_item_properties(self.selected_map_item)
        elif self.selected_logic_point is not None:
            if self.selected_logic_point.kind == "puzzle" and self.selected_logic_point.index is not None:
                self._insert_puzzle_properties(self.selected_logic_point.index)
            else:
                self._insert_logic_point_properties(self.selected_logic_point)
        elif self.selected_flying_path_index is not None:
            self._insert_flying_path_properties(self.selected_flying_path_index)
        else:
            self.property_tree.insert("", tk.END, text="Selection", values=("None",))

    def _selection_snapshot(self) -> tuple[int | None, int | None, LogicPoint | None, EnemySelection | None, MapItemSelection | None]:
        return (
            self.selected_event_index,
            self.selected_flying_path_index,
            self.selected_logic_point,
            self.selected_enemy_wave,
            self.selected_map_item,
        )

    def _restore_selection_snapshot(self, snapshot: tuple[int | None, int | None, LogicPoint | None, EnemySelection | None, MapItemSelection | None]) -> None:
        (
            self.selected_event_index,
            self.selected_flying_path_index,
            self.selected_logic_point,
            self.selected_enemy_wave,
            self.selected_map_item,
        ) = snapshot

    def _set_selection_from_ref_for_properties(self, ref: tuple[str, object]) -> None:
        ref_kind, value = ref
        self.selected_event_index = None
        self.selected_flying_path_index = None
        self.selected_logic_point = None
        self.selected_enemy_wave = None
        self.selected_map_item = None
        if ref_kind == "event":
            self.selected_event_index = int(value)
        elif ref_kind == "path":
            self.selected_flying_path_index = int(value)
        elif ref_kind == "wave":
            assert isinstance(value, EnemySelection)
            self.selected_enemy_wave = value
        elif ref_kind == "item":
            assert isinstance(value, MapItemSelection)
            self.selected_map_item = value
        else:
            assert isinstance(value, LogicPoint)
            self.selected_logic_point = value

    def _populate_properties_tree_for_ref(self, tree: ttk.Treeview, ref: tuple[str, object]) -> None:
        if self.loaded is None:
            return
        snapshot = self._selection_snapshot()
        original_tree = self.property_tree
        try:
            self.property_tree = tree
            self._set_selection_from_ref_for_properties(ref)
            self._update_entity_properties()
        finally:
            self.property_tree = original_tree
            self._restore_selection_snapshot(snapshot)

    def _insert_property_section(self, title: str, source: str, *, open: bool = True) -> str:
        return self.property_tree.insert("", tk.END, text=title, values=("",), open=open)

    def _insert_property(self, parent: str, field: str, value: object, source: str, *, open: bool = True) -> str:
        return self.property_tree.insert(parent, tk.END, text=field, values=(str(value),), open=open)

    def _event_cells_text(self, event_index: int, *, limit: int = 8) -> str:
        if self.loaded is None or self.loaded.logic_graph is None:
            return "effect-only"
        cells = self.loaded.logic_graph.event_cells.get(event_index, ())
        if not cells:
            return "effect-only"
        text = ", ".join(f"{x},{y}" for x, y in cells[:limit])
        if len(cells) > limit:
            text += ", ..."
        return text

    def _wave_target_for_event(self, event) -> tuple[str, object, str, str] | None:
        if self.loaded is None or self.loaded.alfils_data is None or event is None:
            return None
        alfils = self.loaded.alfils_data
        if event.event_type_index == 0 and 0 <= event.param < len(alfils.flying_waves):
            return "FW", alfils.flying_waves[event.param], "flying", "flying wave"
        if event.event_type_index == 1 and 0 <= event.param < len(alfils.walking_waves):
            return "WW", alfils.walking_waves[event.param], "walking", "walking wave"
        if event.event_type_index == 3 and 0 <= event.param < len(alfils.intel_walking_waves):
            return "IW", alfils.intel_walking_waves[event.param], "walking", "intelligent walking wave"
        if event.event_type_index == 4 and 0 <= event.param < len(alfils.intel_flying_waves):
            return "IF", alfils.intel_flying_waves[event.param], "flying", "intelligent flying wave"
        return None

    def _insert_wave_fields(self, parent: str, prefix: str, wave, enemy_kind: str, source: str) -> None:
        self._insert_property(parent, "Wave", f"{prefix}{wave.index}", source)
        self._insert_property(parent, "Enemy count", wave.enemy_count, source)
        self._insert_property(parent, "Health", wave.health, source)
        self._insert_property(parent, "Enemy info", self._enemy_summary(wave, enemy_kind), "enemy table")
        self._insert_property(parent, "Reward", self._wave_reward_text(wave), "item table")
        if hasattr(wave, "spawn_delay"):
            self._insert_property(parent, "Spawn delay", getattr(wave, "spawn_delay"), source)
        if hasattr(wave, "facing"):
            self._insert_property(parent, "Facing", getattr(wave, "facing"), source)
        if prefix == "FW":
            self._insert_property(parent, "Flying path", f"FP{wave.flying_path_index}", ".PAT")
        info = self._enemy_info(wave, enemy_kind)
        if info is not None:
            self._insert_property(parent, "Sprite", f"DOS #{info.sprite_index_for_facing(getattr(wave, 'facing', 0))}", "sprite table")
            self._insert_property(parent, "Bounds", f"{info.width}x{info.height}px", "enemy table")
            self._insert_property(parent, "Action", info.action_type, "enemy table")

    def _insert_puzzle_effect_fields(self, parent: str, puzzle) -> None:
        effect = self._insert_property(parent, "Effect", self._effect_text(puzzle), "decoded", open=True)
        self._insert_property(effect, "Raw type", f"{puzzle.effect_function_index}: {puzzle_effect_name(puzzle.effect_function_index)}", "map")
        self._insert_property(effect, "Raw param", puzzle.effect_param, "map")
        self._insert_property(effect, "Remove item after effect", int(puzzle.remove_after_effect), "map")

        effect_type = puzzle.effect_function_index
        param = puzzle.effect_param
        if effect_type == 0:
            target = self._insert_property(effect, "Object", self._object_name(param), "object table", open=True)
            self._insert_property(target, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map")
        elif effect_type == 1:
            target = self._insert_property(effect, "Weapon", self._weapon_name(param), "weapon table", open=True)
            self._insert_property(target, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map")
        elif effect_type in (2, 9):
            target = self._insert_property(effect, "Door", f"{puzzle.pixel_x},{puzzle.pixel_y} 32x48", "map", open=True)
            self._insert_property(target, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map")
            self._insert_property(target, "Size", "32x48", "map")
        elif effect_type == 5:
            target = self._insert_property(effect, "Event", self._event_trigger_text(param - 1), "PALFILS", open=True)
            self._insert_property(target, "Trigger cells", self._event_cells_text(param - 1), "map")
        elif effect_type == 6:
            target = self._insert_property(effect, "Target", "type-4 destructible", "decoded", open=True)
            self._insert_property(target, "Search origin", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map")
        elif effect_type in (7, 8):
            target = self._insert_property(effect, "Trapdoor", f"D{param}", "PALFILS", open=True)
            if self.loaded is not None and self.loaded.alfils_data is not None and 0 <= param < len(self.loaded.alfils_data.trapdoors):
                trapdoor = self.loaded.alfils_data.trapdoors[param]
                self._insert_property(target, "Position", f"{trapdoor.pixel_x},{trapdoor.pixel_y}", "PALFILS")
        elif effect_type == 10:
            self._insert_property(effect, "Weapon", self._weapon_name(param), "weapon table")

    def _insert_puzzle_condition_fields(self, parent: str, puzzle) -> None:
        conditions = self._insert_property(parent, "Conditions", "all must pass", "map puzzle", open=True)
        for slot, (condition_type, param) in enumerate(zip(puzzle.condition_function_indices, puzzle.condition_params)):
            condition_parent = self._insert_property(
                conditions,
                f"Condition {slot}",
                self._condition_text(condition_type, param),
                "decoded",
                open=True,
            )
            self._insert_property(condition_parent, "Type", f"{condition_type}: {condition_type_name(condition_type)}", "map")
            self._insert_puzzle_condition_param_fields(condition_parent, condition_type, param)

    def _insert_event_effect_tree(self, parent: str, event) -> None:
        effect = self._insert_property(parent, "Effect", event.type_name, "PALFILS", open=True)
        self._insert_property(effect, "Raw type", event.event_type_index, "PALFILS")
        self._insert_property(effect, "Raw param", event.param, "PALFILS")

        wave_target = self._wave_target_for_event(event)
        if wave_target is not None:
            prefix, wave, enemy_kind, title = wave_target
            param = self._insert_property(effect, "Param: wave", f"{prefix}{event.param}", "PALFILS", open=True)
            self._insert_property(param, "Meaning", title, "decoded")
            self._insert_wave_fields(param, prefix, wave, enemy_kind, "PALFILS")
            return

        if event.event_type_index == 2 and self.loaded.map_data is not None:
            puzzle = self.loaded.map_data.puzzles[event.param] if 0 <= event.param < len(self.loaded.map_data.puzzles) else None
            param = self._insert_property(effect, "Param: puzzle", f"P{event.param}", "map puzzle", open=True)
            if puzzle is None:
                self._insert_property(param, "Status", "puzzle slot unavailable", "map")
                return
            self._insert_property(param, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map")
            self._insert_puzzle_effect_fields(param, puzzle)
            self._insert_puzzle_condition_fields(param, puzzle)
            self._insert_puzzle_condition_summary(param, puzzle.index)
            return

        if event.event_type_index is not None and 6 <= event.event_type_index <= 9 and self.loaded.alfils_data is not None:
            block = self.loaded.alfils_data.moving_blocks[event.param] if 0 <= event.param < len(self.loaded.alfils_data.moving_blocks) else None
            param = self._insert_property(effect, "Param: moving block", f"MB{event.param}", "PALFILS", open=True)
            if block is None:
                self._insert_property(param, "Status", "moving block slot unavailable", "PALFILS")
                return
            action_index = event.event_type_index - 6
            self._insert_property(param, "Action", f"A{action_index}: {block.action_description(action_index)}", "PALFILS")
            self._insert_property(param, "Position", f"{block.pixel_x},{block.pixel_y}", "PALFILS")
            self._insert_property(param, "Size", f"{block.width_pixels}x{block.height_pixels}px", "PALFILS")
            return

        if event.event_type_index == 5:
            self._insert_property(effect, "Param: checkpoint", event.param, "PALFILS")
        elif event.event_type_index == 10:
            self._insert_property(effect, "Param: guardian", event.param, "PALFILS")
        elif event.event_type_index == 11:
            self._insert_property(effect, "Status", "inactive event slot", "PALFILS")
        else:
            self._insert_property(effect, "Decoded param", event.param, "PALFILS")

    def _insert_event_properties(self, event_index: int) -> None:
        assert self.loaded is not None
        event = self.loaded.alfils_data.event(event_index) if self.loaded.alfils_data is not None else None
        root = self._insert_property_section(f"Map trigger E{event_index}", "layer B / PALFILS")
        self._insert_property(root, "Trigger cells", self._event_cells_text(event_index), "map")
        if event is None:
            self._insert_property(root, "Status", "unused PALFILS event slot", "PALFILS")
            return
        self._insert_event_effect_tree(root, event)

        if self.loaded.logic_graph is not None:
            graph = self.loaded.logic_graph
            links = self._insert_property_section("Graph links", "logic", open=False)
            direct = graph.outgoing_edges_for_event(event_index)
            incoming = graph.incoming_edges_for_event(event_index)
            self._insert_property(links, "Direct outgoing", len(direct), "logic")
            self._insert_property(links, "Incoming", len(incoming), "logic")
            related = graph.related_edges_for_event(event_index, recursive=self.recursive_logic_links_var.get())
            self._insert_property(links, "Connected edges", len(related), "logic")
            puzzles = sorted({
                point.index
                for edge in related
                for point in (edge.source, edge.target)
                if point.kind == "puzzle" and point.index is not None
            })
            if puzzles:
                self._insert_property(links, "Puzzle records", ", ".join(f"P{index}" for index in puzzles[:12]), "logic")

    def _insert_enemy_wave_properties(self, selection: EnemySelection, *, title: str) -> None:
        wave = self._wave_from_selection(selection)
        root = self._insert_property_section(f"{title}: {selection.category}{selection.wave_index}", "PALFILS")
        if wave is None:
            self._insert_property(root, "Status", "wave slot unavailable", "PALFILS")
            return
        self._insert_wave_fields(root, selection.category, wave, self._selection_enemy_kind(selection), "PALFILS")
        if selection.event_index is not None:
            self._insert_property(root, "Clicked trigger", f"E{selection.event_index}", "map")
        if self.loaded is not None and self.loaded.alfils_data is not None:
            event_type = {"FW": 0, "WW": 1, "IW": 3, "IF": 4}.get(selection.category)
            events = [
                event for event in self.loaded.alfils_data.active_events
                if event.event_type_index == event_type and event.param == selection.wave_index
            ]
            if events:
                triggers = self._insert_property_section("Trigger events", "PALFILS", open=False)
                for event in events[:16]:
                    self._insert_property(triggers, f"E{event.index}", self._event_cells_text(event.index, limit=3), "map")

    def _insert_map_item_properties(self, selection: MapItemSelection) -> None:
        item = self._map_item_for_selection(selection)
        root = self._insert_property_section(f"Map item I{selection.item_index}", "map")
        if item is None:
            self._insert_property(root, "Status", "map item unavailable", "map")
            return
        self._insert_property(root, "Kind", "weapon" if item.is_weapon else "object", "map")
        self._insert_property(root, "Position", f"{item.pixel_x},{item.pixel_y}", "map")
        self._insert_property(root, "Raw ID", f"{item.object_or_weapon_info_index} / 0x{item.object_or_weapon_info_index:04X}", "map")
        sprite = self._map_item_sprite(item)
        if sprite is not None:
            self._insert_property(root, "Sprite box", f"{sprite.width}x{sprite.height}px", "sprite")
        if item.is_weapon:
            weapon_index = item.object_or_weapon_info_index - 192
            info = self.loaded.weapon_table.get(weapon_index) if self.loaded is not None and self.loaded.weapon_table is not None else None
            table = self._insert_property_section(f"Weapon WPN{weapon_index}", "weapon table")
            if info is not None:
                self._insert_property(table, "Name", info.full_name, "weapon table")
                self._insert_property(table, "Value", info.value, "weapon table")
                self._insert_property(table, "Power", f"{info.base_power}/{info.current_power}", "weapon table")
        else:
            object_index = item.object_or_weapon_info_index
            info = self.loaded.object_table.get(object_index) if self.loaded is not None and self.loaded.object_table is not None else None
            table = self._insert_property_section(f"Object OBJ{object_index}", "object table")
            if info is not None:
                self._insert_property(table, "Name", info.full_name, "object table")
                self._insert_property(table, "Type", f"{info.type_name} ({info.type_index})", "object table")
                self._insert_property(table, "Value", info.value, "object table")
                if info.effect_name is not None:
                    self._insert_property(table, "Usable effect", f"{info.effect_name} ({info.effect_index})", "object table")
        if self.loaded is not None and self.loaded.logic_graph is not None:
            graph = self.loaded.logic_graph
            roles = self._insert_property_section("Decoded roles", "logic")
            points = graph.points_for_map_item(item.index)
            if points:
                for point in points:
                    self._insert_property(roles, point.label, self._role_label(point.kind), "logic")
            else:
                self._insert_property(roles, "Role", "no decoded direct graph role", "logic")
            links = self._insert_property_section("Puzzle / mechanism links", "logic", open=False)
            puzzles = self._puzzle_links_for_map_item(item.index, recursive=False)
            self._insert_property(links, "Puzzle records", ", ".join(f"P{index}" for index in puzzles) if puzzles else "none", "logic")
            self._insert_property(links, "Direct edges", len(graph.direct_edges_for_map_item(item.index)), "logic")

    def _insert_logic_point_properties(self, point: LogicPoint) -> None:
        root = self._insert_property_section(f"{point.label}: {self._role_label(point.kind)}", "logic")
        self._insert_property(root, "Position", f"{point.pixel_x},{point.pixel_y}", "logic")
        if point.index is not None:
            self._insert_property(root, "Index", point.index, "logic")
        self._insert_logic_point_specific_properties(point)
        if self.loaded is not None and self.loaded.logic_graph is not None:
            graph = self.loaded.logic_graph
            direct = graph.direct_edges_for_point(point)
            self._insert_property(root, "Direct links", len(direct), "logic")
            links = self._insert_property_section("Connected graph", "logic", open=False)
            related = graph.related_edges_for_point(point, recursive=self.recursive_logic_links_var.get())
            self._insert_property(links, "Connected edges", len(related), "logic")
            puzzles = sorted({
                other.index
                for edge in related
                for other in (edge.source, edge.target)
                if other.kind == "puzzle" and other.index is not None
            })
            self._insert_property(links, "Puzzle records", ", ".join(f"P{index}" for index in puzzles) if puzzles else "none", "logic")

    def _insert_logic_point_specific_properties(self, point: LogicPoint) -> None:
        if self.loaded is None or self.loaded.alfils_data is None or point.index is None:
            return
        alfils = self.loaded.alfils_data

        if point.kind == "hint" and 0 <= point.index < len(alfils.hints):
            record = alfils.hints[point.index]
            section = self._insert_property_section(f"Hint H{record.index}", "PALFILS")
            self._insert_property(section, "X position", record.pixel_x, "PALFILS")
            self._insert_property(section, "Message", record.text or "empty", "PALFILS")
            return

        if point.kind == "switch" and 0 <= point.index < len(alfils.switches):
            record = alfils.switches[point.index]
            section = self._insert_property_section(f"Switch S{record.index}", "PALFILS")
            self._insert_property(section, "Object", self._object_name(record.object_info_index), "object table")
            self._insert_property(section, "Position", f"{record.pixel_x},{record.pixel_y}", "PALFILS")
            self._insert_property(section, "Physical binding", self._switch_binding_text(record.index), "logic")
            return

        if point.kind == "teleport" and 0 <= point.index < len(alfils.teleports):
            record = alfils.teleports[point.index]
            section = self._insert_property_section(f"Teleport T{record.index}", "PALFILS")
            self._insert_property(section, "Source X", record.src_pixel_x, "PALFILS")
            self._insert_property(section, "Destination", f"{record.normalized_dst_pixel_x},{record.normalized_dst_pixel_y}", "PALFILS")
            self._insert_property(section, "Marker", f"{record.marker_x},{record.marker_y}", "viewer")
            return

        if point.kind == "trapdoor" and 0 <= point.index < len(alfils.trapdoors):
            record = alfils.trapdoors[point.index]
            section = self._insert_property_section(f"Trapdoor D{record.index}", "PALFILS")
            self._insert_property(section, "Initial state", "opened" if record.is_opened else "closed", "PALFILS")
            self._insert_property(section, "Position", f"{record.pixel_x},{record.pixel_y}", "PALFILS")
            return

        if point.kind == "moving_block" and 0 <= point.index < len(alfils.moving_blocks):
            record = alfils.moving_blocks[point.index]
            section = self._insert_property_section(f"Moving block MB{record.index}", "PALFILS")
            self._insert_property(section, "Position", f"{record.pixel_x},{record.pixel_y}", "PALFILS")
            self._insert_property(section, "Size", f"{record.width_pixels}x{record.height_pixels}px", "PALFILS")
            self._insert_property(section, "Sprite tile", record.map_sprite_index, "PALFILS")
            self._insert_property(section, "Speed", f"{record.speed_pixels_per_frame}px/frame", "PALFILS")
            targets = self._insert_property_section("Target points", "PALFILS", open=False)
            for index, (x, y) in enumerate(record.target_points):
                if x == 0 and y == 0:
                    continue
                self._insert_property(targets, f"Target {index}", f"{x},{y}", "PALFILS")
            actions = self._insert_property_section("Actions", "PALFILS", open=False)
            for index in range(len(record.actions)):
                self._insert_property(actions, f"A{index}", record.action_description(index), "PALFILS")
            return

        if point.kind == "hardcoded_teleport_destination":
            for record in special_teleport_destinations(self.loaded.resource.level):
                if record.index != point.index:
                    continue
                section = self._insert_property_section(f"Hardcoded teleport HT{record.index}", "PC table")
                self._insert_property(section, "Destination", f"{record.pixel_x},{record.pixel_y}", "PC table")
                self._insert_property(section, "Coded value", f"0x{record.coded:04X}", "PC table")
                if record.unpacked_game_offset is not None:
                    self._insert_property(section, "GAME.EXE offset", f"0x{record.unpacked_game_offset:X}", "PC table")
                return

        if point.kind == "objective_location":
            for record in objective_locations(self.loaded.resource.level):
                if record.index != point.index:
                    continue
                section = self._insert_property_section(f"Objective OJE{record.index}", "PC table")
                self._insert_property(section, "Cell", f"{record.cell_x},{record.cell_y}", "PC table")
                self._insert_property(section, "Position", f"{record.pixel_x},{record.pixel_y}", "PC table")
                self._insert_property(section, "GAME.EXE offset", f"0x{record.unpacked_game_offset:X}", "PC table")
                return

        if point.kind == "player_start":
            record = player_start_location(self.loaded.resource.level)
            if record is None:
                return
            section = self._insert_property_section("Player start", "PC table")
            self._insert_property(section, "Position", f"{record.pixel_x},{record.pixel_y}", "PC table")
            self._insert_property(section, "Source", record.source_note, "PC table")

    def _object_name(self, object_index: int) -> str:
        if self.loaded is None or self.loaded.object_table is None:
            return f"OBJ{object_index}"
        info = self.loaded.object_table.get(object_index)
        return f"OBJ{object_index}: {info.full_name}" if info is not None else f"OBJ{object_index}"

    def _object_ref(self, object_index: int) -> str:
        if self.loaded is None or self.loaded.object_table is None:
            return f"OBJ{object_index}"
        info = self.loaded.object_table.get(object_index)
        return f"OBJ{object_index} ({info.full_name})" if info is not None else f"OBJ{object_index}"

    def _weapon_name(self, weapon_index: int) -> str:
        if self.loaded is None or self.loaded.weapon_table is None:
            return f"WPN{weapon_index}"
        info = self.loaded.weapon_table.get(weapon_index)
        return f"WPN{weapon_index}: {info.full_name}" if info is not None else f"WPN{weapon_index}"

    def _weapon_ref(self, weapon_index: int) -> str:
        if self.loaded is None or self.loaded.weapon_table is None:
            return f"WPN{weapon_index}"
        info = self.loaded.weapon_table.get(weapon_index)
        return f"WPN{weapon_index} ({info.full_name})" if info is not None else f"WPN{weapon_index}"

    def _switch_binding_text(self, switch_index: int) -> str:
        if self.loaded is None or self.loaded.logic_graph is None:
            return f"S{switch_index}"
        graph = self.loaded.logic_graph
        sources = [
            edge.source.label
            for edge in graph.all_edges
            if edge.edge_kind == "switch_binding"
            and edge.target.kind == "switch"
            and edge.target.index == switch_index
        ]
        if sources:
            return f"S{switch_index} via {', '.join(sources)}"
        return f"S{switch_index}"

    def _condition_param_rows(self, condition_type: int, param: int) -> list[tuple[str, object, str]]:
        if condition_type == 0:
            return []
        if condition_type in (1, 2):
            return [("Object", self._object_ref(param), "object table")]
        if condition_type in (3, 4):
            return [("Weapon", self._weapon_ref(param), "weapon table")]
        if condition_type in (5, 6):
            event_index = param - 1
            return [
                ("Event", self._event_trigger_text(event_index), "PALFILS"),
                ("Trigger cells", self._event_cells_text(event_index), "map"),
            ]
        if condition_type == 7:
            return [("Health threshold", f"{param}/24", "decoded")]
        if condition_type == 8:
            return [("Health threshold", f"{param}/24", "decoded")]
        if condition_type == 9:
            return [("Time threshold", f"{param * 5}s", "decoded")]
        if condition_type == 10:
            return [("Time threshold", f"{param * 5}s", "decoded")]
        if condition_type == 11:
            rows: list[tuple[str, object, str]] = [("Switch", self._switch_binding_text(param), "PALFILS")]
            if self.loaded is not None and self.loaded.alfils_data is not None and 0 <= param < len(self.loaded.alfils_data.switches):
                switch = self.loaded.alfils_data.switches[param]
                rows.extend(
                    [
                        ("Object", self._object_name(switch.object_info_index), "object table"),
                        ("Position", f"{switch.pixel_x},{switch.pixel_y}", "PALFILS"),
                    ]
                )
            return rows
        if condition_type == 12:
            rows = [("Switch", self._switch_binding_text(param), "PALFILS")]
            if self.loaded is not None and self.loaded.alfils_data is not None and 0 <= param < len(self.loaded.alfils_data.switches):
                switch = self.loaded.alfils_data.switches[param]
                rows.extend(
                    [
                        ("Object", self._object_name(switch.object_info_index), "object table"),
                        ("Position", f"{switch.pixel_x},{switch.pixel_y}", "PALFILS"),
                    ]
                )
            return rows
        if condition_type == 13:
            return [("Score threshold", param * 5000, "decoded")]
        if condition_type == 14:
            return [("Score threshold", param * 5000, "decoded")]
        if condition_type == 15:
            return [("Lives threshold", param, "decoded")]
        if condition_type == 16:
            return [("Lives threshold", param, "decoded")]
        return [("Raw param", param, "map")]

    def _insert_puzzle_condition_param_fields(self, parent: str, condition_type: int, param: int) -> None:
        if condition_type in (5, 6):
            event_index = param - 1
            target = self._insert_property(parent, "Event", self._event_trigger_text(event_index), "PALFILS", open=True)
            self._insert_property(target, "Trigger cells", self._event_cells_text(event_index), "map")
            return
        if condition_type in (11, 12):
            target = self._insert_property(parent, "Switch", self._switch_binding_text(param), "PALFILS", open=True)
            if self.loaded is not None and self.loaded.alfils_data is not None and 0 <= param < len(self.loaded.alfils_data.switches):
                switch = self.loaded.alfils_data.switches[param]
                self._insert_property(target, "Object", self._object_name(switch.object_info_index), "object table")
                self._insert_property(target, "Position", f"{switch.pixel_x},{switch.pixel_y}", "PALFILS")
            return
        for field, value, source in self._condition_param_rows(condition_type, param):
            self._insert_property(parent, field, value, source)

    def _event_action_text(self, event) -> str:
        target = self._wave_target_for_event(event)
        if target is not None:
            prefix, wave, _enemy_kind, _title = target
            return f"spawn {prefix}{wave.index}"
        if event.event_type_index == 2:
            return f"check P{event.param}"
        if event.event_type_index is not None and 6 <= event.event_type_index <= 9:
            return f"activate MB{event.param} A{event.event_type_index - 6}"
        if event.event_type_index == 5:
            return f"checkpoint {event.param}"
        if event.event_type_index == 10:
            return f"load guardian {event.param}"
        if event.event_type_index == 11:
            return "inactive"
        return f"{event.type_name} param={event.param}"

    def _event_trigger_text(self, event_index: int) -> str:
        if self.loaded is None or self.loaded.alfils_data is None:
            return f"E{event_index}"
        event = self.loaded.alfils_data.event(event_index)
        if event is None:
            return f"E{event_index}"
        return f"E{event_index} ({self._event_action_text(event)})"

    def _condition_text(self, condition_type: int, param: int) -> str:
        name = condition_type_name(condition_type)
        param_rows = self._condition_param_rows(condition_type, param)
        param_text = str(param_rows[0][1]) if param_rows else str(param)
        if condition_type == 0:
            return "always true"
        if condition_type in (1, 2):
            verb = "player carries" if condition_type == 1 else "player does not carry"
            return f"{verb} {param_text}"
        if condition_type in (3, 4):
            verb = "player holds" if condition_type == 3 else "player does not hold"
            return f"{verb} {param_text}"
        if condition_type in (5, 6):
            verb = "event has fired" if condition_type == 5 else "event has not fired"
            return f"{verb}: {param_text}"
        if condition_type in (11, 12):
            verb = "switch ON" if condition_type == 11 else "switch OFF"
            return f"{verb}: {param_text}"
        if condition_type == 7:
            return f"health > {param_text}"
        if condition_type == 8:
            return f"health < {param_text}"
        if condition_type == 9:
            return f"time > {param_text}"
        if condition_type == 10:
            return f"time < {param_text}"
        if condition_type == 13:
            return f"score > {param_text}"
        if condition_type == 14:
            return f"score < {param_text}"
        if condition_type == 15:
            return f"lives > {param_text}"
        if condition_type == 16:
            return f"lives < {param_text}"
        return f"{name}({param})"

    def _effect_text(self, puzzle) -> str:
        effect = puzzle.effect_function_index
        param = puzzle.effect_param
        name = puzzle_effect_name(effect)
        if effect == 0:
            return f"spawn {self._object_ref(param)}"
        if effect == 1:
            return f"spawn {self._weapon_ref(param)}"
        if effect in (2, 9):
            return f"{name} at ({puzzle.pixel_x},{puzzle.pixel_y})"
        if effect == 5:
            return f"trigger {self._event_trigger_text(param - 1)}"
        if effect == 6:
            return f"destroy type-4 target at/near ({puzzle.pixel_x},{puzzle.pixel_y})"
        if effect in (7, 8):
            return f"{name} D{param}"
        if effect == 10:
            return f"remove {self._weapon_ref(param)}"
        return f"{name} param={param}"

    def _puzzle_condition_meaning(self, puzzle) -> str:
        conditions = [
            self._condition_text(kind, param)
            for kind, param in zip(puzzle.condition_function_indices, puzzle.condition_params)
            if kind != 0
        ]
        return "; ".join(conditions) if conditions else "always"

    def _puzzle_meaning_text(self, puzzle) -> str:
        return f"if {self._puzzle_condition_meaning(puzzle)} -> {self._effect_text(puzzle)}"

    def _insert_puzzle_condition_summary(self, parent: str, puzzle_index: int) -> None:
        if self.loaded is None or not (0 <= puzzle_index < len(self.loaded.map_data.puzzles)):
            return
        puzzle = self.loaded.map_data.puzzles[puzzle_index]
        summary = self._puzzle_condition_meaning(puzzle)
        self._insert_property(parent, "Readable conditions", summary, "decoded")

    def _insert_puzzle_properties(self, puzzle_index: int) -> None:
        assert self.loaded is not None
        if not (0 <= puzzle_index < len(self.loaded.map_data.puzzles)):
            root = self._insert_property_section(f"Puzzle P{puzzle_index}", "map")
            self._insert_property(root, "Status", "puzzle slot unavailable", "map")
            return

        puzzle = self.loaded.map_data.puzzles[puzzle_index]
        root = self._insert_property_section(f"Puzzle P{puzzle.index}", "map puzzle")
        self._insert_property(root, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map")
        if 0 <= puzzle.string_index < len(self.loaded.map_data.puzzle_strings):
            text = self.loaded.map_data.puzzle_strings[puzzle.string_index]
            if text:
                self._insert_property(root, "Message", text, "map")

        self._insert_puzzle_effect_fields(root, puzzle)
        self._insert_puzzle_condition_fields(root, puzzle)
        if self.loaded.logic_graph is not None:
            graph = self.loaded.logic_graph
            point = graph.point_for_puzzle(puzzle.index)
            if point is not None:
                outgoing = [edge for edge in graph.direct_edges_for_point(point) if graph._same_graph_node(edge.source, point)]
                incoming = [edge for edge in graph.direct_edges_for_point(point) if graph._same_graph_node(edge.target, point)]
                if outgoing:
                    targets = self._insert_property_section("Resolved effect targets", "logic", open=True)
                    for edge in outgoing[:20]:
                        self._insert_property(targets, edge.target.label, edge.label, "logic")
                if incoming:
                    sources = self._insert_property_section("Condition graph sources", "logic", open=False)
                    for edge in incoming[:20]:
                        self._insert_property(sources, edge.source.label, edge.label, "logic")

    def _insert_flying_path_properties(self, path_index: int) -> None:
        root = self._insert_property_section(f"Flying path FP{path_index}", ".PAT")
        path = self.loaded.flying_paths.get(path_index) if self.loaded is not None and self.loaded.flying_paths is not None else None
        if path is None:
            self._insert_property(root, "Status", "path unavailable", ".PAT")
            return
        self._insert_property(root, "Type", path.kind, ".PAT")
        self._insert_property(root, "Nodes", len(path.deltas), ".PAT")
        self._insert_property(root, "Base", f"{path.base_x},{path.base_y}", ".PAT")

    def _populate_entity_tree(self) -> None:
        if not hasattr(self, "entity_group_stack"):
            return
        for frame in self.entity_group_frames.values():
            frame.destroy()
        for button in self.entity_group_buttons.values():
            button.destroy()
        self.entity_group_frames.clear()
        self.entity_group_buttons.clear()
        self.entity_trees.clear()
        self.entity_refs.clear()
        self.context_refs.clear()
        self.entity_rows_by_ref.clear()
        if hasattr(self, "context_tree"):
            self.context_tree.delete(*self.context_tree.get_children())
        self.selected_entity_group = None
        if self.loaded is None:
            return

        graph = self.loaded.logic_graph
        alfils = self.loaded.alfils_data
        if graph is None or alfils is None:
            tree = self._create_entity_group_tab("Logic")
            tree.insert("", tk.END, text="No PALFILS graph", values=("Load a level with logic data", ""))
            return

        for group_name, entities in self.loaded.entity_index.iter_groups():
            tree = self._create_entity_group_tab(group_name)
            for entity in entities:
                detail, position, ref_kind, ref_value = self._entity_browser_row(entity)
                self._insert_entity(tree, entity.label, detail, position, ref_kind, ref_value)
        self._update_entity_tree_highlight()

    def _puzzle_links_for_map_item(self, item_index: int, *, recursive: bool = False) -> tuple[int, ...]:
        if self.loaded is None or self.loaded.logic_graph is None:
            return ()
        graph = self.loaded.logic_graph
        edges = graph.related_edges_for_map_item(item_index, recursive=recursive) if recursive else graph.direct_edges_for_map_item(item_index)
        return tuple(sorted({
            point.index
            for edge in edges
            for point in (edge.source, edge.target)
            if point.kind == "puzzle" and point.index is not None
        }))

    def _populate_puzzle_tree(self) -> None:
        if not hasattr(self, "puzzle_tree"):
            return
        self.puzzle_tree.delete(*self.puzzle_tree.get_children())
        self.puzzle_refs.clear()
        if self.loaded is None or self.loaded.logic_graph is None:
            return

        graph = self.loaded.logic_graph
        for item in self.loaded.map_data.active_items:
            points = graph.points_for_map_item(item.index)
            puzzle_links = self._puzzle_links_for_map_item(item.index, recursive=False)
            if not points and not puzzle_links:
                continue
            roles = ", ".join(dict.fromkeys(self._role_label(point.kind) for point in points))
            links = ", ".join(f"P{index}" for index in puzzle_links) or "—"
            iid = self.puzzle_tree.insert(
                "",
                tk.END,
                text=f"I{item.index}",
                values=(roles or "map item", links, self._position_text(item.pixel_x, item.pixel_y)),
            )
            self.puzzle_refs[iid] = ("item", MapItemSelection(item.index))

        puzzle_parent = self.puzzle_tree.insert("", tk.END, text="Puzzle records", values=("", "", ""), open=False)
        for puzzle in self.loaded.map_data.active_puzzles:
            point = graph.point_for_puzzle(puzzle.index)
            if point is None:
                continue
            incoming = [
                edge.source.label
                for edge in graph.direct_edges_for_point(point)
                if graph._same_graph_node(edge.target, point)
            ]
            links = ", ".join(incoming[:3]) or "—"
            if len(incoming) > 3:
                links += ", ..."
            iid = self.puzzle_tree.insert(
                puzzle_parent,
                tk.END,
                text=f"P{puzzle.index}",
                values=(self._puzzle_meaning_text(puzzle), links, self._position_text(point.pixel_x, point.pixel_y)),
            )
            self.puzzle_refs[iid] = ("point", point)

    def _puzzle_text_for_selection(self) -> str:
        if self.loaded is None or self.loaded.logic_graph is None:
            return "Puzzle view is unavailable until PALFILS logic is loaded."
        if self.selected_map_item is not None:
            item = self._map_item_for_selection(self.selected_map_item)
            if item is None:
                return f"Map item I{self.selected_map_item.item_index} is unavailable."
            graph = self.loaded.logic_graph
            points = graph.points_for_map_item(item.index)
            puzzle_links = self._puzzle_links_for_map_item(item.index, recursive=False)
            lines = [
                f"Unified object I{item.index}",
                "=" * (len(str(item.index)) + 17),
                "",
                f"Map object: {'weapon' if item.is_weapon else 'object'} raw={item.object_or_weapon_info_index}",
                f"Position: ({item.pixel_x}, {item.pixel_y})",
                "Roles: " + (", ".join(self._role_label(point.kind) for point in points) if points else "no decoded logic role"),
                "Puzzle links: " + (", ".join(f"P{index}" for index in puzzle_links) if puzzle_links else "none"),
                "",
                "Direct role nodes:",
            ]
            if points:
                for point in points:
                    lines.append(f"  {point.label}: {self._role_label(point.kind)}")
            else:
                lines.append("  —")
            lines.extend(["", "Direct graph links:"])
            direct = graph.direct_edges_for_map_item(item.index)
            if direct:
                for edge in direct[:30]:
                    lines.append(f"  {edge.source.label} -> {edge.target.label}: {edge.label}")
            else:
                lines.append("  —")
            return "\n".join(lines)
        if self.selected_logic_point is not None:
            point = self.selected_logic_point
            graph = self.loaded.logic_graph
            puzzles = sorted({
                other.index
                for edge in graph.related_edges_for_point(point, recursive=True)
                for other in (edge.source, edge.target)
                if other.kind == "puzzle" and other.index is not None
            })
            return (
                f"{point.label} ({self._role_label(point.kind)})\n"
                f"Position: ({point.pixel_x}, {point.pixel_y})\n"
                f"Puzzle links: {', '.join(f'P{index}' for index in puzzles) if puzzles else 'none'}"
            )
        return "Select a switch, map item, puzzle record, or logic target to see its unified puzzle-facing roles."

    def _update_puzzle_text(self) -> None:
        if not hasattr(self, "puzzle_text"):
            return
        self.puzzle_text.delete("1.0", tk.END)
        self.puzzle_text.insert("1.0", self._puzzle_text_for_selection())

    def _on_puzzle_entity_selected(self, _event: tk.Event) -> None:
        selection = self.puzzle_tree.selection()
        if not selection or self.loaded is None:
            return
        ref = self.puzzle_refs.get(selection[0])
        if ref is None:
            return
        ref_kind, value = ref
        self._clear_auto_flying_path_overlay()
        if ref_kind == "item":
            assert isinstance(value, MapItemSelection)
            self._select_map_item(value, center=True, status_prefix="Puzzle view selected")
        elif ref_kind == "point":
            assert isinstance(value, LogicPoint)
            self.selected_event_index = None
            self.selected_flying_path_index = None
            self.selected_logic_point = value
            self.selected_enemy_wave = None
            self.selected_map_item = None
            if value.kind not in {"event_effect", "flying_wave", "checkpoint", "guardian", "destroy_type4_offmap"}:
                self.map_canvas.center_on_pixel(value.pixel_x, value.pixel_y)
            self.inspect_var.set(f"Puzzle view selected {value.label} ({value.kind}).")
        self._update_logic_text()
        self._update_entity_properties()
        self._update_puzzle_text()
        self._rerender_loaded()

    def _entity_browser_row(self, entity: IndexedEntity) -> tuple[str, str, str, object]:
        assert self.loaded is not None
        graph = self.loaded.logic_graph
        alfils = self.loaded.alfils_data
        map_data = self.loaded.map_data
        assert graph is not None and alfils is not None

        group = entity.group
        payload = entity.payload
        if group == "Events":
            event = payload
            cells = graph.event_cells.get(event.index, ())
            position = " ".join(f"{x},{y}" for x, y in cells[:2]) if cells else "effect-only"
            if len(cells) > 2:
                position += " …"
            return self._event_action_text(event), position, "event", event.index

        if group == "Puzzles":
            point = payload
            puzzle = map_data.puzzles[int(entity.key.index)]
            detail = self._puzzle_meaning_text(puzzle)
            return detail, self._position_text(point.pixel_x, point.pixel_y), "point", point

        if group == "Switches":
            point = payload
            record = alfils.switches[int(entity.key.index)]
            return self._object_name(record.object_info_index), self._position_text(point.pixel_x, point.pixel_y), "point", point

        if group in {"Teleport table records", "Teleports"}:
            point = payload
            record = alfils.teleports[int(entity.key.index)]
            is_bound = any(
                edge.edge_kind == "teleport_binding" and edge.target.kind == "teleport" and edge.target.index == record.index
                for edge in graph.all_edges
            )
            status = "bound" if is_bound else "unbound / likely stale row"
            detail = f"{status}; srcX={record.src_pixel_x} → dst=({record.normalized_dst_pixel_x},{record.normalized_dst_pixel_y})"
            return detail, self._position_text(point.pixel_x, point.pixel_y), "point", point

        if group in {"Hardcoded teleport destinations", "HC teleports"}:
            point = payload
            record = next(record for record in special_teleport_destinations(self.loaded.resource.level) if record.index == int(entity.key.index))
            offset_text = f"EXE@0x{record.unpacked_game_offset:X}" if record.unpacked_game_offset is not None else "patched special destination"
            detail = f"coded=0x{record.coded:04X}; {offset_text}"
            return detail, self._position_text(record.pixel_x, record.pixel_y), "point", point

        if group in {"Objective locations", "Objectives"}:
            point = payload
            record = next(record for record in objective_locations(self.loaded.resource.level) if record.index == int(entity.key.index))
            detail = f"cell=({record.cell_x},{record.cell_y}); EXE@0x{record.unpacked_game_offset:X}"
            return detail, self._position_text(record.pixel_x, record.pixel_y), "point", point

        if group == "Player start":
            point = payload
            start = player_start_location(self.loaded.resource.level)
            source_note = start.source_note if start is not None else "—"
            pixel_x = start.pixel_x if start is not None else point.pixel_x
            pixel_y = start.pixel_y if start is not None else point.pixel_y
            return source_note, self._position_text(pixel_x, pixel_y), "point", point

        if group == "Hints":
            point = payload
            record = alfils.hints[int(entity.key.index)]
            detail = record.text or "—"
            return detail, f"x={record.pixel_x}", "point", point

        if group == "Trapdoors":
            point = payload
            record = alfils.trapdoors[int(entity.key.index)]
            detail = "opened" if record.is_opened else "closed"
            return detail, self._position_text(point.pixel_x, point.pixel_y), "point", point

        if group == "Moving blocks":
            point = payload
            record = alfils.moving_blocks[int(entity.key.index)]
            detail = f"{record.width_pixels}×{record.height_pixels}px"
            return detail, self._position_text(point.pixel_x, point.pixel_y), "point", point

        if group == "Enemy waves":
            wave = payload
            category = entity.key.variant
            if category in {"WW", "IW"}:
                kind = "walking"
            else:
                kind = "flying"
            if category == "WW":
                prefix = "walking"
            elif category == "IW":
                prefix = "intel walking"
            elif category == "IF":
                prefix = "intel flying"
            else:
                prefix = "flying"
            detail = f"{prefix} ×{wave.enemy_count}"
            if category == "FW":
                if self.loaded.flying_paths is not None:
                    path = self.loaded.flying_paths.get(wave.flying_path_index)
                    path_detail = f", {path.kind}, nodes={len(path.deltas)}" if path is not None else ", path missing"
                else:
                    path_detail = ", .PAT unavailable"
                detail = f"{detail}, path={wave.flying_path_index}{path_detail}"
            detail += f", {self._enemy_summary(wave, kind)}, hp={wave.health}{self._reward_suffix(wave)}"
            position = "trigger-relative" if category == "FW" else self._position_text(entity.pixel_x, entity.pixel_y)
            selection = EnemySelection(category, wave.index, None, entity.pixel_x, entity.pixel_y)
            return detail, position, "wave", selection

        if group == "Flying paths":
            path = payload
            wave_count = sum(1 for wave in alfils.active_flying_waves if wave.flying_path_index == path.index)
            trigger_count = 0
            for event in alfils.active_events:
                if event.event_type_index != 0 or not (0 <= event.param < len(alfils.flying_waves)):
                    continue
                wave = alfils.flying_waves[event.param]
                if wave.flying_path_index == path.index:
                    trigger_count += len(graph.event_cells.get(event.index, ()))
            detail = f"{path.kind}, nodes={len(path.deltas)}, waves={wave_count}, trigger cells={trigger_count}"
            return detail, "path-only", "path", path.index

        if group == "Physical logic targets" or group.startswith("Logic targets:") or group.startswith("Logic:"):
            point = payload
            detail = point.kind.replace("_", " ")
            position = "off-map" if point.kind == "destroy_type4_offmap" else self._position_text(point.pixel_x, point.pixel_y)
            return detail, position, "point", point

        if group == "Map items":
            item = payload
            if item.is_weapon:
                info = self.loaded.weapon_table.get(item.object_or_weapon_info_index - 192) if self.loaded.weapon_table is not None else None
                detail = f"weapon: {info.full_name}" if info is not None else f"weapon {item.object_or_weapon_info_index - 192}"
            else:
                info = self.loaded.object_table.get(item.object_or_weapon_info_index) if self.loaded.object_table is not None else None
                detail = f"{info.type_name}: {info.full_name}" if info is not None else f"object {item.object_or_weapon_info_index}"
            return detail, self._position_text(item.pixel_x, item.pixel_y), "item", MapItemSelection(item.index)

        return entity.key.display(), self._position_text(entity.pixel_x, entity.pixel_y), entity.selection_kind, payload

    def _ref_for_logic_point(self, point: LogicPoint) -> tuple[str, object] | None:
        if self.loaded is None or self.loaded.logic_graph is None:
            return None
        graph = self.loaded.logic_graph
        if point.kind in {"event_cell", "event_effect"} and point.index is not None:
            return ("event", point.index)
        if point.kind == "puzzle" and point.index is not None:
            canonical = graph.point_for_puzzle(point.index)
            return ("point", canonical or point)
        if point.kind == "switch" and point.index is not None:
            canonical = graph.point_for_switch(point.index)
            return ("point", canonical or point)
        if point.kind in {
            "map_item",
            "switch_item",
            "teleport_stone",
            "map_object_source",
            "map_weapon_source",
            "destructable_object",
        } and point.index is not None:
            return ("item", MapItemSelection(point.index))
        if point.kind == "walking_wave" and point.index is not None and self.loaded.alfils_data is not None:
            wave = self.loaded.alfils_data.walking_waves[point.index]
            return ("wave", EnemySelection("WW", point.index, None, wave.pixel_x, wave.pixel_y))
        if point.kind == "intel_walking_wave" and point.index is not None and self.loaded.alfils_data is not None:
            wave = self.loaded.alfils_data.intel_walking_waves[point.index]
            return ("wave", EnemySelection("IW", point.index, None, wave.pixel_x, wave.pixel_y))
        if point.kind == "intel_flying_wave" and point.index is not None and self.loaded.alfils_data is not None:
            wave = self.loaded.alfils_data.intel_flying_waves[point.index]
            return ("wave", EnemySelection("IF", point.index, None, wave.pixel_x, wave.pixel_y))
        return ("point", point)

    @staticmethod
    def _dedupe_edges(edges) -> tuple:
        selected = []
        seen: set[int] = set()
        for edge in edges:
            edge_id = id(edge)
            if edge_id in seen:
                continue
            seen.add(edge_id)
            selected.append(edge)
        return tuple(selected)

    def _direct_edges_for_event_highlight(self, event_index: int) -> tuple:
        assert self.loaded is not None and self.loaded.logic_graph is not None
        graph = self.loaded.logic_graph
        return self._dedupe_edges(graph.outgoing_edges_for_event(event_index) + graph.incoming_edges_for_event(event_index))

    def _one_hop_edges_for_event_highlight(self, event_index: int) -> tuple:
        assert self.loaded is not None and self.loaded.logic_graph is not None
        graph = self.loaded.logic_graph
        edges = list(self._direct_edges_for_event_highlight(event_index))
        for edge in tuple(edges):
            for point in (edge.source, edge.target):
                if point.kind == "event_cell" and point.index == event_index:
                    continue
                edges.extend(graph.direct_edges_for_point(point))
        return self._dedupe_edges(edges)

    def _one_hop_edges_for_point_highlight(self, point: LogicPoint) -> tuple:
        assert self.loaded is not None and self.loaded.logic_graph is not None
        graph = self.loaded.logic_graph
        edges = list(graph.direct_edges_for_point(point))
        for edge in tuple(edges):
            other = edge.target if graph._same_graph_node(edge.source, point) else edge.source
            edges.extend(graph.direct_edges_for_point(other))
        return self._dedupe_edges(edges)

    def _highlight_edges_for_event(self, event_index: int) -> tuple:
        assert self.loaded is not None and self.loaded.logic_graph is not None
        graph = self.loaded.logic_graph
        scope = self.logic_link_scope_var.get()
        if scope == "full":
            return graph.related_edges_for_event(event_index, recursive=True)
        if scope == "one_hop":
            return self._one_hop_edges_for_event_highlight(event_index)
        return self._direct_edges_for_event_highlight(event_index)

    def _highlight_edges_for_point(self, point: LogicPoint) -> tuple:
        assert self.loaded is not None and self.loaded.logic_graph is not None
        graph = self.loaded.logic_graph
        scope = self.logic_link_scope_var.get()
        if scope == "full":
            return graph.related_edges_for_point(point, recursive=True)
        if scope == "one_hop":
            return self._one_hop_edges_for_point_highlight(point)
        return graph.direct_edges_for_point(point)

    def _related_entity_refs_for_selection(self) -> set[tuple[str, object]]:
        if self.loaded is None or self.loaded.logic_graph is None:
            return set()
        graph = self.loaded.logic_graph
        refs: set[tuple[str, object]] = set()
        edges = ()
        if self.selected_event_index is not None:
            refs.add(("event", self.selected_event_index))
            edges = self._highlight_edges_for_event(self.selected_event_index)
        elif self.selected_map_item is not None:
            refs.add(("item", self.selected_map_item))
            points = graph.points_for_map_item(self.selected_map_item.item_index)
            if self.logic_link_scope_var.get() == "full":
                edges = graph.related_edges_for_map_item(self.selected_map_item.item_index, recursive=True)
            else:
                edge_groups = [self._highlight_edges_for_point(point) for point in points]
                edges = self._dedupe_edges(edge for group in edge_groups for edge in group)
        elif self.selected_logic_point is not None:
            ref = self._ref_for_logic_point(self.selected_logic_point)
            if ref is not None:
                refs.add(ref)
            edges = self._highlight_edges_for_point(self.selected_logic_point)
        elif self.selected_enemy_wave is not None:
            refs.add(("wave", self.selected_enemy_wave))
        elif self.selected_flying_path_index is not None:
            refs.add(("path", self.selected_flying_path_index))

        for edge in edges:
            for point in (edge.source, edge.target):
                ref = self._ref_for_logic_point(point)
                if ref is not None:
                    refs.add(ref)
        return refs

    def _update_entity_tree_highlight(self) -> None:
        if not hasattr(self, "entity_group_stack"):
            return
        related = self._related_entity_refs_for_selection()
        for item_id, ref in self.entity_refs.items():
            tags = ("related",) if ref in related else ()
            for tree in self.entity_trees.values():
                if tree.exists(item_id):
                    tree.item(item_id, tags=tags)
                    break
        self._update_context_tree(related)

    def _update_context_tree(self, related: set[tuple[str, object]] | None = None) -> None:
        if not hasattr(self, "context_tree"):
            return
        related = self._related_entity_refs_for_selection() if related is None else related
        self.context_tree.delete(*self.context_tree.get_children())
        self.context_refs.clear()
        if hasattr(self, "context_property_tree"):
            self.context_property_tree.delete(*self.context_property_tree.get_children())
        if not related:
            self.context_tree.insert("", tk.END, text="No selection", values=("", "Select an entity to see nearby context", ""))
            if hasattr(self, "context_property_tree"):
                self.context_property_tree.insert("", tk.END, text="Selection", values=("None",))
            return

        ordered_refs = [ref for ref in self.entity_rows_by_ref if ref in related]
        for ref in ordered_refs:
            label, group, detail, position = self.entity_rows_by_ref[ref]
            iid = f"context:{len(self.context_refs)}"
            self.context_tree.insert("", tk.END, iid=iid, text=label, values=(group, detail, position))
            self.context_refs[iid] = ref

    def _on_context_selected(self, _event: tk.Event) -> None:
        if not hasattr(self, "context_property_tree"):
            return
        selection = self.context_tree.selection()
        if not selection:
            return
        ref = self.context_refs.get(selection[0])
        if ref is None:
            self.context_property_tree.delete(*self.context_property_tree.get_children())
            self.context_property_tree.insert("", tk.END, text="Selection", values=("None",))
            return
        self._populate_properties_tree_for_ref(self.context_property_tree, ref)

    def _on_context_activated(self, event: tk.Event) -> None:
        self._on_entity_selected(event)

    def _on_browser_entity_selected(self, event: tk.Event) -> None:
        tree = event.widget
        if not isinstance(tree, ttk.Treeview):
            return
        selection = tree.selection()
        if not selection:
            return
        ref = self.entity_refs.get(selection[0])
        if ref is None:
            self.property_tree.delete(*self.property_tree.get_children())
            self.property_tree.insert("", tk.END, text="Selection", values=("None",))
            return
        self._populate_properties_tree_for_ref(self.property_tree, ref)

    def _on_entity_selected(self, _event: tk.Event) -> None:
        tree = _event.widget
        if not isinstance(tree, ttk.Treeview):
            return
        selection = tree.selection()
        if not selection or self.loaded is None:
            return
        ref = self.entity_refs.get(selection[0]) or self.context_refs.get(selection[0])
        if ref is None:
            return
        ref_kind, value = ref
        if ref_kind == "event":
            self._clear_auto_flying_path_overlay()
            event_index = int(value)
            self.selected_event_index = event_index
            self.selected_flying_path_index = None
            self.selected_logic_point = None
            self.selected_enemy_wave = None
            self.selected_map_item = None
            point = self.loaded.logic_graph.preferred_event_point(event_index) if self.loaded.logic_graph is not None else None
            if point is not None:
                self.map_canvas.center_on_pixel(point.pixel_x, point.pixel_y)
            self.inspect_var.set(f"Entity browser selected event E{event_index}.")
        elif ref_kind == "path":
            path_index = int(value)
            self.selected_event_index = None
            self.selected_logic_point = None
            self.selected_enemy_wave = None
            self.selected_map_item = None
            self.selected_flying_path_index = path_index
            if not self.show_flying_paths_var.get():
                self.show_flying_paths_var.set(True)
                self._auto_enabled_flying_paths = True
            if self.loaded.alfils_data is not None and self.loaded.logic_graph is not None:
                centered = False
                for event in self.loaded.alfils_data.active_events:
                    if event.event_type_index != 0 or not (0 <= event.param < len(self.loaded.alfils_data.flying_waves)):
                        continue
                    wave = self.loaded.alfils_data.flying_waves[event.param]
                    if wave.flying_path_index != path_index:
                        continue
                    point = self.loaded.logic_graph.preferred_event_point(event.index)
                    if point is not None:
                        self.map_canvas.center_on_pixel(point.pixel_x, point.pixel_y)
                        centered = True
                        break
                if not centered:
                    self.map_canvas.center_on_pixel(0, 0)
            self.inspect_var.set(f"Entity browser selected flying path FP{path_index}.")
        elif ref_kind == "wave":
            self._clear_auto_flying_path_overlay()
            selection = value
            assert isinstance(selection, EnemySelection)
            self._select_enemy_wave(selection, center=True, status_prefix="Entity browser selected")
        elif ref_kind == "item":
            self._clear_auto_flying_path_overlay()
            selection = value
            assert isinstance(selection, MapItemSelection)
            self._select_map_item(selection, center=True, status_prefix="Entity browser selected")
        else:
            self._clear_auto_flying_path_overlay()
            point = value
            assert isinstance(point, LogicPoint)
            self.selected_event_index = None
            self.selected_flying_path_index = None
            self.selected_logic_point = point
            self.selected_enemy_wave = None
            self.selected_map_item = None
            if point.kind not in {"event_effect", "flying_wave", "checkpoint", "guardian", "destroy_type4_offmap"}:
                self.map_canvas.center_on_pixel(point.pixel_x, point.pixel_y)
            self.inspect_var.set(f"Entity browser selected {point.label} ({point.kind}).")
        self._update_logic_text()
        self._update_entity_properties()
        self._update_puzzle_text()
        self._update_entity_tree_highlight()
        self._rerender_loaded()


    def _sync_entity_browser_to_selection(self) -> None:
        target: tuple[str, object] | None = None
        if self.selected_map_item is not None:
            target = ("item", self.selected_map_item)
        elif self.selected_enemy_wave is not None:
            target = ("wave", self.selected_enemy_wave)
        elif self.selected_logic_point is not None:
            target = ("point", self.selected_logic_point)
        elif self.selected_event_index is not None:
            target = ("event", self.selected_event_index)
        elif self.selected_flying_path_index is not None:
            target = ("path", self.selected_flying_path_index)
        if target is None:
            return
        for item_id, ref in self.entity_refs.items():
            if ref == target:
                for tree in self.entity_trees.values():
                    if not tree.exists(item_id):
                        continue
                    tree.selection_set(item_id)
                    tree.focus(item_id)
                    tree.see(item_id)
                    for group, group_tree in self.entity_trees.items():
                        if group_tree is tree:
                            self._show_entity_group(group)
                            break
                    break
                break

    def _on_map_double_clicked(self, image_x: int, image_y: int) -> None:
        self._on_map_clicked(image_x, image_y)
        self._sync_entity_browser_to_selection()

    def _on_map_clicked(self, image_x: int, image_y: int) -> None:
        if self.loaded is None:
            return
        if image_x < 0 or image_y < 0:
            return
        cell_x = image_x // MAP_CELL_WIDTH
        cell_y = image_y // MAP_CELL_HEIGHT
        if not (0 <= cell_x < 128 and 0 <= cell_y < 64):
            return
        map_data = self.loaded.map_data
        a = map_data.layer_a_at(cell_x, cell_y)
        b = map_data.layer_b_at(cell_x, cell_y)
        event_text = ""
        logic_point_text = ""
        selected_changed = False
        enemy_hit = self._pick_enemy_wave(image_x, image_y)
        if enemy_hit is not None:
            self._select_enemy_wave(enemy_hit, center=False, status_prefix="Map selected")
            selected_changed = True
            enemy_text = f", enemy {enemy_hit.category}{enemy_hit.wave_index}"
            if enemy_hit.event_index is not None:
                enemy_text += f" via E{enemy_hit.event_index}"
            self.inspect_var.set(
                f"Pixel ({image_x}, {image_y}) → cell ({cell_x}, {cell_y}): "
                f"Layer A tile {a}, Layer B value {b}{enemy_text}."
            )
            self._update_logic_text()
            self._rerender_loaded()
            return
        item_hit = self._pick_map_item(image_x, image_y)
        if item_hit is not None:
            raw_item = self._map_item_for_selection(item_hit)
            self._select_map_item(item_hit, center=False, status_prefix="Map selected")
            item_label = f"I{item_hit.item_index}"
            if raw_item is not None:
                item_label += " weapon" if raw_item.is_weapon else " object"
            self.inspect_var.set(
                f"Pixel ({image_x}, {image_y}) → cell ({cell_x}, {cell_y}): "
                f"Layer A tile {a}, Layer B value {b}, map item {item_label}."
            )
            self._update_logic_text()
            self._rerender_loaded()
            return
        if b >= 3:
            event_index = b - 3
            event = self.loaded.alfils_data.event(event_index) if self.loaded.alfils_data is not None else None
            if event is None:
                event_text = f", event index {event_index}"
            else:
                event_text = f", event {event_index}: {self._event_action_text(event)}"
            if self.loaded.logic_graph is not None and (self.selected_event_index != event_index or self.selected_logic_point is not None):
                self._clear_auto_flying_path_overlay()
                self.selected_event_index = event_index
                self.selected_flying_path_index = None
                self.selected_logic_point = None
                self.selected_enemy_wave = None
                self.selected_map_item = None
                selected_changed = True
        elif self.loaded.logic_graph is not None:
            hit_point = self.loaded.logic_graph.pick_point(image_x, image_y)
            if hit_point is not None:
                logic_point_text = f", logic target {hit_point.label} ({hit_point.kind})"
                if self.selected_logic_point != hit_point or self.selected_event_index is not None:
                    self._clear_auto_flying_path_overlay()
                    self.selected_event_index = None
                    self.selected_flying_path_index = None
                    self.selected_logic_point = hit_point
                    self.selected_enemy_wave = None
                    self.selected_map_item = None
                    selected_changed = True
        item_text = ""
        hit_items: list[str] = []
        for item in map_data.active_items:
            sprite = None
            if self.loaded.sprite_bank is not None:
                if item.is_weapon:
                    sprite = self.loaded.sprite_bank.weapon_sprite(item.object_or_weapon_info_index - 192)
                else:
                    sprite = self.loaded.sprite_bank.object_sprite(item.object_or_weapon_info_index)
            width = sprite.width if sprite is not None else 12
            height = sprite.height if sprite is not None else 12
            if item.pixel_x <= image_x < item.pixel_x + width and item.pixel_y <= image_y < item.pixel_y + height:
                if item.is_weapon:
                    info = self.loaded.weapon_table.get(item.object_or_weapon_info_index - 192) if self.loaded.weapon_table is not None else None
                    name = info.full_name if info is not None else f"weapon {item.object_or_weapon_info_index - 192}"
                    hit_items.append(f"I{item.index} weapon: {name}")
                else:
                    info = self.loaded.object_table.get(item.object_or_weapon_info_index) if self.loaded.object_table is not None else None
                    name = info.full_name if info is not None else f"object {item.object_or_weapon_info_index}"
                    type_name = info.type_name if info is not None else "OBJECT"
                    hit_items.append(f"I{item.index} {type_name}: {name}")
        if hit_items:
            item_text = " Items: " + "; ".join(hit_items[:3]) + (" …" if len(hit_items) > 3 else "")
        self.inspect_var.set(
            f"Pixel ({image_x}, {image_y}) → cell ({cell_x}, {cell_y}): "
            f"Layer A tile {a}, Layer B value {b}{event_text}{logic_point_text}.{item_text}"
        )
        if selected_changed:
            self._update_logic_text()
            self._rerender_loaded()
        elif b >= 3 or logic_point_text:
            self._update_logic_text()
