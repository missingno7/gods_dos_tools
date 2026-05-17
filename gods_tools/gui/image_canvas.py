from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

from gods_tools.render.levels import CanvasOverlay


class ImageCanvas(ttk.Frame):
    """Scrollable image preview with fixed zoom choices."""

    def __init__(self, master: tk.Misc, initial_zoom: int = 2) -> None:
        super().__init__(master)
        self._pil_image: Image.Image | None = None
        self._photo: ImageTk.PhotoImage | None = None
        self._image_item: int | None = None
        self._zoom = tk.IntVar(value=max(1, int(initial_zoom)))
        self._click_callback = None
        self._double_click_callback = None
        self._hover_callback = None
        self._overlay: CanvasOverlay | None = None

        toolbar = ttk.Frame(self)
        toolbar.pack(side=tk.TOP, fill=tk.X)
        ttk.Label(toolbar, text="Zoom").pack(side=tk.LEFT, padx=(0, 6))
        for value in (1, 2, 3, 4):
            ttk.Radiobutton(
                toolbar,
                text=f"{value}×",
                value=value,
                variable=self._zoom,
                command=self._redraw,
            ).pack(side=tk.LEFT)

        canvas_frame = ttk.Frame(self)
        canvas_frame.pack(side=tk.TOP, fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, background="#161616", highlightthickness=0)
        xscroll = ttk.Scrollbar(canvas_frame, orient=tk.HORIZONTAL, command=self.canvas.xview)
        yscroll = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=xscroll.set, yscrollcommand=yscroll.set)

        self.canvas.grid(row=0, column=0, sticky="nsew")
        yscroll.grid(row=0, column=1, sticky="ns")
        xscroll.grid(row=1, column=0, sticky="ew")
        canvas_frame.rowconfigure(0, weight=1)
        canvas_frame.columnconfigure(0, weight=1)

        self.canvas.bind("<ButtonPress-2>", self._scan_mark)
        self.canvas.bind("<B2-Motion>", self._scan_drag)
        self.canvas.bind("<ButtonPress-3>", self._scan_mark)
        self.canvas.bind("<B3-Motion>", self._scan_drag)
        self.canvas.bind("<Button-1>", self._on_left_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_left_click)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)

    def set_image(self, image: Image.Image | None) -> None:
        self._pil_image = image
        self._redraw()

    def set_click_callback(self, callback) -> None:
        self._click_callback = callback

    def set_double_click_callback(self, callback) -> None:
        self._double_click_callback = callback

    def set_hover_callback(self, callback) -> None:
        self._hover_callback = callback

    def set_overlay(self, overlay: CanvasOverlay | None) -> None:
        self._overlay = overlay
        self._redraw()

    def center_on_pixel(self, image_x: int, image_y: int) -> None:
        """Center the scrollable viewport on a source-image pixel when possible."""

        if self._pil_image is None:
            return
        zoom = max(1, int(self._zoom.get()))
        target_x = max(0, int(image_x) * zoom)
        target_y = max(0, int(image_y) * zoom)
        image_width = max(1, self._pil_image.width * zoom)
        image_height = max(1, self._pil_image.height * zoom)

        self.canvas.update_idletasks()
        viewport_width = max(1, self.canvas.winfo_width())
        viewport_height = max(1, self.canvas.winfo_height())
        scroll_x = max(0, min(image_width - viewport_width, target_x - viewport_width // 2))
        scroll_y = max(0, min(image_height - viewport_height, target_y - viewport_height // 2))
        self.canvas.xview_moveto(scroll_x / image_width if image_width > viewport_width else 0.0)
        self.canvas.yview_moveto(scroll_y / image_height if image_height > viewport_height else 0.0)


    def _event_to_image_xy(self, event: tk.Event) -> tuple[int, int] | None:
        if self._pil_image is None:
            return None
        zoom = max(1, int(self._zoom.get()))
        canvas_x = int(self.canvas.canvasx(event.x))
        canvas_y = int(self.canvas.canvasy(event.y))
        return (canvas_x // zoom, canvas_y // zoom)

    def _on_left_click(self, event: tk.Event) -> None:
        if self._click_callback is None:
            return
        coords = self._event_to_image_xy(event)
        if coords is None:
            return
        self._click_callback(*coords)

    def _on_double_left_click(self, event: tk.Event) -> None:
        if self._double_click_callback is None:
            return
        coords = self._event_to_image_xy(event)
        if coords is None:
            return
        self._double_click_callback(*coords)

    def _on_motion(self, event: tk.Event) -> None:
        if self._hover_callback is None:
            return
        coords = self._event_to_image_xy(event)
        if coords is None:
            return
        self._hover_callback(*coords)

    def _on_leave(self, _event: tk.Event) -> None:
        if self._hover_callback is not None:
            self._hover_callback(None, None)

    def _scan_mark(self, event: tk.Event) -> None:
        self.canvas.scan_mark(event.x, event.y)

    def _scan_drag(self, event: tk.Event) -> None:
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def _redraw(self) -> None:
        self.canvas.delete("all")
        self._photo = None
        self._image_item = None

        if self._pil_image is None:
            self.canvas.configure(scrollregion=(0, 0, 1, 1))
            return

        zoom = max(1, int(self._zoom.get()))
        image = self._pil_image
        if zoom != 1:
            image = image.resize((image.width * zoom, image.height * zoom), Image.Resampling.NEAREST)

        self._photo = ImageTk.PhotoImage(image)
        self._image_item = self.canvas.create_image(0, 0, anchor="nw", image=self._photo)
        self._draw_overlay(zoom)
        self.canvas.configure(scrollregion=(0, 0, image.width, image.height))

    def _draw_overlay(self, zoom: int) -> None:
        if self._overlay is None:
            return
        for line in self._overlay.lines:
            x1 = line.start_x * zoom
            y1 = line.start_y * zoom
            x2 = line.end_x * zoom
            y2 = line.end_y * zoom
            kwargs = {"fill": self._rgba_to_hex(line.color), "width": line.width}
            if line.dashed:
                kwargs["dash"] = (6, 4)
            self.canvas.create_line(x1, y1, x2, y2, **kwargs, tags=("overlay",))
        for rect in self._overlay.rectangles:
            self._draw_rectangle(rect, zoom)
        for marker in self._overlay.markers:
            self._draw_marker(marker, zoom)

    def _draw_rectangle(self, rect, zoom: int) -> None:
        color = self._rgba_to_hex(rect.color)
        self.canvas.create_rectangle(rect.x0 * zoom, rect.y0 * zoom, rect.x1 * zoom, rect.y1 * zoom, outline=color, width=rect.width, tags=("overlay",))
        if rect.label:
            self._draw_label(rect.x0 * zoom + 4, rect.y0 * zoom + 2, rect.label, color)

    def _draw_marker(self, marker, zoom: int) -> None:
        x = marker.x * zoom
        y = marker.y * zoom
        color = self._rgba_to_hex(marker.color)
        shape = marker.shape
        if shape == "cell":
            half_w = (32 * zoom) // 2
            half_h = (16 * zoom) // 2
            self.canvas.create_rectangle(x - half_w, y - half_h, x + half_w - 1, y + half_h - 1, outline=color, width=2, tags=("overlay",))
        elif shape == "square":
            self.canvas.create_rectangle(x - 6, y - 6, x + 6, y + 6, outline=color, width=2, tags=("overlay",))
        elif shape == "triangle":
            self.canvas.create_polygon(x, y - 7, x + 7, y + 6, x - 7, y + 6, outline=color, fill="", width=2, tags=("overlay",))
        elif shape == "diamond":
            self.canvas.create_polygon(x, y - 7, x + 7, y, x, y + 7, x - 7, y, outline=color, fill="", width=2, tags=("overlay",))
        elif shape == "dot":
            self.canvas.create_oval(x - 3, y - 3, x + 3, y + 3, outline=color, fill=color, width=1, tags=("overlay",))
        elif shape == "label_only":
            pass
        else:
            radius = 10 if shape == "selected" else 6
            self.canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=color, width=2, tags=("overlay",))
        if marker.label:
            self._draw_label(x + 12, y - 10, marker.label, color)

    def _draw_label(self, x: int, y: int, text: str, color: str) -> None:
        text_id = self.canvas.create_text(x, y, anchor="nw", text=text, fill=color, font=("TkDefaultFont", 9, "bold"), tags=("overlay", "overlay_text"))
        bbox = self.canvas.bbox(text_id)
        if bbox is not None:
            rect = self.canvas.create_rectangle(bbox[0] - 2, bbox[1] - 1, bbox[2] + 2, bbox[3] + 1, fill="#101010", outline=color, width=1, tags=("overlay",))
            self.canvas.tag_lower(rect, text_id)

    @staticmethod
    def _rgba_to_hex(color) -> str:
        r, g, b = color[:3]
        return f"#{r:02x}{g:02x}{b:02x}"
