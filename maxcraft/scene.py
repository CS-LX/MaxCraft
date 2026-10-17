"""Max main-thread adapter: native geometry, camera and texture materials."""
from pathlib import Path
from contextlib import contextmanager
import math
import struct
import time
import uuid
from PySide6 import QtCore, QtGui
import pymxs
from pymxs import runtime as rt
from .geometry import to_mc, to_max, camera_axes
from .protocol import VERTEX, ProtocolError
from .textures import region_for_uv, local_uv


@contextmanager
def suspend_redraw():
    # Max uses a counter. pymxs.redraw(False) increments it again on exit
    # when nested under an already disabled redraw, and skips cleanup on errors.
    rt.disableSceneRedraw()
    try:
        yield
    finally:
        rt.enableSceneRedraw()


class Scene:
    def __init__(self, units=70.0):
        self.units = units
        self.id = uuid.uuid4().hex[:8]
        self.nodes = {}
        self.materials = {}
        self.cutout_template = None
        self.cutout_pool = []
        self.textures = {}
        self.sprite_maps = {}
        self.raw_meshes = {}
        self.render_packets = {}
        self.dirty_sprites = set()
        self.mesh_material_keys = {}
        self.mesh_layouts = {}
        self.last_camera = None
        self.last_fov = None
        self.geometry_changed = False
        self.skipped_meshes = 0
        self.reused_meshes = 0
        self.sprite_id = 0
        self.cache = Path.home() / 'AppData' / 'Local' / 'MaxCraft' / 'cache' / self.id
        self.cache.mkdir(parents=True, exist_ok=True)
        self.previous = None
        self.last_dynamic = 0.0

    def capture_view(self):
        self.last_camera = self.last_fov = None
        self.viewport = int(rt.viewport.activeViewport)
        self.previous = (rt.viewport.getType(), rt.viewport.getTM(), rt.viewport.getFOV())
        self.previous_camera = rt.viewport.getCamera()
        self.previous_background = rt.NitrousGraphicsManager.BackgroundProgressiveRenderingEnabled
        # The Qt game overlay owns focus while the underlying Max view draws.
        rt.NitrousGraphicsManager.BackgroundProgressiveRenderingEnabled = True
        settings = rt.NitrousGraphicsManager.GetActiveViewportSetting()
        self.previous_display = (settings.TextureSizeLimit, settings.UseTextureEnabled,
                                 rt.viewport.getGridVisibility(self.viewport),
                                 settings.ShowMaterialOption, settings.TransparencyEnabled)
        self.previous_progressive = settings.ProgressiveRenderingEnabled
        # Allow background refinement while the Qt game overlay owns focus.
        settings.ProgressiveRenderingEnabled = True
        settings.TextureSizeLimit = max(4096, settings.TextureSizeLimit)
        settings.UseTextureEnabled = True
        settings.ShowMaterialOption = rt.Name('Realistic')
        settings.TransparencyEnabled = True
        rt.viewport.setGridVisibility(self.viewport, False)
        rt.viewport.setType(rt.Name('view_persp_user'))

    def restore_view(self):
        if self.previous:
            kind, matrix, fov = self.previous
            rt.viewport.activeViewport = self.viewport
            rt.NitrousGraphicsManager.BackgroundProgressiveRenderingEnabled = self.previous_background
            settings = rt.NitrousGraphicsManager.GetActiveViewportSetting()
            size, textures, grid, material_mode, transparency = self.previous_display
            settings.TextureSizeLimit = size
            settings.UseTextureEnabled = textures
            settings.ShowMaterialOption = material_mode
            settings.TransparencyEnabled = transparency
            settings.ProgressiveRenderingEnabled = self.previous_progressive
            rt.viewport.setGridVisibility(self.viewport, grid)
            if getattr(self, 'previous_camera', None) is not None and rt.isValidNode(self.previous_camera):
                rt.viewport.setCamera(self.previous_camera)
            else:
                rt.viewport.setType(kind)
                rt.viewport.setTM(matrix)
                rt.viewport.setFOV(fov)
            self.previous = None
            rt.redrawViews()

    def camera(self, state, yaw, pitch, aspect):
        if not self.previous or not (state['flags'] & 1):
            return
        signature = (state['eye'], yaw, pitch, aspect, state['fov'], state['camera_mode'], state['camera_distance'])
        if signature == self.last_camera:
            if self.geometry_changed:
                rt.redrawViews()
                self.geometry_changed = False
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
        if int(rt.viewport.activeViewport) != self.viewport:
            rt.viewport.activeViewport = self.viewport
        rt.viewport.setTM(rt.inverse(camera))
        vfov = max(10.0, min(140.0, state['fov'] or 70.0))
        hfov = math.degrees(2 * math.atan(math.tan(math.radians(vfov) / 2) * aspect))
        if hfov != self.last_fov:
            rt.viewport.setFOV(hfov)
            self.last_fov = hfov
        rt.redrawViews()
        self.last_camera = signature
        self.geometry_changed = False

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
        for sprite in self.sprite_maps:
            if sprite[0] == key:
                self.write_sprite(sprite)

    def write_sprite(self, key):
        texture, rect, tint, flags = key
        image = self.textures[texture].copy(*rect).convertToFormat(QtGui.QImage.Format_RGBA8888)
        # Bake the per-face tint provided by MC (grass/leaves/water), preserving alpha.
        if tint != (255, 255, 255, 255):
            pixels = image.bits()
            for i in range(0, image.sizeInBytes(), 4):
                for channel in range(4):
                    pixels[i+channel] = pixels[i+channel] * tint[channel] // 255
        # Standard blended materials need expanded pixels to resist Nitrous
        # filtering. The cutout shader samples native sprites with point filtering.
        scale = (max(1, min(16, 512 // max(image.width(), image.height()))) if flags & 2 else 1)
        image = image.scaled(image.width()*scale, image.height()*scale,
                             QtCore.Qt.IgnoreAspectRatio, QtCore.Qt.FastTransformation)
        path, tex, opacity = self.sprite_maps[key]
        if not image.save(str(path)):
            raise OSError('Could not save Minecraft sprite')
        if tex is not None:
            if opacity is None:
                tex.Sprite = rt.openBitmap(str(path))
            else:
                tex.reload()
                opacity.reload()
            self.geometry_changed = True

    def flush_textures(self, budget=2):
        for _ in range(min(budget, len(self.dirty_sprites))):
            self.write_sprite(self.dirty_sprites.pop())

    def atlas_patch(self, data):
        if len(data) < 16:
            raise ProtocolError('Truncated animated atlas patch')
        x, y, w, h = struct.unpack_from('<4I', data)
        atlas = self.textures.get(0)
        if atlas is None:
            return
        if not (w and h and x+w <= atlas.width() and y+h <= atlas.height() and len(data) == 16+w*h*4):
            raise ProtocolError('Invalid animated atlas patch')
        image = QtGui.QImage(data[16:], w, h, w*4, QtGui.QImage.Format_RGBA8888)
        if atlas.copy(x, y, w, h) == image:
            return
        painter = QtGui.QPainter(atlas)
        painter.setCompositionMode(QtGui.QPainter.CompositionMode_Source)
        painter.drawImage(x, y, image)
        painter.end()
        area = QtCore.QRect(x, y, w, h)
        for key in self.sprite_maps:
            if key[0] == 0 and area.intersects(QtCore.QRect(*key[1])):
                self.dirty_sprites.add(key)

    def face_material(self, texture, vertices, dynamic=False):
        flags = vertices[0][7]
        tint = tuple(round(sum((v[5] >> (8*c)) & 255 for v in vertices)/3) for c in range(4))
        if dynamic:
            # Nitrous cannot reliably evaluate Vertex Color through the composed
            # opacity shader here. Quantize per-face particle fades and bound the
            # cache, instead of creating a new material for every 8-bit value.
            tint = tuple(min(255, round(c/32)*32) for c in tint)
        if flags & 4 or texture not in self.textures:
            key = ('plain', tint)
            if key not in self.materials:
                mat = rt.standardMaterial(name=f'MaxCraft_{self.id}_plain_{len(self.materials)}')
                mat.diffuse = rt.color(*tint[:3]); mat.opacity = tint[3]*100/255
                mat.selfIllumAmount = 100; mat.twoSided = True
                self.materials[key] = mat
            return key, [rt.point3(v[3], 1-v[4], 0) for v in vertices]
        image = self.textures[texture]
        rect = region_for_uv([(v[3], v[4]) for v in vertices], image.width(), image.height())
        key = (texture, rect, tint, flags & 3)
        if key not in self.materials:
            if len(self.materials) >= 4096:
                raise ProtocolError('Sprite material limit exceeded; use a smaller world')
            path = self.cache / f'sprite-{self.sprite_id}.png'
            self.sprite_id += 1
            self.sprite_maps[key] = (path, None, None)
            if not flags & 2:
                # Alpha-tested surfaces write depth. Treating leaves as blended
                # opacity maps made entire chunk objects transparent in Nitrous.
                if self.cutout_template is None:
                    self.cutout_template = rt.DirectX_9_Shader(
                        effectFile=str(Path(__file__).parent / 'shaders/voxel.fx'))
                # Max's first effect clone after bitmap I/O waits ~1 s; later
                # clones cost ~10 ms. Batch clones before writing new sprites,
                # so a chunk doesn't pay that wait once per material.
                if not self.cutout_pool:
                    self.cutout_pool = [rt.copy(self.cutout_template) for _ in range(64)]
                mat = self.cutout_pool.pop()
                mat.name = f'MaxCraft_{self.id}_cutout_{len(self.materials)}'
                self.write_sprite(key)
                mat.Sprite = rt.openBitmap(str(path))
                self.materials[key] = mat
                self.sprite_maps[key] = (path, mat, None)
                return key, [rt.point3(*local_uv((v[3],v[4]), rect, image.width(), image.height()), 0) for v in vertices]
            self.write_sprite(key)
            mat = rt.standardMaterial(name=f'MaxCraft_{self.id}_sprite_{len(self.materials)}')
            mat.diffuse = rt.color(255, 255, 255)
            mat.selfIllumAmount = 60; mat.twoSided = True
            tex = rt.bitmapTexture(filename=str(path)); tex.filtering = 2
            mat.diffuseMap = tex
            # The upstream alpha includes cutouts (plants) and translucent liquids.
            opacity = rt.bitmapTexture(filename=str(path)); opacity.filtering = 2
            opacity.alphaSource = 0; opacity.monoOutput = 1
            mat.opacityMap = opacity
            self.materials[key] = mat
            self.sprite_maps[key] = (path, tex, opacity)
            rt.showTextureMap(mat, tex, True)
            rt.enableHardwareMaterial(mat, True)
            rt.showHWTextureMap(mat, True)
        return key, [rt.point3(*local_uv((v[3],v[4]), rect, image.width(), image.height()), 0) for v in vertices]

    def delete_key(self, key):
        node = self.nodes.pop(key, None)
        self.mesh_material_keys.pop(key, None)
        self.mesh_layouts.pop(key, None)
        self.render_packets.pop(key, None)
        getattr(self, 'bound_materials', {}).pop(key, None)
        if node is not None and rt.isValidNode(node):
            with pymxs.undo(False):
                rt.delete(node)
            self.geometry_changed = True

    def mesh(self, key, data, count, origin, texture=0):
        if count > 500000 or count % 3 or len(data) != count * 32:
            raise ProtocolError('Invalid mesh packet')
        self.raw_meshes[key] = (data, count, origin, texture)
        # Separate depth-writing solids/cutouts from alpha-blended surfaces so
        # Nitrous does not sort a whole chunk as one translucent object.
        solid, blend = [], []
        for i in range(0, len(data), 96):
            flags = struct.unpack_from('<I', data, i+28)[0]
            alpha = data[i+23]
            translucent = flags & 2 or (flags & 4 and alpha < 255)
            (blend if translucent else solid).append(data[i:i+96])
        for suffix, triangles in ((':solid', solid), (':blend', blend)):
            self._mesh(key+suffix, b''.join(triangles), len(triangles)*3, origin, texture)
        if not count:
            self.raw_meshes.pop(key, None)

    def _mesh(self, key, data, count, origin, texture=0):
        if count > 500000 or count % 3 or len(data) != count * 32:
            raise ProtocolError('Invalid mesh packet')
        if not count:
            self.delete_key(key)
            return
        packet = (data, count, origin, texture)
        if self.render_packets.get(key) == packet and key in self.nodes and rt.isValidNode(self.nodes[key]):
            self.skipped_meshes += 1
            return
        points, uv, materials, material_ids = [], [], {}, []
        vertices = list(VERTEX.iter_unpack(data))
        for x, y, z, u, v, color, light, flags in vertices:
            if not all(math.isfinite(n) for n in (x, y, z, u, v)):
                raise ProtocolError('Non-finite mesh vertex')
            points.append(rt.point3(*to_max((x + origin[0], y + origin[1], z + origin[2]), self.units)))
        layout = (count, texture, b''.join(data[i+12:i+24] + data[i+28:i+32] for i in range(0, len(data), 32)))
        node = self.nodes.get(key)
        valid = node is not None and rt.isValidNode(node)
        if valid and self.mesh_layouts.get(key) == layout:
            with pymxs.undo(False), suspend_redraw():
                rt.setMesh(node, vertices=rt.Array(*points))
                rt.update(node)
            self.render_packets[key] = packet
            self.reused_meshes += 1
            self.geometry_changed = True
            return
        for i in range(0, count, 3):
            mat_key, face_uv = self.face_material(texture, vertices[i:i+3], key.startswith(('entities', 'avatar')))
            if mat_key not in materials:
                materials[mat_key] = len(materials)+1
            material_ids.append(materials[mat_key]); uv.extend(face_uv)
        faces = [rt.point3(i+1, i+2, i+3) for i in range(0, count, 3)]
        with pymxs.undo(False), suspend_redraw():
            new_node = node if valid else rt.mesh(name=f'MaxCraft_{self.id}_{key}')
            try:
                # Keep scene nodes/material bindings stable. Build mapping faces
                # inside one MAXScript call instead of thousands of pymxs calls.
                keys = tuple(materials)
                if valid and getattr(self, 'bound_materials', {}).get(key) == keys:
                    mat = new_node.material
                else:
                    mat = rt.multiMaterial(numsubs=len(materials))
                    for mat_key, index in materials.items():
                        mat[index-1] = self.materials[mat_key]
                if not getattr(self, '_bulk_ready', False):
                    rt.execute('''fn MaxCraftApplyMesh node verts faces uvs ids material = (
                        setMesh node vertices:verts faces:faces tverts:uvs materialIDs:ids
                        buildTVFaces node
                        for i=1 to faces.count do (
                            setTVFace node i faces[i]
                            setFaceSmoothGroup node i 0
                        )
                        node.material=material
                        update node
                    )''')
                    self._bulk_ready = True
                rt.MaxCraftApplyMesh(new_node, rt.Array(*points), rt.Array(*faces), rt.Array(*uv), rt.Array(*material_ids), mat)
                new_node.wirecolor = rt.color(155, 210, 150)
                rt.setUserProp(new_node, 'MaxCraftOwned', self.id)
                rt.update(new_node)
                self.nodes[key] = new_node
                self.render_packets[key] = packet
                self.mesh_layouts[key] = layout
                if not hasattr(self, 'bound_materials'):
                    self.bound_materials = {}
                self.bound_materials[key] = keys
                self.mesh_material_keys[key] = set(materials)
                self.geometry_changed = True
                if len(self.materials) > 512:
                    active = set().union(*self.mesh_material_keys.values())
                    for old in set(self.materials)-active:
                        del self.materials[old]
                        sprite = self.sprite_maps.pop(old, None)
                        self.dirty_sprites.discard(old)
                        if sprite:
                            try: sprite[0].unlink(missing_ok=True)
                            except OSError: pass
            except Exception:
                if not valid:
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
        elif kind == 7:
            self.atlas_patch(data)
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
                if key.startswith(prefix) and key.rsplit(':', 1)[0] not in keep:
                    self.delete_key(key)
            for key in list(self.raw_meshes):
                if key.startswith(prefix) and key not in keep:
                    self.raw_meshes.pop(key, None)
        # 8/10: light/solids; 9: ragdoll; 11: destructive
        # host edits. These are consumed by the transport but unsupported in v0.1.

    def clear(self):
        for key in list(self.nodes):
            self.delete_key(key)
        self.raw_meshes.clear()
        self.render_packets.clear()
        self.dirty_sprites.clear()
        self.materials.clear()
        self.sprite_maps.clear()
        self.textures.clear()
        self.mesh_material_keys.clear()
        self.mesh_layouts.clear()
        self.bound_materials = {}


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

