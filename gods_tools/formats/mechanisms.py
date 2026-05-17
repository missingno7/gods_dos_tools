from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass

from .logic import LogicEdge, LogicGraph, LogicPoint


@dataclass(frozen=True)
class MechanismNarrative:
    title: str
    text: str


def _edge_key(edge: LogicEdge) -> tuple:
    return (
        edge.source.kind,
        edge.source.index,
        edge.source.pixel_x,
        edge.source.pixel_y,
        edge.source.label,
        edge.target.kind,
        edge.target.index,
        edge.target.pixel_x,
        edge.target.pixel_y,
        edge.target.label,
        edge.label,
        edge.edge_kind,
        edge.positive_state,
    )


def merge_edges(*groups: tuple[LogicEdge, ...] | list[LogicEdge]) -> tuple[LogicEdge, ...]:
    merged: list[LogicEdge] = []
    seen: set[tuple] = set()
    for group in groups:
        for edge in group:
            key = _edge_key(edge)
            if key in seen:
                continue
            seen.add(key)
            merged.append(edge)
    return tuple(merged)


def _point_phrase(point: LogicPoint) -> str:
    if point.kind in {"event_cell", "event_effect"} and point.index is not None:
        return f"event E{point.index}"
    if point.kind == "puzzle" and point.index is not None:
        return f"puzzle P{point.index}"
    if point.kind == "switch" and point.index is not None:
        return f"switch-state S{point.index}"
    if point.kind == "switch_item" and point.index is not None:
        return f"switch item {point.label}"
    if point.kind == "door":
        return f"door {point.label}"
    if point.kind == "trapdoor":
        return f"trapdoor {point.label}"
    if point.kind in {"backdoor", "backdoor_destination", "backdoor_world"}:
        return point.label
    if point.kind in {"spawned_object", "spawned_weapon"}:
        return point.label
    if point.kind in {"destructable_object", "destroy_type4_offmap", "destroy_type4_unresolved"}:
        return point.label
    if point.kind in {"walking_wave", "intel_walking_wave", "intel_flying_wave", "flying_wave"}:
        return point.label
    if point.kind == "moving_block":
        return point.label
    if point.kind == "teleport":
        return point.label
    if point.kind == "hint":
        return f"hint {point.label}"
    if point.kind == "player_start":
        return "player start"
    if point.kind in {
        "map_object_source",
        "spawned_object_source",
        "walking_reward_object",
        "intel_walking_reward_object",
        "intel_flying_reward_object",
        "flying_reward_object",
    }:
        return point.label
    return point.label


def _strip_prefix(text: str, prefix: str) -> str:
    return text[len(prefix):].strip() if text.startswith(prefix) else text


def _condition_phrase(edge: LogicEdge) -> str:
    name = _strip_prefix(edge.label, "condition")
    source = _point_phrase(edge.source)
    # The label already holds the game's semantic name; add a concise everyday phrasing where clear.
    if name == "SwitchOn":
        return f"{source} is ON"
    if name == "SwitchOff":
        return f"{source} is OFF"
    if name == "EventTriggered":
        return f"{source} has already triggered"
    if name == "EventNotTriggered":
        return f"{source} has not triggered yet"
    if name == "Carrying":
        return f"the player is carrying {source}"
    if name == "NotCarrying":
        return f"the player is not carrying {source}"
    if name == "Holding":
        return f"the player is holding {source}"
    if name == "NotHolding":
        return f"the player is not holding {source}"
    return f"{source} satisfies {name}"


def _effect_phrase(edge: LogicEdge) -> str:
    label = _strip_prefix(edge.label, "effect")
    if ":" in label:
        semantic, plain = [part.strip() for part in label.split(":", 1)]
        return f"{plain} → {_point_phrase(edge.target)} ({semantic})"
    return f"{label} → {_point_phrase(edge.target)}"


def _event_action_phrase(edge: LogicEdge) -> str:
    return f"{edge.label} → {_point_phrase(edge.target)}"


