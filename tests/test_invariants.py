# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""The round-trip invariant judge (tools/io_sync/invariants.py) and its planted faults (plain Python).

Each planted fault is one edit to a small X3D file that a lossy import/export could make; the judge must name the
invariant it breaks, and a pure renaming of DEFs must break nothing."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "io_sync"))
import invariants  # noqa: E402

E0 = """<X3D profile='Interchange' version='4.0'><Scene>
 <Transform DEF='OB_A' translation='1 0 0'>
  <Group DEF='CO_Part'>
   <Shape><Appearance DEF='AP_Red'><PhysicalMaterial baseColor='0.8 0.1 0.1' metallic='0' roughness='0.5'/>
    <ImageTexture url='"textures/red.png"'/></Appearance>
    <IndexedFaceSet coordIndex='0 1 2 -1 0 2 3 -1'><Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedFaceSet>
   </Shape>
  </Group>
 </Transform>
 <Transform DEF='OB_B' translation='0 0 -2' scale='2 2 2'><Group USE='CO_Part'/></Transform>
 <Transform DEF='OB_Cam' translation='0 1 5'><Viewpoint DEF='CA_Cam' position='0 0 0'/></Transform>
 <DirectionalLight DEF='LA_Sun' intensity='0.8' color='1 0.9 0.8'/>
 <TimeSensor DEF='TI_Clock' loop='true'/>
 <PositionInterpolator DEF='PI_Move' key='0 1' keyValue='0 0 0 1 0 0'/>
 <ROUTE fromNode='TI_Clock' fromField='fraction_changed' toNode='PI_Move' toField='set_fraction'/>
 <ROUTE fromNode='PI_Move' fromField='value_changed' toNode='OB_A' toField='set_translation'/>
</Scene></X3D>"""

PLANTS = {
    "a ROUTE is lost": (("<ROUTE fromNode='PI_Move' fromField='value_changed' toNode='OB_A' toField='set_translation'/>",
                         ""), "routes"),
    "a base colour drifts": (("baseColor='0.8 0.1 0.1'", "baseColor='0.8 0.2 0.1'"), "materials"),
    "shared data is copied": (("<Group USE='CO_Part'/>", "<Group><Shape><IndexedFaceSet coordIndex='0 1 2 -1 0 2 3 -1'>"
                               "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedFaceSet></Shape></Group>"),
                              "instancing"),
    "an object moves": (("translation='0 0 -2'", "translation='0 0 -3'"), "bbox"),
    "a face is lost": (("coordIndex='0 1 2 -1 0 2 3 -1'", "coordIndex='0 1 2 -1'"), "faces"),
    "a light dims": (("intensity='0.8'", "intensity='0.5'"), "lights"),
    "the bound camera moves": (("translation='0 1 5'", "translation='0 1 6'"), "first_viewpoint"),
    "a texture is lost": (("<ImageTexture url='\"textures/red.png\"'/>", ""), "textures"),
}


class InvariantJudge(unittest.TestCase):
    def setUp(self):
        self.base = invariants.measure(E0)

    def test_measures_the_scene(self):
        self.assertEqual(self.base["faces"], {"IndexedFaceSet": 4})
        self.assertEqual(self.base["instancing"], {"Group": 1})
        self.assertEqual(self.base["viewpoints"], 1)
        self.assertEqual(self.base["first_viewpoint"], [0.0, 1.0, 5.0])
        # OB_B's copy is scaled 2 and moved to z -2: the world box spans both copies
        self.assertEqual(self.base["bbox"], [[0.0, 0.0, -2.0], [2.0, 2.0, 0.0]])
        self.assertEqual(sum(self.base["routes"].values()), 2)

    def test_renaming_every_def_breaks_nothing(self):
        renamed = E0
        for old, new in (("OB_A", "X1"), ("CO_Part", "X2"), ("AP_Red", "X3"), ("PI_Move", "X4"), ("TI_Clock", "X5")):
            renamed = renamed.replace(f"'{old}'", f"'{new}'")
        self.assertEqual(invariants.compare(self.base, invariants.measure(renamed)), {})

    def test_every_planted_fault_is_caught_by_its_invariant(self):
        for name, ((find, replace), invariant) in PLANTS.items():
            with self.subTest(plant=name):
                self.assertEqual(E0.count(find), 1, name)
                broken = invariants.compare(self.base, invariants.measure(E0.replace(find, replace)))
                self.assertIn(invariant, broken, f"{name}: judge said {sorted(broken)}")

    def test_budget_fails_a_new_break_and_reports_a_healed_one(self):
        broken = {"main": invariants.compare(self.base, invariants.measure(E0.replace("intensity='0.8'", "")))}
        failures, _ = invariants.check_budget(broken, {"profiles": {"main": {}}})
        self.assertEqual(len(failures), 1)
        self.assertIn("lights", failures[0])
        failures, tightened = invariants.check_budget({"main": {}}, {"profiles": {"main": broken["main"]}})
        self.assertEqual((failures, len(tightened)), ([], 1))

    def test_committed_budget_names_only_known_invariants(self):
        budget = json.loads((ROOT / "tools" / "io_sync" / "invariant_budget.json").read_text())
        known = set(self.base)
        for profile, broken in budget["profiles"].items():
            self.assertLessEqual(set(broken), known, profile)


if __name__ == "__main__":
    unittest.main()
