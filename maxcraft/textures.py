"""Atlas regions used by actual Minecraft triangles; no block models are generated."""
import math


def region_for_uv(uvs, width, height):
    if not uvs or width < 1 or height < 1:
        raise ValueError('Invalid atlas region')
    if not all(math.isfinite(v) for uv in uvs for v in uv):
        raise ValueError('Non-finite texture coordinates')
    x = max(0, min(width-1, math.floor(min(u for u, v in uvs)*width + .001)))
    y = max(0, min(height-1, math.floor(min(v for u, v in uvs)*height + .001)))
    right = max(x+1, min(width, math.ceil(max(u for u, v in uvs)*width - .001)))
    bottom = max(y+1, min(height, math.ceil(max(v for u, v in uvs)*height - .001)))
    return x, y, right-x, bottom-y


def local_uv(uv, rect, width, height):
    x, y, w, h = rect
    return (uv[0]*width-x)/w, 1-(uv[1]*height-y)/h
