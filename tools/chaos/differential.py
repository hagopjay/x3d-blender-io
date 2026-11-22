"""Differential chaos testing: mutate small X3D files, ask several independent judges, keep every disagreement.

Run with the bpy wheel's Python (it has bpy, x3d.py and saxonche) or inside Blender:

    python tools/chaos/differential.py --seeds tests/golden --per-seed 60 --out /tmp/chaos \
        [--rng 7] [--schematron-cache DIR] [--xsd DIR_WITH_x3d-4.0.xsd] [--no-schematron] [--fail-on-crash]

Each mutant is one seed file with one mutation (tools/chaos/mutations.py names them). Judges:

  own         the add-on's validator (source/validate.py: XML, element names, field values)
  x3dpy       Web3D's x3d.py package, strict field types (source/validate.py validate_with_x3d_py)
  xsd         the Web3D X3D 4.0 XML Schema through xmllint (only when --xsd is given)
  schematron  the Web3D X3D Schematron (tools/schematron, vendored and pinned)
  import      this add-on's importer in bpy: FINISHED, CANCELLED or the exception it raised
  reexport    the X3D 4.0 export of what the import built: ok or the exception

A row is interesting when the judges disagree (one says valid, another invalid), when the import raises on a file
every validator accepts (our bug), or when the export raises after a successful import (our bug). The summary groups
rows by signature (judge verdicts plus the exception's type and last frame), so a thousand mutants give a short list.
Mutants and logs stay under --out; nothing is written to the repository.
"""
from __future__ import annotations

import argparse
import contextlib
import faulthandler
import io
import json
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import traceback
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
# X3D_ADDON_SOURCE points the judges at another copy of source/ (tools/oracles/plant.py writes one with a planted fault)
SOURCE = Path(os.environ.get("X3D_ADDON_SOURCE", REPO / "source")).resolve()
sys.path.insert(0, str(SOURCE))
sys.path.insert(0, str(REPO / "tools" / "schematron"))

import mutations  # noqa: E402


