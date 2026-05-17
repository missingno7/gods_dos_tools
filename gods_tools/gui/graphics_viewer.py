from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image

from gods_tools.formats.atlas_dat import AtlasDat, load_packed_atlas_dat
from gods_tools.formats.compression import GodsCompressionError, load_packed
from gods_tools.formats.pi1 import Pi1Image, load_packed_pi1
from gods_tools.formats.resources import GraphicsResource, discover_graphics_resources
from gods_tools.render.images import build_atlas_contact_sheet, render_pi1
from .image_canvas import ImageCanvas


@dataclass
class LoadedGraphics:
    resource: GraphicsResource
    pi1: Pi1Image
    sheet_image: Image.Image
    atlas: AtlasDat | None
    atlas_contact_sheet: Image.Image | None


class GraphicsViewer(ttk.Frame):
    def __init__(self, master: tk.Misc, game_dir: Path) -> None:
        super().__init__(master)
        self.game_dir = Path(game_dir)
        self.resources: list[GraphicsResource] = []
        self.loaded: LoadedGraphics | None = None

        self.search_var = tk.StringVar()
        self.info_var = tk.StringVar(value="Select a graphics resource.")

        self._build_ui()
        self.reload_resources()

    def _build_ui(self) -> None:
        outer = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        outer.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(outer, padding=8)
        right = ttk.Frame(outer, padding=8)
        outer.add(left, weight=1)
        outer.add(right, weight=4)

        ttk.Label(left, text="Graphics resources", font=("", 11, "bold")).pack(anchor="w")
        search = ttk.Entry(left, textvariable=self.search_var)
        search.pack(fill=tk.X, pady=(6, 6))
        search.bind("<KeyRelease>", lambda _event: self._populate_resource_list())

        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)
        self.resource_list = tk.Listbox(list_frame, exportselection=False)
        scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.resource_list.yview)
        self.resource_list.configure(yscrollcommand=scroll.set)
        self.resource_list.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.resource_list.bind("<<ListboxSelect>>", self._on_resource_selected)

        ttk.Separator(left).pack(fill=tk.X, pady=8)
        ttk.Label(left, textvariable=self.info_var, wraplength=320, justify=tk.LEFT).pack(
            fill=tk.X, anchor="nw"
        )

        self.preview_tabs = ttk.Notebook(right)
        self.preview_tabs.pack(fill=tk.BOTH, expand=True)

        sheet_tab = ttk.Frame(self.preview_tabs)
        atlas_tab = ttk.Frame(self.preview_tabs)
        data_tab = ttk.Frame(self.preview_tabs)
        self.preview_tabs.add(sheet_tab, text="PI1 screen")
        self.preview_tabs.add(atlas_tab, text="DAT atlas")
        self.preview_tabs.add(data_tab, text="Raw details")

        self.sheet_canvas = ImageCanvas(sheet_tab)
        self.sheet_canvas.pack(fill=tk.BOTH, expand=True)

        self.atlas_canvas = ImageCanvas(atlas_tab)
        self.atlas_canvas.pack(fill=tk.BOTH, expand=True)

        self.raw_text = tk.Text(
            data_tab,
            wrap="none",
            height=20,
            background="#101010",
            foreground="#e8e8e8",
            insertbackground="#e8e8e8",
        )
        raw_y = ttk.Scrollbar(data_tab, orient=tk.VERTICAL, command=self.raw_text.yview)
        raw_x = ttk.Scrollbar(data_tab, orient=tk.HORIZONTAL, command=self.raw_text.xview)
        self.raw_text.configure(yscrollcommand=raw_y.set, xscrollcommand=raw_x.set)
        self.raw_text.grid(row=0, column=0, sticky="nsew")
        raw_y.grid(row=0, column=1, sticky="ns")
        raw_x.grid(row=1, column=0, sticky="ew")
        data_tab.rowconfigure(0, weight=1)
        data_tab.columnconfigure(0, weight=1)

    def reload_resources(self) -> None:
        self.resources = discover_graphics_resources(self.game_dir)
        self._populate_resource_list()
        if self.resources:
            self.resource_list.selection_set(0)
            self._load_resource(self.resources[0])

    def _populate_resource_list(self) -> None:
        query = self.search_var.get().strip().lower()
        self.resource_list.delete(0, tk.END)
        for resource in self.resources:
            display = resource.display_name
            if not query or query in display.lower():
                self.resource_list.insert(tk.END, display)

    def _filtered_resources(self) -> list[GraphicsResource]:
        query = self.search_var.get().strip().lower()
        return [
            resource
            for resource in self.resources
            if not query or query in resource.display_name.lower()
        ]

    def _on_resource_selected(self, _event: tk.Event) -> None:
        selection = self.resource_list.curselection()
        if not selection:
            return
        filtered = self._filtered_resources()
        index = selection[0]
        if index >= len(filtered):
            return
        self._load_resource(filtered[index])

    def _load_resource(self, resource: GraphicsResource) -> None:
        try:
            pi1 = load_packed_pi1(resource.pi1_path)
            sheet_image = render_pi1(pi1).convert("RGB")
            atlas = load_packed_atlas_dat(resource.dat_path) if resource.dat_path else None
            atlas_sheet = None
            if atlas is not None:
                atlas_sheet = build_atlas_contact_sheet(sheet_image, atlas).image
        except (GodsCompressionError, ValueError, OSError) as exc:
            messagebox.showerror("GODS graphics viewer", f"Could not load {resource.display_name}\n\n{exc}")
            return

        self.loaded = LoadedGraphics(
            resource=resource,
            pi1=pi1,
            sheet_image=sheet_image,
            atlas=atlas,
            atlas_contact_sheet=atlas_sheet,
        )

        self.sheet_canvas.set_image(sheet_image)
        self.atlas_canvas.set_image(atlas_sheet)
        self._update_info()
        self._update_raw_text()

    def _update_info(self) -> None:
        assert self.loaded is not None
        loaded = self.loaded
        atlas_count = loaded.atlas.count if loaded.atlas is not None else 0
        dat_name = loaded.resource.dat_path.name if loaded.resource.dat_path else "—"
        self.info_var.set(
            "\n".join(
                [
                    f"PI1: {loaded.resource.pi1_path.name}",
                    f"DAT: {dat_name}",
                    f"Image: {loaded.pi1.width} × {loaded.pi1.height}",
                    f"Resolution word: 0x{loaded.pi1.resolution:04X}",
                    f"Atlas records: {atlas_count}",
                ]
            )
        )

    def _update_raw_text(self) -> None:
        assert self.loaded is not None
        loaded = self.loaded

        pi1_packed = load_packed(loaded.resource.pi1_path)
        lines = [
            f"PI1 packed file: {loaded.resource.pi1_path.name}",
            f"  packed size:   {pi1_packed.packed_size}",
            f"  unpacked size: {pi1_packed.unpacked_size}",
            f"  first 64 bytes: {pi1_packed.data[:64].hex(' ')}",
            "",
            "Palette words:",
            "  " + " ".join(f"{word:04X}" for word in loaded.pi1.palette_words),
            "",
        ]

        if loaded.atlas is not None and loaded.resource.dat_path is not None:
            dat_packed = load_packed(loaded.resource.dat_path)
            lines.extend(
                [
                    f"DAT packed file: {loaded.resource.dat_path.name}",
                    f"  packed size:   {dat_packed.packed_size}",
                    f"  unpacked size: {dat_packed.unpacked_size}",
                    f"  atlas records: {loaded.atlas.count}",
                    "",
                    "First atlas records:",
                ]
            )
            for record in loaded.atlas.records[:24]:
                lines.append(
                    f"  #{record.index:03d}: "
                    f"{record.width:3d}×{record.height:3d} "
                    f"at ({record.x:3d}, {record.y:3d}), "
                    f"unknown=0x{record.unknown:04X}"
                )
        else:
            lines.append("No paired packed DAT atlas was found for this PI1 screen.")

        self.raw_text.delete("1.0", tk.END)
        self.raw_text.insert("1.0", "\n".join(lines))
