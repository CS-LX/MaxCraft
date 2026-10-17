"""Max-only regression: replay a real received mesh and restore it in finally.

Does not send commands or change the Minecraft world. Runs outside the MCP
callback so the nested redraw counter can be checked from an enabled state.
"""
import json
from pathlib import Path
from PySide6 import QtCore
from pymxs import runtime as rt
from maxcraft.scene import suspend_redraw
import maxcraft.ui


def validate():
    p = maxcraft.ui._panel
    s = p.scene
    result = {}
    key = next(k for k in s.render_packets if k.startswith('section_') and k.endswith(':solid'))
    data, count, origin, texture = packet = s.render_packets[key]
    try:
        assert not rt.isSceneRedrawDisabled(), 'Viewport redraw already disabled'
        rt.disableSceneRedraw()
        try:
            try:
                with suspend_redraw():
                    raise ValueError('Intentional nested redraw exception')
            except ValueError:
                pass
            assert rt.isSceneRedrawDisabled()
        finally:
            rt.enableSceneRedraw()
        assert not rt.isSceneRedrawDisabled(), 'Nested redraw leaked a counter'
        result['nested_redraw_exception_restored'] = True
        node = s.nodes[key]
        handle = int(node.handle)
        mat = int(rt.getHandleByAnim(node.material))
        point = tuple(rt.getVert(node, 1))
        uv = tuple(rt.getTVert(node, 1))
        if key in getattr(s, 'atlas_tiles', {}):
            from maxcraft.protocol import VERTEX
            vertex = VERTEX.unpack_from(data)
            expected_color = tuple(((vertex[5] >> (8*c)) & 255)/255 for c in range(3))
            color = tuple(rt.meshop.getMapVert(node, 0, 1))
            assert all(abs(a-b) < 1e-5 for a,b in zip(color,expected_color))
            assert abs(uv[0]-vertex[3]) < 1e-5 and abs(uv[1]-(1-vertex[4])) < 1e-5
            result['original_atlas_uv_and_vertex_tint'] = True
        skipped = s.skipped_meshes
        s._mesh(key, *packet)
        assert s.skipped_meshes == skipped+1
        s._mesh(key, data, count, (origin[0]+.125, origin[1], origin[2]), texture)
        assert int(s.nodes[key].handle) == handle
        assert int(rt.getHandleByAnim(node.material)) == mat
        assert abs(rt.getVert(node, 1).x-point[0]-.125*s.units) < .001
        assert tuple(rt.getTVert(node, 1)) == uv
        result['position_update_keeps_node_material_and_uv'] = True
        s._mesh(key, data+data[:96], count+3, origin, texture)
        assert int(s.nodes[key].handle) == handle
        assert int(rt.getNumTVerts(node)) == count+3
        assert int(rt.getNumFaces(node)) == (count+3)//3
        assert tuple(rt.getTVFace(node, (count+3)//3)) == (count+1,count+2,count+3)
        if key in getattr(s, 'atlas_tiles', {}):
            assert int(rt.meshop.getNumMapVerts(node, 0)) == count+3
            assert tuple(rt.meshop.getMapFace(node, 0, (count+3)//3)) == (count+1,count+2,count+3)
        result['topology_update_keeps_node_and_correct_mapping'] = True
        result['duplicate_packet_skipped'] = True
        if key in getattr(s, 'atlas_tiles', {}):
            import struct
            atlas = s.textures[0]
            used = set().union(*(tiles for tex,tiles in s.atlas_tiles.values() if tex == 0))
            unused = next((x,y) for x in range(atlas.width()//16)
                          for y in range(atlas.height()//16) if (x,y) not in used)
            for tile, should_upload in ((unused, False), (next(iter(used)), True)):
                x, y = (v*16 for v in tile)
                header = struct.pack('<4I', x, y, 1, 1)
                original_image = atlas.copy(x,y,1,1)
                original = bytes(original_image.constBits())
                dirty = set(s.dirty_atlases)
                try:
                    s.dirty_atlases.clear()
                    changed = bytes((original[0]^255, *original[1:]))
                    s.atlas_patch(header+changed)
                    assert (0 in s.dirty_atlases) == should_upload
                    actual_image = atlas.copy(x,y,1,1)
                    assert bytes(actual_image.constBits()) == changed
                finally:
                    s.atlas_patch(header+original)
                    s.dirty_atlases = dirty
            result['atlas_patches_upload_only_used_regions'] = True
    except Exception as error:
        result['error'] = str(error)
    finally:
        s._mesh(key, *packet)
        rt.redrawViews()
    result['restored_vertex_count'] = int(rt.getNumVerts(s.nodes[key]))
    result['passed'] = 'error' not in result
    output = Path(__file__).resolve().parents[1]/'logs/mesh-update-validation.json'
    output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    p._mesh_validation = result


QtCore.QTimer.singleShot(100, validate)