def _event_cells_text(graph: LogicGraph, event_index: int) -> str:
    cells = graph.event_cells.get(event_index, ())
    if not cells:
        return "effect-triggered only"
    preview = ", ".join(f"({x},{y})" for x, y in cells[:6])
    if len(cells) > 6:
        preview += ", …"
    return preview


def _event_indices(edges: tuple[LogicEdge, ...], root_events: tuple[int, ...]) -> tuple[int, ...]:
    indices = set(root_events)
    for edge in edges:
        for point in (edge.source, edge.target):
            if point.kind in {"event_cell", "event_effect"} and point.index is not None:
                indices.add(point.index)
    return tuple(sorted(indices))


def _puzzle_indices(edges: tuple[LogicEdge, ...]) -> tuple[int, ...]:
    indices: set[int] = set()
    for edge in edges:
        for point in (edge.source, edge.target):
            if point.kind == "puzzle" and point.index is not None:
                indices.add(point.index)
    return tuple(sorted(indices))


def _component_stats(edges: tuple[LogicEdge, ...], root_events: tuple[int, ...]) -> tuple[int, int, int, int]:
    event_count = len(_event_indices(edges, root_events))
    puzzle_count = len(_puzzle_indices(edges))
    condition_count = sum(edge.edge_kind == "puzzle_condition" for edge in edges)
    outcome_count = sum(edge.edge_kind in {"puzzle_effect", "event_target", "teleport_binding", "switch_binding"} for edge in edges)
    return event_count, puzzle_count, condition_count, outcome_count


def describe_component(
    graph: LogicGraph,
    *,
    title: str,
    selection_summary: str,
    edges: tuple[LogicEdge, ...],
    root_events: tuple[int, ...] = (),
) -> MechanismNarrative:
    """Convert a decoded logic component into a human-facing mechanism explanation."""

    edges = merge_edges(edges)
    events = _event_indices(edges, root_events)
    puzzles = _puzzle_indices(edges)
    event_count, puzzle_count, condition_count, outcome_count = _component_stats(edges, root_events)

    lines: list[str] = [
        title,
        "=" * len(title),
        "",
        selection_summary,
        "",
    ]

    if not edges and not events:
        lines.extend([
            "No decoded event/puzzle component is attached to this selection.",
            "It may be a purely visual object, a raw map item without logic, or a standalone path/resource.",
        ])
        return MechanismNarrative(title, "\n".join(lines))

    lines.extend([
        "At a glance",
        "-----------",
        f"Events involved:    {event_count}",
        f"Puzzles involved:   {puzzle_count}",
        f"Conditions checked: {condition_count}",
        f"Outcomes / links:    {outcome_count}",
        "",
    ])

    if events:
        lines.extend(["Entry points", "------------"])
        entry_preview = events[:18]
        for event_index in entry_preview:
            lines.append(f"• E{event_index}: {_event_cells_text(graph, event_index)}")
        if len(events) > len(entry_preview):
            lines.append(f"• … {len(events) - len(entry_preview)} more event entry points in this connected component")
        lines.append("")

    direct_actions_by_event: dict[int, list[str]] = defaultdict(list)
    puzzle_checks_by_event: dict[int, list[str]] = defaultdict(list)
    for edge in edges:
        if edge.edge_kind != "event_target":
            continue
        if edge.source.kind not in {"event_cell", "event_effect"} or edge.source.index is None:
            continue
        if edge.target.kind == "puzzle" and edge.target.index is not None:
            puzzle_checks_by_event[edge.source.index].append(f"P{edge.target.index}")
        else:
            direct_actions_by_event[edge.source.index].append(_event_action_phrase(edge))

    if direct_actions_by_event or puzzle_checks_by_event:
        lines.extend(["Event actions", "-------------"])
        for event_index in events:
            checks = puzzle_checks_by_event.get(event_index, [])
            actions = direct_actions_by_event.get(event_index, [])
            if checks:
                joined = ", ".join(dict.fromkeys(checks))
                lines.append(f"• E{event_index} evaluates {joined}.")
            for action in dict.fromkeys(actions):
                lines.append(f"• E{event_index} {action}.")
        lines.append("")

    if puzzles:
        incoming_by_puzzle: dict[int, list[str]] = defaultdict(list)
        conditions_by_puzzle: dict[int, list[str]] = defaultdict(list)
        effects_by_puzzle: dict[int, list[str]] = defaultdict(list)

        for edge in edges:
            if edge.edge_kind == "event_target" and edge.target.kind == "puzzle" and edge.target.index is not None:
                incoming_by_puzzle[edge.target.index].append(_point_phrase(edge.source))
            elif edge.edge_kind == "puzzle_condition" and edge.target.kind == "puzzle" and edge.target.index is not None:
                conditions_by_puzzle[edge.target.index].append(_condition_phrase(edge))
            elif edge.edge_kind == "puzzle_effect" and edge.source.kind == "puzzle" and edge.source.index is not None:
                effects_by_puzzle[edge.source.index].append(_effect_phrase(edge))

        lines.extend(["Puzzle stories", "--------------"])
        puzzle_preview = puzzles[:24]
        for puzzle_index in puzzle_preview:
            incoming = list(dict.fromkeys(incoming_by_puzzle.get(puzzle_index, [])))
            conditions = list(dict.fromkeys(conditions_by_puzzle.get(puzzle_index, [])))
            effects = list(dict.fromkeys(effects_by_puzzle.get(puzzle_index, [])))
            lead = f"P{puzzle_index}"
            if incoming:
                lead += " is evaluated from " + ", ".join(incoming)
            else:
                lead += " participates in this component"
            lines.append(f"• {lead}.")
            if conditions:
                lines.append("  Requires: " + "; ".join(conditions) + ".")
            else:
                lines.append("  Requires: no decoded extra condition beyond being evaluated.")
            if effects:
                lines.append("  If true:  " + "; ".join(effects) + ".")
            else:
                lines.append("  If true:  no decoded physical/global effect in this component.")
        if len(puzzles) > len(puzzle_preview):
            lines.append(f"• … {len(puzzles) - len(puzzle_preview)} more puzzles in this connected component")
        lines.append("")

    bindings = [edge for edge in edges if edge.edge_kind in {"switch_binding", "teleport_binding", "chest_key_binding", "hint_binding"}]
    if bindings:
        lines.extend(["Physical bindings", "-----------------"])
        for edge in bindings:
            lines.append(f"• {_point_phrase(edge.source)} → {_point_phrase(edge.target)}: {edge.label}.")
        lines.append("")

    lines.extend([
        "Reading tip",
        "-----------",
        "The Logic Inspector tab still shows the raw graph edges. This tab compresses the same component into a designer-facing mechanism story.",
    ])
    return MechanismNarrative(title, "\n".join(lines))


