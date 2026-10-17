"""Present physics ticks on Max's clock, without predicting through collisions.

Adapted from SkyCraft's MIT-licensed skse/src/Game.cpp: retain tick history,
filter noisy timestamps, and interpolate slightly behind the newest tick.
"""
from collections import deque
import math


def lerp(a, b, t):
    return tuple(x+(y-x)*t for x,y in zip(a,b))


class MotionClock:
    def __init__(self, frequency):
        self.frequency = frequency
        self.reset()

    def reset(self):
        self.history = deque(maxlen=8)
        self.lateness = deque(maxlen=40)
        self.delay = .020
        self.last_now = None
        self.ack = None
        self.period = None
        self.outliers = 0
        self.late_frames = 0

    def sample(self, state, now):
        stamp = state.get('tick_qpc', 0)
        if not stamp or not state['flags'] & 1:
            self.reset()
            return state
        period = state['tick_ms']/1000
        at = stamp/self.frequency
        # Menus stop MC's tick clock. Do not wind the view backwards on resume.
        if state['flags'] & 2:
            self.reset()
            return state
        if (self.ack != state['ack'] or self.period != period or
                (self.last_now is not None and now-self.last_now > .5) or
                (self.history and stamp < self.history[-1]['stamp'])):
            self.reset()
        self.ack, self.period = state['ack'], period
        if not self.history or self.history[-1]['stamp'] != stamp:
            tick = dict(stamp=stamp, at=at, slots=1, prev=state['tick_prev'],
                        cur=state['tick_cur'], eye=state['tick_eye'])
            if self.history:
                last = self.history[-1]
                n = round((at-last['at'])/period)
                error = at-(last['at']+n*period)
                if math.dist(last['cur'], tick['prev']) > 2 or math.dist(tick['prev'],tick['cur']) > 8:
                    # Teleports may also originate in Minecraft commands.
                    self.history.clear()
                    self.lateness.clear()
                elif n == 0 and last['slots'] >= 2:
                    last['at'] -= period
                    last['slots'] -= 1
                    tick['at'] = last['at']+period
                elif 1 <= n <= 10 and abs(error) < period*.3:
                    tick['at'] = last['at']+n*period+error/16
                    tick['slots'] = n
                    self.outliers = 0
                elif 0 <= n <= 10 and self.outliers < 2:
                    self.outliers += 1
                    tick['slots'] = max(1,n)
                    tick['at'] = last['at']+tick['slots']*period
                else:
                    self.outliers = 0
            if self.last_now is not None:
                due = self.last_now-tick['at']
                if -.05 < due < .04:
                    self.lateness.append(due)
            self.history.append(tick)
        dt = min(.1,max(0,now-self.last_now)) if self.last_now is not None else 0
        self.last_now = now
        if self.lateness:
            target = min(.040,max(.004,max(self.lateness)+.001))
            self.delay = (min(target,self.delay+.020*dt) if target > self.delay
                          else max(target,self.delay-.002*dt))
        render_time = now-self.delay
        ticks = list(self.history)
        i = next((j for j in range(len(ticks)-1,-1,-1) if ticks[j]['at'] <= render_time),0)
        tick = ticks[i]
        phase = (render_time-tick['at'])/period
        t = min(1,max(0,phase))
        pos = lerp(tick['prev'],tick['cur'],t)
        eye_height = tick['eye'][0]+(tick['eye'][1]-tick['eye'][0])*t
        if phase > 1 and i+1 < len(ticks):
            following = ticks[i+1]
            gap = following['at']-(tick['at']+period)
            u = min(1,max(0,(render_time-tick['at']-period)/gap)) if gap > 0 else 1
            pos = lerp(tick['cur'],following['prev'],u)
            eye_height = tick['eye'][1]+(following['eye'][0]-tick['eye'][1])*u
        elif phase > 1:
            self.late_frames += 1
        return dict(state, pos=pos, eye=(pos[0],pos[1]+eye_height,pos[2]))
