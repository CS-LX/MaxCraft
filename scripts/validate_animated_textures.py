"""Max-only regression on the connected world's real animated geometry.

Checks UV reconstruction, material assignments, actual pixel animation and
absence of file writes for full atlases / unused sprite materials. Does not
change Minecraft blocks, the player's position, or scene geometry.
"""
import hashlib
import json
from pathlib import Path
from PySide6 import QtCore,QtGui
from pymxs import runtime as rt
from maxcraft.protocol import VERTEX
import maxcraft.ui as ui


class AnimationValidation(QtCore.QObject):
    def __init__(self, panel):
        super().__init__(panel)
        self.p=panel
        self.result={}
        QtCore.QTimer.singleShot(100,self.start)

    def start(self):
        try:
            s=self.p.scene
            active=set().union(*(set(v) for v in s.animation_bindings.values()))
            self.paths=[path for key,(mat,path) in s.animation_materials.items() if key in active]
            assert self.paths, 'Current view needs an animated atlas region'
            self.hashes={p:hashlib.sha256(p.read_bytes()).hexdigest() for p in self.paths}
            self.full={p:p.stat().st_mtime_ns for p in s.cache.glob('atlas-*.png')}
            used=set().union(*s.mesh_material_keys.values())
            inactive=[key for key in s.sprite_maps if key not in used]
            if inactive:
                key=inactive[0]
                path=s.sprite_maps[key][0]
                before=path.stat().st_mtime_ns
                marker='__MaxCraft_animation_validation__'
                try:
                    s.dirty_sprites.add(key)
                    s.mesh_material_keys[marker]={key}
                    s.flush_textures(1)
                    assert key not in s.dirty_sprites
                    assert path.stat().st_mtime_ns!=before
                    self.result['reactivated_sprite_refreshed']=True
                finally:
                    s.mesh_material_keys.pop(marker,None)
            self.unused={path:path.stat().st_mtime_ns for key,(path,_,_) in s.sprite_maps.items()
                         if key not in used and path.exists()}
            faces=0
            for key,bindings in s.animation_bindings.items():
                if not any(region for texture,region in bindings):
                    continue
                node=s.nodes[key]
                data,count,origin,texture=s.render_packets[key]
                width,height=s.textures[texture].width(),s.textures[texture].height()
                vertices=list(VERTEX.iter_unpack(data))
                for i in range(0,count,3):
                    binding=bindings[int(rt.getFaceMatID(node,i//3+1))-1]
                    rect=binding[1]
                    for j in range(3):
                        uv=rt.getTVert(node,i+j+1)
                        x,y,w,h=rect if rect else (0,0,width,height)
                        u=(uv.x*w+x)/width
                        v=((1-uv.y)*h+y)/height
                        assert abs(u-vertices[i+j][3])<1e-5 and abs(v-vertices[i+j][4])<1e-5
                    faces+=1
            self.result['faces_with_verified_uvs']=faces
            self.result['animated_images']=[list((QtGui.QImage(str(p)).size().toTuple())) for p in self.paths]
            self.result['unused_sprite_count']=len(self.unused)
            QtCore.QTimer.singleShot(2500,self.finish)
        except Exception as error:
            self.result['error']=repr(error)
            self.save()

    def finish(self):
        try:
            self.result['animated_pixels_changed']=sum(hashlib.sha256(p.read_bytes()).hexdigest()!=h
                                                       for p,h in self.hashes.items())
            assert self.result['animated_pixels_changed']>0, 'Animated pixels stopped updating'
            assert all(p.stat().st_mtime_ns==stamp for p,stamp in self.full.items()), 'Full atlas rewritten'
            assert all(p.stat().st_mtime_ns==stamp for p,stamp in self.unused.items()), 'Unused sprite rewritten'
            self.result['full_atlas_not_rewritten']=True
            self.result['unused_sprites_not_rewritten']=True
        except Exception as error:
            self.result['error']=repr(error)
        self.save()

    def save(self):
        self.result['errors']=self.p.error_count
        self.result['passed']='error' not in self.result and not self.p.error_count
        root=Path(__file__).resolve().parents[1]
        (root/'logs/animated-texture-validation.json').write_text(json.dumps(self.result,indent=2),encoding='utf-8')


ui._animation_validation=AnimationValidation(ui._panel)
