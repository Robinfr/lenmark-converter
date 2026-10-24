"""Exercise raster preservation and rejection of cache mappings we cannot carry."""
import hashlib
import io
from pathlib import Path
import struct
import unittest

from lenmark_converter.bitmap import write_bitmap
from lenmark_converter.codec import Cursor, FormatError, GeometryConverter, Writer
from lenmark_converter.verify import verify_bytes


FIXTURE = Path(__file__).parent / "fixtures" / "rectangle.emd"


def bmp():
    # Real uncompressed 24-bit BMP header, three pixels across and two rows.
    pixels = b"BitmapEnd\n" + bytes(range(14))
    return (b"BM" + struct.pack("<IHHI", 78, 0, 0, 54)
            + struct.pack("<IiiHHIIiiII", 40, 3, 2, 1, 24, 0, 24, 0, 0, 0, 0)
            + pixels)


def source_bitmap(warped=False, nonuniform=False, attached=False):
    source = FIXTURE.read_bytes()
    start = source.index(b"\nEntity\n") + 1
    end = source.index(b"EntityEnd\n", start) + len(b"EntityEnd\n")
    entity = source[start:end].replace(b"201:5\n", b"201:13\n", 1)
    if attached:
        entity = entity.replace(b"230:0\n", b"230:1\n")
    header = (b"201\nCSPoint\n201:0\n202:0.0254\n203:120\nCSPointEnd\n"
              b"202:3\n203:2\n204:3\n205:2\n206:0\n207:1\n208:0\n209:0\n210:1000\n212:0\n")
    header += b"".join(f"213:{i}:{int(i * 25.5)}\n".encode() for i in range(11))
    header += b"214:2\n215:3\n"
    rows = bytearray()
    for row in range(2):
        rows.extend(f"216:{row}:3\n".encode())
        for col in range(3):
            x = col * .0254 + (.001 if nonuniform and row == 1 and col == 1 else 0)
            z = 121 if warped and row == 1 and col == 1 else 120
            rows.extend(struct.pack("<3fB", x, row * .0254, z, 127))
    settings = (b"217:0\n218:0\n219:0\n220:1\n221:230\n222:0\n223:0\n"
                b"224:10\n225:10\n226:0\n227:0\n228:0\n211\n")
    return b"Bitmap\n" + entity + header + rows + settings + bmp() + b"BitmapEnd\n"


def convert_bitmap(source=None):
    cursor = Cursor(io.BytesIO(source_bitmap() if source is None else source))
    target = io.BytesIO()
    converter = GeometryConverter(cursor, Writer(target))
    cursor.expect(b"Bitmap")
    target.write(b"Bitmap\n")
    write_bitmap(converter)
    document = (b"File Ver 3.7\nSECTION\nPARAMETERS\nENDSEC\nSECTION\nDOCINFO\n101:1\nENDSEC\n"
                b"SECTION\n3DModel\n101\nENDSEC\nSECTION\nENTITIES\nGeometryVersion:2\n"
                + target.getvalue() + b"ENDSEC\n")
    return document, converter


class BitmapTests(unittest.TestCase):
    def test_original_bmp_bytes_and_settings_survive_without_image_processing(self):
        document, converter = convert_bitmap()
        verified = verify_bytes(document)
        self.assertIn(bmp(), document)
        self.assertEqual(verified["bitmap_bmp_sha256"], [hashlib.sha256(bmp()).hexdigest()])
        self.assertEqual(converter.bitmap_bmp_sha256, verified["bitmap_bmp_sha256"])
        for key in ("bitmap_images", "bitmap_bytes", "bitmap_pixels", "raster_pixels"):
            self.assertEqual(converter.counts[key], verified[key])
        self.assertEqual(converter.counts["bitmap_cached_pixels"], 6)
        self.assertEqual(converter.counts["bitmap_cache_regenerated"], 1)
        self.assertIn("regenerated", converter.conversion_notes[0])
        self.assertEqual(converter.coordinate_hash.hexdigest(), verified["coordinate_sha256"])

    def test_warped_nonuniform_and_attached_bitmaps_are_rejected(self):
        for options in ({"warped": True}, {"nonuniform": True}, {"attached": True}):
            with self.subTest(options=options), self.assertRaises(FormatError):
                convert_bitmap(source_bitmap(**options))

    def test_inconsistent_dimensions_and_curve_are_rejected(self):
        source = source_bitmap()
        for broken in (source.replace(b"214:2\n215:3", b"214:3\n215:3"),
                       source.replace(b"216:1:3", b"216:1:2"),
                       source.replace(b"213:5:127", b"213:9:127"),
                       source.replace(b"210:1000\n212", b"210:0\n212")):
            with self.subTest(case=broken[-100:]), self.assertRaises(FormatError):
                convert_bitmap(broken)

    def test_truncated_or_invalid_bmp_is_rejected(self):
        source = source_bitmap()
        start = source.index(b"211\nBM") + len(b"211\n")
        for broken in (source[:start + 20], source[:start + 60],
                       source[:start] + source[start:].replace(b"BM", b"XX", 1),
                       source[:start + 30] + struct.pack("<I", 1) + source[start + 34:]):
            with self.subTest(length=len(broken)), self.assertRaises(FormatError):
                convert_bitmap(broken)


if __name__ == "__main__":
    unittest.main()
