# SPDX-License-Identifier: GPL-3.0-or-later
"""Branch coverage of source/ for the whole test suite, measured inside Blender.

    blender -b --factory-startup -noaudio --python tools/coverage_in_blender.py -- OUT_DIR [test_module ...]

Needs coverage.py importable by Blender's Python; point COVERAGE_SITE at a folder made with
``<blender python> -m pip install --target FOLDER coverage x3d`` to keep Blender's own install untouched.

Writes to OUT_DIR: ``.coverage`` (data), ``report.txt`` (per module, missing lines), ``coverage.json``,
``table.md`` (module, statements, missed, line+branch %, branch %, and the three functions with the most missed
lines) and ``tests.log``. The tests expose source/ as ``<tmp>/io_scene_x3d`` through a symlink; coverage.py records
real paths, so code run through the registered add-on is counted against source/.
"""
from __future__ import annotations

import ast
import json
import os
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
if not argv:
    sys.exit(__doc__)
out = Path(argv[0]).resolve()
names = argv[1:]
out.mkdir(parents=True, exist_ok=True)
if os.environ.get("COVERAGE_SITE"):
    sys.path.insert(0, os.environ["COVERAGE_SITE"])

import coverage  # noqa: E402

cov = coverage.Coverage(branch=True, source=[str(REPO / "source")], data_file=str(out / ".coverage"))
cov.start()
import bpy  # noqa: E402

sys.path.insert(0, str(REPO / "tests"))
loader = unittest.defaultTestLoader
if names:
    suite = loader.loadTestsFromNames(names)
else:
    suite = unittest.TestSuite(loader.loadTestsFromName(path.stem) for path in sorted((REPO / "tests").glob("test_*.py")))
with open(out / "tests.log", "w") as log:
    result = unittest.TextTestRunner(verbosity=1, stream=log).run(suite)
cov.stop()
cov.save()
with open(out / "report.txt", "w") as handle:
    cov.report(file=handle, show_missing=True, skip_empty=True)
cov.json_report(outfile=str(out / "coverage.json"))

data = json.loads((out / "coverage.json").read_text())
rows = ["| module | stmts | miss | line+branch % | branch % (of) | most missed lines: function:line(n) |",
        "|---|---:|---:|---:|---:|---|"]
for path, item in sorted(data["files"].items()):
    summary = item["summary"]
    missing = set(item["missing_lines"])
    functions = []
    for node in ast.walk(ast.parse(Path(path).read_text())):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            count = sum(1 for line in range(node.lineno, node.end_lineno + 1) if line in missing)
            if count:
                functions.append((count, node.name, node.lineno))
    hot = ", ".join(f"{name}:{line}({count})" for count, name, line in sorted(functions, reverse=True)[:3])
    branches = summary["num_branches"]
    branch = 100.0 * summary["covered_branches"] / branches if branches else 100.0
    rows.append(f"| {Path(path).name} | {summary['num_statements']} | {summary['missing_lines']} | "
                f"{summary['percent_covered']:.0f} | {branch:.0f}% ({branches}) | {hot} |")
totals = data["totals"]
rows.append(f"| **total** | {totals['num_statements']} | {totals['missing_lines']} | {totals['percent_covered']:.1f} | "
            f"{100.0 * totals['covered_branches'] / totals['num_branches']:.1f}% ({totals['num_branches']}) | |")
instrument = (f"Blender {bpy.app.version_string}, Python {sys.version.split()[0]}, coverage.py {coverage.__version__}; "
              f"{result.testsRun} tests, {len(result.failures)} failures, {len(result.errors)} errors, "
              f"{len(result.skipped)} skipped")
(out / "table.md").write_text(instrument + "\n\n" + "\n".join(rows) + "\n")
print(instrument)
sys.exit(0)