def make_mutants(seeds: list[Path], per_seed: int, rng: random.Random, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for seed in seeds:
        text = seed.read_text(encoding="utf-8")
        made = 0
        tries = 0
        while made < per_seed and tries < per_seed * 6:
            tries += 1
            op = rng.choice(mutations.OPERATORS)
            result = op(text, rng)
            if result is None:
                continue
            mutated, what = result
            name = f"{seed.name.split('.')[0]}__{made:03d}__{op.__name__}.x3d"
            (out / name).write_text(mutated, encoding="utf-8")
            rows.append({"file": name, "seed": seed.name, "op": op.__name__, "what": what})
            made += 1
    return rows


def judge_own_and_x3dpy(path: Path) -> tuple[dict, dict]:
    import validate

    own = validate.validate_xml_file(str(path))
    try:
        x3dpy = validate.validate_with_x3d_py(str(path))
    except Exception as exc:  # the judge itself crashed: that is a finding about the judge
        return ({"valid": own.valid, "errors": own.errors[:3]},
                {"valid": None, "crash": f"{type(exc).__name__}: {exc}"[:300]})
    if x3dpy is None:
        x3dpy_row = {"valid": None, "errors": ["x3d.py not installed"]}
    else:
        x3dpy_row = {"valid": x3dpy.valid, "errors": x3dpy.errors[:3]}
    return {"valid": own.valid, "errors": own.errors[:3]}, x3dpy_row


def judge_xsd(paths: list[Path], xsd: Path) -> dict[str, dict]:
    verdicts: dict[str, dict] = {}
    for start in range(0, len(paths), 200):
        chunk = paths[start:start + 200]
        proc = subprocess.run(["xmllint", "--noout", "--nonet", "--schema", str(xsd), *map(str, chunk)],
                              capture_output=True, text=True)
        errors: dict[str, list[str]] = defaultdict(list)
        for line in proc.stderr.splitlines():
            m = re.match(r"(.+?\.x3d):(\d+): (.*)", line)
            if m:
                errors[Path(m.group(1)).name].append(m.group(3)[:200])
        for path in chunk:
            ok = f"{path} validates" in proc.stderr
            verdicts[path.name] = {"valid": ok, "errors": errors.get(path.name, [])[:3]}
    return verdicts


class ImportJudge:
    def __init__(self):
        import bpy

        self.bpy = bpy
        self.tmp = tempfile.mkdtemp(prefix="chaos-addon-")
        package = Path(self.tmp) / "io_scene_x3d"
        package.symlink_to(SOURCE, target_is_directory=True)
        sys.path.insert(0, self.tmp)
        import importlib

        module = importlib.import_module("io_scene_x3d")
        with contextlib.suppress(Exception):
            module.register()

    def run(self, path: Path, out_dir: Path) -> tuple[dict, dict]:
        bpy = self.bpy
        bpy.ops.wm.read_factory_settings(use_empty=True)
        sink = io.StringIO()
        t0 = time.time()
        faulthandler.dump_traceback_later(120, exit=True)   # a hang ends the run with a traceback, not silence
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = bpy.ops.import_scene.x3d(filepath=str(path))
            imp = {"result": sorted(result)[0] if result else "NONE", "objects": len(bpy.data.objects),
                   "seconds": round(time.time() - t0, 2)}
        except Exception as exc:
            imp = {"result": "EXCEPTION", "exception": _signature(exc), "message": str(exc)[-400:],
                   "seconds": round(time.time() - t0, 2)}
        finally:
            faulthandler.cancel_dump_traceback_later()
        if imp["result"] != "FINISHED":
            return imp, {"result": "SKIPPED"}
        target = out_dir / (path.stem + ".reexport.x3d")
        faulthandler.dump_traceback_later(120, exit=True)
        try:
            with contextlib.redirect_stdout(sink), contextlib.redirect_stderr(sink):
                result = bpy.ops.export_scene.x3d(filepath=str(target))
            exp = {"result": sorted(result)[0] if result else "NONE"}
        except Exception as exc:
            exp = {"result": "EXCEPTION", "exception": _signature(exc), "message": str(exc)[-400:]}
        finally:
            faulthandler.cancel_dump_traceback_later()
        return imp, exp


def _signature(exc: BaseException) -> str:
    """Exception type plus the deepest add-on frame: the same bug in two mutants gives one signature."""
    text = str(exc)
    # bpy.ops wraps the operator's exception in a RuntimeError whose text holds the inner traceback
    frames = re.findall(r'File "([^"]+)", line (\d+), in (\w+)', text)
    inner = re.findall(r"\n(\w+(?:Error|Exception|Warning)): ", text)
    if frames:
        own = [f for f in frames if "io_scene_x3d" in f[0] or "/source/" in f[0]] or frames
        f = own[-1]
        return f"{inner[-1] if inner else type(exc).__name__} at {Path(f[0]).name}:{f[1]} {f[2]}"
    tb = traceback.extract_tb(exc.__traceback__)
    last = tb[-1] if tb else None
    return f"{type(exc).__name__} at {Path(last.filename).name}:{last.lineno} {last.name}" if last else type(exc).__name__


def classify(row: dict) -> str:
    verdicts = {k: row[k]["valid"] for k in ("own", "x3dpy", "xsd", "schematron") if k in row and row[k]["valid"] is not None}
    imp, exp = row["import"]["result"], row["reexport"]["result"]
    if any("crash" in row.get(k, {}) for k in ("own", "x3dpy")):
        return "judge-crash"
    if exp == "EXCEPTION":
        return "reexport-crash"
    if imp == "EXCEPTION" and verdicts and all(verdicts.values()):
        return "import-crash-on-valid"
    if imp == "EXCEPTION":
        return "import-crash-on-invalid"
    if len(set(verdicts.values())) > 1:
        return "judges-disagree"
    return "agree"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", nargs="+", required=True)
    ap.add_argument("--per-seed", type=int, default=40)
    ap.add_argument("--rng", type=int, default=7)
    ap.add_argument("--out", required=True)
    ap.add_argument("--xsd", help="folder holding x3d-4.0.xsd (and its includes) for xmllint")
    ap.add_argument("--schematron-cache", default=str(REPO / ".cache" / "schematron"))
    ap.add_argument("--no-schematron", action="store_true")
    ap.add_argument("--no-import", action="store_true")
    ap.add_argument("--fail-on-crash", action="store_true",
                    help="exit 1 when the import, the re-export or a validator raised on any mutant")
    args = ap.parse_args(argv)

    out = Path(args.out)
    seeds = []
    for s in args.seeds:
        p = Path(s)
        seeds += sorted(p.glob("*.x3d")) if p.is_dir() else [p]
    rng = random.Random(args.rng)
    mutants_dir = out / "mutants"
    rows = make_mutants(seeds, args.per_seed, rng, mutants_dir)
    print(f"[chaos] {len(rows)} mutants from {len(seeds)} seeds, rng {args.rng}")
    paths = [mutants_dir / r["file"] for r in rows]

    t0 = time.time()
    for row, path in zip(rows, paths):
        row["own"], row["x3dpy"] = judge_own_and_x3dpy(path)
    print(f"[chaos] own validator and x3d.py: {time.time() - t0:.1f} s")

    if args.xsd:
        t0 = time.time()
        xsd = judge_xsd(paths, Path(args.xsd) / "x3d-4.0.xsd")
        for row in rows:
            row["xsd"] = xsd[row["file"]]
        print(f"[chaos] XSD: {time.time() - t0:.1f} s")

    if not args.no_schematron:
        from schematron import Judge

        judge = Judge(Path(args.schematron_cache))
        t0 = time.time()
        for row, path in zip(rows, paths):
            try:
                errs = [f for f in judge.check(path) if f["role"] == "error"]
                row["schematron"] = {"valid": not errs, "errors": [e["message"][:200] for e in errs[:3]]}
            except Exception as exc:
                row["schematron"] = {"valid": None, "errors": [f"judge failed: {type(exc).__name__}: {exc}"[:200]]}
        print(f"[chaos] Schematron: {time.time() - t0:.1f} s")

    if args.no_import:
        for row in rows:
            row["import"] = row["reexport"] = {"result": "SKIPPED"}
    else:
        judge = ImportJudge()
        reexport_dir = out / "reexport"
        reexport_dir.mkdir(exist_ok=True)
        t0 = time.time()
        for i, (row, path) in enumerate(zip(rows, paths)):
            row["import"], row["reexport"] = judge.run(path, reexport_dir)
            if i % 100 == 99:
                print(f"[chaos] imported {i + 1} of {len(rows)} ({time.time() - t0:.0f} s)")
        print(f"[chaos] import and re-export: {time.time() - t0:.1f} s")

    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        row["class"] = classify(row)
        verdict = "".join(
            ("." if row[k]["valid"] is None else ("V" if row[k]["valid"] else "x")) if k in row else "-"
            for k in ("own", "x3dpy", "xsd", "schematron"))
        sig = row["import"].get("exception") or row["reexport"].get("exception") or ""
        groups[(row["class"], verdict, row["op"], sig)].append(row)
    counts = Counter(r["class"] for r in rows)
    summary = {"mutants": len(rows), "seeds": [s.name for s in seeds], "rng": args.rng, "classes": dict(counts),
               "judges": "own x3dpy xsd schematron (V valid, x invalid, . no verdict, - not run)",
               "groups": [{"class": c, "verdicts": v, "op": op, "signature": sig, "count": len(rs),
                           "example": rs[0]["file"], "what": rs[0]["what"]}
                          for (c, v, op, sig), rs in sorted(groups.items(), key=lambda kv: (kv[0][0] == "agree", kv[0]))]}
    (out / "rows.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(f"[chaos] classes: {dict(counts)}")
    for g in summary["groups"]:
        if g["class"] != "agree":
            print(f"[chaos] {g['class']:24s} {g['verdicts']} {g['op']:18s} x{g['count']:<4d} {g['signature']}  e.g. {g['example']}")
    crashes = sum(n for c, n in counts.items() if "crash" in c)
    if args.fail_on_crash and crashes:
        print(f"[chaos] FAIL: {crashes} mutant(s) crashed a judge, the import or the re-export")
        return 1
    print(f"[chaos] {'PASS' if not crashes else 'done'}: {crashes} crash(es); disagreements are listed, not gated")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else None))
