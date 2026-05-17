from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, defaultdict

from .alfils import AlfilsData
from .logic import LogicGraph
from .map import GodsMap


@dataclass(frozen=True)
class DiagnosticItem:
    severity: str  # INFO / WARN
    code: str
    message: str


@dataclass(frozen=True)
class LevelDiagnostics:
    items: tuple[DiagnosticItem, ...]
    stats: tuple[tuple[str, int], ...]

    @property
    def warning_count(self) -> int:
        return sum(item.severity == "WARN" for item in self.items)

    @property
    def info_count(self) -> int:
        return sum(item.severity == "INFO" for item in self.items)

    def render_text(self) -> str:
        lines = [
            "Level diagnostics",
            "=================",
            "",
            f"Warnings: {self.warning_count}",
            f"Info:     {self.info_count}",
            "",
            "Counts",
            "------",
        ]
        for name, value in self.stats:
            lines.append(f"{name}: {value}")
        lines.extend(["", "Findings", "--------"])
        if not self.items:
            lines.append("No diagnostics emitted.")
        else:
            for item in self.items:
                lines.append(f"[{item.severity}] {item.code}: {item.message}")
        return "\n".join(lines)


def build_level_diagnostics(map_data: GodsMap, alfils_data: AlfilsData, graph: LogicGraph) -> LevelDiagnostics:
    items: list[DiagnosticItem] = []

    # Events that exist in PALFILS but have no direct map cells and are not triggered by a puzzle.
    triggered_by_puzzle = {
        edge.target.index
        for edge in graph.all_edges
        if edge.edge_kind == "puzzle_effect"
        and edge.target.kind in {"event_cell", "event_effect"}
        and edge.target.index is not None
    }
    unreachable_events = [
        event.index
        for event in alfils_data.stored_events
        if event.index not in graph.event_cells and event.index not in triggered_by_puzzle
    ]
    if unreachable_events:
        items.append(
            DiagnosticItem(
                "INFO",
                "stored-events-without-entry",
                "Stored PALFILS event slots with no map trigger and no decoded TriggerEvent incoming link: "
                + ", ".join(f"E{index}" for index in unreachable_events[:40])
                + (" …" if len(unreachable_events) > 40 else ""),
            )
        )

    incoming_events_by_puzzle: dict[int, set[int]] = defaultdict(set)
    for edge in graph.all_edges:
        if edge.edge_kind != "event_target":
            continue
        if edge.target.kind != "puzzle" or edge.target.index is None:
            continue
        if edge.source.index is not None:
            incoming_events_by_puzzle[edge.target.index].add(edge.source.index)

    active_puzzles = {puzzle.index for puzzle in map_data.active_puzzles}
    orphan_puzzles = sorted(active_puzzles - set(incoming_events_by_puzzle))
    if orphan_puzzles:
        items.append(
            DiagnosticItem(
                "INFO",
                "active-puzzles-without-event",
                "Active puzzle records without decoded CheckPuzzle event incoming link: "
                + ", ".join(f"P{index}" for index in orphan_puzzles[:40])
                + (" …" if len(orphan_puzzles) > 40 else ""),
            )
        )

    multi_event_puzzles = {
        puzzle_index: sorted(event_indices)
        for puzzle_index, event_indices in incoming_events_by_puzzle.items()
        if len(event_indices) > 1
    }
    if multi_event_puzzles:
        preview = "; ".join(
            f"P{puzzle}= " + ",".join(f"E{event}" for event in events)
            for puzzle, events in list(sorted(multi_event_puzzles.items()))[:20]
        )
        items.append(
            DiagnosticItem(
                "INFO",
                "puzzles-evaluated-by-multiple-events",
                preview + (" …" if len(multi_event_puzzles) > 20 else ""),
            )
        )

    teleport_bound = {
        edge.target.index
        for edge in graph.all_edges
        if edge.edge_kind == "teleport_binding"
        and edge.target.kind == "teleport"
        and edge.target.index is not None
    }
    unbound_teleports = [record.index for record in alfils_data.active_teleports if record.index not in teleport_bound]
    if unbound_teleports:
        items.append(
            DiagnosticItem(
                "INFO",
                "unbound-teleport-rows",
                "Populated PALFILS teleport rows without a fixed decoded teleport-stone source in this world: "
                + ", ".join(f"T{index}" for index in unbound_teleports[:40])
                + (" …" if len(unbound_teleports) > 40 else ""),
            )
        )

    referenced_moving_actions: set[tuple[int, int]] = set()
    opaque_referenced: list[str] = []
    for event in alfils_data.active_events:
        if event.event_type_index is None or not (6 <= event.event_type_index <= 9):
            continue
        action_index = event.event_type_index - 6
        referenced_moving_actions.add((event.param, action_index))
        if 0 <= event.param < len(alfils_data.moving_blocks):
            block = alfils_data.moving_blocks[event.param]
            if block.action_kind(action_index) == "opaque_unreferenced_raw":
                opaque_referenced.append(f"MB{event.param}/A{action_index}@E{event.index}")
    if opaque_referenced:
        items.append(
            DiagnosticItem(
                "WARN",
                "opaque-referenced-moving-block-actions",
                "Unexpected moving-block raw actions are actually referenced: " + ", ".join(opaque_referenced),
            )
        )

    unused_action_slots = []
    for block in alfils_data.active_moving_blocks:
        for action_index in range(4):
            if (block.index, action_index) not in referenced_moving_actions:
                unused_action_slots.append(f"MB{block.index}/A{action_index}")
    if unused_action_slots:
        items.append(
            DiagnosticItem(
                "INFO",
                "unused-moving-block-action-slots",
                "Unused moving-block action slots: "
                + ", ".join(unused_action_slots[:60])
                + (" …" if len(unused_action_slots) > 60 else ""),
            )
        )

    # Extra integrity snapshots useful while cleaning the project.
    edge_counts = Counter(edge.edge_kind for edge in graph.all_edges)
    stats = (
        ("Active events", len(alfils_data.active_events)),
        ("Stored events", len(alfils_data.stored_events)),
        ("Active puzzles", len(map_data.active_puzzles)),
        ("Graph edges", len(graph.all_edges)),
        ("Chest-key links", edge_counts.get("chest_key_binding", 0)),
        ("Reveal-clue hint links", edge_counts.get("hint_binding", 0)),
        ("Teleport bindings", edge_counts.get("teleport_binding", 0)),
        ("Unbound teleport rows", len(unbound_teleports)),
        ("Unused moving-block action slots", len(unused_action_slots)),
    )
    return LevelDiagnostics(items=tuple(items), stats=stats)
