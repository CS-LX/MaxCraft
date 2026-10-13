"""Developer-only: place real MC blocks via its own chat for visual/depth QA.

Run inside Max with the demo connected. Never steals desktop keyboard/mouse focus.
"""
from PySide6 import QtCore
import maxcraft.ui


class Commands(QtCore.QObject):
    def __init__(self, commands):
        super().__init__(maxcraft.ui._panel)
        self.p = maxcraft.ui._panel
        self.commands = list(commands)
        self.entering = False
        self.p.playing = True
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.step)
        self.timer.start(600)

    def step(self):
        if not self.commands:
            self.p.playing = False
            self.p.link.input(6)
            self.timer.stop()
            return
        if not self.entering:
            self.p.link.input(1, 23, 1)  # T opens vanilla chat.
            self.p.link.input(1, 23, 0)
        else:
            for char in self.commands.pop(0):
                self.p.link.input(5, a=ord(char))
            self.p.link.input(1, 40, 1)
            self.p.link.input(1, 40, 0)
        self.entering = not self.entering


maxcraft.ui._commands = Commands([
    '/setblock -9 101 8 minecraft:diamond_block',
    '/setblock -3 100 0 minecraft:gold_block',
    '/setblock 2 100 -1 minecraft:grass_block',
    '/setblock 2 101 -1 minecraft:oak_leaves[persistent=true]',
])
