"""Max main-thread adapter: native geometry, camera and texture materials."""
from pathlib import Path
import math
import struct
import time
import uuid
from PySide6 import QtGui
import pymxs
from pymxs import runtime as rt
from .geometry import to_mc, to_max, camera_axes
from .protocol import VERTEX, ProtocolError


class Scene:
    def __init__(self, units=70.0):
        self.units = units
        self.id = uuid.uuid4().hex[:8]
        self.nodes = {}
        self.materials = {}
        self.textures = {}
        self.cache = Path.home() / 'AppData' / 'Local' / 'MaxCraft' / 'cache' / self.id
        self.cache.mkdir(parents=True, exist_ok=True)
        self.previous = None
        self.last_dynamic = 0.0

    def capture_view(self):
        self.viewport = int(rt.viewport.activeViewport)
        self.previous = (rt.viewport.getType(), rt.viewport.getTM(), rt.viewport.getFOV())
        rt.viewport.setType(rt.Name('view_persp_user'))

    def restore_view(self):
        if self.previous:
            kind, matrix, fov = self.previous
            rt.viewport.activeViewport = self.viewport
            rt.viewport.setType(kind)
            rt.viewport.setTM(matrix)
            rt.viewport.setFOV(fov)
            self.previous = None
            rt.redrawViews()

    def camera(self, state, yaw, pitch, aspect):
        if not self.previous or not (state['flags'] & 1):
            return
        right, up, back = camera_axes(yaw, pitch)
        eye = to_max(state['eye'], self.units)
        if state['camera_mode']:
            distance = state['camera_distance'] * self.units
            sign = 1 if state['camera_mode'] == 1 else -1
            eye = tuple(eye[i] + back[i] * distance * sign for i in range(3))
            if sign < 0:
                right, back = tuple(-x for x in right), tuple(-x for x in back)
        camera = rt.matrix3(rt.point3(*right), rt.point3(*up), rt.point3(*back), rt.point3(*eye))
        rt.viewport.activeViewport = self.viewport
        rt.viewport.setTM(rt.inverse(camera))
        vfov = max(10.0, min(140.0, state['fov'] or 70.0))
        hfov = math.degrees(2 * math.atan(math.tan(math.radians(vfov) / 2) * aspect))
        rt.viewport.setFOV(hfov)
        rt.redrawViews()

    def snapshot(self, selection_only=False):
        source = list(rt.selection if selection_only else rt.geometry)
        source = [n for n in source if not rt.getUserProp(n, 'MaxCraftOwned') and not n.isHidden]
        if not source:
            raise ValueError('没有可导出的场景网格；先创建演示场景或选择模型。')
        triangles = []
        for node in source:
            mesh = rt.snapshotAsMesh(node)
            try:
                if len(triangles) + mesh.numfaces > 100000:
                    raise ValueError('场景超过 100,000 三角面，请选择较小区域。')
                vertices = [to_mc(tuple(rt.getVert(mesh, i)), self.units) for i in range(1, mesh.numverts + 1)]
                for i in range(1, mesh.numfaces + 1):
                    ids = rt.getFace(mesh, i)
                    triangles.append(tuple(vertices[int(k) - 1] for k in ids))
            finally:
                rt.delete(mesh)
        return triangles, len(source)

    def texture(self, key, w, h, pixels):
        if not (0 < w <= 8192 and 0 < h <= 8192 and len(pixels) == w*h*4):
            raise ProtocolError('Invalid texture dimensions')
        image = QtGui.QImage(pixels, w, h, w*4, QtGui.QImage.Format_RGBA8888).copy()
        self.textures[key] = image
        path = self.cache / f'texture-{key}.png'
        if not image.save(str(path)):
            raise OSError('Could not save the Minecraft texture atlas')
        if key in self.materials:
            mat = self.materials[key]
            try:
                rt.reload(mat.diffuseMap)
            except RuntimeError:
                mat.diffuseMap = rt.bitmapTexture(filename=str(path))
        else:
            mat = rt.standardMaterial(name=f'MaxCraft_{self.id}_texture_{key}')
            mat.diffuse = rt.color(255, 255, 255)
            mat.selfIllumAmount = 60
            mat.twoSided = True
            tex = rt.bitmapTexture(filename=str(path))
            tex.filtering = 2
            mat.diffuseMap = tex
            self.materials[key] = mat
            rt.showTextureMap(mat, tex, True)
        return mat

    def delete_key(self, key):
        node = self.nodes.pop(key, None)
        if node is not None and rt.isValidNode(node):
            with pymxs.undo(False):
                rt.delete(node)

    def mesh(self, key, data, count, origin, texture=0):
        if count > 500000 or count % 3 or len(data) != count * 32:
            raise ProtocolError('Invalid mesh packet')
        if not count:
            self.delete_key(key)
            return
        points, uv = [], []
        for x, y, z, u, v, color, light, flags in VERTEX.iter_unpack(data):
            if not all(math.isfinite(n) for n in (x, y, z, u, v)):
                raise ProtocolError('Non-finite mesh vertex')
            points.append(rt.point3(*to_max((x + origin[0], y + origin[1], z + origin[2]), self.units)))
            uv.append(rt.point3(u, 1.0-v, 0))
        faces = [rt.point3(i+1, i+2, i+3) for i in range(0, count, 3)]
        with pymxs.undo(False), pymxs.redraw(False):
            new_node = rt.mesh(name=f'MaxCraft_{self.id}_{key}', vertices=rt.Array(*points), faces=rt.Array(*faces))
            try:
                rt.setNumTVerts(new_node, count)
                rt.buildTVFaces(new_node)
                for i, p in enumerate(uv, 1):
                    rt.setTVert(new_node, i, p)
                for i, face in enumerate(faces, 1):
                    rt.setTVFace(new_node, i, face)
                if texture in self.materials:
                    new_node.material = self.materials[texture]
                new_node.wirecolor = rt.color(155, 210, 150)
                rt.setUserProp(new_node, 'MaxCraftOwned', self.id)
                rt.update(new_node)
                self.delete_key(key)
                self.nodes[key] = new_node
            except Exception:
                rt.delete(new_node)
                raise

    def consume(self, kind, data, player=None):
        if kind == 1:
            if len(data) < 8:
                raise ProtocolError('Truncated atlas')
            w, h = struct.unpack_from('<II', data)
            self.texture(0, w, h, data[8:])
        elif kind == 2:
            if len(data) < 16:
                raise ProtocolError('Truncated section')
            sx, sy, sz, count = struct.unpack_from('<iiiI', data)
            self.mesh(f'section_{sx}_{sy}_{sz}', data[16:], count, (sx*16, sy*16, sz*16))
        elif kind == 3:
            self.clear()
        elif kind == 4:
            if len(data) < 16:
                raise ProtocolError('Truncated texture')
            key, w, h, _ = struct.unpack_from('<4I', data)
            self.texture(key, w, h, data[16:])
        elif kind in (5, 6):
            header = 8 if kind == 5 else 32
            if len(data) < header:
                raise ProtocolError('Truncated entity batch')
            if kind == 5:
                batches, vertices = struct.unpack_from('<II', data)
                origin = player['pos'] if player else (0, 100, 0)
            else:
                x, y, z, batches, vertices = struct.unpack_from('<dddII', data)
                origin = (x, y, z)
            if batches > 2048 or len(data) != header + batches * 16 + vertices * 32:
                raise ProtocolError('Invalid entity batch size')
            prefix = 'avatar' if kind == 5 else 'entities'
            keep = set()
            start = header + batches * 16
            for i in range(batches):
                tex, first, count, flags = struct.unpack_from('<4I', data, header + i*16)
                if first + count > vertices:
                    raise ProtocolError('Entity vertex range exceeds buffer')
                key = f'{prefix}_{i}'
                self.mesh(key, data[start + first*32:start + (first+count)*32], count, origin, tex)
                keep.add(key)
            for key in list(self.nodes):
                if key.startswith(prefix) and key not in keep:
                    self.delete_key(key)
        # 7: animated atlas patches; 8/10: light/solids; 9: ragdoll; 11: destructive
        # host edits. These are consumed by the transport but unsupported in v0.1.

    def clear(self):
        for key in list(self.nodes):
            self.delete_key(key)


