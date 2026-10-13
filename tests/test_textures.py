import unittest
from maxcraft.textures import region_for_uv, local_uv


class TextureTests(unittest.TestCase):
    def test_real_non_square_atlas_sprite_and_roundoff(self):
        uv = [(1904/2048, 880/2576), (1920/2048, 896/2576 + 1e-8)]
        rect = region_for_uv(uv, 2048, 2576)
        self.assertEqual(rect, (1904, 880, 16, 16))
        self.assertEqual(local_uv(uv[0], rect, 2048, 2576), (0., 1.))
        end = local_uv(uv[1], rect, 2048, 2576)
        self.assertAlmostEqual(end[0], 1.)
        self.assertAlmostEqual(end[1], 0., places=4)

    def test_boundary_and_degenerate_uv_stays_in_atlas(self):
        self.assertEqual(region_for_uv([(1,1)]*3, 16, 16), (15,15,1,1))
        self.assertEqual(region_for_uv([(-1,-1),(2,2)],16,16), (0,0,16,16))

    def test_nonfinite_uv_is_rejected(self):
        with self.assertRaises(ValueError):
            region_for_uv([(float('nan'), 0)],16,16)
