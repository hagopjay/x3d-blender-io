# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Metamorphic relations on the frozen scenes: change the input in a known way, the X3D 4.0 export must change in the
matching known way (v3 plan, Gate 2). No reference image and no golden file is needed (needs ``bpy``).

    python .github/scripts/run_tests_in_blender.py -- test_metamorphic_bpy

Six relations x twelve scenes (tests/frozen_scenes.py), compared in canonical form (tools/io_sync/x3d_c14n.py):

  R1 move an object by v          exactly one Transform's translation changes, by v after the axis conversion
  R2 rename an object             nothing changes once DEF names are canonical (D1, D2, ...)
  R3 reorder the outliner         the same top-level subtrees (sibling order may move); the first Viewpoint, which X3D
                                  binds, should not move: it does today in 1 of 12 (budget, see the test)
  R4 export at global scale 2     only top-level Transforms change: translation and scale x2, rotation unchanged
  R5 export, import, export with a non-default axis and back
                                  the same file as the default-axis round trip
  R6 add an unused material       nothing changes
"""

from __future__ import annotations

import difflib
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tools" / "io_sync"))
V = (0.5, -0.25, 0.75)


def _register():
    tmp = tempfile.mkdtemp(prefix="x3d_mr_")
    # X3D_ADDON_SOURCE points the relations at another copy of source/, e.g. a planted fault (tools/oracles/plant.py)
    source = Path(os.environ.get("X3D_ADDON_SOURCE", ROOT / "source")).resolve()
    (Path(tmp) / "io_scene_x3d").symlink_to(source, target_is_directory=True)
    sys.path.insert(0, tmp)
    import importlib
    module = importlib.import_module("io_scene_x3d")
    try:
        module.register()
    except Exception:
        pass
    return tmp


def _changed(a: str, b: str):
    """(removed lines, added lines) between two canonical texts."""
    diff = [line for line in difflib.unified_diff(a.splitlines(), b.splitlines(), n=0, lineterm="")
            if line[:1] in "+-" and line[:3] not in ("+++", "---")]
    return [line[1:] for line in diff if line[0] == "-"], [line[1:] for line in diff if line[0] == "+"]


def _attrs(line: str) -> dict:
    return ET.fromstring(line.strip().rstrip(">").rstrip("/") + "/>").attrib


def _subtrees(text):
    """The Scene's children as a sorted list, with USE expanded and DEF/USE dropped, so that which copy of a shared
    node is written first (and so carries the DEF) does not count as a difference."""
    import copy

    scene_el = ET.fromstring(text).find("Scene")
    defs = {el.get("DEF"): el for el in scene_el.iter() if el.get("DEF")}

    def expand(el):
        if el.get("USE") in defs:
            el = copy.deepcopy(defs[el.get("USE")])
        out = ET.Element(el.tag, {k: v for k, v in el.attrib.items() if k not in ("DEF", "USE")})
        out.extend(expand(child) for child in el)
        return out
    return sorted(ET.tostring(expand(child), encoding="unicode") for child in scene_el)


def _first_viewpoint(text):
    return next((el.get("DEF") for el in ET.fromstring(text).iter("Viewpoint")), None)


def _floats(text):
    return [float(t) for t in text.split()]


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
class MetamorphicRelations(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = _register()
        import frozen_scenes
        import x3d_c14n
        cls.scenes = frozen_scenes
        cls.c14n = x3d_c14n

    def _export(self, name, **kw):
        import bpy

        path = os.path.join(self.tmp, name)
        self.assertEqual(bpy.ops.export_scene.x3d(filepath=path, x3d_version="X3D40", use_selection=False, **kw),
                         {"FINISHED"})
        return path

    def _canon(self, path, rename=False):
        return self.c14n.canonical_file(path, rename_defs=rename)

    def test_r1_move_changes_exactly_one_translation_by_the_vector(self):
        for scene in self.scenes.SCENES:
            with self.subTest(scene=scene):
                main = self.scenes.build(scene)["main"]
                base = self._canon(self._export("r1a.x3d"))
                main = self.scenes.build(scene)["main"]
                main.delta_location = V
                top_level = main.parent is None
                removed, added = _changed(base, self._canon(self._export("r1b.x3d")))
                self.assertEqual((len(removed), len(added)), (1, 1), f"{scene}: {removed} -> {added}")
                old, new = _attrs(removed[0]), _attrs(added[0])
                self.assertEqual(old.get("DEF"), new.get("DEF"))
                self.assertEqual({k for k in old if old[k] != new.get(k)}, {"translation"})
                delta = [b - a for a, b in zip(_floats(old["translation"]), _floats(new["translation"]))]
                # a top-level Transform carries the Z-up to Y-up conversion: Blender (x, y, z) is X3D (x, z, -y)
                expected = (V[0], V[2], -V[1]) if top_level else V
                for got, want in zip(delta, expected):
                    self.assertAlmostEqual(got, want, places=4, msg=f"{scene}: {delta} != {expected}")

    def test_r2_rename_changes_nothing_but_names(self):
        for scene in self.scenes.SCENES:
            with self.subTest(scene=scene):
                self.scenes.build(scene)
                base = self._canon(self._export("r2a.x3d"), rename=True)
                main = self.scenes.build(scene)["main"]
                main.name = main.name + "_Renamed"
                self.assertEqual(base, self._canon(self._export("r2b.x3d"), rename=True))

    def test_r3_outliner_order_keeps_the_subtrees_and_the_first_viewpoint(self):
        import bpy

        strict, first_moved = 0, []
        for scene in self.scenes.SCENES:
            with self.subTest(scene=scene):
                self.scenes.build(scene)
                bound = bpy.context.scene.camera.name if bpy.context.scene.camera else None
                base = self._canon(self._export("r3a.x3d"))
                self.scenes.build(scene)
                collection = bpy.context.scene.collection
                objects = list(collection.objects)
                for obj in objects:
                    collection.objects.unlink(obj)
                for obj in reversed(objects):
                    collection.objects.link(obj)
                self.assertEqual(bound, bpy.context.scene.camera.name if bpy.context.scene.camera else None)
                moved = self._canon(self._export("r3b.x3d"))
                strict += base == moved
                self.assertEqual(_subtrees(base), _subtrees(moved), f"{scene}: the top-level subtrees differ")
                if _first_viewpoint(base) != _first_viewpoint(moved):
                    first_moved.append(scene)
        print(f"[metamorphic] R3 strict order kept in {strict} of {len(self.scenes.SCENES)} scenes; first Viewpoint "
              f"moved in {first_moved}")
        # KNOWN LOSS (Confirmed, bpy 5.3.0, main 47ed742): the export writes Viewpoints in outliner order and ignores
        # scene.camera, and X3D binds the first Viewpoint it meets, so reordering the outliner changes which camera a
        # browser opens on while Blender's active camera stays the same. The importer binds the first Viewpoint
        # (populate.py), so the active camera survives a round trip only when it happens to come first. This budget
        # may only shrink: writing scene.camera's Viewpoint first takes 'cameras' off it.
        self.assertLessEqual(set(first_moved), {"cameras"})
    def test_r4_global_scale_doubles_lengths_and_nothing_else(self):
        for scene in self.scenes.SCENES:
            with self.subTest(scene=scene):
                self.scenes.build(scene)
                base = self._canon(self._export("r4a.x3d"))
                self.scenes.build(scene)
                removed, added = _changed(base, self._canon(self._export("r4b.x3d", global_scale=2.0)))
                self.assertEqual(len(removed), len(added))
                self.assertGreater(len(removed), 0)
                for old_line, new_line in zip(removed, added):
                    self.assertEqual(len(old_line) - len(old_line.lstrip()), 2, f"{scene}: not top level: {old_line}")
                    old, new = _attrs(old_line), _attrs(new_line)
                    self.assertEqual(old.get("rotation"), new.get("rotation"))
                    for key in ("translation", "scale"):
                        for a, b in zip(_floats(old[key]), _floats(new[key])):
                            self.assertAlmostEqual(2.0 * a, b, places=4, msg=f"{scene} {key}")
                    self.assertEqual({k for k in old if old[k] != new.get(k)} - {"translation", "scale"}, set())

    def test_r5_a_non_default_axis_round_trip_returns_the_same_file(self):
        import bpy

        for scene in self.scenes.SCENES:
            with self.subTest(scene=scene):
                self.scenes.build(scene)
                first = self._export("r5a.x3d")
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.assertEqual(bpy.ops.import_scene.x3d(filepath=first), {"FINISHED"})
                default = self._canon(self._export("r5a2.x3d"), rename=True)
                self.scenes.build(scene)
                other = self._export("r5b.x3d", axis_forward="Y", axis_up="Z")
                bpy.ops.wm.read_factory_settings(use_empty=True)
                self.assertEqual(bpy.ops.import_scene.x3d(filepath=other, axis_forward="Y", axis_up="Z"), {"FINISHED"})
                self.assertEqual(default, self._canon(self._export("r5b2.x3d"), rename=True))

    def test_r6_an_unused_material_changes_nothing(self):
        import bpy

        for scene in self.scenes.SCENES:
            with self.subTest(scene=scene):
                self.scenes.build(scene)
                base = self._canon(self._export("r6a.x3d"))
                self.scenes.build(scene)
                bpy.data.materials.new("NobodyUsesMe")
                self.assertEqual(base, self._canon(self._export("r6b.x3d")))


if __name__ == "__main__":
    unittest.main()
