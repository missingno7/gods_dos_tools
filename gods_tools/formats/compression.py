from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import dclimplode
except ImportError as exc:  # pragma: no cover - user-facing path
    dclimplode = None
    _DCL_IMPORT_ERROR = exc
else:
    _DCL_IMPORT_ERROR = None


class GodsCompressionError(RuntimeError):
    """Raised when a packed GODS resource cannot be decompressed."""


@dataclass(frozen=True)
class PackedResource:
    path: Path
    packed_size: int
    unpacked_size: int
    data: bytes


def dcl_unpack(data: bytes) -> bytes:
    """Unpack a GODS `P*` resource.

    DOS GODS uses PKWARE Data Compression Library (DCL) "implode" streams
    directly, without a wrapper that needs to be stripped. The first bytes of
    the stream are the DCL literal/dictionary mode bytes.
    """
    if dclimplode is None:  # pragma: no cover - depends on environment
        raise GodsCompressionError(
            "Missing dependency `dclimplode`. Install requirements.txt first."
        ) from _DCL_IMPORT_ERROR

    try:
        obj = dclimplode.decompressobj()
        return obj.decompress(data)
    except Exception as exc:  # pragma: no cover - library-specific error type
        raise GodsCompressionError(f"PKWARE DCL unpack failed: {exc}") from exc


def load_packed(path: str | Path) -> PackedResource:
    path = Path(path)
    packed = path.read_bytes()
    unpacked = dcl_unpack(packed)
    return PackedResource(
        path=path,
        packed_size=len(packed),
        unpacked_size=len(unpacked),
        data=unpacked,
    )
