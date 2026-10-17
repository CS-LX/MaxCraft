import math
import unittest
from maxcraft.motion import MotionClock


def tick(at, prev, cur, ack=1, flags=1, period=50):
    return dict(tick_qpc=round(at*1_000_000), tick_prev=(prev,100,0),
                tick_cur=(cur,100,0), tick_eye=(1.6,1.62), tick_ms=period,
                ack=ack, flags=flags, pos=(cur,100,0), eye=(cur,101.62,0))


class MotionTests(unittest.TestCase):
    def test_same_backend_snapshot_moves_on_host_clock(self):
        motion = MotionClock(1_000_000)
        state = tick(1,0,1)
        a = motion.sample(state,1.03)
        b = motion.sample(state,1.04)
        self.assertAlmostEqual(a['pos'][0],.2)
        self.assertAlmostEqual(b['pos'][0],.4)
        self.assertGreater(b['eye'][1],a['eye'][1])

    def test_late_tick_never_extrapolates_through_wall(self):
        motion = MotionClock(1_000_000)
        state = tick(1,0,1)
        motion.sample(state,1.03)
        self.assertEqual(motion.sample(state,1.2)['pos'],(1,100,0))

    def test_ack_and_large_teleport_do_not_blend_old_location(self):
        motion = MotionClock(1_000_000)
        motion.sample(tick(1,0,1),1.04)
        self.assertEqual(motion.sample(tick(1.05,100,100,ack=2),1.08)['pos'],(100,100,0))
        self.assertEqual(motion.sample(tick(1.1,-50,-50,ack=2),1.13)['pos'],(-50,100,0))

    def test_menu_resets_history_and_missing_timestamp_uses_raw(self):
        motion = MotionClock(1_000_000)
        motion.sample(tick(1,0,1),1.04)
        state = tick(1,0,1,flags=3)
        self.assertIs(motion.sample(state,1.06),state)
        self.assertFalse(motion.history)
        state['tick_qpc'] = 0
        self.assertIs(motion.sample(state,1.08),state)

    def test_jittered_tick_arrival_has_no_backward_or_repeated_steps(self):
        motion = MotionClock(1_000_000)
        previous = None
        held = None
        seen = -1
        steps = []
        # 20 Hz simulation arrives asynchronously at a 60 Hz presenter.
        for frame in range(1,121):
            now = 10+frame/60
            index = math.floor((now-10-.009)/.05)
            if index != seen:
                jitter = (.002,-.001,.001,-.002)[index%4]
                held = tick(10+index*.05+jitter,index*.2,(index+1)*.2)
                seen = index
            sample = motion.sample(held,now)['pos'][0]
            if previous is not None and frame > 10:
                steps.append(sample-previous)
            previous = sample
        self.assertTrue(all(.01 < delta < .12 for delta in steps),steps)

    def test_tick_rate_change_resets_timeline(self):
        motion = MotionClock(1_000_000)
        motion.sample(tick(1,0,1),1.04)
        result = motion.sample(tick(1.1,2,3,period=100),1.14)
        self.assertEqual(len(motion.history),1)
        self.assertAlmostEqual(result['pos'][0],2.2)


if __name__ == '__main__':
    unittest.main()
