import ctypes
import math
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from maxcraft.protocol import Atomics, ByteRing, Link, MC, MC_SNAPSHOT, ProtocolError, VERTEX
from maxcraft.geometry import to_mc, to_max, camera_axes, collision_packets


class RingTests(unittest.TestCase):
    def setUp(self):
        self.buffer = bytearray(256)
        self.atomic = Atomics(self.buffer)
        self.ring = ByteRing(self.buffer, self.atomic, 0, 256)

    def test_backpressure_preserves_unread(self):
        self.assertTrue(self.ring.write(1, b'a'*80))
        self.assertFalse(self.ring.write(2, b'b'*80))
        self.assertEqual(self.ring.read(), [(1, b'a'*80)])

    def test_wrap_with_padding(self):
        self.ring.write(1, b'a'*80)
        self.ring.read()
        self.assertTrue(self.ring.write(2, b'b'*48))
        self.assertEqual(self.ring.read(), [(2, b'b'*48)])

    def test_partial_drain(self):
        for i in range(4):
            self.ring.write(1, bytes([i]))
        self.assertEqual(len(self.ring.read(max_messages=2)), 2)
        self.assertEqual(self.ring.read(), [(1, b'\x02'), (1, b'\x03')])

    def test_corrupt_length_rejected_before_allocation(self):
        struct.pack_into('<II', self.buffer, 128, 1, 0xffffffff)
        self.atomic.store64(0, 8)
        with self.assertRaises(ProtocolError):
            self.ring.read()

    def test_counters_and_oversize(self):
        with self.assertRaises(ValueError):
            self.ring.write(1, bytes(129))
        self.atomic.store64(64, 8)
        with self.assertRaises(ProtocolError):
            self.ring.read()

    def test_exchange_is_real_rmw(self):
        self.assertEqual(self.atomic.exchange32(32, 6), 0)
        self.assertEqual(self.atomic.exchange32(32, 1), 6)
        self.assertEqual(self.atomic.load32(32), 1)


class GeometryTests(unittest.TestCase):
    def test_coordinates_roundtrip_and_orientation(self):
        for p in [(0, 0, 0), (70, -140, 210), (-50, 321, -234)]:
            for a, b in zip(p, to_max(to_mc(p))):
                self.assertAlmostEqual(a, b)
        self.assertEqual(to_mc((0, 0, 70)), (0, 101, 0))

    def test_camera_orthonormal(self):
        for yaw, pitch in [(0, 0), (90, 45), (179, -89.9)]:
            axes = camera_axes(yaw, pitch)
            for a in axes:
                self.assertAlmostEqual(sum(n*n for n in a), 1)
            for i in range(3):
                self.assertAlmostEqual(sum(axes[i][j]*axes[(i+1)%3][j] for j in range(3)), 0)

    def test_surface_voxels_and_negative_regions(self):
        tri = ((-1., 100., -1.), (-1., 100., 1.), (1., 100., 1.))
        packets = collision_packets([tri], 7)
        self.assertEqual(packets[0], (1, struct.pack('<I', 7)))
        self.assertTrue(any(k == 3 for k, _ in packets))
        voxels = []
        for kind, payload in packets:
            if kind == 2:
                header = struct.unpack_from('<6iII', payload)
                self.assertEqual(header[6], 7)
                self.assertEqual(len(payload), 32 + header[7]*80)
                voxels.extend(struct.iter_unpack('<iiiI8Q', payload[32:]))
        self.assertTrue(voxels)
        self.assertTrue(any(v[0] < 0 for v in voxels))
        self.assertTrue(all(v[1] == 99 for v in voxels))
        known = [struct.unpack_from('<6iII', p) for k,p in packets if k == 2]
        self.assertTrue(any(h[1] == 88 and h[7] == 0 for h in known), 'Air below ground must be marked known to release teleport hold')

    def test_geometry_limits_fail_closed(self):
        with self.assertRaises(ValueError):
            collision_packets([((0,0,0),(100000,0,0),(0,0,100000))], 1)

    def test_wire_sizes(self):
        self.assertEqual(VERTEX.size, 32)
        self.assertEqual(MC_SNAPSHOT.size, 104)


class PlayerTests(unittest.TestCase):
    def setUp(self):
        self.link = Link.__new__(Link)
        self.link.m = bytearray(1024)
        self.link.a = Atomics(self.link.m)
        MC_SNAPSHOT.pack_into(self.link.m, MC, 2, 5, 1., 100., 3., 90., -20., 1.62, .5, 123, 2, 50, 70., 0., 0., 0, 1., 101.62, 3.)

    def test_exact_camera_offsets(self):
        state = self.link.read_player()
        self.assertEqual(state['pos'], (1., 100., 3.))
        self.assertEqual(state['eye'], (1., 101.62, 3.))
        self.assertEqual(state['fov'], 70.)
        self.assertEqual(state['ack'], 123)

    def test_writer_in_progress_is_skipped(self):
        self.link.a.exchange32(MC, 3)
        self.assertIsNone(self.link.read_player())

    def test_invalid_fov_is_rejected(self):
        struct.pack_into('<f', self.link.m, MC + 0x40, float('nan'))
        with self.assertRaises(ProtocolError):
            self.link.read_player()


if __name__ == '__main__':
    unittest.main()

