"""Integration checks using a small original LenMark rectangle control."""

import io
from pathlib import Path
import struct
import unittest

from lenmark_converter.codec import FormatError
from lenmark_converter.project import convert_stream
from lenmark_converter.verify import verify_bytes


FIXTURE = Path(__file__).parent / "fixtures" / "rectangle.emd"


class ConversionTests(unittest.TestCase):
    def convert(self, source=None):
        target = io.BytesIO()
        stats = convert_stream(io.BytesIO(FIXTURE.read_bytes() if source is None else source), target)
        return target.getvalue(), stats

    def test_original_rectangle_retains_coordinates_and_primitive(self):
        target, source_stats = self.convert()
        verified = verify_bytes(target)
        self.assertTrue(target.startswith(b"File Ver 3.7\n"))
        self.assertEqual(verified["type_5"], 1)
        self.assertEqual(verified["bezier_nodes"], 8)
        self.assertEqual(verified["points"], 29)
        for field in ("coordinate_sha256", "points", "entities", "fills", "bezier_nodes"):
            self.assertEqual(source_stats[field], verified[field])
        body = target.index(b"GeometryVersion:2\nRectangle\n") + len(b"GeometryVersion:2\nRectangle\n")
        name_length = target[body + 37]
        bounds = struct.unpack_from("<6d", target, body + 38 + name_length)
        self.assertEqual(bounds, (-0.5, 0.5, -0.5, 0.5, 120.0, 120.0))

    def test_pen_values_are_copied_literally_with_new_defaults(self):
        target, _ = self.convert()
        source_header = FIXTURE.read_bytes().split(b"ENDSEC\n", 1)[0].splitlines()[1:]
        output_header = target.split(b"ENDSEC\n", 1)[0].splitlines()[1:]
        for setting in source_header:
            self.assertIn(setting, output_header)
        self.assertIn(b"18:0", output_header)
        self.assertIn(b"25:1", output_header)
        self.assertIn(b"26:1", output_header)

    def test_all_migrated_pens_use_explicit_settings_flag_not_pen_index(self):
        source = FIXTURE.read_bytes()
        layer = source[source.index(b"Layer:0\n"):source.index(b"LayerEnd\n") + len(b"LayerEnd\n")]
        source = source.replace(b"LayerEnd\n", b"LayerEnd\n" + layer.replace(b"Layer:0\n", b"Layer:17\n"), 1)
        target, stats = self.convert(source)
        self.assertEqual(stats["pens"], 2)
        header = target.split(b"ENDSEC\n", 1)[0]
        self.assertEqual(header.count(b"18:0\n"), 2)
        self.assertNotIn(b"18:17\n", header)

    def test_integral_legacy_decimal_flag_is_accepted_fractional_rejected(self):
        source = FIXTURE.read_bytes()
        source = source.replace(b"205:0.000000\n206:0.000000", b"205:0\n206:0.000000")
        _, stats = self.convert(source)
        self.assertEqual(stats["bezier_nodes"], 8)
        fractional = source.replace(b"205:0\n206:0.000000", b"205:0.25\n206:0.000000")
        with self.assertRaisesRegex(FormatError, "numeric field 205"):
            self.convert(fractional)

    def test_unknown_fields_versions_and_trailing_bytes_fail(self):
        source = FIXTURE.read_bytes()
        for broken in (source.replace(b"File Ver 3.0", b"File Ver 3.1"),
                       source.replace(b"230:0\nEntityEnd", b"999:7\n230:0\nEntityEnd"),
                       source.replace(b"LayerEnd\n", b"999:123\nLayerEnd\n", 1),
                       source.replace(b"101:1\nENDSEC", b"101:1\n999:123\nENDSEC", 1),
                       source.replace(b"3:100.000000\n", b"3:nan\n", 1),
                       source + b"trailing data",
                       source.replace(b"201:-0.500000", b"201:nan", 1)):
            with self.subTest(broken=broken[:20]):
                with self.assertRaises(ValueError):
                    self.convert(broken)

    def test_empty_and_single_point_cached_paths_are_preserved(self):
        source = FIXTURE.read_bytes()
        point = b"CSPoint\n201:1.25\n202:-2.5\n203:120.000000\nCSPointEnd\n"
        source = source.replace(b"FillEnd\n", b"Polyline\nPolylineEnd\nPolyline\n" + point + b"PolylineEnd\nFillEnd\n", 1)
        target, stats = self.convert(source)
        verified = verify_bytes(target)
        self.assertEqual(stats["polylines"], 2)
        self.assertEqual(verified["polylines"], 2)
        self.assertEqual(stats["coordinate_sha256"], verified["coordinate_sha256"])

    def test_group_uses_native_file_section_framing_for_children(self):
        source = FIXTURE.read_bytes()
        marker = b"GeometryVersion:2\n"
        header, geometry = source.split(marker, 1)
        rectangle = geometry.removesuffix(b"ENDSEC\n")
        start = rectangle.index(b"\nEntity\n") + 1
        end = rectangle.index(b"EntityEnd\n") + len(b"EntityEnd\n")
        group_entity = rectangle[start:end].replace(b"201:5\n", b"201:0\n", 1)
        grouped = header + marker + b"Group\n" + group_entity + rectangle + b"GroupEnd\nENDSEC\n"
        target, stats = self.convert(grouped)
        # CS_Group::SerializeFile calls SerializeEntityList, whose disk
        # protocol is an ENTITIES section. The in-memory serializer's counted
        # numeric list is accepted by our old reader but invisible in LenMark.
        nested_header = b"SECTION\nENTITIES\nGeometryVersion:2\n"
        self.assertEqual(target.count(nested_header), 2)
        verified = verify_bytes(target)
        self.assertEqual(verified["counts"]["Group"], 1)
        self.assertEqual(verified["counts"]["Rectangle"], 1)
        self.assertEqual(verified["coordinate_sha256"], stats["coordinate_sha256"])


if __name__ == "__main__":
    unittest.main()
