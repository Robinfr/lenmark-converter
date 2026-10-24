"""Geometric regressions for native Bezier anchor/handle interpretation.

The native file serializer stores each node as anchor, incoming handle,
outgoing handle. Legacy EMD tags use incoming=203, anchor=204, outgoing=205.
Coincident controls on straight paths cannot expose an incorrect permutation.
"""
import io
import math
import struct
import unittest

from lenmark_converter.codec import Cursor, GeometryConverter, Writer


def legacy_node(incoming, anchor, outgoing, flags=(0, 2)):
    result = f"BezierNode\n201:{flags[0]}\n202:{flags[1]}\n".encode()
    for tag, point in zip((203, 204, 205), (incoming, anchor, outgoing)):
        result += f"{tag}\nCSPoint\n".encode()
        result += b"".join(f"{coordinate}:{value:.9f}\n".encode()
                           for coordinate, value in zip((201, 202, 203), point))
        result += b"CSPointEnd\n"
    return result + b"BezierNodeEnd\n"


def native_nodes(source, count):
    output = io.BytesIO()
    converter = GeometryConverter(Cursor(io.BytesIO(source)), Writer(output))
    for _ in range(count):
        converter.node()
    data = output.getvalue()
    return [struct.unpack_from("<9d2i", data, 80 * index) for index in range(count)]


def evaluate_native_cubic(start, end, t):
    """Evaluate the native drawing convention, independently of source tags."""
    # Serialized positions: first triple is the on-curve anchor; second is
    # the handle leading into that anchor; third leads out of it.
    controls = (start[0:3], start[6:9], end[3:6], end[0:3])
    weights = ((1 - t) ** 3, 3 * (1 - t) ** 2 * t,
               3 * (1 - t) * t ** 2, t ** 3)
    return tuple(sum(weight * control[axis] for weight, control in zip(weights, controls))
                 for axis in range(3))


class NativeCurveTests(unittest.TestCase):
    def test_native_anchors_and_handles_preserve_a_circular_contour(self):
        radius = 50.0
        handle = radius * 4 * (math.sqrt(2) - 1) / 3
        z = 120.0
        source = b"".join([
            legacy_node((radius, -handle, z), (radius, 0, z), (radius, handle, z)),
            legacy_node((handle, radius, z), (0, radius, z), (-handle, radius, z)),
            legacy_node((-radius, handle, z), (-radius, 0, z), (-radius, -handle, z)),
            legacy_node((-handle, -radius, z), (0, -radius, z), (handle, -radius, z)),
        ])
        nodes = native_nodes(source, 4)
        evaluated = []
        for index, start in enumerate(nodes):
            end = nodes[(index + 1) % len(nodes)]
            for step in range(101):
                evaluated.append(evaluate_native_cubic(start, end, step / 100))
        # Four cubic arcs approximate a circle with at most 0.0273% radial
        # error; swapping a handle and anchor produces errors over 7 mm.
        maximum_error = max(abs(math.hypot(x, y) - radius) for x, y, _ in evaluated)
        self.assertLessEqual(maximum_error, 0.014)
        self.assertTrue(all(abs(actual_z - z) < 1e-9 for _, _, actual_z in evaluated))

    def test_noncoincident_control_roles_and_flags_survive_serialization(self):
        incoming, anchor, outgoing = (1, 2, 3), (4, 5, 6), (7, 8, 9)
        record, = native_nodes(legacy_node(incoming, anchor, outgoing, flags=(1, 3)), 1)
        self.assertEqual(record[0:3], anchor)
        self.assertEqual(record[3:6], incoming)
        self.assertEqual(record[6:9], outgoing)
        self.assertEqual(record[9:], (1, 3))


if __name__ == "__main__":
    unittest.main()
