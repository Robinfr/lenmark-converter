"""Binary reader tests use constructed records, independent of the writer."""
import hashlib
import io
import math
import struct
import unittest

from lenmark_converter.verify import GeometryReader, InvalidEmx, cubic_point, verify_bytes


def pack(fmt, *args):
    return struct.pack('<' + fmt, *args)


def document(geometry=b'', model=b''):
    return (b'File Ver 3.7\nSECTION\nPARAMETERS\nENDSEC\n'
            b'SECTION\nDOCINFO\n101:1\nENDSEC\n'
            b'SECTION\n3DModel\n101\n' + model +
            b'ENDSEC\nSECTION\nENTITIES\nGeometryVersion:2\n' + geometry + b'ENDSEC\n')


# Native 3.7 default Fill bytes, with no paths. The 124-byte prefix includes
# two integer options introduced since EMD 3.0.
EMPTY_FILL = pack('4i7d2id3id4iq', 0, 1, 0, 0,
                  1., 0., 0., 0., 0., 0., 0., 0, 0, 90.,
                  0, 1, 0, 10., 0, 0, 0, 0, 0)


def entity(type_id=27, point=(0., 0., 120.), name=b''):
    return (pack('iiqiBiiq', type_id, 0, 0, 0, 0, 1, 0, 0) +
            bytes([len(name)]) + name +
            pack('6d3i2d', 0., 0., 0., 0., 120., 120., 1, 1, 1, 0., 0.) +
            pack('3d', *point) * 5 + EMPTY_FILL * 3 + pack('qi', 0, 0))


def atom(type_id=27):
    return entity(type_id) + pack('ii', 0, 0)


class VerifyTests(unittest.TestCase):
    def test_empty_document_and_empty_bezier(self):
        self.assertEqual(verify_bytes(document())['top_level_objects'], 0)
        result = verify_bytes(document(b'Bezier\n' + atom() + pack('q', 0)))
        self.assertEqual(result['entities'], 1)
        self.assertEqual(result['fills'], 3)
        self.assertEqual(result['points'], 5)
        self.assertEqual(result['coordinate_sha256'], hashlib.sha256(pack('3d', 0., 0., 120.) * 5).hexdigest())

    def test_file_group_children_are_a_nested_entity_section(self):
        # Evidence: native CS_Group::SerializeFile0x57f90 calls
        # SerializeEntityList0x4cbc0, whose store branch0x4cd10 emits these
        # literal strings. No binary child count/discriminator is written.
        group = (b'Group\n' + entity(0) +
                 b'SECTION\nENTITIES\nGeometryVersion:2\n' +
                 b'Bezier\n' + atom() + pack('q', 0) + b'ENDSEC\n')
        result = verify_bytes(document(group))
        self.assertEqual(result['entities'], 2)
        self.assertEqual(result['counts']['Group'], 1)
        self.assertEqual(result['counts']['Bezier'], 1)
        self.assertEqual(result['max_depth'], 1)

    def test_memory_group_serialization_is_rejected_as_a_file(self):
        # This was the original defect: native Serialize (Undo/state copies)
        # uses count + GetType(), whereas native SerializeFile expects section
        # framing. A reader mirroring the writer had incorrectly accepted it.
        for discriminator in (0, 20, 27):
            bad = (b'Group\n' + entity(0) + pack('qi', 1, discriminator) +
                   atom() + pack('q', 0))
            with self.subTest(discriminator=discriminator), self.assertRaisesRegex(
                    InvalidEmx, 'nested ENTITIES section'):
                verify_bytes(document(bad))

    def test_file_group_recursively_consumes_child_sections(self):
        section = b'SECTION\nENTITIES\nGeometryVersion:2\n'
        inner = b'Group\n' + entity(0) + section + b'Bezier\n' + atom() + pack('q', 0) + b'ENDSEC\n'
        outer = b'Group\n' + entity(0) + section + inner + b'ENDSEC\n'
        result = verify_bytes(document(outer))
        self.assertEqual(result['counts']['Group'], 2)
        self.assertEqual(result['counts']['Bezier'], 1)
        self.assertEqual(result['top_level_objects'], 1)
        self.assertEqual(result['max_depth'], 2)

    def test_file_group_wrapper_must_match_child_binary_type(self):
        group = (b'Group\n' + entity(0) +
                 b'SECTION\nENTITIES\nGeometryVersion:2\n' +
                 b'Bezier\n' + atom(26) + pack('q', 0) + b'ENDSEC\n')
        with self.assertRaisesRegex(InvalidEmx, 'entity type'):
            verify_bytes(document(group))

    def test_wrapper_and_binary_type_must_agree(self):
        with self.assertRaisesRegex(InvalidEmx, 'entity type'):
            verify_bytes(document(b'Bezier\n' + atom(26) + pack('q', 0)))

    def test_negative_and_oversized_counts_rejected(self):
        for count in (-1, 2**62):
            with self.subTest(count=count), self.assertRaisesRegex(InvalidEmx, 'count'):
                verify_bytes(document(b'Bezier\n' + atom() + pack('q', count)))

    def test_every_truncation_of_minimal_record_is_rejected(self):
        record = b'Bezier\n' + atom() + pack('q', 0)
        for length in range(1, len(record)):
            with self.subTest(length=length), self.assertRaises(InvalidEmx):
                verify_bytes(document(record[:length]))

    def test_nonfinite_point_is_rejected(self):
        for value in (math.inf, -math.inf, math.nan):
            record = b'Bezier\n' + entity(point=(value, 0., 120.)) + pack('iiq', 0, 0, 0)
            with self.subTest(value=value), self.assertRaisesRegex(InvalidEmx, 'non-finite'):
                verify_bytes(document(record))

    def test_unknown_type_and_trailing_data_rejected(self):
        with self.assertRaisesRegex(InvalidEmx, 'unsupported top-level'):
            verify_bytes(document(b'Unknown\n'))
        with self.assertRaisesRegex(InvalidEmx, 'trailing'):
            verify_bytes(document() + b'garbage')

    def test_segment_node_bytes_count_and_hash(self):
        node_point = pack('3d', 3., 4., 120.)
        node = node_point * 3 + pack('2i', 0, 2)
        segment = atom(26) + pack('iq', 1, 1) + node
        report = verify_bytes(document(b'Bezier\n' + atom() + pack('q', 1) + segment))
        self.assertEqual(report['bezier_nodes'], 1)
        self.assertEqual(report['points'], 13)
        expected = pack('3d', 0., 0., 120.) * 10 + node_point * 3
        self.assertEqual(report['coordinate_sha256'], hashlib.sha256(expected).hexdigest())

    def test_invalid_metadata_flag_rejected(self):
        bad = bytearray(atom())
        bad[20] = 2
        with self.assertRaisesRegex(InvalidEmx, 'metadata flag'):
            verify_bytes(document(b'Bezier\n' + bad + pack('q', 0)))