def create_demo():
    """Small additive Max-native play space, placed only once."""
    if any(rt.getUserProp(n, 'MaxCraftDemo') for n in rt.objects):
        return
    colors = [(112, 142, 95), (155, 159, 168), (211, 133, 71)]
    materials = []
    for i, rgb in enumerate(colors):
        mat = rt.standardMaterial(name=f'MaxCraft_Demo_Material_{i}')
        mat.diffuse = rt.color(*rgb)
        materials.append(mat)
    with pymxs.undo(True, 'Create MaxCraft demo'):
        specs = [('Ground', (0, 0, -35), (1680, 1680, 35), 0),
                 ('Plinth', (0, -350, 0), (280, 210, 35), 1),
                 ('Wall', (-350, -300, 0), (70, 420, 210), 1)]
        for i in range(5):
            specs.append((f'Step_{i}', (350, -70*i, 0), (140, 70, 35*(i+1)), 1))
        for name, pos, dims, material in specs:
            node = rt.box(name=f'MaxCraft_Demo_{name}', pos=rt.point3(*pos), width=dims[0], length=dims[1], height=dims[2])
            node.material = materials[material]
            rt.setUserProp(node, 'MaxCraftDemo', True)
        teapot = rt.teapot(name='MaxCraft_Demo_Teapot', radius=65, segs=3, pos=rt.point3(0, -350, 35))
        teapot.material = materials[2]
        rt.setUserProp(teapot, 'MaxCraftDemo', True)
    rt.redrawViews()

