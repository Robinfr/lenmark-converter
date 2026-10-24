"""Check native text preservation with small, synthetic legacy records."""
import io
import struct
import unittest

from lenmark_converter.codec import Cursor, GeometryConverter, Writer
from lenmark_converter.text import _raw_text
from lenmark_converter.verify import verify_bytes


def point(value=(3, 4, 5)):
    return b"CSPoint\n" + b"".join(
        f"{tag}:{v}\n".encode() for tag, v in zip((201, 202, 203), value)
    ) + b"CSPointEnd\n"


def atom(kind):
    fields = {
        201: kind, 202: 0, 203: 0, 204: 0, 205: 1, 206: 0, 207: 0,
        208: "", 209: 3, 210: 3, 211: 4, 212: 4, 213: 1, 214: 1,
        215: 1, 216: 0, 217: 0,
    }
    prefix = b"".join(f"{k}:{v}\n".encode() for k, v in fields.items())
    points = b"".join(f"{tag}\n".encode() + point() for tag in range(218, 223))
    fill_values = [0, 1, 0, 0, 1., 0., 0., 0., 0., 0., 0., 0, 90., 0, 1, 0, 10., 0, 0, 0]
    fill = b"Fill\n" + b"".join(
        f"{tag}:{v}\n".encode() for tag, v in zip(range(201, 221), fill_values)
    ) + b"FillEnd\n"
    return (b"AtomEntity\nEntity\n" + prefix + points + b"223\n" + fill * 3
            + b"224:5\n225:5\n230:0\nEntityEnd\n300:0\n301:0\nAtomEntityEnd\n")


def legacy_text(source=b" ", repeat=0):
    prefix = (b"ArcText\nText\n" + atom(11) + b"ProcessRepeat\n"
              + f"201:{repeat}\n".encode()
              + b"202:0\n203:0\n204:0\n205:1\n206\n\n  0\nProcessRepeatEnd\n")
    text_fields = {201: 2, 202: 0, 203: 0, 204: 0, 205: 0, 206: 0,
                   207: 0., 208: 100., 209: 0, 210: 0., 211: 0, 212: 10.,
                   213: "Example font", 214: .5, 215: 0., 216: 0}
    prefix += b"".join(f"{k}:{v}\n".encode() for k, v in text_fields.items())
    prefix += b"217\n" + point() + b"218\nMatrix3D\n"
    prefix += b"".join(f"{tag}:{int((tag-201) % 5 == 0)}\n".encode() for tag in range(201, 217))
    prefix += b"Matrix3DEnd\n219\n" + source + b"\n  0\n"
    prefix += b"".join(f"{tag}:{tag-220}\n".encode() for tag in range(220, 230))
    prefix += b"".join(f"{tag}:{tag}\n".encode() for tag in range(230, 236))
    prefix += b"StaticText\nVariableText\n201\n" + source + b"\n  0\nVariableTextEnd\nStaticTextEnd\n"
    prefix += b"LineText\n" + atom(0) + b"201:3\n202:4\n203:4\n204:14\n205\n" + point()
    prefix += b"Character\n" + atom(0) + b"201:3\n202:4\n203:4\n204:14\n205\n" + point()
    prefix += b"CharacterEnd\nLineTextEnd\nTextEnd\n"
    prefix += b"".join(f"{tag}:0\n".encode() for tag in range(201, 216))
    prefix += b"Bezier\n" + atom(27) + b"BezierEnd\n"
    prefix += b"216:0\n217:1\n218:2\n219:3\n220:4\n221:12.5\n222:24.5\nArcTextEnd\n"
    return prefix


def document(geometry):
    return (b"File Ver 3.7\nSECTION\nPARAMETERS\nENDSEC\nSECTION\nDOCINFO\n101:1\nENDSEC\n"
            b"SECTION\n3DModel\n101\nENDSEC\nSECTION\nENTITIES\nGeometryVersion:2\n"
            + geometry + b"ENDSEC\n")


class NativeTextTests(unittest.TestCase):
    def test_raw_text_preserves_multiline_crlf_and_non_ascii_bytes(self):
        cursor = Cursor(io.BytesIO(b"219\nfirst\r\nsecond\xe9\n  0\n220:0\n"))
        self.assertEqual(_raw_text(cursor, 219), b"first\r\nsecond\xe9")
        self.assertEqual(cursor.field(220), b"0")

    def test_raw_text_rejects_missing_metadata_without_consuming_next_record(self):
        with self.assertRaisesRegex(ValueError, "unsupported raw Text framing"):
            _raw_text(Cursor(io.BytesIO(b"219\nsource\nTextEnd\n")), 219)

    def test_native_text_retains_sources_glyphs_transform_and_coordinate_fingerprint(self):
        source = b"first\r\nsecond\xe9"
        stream = io.BytesIO()
        converter = GeometryConverter(Cursor(io.BytesIO(legacy_text(source))), Writer(stream))
        converter.object(b"ArcText")
        geometry = b"ArcText\n" + stream.getvalue()
        # Two source copies are serialized: editable Text and StaticText.
        self.assertEqual(geometry.count(source), 2)
        self.assertIn(b"Example font", geometry)
        self.assertTrue(geometry.endswith(struct.pack("<3B2dB", 1, 2, 3, 12.5, 24.5, 4)))
        report = verify_bytes(document(geometry))
        self.assertEqual(report["entities"], 4)
        self.assertEqual(report["points"], converter.counts["points"])
        self.assertEqual(report["coordinate_sha256"], converter.coordinate_hash.hexdigest())
        self.assertEqual(report["counts"]["ArcText"], 1)

    def test_active_repeat_is_rejected_instead_of_losing_automation(self):
        converter = GeometryConverter(Cursor(io.BytesIO(legacy_text(repeat=1))), Writer(io.BytesIO()))
        with self.assertRaisesRegex(ValueError, "active ProcessRepeat"):
            converter.object(b"ArcText")


if __name__ == "__main__":
    unittest.main()
