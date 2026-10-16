# X3D export test suite

A 194-case Blender scene (147 CORE, 21 FIDELITY, 26 ROADMAP across 18 zones plus an optional stress zone) that is
exported with this add-on, validated at file level, and loaded in a real X3D browser (X_ITE).

| script | what it proves |
|---|---|
| `x3d_test_suite.py` | builds the scene and the three exports (`main`, `crease`, `x41`); writes the manifest |
| `validate_x3d_export.py` | the **file** is right (numbers, structure, animation maths, skinning maths); exit 1 if any CORE case fails |
| `x3d_browser_check.py` | X_ITE loads it, animates it and shows every zone (needs `pip install playwright` + Chromium) |

```bash
OUT=/tmp/x3d-suite
blender -b --factory-startup --python tests/suite/x3d_test_suite.py -- --out $OUT --repo "$PWD" --export
python3 tests/suite/validate_x3d_export.py $OUT --html $OUT/report.html
python3 tests/suite/x3d_browser_check.py  $OUT --report $OUT/browser_report.html   # optional
```

Answer key and findings: `docs/test-suite/X3D_TEST_EXPECTATIONS.md`, case table: `docs/test-suite/x3d_case_catalog.md`,
run commentary and the Blender 5.1.0 reproduction: `docs/test-suite/SUITE_COMMENTARY.md`.
Target output for the shader roadmap (Z17): `reference/glsl_golden.x3d`.
