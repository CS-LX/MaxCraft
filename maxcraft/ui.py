"""Modeless control panel and transparent game input/HUD over a native Max viewport."""
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
from ctypes import wintypes
import math
from pathlib import Path
import time
import traceback
from PySide6 import QtCore, QtGui, QtWidgets
import qtmax
from pymxs import runtime as rt
from .protocol import Link, ProtocolError
from .geometry import collision_packets
from .scene import Scene, create_demo
from . import backend

K = QtCore.Qt.Key
SCANCODES = {int(getattr(K, 'Key_' + chr(65+i))): 4+i for i in range(26)}
SCANCODES.update({int(getattr(K, 'Key_' + str(i))): 29+i for i in range(1, 10)})
SCANCODES.update({int(K.Key_0):39, int(K.Key_Return):40, int(K.Key_Enter):40,
                 int(K.Key_Escape):41, int(K.Key_Backspace):42, int(K.Key_Tab):43,
                 int(K.Key_Space):44, int(K.Key_Minus):45, int(K.Key_Equal):46,
                 int(K.Key_BracketLeft):47, int(K.Key_BracketRight):48, int(K.Key_Backslash):49,
                 int(K.Key_Semicolon):51, int(K.Key_Apostrophe):52, int(K.Key_QuoteLeft):53,
                 int(K.Key_Comma):54, int(K.Key_Period):55, int(K.Key_Slash):56,
                 int(K.Key_Control):224, int(K.Key_Shift):225, int(K.Key_Alt):226,
                 int(K.Key_Right):79, int(K.Key_Left):80, int(K.Key_Down):81, int(K.Key_Up):82,
                 int(K.Key_Delete):76, int(K.Key_Home):74, int(K.Key_End):77,
                 int(K.Key_PageUp):75, int(K.Key_PageDown):78})
SCANCODES.update({int(getattr(K, f'Key_F{i}')):57+i for i in range(1, 13)})


class GameOverlay(QtWidgets.QWidget):
    def __init__(self, panel):
        super().__init__(qtmax.GetQMaxMainWindow(), QtCore.Qt.Tool | QtCore.Qt.FramelessWindowHint)
        self.panel = panel
        self.setObjectName('MaxCraftGameOverlay')
        self.setAttribute(QtCore.Qt.WA_TranslucentBackground)
        self.setFocusPolicy(QtCore.Qt.StrongFocus)
        self.setMouseTracking(True)
        self.image = QtGui.QImage()
        self.last_mouse = None
        self.screen_open = False
        qtmax.DisableMaxAcceleratorsOnFocus(self, True)

    def fit_viewport(self):
        hwnd = int(rt.viewport.getHWnd())
        rect, origin = wintypes.RECT(), wintypes.POINT()
        user32 = ctypes.windll.user32
        if not user32.GetClientRect(wintypes.HWND(hwnd), ctypes.byref(rect)):
            raise RuntimeError('Active Max viewport is unavailable')
        user32.ClientToScreen(wintypes.HWND(hwnd), ctypes.byref(origin))
        dpr = self.devicePixelRatioF()
        self.setGeometry(round(origin.x/dpr), round(origin.y/dpr), round(rect.right/dpr), round(rect.bottom/dpr))

    def paintEvent(self, event):
        painter = QtGui.QPainter(self)
        if not self.image.isNull():
            painter.drawImage(self.rect(), self.image)
        painter.setPen(QtGui.QColor('#e8f4df'))
        painter.setFont(QtGui.QFont('Segoe UI', 10))
        painter.drawText(14, 22, 'MAXCRAFT  /  F8 暂停并返回 3ds Max')

    def keyPressEvent(self, event):
        if event.key() == K.Key_F8:
            self.panel.pause()
            return
        if not self.panel.link:
            return
        code = SCANCODES.get(event.key())
        if code:
            self.panel.send_input(1, code, 1)
        if self.screen_open and event.text() and not (event.modifiers() & (QtCore.Qt.ControlModifier | QtCore.Qt.AltModifier)):
            for char in event.text():
                if ord(char) >= 32:
                    self.panel.send_input(5, a=ord(char))
        event.accept()

    def keyReleaseEvent(self, event):
        if not event.isAutoRepeat():
            code = SCANCODES.get(event.key())
            if code:
                self.panel.send_input(1, code, 0)
        event.accept()

    def mousePressEvent(self, event):
        self.setFocus()
        buttons = {QtCore.Qt.LeftButton:1, QtCore.Qt.MiddleButton:2, QtCore.Qt.RightButton:3}
        code = buttons.get(event.button())
        if code:
            self.panel.send_input(2, code, 1)

    def mouseReleaseEvent(self, event):
        buttons = {QtCore.Qt.LeftButton:1, QtCore.Qt.MiddleButton:2, QtCore.Qt.RightButton:3}
        code = buttons.get(event.button())
        if code:
            self.panel.send_input(2, code, 0)

    def mouseMoveEvent(self, event):
        if self.screen_open:
            self.panel.send_input(4, a=round(event.position().x()*self.panel.render_width/self.width()),
                                  b=round(event.position().y()*self.panel.render_height/self.height()))
            return
        center = self.rect().center()
        delta = event.position() - QtCore.QPointF(center)
        if abs(delta.x()) + abs(delta.y()) < 0.5:
            return
        self.panel.yaw = (self.panel.yaw + delta.x() * 0.15) % 360
        self.panel.pitch = max(-89.9, min(89.9, self.panel.pitch + delta.y()*0.15))
        QtGui.QCursor.setPos(self.mapToGlobal(center))

    def wheelEvent(self, event):
        self.panel.send_input(3, a=event.angleDelta().y())
        event.accept()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        if self.panel.playing:
            self.panel.pause()

    def closeEvent(self, event):
        self.panel.pause()
        event.ignore()


