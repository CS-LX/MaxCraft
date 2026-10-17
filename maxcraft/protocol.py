"""SkyCraft v11 wire adapter. Layout matches the MIT upstream protocol.

No Minecraft mechanics live here. All coordinates on the wire are MC blocks.
Single producer / consumer per ring; real inter-process atomics, bounded reads.
"""
from __future__ import annotations
import ctypes
import math
import mmap
import os
from pathlib import Path
import struct
import time

MAGIC, VERSION = 0x43594B53, 11
DEFAULT_NAME = r"Local\MaxCraft_v11"
SKY, MC, OVERLAY, OVERLAY_HEADERS = 0x100, 0x200, 0x300, 0x340
INPUT, EVENTS, ENTITIES, COLLISION = 0x1000, 0x17000, 0x1C000, 0x20000
COLLISION_BYTES = 32 << 20
PIXELS = COLLISION + COLLISION_BYTES
SLOT_BYTES = 3840 * 2160 * 4
RENDER = PIXELS + SLOT_BYTES * 3
RENDER_BYTES = 64 << 20
MAPPING_BYTES = RENDER + RENDER_BYTES
VERTEX = struct.Struct('<5fIII')
MC_SNAPSHOT = struct.Struct('<IIdddffffIIQfffIddd')


class ProtocolError(RuntimeError):
    pass


class Atomics:
    def __init__(self, buffer):
        self.buffer = buffer
        self.address = ctypes.addressof(ctypes.c_char.from_buffer(buffer))
        self.dll = ctypes.CDLL(str(Path(__file__).parent / '_native' / 'atomics.dll'))
        for name, args, result in [
            ('mc_load32', [ctypes.c_void_p], ctypes.c_uint32),
            ('mc_load64', [ctypes.c_void_p], ctypes.c_uint64),
            ('mc_exchange32', [ctypes.c_void_p, ctypes.c_uint32], ctypes.c_uint32),
            ('mc_store64', [ctypes.c_void_p, ctypes.c_uint64], None),
        ]:
            fn = getattr(self.dll, name)
            fn.argtypes, fn.restype = args, result

    def load32(self, offset):
        return self.dll.mc_load32(self.address + offset)

    def load64(self, offset):
        return self.dll.mc_load64(self.address + offset)

    def exchange32(self, offset, value):
        return self.dll.mc_exchange32(self.address + offset, value)

    def store64(self, offset, value):
        self.dll.mc_store64(self.address + offset, value)


def tick_ms():
    fn = ctypes.windll.kernel32.GetTickCount64
    fn.restype = ctypes.c_uint64
    return fn()


def align8(n):
    return (n + 7) & ~7


class ByteRing:
    def __init__(self, buffer, atomics, offset, size):
        self.buffer, self.a, self.offset = buffer, atomics, offset
        self.capacity = size - 0x80

    def counters(self):
        head, tail = self.a.load64(self.offset), self.a.load64(self.offset + 0x40)
        if head < tail or head - tail > self.capacity:
            raise ProtocolError('Invalid ring counters; disconnect and restart both ends.')
        return head, tail

    def write(self, kind, payload):
        if not kind:
            raise ValueError('Message zero is reserved for wrap padding')
        size = align8(8 + len(payload))
        if size > self.capacity:
            raise ValueError('Packet exceeds ring capacity')
        head, tail = self.counters()
        pos = head % self.capacity
        padding = self.capacity - pos if pos + size > self.capacity else 0
        if size + padding > self.capacity - (head - tail):
            return False
        if padding:
            struct.pack_into('<II', self.buffer, self.offset + 0x80 + pos, 0, 0)
            head += padding
            pos = 0
        start = self.offset + 0x80 + pos
        struct.pack_into('<II', self.buffer, start, kind, len(payload))
        self.buffer[start + 8:start + 8 + len(payload)] = payload
        self.a.store64(self.offset, head + size)
        return True

    def read(self, max_messages=64, max_bytes=16 << 20):
        head, tail = self.counters()
        output, used = [], 0
        while tail < head and len(output) < max_messages:
            pos = tail % self.capacity
            start = self.offset + 0x80 + pos
            if head - tail < 8:
                raise ProtocolError('Truncated ring header')
            kind, length = struct.unpack_from('<II', self.buffer, start)
            if kind == 0:
                padding = self.capacity - pos
                if tail + padding > head:
                    raise ProtocolError('Invalid wrap marker')
                tail += padding
                continue
            size = align8(8 + length)
            if size > self.capacity - pos or size > head - tail:
                raise ProtocolError('Malformed ring packet length')
            if output and used + size > max_bytes:
                break
            output.append((kind, bytes(self.buffer[start + 8:start + 8 + length])))
            tail += size
            used += size
        self.a.store64(self.offset + 0x40, tail)
        return output


