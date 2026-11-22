# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Loss receipt v1 core (source/receipt.py): rules, entries, the stable hash line (plain Python, no Blender)."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "source"))
import receipt  # noqa: E402

TABLE = receipt.load_table()


def owner(group, name, values, custom=None, node=None):
    return receipt.Owner(group=group, datablock=name, get=lambda prop: values[prop],
                         custom=lambda key: (custom or {}).get(key), node=node)


def light(kind, name, **values):
    base = {"POINT": dict(type="POINT", energy=1.0, use_temperature=False, temperature=6500.0, exposure=0.0,
                          normalize=True, specular_factor=1.0, diffuse_factor=1.0, transmission_factor=1.0,
                          volume_factor=1.0, cutoff_distance=40.0, use_custom_distance=True),
            "SPOT": dict(type="SPOT", energy=1.0, use_temperature=False, temperature=6500.0, exposure=0.0,
                         normalize=True, specular_factor=1.0, diffuse_factor=1.0, transmission_factor=1.0,
                         volume_factor=1.0, cutoff_distance=40.0, use_custom_distance=True, spot_size=0.785,
                         spot_blend=0.15, use_square=False)}[kind]
    base.update(values)
    return base


class Rules(unittest.TestCase):
    def test_light_energy_is_clamped_above_the_cap(self):
        entries = receipt.evaluate(TABLE, [owner("light.point", "Bright", light("POINT", "Bright", energy=10.0)),
                                           owner("light.point", "Dim", light("POINT", "Dim", energy=1.0))])
        clamped = [(e.row, e.datablock, e.limit) for e in entries if e.kind == "clamped"]
        self.assertEqual(clamped, [("light.point:energy", "Bright", 1.75)])

    def test_an_imported_light_keeps_its_intensity_and_gets_no_clamp_entry(self):
        entries = receipt.evaluate(TABLE, [owner("light.point", "FromFile", light("POINT", "FromFile", energy=10.0),
                                                 custom={"x3d_intensity": 5.7})])
        self.assertNotIn("light.point:energy", [e.row for e in entries])

    def test_when_gates_a_rule_on_another_property(self):
        cold = owner("light.point", "Cold", light("POINT", "Cold", use_temperature=True, temperature=12000.0))
        off = owner("light.point", "Off", light("POINT", "Off", use_temperature=False, temperature=12000.0))
        rows = [(e.row, e.datablock) for e in receipt.evaluate(TABLE, [cold, off])]
        self.assertIn(("light.point:temperature", "Cold"), rows)
        self.assertNotIn(("light.point:temperature", "Off"), rows)

    def test_neq_on_colours_and_linked_inputs(self):
        sockets = {"IOR": 1.5, "Subsurface Weight": 0.0, "Specular IOR Level": 0.5, "Specular Tint": [1, 1, 1, 1],
                   "Anisotropic": 0.0, "Transmission Weight": "linked", "Coat Weight": 0.25, "Sheen Weight": 0.0,
                   "Thin Film Thickness": 0.0, "Diffuse Roughness": 0.0, "Thin Wall": False,
                   "Transmission Dispersion Scale": 0.0}
        rows = {e.row for e in receipt.evaluate(TABLE, [owner("principled", "Glass", sockets)])}
        self.assertEqual(rows, {"principled:Coat Weight", "principled:Transmission Weight"})
        sockets["Specular Tint"] = [1, 0.5, 1, 1]
        rows = {e.row for e in receipt.evaluate(TABLE, [owner("principled", "Glass", sockets)])}
        self.assertIn("principled:Specular Tint", rows)

    def test_a_property_this_blender_lacks_is_skipped(self):
        def get(prop):
            raise AttributeError(prop)
        self.assertEqual(receipt.evaluate(TABLE, [receipt.Owner("light.point", "Old", get)]), [])

    def test_versioned_rows_resolve(self):
        row = {"id": "world:color", "class": "editor_only", "before": {"5.0": {"class": "carried"}}}
        self.assertEqual(receipt.resolve_row(row, "4.5.14 LTS")["class"], "carried")
        self.assertEqual(receipt.resolve_row(row, "5.3.0")["class"], "editor_only")
        self.assertNotIn("before", receipt.resolve_row(row, None))


class HashLine(unittest.TestCase):
    def test_line_depends_only_on_content_not_order(self):
        a = owner("light.point", "A", light("POINT", "A", energy=9.0))
        b = owner("light.spot", "B", light("SPOT", "B", energy=9.0, spot_blend=0.5))
        one = receipt.receipt_line(receipt.evaluate(TABLE, [a, b]))
        two = receipt.receipt_line(receipt.evaluate(TABLE, [b, a]))
        self.assertEqual(one, two)
        self.assertRegex(one, r"^sha256=[0-9a-f]{32} dropped=\d+ approximated=\d+ clamped=\d+ "
                              r"schema=x3d-blender-io\.loss-receipt/1$")

    def test_line_changes_when_a_loss_changes(self):
        a = receipt.receipt_line(receipt.evaluate(TABLE, [owner("light.point", "A", light("POINT", "A", energy=9.0))]))
        b = receipt.receipt_line(receipt.evaluate(TABLE, [owner("light.point", "A", light("POINT", "A", energy=8.0))]))
        self.assertNotEqual(a, b)

    def test_empty_scene_has_a_line_too(self):
        self.assertTrue(receipt.receipt_line([]).startswith("sha256="))

    def test_emitter_and_receipt_agree_on_the_meta_name(self):
        text = (ROOT / "source" / "emit_x3d40.py").read_text()
        self.assertIn(f'RECEIPT_META = "{receipt.RECEIPT_META}"', text)


class Sidecar(unittest.TestCase):
    def test_receipt_document_shape(self):
        entries = receipt.evaluate(TABLE, [owner("light.point", "A", light("POINT", "A", energy=9.0))])
        doc = receipt.build_receipt(entries, notes=["a note"], subject={"file": "a.x3d"}, tools={"addon": "t"},
                                    prev="sha256=00 dropped=0 approximated=0 clamped=0")
        self.assertEqual(doc["schema"], "x3d-blender-io.loss-receipt/1")
        self.assertEqual(doc["totals"], {"dropped": 0, "approximated": 0, "clamped": 1, "notes": 1})
        entry = doc["entries"][0]
        self.assertEqual(entry["row"], "light.point:energy")
        self.assertEqual(entry["rule"], "source/mapping/blender_rna.json#light.point:energy")
        self.assertEqual(set(entry["locus"]), {"datablock", "node", "field"})
        self.assertEqual(len(doc["tools"]["mapping_sha256"]), 64)
        json.dumps(doc)

    def test_prev_chains_to_an_imported_line(self):
        meta = [("generator", "x"), (receipt.RECEIPT_META, "sha256=ab dropped=1")]
        self.assertEqual(receipt.prev_from_meta(meta), "sha256=ab dropped=1")
        self.assertIsNone(receipt.prev_from_meta([("generator", "x")]))

    def test_planted_fault_a_missing_rule_changes_the_receipt(self):
        """Planted fault for the receipt: drop the clamp rule from the table and the clamp entry disappears."""
        broken = json.loads(json.dumps(TABLE))
        for row in broken["rows"]:
            if row["id"] == "light.point:energy":
                del row["receipt"]
        bright = [owner("light.point", "A", light("POINT", "A", energy=9.0))]
        self.assertNotEqual(receipt.receipt_line(receipt.evaluate(TABLE, bright)),
                            receipt.receipt_line(receipt.evaluate(broken, bright)))


if __name__ == "__main__":
    unittest.main()
