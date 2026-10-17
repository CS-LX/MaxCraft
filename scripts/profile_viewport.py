"""Run inside Max with a connected game; collect 20 seconds without blocking UI.

Measures host bridge work, not display FPS. Does not modify the Minecraft world.
"""
import json
import math
import time
from pathlib import Path
from PySide6 import QtCore
import maxcraft.ui


class Profile(QtCore.QObject):
    def __init__(self, panel, seconds=20, rotate=False):
        super().__init__(panel)
        if not panel.playing or not panel.player:
            raise RuntimeError('Start the game before profiling')
        self.p = panel
        self.rotate, self.yaw = rotate, panel.yaw
        self.originals, self.samples = [], {}
        self.start = time.perf_counter()
        self.ticks, self.frame = panel.ticks, panel.player['frame']
        self.skipped, self.reused = panel.scene.skipped_meshes, panel.scene.reused_meshes
        for obj, name in [(panel, 'update_bridge'), (panel.scene, 'camera'),
                          (panel.scene, 'mesh'), (panel.scene, 'atlas_patch'),
                          (panel.scene, 'flush_textures'), (panel.link, 'overlay'),
                          (panel.link.render, 'read')]:
            original = getattr(obj, name)
            self.originals.append((obj, name, obj.__dict__.get(name)))
            values = self.samples[name] = []
            def measured(*args, _fn=original, _values=values, _name=name, **kwargs):
                start = time.perf_counter()
                try:
                    if self.rotate and _name == 'update_bridge':
                        panel.yaw = self.yaw+20*math.sin((start-self.start)*.7)
                    return _fn(*args, **kwargs)
                finally:
                    _values.append((time.perf_counter()-start)*1000)
            setattr(obj, name, measured)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.finish)
        self.timer.start(seconds*1000)

    def finish(self):
        for obj, name, original in self.originals:
            if original is None:
                obj.__dict__.pop(name, None)
            else:
                setattr(obj, name, original)
        self.originals.clear()
        elapsed = time.perf_counter()-self.start
        p = self.p
        if self.rotate:
            p.yaw = self.yaw
        self.result = dict(seconds=elapsed, bridge_hz=(p.ticks-self.ticks)/elapsed,
                           mode='rotating_camera' if self.rotate else 'stationary_camera',
                           mc_render_hz=(p.player['frame']-self.frame)/elapsed,
                           raw_meshes={k:v[1] for k,v in p.scene.raw_meshes.items()},
                           materials=len(p.scene.materials), errors=p.error_count,
                           hud_size=[p.render_width,p.render_height],
                           skipped_meshes=p.scene.skipped_meshes-self.skipped,
                           reused_meshes=p.scene.reused_meshes-self.reused,
                           timing={k:dict(n=len(v),mean_ms=sum(v)/len(v),
                                          p95_ms=sorted(v)[int((len(v)-1)*.95)],max_ms=max(v))
                                   for k,v in self.samples.items() if v})
        output = Path(__file__).resolve().parents[1]/'logs/perf-after.json'
        output.parent.mkdir(exist_ok=True)
        output.write_text(json.dumps(self.result,indent=2),encoding='utf-8')


maxcraft.ui._profile = Profile(maxcraft.ui._panel, rotate=globals().get('ROTATE', False))
