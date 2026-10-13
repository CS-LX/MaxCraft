"""Run inside 3ds Max after a real backend connects. Timed input, never mocked physics.

Results are written to logs/integration.json. Does not run automatically on install.
"""
import json
from pathlib import Path
import time
from PySide6 import QtCore, QtGui, QtWidgets, QtTest
import maxcraft.ui

ROOT = Path(__file__).resolve().parents[1]


class Probe(QtCore.QObject):
    def __init__(self):
        super().__init__(maxcraft.ui._panel)
        self.p = maxcraft.ui._panel
        self.stage = 0
        self.started = time.monotonic()
        self.deadline = self.started
        self.results = {}
        self.timer = QtCore.QTimer(self)
        # Exercise the real protocol while the user keeps working in other apps.
        self.p.playing = True
        self.timer.timeout.connect(self.step)
        self.timer.start(100)

    def write(self):
        (ROOT / 'logs').mkdir(exist_ok=True)
        (ROOT / 'logs/integration.json').write_text(json.dumps(self.results, indent=2), encoding='utf-8')

    def key(self, code, down):
        self.p.link.input(1, code, int(down))

    def command(self, text):
        for char in text:
            self.p.link.input(5, a=ord(char))
        self.key(40, True)
        self.key(40, False)

    def next(self, delay):
        self.stage += 1
        self.deadline = time.monotonic() + delay
        self.write()

    def step(self):
        try:
            self.run_step()
        except Exception as error:
            self.results['error'] = str(error)
            self.results['stage'] = self.stage
            self.write()
            self.p.pause()
            self.timer.stop()

    def run_step(self):
        p = self.p
        if time.monotonic() - self.started > 180:
            raise RuntimeError('Real backend probe timed out')
        if time.monotonic() < self.deadline:
            return
        state = p.player
        if self.stage == 0:
            if not p.link or not p.link.alive() or not state or not state['flags'] & 1:
                return
            if state['ack'] != p.teleport or abs(state['pos'][1]-100) > .1:
                return
            self.results['handshake'] = True
            self.results['standing_on_max_geometry'] = state['pos']
            self.results['overlay_pixels'] = [p.overlay.image.width(), p.overlay.image.height()]
            self.results['start'] = list(state['pos'])
            self.next(.5)
        elif self.stage == 1:
            self.key(26, True)
            self.next(.7)
        elif self.stage == 2:
            self.key(26, False)
            self.results['after_w'] = list(state['pos'])
            self.results['movement_distance'] = sum((a-b)**2 for a,b in zip(state['pos'], self.results['start']))**.5
            self.key(44, True)
            self.next(.3)
        elif self.stage == 3:
            self.key(44, False)
            self.results['jump_y'] = state['pos'][1]
            self.next(1)
        elif self.stage == 4:
            QtTest.QTest.keyClick(p.overlay, QtCore.Qt.Key_E)
            self.next(1)
        elif self.stage == 5:
            self.results['inventory_from_qt_key'] = bool(state['flags'] & 2)
            p.overlay.image.save(str(ROOT / 'logs/inventory.png'))
            QtTest.QTest.keyClick(p.overlay, QtCore.Qt.Key_Escape)
            self.next(.5)
        elif self.stage == 6:
            self.key(23, True)
            self.key(23, False)
            self.next(.5)
        elif self.stage == 7:
            self.command('/give @s minecraft:stone 64')
            self.next(1)
        elif self.stage == 8:
            self.results['baseline_faces'] = sum(n.mesh.numfaces for k,n in p.scene.nodes.items() if k.startswith('section'))
            # SkyCraft's original starter kit puts oak planks in hotbar slot 5.
            self.key(34, True)
            self.key(34, False)
            # Aim ahead of the player's collision capsule; too steep hits our own cell.
            p.pitch = 45
            self.next(.8)
        elif self.stage == 9:
            p.link.input(2, 3, 1)
            self.next(.15)
        elif self.stage == 10:
            p.link.input(2, 3, 0)
            self.next(2)
        elif self.stage == 11:
            self.results['placed_sections'] = [k for k in p.scene.nodes if k.startswith('section')]
            self.results['placed_faces'] = sum(n.mesh.numfaces for k,n in p.scene.nodes.items() if k.startswith('section'))
            p.overlay.image.save(str(ROOT / 'logs/hud.png'))
            p.link.input(2, 1, 1)
            self.next(.5)
        elif self.stage == 12:
            p.link.input(2, 1, 0)
            self.next(2)
        elif self.stage == 13:
            self.results['after_break_faces'] = sum(n.mesh.numfaces for k,n in p.scene.nodes.items() if k.startswith('section'))
            self.results['mesh_updates'] = p.mesh_updates
            self.results['host_errors'] = p.error_count
            QtTest.QTest.keyClick(p.overlay, QtCore.Qt.Key_F8)
            self.results['f8_released_input'] = not p.playing and not p.overlay.isVisible()
            self.results['completed'] = True
            self.results['passed'] = (self.results['movement_distance'] > 1
                                      and self.results['jump_y'] > 100.5
                                      and self.results['inventory_from_qt_key']
                                      and self.results['placed_faces'] > self.results['baseline_faces']
                                      and self.results['after_break_faces'] < self.results['placed_faces']
                                      and self.results['host_errors'] == 0
                                      and self.results['f8_released_input'])
            self.write()
            self.timer.stop()
        else:
            self.timer.stop()


probe = Probe()
maxcraft.ui._probe = probe
