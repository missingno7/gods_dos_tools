from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


class PatchPlanError(ValueError):
    """Raised when a write-back plan is internally inconsistent or unsafe."""


@dataclass(frozen=True)
class RawBytePatch:
    """One exact modification against an unpacked source payload."""

    target: str  # currently 'map' or 'alfils'
    offset: int
    before: bytes
    after: bytes
    reason: str

    @property
    def end_offset(self) -> int:
        return self.offset + len(self.before)

    def validate_shape(self) -> None:
        if self.offset < 0:
            raise PatchPlanError(f"Patch offset cannot be negative: {self.offset}")
        if len(self.before) != len(self.after):
            raise PatchPlanError(
                f"Patch at 0x{self.offset:X} changes byte count {len(self.before)} -> {len(self.after)}; "
                "the first write-back stage intentionally supports in-place patches only."
            )


@dataclass(frozen=True)
class WriteBackPlan:
    """Auditable patch list before any future repack/save step is attempted."""

    patches: tuple[RawBytePatch, ...] = ()

    def with_patch(self, patch: RawBytePatch) -> "WriteBackPlan":
        candidate = WriteBackPlan(self.patches + (patch,))
        candidate.validate()
        return candidate

    def extend(self, patches: Iterable[RawBytePatch]) -> "WriteBackPlan":
        candidate = WriteBackPlan(self.patches + tuple(patches))
        candidate.validate()
        return candidate

    def patches_for(self, target: str) -> tuple[RawBytePatch, ...]:
        return tuple(patch for patch in self.patches if patch.target == target)

    def validate(self) -> None:
        by_target: dict[str, list[RawBytePatch]] = {}
        for patch in self.patches:
            patch.validate_shape()
            by_target.setdefault(patch.target, []).append(patch)
        for target, patches in by_target.items():
            ordered = sorted(patches, key=lambda patch: (patch.offset, patch.end_offset))
            previous: RawBytePatch | None = None
            for patch in ordered:
                if previous is not None and patch.offset < previous.end_offset:
                    raise PatchPlanError(
                        f"Overlapping {target} patches: 0x{previous.offset:X}-0x{previous.end_offset:X} "
                        f"and 0x{patch.offset:X}-0x{patch.end_offset:X}."
                    )
                previous = patch

    def apply_to_payload(self, target: str, payload: bytes) -> bytes:
        self.validate()
        mutable = bytearray(payload)
        for patch in sorted(self.patches_for(target), key=lambda item: item.offset):
            if patch.end_offset > len(mutable):
                raise PatchPlanError(
                    f"Patch at 0x{patch.offset:X} extends past {target} payload length {len(mutable)}."
                )
            actual = bytes(mutable[patch.offset:patch.end_offset])
            if actual != patch.before:
                raise PatchPlanError(
                    f"Patch precondition failed for {target} at 0x{patch.offset:X}: "
                    f"expected {patch.before.hex()}, found {actual.hex()}."
                )
            mutable[patch.offset:patch.end_offset] = patch.after
        return bytes(mutable)

    def render_text(self) -> str:
        if not self.patches:
            return "Write-back plan\n===============\n\nNo pending byte patches."
        lines = ["Write-back plan", "===============", ""]
        for index, patch in enumerate(self.patches, start=1):
            lines.extend([
                f"{index}. {patch.target}@0x{patch.offset:04X} ({len(patch.before)} bytes)",
                f"   before: {patch.before.hex(' ')}",
                f"   after:  {patch.after.hex(' ')}",
                f"   reason: {patch.reason}",
            ])
        return "\n".join(lines)
