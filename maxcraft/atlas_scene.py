"""Shared-atlas cutout batches: original UVs, vertex tint and explicit depth."""
from pathlib import Path
from itertools import chain
import math
import struct
import time
import pymxs
from pymxs import runtime as rt
from .scene import Scene, suspend_redraw, point_array, set_effect_texture
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
        self.animation_regions = {}
        self.animation_materials = {}
        self.animation_bitmaps = {}
        self.animation_bindings = {}
        self.dirty_animations = set()
        self.remap_meshes = set()
        self.last_animation_flush = 0.0

    def atlas_material(self, texture):
        if texture not in self.atlas_materials:
            path = self.cache / f'atlas-{texture}.png'
            if not self.textures[texture].save(str(path)):
                raise OSError('Could not save Minecraft atlas')
            mat = rt.DirectX_9_Shader(name=f'MaxCraft_{self.id}_atlas_{texture}',
                                     effectFile=str(Path(__file__).parent/'shaders/world.fx'))
            set_effect_texture(mat,path)
            self.atlas_materials[texture] = mat
        return self.atlas_materials[texture]

    def texture(self,key,w,h,pixels):
        super().texture(key,w,h,pixels)
        if key in self.atlas_materials:
            self.dirty_atlases.add(key)
        self.dirty_animations.update(k for k in self.animation_materials if k[0] == key)

    def animation_material(self, key):
        if key not in self.animation_materials:
            texture, rect = key
            path = self.cache / ('animation-'+'-'.join(map(str,(texture,*rect)))+'.png')
            mat = rt.DirectX_9_Shader(name=f'MaxCraft_{self.id}_animation_{len(self.animation_materials)}',
                                     effectFile=str(Path(__file__).parent/'shaders/world.fx'))
            # DirectX effects consume the filename, not MAXScript pixel storage.
            # Reuse a descriptor instead of decoding it through openBitmap on
            # every update (measured 70-100 ms even for a 48 px image).
            bitmap=rt.bitmap(rect[2],rect[3],filename=str(path))
            # Max rejects an unsaved output bitmap even if an external writer
            # has already created that filename. Save once to register it.
            rt.save(bitmap)
            if not self.textures[texture].copy(*rect).save(str(path)):
                rt.close(bitmap)
                raise OSError('Could not save animated Minecraft region')
            set_effect_texture(mat,path,bitmap)
            self.animation_materials[key] = (mat,path)
            self.animation_bitmaps[key] = bitmap
        return self.animation_materials[key][0]

    def animation_region(self, texture, rect):
        x,y,w,h = rect
        region = self.animation_regions.get((texture,x//16,y//16))
        if region:
            rx,ry,rw,rh = region
            if rx <= x and ry <= y and x+w <= rx+rw and y+h <= ry+rh:
                return region
        return None

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
            self.animation_bindings.pop(key, None)
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
            width,height = self.textures[texture].width(),self.textures[texture].height()
            uv,ids,bindings,tiles = [],[],{},set()
            if texture != 0:
                # Entity/particle skins receive separate complete textures.
                # They do not need block-animation region discovery per face.
                uv=[(v[3],1-v[4],0) for v in verts]
                ids=[1]*(count//3)
                bindings[(texture,None)]=1
            for i in range(0,count if texture == 0 else 0,3):
                tri=verts[i:i+3]
                rect=region_for_uv([(v[3],v[4]) for v in tri],width,height)
                region=self.animation_region(texture,rect)
                binding=(texture,region)
                if binding not in bindings:
                    bindings[binding]=len(bindings)+1
                ids.append(bindings[binding])
                if region:
                    x,y,w,h=region
                    uv.extend(((v[3]*width-x)/w,1-(v[4]*height-y)/h,0) for v in tri)
                else:
                    uv.extend((v[3],1-v[4],0) for v in tri)
                    x,y,w,h=rect
                    tiles.update((a,b) for a in range(x//16,(x+w-1)//16+1)
                                 for b in range(y//16,(y+h-1)//16+1))
            uv = point_array(uv)
            colors = point_array(tuple(((v[5]>>(8*c))&255)/255 for c in range(3)) for v in verts)
            faces = rt.execute(f'for i=1 to {count} by 3 collect [i,i+1,i+2]')
            binding_keys=tuple(bindings)
            if valid and self.animation_bindings.get(key) == binding_keys:
                mat=node.material
            else:
                mats=[self.animation_material(binding) if binding[1] else self.atlas_material(texture)
                      for binding in binding_keys]
                if len(mats)==1:
                    mat=mats[0]
                else:
                    mat=rt.multiMaterial(numsubs=len(mats))
                    for i,item in enumerate(mats):
                        mat[i]=item
            with pymxs.undo(False), suspend_redraw():
                if not valid:
                    node = rt.mesh(name=f'MaxCraft_{self.id}_{key}')
                try:
                    if not self._atlas_bulk_ready:
                        rt.execute('''fn MaxCraftApplyAtlasMesh node verts faces uvs colors ids material = (
                            setMesh node vertices:verts faces:faces tverts:uvs
                            buildTVFaces node
                            meshop.setMapSupport node 0 true
                            meshop.setNumMapVerts node 0 colors.count
                            meshop.setNumMapFaces node 0 faces.count
                            for i=1 to colors.count do meshop.setMapVert node 0 i colors[i]
                            for i=1 to faces.count do (
                                setTVFace node i faces[i]
                                meshop.setMapFace node 0 i faces[i]
                                setFaceMatID node i ids[i]
                                setFaceSmoothGroup node i 0
                            )
                            node.material=material
                            update node
                        )''')
                        self._atlas_bulk_ready = True
                    rt.MaxCraftApplyAtlasMesh(node,points,faces,uv,colors,rt.Array(*ids),mat)
                    rt.setUserProp(node,'MaxCraftOwned',self.id)
                except Exception:
                    if not valid:
                        rt.delete(node)
                    raise
            self.atlas_tiles[key]=(texture,tiles)
            self.animation_bindings[key]=binding_keys
            self.mesh_material_keys[key]=set()
            # A batch may switch between atlas and fallback materials. Never
            # reuse the fallback's previous MultiMaterial binding after that.
            getattr(self, 'bound_materials', {}).pop(key, None)
        self.nodes[key]=node
        self.render_packets[key]=packet
        self.mesh_layouts[key]=layout
        self.geometry_changed=True

    def atlas_patch(self,data):
        changed_pixels=super().atlas_patch(data)
        if self.textures.get(0) is None:
            return
        x,y,w,h=struct.unpack_from('<4I',data)
        region=(x,y,w,h)
        changed={(a,b) for a in range(x//16,(x+w-1)//16+1) for b in range(y//16,(y+h-1)//16+1)}
        new=any(self.animation_regions.get((0,a,b)) != region for a,b in changed)
        if new:
            for a,b in changed:
                self.animation_regions[(0,a,b)]=region
            self.remap_meshes.update(key for key,(tex,tiles) in self.atlas_tiles.items()
                                     if tex==0 and changed.intersection(tiles))
        if not changed_pixels:
            return
        if (0,region) in self.animation_materials:
            self.dirty_animations.add((0,region))
        if any(tex==0 and changed.intersection(tiles) for tex,tiles in self.atlas_tiles.values()):
            self.dirty_atlases.add(0)

    def flush_textures(self,budget=2):
        if self.remap_meshes:
            key=self.remap_meshes.pop()
            packet=self.render_packets.pop(key,None)
            if packet:
                self.mesh_layouts.pop(key,None)
                self._mesh(key,*packet)
        super().flush_textures(budget)
        now=time.monotonic()
        if self.dirty_animations and now-self.last_animation_flush>=.05:
            active=set().union(*(set(bindings) for bindings in self.animation_bindings.values()))
            for key in list(self.dirty_animations.intersection(active))[:4]:
                texture,rect=key
                mat,path=self.animation_materials[key]
                if not self.textures[texture].copy(*rect).save(str(path)):
                    raise OSError('Could not refresh animated Minecraft region')
                set_effect_texture(mat,path,self.animation_bitmaps[key])
                self.dirty_animations.discard(key)
                self.geometry_changed=True
            self.last_animation_flush=now
        if self.dirty_atlases and time.monotonic()-self.last_atlas_flush>=.1:
            # While discovering regions, finish remapping before uploading the
            # full atlas. Once mapped, animated pixels only upload small crops.
            if self.remap_meshes:
                return
            texture=self.dirty_atlases.pop()
            if texture in self.atlas_materials:
                path=self.cache/f'atlas-{texture}.png'
                if not self.textures[texture].save(str(path)):
                    raise OSError('Could not refresh Minecraft atlas')
                set_effect_texture(self.atlas_materials[texture],path)
                self.geometry_changed=True
            self.last_atlas_flush=time.monotonic()

    def delete_key(self,key):
        self.atlas_tiles.pop(key,None)
        self.animation_bindings.pop(key,None)
        self.remap_meshes.discard(key)
        super().delete_key(key)

    def clear(self):
        super().clear()
        self.atlas_materials.clear()
        self.atlas_tiles.clear()
        self.dirty_atlases.clear()
        self.animation_regions.clear()
        self.animation_materials.clear()
        for bitmap in self.animation_bitmaps.values():
            rt.close(bitmap)
        self.animation_bitmaps.clear()
        self.animation_bindings.clear()
        self.dirty_animations.clear()
        self.remap_meshes.clear()
