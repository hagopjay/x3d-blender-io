# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Khronos glTF Validator gate: an X3D probe through the add-on to a glb has zero validator errors, and a corrupted glb fails.

The fidelity rig (tools/fidelity_rig) validates every glb it makes with validate_glb.mjs (gltf-validator, pinned in
tools/fidelity_rig/package.json). This test needs no browser: it imports a probe, exports a glb with the rig's settings
(blender_leg.py), and runs the gate on it. Skipped, with the reason, when ``bpy``, node or gltf-validator is missing
(``npm install`` in tools/fidelity_rig, or point GLTF_VALIDATOR_DIR at an installed gltf-validator)::

    cd tests && python -m unittest test_glb_validator_bpy
"""

from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path

try:
    import bpy  # noqa: F401
    HAVE_BPY = True
except Exception:  # pragma: no cover - plain Python
    HAVE_BPY = False

from test_roundtrip_bpy import _register_extension

ROOT = Path(__file__).resolve().parents[1]
RIG = ROOT / "tools" / "fidelity_rig"
GATE = RIG / "validate_glb.mjs"
PROBE = RIG / "probes" / "p1-point-physical.x3d"


def _gate_unavailable():
    """None when node and gltf-validator work, else why the gate cannot run here."""
    node = shutil.which("node")
    if not node:
        return "node is not installed"
    r = subprocess.run([node, str(GATE), "--version"], capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return (r.stderr or r.stdout).strip() or "gltf-validator did not load"
    return None


NO_GATE = _gate_unavailable() if GATE.exists() else "validate_glb.mjs is missing"


if NO_GATE and os.environ.get("GLTF_VALIDATOR_REQUIRED") == "1":
    class GlbValidatorGateRequiredTests(unittest.TestCase):
        """CI sets GLTF_VALIDATOR_REQUIRED=1: a validator that cannot load is a failure there, not 8 silent skips."""

        def test_the_validator_loads(self):
            self.fail(f"GLTF_VALIDATOR_REQUIRED=1 but the glTF validator gate is unavailable: {NO_GATE}")


def _run_gate(path, *extra):
    r = subprocess.run(["node", str(GATE), str(path), *extra], capture_output=True, text=True, timeout=120)
    report = Path(str(path) + ".validation.json")
    return r, (json.loads(report.read_text()) if report.exists() else None)


@unittest.skipUnless(HAVE_BPY, "bpy is not available")
@unittest.skipIf(NO_GATE, f"glTF validator gate unavailable: {NO_GATE}")
class GlbValidatorGateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir = tempfile.mkdtemp(prefix="x3d_glb_validator_")
        _register_extension(cls.tmpdir)
        cls.glb = os.path.join(cls.tmpdir, "scene.glb")
        cls._export(cls.glb, "GLB")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmpdir, ignore_errors=True)

    @staticmethod
    def _export(path, export_format):
        """The Blender leg of the rig: import the probe, export with blender_leg.py's glTF settings."""
        bpy.ops.wm.read_factory_settings(use_empty=True)
        assert bpy.ops.import_scene.x3d(filepath=str(PROBE)) == {"FINISHED"}
        assert bpy.ops.export_scene.gltf(
            filepath=path, export_format=export_format, export_lights=True, export_cameras=True,
            export_import_convert_lighting_mode="COMPAT", use_renderable=True, export_yup=True, export_extras=True,
            export_apply=True, use_mesh_edges=True, use_mesh_vertices=True) == {"FINISHED"}

    def _corrupt(self, name, mutate):
        data = bytearray(Path(self.glb).read_bytes())
        path = os.path.join(self.tmpdir, name)
        Path(path).write_bytes(bytes(mutate(data)))
        return path

    def test_probe_glb_has_no_validator_errors(self):
        r, rep = _run_gate(self.glb)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rep["numErrors"], 0, rep["issues"])
        self.assertEqual(rep["numWarnings"], 0, rep["issues"])
        self.assertTrue(rep["ok"])
        # the probe is three boxes (12 triangles each) under one PointLight
        self.assertEqual(rep["totalTriangleCount"], 36)
        self.assertEqual(rep["drawCallCount"], 3)
        self.assertEqual(rep["materialCount"], 1)
        self.assertIn("KHR_lights_punctual", rep["extensionsUsed"])
        self.assertEqual(rep["bytes"], os.path.getsize(self.glb))
        self.assertRegex(rep["sha256"], r"^[0-9a-f]{64}$")
        self.assertIn("OK", r.stdout.splitlines()[0])

    def test_report_names_the_validator_version_pinned_in_package_json(self):
        _, rep = _run_gate(self.glb)
        pinned = json.loads((RIG / "package.json").read_text())["dependencies"]["gltf-validator"]
        self.assertEqual(rep["validatorVersion"], pinned)

    def test_separate_gltf_resolves_its_bin_and_has_no_errors(self):
        out = os.path.join(self.tmpdir, "sep")
        os.makedirs(out)
        self._export(os.path.join(out, "scene.gltf"), "GLTF_SEPARATE")
        r, rep = _run_gate(os.path.join(out, "scene.gltf"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rep["numErrors"], 0, rep["issues"])
        self.assertEqual(rep["totalTriangleCount"], 36)   # only true when the .bin was read through externalResourceFunction

    def test_a_truncated_bin_chunk_fails_the_gate(self):
        bad = self._corrupt("truncated.glb", lambda d: d[:-64])   # the header still claims the full length
        r, rep = _run_gate(bad)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertGreater(rep["numErrors"], 0)
        self.assertFalse(rep["ok"])
        self.assertIn("FAIL", r.stdout.splitlines()[0])

    def test_a_wrong_json_chunk_length_fails_the_gate(self):
        def mutate(d):
            (json_len,) = struct.unpack_from("<I", d, 12)
            struct.pack_into("<I", d, 12, json_len + 4096)   # the JSON chunk now claims to run past the end of the file
            return d
        r, rep = _run_gate(self._corrupt("jsonlen.glb", mutate))
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertGreater(rep["numErrors"], 0)

    def test_an_unknown_gltf_major_version_fails_the_gate(self):
        data = Path(self.glb).read_bytes()
        self.assertIn(b'"version":"2.0"', data)   # same length swap, so the chunk and file lengths stay valid
        bad = os.path.join(self.tmpdir, "version.glb")
        Path(bad).write_bytes(data.replace(b'"version":"2.0"', b'"version":"3.0"', 1))
        r, rep = _run_gate(bad)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("UNKNOWN_ASSET_MAJOR_VERSION", [i["code"] for i in rep["issues"]])

    def test_a_file_that_is_not_gltf_fails_the_gate(self):
        bad = os.path.join(self.tmpdir, "garbage.glb")
        Path(bad).write_bytes(b"not a glTF at all")
        r, rep = _run_gate(bad)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertEqual(rep["issues"][0]["code"], "VALIDATOR_EXCEPTION")

    def _glb_with_edited_json(self, name, edit):
        """The probe glb with its JSON chunk edited by `edit(dict)` and repacked (4-byte padded, lengths rewritten)."""
        data = Path(self.glb).read_bytes()
        (json_len,) = struct.unpack_from("<I", data, 12)
        doc = json.loads(data[20:20 + json_len])
        edit(doc)
        chunk = json.dumps(doc, separators=(",", ":")).encode()
        chunk += b" " * (-len(chunk) % 4)
        rest = data[20 + json_len:]
        path = os.path.join(self.tmpdir, name)
        Path(path).write_bytes(struct.pack("<III", 0x46546C67, 2, 20 + len(chunk) + len(rest))
                               + struct.pack("<II", len(chunk), 0x4E4F534A) + chunk + rest)
        return path

    def test_max_warnings_fails_a_glb_that_has_a_warning_and_the_report_labels_it_a_warning(self):
        # an alphaCutoff on an OPAQUE material is a validator WARNING, not an error
        bad = self._glb_with_edited_json("warning.glb", lambda d: d["materials"][0].update(alphaCutoff=0.5))
        r, rep = _run_gate(bad)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)   # warnings pass unless a limit is given
        self.assertEqual((rep["numErrors"], rep["numWarnings"]), (0, 1), rep["issues"])
        self.assertEqual([(i["severity"], i["code"]) for i in rep["issues"] if i["severity"] != "INFO"],
                         [("WARNING", "MATERIAL_ALPHA_CUTOFF_INVALID_MODE")])
        r, rep = _run_gate(bad, "--max-warnings", "0")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(rep["ok"])
        self.assertIn("FAIL", r.stdout.splitlines()[0])
        r, rep = _run_gate(bad, "--max-warnings", "1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(rep["ok"])

    def test_an_extension_the_validator_does_not_know_is_listed_as_not_validated(self):
        data = Path(self.glb).read_bytes()
        (json_len,) = struct.unpack_from("<I", data, 12)
        doc = json.loads(data[20:20 + json_len])
        doc["extensionsUsed"].append("VENDOR_unknown_ext")
        doc["materials"][0].setdefault("extensions", {})["VENDOR_unknown_ext"] = {"anything": [1, "x"]}
        body = json.dumps(doc, separators=(",", ":")).encode()
        body += b" " * (-len(body) % 4)
        rest = data[20 + json_len:]
        bad = os.path.join(self.tmpdir, "unknown_ext.glb")
        Path(bad).write_bytes(struct.pack("<4sII", b"glTF", 2, 20 + len(body) + len(rest)) +
                              struct.pack("<I4s", len(body), b"JSON") + body + rest)
        r, rep = _run_gate(bad)
        # the validator reports this at INFO only, so the gate passes: what is recorded, and said on stdout, is that nothing was checked
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(rep["extensionsNotValidated"], ["VENDOR_unknown_ext"])
        self.assertIn("NOT VALIDATED: VENDOR_unknown_ext", r.stdout)

    def test_max_warnings_is_enforced_and_a_missing_file_is_a_usage_error(self):
        r, _ = _run_gate(self.glb, "--max-warnings", "0")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)   # the probe has no warnings
        r, _ = _run_gate(os.path.join(self.tmpdir, "no_such.glb"))
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
