# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""An imported Box, Sphere, Cylinder or Cone goes back out of the X3D 4.0 export as that node while its mesh is
unedited, instead of a tessellated IndexedFaceSet.

The import tessellates a primitive into a mesh (a Sphere into 16 x 16 facets), and the export wrote that mesh as an
IndexedFaceSet: THALASSA's re-export grew 1.9x and X_ITE drew its spheres faceted where the original was smooth.
The import now keeps the node and fields on the mesh (``x3d_primitive``) with a checksum of the vertex positions;
the export writes the primitive back, DEF on first use and USE after, unless a vertex moved, the counts changed,
or a TextureTransform was baked into the UVs.

Skipped when ``bpy`` is not importable::

    cd tests && python -m unittest test_primitive_round_trip_bpy
"""

from __future__ import annotations

import os
import re
import tempfile
import unittest

try:
    import bpy
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

HEAD = '<?xml version="1.0" encoding="UTF-8"?>\n<X3D profile="Immersive" version="4.0"><head/><Scene>\n'
TAIL = "</Scene></X3D>\n"
LOOK = '<Appearance><PhysicalMaterial baseColor="0.8 0.3 0.2"/></Appearance>'


@unittest.skipUnless(HAVE_BPY, "bpy not available")
class PrimitiveRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="x3d_primitive_rt_")
        _register_extension(self.tmp)
        bpy.ops.wm.read_factory_settings(use_empty=True)
        _register_extension(self.tmp)

    def _round_trip(self, body, edit=None):
        src = os.path.join(self.tmp, "in.x3d")
        with open(src, "w", encoding="utf-8") as handle:
            handle.write(HEAD + body + TAIL)
        self.assertEqual(bpy.ops.import_scene.x3d(filepath=src), {"FINISHED"})
        if edit is not None:
            edit()
        out = os.path.join(self.tmp, "out.x3d")
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=out, x3d_version="X3D40", use_selection=False),
                         {"FINISHED"})
        with open(out, encoding="utf-8") as handle:
            return handle.read()

    def test_each_primitive_comes_back_with_its_fields(self):
        text = self._round_trip(
            f'<Transform translation="-6 0 0"><Shape>{LOOK}<Box size="1 2 3"/></Shape></Transform>'
            f'<Transform translation="-2 0 0"><Shape>{LOOK}<Sphere radius="0.75"/></Shape></Transform>'
            f'<Transform translation="2 0 0"><Shape>{LOOK}<Cylinder radius="0.5" height="3" top="false"/></Shape>'
            '</Transform>'
            f'<Transform translation="6 0 0"><Shape>{LOOK}<Cone bottomRadius="0.4" height="1.5" bottom="false"/>'
            '</Shape></Transform>')
        self.assertNotIn("<IndexedFaceSet", text)
        box = re.search(r"<Box\b[^>]*>", text).group(0)
        self.assertIn('size="1.000000 2.000000 3.000000"', box)
        self.assertIn('radius="0.750000"', re.search(r"<Sphere\b[^>]*>", text).group(0))
        cylinder = re.search(r"<Cylinder\b[^>]*>", text).group(0)
        self.assertIn('radius="0.500000"', cylinder)
        self.assertIn('height="3.000000"', cylinder)
        self.assertIn('top="false"', cylinder)
        cone = re.search(r"<Cone\b[^>]*>", text).group(0)
        self.assertIn('bottomRadius="0.400000"', cone)
        self.assertIn('bottom="false"', cone)

    def test_shared_primitive_is_def_then_use(self):
        text = self._round_trip(
            f'<Transform translation="-2 0 0"><Shape DEF="S">{LOOK}<Sphere radius="0.5"/></Shape></Transform>'
            '<Transform translation="2 0 0"><Shape USE="S"/></Transform>')
        spheres = re.findall(r"<Sphere\b[^>]*>", text)
        self.assertEqual(len(spheres), 2)
        self.assertIn("DEF=", spheres[0])
        self.assertIn("USE=", spheres[1])

    def test_edited_mesh_falls_back_to_indexed_face_set(self):
        def move_a_vertex():
            mesh = next(o for o in bpy.data.objects if o.type == "MESH").data
            mesh.vertices[0].co.x += 0.25
        text = self._round_trip(f'<Shape>{LOOK}<Box size="1 1 1"/></Shape>', edit=move_a_vertex)
        self.assertNotIn("<Box", text)
        self.assertIn("<IndexedFaceSet", text)

    def test_texture_transform_keeps_the_mesh(self):
        body = ('<Shape><Appearance><PhysicalMaterial/><TextureTransform scale="2 2"/></Appearance>'
                '<Box size="1 1 1"/></Shape>')
        text = self._round_trip(body)
        self.assertNotIn("<Box", text)
        self.assertIn("<IndexedFaceSet", text)


if __name__ == "__main__":
    unittest.main()