def bitmap_record(bmp=None, *, dimensions=(2, 3, 1, 1), rows=3, columns=2):
    if bmp is None:
        bmp = (pack('2sIHHI', b'BM', 58, 0, 0, 54) +
               pack('IiiHHIIiiII', 40, 1, 1, 1, 24, 0, 4, 0, 0, 0, 0) +
               bytes((20, 40, 60, 0)))
    settings = pack('5i3d9i2B', *([0] * 5), *([0.] * 3), *([0] * 9), 230, 0)
    curve = b''.join(pack('Bf', min(255, index * 26), index * 10.) for index in range(11))
    return (b'Bitmap\n' + entity(13) + pack('3d', 1., 2., 120.) +
            pack('6d', *([0.] * 6)) + pack('4i', *dimensions) +
            settings + curve + pack('2i', rows, columns) + bmp)


class VerifyBitmapTests(unittest.TestCase):
    def test_bitmap_is_entity_without_atom_and_preserves_bmp_checksum(self):
        record = bitmap_record()
        report = verify_bytes(document(record))
        bmp = record[-58:]
        self.assertEqual(report['type_13'], 1)
        self.assertEqual(report['points'], 6)
        self.assertEqual(report['bitmap_images'], 1)
        self.assertEqual(report['bitmap_bytes'], 58)
        self.assertEqual(report['bitmap_pixels'], 1)
        self.assertEqual(report['raster_pixels'], 6)
        self.assertEqual(report['bitmap_bmp_sha256'], [hashlib.sha256(bmp).hexdigest()])

    def test_bitmap_rejects_bad_scan_or_original_dimensions(self):
        for record in (bitmap_record(rows=2), bitmap_record(columns=-1),
                       bitmap_record(dimensions=(2, 3, 2, 1))):
            with self.subTest(record=record[-60:]), self.assertRaisesRegex(InvalidEmx, 'dimensions'):
                verify_bytes(document(record))

    def test_bitmap_rejects_truncated_pixels_compression_and_bad_headers(self):
        original = bitmap_record()[-58:]
        variants = []
        for offset, fmt, value in ((2, 'I', 59), (10, 'I', 100),
                                   (14, 'I', 108), (30, 'I', 1),
                                   (34, 'I', 100), (22, 'i', 2)):
            bmp = bytearray(original)
            struct.pack_into('<' + fmt, bmp, offset, value)
            variants.append(bytes(bmp))
        for bmp in variants:
            with self.subTest(header=bmp[:54]), self.assertRaises(InvalidEmx):
                verify_bytes(document(bitmap_record(bmp)))

    def test_each_bitmap_truncation_is_rejected(self):
        record = bitmap_record()
        for size in range(1, len(record)):
            with self.subTest(size=size), self.assertRaises(InvalidEmx):
                verify_bytes(document(record[:size]))


