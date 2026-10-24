"""Independent, bounded reader for the supported EMX 3.7 geometry archive.

This checks binary framing and records a coordinate fingerprint. It does not
claim that LenMark has accepted a document or that machine settings are safe.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
import hashlib
import math
import mmap
from pathlib import Path
import struct


class InvalidEmx(ValueError):
    """The file is truncated, malformed, or outside the verified subset."""


NAMES = {0: "Group", 5: "Rectangle", 8: "Ellipse", 11: "ArcText", 13: "Bitmap",
         14: "Delay", 17: "RRotate", 26: "Segment", 27: "Bezier", 29: "MPLine"}
FILL_FORMAT = "<4i7d2id3id4i"


@dataclass(frozen=True)
class NativeBezierNode:
    """Native FILE slots are anchor, incoming handle, outgoing handle.

    EMD ReadText assigns tags204,203,205 respectively to those members;
    tag order is therefore different from native binary serialization order.
    """

    anchor: tuple[float, float, float]
    incoming: tuple[float, float, float]
    outgoing: tuple[float, float, float]
    flags: tuple[int, int]


def cubic_point(start: NativeBezierNode, end: NativeBezierNode, t: float):
    """Evaluate the cubic control polygon in native node-slot order.

    This geometry audit intentionally evaluates handles independently of any
    display/marking mode flags; it does not emulate LenMark's renderer.
    """
    if not math.isfinite(t) or not 0 <= t <= 1:
        raise ValueError("Cubic evaluation requires finite t between 0 and 1")
    u = 1 - t
    weights = (u * u * u, 3 * u * u * t, 3 * u * t * t, t * t * t)
    points = (start.anchor, start.outgoing, end.incoming, end.anchor)
    return tuple(sum(weight * point[axis] for weight, point in zip(weights, points))
                 for axis in range(3))


class GeometryReader:
    """Consume one EMX ENTITIES body without relying on the converter writer."""

    def __init__(self, data, offset: int = 0, limit: int | None = None):
        self.data = data
        self.offset = offset
        self.limit = len(data) if limit is None else limit
        self.counts: Counter[str] = Counter()
        self.source_counts: Counter[str] = Counter()
        self.points_hash = hashlib.sha256()
        self.paths_hash = hashlib.sha256()
        self.points_count = 0
        self.pens: set[int] = set()
        self.ids: set[int] = set()
        self.max_depth = 0
        self.bitmap_bmp_sha256: list[str] = []

    def fail(self, message: str):
        raise InvalidEmx(f"{message} at byte {self.offset}")

    def raw(self, size: int) -> bytes:
        if size < 0 or self.offset + size > self.limit:
            self.fail(f"truncated record: need {size} bytes")
        result = self.data[self.offset:self.offset + size]
        self.offset += size
        return result

    def unpack(self, fmt: str) -> tuple:
        fmt = "<" + fmt.lstrip("<")
        size = struct.calcsize(fmt)
        if self.offset + size > self.limit:
            self.fail(f"truncated {fmt} value")
        values = struct.unpack_from(fmt, self.data, self.offset)
        self.offset += size
        for value in values:
            if isinstance(value, float) and not math.isfinite(value):
                self.fail("non-finite coordinate or setting")
        return values

    def scalar(self, fmt: str):
        return self.unpack(fmt)[0]

    def count(self, minimum_item_size: int, label: str) -> int:
        count = self.scalar("q")
        if count < 0 or count > (self.limit - self.offset) // minimum_item_size:
            self.fail(f"invalid {label} count {count}")
        return count

    def mfc(self) -> bytes:
        """Read the MFC ANSI CString length encoding (including long strings)."""
        length = self.scalar("B")
        width = 1
        if length == 0xFF:
            length = self.scalar("H")
            if length == 0xFFFE:
                width = 2
                length = self.scalar("B")
                if length == 0xFF:
                    length = self.scalar("H")
                    if length == 0xFFFF:
                        length = self.scalar("I")
            elif length == 0xFFFF:
                length = self.scalar("I")
        return self.raw(length * width)

    def point(self, *, path: bool = False):
        pos = self.offset
        value = self.unpack("3d")
        raw = self.data[pos:self.offset]
        self.points_hash.update(raw)
        if path:
            self.paths_hash.update(raw)
        self.points_count += 1
        self.source_counts["points"] += 1
        return value

    def polyline(self, *, hatch: bool):
        count = self.count(24, "polyline point")
        self.paths_hash.update(struct.pack("<q", count))
        self.counts["hatch_paths" if hatch else "mapped_paths"] += 1
        self.source_counts["polylines"] += 1
        for _ in range(count):
            self.point(path=True)

    def fill(self):
        fields = self.unpack(FILL_FORMAT)
        self.counts["Fill"] += 1
        self.source_counts["fills"] += 1
        self.pens.add(fields[3])
        if fields[0]:
            self.counts["active_fills"] += 1
        count = self.count(8, "hatch path")
        for _ in range(count):
            self.polyline(hatch=True)

    def entity(self, expected_type: int | None = None):
        type_id, pen, object_id, _, metadata = self.unpack("iiqiB")
        if expected_type is not None and type_id != expected_type:
            self.fail(f"entity type {type_id} does not match {expected_type}")
        if metadata not in (0, 1):
            self.fail(f"invalid entity metadata flag {metadata}")
        if metadata:
            self.mfc()
        self.unpack("iiq")  # ID counter, outline mode, attachment mode
        self.mfc()  # display name
        self.unpack("6d3i2d")  # evaluated bounds and cached display settings
        for _ in range(5):
            self.point()
        for _ in range(3):
            self.fill()
        count = self.count(8, "model reference")
        self.raw(count * 8)
        self.unpack("i")  # mapped / parent flag
        self.pens.add(pen)
        self.source_counts["entities"] += 1
        self.source_counts[f"type_{type_id}"] += 1
        if object_id >= 0:
            self.ids.add(object_id)
        return type_id

    def atom(self, expected_type: int, depth: int):
        self.entity(expected_type)
        mapped = self.scalar("i")
        if mapped not in (0, 1):
            self.fail(f"invalid mapped-geometry flag {mapped}")
        if mapped:
            self.record(29, depth + 1)
        self.unpack("i")

    def node(self):
        self.counts["BezierNode"] += 1
        self.source_counts["bezier_nodes"] += 1
        anchor = self.point()
        incoming = self.point()
        outgoing = self.point()
        flags = self.unpack("2i")
        return NativeBezierNode(anchor, incoming, outgoing, flags)

    def bitmap(self):
        """Read CS_Dib geometry/settings and its embedded uncompressed BMP.

        Raster caches from old EMD files are deliberately absent in native EMX;
        the BMP is the independently checksummed image source.
        """
        self.entity(13)
        self.point()
        self.unpack("6d")
        width, height, original_width, original_height = self.unpack("4i")
        if min(width, height, original_width, original_height) <= 0:
            self.fail("invalid bitmap dimensions")
        self.unpack("5i3d9i2B")
        for _ in range(11):
            self.unpack("Bf")
        rows, columns = self.unpack("2i")
        if rows < 0 or columns < 0:
            self.fail("negative raster dimensions")
        if rows != height or columns != width:
            self.fail("raster dimensions do not match bitmap processing dimensions")
        start = self.offset
        signature, size, _, _, pixel_offset = self.unpack("2sIHHI")
        if signature != b"BM" or size < 54 or not 54 <= pixel_offset <= size:
            self.fail("invalid BMP file header")
        payload = self.raw(size - 14)
        (header_size, bmp_width, bmp_height, planes, bits, compression,
         image_size, _, _, colors, _) = struct.unpack_from("<IiiHHIIiiII", payload)
        if header_size != 40 or planes != 1:
            self.fail("unsupported BMP information header")
        if bmp_width <= 0 or bmp_height == 0 or bits not in (1, 4, 8, 16, 24, 32):
            self.fail("invalid BMP pixel layout")
        if compression != 0:
            self.fail("compressed BMP is outside the verified subset")
        stride = ((bmp_width * bits + 31) // 32) * 4
        required = stride * abs(bmp_height)
        if required > size - pixel_offset:
            self.fail("truncated BMP pixel data")
        if image_size not in (0, required):
            self.fail("BMP image-size field does not match its pixel layout")
        if bits <= 8:
            palette_colors = colors or (1 << bits)
            if palette_colors > 1 << bits or 54 + palette_colors * 4 > pixel_offset:
                self.fail("invalid BMP palette layout")
        if bmp_width != original_width or abs(bmp_height) != original_height:
            self.fail("BMP dimensions differ from stored original dimensions")
        self.bitmap_bmp_sha256.append(hashlib.sha256(self.data[start:self.offset]).hexdigest())
        self.source_counts["bitmap_images"] += 1
        self.source_counts["bitmap_bytes"] += size
        self.source_counts["bitmap_pixels"] += bmp_width * abs(bmp_height)
        self.source_counts["raster_pixels"] += rows * columns

    def text_helper(self, *, line: bool, depth: int):
        if depth > 128:
            self.fail("text nesting exceeds 128 records")
        self.counts["LineText" if line else "Character"] += 1
        self.atom(0, depth)
        self.unpack("4d")
        self.point()
        for _ in range(self.count(4, "text helper")):
            if line:
                self.text_helper(line=False, depth=depth + 1)
            else:
                self.record(26, depth + 1)

    def text(self, depth: int):
        self.atom(11, depth)
        self.unpack("5i")  # ProcessRepeat scalar fields
        self.mfc()
        repeats = self.count(8, "repeat offset")
        if repeats:
            self.fail("nonempty repeat offsets are outside the text subset")
        self.unpack("6B2dBdBd")
        self.mfc()  # font name
        self.unpack("2dB")
        self.unpack("6d")  # Text bounds move ahead of origin in EMX
        self.point()
        self.unpack("16d")
        self.mfc()  # original editable source text
        self.unpack("10i")
        for _ in range(self.count(4, "variable text")):
            subtype = self.scalar("i")
            if subtype != 2:
                self.fail(f"unsupported variable text subtype {subtype}")
            self.mfc()
        for _ in range(self.count(4, "text line")):
            self.text_helper(line=True, depth=depth + 1)

    def arc_text(self, depth: int):
        self.text(depth)
        self.unpack("7B8d")
        self.record(27, depth + 1)
        extra = self.scalar("i")
        if extra not in (0, 1):
            self.fail(f"invalid second ArcText Bezier flag {extra}")
        if extra:
            self.record(27, depth + 1)
        self.unpack("3B2dB")

    def entity_section(self, depth: int):
        # FILE serialization (CS_Group::SerializeFile -> SerializeEntityList)
        # uses nested textual ENTITIES framing. The superficially similar
        # count + type-discriminator list belongs to in-memory Serialize only.
        framing = b"SECTION\nENTITIES\nGeometryVersion:2\n"
        if self.raw(len(framing)) != framing:
            self.fail("Group FILE children require a nested ENTITIES section")
        wrappers = {name.encode(): type_id for type_id, name in NAMES.items()}
        while True:
            end = self.data.find(b"\n", self.offset, min(self.limit, self.offset + 128))
            if end < 0:
                self.fail("missing nested entity wrapper or ENDSEC")
            wrapper = self.raw(end + 1 - self.offset)[:-1]
            if wrapper == b"ENDSEC":
                return
            if wrapper not in wrappers:
                self.fail(f"unsupported nested entity wrapper {wrapper!r}")
            self.record(wrappers[wrapper], depth + 1)

    def record(self, type_id: int | None = None, depth: int = 0):
        if depth > 128:
            self.fail("geometry nesting exceeds 128 records")
        self.max_depth = max(depth, self.max_depth)
        if type_id is None:
            if self.offset + 4 > self.limit:
                self.fail("missing entity type")
            type_id = struct.unpack_from("<i", self.data, self.offset)[0]
        name = NAMES.get(type_id)
        if name is None:
            self.fail(f"unsupported entity type {type_id}")
        self.counts[name] += 1
        if type_id == 11:
            self.arc_text(depth)
            return
        if type_id == 13:
            self.bitmap()
            return
        if type_id in (0, 14, 17):
            self.entity(type_id)
        else:
            self.atom(type_id, depth)
        if type_id == 0:
            self.entity_section(depth)
        elif type_id == 27:
            for _ in range(self.count(4, "Bezier segment")):
                self.record(26, depth + 1)
        elif type_id == 26:
            self.unpack("i")
            for _ in range(self.count(80, "Bezier node")):
                self.node()
        elif type_id == 29:
            self.unpack("i")  # MPLine parent type, added in recent releases
            for _ in range(self.count(8, "mapped path")):
                self.polyline(hatch=False)
        elif type_id == 5:
            self.unpack("4did")
            for _ in range(8):
                self.node()
        elif type_id == 8:
            self.unpack("i4d")
            self.point()
            for _ in range(6):
                self.node()
            self.unpack("i")
            for _ in range(4):
                self.node()
        elif type_id == 14:
            self.unpack("i")
        elif type_id == 17:
            self.unpack("di")

    def report(self) -> dict:
        return {
            **self.source_counts,
            "coordinate_sha256": self.points_hash.hexdigest(),
            "bitmap_bmp_sha256": self.bitmap_bmp_sha256,
            "counts": dict(sorted(self.counts.items())),
            "points": self.points_count,
            "points_sha256": self.points_hash.hexdigest(),
            "toolpaths_sha256": self.paths_hash.hexdigest(),
            "pens": sorted(self.pens),
            "persistent_ids": len(self.ids),
            "max_depth": self.max_depth,
        }


def verify_bytes(data) -> dict:
    """Verify a complete EMX and return JSON-compatible geometry statistics."""
    end_marker = b"ENDSEC\n"
    r = GeometryReader(data)

    def line() -> bytes:
        end = data.find(b"\n", r.offset, min(r.limit, r.offset + 4096))
        if end < 0:
            r.fail("missing or oversized text framing line")
        return r.raw(end + 1 - r.offset)[:-1]

    def expect(value: bytes):
        actual = line()
        if actual != value:
            r.fail(f"expected {value!r}, got {actual!r}")

    expect(b"File Ver 3.7")
    expect(b"SECTION")
    expect(b"PARAMETERS")
    while line() != b"ENDSEC":
        pass
    expect(b"SECTION")
    expect(b"DOCINFO")
    while line() != b"ENDSEC":
        pass
    expect(b"SECTION")
    expect(b"3DModel")
    expect(b"101")
    model_start = r.offset
    marker = b"ENDSEC\nSECTION\nENTITIES\nGeometryVersion:2\n"
    model_end = data.find(marker, model_start)
    if model_end < 0:
        r.fail("missing ENTITIES section after model archive")
    r.offset = model_end + len(marker)
    # Restrict binary reads to the geometry area, excluding its closing marker.
    if bytes(data[-len(end_marker):]) != end_marker:
        r.fail("missing final ENDSEC or unexpected trailing data")
    r.limit -= len(end_marker)
    top_level = 0
    wrappers = {name.encode(): type_id for type_id, name in NAMES.items()}
    while r.offset < r.limit:
        wrapper = line()
        if wrapper not in wrappers:
            r.fail(f"unsupported top-level wrapper {wrapper!r}")
        r.record(wrappers[wrapper])
        top_level += 1
    if r.offset != r.limit:
        r.fail("geometry record exceeds ENTITIES section")
    report = r.report()
    report.update({"file_version": "3.7", "geometry_version": 2,
                   "top_level_objects": top_level,
                   "model_bytes": model_end - model_start,
                   "geometry_bytes": r.limit - model_end - len(marker),
                   "validation": "binary geometry framing and finite numeric values"})
    return report


def verify_file(path: str | Path) -> dict:
    """Verify without loading the entire project into Python-managed memory."""
    with Path(path).open("rb") as stream:
        if not stream.seek(0, 2):
            raise InvalidEmx("empty EMX file")
        stream.seek(0)
        with mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as data:
            return verify_bytes(data)
