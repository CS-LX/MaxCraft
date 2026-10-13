"""Pure geometry and collision serialization; no access to Max from worker threads."""
import math
import struct
from collections import defaultdict

UNITS = 70.0
HEIGHT_OFFSET = 100.0


def to_mc(point, units=UNITS):
    x, y, z = point
    return x / units, z / units + HEIGHT_OFFSET, -y / units


def to_max(point, units=UNITS):
    x, y, z = point
    return x * units, -z * units, (y - HEIGHT_OFFSET) * units


def camera_axes(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    forward = (-math.sin(y) * math.cos(p), -math.cos(y) * math.cos(p), -math.sin(p))
    right = (-math.cos(y), math.sin(y), 0.0)
    up = (right[1] * forward[2], -right[0] * forward[2], right[0] * forward[1] - right[1] * forward[0])
    return right, up, tuple(-v for v in forward)


def collision_packets(triangles, epoch, max_regions=4096, max_samples=4_000_000):
    """Bucket exact triangles and conservatively sample surfaces into 1/8-block voxels.

    Closed meshes retain smooth triangle collision for the player; sampled shells
    provide vanilla placement/support and entity collision. No destructive Max edits.
    """
    regions = defaultdict(list)
    blocks = defaultdict(lambda: [0] * 8)
    samples = 0
    for tri in triangles:
        if len(tri) != 3 or not all(math.isfinite(c) for p in tri for c in p):
            raise ValueError('Invalid collision triangle')
        lower = [math.floor(min(p[i] for p in tri) / 8) for i in range(3)]
        upper = [math.floor(max(p[i] for p in tri) / 8) for i in range(3)]
        if math.prod(upper[i] - lower[i] + 1 for i in range(3)) > max_regions:
            raise ValueError('Scene triangles span too many regions; check Units per block.')
        encoded = struct.pack('<9fI', *(c for p in tri for c in p), 0)
        for rx in range(lower[0], upper[0] + 1):
            for ry in range(lower[1], upper[1] + 1):
                for rz in range(lower[2], upper[2] + 1):
                    regions[(rx, ry, rz)].append(encoded)
        if len(regions) > max_regions:
            raise ValueError('Scene too large; export a smaller selection.')
        a, b, c = tri
        steps = max(1, math.ceil(max(math.dist(a, b), math.dist(b, c), math.dist(c, a)) * 12))
        samples += (steps + 1) * (steps + 2) // 2
        if samples > max_samples:
            raise ValueError('Collision sampling limit exceeded; export a smaller scene/selection.')
        # Bias the surface inward. Max outward winding survives the axis mapping.
        ab, ac = [b[i] - a[i] for i in range(3)], [c[i] - a[i] for i in range(3)]
        normal = (ab[1]*ac[2]-ab[2]*ac[1], ab[2]*ac[0]-ab[0]*ac[2], ab[0]*ac[1]-ab[1]*ac[0])
        norm = math.sqrt(sum(n*n for n in normal)) or 1
        bias = [n / norm * 0.002 for n in normal]
        for i in range(steps + 1):
            for j in range(steps + 1 - i):
                q = [math.floor((a[k] + ab[k]*i/steps + ac[k]*j/steps - bias[k]) * 8) for k in range(3)]
                key = tuple(v // 8 for v in q)
                blocks[key][q[1] % 8] |= 1 << (q[2] % 8 * 8 + q[0] % 8)
    voxel_regions = defaultdict(list)
    for (x, y, z), bits in blocks.items():
        voxel_regions[(x // 8, y // 8, z // 8)].append(struct.pack('<iiiI8Q', x, y, z, 0, *bits))
    result = [(1, struct.pack('<I', epoch))]
    for region in sorted(regions.keys() | voxel_regions.keys()):
        low = tuple(v * 8 for v in region)
        high = tuple(v + 7 for v in low)
        tris, voxels = regions[region], voxel_regions[region]
        result.append((3, struct.pack('<6iII', *low, *high, epoch, len(tris)) + b''.join(tris)))
        result.append((2, struct.pack('<6iII', *low, *high, epoch, len(voxels)) + b''.join(voxels)))
    return result

