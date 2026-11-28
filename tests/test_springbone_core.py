"""The Python spring-bone solver against the JavaScript one (x3d.loom x3d.springbone, golden trace) and against the
closed-form answers the JavaScript witnesses use. No bpy needed."""

import json
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))
import springbone_core as S  # noqa: E402

HERE = os.path.dirname(__file__)


def _golden():
    with open(os.path.join(HERE, "springbone", "golden.json")) as fh:
        return json.load(fh)


def _affine(pw):
    return (pw["L"], pw["t"])


class GoldenTrace(unittest.TestCase):
    """400 jittered frames, two trees, every feature on; JS positions and hashes at 16 checkpoints."""

    def test_matches_javascript(self):
        g = _golden()
        ch = S.SpringChain(g["trees"], g["params"])
        checks = {c["frame"]: c for c in g["check"]}
        worst, hashes = 0.0, 0
        for f, fr in enumerate(g["frames"]):
            pw = _affine(fr["parentWorld"])
            pose = [[dict(p) for p in tree] for tree in g["pose0"]]
            pose[0][1]["rotation"] = fr["rot1"]
            cap_world = (pw[0], S.apply_point(pw, g["capsuleFrameOffset"]))
            cs = [dict(c, world=cap_world) if c.get("frame") else c for c in g["colliders"]]
            out = ch.frame({"dt": fr["dt"], "time": fr["time"], "reference": pw,
                            "trees": [{"parentWorld": pw, "pose": pose[0]}, {"parentWorld": pw, "pose": pose[1]}],
                            "colliders": cs})
            if f in checks:
                c = checks[f]
                for ti, tree in enumerate(out["trees"]):
                    for a, b in zip(tree["positions"], c["positions"][ti]):
                        worst = max(worst, max(abs(a[i] - b[i]) for i in range(3)))
                self.assertEqual(ch.state_hash(), c["hash"], f"hash at frame {f}")
                hashes += 1
        self.assertLessEqual(worst, 1e-12, f"worst position difference {worst:.3e} m")
        self.assertEqual(hashes, len(g["check"]))
        self.assertEqual(ch.steps, g["steps"])


class ClosedForm(unittest.TestCase):
    def _two(self):
        I = [0, 0, 0, 1]
        return [{"joints": [{"parent": -1}, {"parent": 0}]}], [{"translation": [0, 0, 0], "rotation": I}, {"translation": [0, -0.5, 0], "rotation": I}]

    def test_linear_recurrence(self):
        for model in ("POSITION", "FORCE"):
            d, e, y0 = 0.1, 0.1, 0.1
            trees, pose = self._two()
            ch = S.SpringChain(trees, {"damping": d, "elasticity": e, "stiffness": 0, "stretch": 1, "springModel": model})
            ch.frame({"dt": 0, "trees": [{"pose": pose}]})
            p = ch.trees[0]["parts"][1]
            p.pos[0] += y0
            p.prev[0] += y0
            Ssum = 2 - d - e if model == "FORCE" else (1 - e) * (2 - d)
            P = 1 - d if model == "FORCE" else (1 - e) * (1 - d)
            r, th = math.sqrt(P), math.acos(Ssum / (2 * math.sqrt(P)))
            D = (y0 * math.cos(th) - r * y0) / math.sin(th)
            worst = 0.0
            for n in range(1, 601):
                out = ch.frame({"dt": 1 / 60, "trees": [{"pose": pose}]})
                want = r ** n * (y0 * math.cos(n * th) + D * math.sin(n * th))
                worst = max(worst, abs(out["trees"][0]["positions"][1][0] - want))
            self.assertLessEqual(worst, 1e-12, model)

    def test_physical_tuning_round_trip(self):
        t = S.tuning_from_physical(2.0, 0.1, 60, "FORCE")
        back = S.physical_from_tuning(t["damping"], t["elasticity"], 60, "FORCE")
        self.assertAlmostEqual(back["frequency"], 2.0, places=12)
        self.assertAlmostEqual(back["dampingRatio"], 0.1, places=12)
        self.assertFalse(S.tuning_from_physical(2.0, 0.1, 60, "POSITION")["feasible"])


if __name__ == "__main__":
    unittest.main()
