"""Shared-atlas cutout batches: original UVs, vertex tint and explicit depth."""
from pathlib import Path
from itertools import chain
import math
import struct
import time
import pymxs
from pymxs import runtime as rt
from .scene import Scene, suspend_redraw, point_array
from .geometry import HEIGHT_OFFSET
from .protocol import VERTEX, ProtocolError
from .textures import region_for_uv


class AtlasScene(Scene):
    def __init__(self, units=70.0):
        super().__init__(units)
        self.init_atlases()

    def init_atlases(self):
        self.atlas_materials = {}
        self.atlas_tiles = {}
        self.dirty_atlases = set()
        self.last_atlas_flush = 0.0
        self._atlas_bulk_ready = False

    def atlas_material(self, texture):
        if texture not in self.atlas_materials:
            path = self.cache / f'atlas-{texture}.png'
            if not self.textures[texture].save(str(path)):
                raise OSError('Could not save Minecraft atlas')
            mat = rt.DirectX_9_Shader(name=f'MaxCraft_{self.id}_atlas_{texture}',
                                     effectFile=str(Path(__file__).parent/'shaders/world.fx'))
            mat.Sprite = rt.openBitmap(str(path))
            self.atlas_materials[texture] = mat
        return self.atlas_materials[texture]

    def texture(self,key,w,h,pixels):
        super().texture(key,w,h,pixels)
        if key in self.atlas_materials:
            self.dirty_atlases.add(key)

    def _mesh(self, key, data, count, origin, texture=0):
        if count > 500000 or count % 3 or len(data) != count*32:
            raise ProtocolError('Invalid mesh packet')
        if not count:
            self.atlas_tiles.pop(key, None)
            return super()._mesh(key, data, count, origin, texture)
        packet = (data,count,origin,texture)
        node = self.nodes.get(key)
        valid = node is not None and rt.isValidNode(node)
        if valid and self.render_packets.get(key) == packet:
            self.skipped_meshes += 1
            return
        verts = list(VERTEX.iter_unpack(data))
        if not key.endswith(':solid') or texture not in self.textures or any(v[7] & 4 for v in verts):
            self.atlas_tiles.pop(key, None)
            return super()._mesh(key, data, count, origin, texture)
        if not all(map(math.isfinite, chain.from_iterable(v[:5] for v in verts))):
            raise ProtocolError('Non-finite mesh vertex')
        x, y, z = origin
        scale = self.units
        points = point_array(((v[0]+x)*scale, -(v[2]+z)*scale, (v[1]+y-HEIGHT_OFFSET)*scale) for v in verts)
        layout = ('atlas',count,texture,b''.join(data[i+12:i+24] for i in range(0,len(data),32)))
        if valid and self.mesh_layouts.get(key) == layout:
            with pymxs.undo(False), suspend_redraw():
                rt.setMesh(node, vertices=points)
                rt.update(node)
            self.reused_meshes += 1
        else:
            uv = point_array((v[3],1-v[4],0) for v in verts)
            colors = point_array(tuple(((v[5]>>(8*c))&255)/255 for c in range(3)) for v in verts)
            faces = rt.execute(f'for i=1 to {count} by 3 collect [i,i+1,i+2]')
            mat = self.atlas_material(texture)
            with pymxs.undo(False), suspend_redraw():
                if not valid:
                    node = rt.mesh(name=f'MaxCraft_{self.id}_{key}')
                try:
                    if not self._atlas_bulk_ready:
                        rt.execute('''fn MaxCraftApplyAtlasMesh node verts faces uvs colors material = (
                            setMesh node vertices:verts faces:faces tverts:uvs
                            buildTVFaces node
                            meshop.setMapSupport node 0 true
                            meshop.setNumMapVerts node 0 colors.count
                            meshop.setNumMapFaces node 0 faces.count
                            for i=1 to colors.count do meshop.setMapVert node 0 i colors[i]
                            for i=1 to faces.count do (
                                setTVFace node i faces[i]
                                meshop.setMapFace node 0 i faces[i]
                                setFaceMatID node i 1
                                setFaceSmoothGroup node i 0
                            )
                            node.material=material
                            update node
                        )''')
                        self._atlas_bulk_ready = True
                    rt.MaxCraftApplyAtlasMesh(node,points,faces,uv,colors,mat)
                    rt.setUserProp(node,'MaxCraftOwned',self.id)
                except Exception:
                    if not valid:
                        rt.delete(node)
                    raise
            w,h = self.textures[texture].width(),self.textures[texture].height()
            tiles=set()
            for i in range(0,count,3):
                tri=verts[i:i+3]
                x,y,rw,rh=region_for_uv([(v[3],v[4]) for v in tri],w,h)
                x0,y0=x//16,y//16
                x1,y1=(x+rw-1)//16,(y+rh-1)//16
                tiles.update((x,y) for x in range(x0,x1+1) for y in range(y0,y1+1))
            self.atlas_tiles[key]=(texture,tiles)
            self.mesh_material_keys[key]=set()
            # A batch may switch between atlas and fallback materials. Never
            # reuse the fallback's previous MultiMaterial binding after that.
            getattr(self, 'bound_materials', {}).pop(key, None)
        self.nodes[key]=node
        self.render_packets[key]=packet
        self.mesh_layouts[key]=layout
        self.geometry_changed=True

    def atlas_patch(self,data):
        if not super().atlas_patch(data):
            return
        x,y,w,h=struct.unpack_from('<4I',data)
        changed={(a,b) for a in range(x//16,(x+w-1)//16+1) for b in range(y//16,(y+h-1)//16+1)}
        if any(tex==0 and changed.intersection(tiles) for tex,tiles in self.atlas_tiles.values()):
            self.dirty_atlases.add(0)

    def flush_textures(self,budget=2):
        super().flush_textures(budget)
        if self.dirty_atlases and time.monotonic()-self.last_atlas_flush>=.1:
            texture=self.dirty_atlases.pop()
            if texture in self.atlas_materials:
                path=self.cache/f'atlas-{texture}.png'
                if not self.textures[texture].save(str(path)):
                    raise OSError('Could not refresh Minecraft atlas')
                self.atlas_materials[texture].Sprite=rt.openBitmap(str(path))
                self.geometry_changed=True
            self.last_atlas_flush=time.monotonic()

    def delete_key(self,key):
        self.atlas_tiles.pop(key,None)
        super().delete_key(key)

    def clear(self):
        super().clear()
        self.atlas_materials.clear()
        self.atlas_tiles.clear()
        self.dirty_atlases.clear()