class NativeCurveSemanticsTests(unittest.TestCase):
    def test_native_binary_first_slot_is_anchor_not_incoming_handle(self):
        k = 27.614237
        wire = pack('9d2i', 50., 0., 120., 50., -k, 120., 50., k, 120., 2, 1)
        node = GeometryReader(wire).node()
        self.assertEqual(node.anchor, (50., 0., 120.))
        self.assertEqual(node.incoming, (50., -k, 120.))
        self.assertEqual(node.outgoing, (50., k, 120.))
        self.assertEqual(node.flags, (2, 1))

    def test_converted_curved_nodes_evaluate_to_the_source_circle(self):
        # Native evidence: ReadText0x15ee0 maps203->+0x28,204->+0x08,
        #205->+0x48; SerializeFile0x15c50 emits+0x08,+0x28,+0x48.
        # A nondegenerate quarter-circle catches swapping anchor and handle;
        # coordinate counts and a writer-shaped byte roundtrip cannot.
        from lenmark_converter.codec import Cursor, GeometryConverter, Writer
        k = 27.614237
        triples = [((50., -k, 120.), (50., 0., 120.), (50., k, 120.)),
                   ((k, 50., 120.), (0., 50., 120.), (-k, 50., 120.))]
        source = bytearray()
        for points in triples:
            source.extend(b'BezierNode\n201:2\n202:1\n')
            for tag, point in zip((203, 204, 205), points):
                source.extend(f'{tag}\nCSPoint\n201:{point[0]}\n202:{point[1]}\n203:{point[2]}\nCSPointEnd\n'.encode())
            source.extend(b'BezierNodeEnd\n')
        stream = io.BytesIO()
        converter = GeometryConverter(Cursor(io.BytesIO(source)), Writer(stream))
        converter.node()
        converter.node()
        reader = GeometryReader(stream.getvalue())
        first, second = reader.node(), reader.node()
        self.assertEqual(cubic_point(first, second, 0), (50., 0., 120.))
        self.assertEqual(cubic_point(first, second, 1), (0., 50., 120.))
        expected_midpoint = 50. / math.sqrt(2)
        actual = cubic_point(first, second, .5)
        self.assertAlmostEqual(actual[0], expected_midpoint, places=5)
        self.assertAlmostEqual(actual[1], expected_midpoint, places=5)
        # The standard four-cubic circle approximation deviates radially by
        # less than 0.014mm at radius 50mm, including off-axis positions.
        for i in range(101):
            point = cubic_point(first, second, i / 100)
            self.assertLess(abs(math.hypot(point[0], point[1]) - 50.), .014)
            self.assertAlmostEqual(point[2], 120., places=10)

    def test_former_tag_order_predicts_the_visible_scalloped_curve(self):
        k = 27.614237
        wrong_first = GeometryReader(pack('9d2i', 50., -k, 120., 50., 0., 120., 50., k, 120., 2, 1)).node()
        wrong_second = GeometryReader(pack('9d2i', k, 50., 120., 0., 50., 120., -k, 50., 120., 2, 1)).node()
        point = cubic_point(wrong_first, wrong_second, .5)
        self.assertGreater(abs(math.hypot(*point[:2]) - 50.), 5.)
        self.assertGreater(abs(math.hypot(*wrong_first.anchor[:2]) - 50.), 7.)


if __name__ == '__main__':
    unittest.main()
