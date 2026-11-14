"""Unit tests for the parts that do not need a camera or a screen.

    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import numpy as np
from PIL import Image

from privacyguard import config as cfgmod
from privacyguard import effects
from privacyguard.detector import Detection, FaceBox, IntruderLogic
from privacyguard.hotkeys import parse_combo
from privacyguard.overlay import premultiply_bgra
from privacyguard.sound import SOUNDS, wav_bytes


def det(boxes):
    d = Detection(boxes=boxes)
    d.owner = 0 if boxes else -1
    d.others = max(0, len(boxes) - 1)
    return d


class ConfigTest(unittest.TestCase):
    def test_clamp(self):
        cfg = cfgmod.deep_merge(cfgmod.DEFAULTS, {"effect": {"intensity": 3.0, "quality": 0.01},
                                                 "monitor": {"confirm_frames": 999}})
        out = cfgmod.clamp_values(cfg)
        self.assertLessEqual(out["effect"]["intensity"], cfgmod.CLAMP[("effect", "intensity")][1])
        self.assertGreaterEqual(out["effect"]["quality"], cfgmod.CLAMP[("effect", "quality")][0])
        self.assertLessEqual(out["monitor"]["confirm_frames"],
                             cfgmod.CLAMP[("monitor", "confirm_frames")][1])

    def test_presets_are_valid(self):
        for key in cfgmod.PRESETS:
            cfg = cfgmod.apply_preset(cfgmod.deep_merge(cfgmod.DEFAULTS, {}), key)
            self.assertTrue(set(cfg["effect"]["names"]) <= set(effects.ORDER), key)


class LogicTest(unittest.TestCase):
    def test_trigger_after_confirm_frames(self):
        logic = IntruderLogic()
        logic.configure(allowed_own_faces=1, confirm_frames=3, cooldown_s=1.0, release_s=1.0)
        one = det([FaceBox(10, 10, 50, 50)])
        two = det([FaceBox(10, 10, 50, 50), FaceBox(100, 20, 40, 40)])
        self.assertIsNone(logic.update(one, now=100.0))
        self.assertIsNone(logic.update(two, now=100.1))
        self.assertIsNone(logic.update(two, now=100.2))
        self.assertEqual(logic.update(two, now=100.3), "trigger")
        self.assertIsNone(logic.update(two, now=100.4))     # inside cooldown

    def test_allowed_zero_faces_triggers_on_first_person(self):
        logic = IntruderLogic()
        logic.configure(allowed_own_faces=0, confirm_frames=1, cooldown_s=1.0, release_s=1.0)
        self.assertEqual(logic.update(det([FaceBox(0, 0, 40, 40)]), now=50.0), "trigger")

    def test_release_after_quiet(self):
        logic = IntruderLogic()
        logic.configure(allowed_own_faces=1, confirm_frames=1, cooldown_s=0.2, release_s=1.0)
        logic.update(det([FaceBox(0, 0, 40, 40), FaceBox(60, 0, 40, 40)]), now=10.0)
        self.assertIsNone(logic.update(det([FaceBox(0, 0, 40, 40)]), now=10.3))
        self.assertEqual(logic.update(det([FaceBox(0, 0, 40, 40)]), now=12.0), "release")


class EffectTest(unittest.TestCase):
    def test_registry(self):
        self.assertEqual(len(effects.ORDER), 16)
        for d in effects.describe():
            self.assertIn(d["key"], effects.ORDER)
            self.assertTrue(d["zh"] and d["en"])

    def test_render_every_effect_small(self):
        cfg = cfgmod.deep_merge(cfgmod.DEFAULTS, {})
        for key in effects.ORDER:
            cfg["effect"]["names"] = [key]
            seq = effects.EffectSequencer(cfg, seed=1)
            rng = np.random.default_rng(1)
            for t in (0.0, 0.7, 2.5):
                img = effects.render_frame(cfg, (160, 100), seq, t, rng)
                self.assertEqual(img.size, (160, 100), key)
                self.assertEqual(img.mode, "RGBA", key)

    def test_sequencer_cycles(self):
        cfg = cfgmod.deep_merge(cfgmod.DEFAULTS, {"effect": {"names": ["pulse_frame", "radar"],
                                                            "cycle_s": 2.0}})
        seq = effects.EffectSequencer(cfg, seed=1)
        self.assertEqual(seq.current(0.5), "pulse_frame")
        self.assertEqual(seq.current(2.5), "radar")
        self.assertEqual(seq.current(4.5), "pulse_frame")


class OverlayTest(unittest.TestCase):
    def test_premultiply(self):
        img = Image.new("RGBA", (4, 3), (200, 100, 50, 128))
        bgra = premultiply_bgra(img)
        self.assertEqual(bgra.shape, (3, 4, 4))
        self.assertEqual(bgra.dtype, np.uint8)
        self.assertEqual(tuple(bgra[0, 0]), (25, 50, 100, 128))     # BGRA, premultiplied


class SoundTest(unittest.TestCase):
    def test_synth(self):
        for s in SOUNDS:
            data = wav_bytes(s["key"], volume=0.5)
            self.assertTrue(data.startswith(b"RIFF"), s["key"])
            self.assertGreater(len(data), 4410 * 2)


class HotkeyTest(unittest.TestCase):
    def test_parse(self):
        mods, vk = parse_combo("ctrl+alt+p")
        self.assertTrue(mods and vk == ord("P"))
        mods, vk = parse_combo("ctrl+shift+F5")
        self.assertEqual(vk, 0x74)
        self.assertIsNone(parse_combo("nonsense"))


if __name__ == "__main__":
    unittest.main()
