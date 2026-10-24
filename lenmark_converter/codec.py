"""Streaming translation of text EMD geometry into x64 EMX records.

Numeric tags belong to individual record types, not a global namespace.
Every input field must be consumed; unknown layouts fail the whole file.
"""

from collections import Counter
from decimal import Decimal, InvalidOperation
import hashlib
import math
import struct


class FormatError(ValueError):
    """The input is unsupported or malformed."""


class Cursor:
    def __init__(self, stream):
        self.stream = stream
        self.line = 0
        self._peek = None

    def peek(self):
        if self._peek is None:
            raw = self.stream.readline()
            if not raw:
                raise FormatError(f"Unexpected end of file after line {self.line}")
            self._peek = raw.removesuffix(b"\n")
        return self._peek

    def pop(self):
        value = self.peek()
        self._peek = None
        self.line += 1
        return value

    def expect(self, expected):
        actual = self.pop().removesuffix(b"\r")
        if actual != expected:
            self.fail(f"Expected {expected!r}, found {actual[:100]!r}")

    def field(self, tag):
        line = self.pop().removesuffix(b"\r")
        prefix = str(tag).encode() + b":"
        if not line.startswith(prefix):
            self.fail(f"Expected field {tag}, found {line[:100]!r}")
        return line[len(prefix):]

    def fail(self, message):
        raise FormatError(f"Line {self.line}: {message}")


class Writer:
    def __init__(self, stream):
        self.stream = stream

    def raw(self, value):
        self.stream.write(value)

    def pack(self, fmt, *values):
        if any(isinstance(v, float) and not math.isfinite(v) for v in values):
            raise FormatError("Non-finite numeric value")
        try:
            self.raw(struct.pack("<" + fmt, *values))
        except (struct.error, OverflowError) as exc:
            raise FormatError(f"Value does not fit {fmt}: {values}") from exc

    def mfc(self, value):
        """Write an ANSI CString using MFC's variable-length prefix."""
        n = len(value)
        if n < 255:
            self.pack("B", n)
        elif n < 65534:
            self.pack("BH", 255, n)
        else:
            self.pack("BHI", 255, 65535, n)
        self.raw(value)

    def reserve(self, size):
        position = self.stream.tell()
        self.raw(bytes(size))
        return position

    def patch(self, position, fmt, *values):
        end = self.stream.tell()
        self.stream.seek(position)
        self.pack(fmt, *values)
        self.stream.seek(end)


