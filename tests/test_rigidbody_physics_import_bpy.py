# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""RigidBodyPhysics import (issues #99 and #100, found by the x3d.nVidia Q12 run 2, Blender 5.3.0 and add-on 2.7.6).

* #99: a RigidBody's collision shape sat at the origin, because only Transform nodes moved what was under them.
  RigidBody (position, orientation), CollidableOffset and CollidableShape (translation, rotation) now do.
* #100: a RigidBody that a joint reached through USE was imported a second time, and so was a CollidableShape that a
  CollisionCollection listed. A USE of a physics node is a reference, never an instance (a USE'd Transform still is one).

Each placement is checked against the same shape inside plain Transforms, so the test does not depend on the axis
conversion. Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_rigidbody_physics_import_bpy
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "source"))

BOX = "<Shape containerField='shape'><Box size='0.2 0.4 0.6'/></Shape>"
PLAIN = "<Shape><Box size='0.2 0.4 0.6'/></Shape>"


def _x3d(body: str) -> str:
    return f"<?xml version='1.0' encoding='UTF-8'?>\n<X3D profile='Full' version='4.0'><Scene>{body}</Scene></X3D>\n"


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class RigidBodyImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_rigidbody_")
        _register_extension(cls.tmpdir)

    def _meshes(self, name, body):
        import bpy
        path = os.path.join(self.tmpdir, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(_x3d(body))
        bpy.ops.wm.read_factory_settings(use_empty=True)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=path), {"FINISHED"})
        # the rigid body world's own objects (a compound body's holder, the start-up anchor) carry no shape of the file
        return sorted((o for o in bpy.data.objects if o.type == "MESH" and "x3d_rigid_body_holder" not in o.keys()
                       and "x3d_physics_helper" not in o.keys()), key=lambda o: o.name)

    def _world(self, name, body):
        """The world matrices of the mesh objects, rounded."""
        out = []
        for o in self._meshes(name, body):
            out.append(tuple(round(v, 4) for row in o.matrix_world for v in row))
        return out

    def test_rigid_body_position_and_orientation_move_its_shape(self):
        placed = self._world("rb_pose.x3d",
                             "<RigidBodyCollection><RigidBody containerField='bodies' position='1 2 3' orientation='0 1 0 0.7'>"
                             f"<CollidableShape containerField='geometry'>{BOX}</CollidableShape></RigidBody></RigidBodyCollection>")
        control = self._world("rb_pose_control.x3d",
                              f"<Transform translation='1 2 3' rotation='0 1 0 0.7'>{PLAIN}</Transform>")
        self.assertEqual(len(placed), 1)
        self.assertEqual(placed, control)
        self.assertNotEqual(placed[0][3], 0.0)          # not at the origin

    def test_collidable_offset_and_shape_compose_with_the_body(self):
        placed = self._world("rb_offset.x3d",
                             "<RigidBodyCollection><RigidBody containerField='bodies' position='1 0 0'>"
                             "<CollidableOffset containerField='geometry' translation='0 2 0'>"
                             f"<CollidableShape containerField='collidable' translation='0 0 3'>{BOX}</CollidableShape>"
                             "</CollidableOffset></RigidBody></RigidBodyCollection>")
        control = self._world("rb_offset_control.x3d",
                              f"<Transform translation='1 0 0'><Transform translation='0 2 0'><Transform translation='0 0 3'>{PLAIN}"
                              "</Transform></Transform></Transform>")
        self.assertEqual(placed, control)

    def test_a_body_a_joint_uses_is_not_imported_twice(self):
        meshes = self._meshes(
            "rb_joint_use.x3d",
            "<RigidBodyCollection>"
            f"<RigidBody DEF='Pivot' containerField='bodies' position='0 5 0' fixed='true'><CollidableShape containerField='geometry'>{BOX}</CollidableShape></RigidBody>"
            f"<RigidBody DEF='Bob' containerField='bodies' position='3 5 0'><CollidableShape containerField='geometry'>{BOX}</CollidableShape></RigidBody>"
            "<BallJoint containerField='joints' anchorPoint='0 5 0'><RigidBody USE='Bob' containerField='body1'/>"
            "<RigidBody USE='Pivot' containerField='body2'/></BallJoint></RigidBodyCollection>")
        self.assertEqual(len(meshes), 2, [o.name for o in meshes])
        self.assertEqual(len({tuple(round(v, 4) for v in o.matrix_world.translation) for o in meshes}), 2)   # apart, not at 0

    def test_a_collidable_a_collection_lists_is_not_imported_twice(self):
        meshes = self._meshes(
            "rb_collection_use.x3d",
            "<RigidBodyCollection>"
            f"<RigidBody containerField='bodies' position='1 1 1'><CollidableShape DEF='C' containerField='geometry'>{BOX}</CollidableShape></RigidBody>"
            "<CollisionCollection containerField='collider'><CollidableShape USE='C' containerField='collidables'/></CollisionCollection>"
            "</RigidBodyCollection>")
        self.assertEqual(len(meshes), 1, [o.name for o in meshes])

    def test_a_used_transform_is_still_an_instance(self):
        meshes = self._meshes("transform_use.x3d",
                              f"<Transform DEF='T' translation='1 0 0'>{PLAIN}</Transform><Transform USE='T'/>")
        self.assertEqual(len(meshes), 2)


if __name__ == "__main__":
    unittest.main()
