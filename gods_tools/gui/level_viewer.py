from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog
from PIL import Image, ImageTk

from gods_tools.formats.compression import GodsCompressionError, dcl_pack
from gods_tools.formats.alfils import AlfilsData, AlfilsFormatError, EVENT_TYPE_NAMES, parse_alfils_payload, load_packed_alfils
from gods_tools.formats.flying_paths import FlyingPathsData, FlyingPathsFormatError, load_packed_flying_paths
from gods_tools.formats.enemy_info import EnemyInfo, get_enemy_info, iter_enemy_infos
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
from gods_tools.formats.map import GodsMap, MapFormatError, MAP_CELL_HEIGHT, MAP_CELL_WIDTH, parse_map_payload, load_packed_map
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


@dataclass(frozen=True)
class PropertyRow:
    field: str
    value: object
    source: str


@dataclass(frozen=True)
class ConditionParamPresentation:
    summary: str
    rows: tuple[PropertyRow, ...] = ()


@dataclass(frozen=True)
class PropertyEditSpec:
    field: str
    ref: tuple[str, object]
    choices: tuple[str, ...] = ()
    pick: bool = False
    atlas: str | None = None


@dataclass(frozen=True)
class PendingPropertyEdit:
    spec: PropertyEditSpec
    value: str
    label: str


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
        self.edit_ref: tuple[str, object] | None = None
        self.edit_vars: dict[str, tk.StringVar] = {}
        self.property_edit_specs: dict[str, PropertyEditSpec] = {}
        self.pending_pick: PropertyEditSpec | None = None
        self.pending_property_edits: list[PendingPropertyEdit] = []
        self.pending_edit_count_var = tk.StringVar(value="No pending edits")
        self.has_unsaved_changes = False
        self.suppress_next_map_double_click = False
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
        entity_actions = ttk.Frame(entity_frame)
        entity_actions.pack(fill=tk.X, pady=(0, 4))
        self.entity_add_button = ttk.Button(entity_actions, text="Add", command=self._on_entity_add)
        self.entity_add_button.pack(side=tk.LEFT)
        self.entity_add_hint_var = tk.StringVar(value="")
        ttk.Label(entity_actions, textvariable=self.entity_add_hint_var, foreground="#666666").pack(side=tk.LEFT, padx=(6, 0))
        self.entity_group_bar = ttk.Frame(entity_frame)
        self.entity_group_bar.pack(fill=tk.X, pady=(0, 4))
        self.entity_group_bar.bind("<Configure>", lambda _event: self._layout_entity_group_buttons())
        self.entity_group_stack = ttk.Frame(entity_frame)
        self.entity_group_stack.pack(fill=tk.BOTH, expand=True)
        self.entity_related_font = tkfont.Font(font="TkDefaultFont")
        self.entity_related_font.configure(weight="bold")

        property_frame = ttk.LabelFrame(browse_pane, text="Properties", padding=4)
        browse_pane.add(property_frame, weight=1)
        self.path_preview_canvas = tk.Canvas(property_frame, height=110, background="#181818", highlightthickness=1, highlightbackground="#606060")
        self.path_preview_canvas.pack(fill=tk.X, pady=(0, 4))
        self.path_preview_canvas.pack_forget()
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
        self.property_tree.tag_configure("pending_changed", foreground="#a86500")
        self.property_tree.tag_configure("pending_delete", foreground="#b00020")
        self.property_tree.tag_configure("pending_new", foreground="#007a3d")
        self.browser_property_tree = self.property_tree
        prop_scroll = ttk.Scrollbar(property_frame, orient=tk.VERTICAL, command=self.property_tree.yview)
        self.property_tree.configure(yscrollcommand=prop_scroll.set)
        property_actions = ttk.Frame(property_frame)
        property_actions.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        ttk.Label(property_actions, textvariable=self.pending_edit_count_var).pack(side=tk.LEFT)
        ttk.Button(property_actions, text="Apply", command=self.apply_pending_property_edits).pack(side=tk.RIGHT)
        ttk.Button(property_actions, text="Clear", command=self.clear_pending_property_edits).pack(side=tk.RIGHT, padx=(0, 4))
        self.property_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.property_tree.bind("<Double-Button-1>", self._on_property_activated)
        self.property_tree.bind("<Delete>", self._on_property_delete)
        prop_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.edit_frame = ttk.LabelFrame(property_frame, text="Edit", padding=4)
        self.edit_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(4, 0))
        self.edit_frame.pack_forget()

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
            self.clear_pending_property_edits()
            self.has_unsaved_changes = False
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
        self.map_canvas.set_image(self._render_image_with_pending_previews(render_result.image))
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
        return self._reward_text_from_kind_and_index(wave.reward_kind, wave.reward_info_index, raw_value=wave.reward)

    def _walking_wave_reward_text_from_raw(self, reward: int) -> str:
        if reward == 0xFF:
            return "none"
        if reward <= 10:
            return self._reward_text_from_kind_and_index("weapon", reward, raw_value=reward)
        return self._reward_text_from_kind_and_index("object", reward - 11, raw_value=reward)

    def _reward_text_from_kind_and_index(self, kind: str | None, index: int, *, raw_value: int) -> str:
        if kind == "object":
            info = self.loaded.object_table.get(index) if self.loaded is not None and self.loaded.object_table is not None else None
            name = info.full_name if info is not None else f"object {index}"
            return f"object #{index}: {name}"
        if kind == "weapon":
            info = self.loaded.weapon_table.get(index) if self.loaded is not None and self.loaded.weapon_table is not None else None
            name = info.full_name if info is not None else f"weapon {index}"
            return f"weapon #{index}: {name}"
        return f"raw {raw_value}"

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
        tree.tag_configure("pending_changed", foreground="#a86500")
        tree.tag_configure("pending_delete", foreground="#b00020")
        tree.tag_configure("pending_new", foreground="#007a3d")
        scroll = ttk.Scrollbar(frame, orient=tk.VERTICAL, command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        tree.bind("<<TreeviewSelect>>", self._on_browser_entity_selected)
        tree.bind("<Double-Button-1>", self._on_entity_selected)
        tree.bind("<Delete>", self._on_browser_entity_delete)
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
        self._update_entity_add_button()

    def _update_entity_add_button(self) -> None:
        if not hasattr(self, "entity_add_button"):
            return
        group = self.selected_entity_group or ""
        if group == "Map items":
            self.entity_add_button.configure(text="Add item", state=tk.NORMAL)
            self.entity_add_hint_var.set("object/weapon atlas, then pick map")
        elif group == "Events":
            self.entity_add_button.configure(text="Add event", state=tk.NORMAL)
            self.entity_add_hint_var.set("choose type/param, then add trigger cells")
        else:
            self.entity_add_button.configure(text="Add", state=tk.DISABLED)
            self.entity_add_hint_var.set("add is not wired for this category yet")

    def _on_entity_add(self) -> None:
        group = self.selected_entity_group or ""
        if group == "Map items":
            self._ask_add_map_item()
        elif group == "Events":
            self._ask_add_event()
        else:
            self.inspect_var.set("Add is not wired for this category yet.")

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
        ref = (ref_kind, ref_value)
        pending_tag = self._pending_tag_for_ref(ref)
        tags = (pending_tag,) if pending_tag is not None else ()
        tree.insert("", tk.END, iid=iid, text=label, values=(detail, position), tags=tags)
        self.entity_refs[iid] = ref
        group = next((name for name, candidate in self.entity_trees.items() if candidate is tree), "")
        self.entity_rows_by_ref.setdefault(ref, (label, group, detail, position))

    def _pending_tag_for_ref(self, ref: tuple[str, object]) -> str | None:
        ref_kind, ref_value = ref
        for edit in reversed(self.pending_property_edits):
            edit_kind, edit_value = edit.spec.ref
            if ref_kind == "event" and edit_kind == "event" and int(ref_value) == int(edit_value):
                if edit.spec.field == "event_delete":
                    return "pending_delete"
                return "pending_new" if edit.spec.field == "event_create" else "pending_changed"
            if ref_kind == "item" and edit_kind == "item" and isinstance(ref_value, MapItemSelection) and isinstance(edit_value, MapItemSelection):
                if ref_value.item_index == edit_value.item_index:
                    return "pending_changed"
            if ref_kind == "wave" and edit_kind == "wave" and isinstance(ref_value, EnemySelection) and isinstance(edit_value, EnemySelection):
                if ref_value.category == edit_value.category and ref_value.wave_index == edit_value.wave_index:
                    return "pending_changed"
            if ref_kind == "point" and edit_kind == "point" and isinstance(ref_value, LogicPoint) and isinstance(edit_value, LogicPoint):
                if ref_value.kind == edit_value.kind and ref_value.index == edit_value.index:
                    return "pending_changed"
        return None

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

    def _update_entity_properties(self) -> None:
        if not hasattr(self, "property_tree"):
            return
        is_browser_properties = getattr(self, "property_tree", None) is getattr(self, "browser_property_tree", None)
        self.property_tree.delete(*self.property_tree.get_children())
        if is_browser_properties:
            self._set_flying_path_preview(None)
            self._clear_edit_controls()
            self.property_edit_specs.clear()
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
        if is_browser_properties:
            self._clear_edit_controls()

    def _ref_for_current_properties_selection(self) -> tuple[str, object] | None:
        if self.selected_map_item is not None:
            return ("item", self.selected_map_item)
        if self.selected_enemy_wave is not None:
            return ("wave", self.selected_enemy_wave)
        if self.selected_logic_point is not None:
            return ("point", self.selected_logic_point)
        if self.selected_event_index is not None:
            return ("event", self.selected_event_index)
        if self.selected_flying_path_index is not None:
            return ("path", self.selected_flying_path_index)
        return None

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
        elif ref_kind == "item_raw":
            return
        else:
            assert isinstance(value, LogicPoint)
            self.selected_logic_point = value

    def _clear_edit_controls(self) -> None:
        if not hasattr(self, "edit_frame"):
            return
        for child in self.edit_frame.winfo_children():
            child.destroy()
        self.edit_vars.clear()
        self.edit_ref = None
        self.edit_frame.pack_forget()

    def _add_edit_entry(self, row: int, key: str, label: str, value: object) -> None:
        assert hasattr(self, "edit_frame")
        ttk.Label(self.edit_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 4), pady=1)
        var = tk.StringVar(value=str(value))
        self.edit_vars[key] = var
        ttk.Entry(self.edit_frame, textvariable=var, width=22).grid(row=row, column=1, sticky="ew", pady=1)

    def _add_edit_combo(self, row: int, key: str, label: str, value: object, values: list[str]) -> None:
        assert hasattr(self, "edit_frame")
        ttk.Label(self.edit_frame, text=label).grid(row=row, column=0, sticky="w", padx=(0, 4), pady=1)
        var = tk.StringVar(value=str(value))
        self.edit_vars[key] = var
        ttk.Combobox(self.edit_frame, textvariable=var, values=values, state="readonly", width=24).grid(row=row, column=1, sticky="ew", pady=1)

    @staticmethod
    def _choice_index(value: str) -> int:
        return int(value.split(":", 1)[0])

    @staticmethod
    def _parse_cells(text: str) -> tuple[tuple[int, int], ...]:
        cells: list[tuple[int, int]] = []
        for chunk in text.replace(";", " ").split():
            x_text, y_text = chunk.split(",", 1)
            cells.append((int(x_text), int(y_text)))
        return tuple(cells)

    def _update_edit_controls_for_ref(self, ref: tuple[str, object] | None) -> None:
        self._clear_edit_controls()
        if ref is None or self.loaded is None or not hasattr(self, "edit_frame"):
            return
        ref_kind, value = ref
        self.edit_ref = ref
        self.edit_frame.pack(fill=tk.X, pady=(4, 0))
        self.edit_frame.columnconfigure(1, weight=1)
        row = 0
        if ref_kind == "event":
            event_index = int(value)
            event = self.loaded.alfils_data.event(event_index) if self.loaded.alfils_data is not None else None
            if event is None:
                event = self.loaded.alfils_data.events[event_index] if self.loaded.alfils_data is not None and 0 <= event_index < len(self.loaded.alfils_data.events) else None
            if event is None:
                self._clear_edit_controls()
                return
            type_values = ["-1: Unused", *[f"{index}: {name}" for index, name in sorted(EVENT_TYPE_NAMES.items())]]
            self._add_edit_combo(row, "event_type", "Type", f"{event.event_type_index if event.event_type_index is not None else -1}: {event.type_name}", type_values)
            row += 1
            self._add_edit_entry(row, "event_param", "Param", event.param)
            row += 1
            cells = self.loaded.logic_graph.event_cells.get(event_index, ()) if self.loaded.logic_graph is not None else ()
            self._add_edit_entry(row, "event_cells", "Map triggers", "; ".join(f"{x},{y}" for x, y in cells))
            row += 1
        elif ref_kind == "item":
            selection = value
            assert isinstance(selection, MapItemSelection)
            item = self.loaded.map_data.items[selection.item_index]
            self._add_edit_entry(row, "item_x", "X", item.pixel_x)
            row += 1
            self._add_edit_entry(row, "item_y", "Y", item.pixel_y)
            row += 1
            self._add_edit_entry(row, "item_raw_id", "Object/weapon id", item.object_or_weapon_info_index)
            row += 1
        elif ref_kind == "point":
            point = value
            assert isinstance(point, LogicPoint)
            if point.kind != "puzzle" or point.index is None:
                self._clear_edit_controls()
                return
            puzzle = self.loaded.map_data.puzzles[point.index]
            effect_values = [f"{index}: {puzzle_effect_name(index)}" for index in range(15)]
            condition_values = [f"{index}: {condition_type_name(index)}" for index in range(17)]
            self._add_edit_entry(row, "puzzle_x", "X", puzzle.pixel_x)
            row += 1
            self._add_edit_entry(row, "puzzle_y", "Y", puzzle.pixel_y)
            row += 1
            self._add_edit_combo(row, "puzzle_effect_type", "Effect type", f"{puzzle.effect_function_index}: {puzzle_effect_name(puzzle.effect_function_index)}", effect_values)
            row += 1
            self._add_edit_entry(row, "puzzle_effect_param", "Effect param", puzzle.effect_param)
            row += 1
            self._add_edit_combo(row, "puzzle_remove", "Remove after", str(int(puzzle.remove_after_effect)), ["0", "1"])
            row += 1
            for slot in range(3):
                cond_type = puzzle.condition_function_indices[slot]
                self._add_edit_combo(row, f"cond{slot}_type", f"Cond {slot} type", f"{cond_type}: {condition_type_name(cond_type)}", condition_values)
                row += 1
                self._add_edit_entry(row, f"cond{slot}_param", f"Cond {slot} param", puzzle.condition_params[slot])
                row += 1
        else:
            self._clear_edit_controls()
            return
        ttk.Button(self.edit_frame, text="Apply", command=self._apply_edit_controls).grid(row=row, column=0, columnspan=2, sticky="ew", pady=(4, 0))

    def _apply_edit_controls(self) -> None:
        if self.loaded is None or self.edit_ref is None:
            return
        ref_kind, value = self.edit_ref
        try:
            session = EditSession(self.loaded.document)
            if ref_kind == "event":
                event_index = int(value)
                session = session.plan_set_event(
                    event_index,
                    event_type_index=self._choice_index(self.edit_vars["event_type"].get()),
                    param=int(self.edit_vars["event_param"].get()),
                )
                session = session.plan_set_event_trigger_cells(event_index, self._parse_cells(self.edit_vars["event_cells"].get()))
            elif ref_kind == "item":
                selection = value
                assert isinstance(selection, MapItemSelection)
                session = session.plan_set_map_item(
                    selection.item_index,
                    pixel_x=int(self.edit_vars["item_x"].get()),
                    pixel_y=int(self.edit_vars["item_y"].get()),
                    raw_id=int(self.edit_vars["item_raw_id"].get()),
                )
            elif ref_kind == "point":
                point = value
                assert isinstance(point, LogicPoint)
                if point.kind != "puzzle" or point.index is None:
                    return
                session = session.plan_set_puzzle(
                    point.index,
                    condition_types=tuple(self._choice_index(self.edit_vars[f"cond{slot}_type"].get()) for slot in range(3)),  # type: ignore[arg-type]
                    condition_params=tuple(int(self.edit_vars[f"cond{slot}_param"].get()) for slot in range(3)),  # type: ignore[arg-type]
                    pixel_x=int(self.edit_vars["puzzle_x"].get()),
                    pixel_y=int(self.edit_vars["puzzle_y"].get()),
                    effect_type=self._choice_index(self.edit_vars["puzzle_effect_type"].get()),
                    effect_param=int(self.edit_vars["puzzle_effect_param"].get()),
                    remove_after_effect=bool(int(self.edit_vars["puzzle_remove"].get())),
                )
            else:
                return
            self._apply_edit_session(session)
        except (AssertionError, KeyError, ValueError, IndexError, TypeError) as exc:
            messagebox.showerror("GODS entity editor", f"Could not apply edit.\n\n{exc}")

    def _apply_edit_session(self, session: EditSession) -> None:
        assert self.loaded is not None
        document = self.loaded.document
        try:
            map_payload = session.preview_patched_map_payload()
            alfils_payload = session.plan.apply_to_payload("alfils", document.alfils_data.raw_payload) if document.alfils_data is not None else None
            map_data = parse_map_payload(map_payload, document.map_data.source_path, document.map_data.packed_size)
            alfils_data = (
                parse_alfils_payload(alfils_payload, document.alfils_data.source_path, document.alfils_data.packed_size)
                if alfils_payload is not None and document.alfils_data is not None
                else document.alfils_data
            )
            logic_graph = build_logic_graph(map_data, alfils_data, document.object_table, document.weapon_table) if alfils_data is not None else None
            diagnostics = build_level_diagnostics(map_data, alfils_data, logic_graph) if alfils_data is not None and logic_graph is not None else None
            new_document = LevelDocument(
                resource=document.resource,
                map_data=map_data,
                alfils_data=alfils_data,
                object_table=document.object_table,
                weapon_table=document.weapon_table,
                sprite_bank=document.sprite_bank,
                flying_paths=document.flying_paths,
                logic_graph=logic_graph,
                diagnostics=diagnostics,
            )
            render_result = render_level_map(
                map_data,
                document.resource,
                self._build_render_options(),
                alfils_data,
                document.object_table,
                document.weapon_table,
                document.sprite_bank,
                flying_paths=document.flying_paths,
            )
            self.loaded = LoadedLevel(
                document=new_document,
                entity_index=build_entity_index(new_document),
                edit_session=session,
                render_result=render_result,
            )
            if self.selected_logic_point is not None and self.selected_logic_point.kind == "puzzle" and self.selected_logic_point.index is not None and logic_graph is not None:
                self.selected_logic_point = logic_graph.point_for_puzzle(self.selected_logic_point.index) or self.selected_logic_point
        except Exception as exc:
            messagebox.showerror("GODS entity editor", f"Could not rebuild edited level.\n\n{exc}")
            return
        self.map_canvas.set_image(self._render_image_with_pending_previews(self.loaded.render_result.image))
        self.map_canvas.set_overlay(self.loaded.render_result.canvas_overlay)
        self._populate_entity_tree()
        self._populate_puzzle_tree()
        self._update_info()
        self._update_logic_text()
        self._update_edit_prep_text()
        self._update_raw_text()
        self._update_entity_properties()
        self.has_unsaved_changes = True
        self.inspect_var.set(f"Applied {session.patch_count} in-memory edit patch(es).")

    def _on_property_activated(self, event: tk.Event) -> None:
        if event.widget is not getattr(self, "browser_property_tree", None):
            return
        item_id = self.property_tree.identify_row(event.y)
        spec = self.property_edit_specs.get(item_id)
        if spec is None:
            return
        current = self.property_tree.set(item_id, "value")
        if spec.field in {"pending_event_type", "pending_event_param"}:
            value = self._ask_choice("Edit property", self.property_tree.item(item_id, "text"), current, spec.choices) if spec.choices else simpledialog.askstring("Edit property", self.property_tree.item(item_id, "text"), initialvalue=current, parent=self)
            if value is not None:
                self._update_pending_event_edit(spec, value, item_id)
            return
        if spec.pick:
            self._set_pick_mode(spec)
            return
        if spec.atlas is not None:
            value = self._ask_atlas_value(spec.atlas, current)
        elif spec.choices:
            value = self._ask_choice("Edit property", self.property_tree.item(item_id, "text"), current, spec.choices)
        else:
            value = simpledialog.askstring("Edit property", self.property_tree.item(item_id, "text"), initialvalue=current, parent=self)
        if value is None:
            return
        self._queue_property_edit(spec, value, item_id)

    def _ask_add_map_item(self) -> None:
        choice = self._ask_choice("Add map item", "Kind", "object", ("object", "weapon"))
        if choice is None:
            return
        atlas = "object" if choice == "object" else "weapon_raw"
        value = self._ask_atlas_value(atlas, "")
        if value is None:
            return
        self._set_pick_mode(PropertyEditSpec("item_create", ("item_raw", int(value)), pick=True))
        self.inspect_var.set("Pick mode: click the map to place the new item.")

    def _ask_add_event(self) -> None:
        if self.loaded is None or self.loaded.alfils_data is None:
            return
        empty = next((event for event in self.loaded.alfils_data.events if event.event_type_index == 11), None)
        if empty is None:
            messagebox.showinfo("GODS entity editor", "No unused event slot is available.")
            return
        self._queue_property_edit(PropertyEditSpec("event_create", ("event", empty.index)), "2,0")
        self._select_pending_event_row(empty.index)
        self.inspect_var.set(f"Queued new event E{empty.index}. Select the pending row and edit Type/Param in Properties before Apply.")

    def _set_pick_mode(self, spec: PropertyEditSpec) -> None:
        self.pending_pick = spec
        self.map_canvas.set_cursor("crosshair")
        self.bind("<Escape>", self._cancel_pick_mode)
        self.inspect_var.set("Pick mode: click the map to set this value. Press Esc to cancel.")

    def _cancel_pick_mode(self, _event: tk.Event | None = None) -> None:
        self._clear_pick_mode()
        self.inspect_var.set("Pick cancelled.")

    def _clear_pick_mode(self) -> None:
        self.pending_pick = None
        self.map_canvas.set_cursor("")
        self.unbind("<Escape>")

    def _queue_property_edit(self, spec: PropertyEditSpec, value: str, item_id: str | None = None) -> None:
        label = self._pending_edit_label(spec, value)
        self.pending_property_edits.append(PendingPropertyEdit(spec, value, label))
        self._update_pending_edit_state()
        if item_id is not None and self.property_tree.exists(item_id):
            self.property_tree.set(item_id, "value", f"{self._display_value_for_spec(spec, value)} *")
            self._set_pending_tags(self.property_tree, item_id, "pending_delete" if self._is_delete_edit(spec) else "pending_changed")
        if spec.field in {"event_delete", "event_create", "item_create"}:
            self._populate_entity_tree()
        else:
            self._refresh_pending_marks()
        self._update_pending_preview_image()
        self.inspect_var.set(f"Queued edit: {label}. Press Apply to rebuild the level.")

    def _pending_event_create_edit_index(self, event_index: int) -> int | None:
        for index, edit in enumerate(self.pending_property_edits):
            if edit.spec.field == "event_create" and int(edit.spec.ref[1]) == event_index:
                return index
        return None

    def _pending_event_create_state(self, event_index: int) -> tuple[int, int] | None:
        edit_index = self._pending_event_create_edit_index(event_index)
        if edit_index is None:
            return None
        type_text, param_text = self.pending_property_edits[edit_index].value.split(",", 1)
        return int(type_text), int(param_text)

    def _replace_pending_event_create_state(self, event_index: int, event_type: int, param: int) -> None:
        edit_index = self._pending_event_create_edit_index(event_index)
        if edit_index is None:
            return
        edit = self.pending_property_edits[edit_index]
        new_value = f"{event_type},{param}"
        self.pending_property_edits[edit_index] = PendingPropertyEdit(
            edit.spec,
            new_value,
            self._pending_edit_label(edit.spec, new_value),
        )

    def _update_pending_event_edit(self, spec: PropertyEditSpec, value: str, item_id: str | None = None) -> None:
        if spec.ref[0] != "pending_event":
            return
        event_index = int(spec.ref[1])
        state = self._pending_event_create_state(event_index)
        if state is None:
            return

        event_type, param = state
        if spec.field == "pending_event_type":
            event_type = self._choice_index(value)
            param = self._normalise_event_param_for_type(event_type, param)
        elif spec.field == "pending_event_param":
            param = self._parse_event_param_value(event_type, value)
        else:
            return

        self._replace_pending_event_create_state(event_index, event_type, param)
        self._populate_entity_tree()

        # Rebuild the selected pending-event property panel from the canonical queued
        # event_create edit.  Updating only the clicked Treeview row used to write the
        # derived "spawn WW0"/"check P0" effect text into the Type cell and left the
        # context-dependent Param row stale after a type switch.
        self._select_pending_event_row(event_index)

        self._update_pending_edit_state()
        self._update_pending_preview_image()
        self.inspect_var.set(f"Updated pending event E{event_index}. Press Apply to create it.")

    def _parse_event_param_value(self, event_type: int, value: str) -> int:
        text = value.strip()
        if text.isdigit():
            return int(text)
        upper = text.upper()
        prefixes = {
            0: "FW",
            1: "WW",
            2: "P",
            3: "IW",
            4: "IF",
            6: "MB",
            7: "MB",
            8: "MB",
            9: "MB",
            10: "G",
        }
        prefix = prefixes.get(event_type)
        if prefix is not None and upper.startswith(prefix):
            return self._leading_integer(upper[len(prefix):])
        return self._leading_integer(text)

    @staticmethod
    def _is_delete_edit(spec: PropertyEditSpec) -> bool:
        return spec.field == "event_delete" or spec.field.startswith("event_delete_cell:")

    def _pending_edit_label(self, spec: PropertyEditSpec, value: str) -> str:
        ref_kind, ref_value = spec.ref
        if ref_kind == "event":
            if spec.field == "event_create":
                return f"new E{int(ref_value)} = {self._display_value_for_spec(spec, value)}"
            return f"E{int(ref_value)} {spec.field} = {self._display_value_for_spec(spec, value)}"
        if ref_kind == "item_raw":
            return f"new item = {self._display_value_for_spec(spec, value)}"
        if ref_kind == "item" and isinstance(ref_value, MapItemSelection):
            return f"I{ref_value.item_index} {spec.field} = {self._display_value_for_spec(spec, value)}"
        if ref_kind == "wave" and isinstance(ref_value, EnemySelection):
            return f"{ref_value.category}{ref_value.wave_index} {spec.field} = {self._display_value_for_spec(spec, value)}"
        if ref_kind == "point" and isinstance(ref_value, LogicPoint):
            return f"{ref_value.label} {spec.field} = {self._display_value_for_spec(spec, value)}"
        return f"{spec.field} = {self._display_value_for_spec(spec, value)}"

    def _display_value_for_spec(self, spec: PropertyEditSpec, value: str) -> str:
        if spec.atlas == "object":
            return self._object_ref(int(value))
        if spec.atlas == "weapon":
            return self._weapon_ref(int(value))
        if spec.atlas == "weapon_raw":
            return self._weapon_ref(int(value) - 192)
        if spec.atlas == "walking_wave_reward":
            return self._walking_wave_reward_text_from_raw(int(value))
        if spec.atlas is not None and spec.atlas.startswith("enemy_"):
            kind = spec.atlas.split("_", 1)[1]
            info = get_enemy_info(self.loaded.resource.level, kind, int(value)) if self.loaded is not None else None
            return f"EN{value}: {info.display_name if info is not None else 'enemy'}"
        if spec.field == "item_create":
            raw_text, x_text, y_text = value.split(",", 2)
            raw_id = int(raw_text)
            item_name = self._weapon_ref(raw_id - 192) if raw_id >= 192 else self._object_ref(raw_id)
            return f"{item_name} at {x_text},{y_text}"
        if spec.field == "event_create":
            type_text, param_text = value.split(",", 1)
            event_type = int(type_text)
            return self._event_action_text_from_values(event_type, int(param_text))
        if spec.field == "event_delete":
            return "delete event"
        if spec.field.startswith("event_delete_cell:"):
            return "delete cell"
        return value

    def _event_action_text_from_values(self, event_type: int | None, param: int) -> str:
        if self.loaded is not None and self.loaded.alfils_data is not None:
            class _EventPreview:
                index = -1

            preview = _EventPreview()
            preview.event_type_index = event_type
            preview.param = param
            preview.type_name = EVENT_TYPE_NAMES.get(event_type, f"Unknown{event_type}") if event_type is not None else "Unused"

            return self._event_action_text(preview)
        if event_type == 2:
            return f"check P{param}"
        return f"{EVENT_TYPE_NAMES.get(event_type, f'Type {event_type}')} param={param}"

    def _on_property_delete(self, _event: tk.Event) -> str:
        item_ids = self.property_tree.selection()
        if not item_ids:
            return "break"
        spec = self.property_edit_specs.get(item_ids[0])
        if spec is None:
            return "break"
        if spec.field.startswith("event_cell:"):
            index = spec.field.split(":", 1)[1]
            self._queue_property_edit(PropertyEditSpec(f"event_delete_cell:{index}", spec.ref), "", item_ids[0])
        elif spec.field == "event_add_cell":
            self.inspect_var.set("Add cell is only a command row; nothing to delete.")
        else:
            self.inspect_var.set("Delete is only available for removable collection rows here.")
        return "break"

    def _on_browser_entity_delete(self, event: tk.Event) -> str:
        tree = event.widget
        if not isinstance(tree, ttk.Treeview):
            return "break"
        item_ids = tree.selection()
        if not item_ids:
            return "break"
        ref = self.entity_refs.get(item_ids[0])
        if ref is None:
            return "break"
        ref_kind, ref_value = ref
        if ref_kind == "event":
            self._queue_property_edit(PropertyEditSpec("event_delete", ("event", ref_value)), "")
        else:
            self.inspect_var.set("Delete for this entity type is not wired yet.")
        return "break"

    def _update_pending_edit_state(self) -> None:
        count = len(self.pending_property_edits)
        if count == 0:
            self.pending_edit_count_var.set("No pending edits")
        elif count == 1:
            self.pending_edit_count_var.set("1 pending edit")
        else:
            self.pending_edit_count_var.set(f"{count} pending edits")

    def clear_pending_property_edits(self) -> None:
        self.pending_property_edits.clear()
        self._update_pending_edit_state()
        self._populate_entity_tree()
        if self.loaded is not None and getattr(self, "property_tree", None) is getattr(self, "browser_property_tree", None):
            self._update_entity_properties()
        self._update_pending_preview_image()

    def apply_pending_property_edits(self) -> None:
        if not self.pending_property_edits:
            self.inspect_var.set("No pending property edits to apply.")
            return
        edits = tuple(self.pending_property_edits)
        self.pending_property_edits.clear()
        self._update_pending_edit_state()
        applied = 0
        for edit in edits:
            if self._apply_property_edit(edit.spec, edit.value, show_errors=True):
                applied += 1
            else:
                remaining = edits[applied + 1 :]
                self.pending_property_edits.extend(remaining)
                self._update_pending_edit_state()
                return
        self.inspect_var.set(f"Applied {applied} pending property edit(s).")

    def save_current_level(self) -> bool:
        if self.loaded is None:
            messagebox.showinfo("GODS entity editor", "No level is loaded.")
            return False
        if self.pending_property_edits:
            self.apply_pending_property_edits()
            if self.pending_property_edits:
                return False
        if not self.has_unsaved_changes:
            self.inspect_var.set("No applied changes to save.")
            return True
        document = self.loaded.document
        try:
            packed_outputs = [(document.map_data.source_path, dcl_pack(document.map_data.raw_payload))]
            if document.alfils_data is not None:
                packed_outputs.append((document.alfils_data.source_path, dcl_pack(document.alfils_data.raw_payload)))
            for path, packed in packed_outputs:
                self._backup_once(path)
                path.write_bytes(packed)
        except (GodsCompressionError, OSError) as exc:
            messagebox.showerror("GODS entity editor", f"Could not save level files.\n\n{exc}")
            return False
        self.has_unsaved_changes = False
        self.inspect_var.set(f"Saved {document.resource.map_path.name}" + (" and PALFILS." if document.alfils_data is not None else "."))
        return True

    @staticmethod
    def _backup_once(path: Path) -> None:
        backup = path.with_name(f"{path.name}.bak")
        if not backup.exists():
            backup.write_bytes(path.read_bytes())

    def _ask_choice(self, title: str, label: str, current: str, values: tuple[str, ...]) -> str | None:
        dialog = tk.Toplevel(self)
        dialog.title(title)
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        result: dict[str, str | None] = {"value": None}
        ttk.Label(dialog, text=label).pack(anchor="w", padx=8, pady=(8, 2))
        var = tk.StringVar(value=current if current in values else values[0])
        combo = ttk.Combobox(dialog, textvariable=var, values=list(values), state="readonly", width=36)
        combo.pack(fill=tk.X, padx=8, pady=4)
        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=8, pady=(4, 8))
        ttk.Button(buttons, text="Apply", command=lambda: (result.__setitem__("value", var.get()), dialog.destroy())).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(6, 0))
        combo.focus_set()
        self.wait_window(dialog)
        return result["value"]

    def _ask_atlas_value(self, atlas: str, current: str) -> str | None:
        if self.loaded is None:
            return None
        records = self._atlas_records(atlas)
        if not records:
            messagebox.showinfo("GODS entity editor", "No atlas records are available for this value.")
            return None

        dialog = tk.Toplevel(self)
        dialog.title(self._atlas_title(atlas))
        dialog.transient(self.winfo_toplevel())
        dialog.grab_set()
        result: dict[str, str | None] = {"value": None}

        header = ttk.Frame(dialog)
        header.pack(fill=tk.X, padx=8, pady=(8, 4))
        ttk.Label(header, text="Double-click an entry, or select and Apply.").pack(side=tk.LEFT)

        shell = ttk.Frame(dialog)
        shell.pack(fill=tk.BOTH, expand=True, padx=8, pady=4)
        canvas = tk.Canvas(shell, width=620, height=420, background="#202020", highlightthickness=0)
        scrollbar = ttk.Scrollbar(shell, orient=tk.VERTICAL, command=canvas.yview)
        grid = ttk.Frame(canvas)
        grid_window = canvas.create_window((0, 0), window=grid, anchor="nw")
        grid.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda event: (canvas.itemconfigure(grid_window, width=event.width), self._layout_atlas_tiles(grid, event.width)))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        values = {str(edit_value) for edit_value, _title, _subtitle, _sprite in records}
        current_value = self._atlas_current_value(atlas, current)
        selected = tk.StringVar(value=current_value if current_value in values else str(records[0][0]))
        images: list[ImageTk.PhotoImage] = []
        for ordinal, (edit_value, title, subtitle, sprite) in enumerate(records):
            tile = ttk.Frame(grid, padding=4)
            tile.grid(row=0, column=ordinal, sticky="nsew", padx=2, pady=2)
            if sprite is not None:
                scale = max(1, min(4, 48 // max(1, max(sprite.size))))
                preview = sprite.resize((max(1, sprite.width * scale), max(1, sprite.height * scale)), resample=Image.Resampling.NEAREST)
                image = ImageTk.PhotoImage(preview)
                images.append(image)
                image_label = ttk.Label(tile, image=image, anchor="center")
            else:
                image_label = ttk.Label(tile, text="no sprite", anchor="center", width=12)
            image_label.pack(fill=tk.X)
            ttk.Radiobutton(tile, text=title, value=str(edit_value), variable=selected).pack(anchor="w")
            ttk.Label(tile, text=subtitle, width=18, wraplength=118).pack(anchor="w")
            for widget in tile.winfo_children():
                widget.bind("<Double-Button-1>", lambda _event, value=str(edit_value): (result.__setitem__("value", value), dialog.destroy()))
                widget.bind("<Button-1>", lambda _event, value=str(edit_value): selected.set(value))

        buttons = ttk.Frame(dialog)
        buttons.pack(fill=tk.X, padx=8, pady=(4, 8))
        ttk.Button(buttons, text="Apply", command=lambda: (result.__setitem__("value", selected.get()), dialog.destroy())).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.LEFT, padx=(6, 0))
        canvas.bind("<MouseWheel>", lambda event: canvas.yview_scroll(int(-1 * (event.delta / 120)), "units"))
        dialog._atlas_images = images  # type: ignore[attr-defined]
        self.wait_window(dialog)
        return result["value"]

    @staticmethod
    def _layout_atlas_tiles(grid: ttk.Frame, width: int) -> None:
        children = grid.winfo_children()
        if not children:
            return
        tile_width = 132
        columns = max(1, width // tile_width)
        for ordinal, tile in enumerate(children):
            tile.grid_configure(row=ordinal // columns, column=ordinal % columns)

    def _atlas_records(self, atlas: str) -> list[tuple[int, str, str, object | None]]:
        if self.loaded is None:
            return []
        records: list[tuple[int, str, str, object | None]] = []
        if atlas == "object" and self.loaded.object_table is not None:
            for info in self.loaded.object_table.records:
                sprite = self.loaded.sprite_bank.object_sprite(info.index) if self.loaded.sprite_bank is not None else None
                records.append((info.index, f"OBJ{info.index}", info.full_name, sprite))
        elif atlas in {"weapon", "weapon_raw"} and self.loaded.weapon_table is not None:
            for info in self.loaded.weapon_table.records:
                edit_value = info.index + 192 if atlas == "weapon_raw" else info.index
                sprite = self.loaded.sprite_bank.weapon_sprite(info.index) if self.loaded.sprite_bank is not None else None
                records.append((edit_value, f"WPN{info.index}", info.full_name, sprite))
        elif atlas == "walking_wave_reward":
            records.append((0xFF, "None", "No reward", None))
            if self.loaded.weapon_table is not None:
                for info in self.loaded.weapon_table.records:
                    # Walking-wave reward bytes 0..10 encode weapons directly.
                    if info.index > 10:
                        continue
                    sprite = self.loaded.sprite_bank.weapon_sprite(info.index) if self.loaded.sprite_bank is not None else None
                    records.append((info.index, f"WPN{info.index}", f"Weapon reward: {info.full_name}", sprite))
            if self.loaded.object_table is not None:
                for info in self.loaded.object_table.records:
                    # Object rewards are stored as object_info_index + 11; 0xFF is reserved for None.
                    raw_reward = info.index + 11
                    if raw_reward >= 0xFF:
                        continue
                    sprite = self.loaded.sprite_bank.object_sprite(info.index) if self.loaded.sprite_bank is not None else None
                    records.append((raw_reward, f"OBJ{info.index}", f"Object reward: {info.full_name}", sprite))
        elif atlas.startswith("enemy_"):
            kind = atlas.split("_", 1)[1]
            for info in iter_enemy_infos(self.loaded.resource.level, kind):
                sprite = self.loaded.sprite_bank.sprite(info.sprite_index_for_facing(0)) if self.loaded.sprite_bank is not None else None
                records.append((info.index, f"EN{info.index}", f"{info.display_name}, {info.action_type}", sprite))
        return records

    @staticmethod
    def _atlas_title(atlas: str) -> str:
        if atlas == "object":
            return "Object atlas"
        if atlas in {"weapon", "weapon_raw"}:
            return "Weapon atlas"
        if atlas == "walking_wave_reward":
            return "Enemy-wave reward atlas"
        if atlas.startswith("enemy_"):
            return "Enemy atlas"
        return "Atlas"

    @staticmethod
    def _atlas_current_value(atlas: str, current: str) -> str:
        text = current.strip()
        if text.isdigit():
            return text
        if atlas == "object" and text.startswith("OBJ"):
            return LevelViewer._leading_integer(text[3:])
        if atlas in {"weapon", "weapon_raw"} and text.startswith("WPN"):
            index = LevelViewer._leading_integer(text[3:])
            return str(index + 192 if atlas == "weapon_raw" else index)
        if atlas == "walking_wave_reward":
            lower = text.lower()
            if lower == "none":
                return str(0xFF)
            if lower.startswith("weapon #"):
                return str(LevelViewer._leading_integer(text.split("#", 1)[1]))
            if lower.startswith("object #"):
                return str(LevelViewer._leading_integer(text.split("#", 1)[1]) + 11)
        return text

    @staticmethod
    def _leading_integer(text: str) -> int:
        digits = []
        for char in text.lstrip():
            if not char.isdigit():
                break
            digits.append(char)
        if not digits:
            raise ValueError(f"Expected numeric id in {text!r}.")
        return int("".join(digits))

    def _apply_property_edit(self, spec: PropertyEditSpec, value: str, *, show_errors: bool = False) -> bool:
        if self.loaded is None:
            return False
        ref_kind, ref_value = spec.ref
        session = EditSession(self.loaded.document)
        try:
            if ref_kind == "event":
                event_index = int(ref_value)
                event = self.loaded.alfils_data.events[event_index]
                event_type = event.event_type_index if event.event_type_index is not None else -1
                param = event.param
                if spec.field == "event_create":
                    type_text, param_text = value.split(",", 1)
                    session = session.plan_set_event(event_index, event_type_index=int(type_text), param=int(param_text))
                    self._apply_edit_session(session)
                    return True
                if spec.field == "event_delete":
                    session = session.plan_set_event(event_index, event_type_index=11, param=0)
                    session = session.plan_set_event_trigger_cells(event_index, ())
                    self._apply_edit_session(session)
                    return True
                if spec.field == "event_type":
                    event_type = self._choice_index(value)
                elif spec.field == "event_param":
                    param = self._parse_event_param_value(event_type, value)
                elif spec.field.startswith("event_cell:"):
                    cells = list(self.loaded.logic_graph.event_cells.get(event_index, ())) if self.loaded.logic_graph is not None else []
                    cell_index = int(spec.field.split(":", 1)[1])
                    if not 0 <= cell_index < len(cells):
                        raise IndexError(f"Event trigger cell index {cell_index} is out of range.")
                    cells[cell_index] = self._parse_cell(value)
                    session = session.plan_set_event_trigger_cells(event_index, tuple(cells))
                    self._apply_edit_session(session)
                    return True
                elif spec.field.startswith("event_delete_cell:"):
                    cells = list(self.loaded.logic_graph.event_cells.get(event_index, ())) if self.loaded.logic_graph is not None else []
                    cell_index = int(spec.field.split(":", 1)[1])
                    if not 0 <= cell_index < len(cells):
                        raise IndexError(f"Event trigger cell index {cell_index} is out of range.")
                    del cells[cell_index]
                    session = session.plan_set_event_trigger_cells(event_index, tuple(cells))
                    self._apply_edit_session(session)
                    return True
                elif spec.field == "event_add_cell":
                    cells = list(self.loaded.logic_graph.event_cells.get(event_index, ())) if self.loaded.logic_graph is not None else []
                    cell = self._parse_cell(value)
                    if cell not in cells:
                        cells.append(cell)
                    session = session.plan_set_event_trigger_cells(event_index, tuple(cells))
                    self._apply_edit_session(session)
                    return True
                else:
                    return False
                session = session.plan_set_event(event_index, event_type_index=event_type, param=param)
            elif ref_kind == "item":
                selection = ref_value
                assert isinstance(selection, MapItemSelection)
                item = self.loaded.map_data.items[selection.item_index]
                x, y, raw_id = item.pixel_x, item.pixel_y, item.object_or_weapon_info_index
                if spec.field == "item_position":
                    x, y = self._parse_position(value)
                elif spec.field == "item_raw_id":
                    raw_id = int(value)
                else:
                    return False
                session = session.plan_set_map_item(selection.item_index, pixel_x=x, pixel_y=y, raw_id=raw_id)
                session = self._plan_bound_switch_move(session, item, x, y, raw_id)
            elif ref_kind == "item_raw":
                raw_text, x_text, y_text = value.split(",", 2)
                empty = next((item for item in self.loaded.map_data.items if item.is_empty), None)
                if empty is None:
                    raise ValueError("No empty map item slot is available.")
                session = session.plan_set_map_item(empty.index, pixel_x=int(x_text), pixel_y=int(y_text), raw_id=int(raw_text))
            elif ref_kind == "wave":
                selection = ref_value
                assert isinstance(selection, EnemySelection)
                if selection.category != "WW":
                    return False
                wave = self.loaded.alfils_data.walking_waves[selection.wave_index] if self.loaded.alfils_data is not None else None
                if wave is None:
                    return False
                fields = {
                    "pixel_x": wave.pixel_x,
                    "pixel_y": wave.pixel_y,
                    "facing": wave.facing,
                    "function_index_unknown": wave.function_index_unknown,
                    "spawn_delay": wave.spawn_delay,
                    "enemy_count": wave.enemy_count,
                    "health": wave.health,
                    "enemy_info_index": wave.enemy_info_index,
                    "missile_type": wave.missile_type,
                    "speed_value": wave.speed_value,
                    "reward": wave.reward,
                    "padding": wave.padding,
                }
                if spec.field == "wave_position":
                    fields["pixel_x"], fields["pixel_y"] = self._parse_position(value)
                elif spec.field == "wave_enemy_info":
                    fields["enemy_info_index"] = int(value)
                elif spec.field == "wave_facing":
                    fields["facing"] = int(value)
                elif spec.field == "wave_function":
                    fields["function_index_unknown"] = int(value)
                elif spec.field == "wave_spawn_delay":
                    fields["spawn_delay"] = int(value)
                elif spec.field == "wave_enemy_count":
                    fields["enemy_count"] = int(value)
                elif spec.field == "wave_health":
                    fields["health"] = int(value)
                elif spec.field == "wave_missile_type":
                    fields["missile_type"] = int(value)
                elif spec.field == "wave_speed":
                    fields["speed_value"] = int(value)
                elif spec.field == "wave_reward":
                    fields["reward"] = int(value)
                else:
                    return False
                session = session.plan_set_walking_wave(selection.wave_index, **fields)
            elif ref_kind == "point":
                point = ref_value
                assert isinstance(point, LogicPoint)
                if point.kind == "switch" and point.index is not None:
                    switch = self.loaded.alfils_data.switches[point.index] if self.loaded.alfils_data is not None else None
                    if switch is None:
                        return False
                    pixel_x, pixel_y = switch.pixel_x, switch.pixel_y
                    object_info_index = switch.object_info_index
                    if spec.field == "switch_position":
                        pixel_x, pixel_y = self._parse_position(value)
                    elif spec.field == "switch_object":
                        object_info_index = int(value)
                    else:
                        return False
                    session = session.plan_set_switch(point.index, pixel_x=pixel_x, pixel_y=pixel_y, object_info_index=object_info_index)
                    self._apply_edit_session(session)
                    return True
                if point.kind == "destructable_object" and point.index is not None:
                    if not 0 <= point.index < len(self.loaded.map_data.items):
                        return False
                    item = self.loaded.map_data.items[point.index]
                    if not item.is_object:
                        return False
                    pixel_x, pixel_y = item.pixel_x, item.pixel_y
                    raw_id = item.object_or_weapon_info_index
                    if spec.field == "destructible_position":
                        pixel_x, pixel_y = self._parse_position(value)
                    elif spec.field == "destructible_object":
                        raw_id = int(value)
                    else:
                        return False
                    session = session.plan_set_map_item(item.index, pixel_x=pixel_x, pixel_y=pixel_y, raw_id=raw_id)
                    self._apply_edit_session(session)
                    return True
                if point.kind != "puzzle" or point.index is None:
                    return False
                puzzle = self.loaded.map_data.puzzles[point.index]
                cond_types = list(puzzle.condition_function_indices)
                cond_params = list(puzzle.condition_params)
                pixel_x, pixel_y = puzzle.pixel_x, puzzle.pixel_y
                effect_type, effect_param = puzzle.effect_function_index, puzzle.effect_param
                remove = puzzle.remove_after_effect
                if spec.field == "puzzle_position":
                    pixel_x, pixel_y = self._parse_position(value)
                elif spec.field == "puzzle_effect_type":
                    effect_type = self._choice_index(value)
                elif spec.field == "puzzle_effect_param":
                    effect_param = int(value)
                elif spec.field == "puzzle_remove":
                    remove = bool(int(value))
                elif spec.field.startswith("cond") and spec.field.endswith("_type"):
                    slot = int(spec.field[4])
                    cond_types[slot] = self._choice_index(value)
                elif spec.field.startswith("cond") and spec.field.endswith("_param"):
                    slot = int(spec.field[4])
                    cond_params[slot] = int(value)
                else:
                    return False
                session = session.plan_set_puzzle(
                    point.index,
                    condition_types=tuple(cond_types),  # type: ignore[arg-type]
                    condition_params=tuple(cond_params),  # type: ignore[arg-type]
                    pixel_x=pixel_x,
                    pixel_y=pixel_y,
                    effect_type=effect_type,
                    effect_param=effect_param,
                    remove_after_effect=remove,
                )
            else:
                return False
            self._apply_edit_session(session)
            return True
        except (AssertionError, ValueError, IndexError, TypeError) as exc:
            if show_errors:
                messagebox.showerror("GODS entity editor", f"Could not edit property.\n\n{exc}")
            return False

    def _plan_bound_switch_move(self, session: EditSession, item, pixel_x: int, pixel_y: int, raw_id: int) -> EditSession:
        if self.loaded is None or self.loaded.alfils_data is None or not item.is_object:
            return session
        for switch in self.loaded.alfils_data.active_switches:
            if switch.pixel_x == item.pixel_x and switch.pixel_y == item.pixel_y and switch.object_info_index == item.object_or_weapon_info_index:
                return session.plan_set_switch(switch.index, pixel_x=pixel_x, pixel_y=pixel_y, object_info_index=raw_id)
        return session

    def _update_pending_preview_image(self) -> None:
        if self.loaded is None:
            return
        self.map_canvas.set_image(self._render_image_with_pending_previews(self.loaded.render_result.image))

    def _render_image_with_pending_previews(self, base_image):
        if self.loaded is None or self.loaded.sprite_bank is None or not self.pending_property_edits:
            return base_image
        preview = base_image.copy().convert("RGBA")
        for edit in self.pending_property_edits:
            sprite = None
            x_y: tuple[int, int] | None = None
            raw_id: int | None = None
            if edit.spec.field == "item_position" and edit.spec.ref[0] == "item" and isinstance(edit.spec.ref[1], MapItemSelection):
                item = self._map_item_for_selection(edit.spec.ref[1])
                if item is None:
                    continue
                raw_id = item.object_or_weapon_info_index
                x_y = self._parse_position(edit.value)
            elif edit.spec.field == "destructible_position" and edit.spec.ref[0] == "point" and isinstance(edit.spec.ref[1], LogicPoint):
                point = edit.spec.ref[1]
                if point.index is None or not 0 <= point.index < len(self.loaded.map_data.items):
                    continue
                item = self.loaded.map_data.items[point.index]
                if not item.is_object:
                    continue
                raw_id = item.object_or_weapon_info_index
                x_y = self._parse_position(edit.value)
            elif edit.spec.field == "item_create":
                raw_text, x_text, y_text = edit.value.split(",", 2)
                raw_id = int(raw_text)
                x_y = (int(x_text), int(y_text))
            if raw_id is None or x_y is None:
                continue
            if raw_id >= 192:
                sprite = self.loaded.sprite_bank.weapon_sprite(raw_id - 192)
            else:
                sprite = self.loaded.sprite_bank.object_sprite(raw_id)
            if sprite is None:
                continue
            preview.alpha_composite(sprite, x_y)
        return preview

    @staticmethod
    def _parse_position(value: str) -> tuple[int, int]:
        x_text, y_text = value.replace(" ", "").split(",", 1)
        return int(x_text), int(y_text)

    @staticmethod
    def _parse_cell(value: str) -> tuple[int, int]:
        x, y = LevelViewer._parse_position(value)
        return x, y

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

    def _insert_property(self, parent: str, field: str, value: object, source: str, *, open: bool = True, edit: PropertyEditSpec | None = None) -> str:
        iid = self.property_tree.insert(parent, tk.END, text=field, values=(str(value),), open=open)
        if edit is not None and getattr(self, "property_tree", None) is getattr(self, "browser_property_tree", None):
            self.property_edit_specs[iid] = edit
            self.property_tree.item(iid, tags=("editable",))
            self.property_tree.tag_configure("editable", foreground="#005bbb")
            pending = self._pending_edit_for_spec(edit)
            if pending is not None:
                self.property_tree.set(iid, "value", f"{self._display_value_for_spec(pending.spec, pending.value)} *")
                self._set_pending_tags(self.property_tree, iid, "pending_delete" if self._is_delete_edit(pending.spec) else "pending_changed")
        return iid

    def _pending_edit_for_spec(self, spec: PropertyEditSpec) -> PendingPropertyEdit | None:
        for edit in reversed(self.pending_property_edits):
            if edit.spec.ref != spec.ref:
                continue
            if edit.spec.field == spec.field:
                return edit
            if spec.field.startswith("event_cell:") and edit.spec.field == f"event_delete_cell:{spec.field.split(':', 1)[1]}":
                return edit
            if edit.spec.field == "event_delete":
                return edit
        return None

    def _set_pending_tags(self, tree: ttk.Treeview, iid: str, tag: str | None) -> None:
        tags = [existing for existing in tree.item(iid, "tags") if existing not in {"pending_changed", "pending_delete", "pending_new"}]
        if tag is not None:
            tags.append(tag)
        tree.item(iid, tags=tuple(tags))

    def _refresh_pending_marks(self) -> None:
        for tree in self.entity_trees.values():
            for iid, ref in self.entity_refs.items():
                if tree.exists(iid):
                    self._set_pending_tags(tree, iid, self._pending_tag_for_ref(ref))

    def _insert_property_rows(self, parent: str, rows: tuple[PropertyRow, ...]) -> None:
        for row in rows:
            self._insert_property(parent, row.field, row.value, row.source)

    def _insert_object_table_properties(self, parent: str, object_index: int, *, title: str = "Object") -> str:
        section = self._insert_property(parent, title, self._object_name(object_index), "object table", open=True)
        info = self.loaded.object_table.get(object_index) if self.loaded is not None and self.loaded.object_table is not None else None
        if info is None:
            self._insert_property(section, "Status", "object table record unavailable", "object table")
            return section
        self._insert_property(section, "Type", f"{info.type_name} ({info.type_index})", "object table")
        self._insert_property(section, "Value", info.value, "object table")
        self._insert_property(section, "Sprite", f"DOS #{info.sprite_index}", "object table")
        if info.effect_name is not None:
            self._insert_property(section, "Usable effect", f"{info.effect_name} ({info.effect_index})", "object table")
        if info.is_destructable:
            self._insert_property(section, "Role", "DestroyType4 target", "decoded")
        if info.is_chest:
            keys = [
                key
                for key in (self.loaded.object_table.records if self.loaded is not None and self.loaded.object_table is not None else ())
                if key.opens_chest_object_info(object_index)
            ]
            chest = self._insert_property(section, "Chest", "locked treasure container", "decoded", open=True)
            self._insert_property(chest, "Opened by", ", ".join(self._object_ref(key.index) for key in keys) if keys else "unknown key", "decoded")
        if info.is_chest_key and self.loaded is not None and self.loaded.object_table is not None:
            chests = [chest for chest in self.loaded.object_table.records if info.opens_chest_object_info(chest.index)]
            key = self._insert_property(section, "Chest key", "opens matching chest object", "decoded", open=True)
            self._insert_property(key, "Opens", ", ".join(self._object_ref(chest.index) for chest in chests) if chests else "unknown chest", "decoded")
        return section

    def _insert_weapon_table_properties(self, parent: str, weapon_index: int, *, title: str = "Weapon") -> str:
        section = self._insert_property(parent, title, self._weapon_name(weapon_index), "weapon table", open=True)
        info = self.loaded.weapon_table.get(weapon_index) if self.loaded is not None and self.loaded.weapon_table is not None else None
        if info is None:
            self._insert_property(section, "Status", "weapon table record unavailable", "weapon table")
            return section
        self._insert_property(section, "Value", info.value, "weapon table")
        self._insert_property(section, "Power", f"{info.base_power}/{info.current_power}", "weapon table")
        self._insert_property(section, "Remove on wall/enemy", f"{info.remove_on_wall_hit}/{info.remove_on_enemy_hit}", "weapon table")
        return section

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

    def _insert_event_trigger_cells(self, parent: str, event_index: int, *, title: str = "Map triggers") -> str:
        ref = ("event", event_index)
        cells = self.loaded.logic_graph.event_cells.get(event_index, ()) if self.loaded is not None and self.loaded.logic_graph is not None else ()
        trigger_root = self._insert_property(parent, title, f"{len(cells)} cell{'s' if len(cells) != 1 else ''}", "map layer B", open=True)
        if not cells:
            self._insert_property(trigger_root, "Status", "effect-only / no direct map trigger cells", "map layer B")
            self._insert_property(trigger_root, "Add cell", "Pick on map", "map layer B", edit=PropertyEditSpec("event_add_cell", ref, pick=True))
            return trigger_root
        for index, (cell_x, cell_y) in enumerate(cells):
            self._insert_property(trigger_root, f"Cell {index}", f"{cell_x},{cell_y}", "map layer B", edit=PropertyEditSpec(f"event_cell:{index}", ref, pick=True))
        self._insert_property(trigger_root, "Add cell", "Pick on map", "map layer B", edit=PropertyEditSpec("event_add_cell", ref, pick=True))
        return trigger_root

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
        ref = ("wave", EnemySelection(prefix, wave.index, None, getattr(wave, "pixel_x", None), getattr(wave, "pixel_y", None)))
        editable_ww = prefix == "WW"
        self._insert_property(parent, "Wave", f"{prefix}{wave.index}", source)
        if hasattr(wave, "pixel_x") and hasattr(wave, "pixel_y"):
            self._insert_property(parent, "Position", f"{wave.pixel_x},{wave.pixel_y}", source, edit=PropertyEditSpec("wave_position", ref) if editable_ww else None)
            if editable_ww:
                self._insert_property(parent, "Pick position", "click map", source, edit=PropertyEditSpec("wave_position", ref, pick=True))
        self._insert_property(parent, "Enemy count", wave.enemy_count, source, edit=PropertyEditSpec("wave_enemy_count", ref) if editable_ww else None)
        self._insert_property(parent, "Health", wave.health, source, edit=PropertyEditSpec("wave_health", ref) if editable_ww else None)
        self._insert_property(parent, "Enemy info", self._enemy_summary(wave, enemy_kind), "enemy table", edit=PropertyEditSpec("wave_enemy_info", ref, atlas=f"enemy_{enemy_kind}") if editable_ww else None)
        self._insert_property(parent, "Reward", self._wave_reward_text(wave), "item table", edit=PropertyEditSpec("wave_reward", ref, atlas="walking_wave_reward") if editable_ww else None)
        if hasattr(wave, "spawn_delay"):
            self._insert_property(parent, "Spawn delay", getattr(wave, "spawn_delay"), source, edit=PropertyEditSpec("wave_spawn_delay", ref) if editable_ww else None)
        if hasattr(wave, "facing"):
            self._insert_property(parent, "Facing", getattr(wave, "facing"), source, edit=PropertyEditSpec("wave_facing", ref, ("0", "1")) if editable_ww else None)
        if editable_ww:
            self._insert_property(parent, "Action/function", getattr(wave, "function_index_unknown"), source, edit=PropertyEditSpec("wave_function", ref))
            self._insert_property(parent, "Missile type", getattr(wave, "missile_type"), source, edit=PropertyEditSpec("wave_missile_type", ref))
            self._insert_property(parent, "Speed", getattr(wave, "speed_value"), source, edit=PropertyEditSpec("wave_speed", ref))
        if prefix == "FW":
            self._insert_property(parent, "Flying path", f"FP{wave.flying_path_index}", ".PAT")
        info = self._enemy_info(wave, enemy_kind)
        if info is not None:
            self._insert_property(parent, "Sprite", f"DOS #{info.sprite_index_for_facing(getattr(wave, 'facing', 0))}", "sprite table")
            self._insert_property(parent, "Bounds", f"{info.width}x{info.height}px", "enemy table")
            self._insert_property(parent, "Action", info.action_type, "enemy table")

    def _insert_puzzle_effect_fields(self, parent: str, puzzle) -> None:
        point = self.loaded.logic_graph.point_for_puzzle(puzzle.index) if self.loaded is not None and self.loaded.logic_graph is not None else None
        ref = ("point", point or LogicPoint(puzzle.pixel_x, puzzle.pixel_y, f"P{puzzle.index}", "puzzle", puzzle.index))
        effect_choices = tuple(f"{index}: {puzzle_effect_name(index)}" for index in range(15))
        effect = self._insert_property(parent, "Effect", self._effect_text(puzzle), "decoded", open=True)
        self._insert_property(effect, "Type", f"{puzzle.effect_function_index}: {puzzle_effect_name(puzzle.effect_function_index)}", "map", edit=PropertyEditSpec("puzzle_effect_type", ref, effect_choices))
        self._insert_property(effect, "Remove item after effect", int(puzzle.remove_after_effect), "map", edit=PropertyEditSpec("puzzle_remove", ref, ("0", "1")))

        effect_type = puzzle.effect_function_index
        param = puzzle.effect_param
        if effect_type == 0:
            self._insert_property(effect, "Object id", self._object_ref(param), "map", edit=PropertyEditSpec("puzzle_effect_param", ref, atlas="object"))
            target = self._insert_object_table_properties(effect, param)
            self._insert_property(target, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map", edit=PropertyEditSpec("puzzle_position", ref))
            self._insert_property(target, "Pick position", "click map", "map", edit=PropertyEditSpec("puzzle_position", ref, pick=True))
        elif effect_type == 1:
            self._insert_property(effect, "Weapon id", self._weapon_ref(param), "map", edit=PropertyEditSpec("puzzle_effect_param", ref, atlas="weapon"))
            target = self._insert_weapon_table_properties(effect, param)
            self._insert_property(target, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map", edit=PropertyEditSpec("puzzle_position", ref))
            self._insert_property(target, "Pick position", "click map", "map", edit=PropertyEditSpec("puzzle_position", ref, pick=True))
        elif effect_type in (2, 9):
            target = self._insert_property(effect, "Door", f"DOOR{puzzle.index}", "decoded", open=True)
            self._insert_property(target, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map", edit=PropertyEditSpec("puzzle_position", ref))
            self._insert_property(target, "Pick position", "click map", "map", edit=PropertyEditSpec("puzzle_position", ref, pick=True))
            self._insert_property(target, "Size", "32x48", "map")
        elif effect_type == 5:
            target = self._insert_property(effect, "Event", self._event_trigger_text(param - 1), "PALFILS", open=True, edit=PropertyEditSpec("puzzle_effect_param", ref))
            self._insert_event_trigger_cells(target, param - 1)
        elif effect_type == 6:
            target = self._insert_property(effect, "Target", "type-4 destructible", "decoded", open=True)
            self._insert_property(target, "Search origin", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map", edit=PropertyEditSpec("puzzle_position", ref))
            self._insert_property(target, "Pick origin", "click map", "map", edit=PropertyEditSpec("puzzle_position", ref, pick=True))
        elif effect_type in (7, 8):
            target = self._insert_property(effect, "Trapdoor", f"D{param}", "PALFILS", open=True, edit=PropertyEditSpec("puzzle_effect_param", ref))
            if self.loaded is not None and self.loaded.alfils_data is not None and 0 <= param < len(self.loaded.alfils_data.trapdoors):
                trapdoor = self.loaded.alfils_data.trapdoors[param]
                self._insert_property(target, "Position", f"{trapdoor.pixel_x},{trapdoor.pixel_y}", "PALFILS")
        elif effect_type == 10:
            self._insert_property(effect, "Weapon", self._weapon_ref(param), "weapon table", edit=PropertyEditSpec("puzzle_effect_param", ref, atlas="weapon"))
        else:
            self._insert_property(effect, "Param", param, "map", edit=PropertyEditSpec("puzzle_effect_param", ref))

    def _insert_puzzle_condition_fields(self, parent: str, puzzle) -> None:
        ref = ("point", self.loaded.logic_graph.point_for_puzzle(puzzle.index) if self.loaded is not None and self.loaded.logic_graph is not None else LogicPoint(puzzle.pixel_x, puzzle.pixel_y, f"P{puzzle.index}", "puzzle", puzzle.index))
        condition_choices = tuple(f"{index}: {condition_type_name(index)}" for index in range(17))
        conditions = self._insert_property(parent, "Conditions", "all must pass", "map puzzle", open=True)
        for slot, (condition_type, param) in enumerate(zip(puzzle.condition_function_indices, puzzle.condition_params)):
            condition_parent = self._insert_property(
                conditions,
                f"Condition {slot}",
                self._condition_text(condition_type, param),
                "decoded",
                open=True,
            )
            self._insert_property(condition_parent, "Type", f"{condition_type}: {condition_type_name(condition_type)}", "map", edit=PropertyEditSpec(f"cond{slot}_type", ref, condition_choices))
            self._insert_property(condition_parent, "Param", param, "map", edit=PropertyEditSpec(f"cond{slot}_param", ref))
            self._insert_puzzle_condition_param_fields(condition_parent, condition_type, param)

    def _insert_event_effect_tree(self, parent: str, event) -> None:
        ref = ("event", event.index)
        type_choices = tuple(["-1: Unused", *[f"{index}: {name}" for index, name in sorted(EVENT_TYPE_NAMES.items())]])
        effect = self._insert_property(parent, "Effect", event.type_name, "PALFILS", open=True)
        type_value = f"{event.event_type_index if event.event_type_index is not None else -1}: {event.type_name}"
        self._insert_property(effect, "Type", type_value, "PALFILS", edit=PropertyEditSpec("event_type", ref, type_choices))
        param_choices = self._event_param_choices(event.event_type_index if event.event_type_index is not None else -1)

        wave_target = self._wave_target_for_event(event)
        if wave_target is not None:
            prefix, wave, enemy_kind, title = wave_target
            param = self._insert_property(effect, "Wave", f"{prefix}{event.param}", "PALFILS", open=True, edit=PropertyEditSpec("event_param", ref, param_choices))
            self._insert_property(param, "Meaning", title, "decoded")
            self._insert_wave_fields(param, prefix, wave, enemy_kind, "PALFILS")
            return

        if event.event_type_index == 2 and self.loaded.map_data is not None:
            puzzle = self.loaded.map_data.puzzles[event.param] if 0 <= event.param < len(self.loaded.map_data.puzzles) else None
            param = self._insert_property(effect, "Puzzle", f"P{event.param}", "map puzzle", open=True, edit=PropertyEditSpec("event_param", ref, param_choices))
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
            param = self._insert_property(effect, "Moving block", f"MB{event.param}", "PALFILS", open=True, edit=PropertyEditSpec("event_param", ref, param_choices))
            if block is None:
                self._insert_property(param, "Status", "moving block slot unavailable", "PALFILS")
                return
            action_index = event.event_type_index - 6
            self._insert_property(param, "Action", f"A{action_index}: {block.action_description(action_index)}", "PALFILS")
            self._insert_property(param, "Position", f"{block.pixel_x},{block.pixel_y}", "PALFILS")
            self._insert_property(param, "Size", f"{block.width_pixels}x{block.height_pixels}px", "PALFILS")
            return

        if event.event_type_index == 5:
            self._insert_property(effect, "Checkpoint", event.param, "PALFILS", edit=PropertyEditSpec("event_param", ref, param_choices))
        elif event.event_type_index == 10:
            self._insert_property(effect, "Guardian", event.param, "PALFILS", edit=PropertyEditSpec("event_param", ref, param_choices))
        elif event.event_type_index == 11:
            self._insert_property(effect, "Status", "inactive event slot", "PALFILS")
        else:
            self._insert_property(effect, "Raw param", event.param, "PALFILS")

    def _insert_event_properties(self, event_index: int) -> None:
        assert self.loaded is not None
        event = self.loaded.alfils_data.event(event_index) if self.loaded.alfils_data is not None else None
        root = self._insert_property_section(f"Map trigger E{event_index}", "layer B / PALFILS")
        pending_tag = self._pending_tag_for_ref(("event", event_index))
        if pending_tag is not None:
            self._set_pending_tags(self.property_tree, root, pending_tag)
        self._insert_event_trigger_cells(root, event_index)
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
        ref = ("item", selection)
        id_atlas = "weapon_raw" if item.is_weapon else "object"
        id_value = self._weapon_ref(item.object_or_weapon_info_index - 192) if item.is_weapon else self._object_ref(item.object_or_weapon_info_index)
        self._insert_property(root, "Kind", "weapon" if item.is_weapon else "object", "map")
        self._insert_property(root, "Position", f"{item.pixel_x},{item.pixel_y}", "map", edit=PropertyEditSpec("item_position", ref))
        self._insert_property(root, "Pick position", "click map", "map", edit=PropertyEditSpec("item_position", ref, pick=True))
        self._insert_property(root, "Object/weapon id", id_value, "map", edit=PropertyEditSpec("item_raw_id", ref, atlas=id_atlas))
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
            ref = ("point", point)
            section = self._insert_property_section(f"Switch S{record.index}", "PALFILS")
            self._insert_property(section, "Object", self._object_ref(record.object_info_index), "object table", edit=PropertyEditSpec("switch_object", ref, atlas="object"))
            self._insert_property(section, "Position", f"{record.pixel_x},{record.pixel_y}", "PALFILS", edit=PropertyEditSpec("switch_position", ref))
            self._insert_property(section, "Pick position", "click map item", "PALFILS", edit=PropertyEditSpec("switch_position", ref, pick=True))
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

        if point.kind == "spawned_object":
            section = self._insert_property_section(f"Spawned object {point.label}", "map puzzle")
            self._insert_object_table_properties(section, point.index)
            self._insert_property(section, "Spawn position", f"{point.pixel_x},{point.pixel_y}", "map")
            return

        if point.kind == "spawned_weapon":
            section = self._insert_property_section(f"Spawned weapon {point.label}", "map puzzle")
            self._insert_weapon_table_properties(section, point.index)
            self._insert_property(section, "Spawn position", f"{point.pixel_x},{point.pixel_y}", "map")
            return

        if point.kind == "destructable_object" and 0 <= point.index < len(self.loaded.map_data.items):
            item = self.loaded.map_data.items[point.index]
            ref = ("point", point)
            section = self._insert_property_section(f"Destructible target {point.label}", "map item")
            self._insert_property(section, "Map item", f"I{item.index}", "map")
            self._insert_property(section, "Position", f"{item.pixel_x},{item.pixel_y}", "map", edit=PropertyEditSpec("destructible_position", ref))
            self._insert_property(section, "Pick position", "click map item", "map", edit=PropertyEditSpec("destructible_position", ref, pick=True))
            if item.is_object:
                self._insert_property(section, "Object", self._object_ref(item.object_or_weapon_info_index), "object table", edit=PropertyEditSpec("destructible_object", ref, atlas="object"))
                self._insert_object_table_properties(section, item.object_or_weapon_info_index)
            if self.loaded.logic_graph is not None:
                incoming = [
                    edge.source.label
                    for edge in self.loaded.logic_graph.direct_edges_for_point(point)
                    if edge.source.kind == "puzzle" and self.loaded.logic_graph._same_graph_node(edge.target, point)
                ]
                self._insert_property(section, "Destroy effects", ", ".join(incoming) if incoming else "none", "logic")
            return

        if point.kind == "spawned_destructable_object" and 0 <= point.index < len(self.loaded.map_data.puzzles):
            puzzle = self.loaded.map_data.puzzles[point.index]
            puzzle_point = self.loaded.logic_graph.point_for_puzzle(puzzle.index) if self.loaded.logic_graph is not None else None
            ref = ("point", puzzle_point or LogicPoint(puzzle.pixel_x, puzzle.pixel_y, f"P{puzzle.index}", "puzzle", puzzle.index))
            section = self._insert_property_section(f"Spawned destructible target {point.label}", "map puzzle")
            self._insert_property(section, "Source puzzle", f"P{puzzle.index}", "map")
            self._insert_property(section, "Spawn position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map", edit=PropertyEditSpec("puzzle_position", ref))
            self._insert_property(section, "Pick position", "click map", "map", edit=PropertyEditSpec("puzzle_position", ref, pick=True))
            if puzzle.effect_function_index == 0:
                self._insert_property(section, "Spawn object", self._object_ref(puzzle.effect_param), "map", edit=PropertyEditSpec("puzzle_effect_param", ref, atlas="object"))
                self._insert_object_table_properties(section, puzzle.effect_param)
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

    @staticmethod
    def _table_item_label(prefix: str, index: int, info, *, style: str) -> str:
        base = f"{prefix}{index}"
        if info is None:
            return base
        if style == "name":
            return f"{base}: {info.full_name}"
        return f"{base} ({info.full_name})"

    def _object_name(self, object_index: int) -> str:
        info = self.loaded.object_table.get(object_index) if self.loaded is not None and self.loaded.object_table is not None else None
        return self._table_item_label("OBJ", object_index, info, style="name")

    def _object_ref(self, object_index: int) -> str:
        info = self.loaded.object_table.get(object_index) if self.loaded is not None and self.loaded.object_table is not None else None
        return self._table_item_label("OBJ", object_index, info, style="ref")

    def _weapon_name(self, weapon_index: int) -> str:
        info = self.loaded.weapon_table.get(weapon_index) if self.loaded is not None and self.loaded.weapon_table is not None else None
        return self._table_item_label("WPN", weapon_index, info, style="name")

    def _weapon_ref(self, weapon_index: int) -> str:
        info = self.loaded.weapon_table.get(weapon_index) if self.loaded is not None and self.loaded.weapon_table is not None else None
        return self._table_item_label("WPN", weapon_index, info, style="ref")

    def _logic_target_detail_text(self, point: LogicPoint) -> str:
        if self.loaded is None:
            return point.kind.replace("_", " ")
        if point.kind == "spawned_object" and point.index is not None:
            return self._object_name(point.index)
        if point.kind == "spawned_weapon" and point.index is not None:
            return self._weapon_name(point.index)
        if point.kind == "destructable_object" and point.index is not None and 0 <= point.index < len(self.loaded.map_data.items):
            item = self.loaded.map_data.items[point.index]
            if item.is_object:
                return f"I{item.index}: {self._object_name(item.object_or_weapon_info_index)}"
            return f"I{item.index}: destructible target"
        if point.kind == "spawned_destructable_object" and point.index is not None and 0 <= point.index < len(self.loaded.map_data.puzzles):
            puzzle = self.loaded.map_data.puzzles[point.index]
            if puzzle.effect_function_index == 0:
                return f"P{puzzle.index}: {self._object_name(puzzle.effect_param)}"
            return f"P{puzzle.index}: spawned destructible target"
        if point.kind == "destroy_type4_unresolved" and point.index is not None:
            return f"P{point.index}: unresolved DestroyType4 target"
        if point.kind == "destroy_type4_offmap" and point.index is not None:
            return f"P{point.index}: off-map DestroyType4"
        return point.kind.replace("_", " ")

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

    def _switch_condition_rows(self, switch_index: int) -> tuple[PropertyRow, ...]:
        if self.loaded is None or self.loaded.alfils_data is None or not (0 <= switch_index < len(self.loaded.alfils_data.switches)):
            return ()
        switch = self.loaded.alfils_data.switches[switch_index]
        return (
            PropertyRow("Object", self._object_name(switch.object_info_index), "object table"),
            PropertyRow("Position", f"{switch.pixel_x},{switch.pixel_y}", "PALFILS"),
        )

    def _condition_param_presentation(self, condition_type: int, param: int) -> ConditionParamPresentation:
        if condition_type == 0:
            return ConditionParamPresentation("")
        if condition_type in (1, 2):
            value = self._object_ref(param)
            return ConditionParamPresentation(value, (PropertyRow("Object", value, "object table"),))
        if condition_type in (3, 4):
            value = self._weapon_ref(param)
            return ConditionParamPresentation(value, (PropertyRow("Weapon", value, "weapon table"),))
        if condition_type in (5, 6):
            event_index = param - 1
            value = self._event_trigger_text(event_index)
            return ConditionParamPresentation(
                value,
                (PropertyRow("Event", value, "PALFILS"),),
            )
        if condition_type in (7, 8):
            value = f"{param}/24"
            return ConditionParamPresentation(value, (PropertyRow("Health threshold", value, "decoded"),))
        if condition_type in (9, 10):
            value = f"{param * 5}s"
            return ConditionParamPresentation(value, (PropertyRow("Time threshold", value, "decoded"),))
        if condition_type in (11, 12):
            value = self._switch_binding_text(param)
            return ConditionParamPresentation(
                value,
                (PropertyRow("Switch", value, "PALFILS"), *self._switch_condition_rows(param)),
            )
        if condition_type in (13, 14):
            value = param * 5000
            return ConditionParamPresentation(str(value), (PropertyRow("Score threshold", value, "decoded"),))
        if condition_type in (15, 16):
            return ConditionParamPresentation(str(param), (PropertyRow("Lives threshold", param, "decoded"),))
        return ConditionParamPresentation(str(param), (PropertyRow("Raw param", param, "map"),))

    def _insert_puzzle_condition_param_fields(self, parent: str, condition_type: int, param: int) -> None:
        if condition_type in (5, 6):
            presentation = self._condition_param_presentation(condition_type, param)
            target = self._insert_property(parent, "Event", presentation.rows[0].value, presentation.rows[0].source, open=True)
            self._insert_event_trigger_cells(target, param - 1)
            return
        if condition_type in (11, 12):
            presentation = self._condition_param_presentation(condition_type, param)
            target = self._insert_property(parent, "Switch", presentation.rows[0].value, presentation.rows[0].source, open=True)
            self._insert_property_rows(target, presentation.rows[1:])
            return
        self._insert_property_rows(parent, self._condition_param_presentation(condition_type, param).rows)

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

    @staticmethod
    def _event_param_field_name(event_type: int) -> str:
        return {
            0: "Flying wave",
            1: "Walking wave",
            2: "Puzzle",
            3: "Intel walking wave",
            4: "Intel flying wave",
            5: "Checkpoint",
            6: "Moving block",
            7: "Moving block",
            8: "Moving block",
            9: "Moving block",
            10: "Guardian",
        }.get(event_type, "Param")

    @staticmethod
    def _event_param_display_value(event_type: int, param: int) -> str:
        if event_type == 0:
            return f"FW{param}"
        if event_type == 1:
            return f"WW{param}"
        if event_type == 2:
            return f"P{param}"
        if event_type == 3:
            return f"IW{param}"
        if event_type == 4:
            return f"IF{param}"
        if 6 <= event_type <= 9:
            return f"MB{param}"
        if event_type == 10:
            return f"G{param}"
        return str(param)

    def _event_param_choices(self, event_type: int) -> tuple[str, ...]:
        """Return valid existing target IDs for an event parameter, when enumerable."""
        if self.loaded is None:
            return ()
        alfils = self.loaded.alfils_data
        map_data = self.loaded.map_data

        if alfils is not None:
            if event_type == 0:
                return tuple(f"FW{index}" for index in range(len(alfils.flying_waves)))
            if event_type == 1:
                return tuple(f"WW{index}" for index in range(len(alfils.walking_waves)))
            if event_type == 3:
                return tuple(f"IW{index}" for index in range(len(alfils.intel_walking_waves)))
            if event_type == 4:
                return tuple(f"IF{index}" for index in range(len(alfils.intel_flying_waves)))
            if 6 <= event_type <= 9:
                return tuple(f"MB{index}" for index in range(len(alfils.moving_blocks)))

        if event_type == 2 and map_data is not None:
            return tuple(f"P{puzzle.index}" for puzzle in map_data.active_puzzles)

        # Checkpoints and guardians are numeric ids in the event table, but this
        # viewer currently has no level-local collection that defines their valid ids.
        return ()

    def _normalise_event_param_for_type(self, event_type: int, param: int) -> int:
        choices = self._event_param_choices(event_type)
        if not choices:
            return param
        valid_params = tuple(self._parse_event_param_value(event_type, choice) for choice in choices)
        return param if param in valid_params else valid_params[0]

    def _condition_text(self, condition_type: int, param: int) -> str:
        name = condition_type_name(condition_type)
        param_text = self._condition_param_presentation(condition_type, param).summary
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
            return f"{name} DOOR{puzzle.index}"
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
        point = self.loaded.logic_graph.point_for_puzzle(puzzle.index) if self.loaded.logic_graph is not None else None
        ref = ("point", point or LogicPoint(puzzle.pixel_x, puzzle.pixel_y, f"P{puzzle.index}", "puzzle", puzzle.index))
        root = self._insert_property_section(f"Puzzle P{puzzle.index}", "map puzzle")
        self._insert_property(root, "Position", f"{puzzle.pixel_x},{puzzle.pixel_y}", "map", edit=PropertyEditSpec("puzzle_position", ref))
        self._insert_property(root, "Pick position", "click map", "map", edit=PropertyEditSpec("puzzle_position", ref, pick=True))
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
        if getattr(self, "property_tree", None) is getattr(self, "browser_property_tree", None):
            self._set_flying_path_preview(path)
        self._insert_property(root, "Type", path.kind, ".PAT")
        self._insert_property(root, "Nodes", len(path.deltas), ".PAT")
        self._insert_property(root, "Base", f"{path.base_x},{path.base_y}", ".PAT")

    def _set_flying_path_preview(self, path) -> None:
        if not hasattr(self, "path_preview_canvas"):
            return
        canvas = self.path_preview_canvas
        canvas.delete("all")
        if path is None:
            canvas.pack_forget()
            return
        if not canvas.winfo_ismapped():
            canvas.pack(fill=tk.X, pady=(0, 4), before=self.browser_property_tree)
        canvas.update_idletasks()
        width = max(canvas.winfo_width(), 220)
        height = max(canvas.winfo_height(), 90)
        points = path.points_for_event_center(0, 0)
        if not points:
            canvas.create_text(10, height // 2, text="empty path", fill="#d8d8d8", anchor="w")
            return
        min_x = min(x for x, _y in points)
        max_x = max(x for x, _y in points)
        min_y = min(y for _x, y in points)
        max_y = max(y for _x, y in points)
        span_x = max(1, max_x - min_x)
        span_y = max(1, max_y - min_y)
        margin = 14
        scale = min((width - margin * 2) / span_x, (height - margin * 2) / span_y, 4.0)
        if scale <= 0:
            scale = 1.0

        def project(point: tuple[int, int]) -> tuple[float, float]:
            x, y = point
            px = margin + (x - min_x) * scale
            py = margin + (y - min_y) * scale
            return px, py

        projected = [project(point) for point in points]
        color = "#50ffb4" if path.is_absolute else "#ffb450"
        canvas.create_rectangle(1, 1, width - 2, height - 2, outline="#606060")
        if len(projected) >= 2:
            flat = [coord for point in projected for coord in point]
            canvas.create_line(*flat, fill="#000000", width=4, smooth=False)
            canvas.create_line(*flat, fill=color, width=2, smooth=False)
        first_x, first_y = projected[0]
        last_x, last_y = projected[-1]
        canvas.create_oval(first_x - 4, first_y - 4, first_x + 4, first_y + 4, outline=color, width=2)
        canvas.create_rectangle(last_x - 3, last_y - 3, last_x + 3, last_y + 3, outline=color, width=2)
        canvas.create_text(8, 8, text=f"FP{path.index} {path.kind}", fill="#d8d8d8", anchor="nw")

    def _populate_entity_tree(self) -> None:
        if not hasattr(self, "entity_group_stack"):
            return
        preserved_group = self.selected_entity_group
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
        self._insert_pending_entity_rows()
        if preserved_group in self.entity_group_frames:
            self._show_entity_group(preserved_group)
        self._update_entity_tree_highlight()

    def _insert_pending_entity_rows(self) -> None:
        for edit in self.pending_property_edits:
            if edit.spec.field == "item_create":
                tree = self.entity_trees.get("Map items") or self._create_entity_group_tab("Map items")
                iid = f"pending:{len(self.entity_refs)}"
                tree.insert("", tk.END, iid=iid, text="NEW item", values=(self._display_value_for_spec(edit.spec, edit.value), "pending"), tags=("pending_new",))
                self.entity_refs[iid] = edit.spec.ref
            elif edit.spec.field == "event_create":
                event_index = int(edit.spec.ref[1])
                tree = self.entity_trees.get("Events") or self._create_entity_group_tab("Events")
                iid = f"pending:{len(self.entity_refs)}"
                tree.insert("", tk.END, iid=iid, text=f"E{event_index} NEW", values=(self._display_value_for_spec(edit.spec, edit.value), "pending"), tags=("pending_new",))
                self.entity_refs[iid] = ("pending_event", event_index)

    def _select_pending_event_row(self, event_index: int) -> None:
        tree = self.entity_trees.get("Events")
        if tree is None:
            return
        target_ref = ("pending_event", event_index)
        for item_id, ref in self.entity_refs.items():
            if ref == target_ref and tree.exists(item_id):
                self._show_entity_group("Events")
                tree.selection_set(item_id)
                tree.focus(item_id)
                tree.see(item_id)
                self._populate_properties_tree_for_pending_event(event_index)
                return

    def _populate_properties_tree_for_pending_event(self, event_index: int) -> None:
        self.property_tree.delete(*self.property_tree.get_children())
        ref = ("pending_event", event_index)
        root = self._insert_property_section(f"Pending event E{event_index}", "pending", open=True)
        type_choices = tuple(["-1: Unused", *[f"{index}: {name}" for index, name in sorted(EVENT_TYPE_NAMES.items())]])
        for edit in self.pending_property_edits:
            if edit.spec.field != "event_create" or int(edit.spec.ref[1]) != event_index:
                continue
            type_text, param_text = edit.value.split(",", 1)
            event_type = int(type_text)
            param = int(param_text)
            self._insert_property(root, "Effect", self._event_action_text_from_values(event_type, param), "pending")
            self._insert_property(root, "Type", f"{type_text}: {EVENT_TYPE_NAMES.get(event_type, f'Type {type_text}')}", "pending", edit=PropertyEditSpec("pending_event_type", ref, type_choices))
            param_choices = self._event_param_choices(event_type)
            self._insert_property(
                root,
                self._event_param_field_name(event_type),
                self._event_param_display_value(event_type, param),
                "pending",
                edit=PropertyEditSpec("pending_event_param", ref, param_choices),
            )
            return

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

        if group == "Spawn effects":
            point = payload
            puzzle_index = int(entity.key.index)
            puzzle_point = graph.point_for_puzzle(puzzle_index) or point
            puzzle = map_data.puzzles[puzzle_index]
            detail = self._effect_text(puzzle)
            return detail, self._position_text(point.pixel_x, point.pixel_y), "point", puzzle_point

        if group == "Destructible targets":
            point = payload
            detail = self._logic_target_detail_text(point)
            puzzle_index = int(entity.key.index)
            if point.kind == "destructable_object":
                return detail, self._position_text(point.pixel_x, point.pixel_y), "item", MapItemSelection(point.index)
            if point.kind == "spawned_destructable_object":
                puzzle_point = graph.point_for_puzzle(puzzle_index) or point
                return detail, self._position_text(point.pixel_x, point.pixel_y), "point", puzzle_point
            puzzle_point = graph.point_for_puzzle(puzzle_index) or point
            return detail, self._position_text(point.pixel_x, point.pixel_y), "point", puzzle_point

        if group == "Physical logic targets" or group.startswith("Logic targets:") or group.startswith("Logic:"):
            point = payload
            detail = self._logic_target_detail_text(point)
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
            for tree in self.entity_trees.values():
                if tree.exists(item_id):
                    tags = []
                    pending_tag = self._pending_tag_for_ref(ref)
                    if pending_tag is None:
                        pending_tag = next((tag for tag in tree.item(item_id, "tags") if tag == "pending_new"), None)
                    if pending_tag is not None:
                        tags.append(pending_tag)
                    if ref in related:
                        tags.append("related")
                    tree.item(item_id, tags=tuple(tags))
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
        if ref[0] == "item_raw":
            self.property_tree.delete(*self.property_tree.get_children())
            root = self._insert_property_section("Pending new map item", "pending", open=True)
            for edit in self.pending_property_edits:
                if edit.spec.ref == ref and edit.spec.field == "item_create":
                    self._insert_property(root, "Create", self._display_value_for_spec(edit.spec, edit.value), "pending")
            return
        if ref[0] == "pending_event":
            self._populate_properties_tree_for_pending_event(int(ref[1]))
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
        if ref_kind == "item_raw":
            self.inspect_var.set("Pending new item will exist after Apply.")
            return
        if ref_kind == "pending_event":
            self.inspect_var.set("Pending new event will exist after Apply.")
            return
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
        if self.suppress_next_map_double_click:
            self.suppress_next_map_double_click = False
            return
        if self.pending_pick is not None:
            self._on_map_clicked(image_x, image_y)
            return
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
        if self.pending_pick is not None:
            spec = self.pending_pick
            self._clear_pick_mode()
            self.suppress_next_map_double_click = True
            self._queue_property_edit(spec, self._pick_value_for_property(spec, image_x, image_y, cell_x, cell_y))
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

    def _pick_value_for_property(self, spec: PropertyEditSpec, image_x: int, image_y: int, cell_x: int, cell_y: int) -> str:
        if spec.field == "item_create":
            ref_kind, raw_id = spec.ref
            if ref_kind == "item_raw":
                return f"{int(raw_id)},{image_x},{image_y}"
        if spec.field.startswith("event_cell:") or spec.field == "event_add_cell":
            return f"{cell_x},{cell_y}"
        if spec.field == "puzzle_position":
            snapped = self._snap_puzzle_pick_position(spec, image_x, image_y)
            if snapped is not None:
                return f"{snapped[0]},{snapped[1]}"
        if spec.field == "switch_position":
            snapped = self._snap_switch_pick_position(image_x, image_y)
            if snapped is not None:
                return f"{snapped[0]},{snapped[1]}"
        if spec.field == "destructible_position":
            snapped = self._snap_destructible_pick_position(image_x, image_y)
            if snapped is not None:
                return f"{snapped[0]},{snapped[1]}"
        return f"{image_x},{image_y}"

    def _snap_switch_pick_position(self, image_x: int, image_y: int) -> tuple[int, int] | None:
        hit = self._pick_map_item(image_x, image_y)
        if hit is None:
            return None
        item = self._map_item_for_selection(hit)
        if item is None or not item.is_object:
            return None
        return item.pixel_x, item.pixel_y

    def _snap_destructible_pick_position(self, image_x: int, image_y: int) -> tuple[int, int] | None:
        hit = self._pick_map_item(image_x, image_y)
        if hit is None or self.loaded is None or self.loaded.object_table is None:
            return None
        item = self._map_item_for_selection(hit)
        if item is None or not item.is_object:
            return None
        info = self.loaded.object_table.get(item.object_or_weapon_info_index)
        if info is None or not info.is_destructable:
            return None
        return item.pixel_x, item.pixel_y

    def _snap_puzzle_pick_position(self, spec: PropertyEditSpec, image_x: int, image_y: int) -> tuple[int, int] | None:
        if self.loaded is None:
            return None
        ref_kind, ref_value = spec.ref
        if ref_kind != "point" or not isinstance(ref_value, LogicPoint) or ref_value.kind != "puzzle" or ref_value.index is None:
            return None
        if not (0 <= ref_value.index < len(self.loaded.map_data.puzzles)):
            return None
        puzzle = self.loaded.map_data.puzzles[ref_value.index]
        if puzzle.effect_function_index != 6:
            return None
        hit = self._pick_map_item(image_x, image_y)
        if hit is None:
            return None
        item = self._map_item_for_selection(hit)
        if item is None or not item.is_object or self.loaded.object_table is None:
            return None
        info = self.loaded.object_table.get(item.object_or_weapon_info_index)
        if info is None or not info.is_destructable:
            return None
        return item.pixel_x, item.pixel_y
