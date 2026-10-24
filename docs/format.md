# Implemented format and evidence

This is an unofficial translator from `File Ver 3.0` EMD to `File Ver 3.7`
EMX, with `GeometryVersion:2` on both sides. Neither extension denotes ZIP or
XML. Both formats combine ASCII section framing with binary model data; EMD
3.0 has tagged text geometry, whereas EMX 3.7 has binary geometry records.

The implementation targets the observed layouts, not every LenMark release.
Unknown fields, classes, unsupported automation, and trailing bytes reject the
entire source file. A rejected file must not produce a partial output.

## Serialization evidence

The public tests use a generic rectangle fixture, synthetic records, and a
minimal empty native model archive. Customer artwork and vendor binaries are
not distributed in this repository.

Target layouts were also checked against the exported serialization routines
in `CSGeometry.dll` from the public `LenMark_3DS_x64 2023.4.04.260914` package.
The inspected DLL SHA-256 is
`601371f3228e0628f94697d275197d0c2c71ec7a55450877ef3b9a9a4481a461`.
Useful routine RVAs in that exact DLL are:

| Routine | RVA |
| --- | --- |
| `CS_Entity::SerializeFile` | `0x4aa80` |
| `CS_AtomEntity::SerializeFile` | `0x7db0` |
| `CS_Fill::SerializeFile` | `0x54fd0` |
| `CS_Bezier::SerializeFile` | `0x11430` |
| `CS_BezierSegment::SerializeFile` | `0x182c0` |
| `CS_BezierNode::SerializeFile` | `0x15c50` |
| `CS_Text::SerializeFile` | `0x8a880` |
| `CS_ArcText::SerializeFile` | `0x96130` |
| `CS_LineText::SerializeFile` | `0x84c90` |
| `CS_Character::SerializeFile` | `0x83010` |
| `CProcessRepeat::Serialize` / `SerializeFile` | `0xabb30` |
| `CEntity::Serialize` | `0xe6a80` |
| `CS_LayerManager::SaveSingleLayer` | `0xae7a0` |
| `CS_LayerManager::ReadSingleLayer` | `0xaed30` |
| `CS_LayerManager::ReadLayerDataFromFile` | `0xafad0` |
| `CS_LayerManager::InitParaArray` | `0xb0730` |