class Panel(QtWidgets.QDialog):
    def __init__(self):
        super().__init__(qtmax.GetQMaxMainWindow())
        self.setObjectName('MaxCraftPanel')
        self.setFont(QtGui.QFont('Microsoft YaHei UI', 10))
        self.setWindowTitle('MaxCraft · Minecraft × 3ds Max')
        self.resize(420, 500)
        self.link = None
        self.scene = Scene()
        self.overlay = GameOverlay(self)
        self.playing = False
        self.yaw, self.pitch = 0.0, 10.0
        self.spawn = (0.5, 100.5, -5.5)
        self.teleport = int(time.time()) & 0x7fffffff
        self.epoch = 1
        self.player = None
        self.collision = deque()
        self.pending_meshes = {}
        self.future = None
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix='MaxCraft-collision')
        self.render_width, self.render_height = 1280, 720
        self.last_status = 0.0
        self.last_dynamic = 0.0
        self.ticks = 0
        self.mesh_updates = 0
        self.error_count = 0
        self.backend_process = None
        layout = QtWidgets.QVBoxLayout(self)
        title = QtWidgets.QLabel('MAXCRAFT')
        title.setStyleSheet('font-size:26px;font-weight:700;color:#b7e479;padding:8px 0;')
        layout.addWidget(title)
        layout.addWidget(QtWidgets.QLabel('真实 Minecraft 逻辑 · 原生 Max 场景'))
        self.status = QtWidgets.QLabel('准备就绪。先创建演示场景，再连接 Minecraft。')
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.demo_button = self.button(layout, '① 创建 Max 演示场景', self.demo)
        form = QtWidgets.QFormLayout()
        self.units = QtWidgets.QDoubleSpinBox()
        self.units.setRange(0.01, 100000)
        self.units.setValue(70)
        form.addRow('Max 单位 / 方块', self.units)
        self.selection_only = QtWidgets.QCheckBox('仅导出选中模型')
        form.addRow(self.selection_only)
        layout.addLayout(form)
        self.connect_button = self.button(layout, '② 建立连接并导出碰撞', self.connect)
        self.launch_button = self.button(layout, '启动 Minecraft 开发端', self.launch_backend)
        self.play_button = self.button(layout, '③ 开始 / 继续游戏', self.play)
        self.play_button.setEnabled(False)
        self.button(layout, '刷新场景碰撞', self.export_collision)
        self.button(layout, '返回出生点', self.respawn)
        self.button(layout, '停止连接 / 恢复 Max 视图', self.disconnect)
        help_text = QtWidgets.QLabel('WASD 移动 · 鼠标转向 · 空格跳跃\n左键挖掘 · 右键使用/放置 · E 背包\n滚轮/1–9 选物品 · T 聊天 · F8 返回 Max\n首次启动需要下载开发依赖，请等待。\n存档：独立 MaxCraft 实例中的 SkyCraft 世界')
        help_text.setWordWrap(True)
        help_text.setStyleSheet('color:#bec4c9;padding:12px 0;')
        layout.addWidget(help_text)
        self.timer = QtCore.QTimer(self)
        self.timer.setTimerType(QtCore.Qt.PreciseTimer)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.timer.start()

    def button(self, layout, text, callback):
        button = QtWidgets.QPushButton(text)
        button.setMinimumHeight(32)
        button.clicked.connect(lambda: self.guarded(callback))
        layout.addWidget(button)
        return button

    def guarded(self, fn):
        try:
            fn()
        except Exception as error:
            self.fail(error)

    def fail(self, error):
        self.error_count += 1
        self.pause()
        self.status.setText(f'错误：{error}')
        log = Path.home() / 'AppData' / 'Local' / 'MaxCraft' / 'maxcraft.log'
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open('a', encoding='utf-8') as output:
            output.write(f'\n{time.ctime()}\n{traceback.format_exc()}\n')

    def demo(self):
        create_demo()
        self.status.setText('已创建地面、台阶、墙与 Max 茶壶。连接后即可进入。')

    def connect(self):
        if self.link:
            return
        self.scene.units = self.units.value()
        self.link = Link()
        self.units.setEnabled(False)
        self.connect_button.setEnabled(False)
        try:
            self.scene.capture_view()
            self.export_collision()
        except Exception:
            self.disconnect(keep_status=True)
            raise

    def export_collision(self):
        if not self.link:
            raise RuntimeError('请先建立连接。')
        if self.future and not self.future.done():
            return
        self.pause()
        triangles, nodes = self.scene.snapshot(self.selection_only.isChecked())
        self.epoch += 1
        self.future = self.pool.submit(collision_packets, triangles, self.epoch)
        self.status.setText(f'正在处理 {nodes} 个模型、{len(triangles)} 个三角面…')

    def play(self):
        if not self.link or not self.link.alive() or not self.player or not self.player['flags'] & 1:
            raise RuntimeError('Minecraft 尚未进入世界；请先运行启动脚本并等待连接。')
        if self.future or self.collision:
            raise RuntimeError('场景碰撞尚未完成，请稍候。')
        self.overlay.fit_viewport()
        ratio = min(1.0, 1920/self.overlay.width(), 1080/self.overlay.height())
        self.render_width = round(self.overlay.width()*ratio)
        self.render_height = round(self.overlay.height()*ratio)
        self.playing = True
        self.hide()
        self.overlay.show()
        self.overlay.activateWindow()
        self.overlay.setFocus()
        self.overlay.setCursor(QtCore.Qt.BlankCursor)
        QtGui.QCursor.setPos(self.overlay.mapToGlobal(self.overlay.rect().center()))

    def launch_backend(self):
        if not self.link:
            self.connect()
        if self.link.alive() or (self.backend_process and self.backend_process.poll() is None):
            self.status.setText('Minecraft 已启动，正在等待就绪。')
            return
        self.backend_process = backend.launch()
        self.status.setText('Minecraft 正在后台启动；首次启动需准备依赖。')

    def pause(self):
        was_playing = self.playing
        self.playing = False
        if self.link:
            try:
                self.link.input(6)
            except ProtocolError:
                pass
        self.overlay.hide()
        self.overlay.unsetCursor()
        if was_playing:
            self.show()
            self.raise_()

    def respawn(self):
        self.teleport = (self.teleport + 1) & 0x7fffffff

    def send_input(self, kind, code=0, a=0, b=0, c=0):
        if self.link and self.playing:
            try:
                self.link.input(kind, code, a, b, c)
            except Exception as error:
                self.fail(error)

    def tick(self):
        try:
            self.update_bridge()
        except Exception as error:
            self.fail(error)
            self.disconnect(keep_status=True)

    def update_bridge(self):
        if not self.link:
            return
        self.ticks += 1
        self.link.heartbeat()
        if self.future and self.future.done():
            future, self.future = self.future, None
            self.collision = deque(future.result())
        for _ in range(min(8, len(self.collision))):
            kind, data = self.collision[0]
            if not self.link.col.write(kind, data):
                break
            self.collision.popleft()
        self.link.write_state(self.spawn, self.yaw, self.pitch, self.teleport, self.epoch,
                              self.render_width, self.render_height, paused=not self.playing)
        self.player = self.link.read_player() or self.player
        alive = self.link.alive()
        if not alive and self.playing:
            self.pause()
        self.link.drain_events()
        for kind, data in self.link.render.read(max_messages=48):
            if kind in (2, 5, 6):
                key = (kind, data[:12]) if kind == 2 else (kind,)
                self.pending_meshes[key] = (kind, data)
            elif kind == 3:
                self.pending_meshes.clear()
                self.scene.consume(kind, data, self.player)
            elif kind in (1, 4):
                self.scene.consume(kind, data, self.player)
        # One latest geometry update per UI tick; stale dynamic frames are replaced.
        if self.pending_meshes:
            key = next(iter(self.pending_meshes))
            kind, data = self.pending_meshes.pop(key)
            if kind == 2 or time.monotonic() - self.last_dynamic > .15:
                self.scene.consume(kind, data, self.player)
                self.mesh_updates += 1
                if kind != 2:
                    self.last_dynamic = time.monotonic()
        frame = self.link.overlay()
        if frame:
            w, h, flags, _, pixels = frame
            image = QtGui.QImage(pixels, w, h, w*4, QtGui.QImage.Format_RGBA8888).copy()
            self.overlay.image = image.mirrored(False, True) if flags & 1 else image
            self.overlay.update()
        if self.playing and self.player:
            menu = bool(self.player['flags'] & 2)
            if menu != self.overlay.screen_open:
                self.overlay.screen_open = menu
                self.overlay.setCursor(QtCore.Qt.ArrowCursor if menu else QtCore.Qt.BlankCursor)
                if self.overlay.isVisible():
                    QtGui.QCursor.setPos(self.overlay.mapToGlobal(self.overlay.rect().center()))
            self.scene.camera(self.player, self.yaw, self.pitch, self.render_width/self.render_height)
        now = time.monotonic()
        if now - self.last_status > 1:
            self.last_status = now
            ready = alive and self.player and self.player['flags'] & 1 and not self.future and not self.collision
            self.play_button.setEnabled(bool(ready))
            if not alive:
                if self.backend_process and self.backend_process.poll() is not None:
                    self.status.setText(f'Minecraft 启动已退出（{self.backend_process.returncode}）。查看项目 logs/minecraft-dev.log 后重新启动。')
                else:
                    self.status.setText('桥接已建立。等待 Minecraft / SkyCraft v11…')
            elif self.future:
                self.status.setText('Minecraft 已连接，正在计算场景碰撞…')
            else:
                pos = self.player['pos'] if self.player else (0, 0, 0)
                self.status.setText(f'Minecraft 已连接 · {len(self.scene.nodes)} 个网格\n位置 {pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f} · 待发送 {len(self.collision)}')

    def disconnect(self, keep_status=False):
        self.pause()
        if self.future:
            self.future.cancel()
            self.future = None
        if self.link:
            self.link.close()
            self.link = None
        self.scene.restore_view()
        self.scene.clear()
        self.pending_meshes.clear()
        self.collision.clear()
        self.player = None
        self.units.setEnabled(True)
        self.connect_button.setEnabled(True)
        self.play_button.setEnabled(False)
        if not keep_status:
            self.status.setText('连接已停止，Max 视图已恢复。重新连接前请退出 Minecraft。')

    def closeEvent(self, event):
        self.disconnect()
        self.timer.stop()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.overlay.deleteLater()
        event.accept()


_panel = None


def show():
    global _panel
    if _panel is not None:
        try:
            if _panel.timer.isActive():
                _panel.show()
                _panel.raise_()
                return _panel
        except RuntimeError:
            pass
    _panel = Panel()
    _panel.show()
    return _panel

