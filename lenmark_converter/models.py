"""Translate the binary model archive embedded in LenMark 3.0 projects.

The old archive uses MFC runtime-class records and 32-bit model IDs. The
3.7 archive widens model IDs and adds CEntity transform state. Analytic
model bodies retain their layout; STL triangles become a flat binary array.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import struct


class UnsupportedModel(ValueError):
    """The model archive is malformed or contains an unmapped class/layout."""


_IDENTITY = struct.pack("<16d", 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1)
_BODY_SIZES = {b"CCone": 96, b"CCylinder": 104, b"CSphere": 60}
_MAX_COUNT = 1_000_000
_MAX_STRING = 1_048_576


@dataclass
class _Base:
    identifier: int
    name: bytes  # Complete CString archive encoding, retained byte for byte.
    appearance: bytes  # COLORREF and visibility, two 32-bit fields.


@dataclass
class _Model:
    class_name: bytes
    schema: int
    base: _Base
    body: bytes


class _Reader:
    def __init__(self, payload: bytes):
        self.payload = payload
        self.offset = 0
        # CArchive map index zero is the null pointer. Classes and objects
        # share one index sequence; the directly serialized root is unmapped.
        self.entries: list[object] = [None]

    def take(self, size: int) -> bytes:
        if size < 0 or size > len(self.payload) - self.offset:
            raise UnsupportedModel(f"Truncated model archive at byte {self.offset}")
        start = self.offset
        self.offset += size
        return self.payload[start:self.offset]

    def number(self, format_: str) -> int:
        return struct.unpack("<" + format_, self.take(struct.calcsize("<" + format_)))[0]

    def count(self) -> int:
        count = self.number("H")
        if count == 0xFFFF:
            count = self.number("I")
        if count > _MAX_COUNT:
            raise UnsupportedModel(f"Model list count exceeds {_MAX_COUNT}")
        return count

    def string(self) -> bytes:
        start = self.offset
        size = self.number("B")
        unit_size = 1
        if size == 0xFF:
            size = self.number("H")
            if size == 0xFFFE:
                unit_size = 2
                size = self.number("B")
                if size == 0xFF:
                    size = self.number("H")
            if size == 0xFFFF:
                size = self.number("I")
        if size > _MAX_STRING:
            raise UnsupportedModel("Model name exceeds the string budget")
        self.take(size * unit_size)
        return self.payload[start:self.offset]

    def base(self) -> _Base:
        return _Base(self.number("i"), self.string(), self.take(8))

    def object(self, expected: bytes | None = None) -> _Model | bytes:
        first_tag = tag = self.number("H")
        if tag == 0x7FFF:
            tag = self.number("I")
            class_flag = 0x80000000
        else:
            class_flag = 0x8000
        if tag == 0:
            raise UnsupportedModel("Null objects are not supported in model lists")
        if first_tag == 0xFFFF:
            schema = self.number("H")
            name_length = self.number("H")
            if not 0 < name_length <= 128:
                raise UnsupportedModel("Invalid MFC runtime-class name length")
            class_name = self.take(name_length)
            self.entries.append((class_name, schema))
        elif tag & class_flag:
            index = tag & ~class_flag
            if index >= len(self.entries) or not isinstance(self.entries[index], tuple):
                raise UnsupportedModel(f"Invalid MFC class reference {index}")
            class_name, schema = self.entries[index]
        else:
            if tag >= len(self.entries):
                raise UnsupportedModel(f"Invalid MFC object reference {tag}")
            result = self.entries[tag]
            if not isinstance(result, (_Model, bytes)):
                raise UnsupportedModel(f"Invalid MFC object reference {tag}")
            if expected is not None and not isinstance(result, bytes):
                raise UnsupportedModel("A triangle reference points to a model")
            if expected is None and not isinstance(result, _Model):
                raise UnsupportedModel("A model reference points to a triangle")
            return result
        if schema != 0:
            raise UnsupportedModel(f"Unsupported {class_name!r} schema {schema}")
        if expected is not None and class_name != expected:
            raise UnsupportedModel(f"Expected {expected!r}, found {class_name!r}")
        object_index = len(self.entries)
        self.entries.append(None)
        if class_name == b"CTriChip":
            if expected != class_name:
                raise UnsupportedModel("CTriChip appeared outside an STL model")
            legacy_triangle = self.take(96)
            # CTriChip::Serialize emits N,V0,V1,V2 (normal members +0x70,
            # +0x78,+0x80 first). CSTLModel::Serialize emits V0,V1,V2,N
            # (vertex members +0x10..+0x60 first). Keeping the legacy order
            # would turn a unit normal into a vertex near the origin.
            result = legacy_triangle[24:] + legacy_triangle[:24]
            _check_finite(result, 12)
        elif class_name in _BODY_SIZES:
            base = self.base()
            body = self.take(_BODY_SIZES[class_name])
            _check_finite(body, {b"CCone": 11, b"CCylinder": 13, b"CSphere": 7}[class_name])
            result = _Model(class_name, schema, base, body)
        elif class_name == b"CSTLModel":
            base = self.base()
            count = self.count()
            if count * 2 > len(self.payload) - self.offset:
                raise UnsupportedModel("Truncated STL triangle list")
            triangles = [self.object(b"CTriChip") for _ in range(count)]
            result = _Model(class_name, schema, base, struct.pack("<q", count) + b"".join(triangles))
        else:
            raise UnsupportedModel(f"Unsupported model class {class_name.decode('ascii', 'replace')}")
        self.entries[object_index] = result
        return result


def _check_finite(body: bytes, count: int) -> None:
    if not all(math.isfinite(x) for x in struct.unpack_from("<" + "d" * count, body)):
        raise UnsupportedModel("Model geometry contains a non-finite coordinate")


def _base_bytes(base: _Base, next_identifier: int) -> bytes:
    return (struct.pack("<q", base.identifier) + base.name + base.appearance
            + struct.pack("<i", next_identifier) + bytes(24) + _IDENTITY)


def _archive_count(count: int) -> bytes:
    return struct.pack("<H", count) if count < 0xFFFF else struct.pack("<HI", 0xFFFF, count)


def _reference(index: int, *, class_: bool) -> bytes:
    if index < 0x7FFF:
        return struct.pack("<H", index | (0x8000 if class_ else 0))
    return struct.pack("<HI", 0x7FFF, index | (0x80000000 if class_ else 0))


def convert_models(payload: bytes) -> bytes:
    """Convert an entire 3.0 ``3DModel`` payload to the 3.7 archive layout.

    Supports empty archives and analytic Cone/Cylinder/Sphere and STL models.
    Model coordinates, names, IDs, appearance, and triangle order are retained.
    New translation state is zero and the new matrix is identity: old files
    store their model coordinates directly. Unknown bytes/classes are errors.
    """
    reader = _Reader(payload)
    root = reader.base()
    models = [reader.object() for _ in range(reader.count())]
    if reader.offset != len(payload):
        raise UnsupportedModel(f"Unmapped model bytes at offset {reader.offset}: {len(payload) - reader.offset} bytes")
    identifiers = [root.identifier] + [model.base.identifier for model in models]
    next_identifier = max(0, max(identifiers) + 1)
    if next_identifier > 0x7FFFFFFF:
        raise UnsupportedModel("Model ID counter exceeds the target 32-bit range")
    output = bytearray(_base_bytes(root, next_identifier) + _archive_count(len(models)))
    classes: dict[bytes, int] = {}
    objects: dict[int, int] = {}
    next_index = 1
    for model in models:
        object_key = id(model)
        if object_key in objects:
            output.extend(_reference(objects[object_key], class_=False))
            continue
        if model.class_name in classes:
            output.extend(_reference(classes[model.class_name], class_=True))
        else:
            output.extend(struct.pack("<HHH", 0xFFFF, model.schema, len(model.class_name)) + model.class_name)
            classes[model.class_name] = next_index
            next_index += 1
        objects[object_key] = next_index
        next_index += 1
        output.extend(_base_bytes(model.base, next_identifier) + model.body)
    return bytes(output)