class GeometryConverter:
    TYPES = {
        b"Group": 0, b"Rectangle": 5, b"Ellipse": 8, b"ArcText": 11,
        b"Bitmap": 13, b"Delay": 14, b"RRotate": 17, b"Segment": 26, b"Bezier": 27,
        b"MPLine": 29,
    }

    def __init__(self, cursor, writer):
        self.cursor = cursor
        self.writer = writer
        self.counts = Counter()
        self.coordinate_hash = hashlib.sha256()
        self.depth = 0

    def number(self, tag, fmt):
        value = self.cursor.field(tag)
        try:
            if fmt == "d":
                result = float(value)
            else:
                decimal = Decimal(value.decode("ascii"))
                if not decimal.is_finite() or decimal != decimal.to_integral_value():
                    raise ValueError("integer field is fractional")
                result = int(decimal)
        except (ValueError, InvalidOperation) as exc:
            self.cursor.fail(f"Invalid numeric field {tag}: {value[:80]!r}")
        if isinstance(result, float) and not math.isfinite(result):
            self.cursor.fail(f"Non-finite field {tag}")
        return result

    def fields(self, specs):
        for tag, fmt in specs:
            self.writer.pack(fmt, self.number(tag, fmt))

    def counted(self, callback, opening):
        position = self.writer.reserve(8)
        count = 0
        while self.cursor.peek().removesuffix(b"\r") == opening:
            callback()
            count += 1
        self.writer.patch(position, "q", count)
        return count

    def read_point(self):
        self.cursor.expect(b"CSPoint")
        values = tuple(self.number(tag, "d") for tag in (201, 202, 203))
        self.cursor.expect(b"CSPointEnd")
        return values

    def write_point(self, values):
        data = struct.pack("<3d", *values)
        self.writer.raw(data)
        self.coordinate_hash.update(data)
        self.counts["points"] += 1

    def point(self):
        self.write_point(self.read_point())

    def point_tag(self, tag):
        self.cursor.expect(str(tag).encode())
        self.point()

    def node(self):
        self.cursor.expect(b"BezierNode")
        flags = tuple(self.number(tag, "i") for tag in (201, 202))
        points = {}
        for tag in (203, 204, 205):
            self.cursor.expect(str(tag).encode())
            points[tag] = self.read_point()
        # Text tags are incoming handle, anchor, outgoing handle. The native
        # FILE archive stores anchor, incoming handle, outgoing handle.
        for tag in (204, 203, 205):
            self.write_point(points[tag])
        self.writer.pack("2i", *flags)
        self.cursor.expect(b"BezierNodeEnd")
        self.counts["bezier_nodes"] += 1

    def polyline(self):
        self.cursor.expect(b"Polyline")
        count = self.counted(self.point, b"CSPoint")
        self.cursor.expect(b"PolylineEnd")
        self.counts["polylines"] += 1

    def fill(self):
        self.cursor.expect(b"Fill")
        self.fields([(tag, "i") for tag in range(201, 205)])
        self.fields([(tag, "d") for tag in range(205, 212)])
        self.writer.pack("i", 0)  # New slot, default in native 3.7 samples.
        self.fields([(212, "i"), (213, "d"), (214, "i"), (215, "i"),
                     (216, "i"), (217, "d"), (218, "i"), (219, "i"), (220, "i")])
        self.writer.pack("i", 0)  # New trailing Fill option.
        self.counted(self.polyline, b"Polyline")
        self.cursor.expect(b"FillEnd")
        self.counts["fills"] += 1

    def entity(self):
        self.cursor.expect(b"Entity")
        kind = self.number(201, "i")
        self.writer.pack("i", kind)
        self.fields([(202, "i"), (203, "q"), (204, "i")])
        self.writer.pack("B", 0)  # No legacy optional metadata string.
        self.fields([(205, "i"), (206, "i"), (207, "q")])
        self.writer.mfc(self.cursor.field(208))
        self.fields([(tag, "d") for tag in range(209, 213)])
        z_position = self.writer.reserve(16)
        self.fields([(213, "i"), (214, "i"), (215, "i"), (216, "d"), (217, "d")])
        for tag in range(218, 223):
            self.point_tag(tag)
        self.cursor.expect(b"223")
        for _ in range(3):
            self.fill()
        zmin, zmax = self.number(224, "d"), self.number(225, "d")
        self.writer.patch(z_position, "2d", zmin, zmax)
        references = []
        while self.cursor.peek().startswith(b"226:"):
            references.append(self.number(226, "q"))
        self.writer.pack("q", len(references))
        for ref in references:
            self.writer.pack("q", ref)
        self.last_entity_attached = self.number(230, "i")
        self.writer.pack("i", self.last_entity_attached)
        self.cursor.expect(b"EntityEnd")
        self.counts["entities"] += 1
        self.counts[f"type_{kind}"] += 1
        return kind

    def atom(self):
        self.cursor.expect(b"AtomEntity")
        kind = self.entity()
        mapped = self.number(300, "i")
        if mapped not in (0, 1):
            self.cursor.fail(f"Unsupported mapped-geometry flag {mapped}")
        self.writer.pack("i", mapped)
        if mapped:
            self.mpline()
        self.fields([(301, "i")])
        self.cursor.expect(b"AtomEntityEnd")
        return kind

    def segment(self):
        self.cursor.expect(b"Segment")
        self.atom()
        self.fields([(201, "i")])
        self.counted(self.node, b"BezierNode")
        self.cursor.expect(b"SegmentEnd")

    def bezier(self):
        self.cursor.expect(b"Bezier")
        self.atom()
        self.counted(self.segment, b"Segment")
        self.cursor.expect(b"BezierEnd")

    def mpline(self):
        self.cursor.expect(b"MPLine")
        self.atom()
        self.writer.pack("i", 0)  # Parent type introduced after legacy format.
        self.counted(self.polyline, b"Polyline")
        self.cursor.expect(b"MPLineEnd")

    def rectangle(self):
        self.cursor.expect(b"Rectangle")
        self.atom()
        self.fields([(201, "d"), (202, "d"), (203, "d"), (204, "d"),
                     (205, "i"), (206, "d")])
        self.cursor.expect(b"207")
        for _ in range(8):
            self.node()
        self.cursor.expect(b"RectangleEnd")

    def group(self):
        self.cursor.expect(b"Group")
        self.entity()
        # Disk serialization uses SerializeEntityList, not the counted
        # SerializeList used by the application's in-memory serializer.
        self.writer.raw(b"SECTION\nENTITIES\nGeometryVersion:2\n")
        while self.cursor.peek().removesuffix(b"\r") != b"GroupEnd":
            wrapper = self.cursor.peek().removesuffix(b"\r")
            if wrapper not in self.TYPES:
                self.cursor.fail(f"Unsupported group child {wrapper[:80]!r}")
            self.writer.raw(wrapper + b"\n")
            self.object(wrapper)
        self.writer.raw(b"ENDSEC\n")
        self.cursor.expect(b"GroupEnd")

    def ellipse(self):
        self.cursor.expect(b"Ellipse")
        self.atom()
        self.fields([(201, "i"), (202, "d"), (203, "d"), (204, "d"), (205, "d")])
        flag = self.number(206, "i")
        self.point_tag(207)
        self.cursor.expect(b"208")
        for _ in range(6):
            self.node()
        self.writer.pack("i", flag)
        self.cursor.expect(b"209")
        for _ in range(4):
            self.node()
        self.cursor.expect(b"EllipseEnd")

    def object(self, wrapper):
        self.depth += 1
        if self.depth > 64:
            self.cursor.fail("Geometry nesting exceeds 64 levels")
        try:
            methods = {b"Group": self.group, b"Bezier": self.bezier,
                       b"Rectangle": self.rectangle, b"MPLine": self.mpline,
                       b"Ellipse": self.ellipse, b"Segment": self.segment}
            if wrapper in methods:
                methods[wrapper]()
            elif wrapper == b"ArcText":
                from .text import write_text
                self.cursor.expect(wrapper)
                write_text(self, wrapper)
            elif wrapper == b"Bitmap":
                from .bitmap import write_bitmap
                self.cursor.expect(wrapper)
                write_bitmap(self)
            elif wrapper in (b"Delay", b"RRotate"):
                self.cursor.expect(wrapper)
                self.entity()
                self.fields([(201, "i")] if wrapper == b"Delay" else [(201, "d"), (202, "i")])
                self.cursor.expect(wrapper + b"End")
            else:
                self.cursor.fail(f"Unsupported entity wrapper {wrapper[:80]!r}")
        finally:
            self.depth -= 1

    def convert(self):
        self.cursor.expect(b"GeometryVersion:2")
        self.writer.raw(b"GeometryVersion:2\n")
        while self.cursor.peek().removesuffix(b"\r") != b"ENDSEC":
            wrapper = self.cursor.peek().removesuffix(b"\r")
            if wrapper not in self.TYPES:
                self.cursor.fail(f"Unsupported entity wrapper {wrapper[:80]!r}")
            self.writer.raw(wrapper + b"\n")
            self.object(wrapper)
            self.counts["top_level_objects"] += 1
        self.cursor.expect(b"ENDSEC")
        self.writer.raw(b"ENDSEC\n")
        if self.cursor.stream.read(1):
            self.cursor.fail("Unexpected data after ENTITIES section")
        stats = {**self.counts, "coordinate_sha256": self.coordinate_hash.hexdigest()}
        if hasattr(self, "bitmap_bmp_sha256"):
            stats["bitmap_bmp_sha256"] = self.bitmap_bmp_sha256
            stats["conversion_notes"] = self.conversion_notes
        return stats
