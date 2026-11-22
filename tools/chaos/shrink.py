"""Shrink a crashing X3D file to a small one that still crashes the same way.

A chaos round hands over files that crash; a bug report needs the smallest file that shows the bug. This takes one
X3D XML file, runs the add-on's import (and re-export) in bpy, records the crash signature (the exception's type and
the last frame of the add-on, as differential.py prints it), then removes what it can while the signature stays the
same:

  1. whole elements, outermost first (a removed Transform takes its subtree with it);
  2. attributes;
  3. half of a value's tokens, then a quarter, and so on (a 4,000-number point list down to the numbers that matter).

It repeats until nothing more can go, so every element, attribute and token left is needed for the crash. Run with
the bpy wheel's Python or inside Blender:

    python tools/chaos/shrink.py CRASHING.x3d --out DIR [--max-tests 2000]

It writes DIR/<name>.min.x3d and prints the signature, the size before and after, and the number of imports it ran.
"""
from __future__ import annotations

import argparse
import copy
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

KEEP = {"X3D", "Scene", "head"}


def _signature_of(judge, path: Path, out: Path) -> str | None:
    """The crash signature of ``path``, or None when it imports and re-exports without one."""
    imp, exp = judge.run(path, out)
    if imp.get("result") == "EXCEPTION":
        return "import: " + imp.get("exception", "?")
    if exp.get("result") == "EXCEPTION":
        return "reexport: " + exp.get("exception", "?")
    return None


class Shrinker:
    def __init__(self, judge, out: Path, target: str, max_tests: int):
        self.judge, self.out, self.target, self.max_tests = judge, out, target, max_tests
        self.tests = 0
        self.probe = out / "shrink-probe.x3d"

    def still_crashes(self, root: ET.Element) -> bool:
        if self.tests >= self.max_tests:
            return False
        self.tests += 1
        ET.ElementTree(root).write(self.probe, encoding="unicode", xml_declaration=True)
        return _signature_of(self.judge, self.probe, self.out) == self.target

    def _parents(self, root):
        return {child: parent for parent in root.iter() for child in parent}

    def pass_elements(self, root) -> bool:
        changed = False
        parents = self._parents(root)
        for elem in list(root.iter()):          # document order: outer elements are tried before their children
            if elem.tag in KEEP or elem not in parents:
                continue
            parent = parents[elem]
            if elem not in list(parent):         # already gone with an ancestor
                continue
            index = list(parent).index(elem)
            parent.remove(elem)
            if self.still_crashes(root):
                changed = True
            else:
                parent.insert(index, elem)
        return changed

    def pass_attributes(self, root) -> bool:
        changed = False
        for elem in root.iter():
            if elem.tag in ("X3D",):
                continue
            for name in list(elem.attrib):
                value = elem.attrib.pop(name)
                if self.still_crashes(root):
                    changed = True
                else:
                    elem.attrib[name] = value
        return changed

    def pass_tokens(self, root) -> bool:
        changed = False
        for elem in root.iter():
            for name, value in list(elem.attrib.items()):
                tokens = value.split()
                chunk = len(tokens) // 2
                while chunk >= 1 and len(tokens) > 1:
                    start, shrunk = 0, False
                    while start < len(tokens):
                        trial = tokens[:start] + tokens[start + chunk:]
                        if trial:
                            elem.attrib[name] = " ".join(trial)
                            if self.still_crashes(root):
                                tokens, shrunk, changed = trial, True, True
                                continue
                        start += chunk
                    elem.attrib[name] = " ".join(tokens)
                    if not shrunk:
                        chunk //= 2
        return changed

    def run(self, root) -> ET.Element:
        while self.tests < self.max_tests:
            changed = self.pass_elements(root)
            changed |= self.pass_attributes(root)
            changed |= self.pass_tokens(root)
            if not changed:
                break
        return root


def shrink_file(judge, path: Path, out: Path, max_tests: int = 2000) -> dict:
    """Shrink ``path``; returns {signature, before, after, tests, path} (path None when it does not crash)."""
    out.mkdir(parents=True, exist_ok=True)
    target = _signature_of(judge, path, out)
    before = path.stat().st_size
    if target is None:
        return {"signature": None, "before": before, "after": before, "tests": 1, "path": None}
    root = ET.parse(path).getroot()
    shrinker = Shrinker(judge, out, target, max_tests)
    small = shrinker.run(copy.deepcopy(root))
    result = out / (path.stem + ".min.x3d")
    ET.ElementTree(small).write(result, encoding="unicode", xml_declaration=True)
    shrinker.probe.unlink(missing_ok=True)
    confirmed = _signature_of(judge, result, out) == target
    return {"signature": target, "before": before, "after": result.stat().st_size, "tests": shrinker.tests + 2,
            "path": str(result), "confirmed": confirmed}


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("file", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--max-tests", type=int, default=2000)
    args = parser.parse_args(argv)
    from differential import ImportJudge

    result = shrink_file(ImportJudge(), args.file, args.out, args.max_tests)
    if result["signature"] is None:
        print(f"[shrink] {args.file.name} does not crash; nothing to shrink")
        return 1
    print(f"[shrink] {result['signature']}")
    print(f"[shrink] {result['before']} -> {result['after']} bytes in {result['tests']} imports; "
          f"{'same signature' if result['confirmed'] else 'SIGNATURE CHANGED'}: {result['path']}")
    return 0 if result["confirmed"] else 1


if __name__ == "__main__":
    sys.exit(main())
