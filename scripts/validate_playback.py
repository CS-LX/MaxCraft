"""Max-only regression of live playback, menus and return to native navigation.

Run with a connected, playing singleplayer world and closed Minecraft menus.
No blocks/entities are created or removed. Samples the existing viewport surface
without capture_viewport/forceCompleteRedraw, so screenshots cannot mask a stall.
"""
import json
from pathlib import Path
import time
import zlib
from PySide6 import QtCore, QtGui, QtWidgets
from pymxs import runtime as rt
import maxcraft.ui as ui


class PlaybackValidation(QtCore.QObject):
    def __init__(self, panel):
        super().__init__(panel)
        if not panel.playing or panel.player['flags'] & 2 or panel.player['camera_mode']:
            raise RuntimeError('Start in first person and close Minecraft menus')
        self.p = panel
        self.result = {}
        self.frames = []
        self.steps = iter([self.inventory_open, self.inventory_close,
                           self.menu_open, self.menu_close,
                           self.third_back, self.third_front, self.first_person,
                           self.native_preview, self.resume, self.finish])
        self.next_step()

    def key(self, key):
        for kind in (QtCore.QEvent.KeyPress, QtCore.QEvent.KeyRelease):
            QtWidgets.QApplication.sendEvent(self.p.overlay,
                QtGui.QKeyEvent(kind, key, QtCore.Qt.NoModifier))

    def next_step(self):
        try:
            delay = next(self.steps)()
            if delay:
                QtCore.QTimer.singleShot(delay, self.next_step)
        except Exception as error:
            self.result['error'] = repr(error)
            self.finish()

    def inventory_open(self):
        self.key(QtCore.Qt.Key_E)
        return 600

    def inventory_close(self):
        assert self.p.player['flags'] & 2, 'E did not open inventory'
        self.result['inventory_open'] = True
        self.key(QtCore.Qt.Key_E)
        return 600

    def menu_open(self):
        assert not self.p.player['flags'] & 2, 'E did not close inventory'
        self.key(QtCore.Qt.Key_Escape)
        return 600

    def menu_close(self):
        assert self.p.player['flags'] & 2, 'Esc did not open menu'
        self.result['escape_menu'] = True
        self.key(QtCore.Qt.Key_Escape)
        return 600

    def third_back(self):
        assert not self.p.player['flags'] & 2
        self.key(QtCore.Qt.Key_F5)
        return 600

    def third_front(self):
        assert self.p.player['camera_mode'] == 1
        self.key(QtCore.Qt.Key_F5)
        return 600

    def first_person(self):
        assert self.p.player['camera_mode'] == 2
        self.key(QtCore.Qt.Key_F5)
        return 600

    def native_preview(self):
        p = self.p
        assert p.player['camera_mode'] == 0
        self.result['f5_camera_cycle'] = True
        assert rt.viewport.getCamera() == p.scene.game_camera
        self.key(QtCore.Qt.Key_F8)
        assert not p.playing and not p.overlay.isVisible()
        assert str(rt.viewport.getType()) == 'view_persp_user'
        assert rt.viewport.getCamera() != p.scene.game_camera
        self.result['f8_releases_native_perspective'] = True
        matrix = rt.viewport.getTM()
        matrix.row4 = matrix.row4 + rt.point3(10, 0, 0)
        rt.viewport.setTM(matrix)
        self.preview_tm = str(rt.viewport.getTM())
        self.preview_start = time.perf_counter()
        self.reused = p.scene.reused_meshes
        self.sampler = QtCore.QTimer(self)
        self.sampler.timeout.connect(self.sample)
        self.sampler.start(50)
        return 4000

    def sample(self):
        image = self.p.overlay.screen().grabWindow(int(rt.viewport.getHWnd())).toImage().scaled(160,100)
        self.frames.append(zlib.crc32(image.constBits()))

    def resume(self):
        self.sampler.stop()
        assert self.preview_tm == str(rt.viewport.getTM()), 'MC overwrote the modelling camera'
        self.result['native_camera_not_overwritten'] = True
        self.result['preview_seconds'] = time.perf_counter()-self.preview_start
        self.result['preview_mesh_updates'] = self.p.scene.reused_meshes-self.reused
        self.result['preview_surface_samples'] = len(self.frames)
        self.result['preview_surface_changes'] = sum(a != b for a,b in zip(self.frames,self.frames[1:]))
        self.p.play_button.click()
        return 600

    def finish(self):
        if hasattr(self, 'sampler'):
            self.sampler.stop()
        p = self.p
        if p.link:
            p.link.input(6)
        self.result['playing'] = p.playing
        self.result['native_camera_attached'] = rt.viewport.getCamera() == p.scene.game_camera
        self.result['errors'] = p.error_count
        self.result['passed'] = (not self.result.get('error') and p.playing
                                 and self.result['native_camera_attached'] and not p.error_count)
        output = Path(__file__).resolve().parents[1]/'logs/playback-validation.json'
        output.write_text(json.dumps(self.result,indent=2),encoding='utf-8')


ui._playback_validation = PlaybackValidation(ui._panel)
