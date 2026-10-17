"""Max-only: measure actual translated camera and dynamic mesh cadence.

Moves forward/back over a short path, releases all input, and restores the
player's starting position. No blocks/entities are created or destroyed.
"""
import json
import math
from pathlib import Path
import time
import zlib
from PySide6 import QtCore
from pymxs import runtime as rt
import maxcraft.ui as ui


class MotionProfile(QtCore.QObject):
    def __init__(self, panel, label='motion', seconds=12, capture=False):
        super().__init__(panel)
        if not panel.playing or not panel.player or panel.player['flags'] & 2:
            raise RuntimeError('Start the game and close Minecraft menus first')
        previous = getattr(ui, '_motion_profile', None)
        if previous is not None and previous.originals:
            raise RuntimeError('Another motion profile is still running')
        self.p, self.label, self.seconds = panel, label, seconds
        self.start = time.perf_counter()
        self.saved = (panel.player['pos'], panel.spawn, panel.yaw, panel.pitch)
        self.samples, self.dynamic, self.camera = [], [], []
        self.capture, self.viewport = capture, []
        self.originals = []
        self.finished = False
        self.key = None
        self.wrap(panel.scene, 'consume', self.consume)
        self.wrap(panel.scene, 'camera', self.camera_sample)
        self.wrap(panel, 'update_bridge', self.update)
        self.timer = QtCore.QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.finish)
        self.timer.start(seconds*1000)

    def wrap(self, obj, name, fn):
        original = getattr(obj, name)
        self.originals.append((obj, name, obj.__dict__.get(name)))
        setattr(obj, name, lambda *a, **kw: fn(original, *a, **kw))

    def consume(self, original, kind, *args):
        started = time.perf_counter()
        result = original(kind, *args)
        if kind in (5, 6):
            self.dynamic.append((started-self.start, kind, (time.perf_counter()-started)*1000))
        return result

    def camera_sample(self, original, state, *args):
        result = original(state, *args)
        self.camera.append((time.perf_counter()-self.start, tuple(state['eye'])))
        return result

    def update(self, original):
        elapsed = time.perf_counter()-self.start
        # Rest .4 s, W .6 s, rest .4 s, S .6 s; repeat along the same short path.
        phase = elapsed % 2
        key = 26 if .4 <= phase < 1 else 22 if 1.4 <= phase < 2 else None
        if key != self.key:
            if self.key is not None:
                self.p.link.input(1, self.key, 0)
            if key is not None:
                self.p.link.input(1, key, 1)
            self.key = key
        started = time.perf_counter()
        try:
            original()
        except Exception:
            self.finish()
            raise
        self.samples.append((elapsed, (time.perf_counter()-started)*1000,
                             self.p.player['frame'], tuple(self.p.player['eye'])))
        if self.capture:
            # Read the existing native window surface; no forced viewport redraw.
            image = self.p.overlay.screen().grabWindow(int(rt.viewport.getHWnd())).toImage().scaled(160,100)
            self.viewport.append((elapsed,zlib.crc32(image.constBits())))

    def finish(self):
        if self.finished:
            return
        self.finished = True
        self.timer.stop()
        p = self.p
        for obj, name, original in reversed(self.originals):
            if original is None:
                obj.__dict__.pop(name, None)
            else:
                setattr(obj, name, original)
        self.originals.clear()
        if p.link:
            p.link.input(6)
        duration = time.perf_counter()-self.start
        def cadence(samples):
            changed = [(b[0], math.dist(a[1], b[1])) for a,b in zip(samples,samples[1:])
                       if math.dist(a[1],b[1]) > 1e-6]
            # Interior of the held-key interval, after acceleration settles.
            moving = [(b[0]-a[0], math.dist(a[1],b[1])) for a,b in zip(samples,samples[1:])
                      if .65 < b[0]%2 < .95 or 1.65 < b[0]%2 < 1.95]
            return dict(changes=len(changed), repeated_moving_samples=sum(d<1e-6 for dt,d in moving),
                        moving_samples=len(moving), max_moving_step=max((d for dt,d in moving),default=0))
        raw = [(s[0],s[3]) for s in self.samples]
        times = [s[1] for s in self.samples]
        self.result = dict(seconds=duration, capture=self.capture, bridge_hz=len(self.samples)/duration,
                           dynamic_updates_hz=len(self.dynamic)/duration,
                           dynamic_mean_ms=sum(x[2] for x in self.dynamic)/max(1,len(self.dynamic)),
                           bridge_mean_ms=sum(times)/max(1,len(times)),
                           raw_camera=cadence(raw), displayed_camera=cadence(self.camera),
                           errors=p.error_count,
                           mesh_vertices={k:v[1] for k,v in p.scene.raw_meshes.items()},
                           samples=self.samples, camera_samples=self.camera, dynamic_samples=self.dynamic,
                           viewport_samples=self.viewport,
                           viewport_repeated_moving=sum(a[1]==b[1] for a,b in zip(self.viewport,self.viewport[1:])
                                                        if .65 < b[0]%2 < .95 or 1.65 < b[0]%2 < 1.95) if self.capture else None)
        root = Path(__file__).resolve().parents[1]/'logs/motion'
        root.mkdir(parents=True,exist_ok=True)
        (root/f'{self.label}.json').write_text(json.dumps(self.result,indent=2),encoding='utf-8')
        p.spawn, default_spawn, p.yaw, p.pitch = self.saved
        p.teleport += 1
        QtCore.QTimer.singleShot(1500, lambda: setattr(p,'spawn',default_spawn))


ui._motion_profile = MotionProfile(ui._panel, globals().get('LABEL','motion'),
                                   capture=globals().get('CAPTURE',False))
