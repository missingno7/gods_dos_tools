from __future__ import annotations

import argparse
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from .graphics_viewer import GraphicsViewer
from .level_viewer import LevelViewer


def default_game_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "game_data" / "Gods"


class GodsToolsApp(tk.Tk):
    def __init__(self, game_dir: Path) -> None:
        super().__init__()
        self.game_dir = game_dir

        self.title("DOS GODS Reverse Engineering Toolkit")
        self.geometry("1280x860")
        self.minsize(960, 640)

        self._build_menu()
        self._build_tabs()

    def _build_menu(self) -> None:
        menu = tk.Menu(self)
        view_menu = tk.Menu(menu, tearoff=False)
        view_menu.add_command(label="Graphics Viewer", command=lambda: self.tabs.select(0))
        view_menu.add_command(label="Level Viewer", command=lambda: self.tabs.select(1))
        menu.add_cascade(label="View", menu=view_menu)
        self.config(menu=menu)

    def _build_tabs(self) -> None:
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill=tk.BOTH, expand=True)

        graphics_tab = GraphicsViewer(self.tabs, self.game_dir)
        level_tab = LevelViewer(self.tabs, self.game_dir)

        self.tabs.add(graphics_tab, text="Graphics Viewer")
        self.tabs.add(level_tab, text="Level Viewer")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DOS GODS graphics/level analysis toolkit.")
    parser.add_argument(
        "--game-dir",
        type=Path,
        default=default_game_dir(),
        help="Directory containing the DOS GODS files. Defaults to bundled game_data/Gods.",
    )
    return parser


def main() -> None:
    args = build_arg_parser().parse_args()
    game_dir = args.game_dir.resolve()
    if not game_dir.exists():
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("DOS GODS tools", f"Game directory does not exist:\n{game_dir}")
        root.destroy()
        raise SystemExit(2)

    app = GodsToolsApp(game_dir)
    app.mainloop()