def describe_event_mechanism(graph: LogicGraph, event_index: int, recursive: bool = True) -> MechanismNarrative:
    edges = graph.related_edges_for_event(event_index, recursive=recursive)
    cells = _event_cells_text(graph, event_index)
    return describe_component(
        graph,
        title=f"Mechanism driven by event E{event_index}",
        selection_summary=f"Selected event E{event_index}. Trigger cells: {cells}.",
        edges=edges,
        root_events=(event_index,),
    )


def describe_point_mechanism(graph: LogicGraph, point: LogicPoint, recursive: bool = True) -> MechanismNarrative:
    edges = graph.related_edges_for_point(point, recursive=recursive)
    return describe_component(
        graph,
        title=f"Mechanism around {point.label}",
        selection_summary=f"Selected logic point {point.label} ({point.kind}) at ({point.pixel_x}, {point.pixel_y}).",
        edges=edges,
    )


def describe_map_item_mechanism(graph: LogicGraph, item_index: int, recursive: bool = True) -> MechanismNarrative:
    edges = graph.related_edges_for_map_item(item_index, recursive=recursive)
    points = graph.points_for_map_item(item_index)
    role_text = ", ".join(point.kind for point in points) if points else "no direct decoded graph role"
    return describe_component(
        graph,
        title=f"Mechanism around map item I{item_index}",
        selection_summary=f"Selected map item I{item_index}. Decoded graph roles: {role_text}.",
        edges=edges,
    )