class Link:
    """Own one private mapping. Refuse live or stale mappings: never reset under MC."""
    def __init__(self, name=DEFAULT_NAME):
        self.name, self.closed = name, False
        self.m = mmap.mmap(-1, MAPPING_BYTES, tagname=name)
        self.a = Atomics(self.m)
        if self.a.load32(0) == MAGIC:
            self.m.close()
            raise ProtocolError('This bridge is already open. Stop the other MaxCraft/Minecraft session first.')
        self.front = 2
        self.seq = 0
        self.col = ByteRing(self.m, self.a, COLLISION, COLLISION_BYTES)
        self.render = ByteRing(self.m, self.a, RENDER, RENDER_BYTES)
        struct.pack_into('<III', self.m, 4, VERSION, os.getpid(), 0)
        self.heartbeat()
        self.a.exchange32(0, MAGIC)

    def heartbeat(self):
        self.a.store64(0x10, tick_ms())

    def alive(self):
        beat = self.a.load64(0x18)
        return bool(beat and 0 <= tick_ms() - beat < 5000)

    def write_state(self, pos, yaw, pitch, teleport, epoch, width, height, paused=False, world=0x4D4158):
        if not all(math.isfinite(v) for v in (*pos, yaw, pitch)):
            raise ValueError('Non-finite camera')
        self.seq += 2
        self.a.exchange32(SKY, self.seq - 1)
        struct.pack_into('<IIIdddffIIIf', self.m, SKY + 4,
                         3 if paused else 1, world, epoch, *pos, yaw, pitch, teleport,
                         max(320, min(1920, width)), max(240, min(1080, height)), 12.0)
        self.a.exchange32(SKY, self.seq)

    def read_player(self):
        for _ in range(4):
            seq = self.a.load32(MC)
            if not seq or seq & 1:
                continue
            raw = bytes(self.m[MC:MC + 0xC8])
            if seq != self.a.load32(MC):
                continue
            v = MC_SNAPSHOT.unpack_from(raw)
            if not all(math.isfinite(v[i]) for i in (2,3,4,5,6,7,8,12,13,14,16,17,18)):
                raise ProtocolError('Non-finite player state')
            return dict(flags=v[1], pos=v[2:5], yaw=v[5], pitch=v[6], eye_height=v[7],
                        sensitivity=v[8], ack=v[9], gui_scale=v[10], frame=v[11],
                        fov=v[12], eye=v[16:19], camera_mode=struct.unpack_from('<I', raw, 0xC0)[0],
                        camera_distance=struct.unpack_from('<f', raw, 0xC4)[0])
        return None

    def input(self, kind, code=0, a=0, b=0, c=0):
        head, tail = self.a.load64(INPUT), self.a.load64(INPUT + 0x40)
        if head < tail or head - tail > 4096:
            raise ProtocolError('Invalid input ring')
        if head - tail >= 4096:
            raise ProtocolError('Input queue full; paused to prevent stuck controls')
        struct.pack_into('<HHiii', self.m, INPUT + 0x80 + head % 4096 * 16, kind, code, a, b, c)
        self.a.store64(INPUT, head + 1)

    def overlay(self):
        if not self.a.load32(OVERLAY) & 4:
            return None
        self.front = self.a.exchange32(OVERLAY, self.front) & 3
        if self.front > 2:
            raise ProtocolError('Invalid overlay buffer')
        w, h, flags, _, frame = struct.unpack_from('<IIIIQ', self.m, OVERLAY_HEADERS + self.front * 0x40)
        if not (0 < w <= 3840 and 0 < h <= 2160):
            return None
        start = PIXELS + self.front * SLOT_BYTES
        # The consumer owns this slot until the next exchange. QImage copies it
        # before that exchange, so avoid an intermediate full-frame bytes copy.
        return w, h, flags, frame, memoryview(self.m)[start:start + w * h * 4]

    def drain_events(self):
        head, tail = self.a.load64(EVENTS), self.a.load64(EVENTS + 0x40)
        if head < tail or head - tail > 512:
            raise ProtocolError('Invalid event ring')
        result = [struct.unpack_from('<II4fII', self.m, EVENTS + 0x80 + i % 512 * 32) for i in range(tail, head)]
        self.a.store64(EVENTS + 0x40, head)
        return result

    def close(self):
        if self.closed:
            return
        try:
            self.input(6)
        except ProtocolError:
            # The zero heartbeat is authoritative even when the input ring is full.
            pass
        finally:
            self.a.store64(0x10, 0)
            self.m.close()
            self.closed = True