Some exports share addresses, so disassembly may display another alias.
Document conversion must follow `SerializeFile`, not the similarly named
`Serialize` methods used for in-memory state. In particular, Group child-list
framing differs between those two paths. Text, ArcText, LineText, Character,
Bezier, and Segment were separately audited through their file paths; their
mapped binary layouts retain the described counts and child records.
The [community EMX grid generator](https://feeltek.lasertips.org/generator/)
provides independent context for the feasibility of producing EMX files.
Its implementation and template data are not dependencies of this converter.

## Framing and geometry

Sections remain `PARAMETERS`, `DOCINFO`, `3DModel`, and `ENTITIES` in that
order. The parameter and document sections retain their source values.
The model body follows the bare `101` tag. The entity body starts with
`GeometryVersion:2`. Top-level binary records retain ASCII wrapper names;
nested records use their class-specific file framing. Groups contain nested
ENTITIES sections, while homogeneous geometry lists use binary counts.

Numbers use explicit little-endian widths: C++ `int`/enum is 32 bits, widened
IDs and geometry list counts are 64 bits, and coordinates are IEEE-754 doubles.
MFC ANSI CStrings retain source bytes and use MFC's variable-length length
prefix. No global UTF-8 decoding or font substitution is performed.

`codec.py` translates the geometry as a stream. It backpatches counts and Z
bounds after reading the corresponding source fields. Main mappings include:

| Source record | Target representation |
| --- | --- |
| Entity | Type, pen, widened ID, flags, name, six bounds, cached points, three Fill slots, model references, final flag |
| AtomEntity | Entity, mapped-object flag and optional MPLine, final integer |
| Group | Entity plus nested ASCII-framed ENTITIES section, named child records and ENDSEC |
| Bezier | AtomEntity plus counted Segment records |
| Segment | AtomEntity, flag, counted BezierNodes |
| BezierNode | Anchor (tag 204), incoming handle (203), outgoing handle (205), then two 32-bit flags |
| Rectangle | AtomEntity, six shape fields, eight BezierNodes |
| MPLine | AtomEntity, parent-type integer, counted polylines |
| Polyline | 64-bit point count, then ordered XYZ triples |

The Entity's source Z bounds, tags 224/225, move beside X/Y bounds in the
binary record. Source model-reference tag 226 becomes a counted list of
64-bit identifiers. Names, curve traversal and control-point roles, node flags,
hatch settings, cached paths, and processing order are retained.

BezierNode text tags and binary slots differ: native `SaveText`/`ReadText`
(`0x15d80`/`0x15ee0`) map tag 203 to member `+0x28` (incoming handle), tag 204
to member `+0x08` (anchor), and tag 205 to member `+0x48` (outgoing handle).
`SerializeFile` at `0x15c50` writes members `+0x08`, `+0x28`, `+0x48`, so the
converter emits tags in order **204, 203, 205**, then flags 201/202. The
coordinate fingerprint follows this native binary order. Versions before
0.1.2 mistakenly retained text-tag order and distorted curves whenever the
anchor and incoming handle differed. This shared correction applies to
Segments, Ellipses, Rectangles and text glyphs.

Missing Pen tag 18 is emitted as `0` for every migrated Pen to retain explicit
saved values rather than declaring equality to machine defaults. Native
`ReadLayerDataFromFile` recomputes this property by comparing actual values to
the machine's default parameter arrays; native edited Pens and the community
writer use zero. This marker's meaning is inferred from serialization and
load behavior.
Missing Pen tags 25 and 26 use native constructor defaults of `1`.

New target fields have no source counterpart: Entity optional metadata is
absent (`0`), the two additional Fill integers are `0`, and MPLine parent type
is `0`. These are explicit compatibility defaults; their wider semantics have
not been established by controlled captures. The converter does not regenerate
hatching or reinterpret laser setting units.

When missing from a legacy Pen, parameter tags 18, 25, and 26 are added as
`0`, `1`, and `1` respectively. Existing values are retained. Tags 25/26 use
the native constructor defaults. Tag 18 is a separate migration policy:
`SaveSingleLayer` maps it to the per-Pen property at offset `0x800c`, and
`ReadLayerDataFromFile` recomputes that property by comparing loaded settings
with the machine's default parameter arrays. Its role as a "using/matching
default parameters" marker is a strong inference. The native constructor sets
it to `1` for fresh default Pens, while a native custom Pen and the community
generator use `0`. Migrated Pens contain explicit saved values, so the
converter writes `0` rather than asserting equivalence to unknown machine
defaults. This value must never be derived from the Pen's index.

## Editable text

`text.py` preserves native Text/ArcText structure, font bytes, editable source,
origin, Matrix3D, static variable text, LineText/Character caches, glyph
Segments, and Fills. It does not flatten text into ordinary outlines.

Text tags 201–216 use the native mixed byte/double/CString layout. Bounds
230–235 move before origin 217, matrix 218, and source string 219. Integer
settings 220–229 follow the source string. StaticText has binary subtype `2`.
LineText and Character each store AtomEntity, four doubles, a reference XYZ
point, and counted children. ArcText retains its Bezier path; its tag 220 byte
moves after the doubles from tags 221/222.

Supported raw strings end with a separate `  0` metadata line, matching the
observed source files. Embedded CR/LF bytes are preserved, including the
multiline content such as `First\r\nSecond`. An actual source line equal to
`  0` is ambiguous in this legacy framing; other escaping/metadata variants
are outside the supported subset. Missing terminators reject the file.
Only inactive ProcessRepeat with no repeat-offset array and StaticText
variable sources are mapped. Other text automation must fail explicitly.

## Bitmaps

`bitmap.py` translates the observed uncompressed BMP record without tracing,
resampling, or modifying its embedded image. Native `CS_Dib::ReadText` at RVA
`0x2af90` establishes the legacy tag-to-member mapping; `CS_Dib::Serialize`
at `0x27e00` establishes the target layout. A Bitmap uses Entity directly,
followed by its control point, six raster bounds, original/processing pixel
dimensions, settings, an eleven-entry power/gray curve, scan dimensions, and a
complete BMP file. BMP bytes and SHA-256 are retained exactly and checked by
the independent target reader.

The legacy source also contains a per-pixel scan cache: each `216:row:count`
marker introduces that many packed `(float32 X, Y, Z, uint8 gray)` records.
The native target format stores the image and settings and rebuilds this cache
on load. Before allowing that change, the converter validates every source
cache position against a flat, axis-aligned grid with `25.4 / DPI` spacing,
checks its control point and dimensions, and derives its raster bounds. Float32
rounding is allowed; warped, rotated, nonuniform, and attached raster mappings
are rejected. Attached Bitmaps require a separate external-cache representation
that is not mapped here. The new integer at native member offset `0x2cc` uses
zero; the source curve's implicit power steps become `0, 10, ..., 100`.

The report records `bitmap_cache_regenerated`, the number of validated legacy
cache pixels, per-image `bitmap_bmp_sha256` values, and an explicit regeneration
note. The raster cache's old XYZ/gray bytes are not copied into EMX. Preserving
the original BMP and processing settings does **not** prove that a newer
LenMark release regenerates identical grayscale values or scan instructions.
That behavior requires native Preview and acceptance testing. Cached raster
positions are excluded from the generic coordinate fingerprint because the
target format does not serialize them; the stored control point remains
included. Raster dimensions and original BMP dimensions are reported separately.

## Model archive

`models.convert_models(payload)` reads the entire source model payload and
rejects unknown classes, schemas, invalid MFC references, truncation, and
trailing bytes. It supports empty lists, Cone/Cylinder/Sphere, and STL models.
Root and child `CEntity` IDs widen from 32 to 64 bits. The target adds a
reconstructed next-ID counter, zero translation, and an identity Matrix3D.
The old records store model geometry directly and have no transform fields to
copy. Analytic bodies retain their bytes; STL `CTriChip` object lists become
counted arrays of triangle records. The record orders differ: legacy
`CTriChip::Serialize` at RVA `0xe7620` writes **normal, vertex 0, vertex 1,
vertex 2**; native `CSTLModel::Serialize` at `0xe8f10` writes **vertex 0,
vertex 1, vertex 2, normal**. Each triple is three doubles. The converter moves
the leading normal triple to the end of every record, preserving all coordinate
bits and vertex order. Copying the 96-byte record unchanged would incorrectly
use its unit normal as a near-origin vertex and distort the entire mesh.
Class and object references are rebuilt after removing the legacy triangle
object tags, preserving triangle order and shared references.

The converted empty archive matches an independently retained native EMX
fixture byte for byte. Model tests also exercise analytic geometry, STL arrays,
reference remapping, long names, malformed input, and full source consumption.
A separate semantic regression decodes a target triangle in native order and
checks its three exact off-origin vertices, unit normal, edge perpendicularity,
and area. This test failed against the original raw-copy implementation and
passes with the explicit normal/vertex reordering. Byte framing and copied-byte
checks alone do not establish correct mesh geometry.

## Verification boundary

`verify.py` is a separately implemented, bounded reader for supported target
geometry. It checks complete consumption, record counts, finite numeric data,
wrapper/type consistency, nested counts, and CString framing. Conversion
compares source and target record counters and a SHA-256 fingerprint of the
ordered, serialized XYZ values. The report also includes a toolpath fingerprint.
These checks detect omitted, reordered, or changed coordinates and malformed
geometry framing.

The model converter validates and fully consumes the source archive; this
does not amount to an independent decoder of the emitted target model archive.
The geometry fingerprint does not establish the semantics of unknown flags,
font availability, machine calibration, parameter-unit compatibility, or native
application acceptance. LenMark open/Preview/Save As/reopen testing remains a
separate acceptance step. Automated checks must not be described as that test.

### Regression boundaries

Group tests require nested ENTITIES sections, including recursively nested
groups and wrapper/type agreement. A writer and reader sharing the same
incorrect in-memory protocol would not establish file compatibility.

STL regression tests interpret emitted triangles as native vertices and
normals, checking exact positions, perpendicular normals, and triangle area.
Raw-byte equality cannot catch an incorrect semantic tuple order.

Bezier tests use distinct anchors and handles, evaluate the emitted cubic
curves, and check circular contours. A four-quarter cubic approximation of a
50 mm circle has maximum radial error 0.013626 mm. Straight segments with
coincident handles cannot expose a control-point role swap.
