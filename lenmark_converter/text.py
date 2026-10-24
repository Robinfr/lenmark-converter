"""Native text serialization for the observed EMD 3.0 grammar.

Field order and widths follow CSGeometry.dll's x64 Serialize routines.  Text
stays editable; cached glyph geometry and transforms are copied, not rendered.
"""

from __future__ import annotations

import math
import struct
from typing import Any


TEXT_PREFIX = (
    *((key, "B") for key in range(201, 207)),
    (207, "d"), (208, "d"), (209, "B"), (210, "d"), (211, "B"),
    (212, "d"), (213, "s"), (214, "d"), (215, "d"), (216, "B"),
)
ARC_PREFIX = (
    *((key, "B") for key in range(201, 208)),
    *((key, "d") for key in range(208, 216)),
)
STATIC_TEXT_TYPE = 2


def _read_fields(cursor: Any, specs: Any) -> list[tuple[str, Any]]:
    fields = []
    for key, fmt in specs:
        raw = cursor.field(key)
        if fmt == "s":
            value = raw
        elif fmt == "d":
            value = float(raw)
            if not math.isfinite(value):
                raise ValueError(f"non-finite Text field {key}")
        else:
            value = int(raw)
            if fmt == "B" and not 0 <= value <= 255:
                raise ValueError(f"Text field {key} must fit an unsigned byte")
        fields.append((fmt, value))
    return fields


def _write_fields(writer: Any, fields: Any) -> None:
    for fmt, value in fields:
        if fmt == "s":
            writer.mfc(value)
        else:
            writer.pack(fmt, value)


def _raw_text(cursor: Any, tag: int) -> bytes:
    """Read the observed raw-string framing, retaining embedded CR/LF bytes.

    EMD uses a separate ``  0`` line after a raw string in all observed text
    records.  Other metadata/escaping variants are deliberately unsupported.
    A payload containing this terminator itself is ambiguous in this grammar.
    """
    cursor.expect(str(tag).encode("ascii"))
    lines = []
    for _ in range(100_000):
        line = cursor.pop()
        if line == b"  0":
            return b"\n".join(lines)
        if not line and not lines:
            # Empty strings are represented by one empty physical line.
            lines.append(line)
        elif line in (b"ProcessRepeatEnd", b"VariableTextEnd", b"TextEnd", b"ENDSEC"):
            raise ValueError(f"unsupported raw Text framing after tag {tag}")
        else:
            lines.append(line)
    raise ValueError("raw Text payload exceeds 100000 lines")


def _process_repeat(c: Any) -> None:
    c.cursor.expect(b"ProcessRepeat")
    values = _read_fields(c.cursor, ((key, "i") for key in range(201, 206)))
    source = _raw_text(c.cursor, 206)
    c.cursor.expect(b"ProcessRepeatEnd")
    # The old grammar has no observed array records; do not fabricate one for
    # active repeat processing whose exact legacy representation is unknown.
    if values[0][1] != 0:
        raise ValueError("active ProcessRepeat text is unsupported")
    _write_fields(c.writer, values)
    c.writer.mfc(source)
    c.writer.pack("q", 0)


def _read_point(cursor: Any, tag: int) -> list[tuple[str, Any]]:
    cursor.expect(str(tag).encode("ascii"))
    cursor.expect(b"CSPoint")
    point = _read_fields(cursor, ((key, "d") for key in range(201, 204)))
    cursor.expect(b"CSPointEnd")
    return point


def _static_text(c: Any) -> None:
    c.cursor.expect(b"StaticText")
    c.cursor.expect(b"VariableText")
    source = _raw_text(c.cursor, 201)
    c.cursor.expect(b"VariableTextEnd")
    c.cursor.expect(b"StaticTextEnd")
    c.writer.pack("i", STATIC_TEXT_TYPE)
    c.writer.mfc(source)


def _text(c: Any) -> None:
    c.atom()
    _process_repeat(c)
    prefix = _read_fields(c.cursor, TEXT_PREFIX)
    origin = _read_point(c.cursor, 217)
    c.cursor.expect(b"218")
    c.cursor.expect(b"Matrix3D")
    matrix = _read_fields(c.cursor, ((key, "d") for key in range(201, 217)))
    c.cursor.expect(b"Matrix3DEnd")
    source = _raw_text(c.cursor, 219)
    settings = _read_fields(c.cursor, ((key, "i") for key in range(220, 230)))
    bounds = _read_fields(c.cursor, ((key, "d") for key in range(230, 236)))

    _write_fields(c.writer, prefix)
    # The binary serializer places these six bounds before the origin/matrix;
    # the text serializer writes them after the ten integer settings.
    _write_fields(c.writer, bounds)
    origin_bytes = struct.pack("<3d", *(value for _, value in origin))
    c.writer.raw(origin_bytes)
    c.coordinate_hash.update(origin_bytes)
    c.counts["points"] += 1
    _write_fields(c.writer, matrix)
    c.writer.mfc(source)
    _write_fields(c.writer, settings)
    c.counted(lambda: _static_text(c), b"StaticText")
    c.counted(lambda: _line_or_character(c, b"LineText"), b"LineText")
    c.cursor.expect(b"TextEnd")


def _line_or_character(c: Any, kind: bytes) -> None:
    c.cursor.expect(kind)
    _line_body(c, kind)


def _line_body(c: Any, kind: bytes) -> None:
    c.atom()
    c.fields(((key, "d") for key in range(201, 205)))
    c.point_tag(205)
    if kind == b"LineText":
        c.counted(lambda: _line_or_character(c, b"Character"), b"Character")
    else:
        c.counted(c.segment, b"Segment")
    c.cursor.expect(kind + b"End")


def write_text(c: Any, kind: bytes) -> None:
    """Write a native text record after its opening marker was consumed."""
    if kind in (b"LineText", b"Character"):
        _line_body(c, kind)
        return
    if kind == b"Text":
        _text(c)
        return
    if kind != b"ArcText":
        raise ValueError(f"unsupported Text wrapper {kind!r}")
    c.cursor.expect(b"Text")
    _text(c)
    c.fields(ARC_PREFIX)
    c.bezier()
    extra_path = int(c.cursor.field(216))
    if extra_path not in (0, 1):
        raise ValueError("ArcText field 216 must be zero or one")
    c.writer.pack("i", extra_path)
    if extra_path:
        # This optional object is a second Bezier in the native serializer.
        c.bezier()
    values = _read_fields(c.cursor, (
        (217, "B"), (218, "B"), (219, "B"), (220, "B"),
        (221, "d"), (222, "d"),
    ))
    _write_fields(c.writer, values[:3])
    _write_fields(c.writer, values[4:])
    _write_fields(c.writer, values[3:4])
    c.cursor.expect(b"ArcTextEnd")
