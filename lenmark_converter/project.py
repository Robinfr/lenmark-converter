"""File framing and loss-detecting conversion of one project."""

from decimal import Decimal, InvalidOperation

from .codec import Cursor, FormatError, GeometryConverter, Writer
from .models import convert_models


MODEL_END = b"ENDSEC\nSECTION\nENTITIES\n"


def _copy_section(cursor, writer, name):
    cursor.expect(b"SECTION")
    cursor.expect(name)
    writer.raw(b"SECTION\n" + name + b"\n")
    seen = set()
    while cursor.peek().removesuffix(b"\r") != b"ENDSEC":
        line = cursor.pop().removesuffix(b"\r")
        try:
            tag, raw = line.split(b":", 1)
            tag = int(tag)
            value = int(raw)
        except ValueError:
            cursor.fail(f"Invalid {name.decode()} field {line[:80]!r}")
        if name != b"DOCINFO" or tag != 101 or tag in seen or not 0 <= value <= 0x7FFFFFFF:
            cursor.fail(f"Unsupported or duplicate {name.decode()} field {tag}")
        seen.add(tag)
        writer.raw(line + b"\n")
    if seen != {101}:
        cursor.fail("Missing DOCINFO field 101")
    cursor.expect(b"ENDSEC")
    writer.raw(b"ENDSEC\n")


def _parameters(cursor, writer):
    cursor.expect(b"SECTION")
    cursor.expect(b"PARAMETERS")
    writer.raw(b"SECTION\nPARAMETERS\n")
    seen = set()
    while cursor.peek().removesuffix(b"\r") != b"ENDSEC":
        line = cursor.pop().removesuffix(b"\r")
        try:
            prefix, number = line.split(b":", 1)
            pen = int(number)
        except ValueError:
            cursor.fail(f"Invalid layer declaration {line[:80]!r}")
        if prefix != b"Layer" or pen not in range(256) or pen in seen:
            cursor.fail(f"Invalid or duplicate layer {line[:80]!r}")
        seen.add(pen)
        writer.raw(line + b"\n")
        tags = set()
        while cursor.peek().removesuffix(b"\r") != b"LayerEnd":
            line = cursor.pop().removesuffix(b"\r")
            try:
                key, value = line.split(b":", 1)
                tag = int(key)
                if not value:
                    raise ValueError
                numeric = Decimal(value.decode("ascii"))
                if not numeric.is_finite():
                    raise ValueError
            except (ValueError, InvalidOperation):
                cursor.fail(f"Invalid pen setting {line[:80]!r}")
            if tag not in range(27):
                cursor.fail(f"Unsupported pen setting {tag}")
            if tag in tags:
                cursor.fail(f"Duplicate pen setting {tag}")
            tags.add(tag)
            writer.raw(line + b"\n")
        # Mark migrated saved values as explicit (18=0), rather than declaring
        # they equal the new machine's defaults. Native custom pens use zero.
        # New options 25/26 use native constructor defaults. Existing settings
        # are copied literally; no power/frequency/timing units are changed.
        for tag, value in ((18, 0), (25, 1), (26, 1)):
            if tag not in tags:
                writer.raw(f"{tag}:{value}\n".encode())
        cursor.expect(b"LayerEnd")
        writer.raw(b"LayerEnd\n")
    if not seen:
        cursor.fail("No pen settings found")
    cursor.expect(b"ENDSEC")
    writer.raw(b"ENDSEC\n")
    return len(seen)


def convert_stream(source, destination):
    """Convert to a seekable binary destination. Never owns either stream."""
    cursor, writer = Cursor(source), Writer(destination)
    cursor.expect(b"File Ver 3.0")
    writer.raw(b"File Ver 3.7\n")
    pens = _parameters(cursor, writer)
    _copy_section(cursor, writer, b"DOCINFO")
    cursor.expect(b"SECTION")
    cursor.expect(b"3DModel")
    cursor.expect(b"101")
    # Binary archive follows the last text line. Use the complete section
    # delimiter, not a short ENDSEC token that could occur inside model data.
    payload = bytearray()
    while not payload.endswith(MODEL_END):
        line = source.readline()
        if not line:
            raise FormatError("Missing 3DModel/ENTITIES section boundary")
        payload.extend(line)
        if len(payload) > 256 * 1024 * 1024:
            raise FormatError("3D model payload exceeds 256 MiB")
    model = convert_models(bytes(payload[:-len(MODEL_END)]))
    writer.raw(b"SECTION\n3DModel\n101\n" + model + MODEL_END)
    geometry = GeometryConverter(cursor, writer)
    stats = geometry.convert()
    return {"source_version": "3.0", "target_version": "3.7", "pens": pens,
            "model_bytes": len(model), **stats}
