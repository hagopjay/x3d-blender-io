# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Spring bones in Blender (x3d.loom x3d.springbone): add a chain, bake it, check the keys put every tip where the solver
said, export it as SpringBoneChain ProtoInstances (XSD-valid), import it back. Skipped without ``bpy``::

    cd tests && python -m unittest test_springbone_bpy
"""

from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover
    HAVE_BPY = False

if HAVE_BPY:
    from test_roundtrip_bpy import _register_extension

XSD = os.environ.get("X3D_XSD", "/home/user/x3d_mcp/src/validation/schemas/x3d-4.0.xsd")


def _tail_rig():
    """An armature: a base bone and a 4-bone tail hanging from it (own, CC0), the base swaying on X."""
    import bpy
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.frame_start, scene.frame_end = 1, 72
    data = bpy.data.armatures.new("TailRig")
    ob = bpy.data.objects.new("TailRig", data)
    scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.mode_set(mode='EDIT')
    base = data.edit_bones.new("base")
    base.head, base.tail = (0, 0, 1.0), (0, 0, 1.2)
    parent = base
    for i in range(4):
        b = data.edit_bones.new(f"tail_{i + 1}")
        b.head = (0, 0, 1.0 - 0.15 * i)
        b.tail = (0, 0, 1.0 - 0.15 * (i + 1))
        b.parent = parent
        b.use_connect = i > 0
        parent = b
    bpy.ops.object.mode_set(mode='POSE')
    pb = ob.pose.bones["base"]
    for f, x in ((1, 0.0), (19, 0.3), (37, 0.0), (55, -0.3), (72, 0.0)):
        pb.location = (x, 0, 0)
        pb.keyframe_insert("location", frame=f)
    bpy.ops.object.mode_set(mode='OBJECT')
    return ob


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class SpringBoneBlenderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        _register_extension(cls.tmp)

    def _add_chain(self, ob):
        import bpy
        from io_scene_x3d import springbone_blender as sb
        bpy.context.view_layer.objects.active = ob
        ob.data.bones.active = ob.data.bones["tail_1"]
        bpy.ops.x3d.springbone_add(name="Tail", frequency=1.5, damping_ratio=0.2, stiffness=0.02, gravity=9.81)
        ob.data.bones.active = ob.data.bones["base"]
        bpy.ops.x3d.springbone_collider_add(shape='SPHERE', radius=0.05, along=0.5)
        chains = sb.get_chains(ob)
        self.assertEqual(len(chains), 1)
        self.assertEqual(chains[0]["roots"], ["tail_1"])
        return sb

    def test_bake_puts_tips_where_the_solver_said(self):
        import bpy
        ob = _tail_rig()
        sb = self._add_chain(ob)
        receipt = sb.bake_armature(bpy.context, ob)
        self.assertEqual(receipt["frames"], 72)
        self.assertGreater(receipt["keys"], 72 * 3)
        tips = receipt["tips"][0]
        worst, moved = 0.0, 0.0
        for fi, f in enumerate(range(1, 73)):
            bpy.context.scene.frame_set(f)
            tail = ob.matrix_world @ ob.pose.bones["tail_4"].tail
            worst = max(worst, max(abs(tail[i] - tips[fi][i]) for i in range(3)))
            moved = max(moved, abs(tail.x - ob.pose.bones["base"].location.x))
        self.assertLess(worst, 1e-5, f"baked tail vs solver tip {worst:.2e} m")
        self.assertGreater(moved, 0.02, "the tail should lag behind the swaying base")
        self.assertTrue(ob.animation_data.action.name.endswith("_spring"))
        sb.clear_bake(ob)
        self.assertFalse(ob.animation_data.action.name.endswith("_spring"))
        print(f"\nbake: 72 frames, {receipt['keys']} keys, tip vs solver {worst:.2e} m, lag {moved:.3f} m, hash {receipt['hash'][0]}")

    def test_export_and_import_round_trip(self):
        import bpy
        ob = _tail_rig()
        self._add_chain(ob)
        out = os.path.join(self.tmp, "tail_spring.x3d")
        bpy.ops.export_scene.x3d(filepath=out)
        text = Path(out).read_text()
        self.assertIn("<ProtoInstance name='SpringBoneChain'", text)
        self.assertIn("<ExternProtoDeclare name='SpringBoneChain'", text)
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "SpringBone.x3d")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp, "springbone-script.js")))
        if os.path.exists(XSD):
            from lxml import etree
            xsd = etree.XMLSchema(etree.parse(XSD))
            ok = xsd.validate(etree.parse(out))
            self.assertTrue(ok, str(xsd.error_log)[:800])
        bpy.ops.wm.read_factory_settings(use_empty=True)
        bpy.ops.import_scene.x3d(filepath=out)
        arms = [o for o in bpy.data.objects if o.type == 'ARMATURE']
        self.assertEqual(len(arms), 1)
        from io_scene_x3d import springbone_blender as sb
        chains = sb.get_chains(arms[0])
        self.assertEqual(len(chains), 1, "the chain comes back on the imported armature")
        c = chains[0]
        self.assertEqual(c["roots"], ["tail_1"])
        self.assertEqual(c["params"]["springModel"], "FORCE")
        self.assertAlmostEqual(c["params"]["frequency"], 1.5, places=6)
        self.assertEqual(len(c["colliders"]), 1)
        self.assertEqual(c["colliders"][0]["bone"], "base")
        # the import rebuilds bone orientations from joint centres, so compare in armature space: base head + 0.1 up
        from mathutils import Vector
        rest = arms[0].data.bones["base"].matrix_local
        where = rest @ Vector(c["colliders"][0]["center"])
        self.assertLess((where - Vector((0, 0, 1.1))).length, 1e-6, tuple(where))


if __name__ == "__main__":
    unittest.main()
