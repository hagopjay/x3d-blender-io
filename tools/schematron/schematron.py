# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Structure judge: the Web3D Consortium's X3D Schematron on this add-on's exports, through SaxonC-HE (plain Python).

    pip install saxonche==13.1.1
    python tools/schematron/schematron.py FILE_OR_FOLDER [...] [--cache DIR] [--out report.json] [--gate]
    python tools/schematron/schematron.py --plants          # every tests/plants/schematron-*.x3d must give an error

The rules (X3dSchematronValidityChecks.sch, 3,303 assert/report statements, served by web3d.org with Last-Modified
21 Oct 2025) and the ISO Schematron skeleton (MIT licence) are vendored under tools/schematron/vendor/ and pinned by
sha256 in VENDOR below, so an upstream edit cannot turn CI red overnight; updating them is a pull request.

The .sch is compiled to XSLT 2.0 by the ISO skeleton (include, abstract expand, svrl for xslt2): about 93 MB, two
minutes of SaxonC-HE time, so the result is cached under --cache keyed by the vendored files' hashes. Two fixes make
it run on SaxonC-HE 13.1.1: predefined entity references in the compiled XSLT are rewritten as character references
(the JDK parser's 100,000-character entity limit, JAXP00010003, otherwise stops the compile), and each X3D file's
DOCTYPE is removed before parsing (the parser would fetch the DTD from web3d.org).

--gate fails (exit 1) on any finding with role "error" (or a failed assert without a role) that is not listed in
tools/schematron/disagreements.json. That file records where Schematron and the other judges (x3d.py 4.0.65.8 strict
validation, the export's own XSD-style checks, X_ITE drawing the file) disagree, names the judge suspected of being
wrong and why, and holds the count per message: a listed count may only shrink (v3 plan: "disagreements are fixtures
with a named suspect judge; only agreed errors block").
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
VENDOR = {
    "X3dSchematronValidityChecks.sch": "9e728c7a640e0745fca009d8334ab2693e090e3fc8410390f23dfa722a812b29",
    "iso_dsdl_include.xsl": "43ff20a1afd89d8a744d1c0b8df94ac5559ffa6a820d1ffbf508d6431ee4fdd9",
    "iso_abstract_expand.xsl": "c5267f124abf23eeb6669884e40a98607c055bfaa1f39e73b7d578feceeb6e46",
    "iso_svrl_for_xslt2.xsl": "0588d617924a0686255f6d182633d434c7986d561be8fcc3b363907d3f671b26",
    "iso_schematron_skeleton_for_saxon.xsl": "95f3195d9f437ea8ff5f75d1a27f4e68ae20b236fe0d4a217bb4209f498a10a3",
}
DISAGREEMENTS = HERE / "disagreements.json"
ENTITIES = (("&lt;", "&#60;"), ("&gt;", "&#62;"), ("&quot;", "&#34;"), ("&apos;", "&#39;"), ("&amp;", "&#38;"))
FINDING = re.compile(r"<svrl:(failed-assert|successful-report)([^>]*)>\s*<svrl:text>(.*?)</svrl:text>", re.S)


def vendor_key() -> str:
    h = hashlib.sha256()
    for name, pinned in sorted(VENDOR.items()):
        data = (HERE / "vendor" / name).read_bytes()
        actual = hashlib.sha256(data).hexdigest()
        if actual != pinned:
            raise SystemExit(f"[schematron] vendor/{name} has sha256 {actual}, pinned {pinned}: update VENDOR with the file")
        h.update(actual.encode())
    return h.hexdigest()[:16]


def compiled_xslt(proc, cache: Path) -> Path:
    key = vendor_key()
    target = cache / f"x3d-schematron-{key}.xsl"
    if target.exists():
        print(f"[schematron] compiled rules from cache {target.name} ({target.stat().st_size:,} bytes)")
        return target
    cache.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    xslt = proc.new_xslt30_processor()
    vendor = HERE / "vendor"
    step1 = xslt.transform_to_string(source_file=str(vendor / "X3dSchematronValidityChecks.sch"),
                                     stylesheet_file=str(vendor / "iso_dsdl_include.xsl"))
    s1 = cache / "step1.sch"
    s1.write_text(step1, encoding="utf-8")
    step2 = xslt.transform_to_string(source_file=str(s1), stylesheet_file=str(vendor / "iso_abstract_expand.xsl"))
    s2 = cache / "step2.sch"
    s2.write_text(step2, encoding="utf-8")
    step3 = xslt.transform_to_string(source_file=str(s2), stylesheet_file=str(vendor / "iso_svrl_for_xslt2.xsl"))
    for a, b in ENTITIES:
        step3 = step3.replace(a, b)
    target.write_text(step3, encoding="utf-8")
    s1.unlink()
    s2.unlink()
    print(f"[schematron] compiled the rules in {time.time() - t0:.1f} s ({len(step3):,} bytes) -> {target}")
    return target


def _unescape(text: str) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    for a, b in (("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&apos;", "'"), ("&amp;", "&")):
        text = text.replace(a, b)
    return text


def template(text: str) -> str:
    """A message with its quoted values replaced by '…', so one rule's findings group together."""
    return re.sub(r"(['\"])[^'\"]*\1", "…", text)[:160]


def parse_svrl(svrl: str) -> list[dict]:
    findings = []
    for kind, attrs, text in FINDING.findall(svrl):
        role = re.search(r'role="([^"]*)"', attrs)
        location = re.search(r'location="([^"]*)"', attrs)
        message = _unescape(text)
        findings.append({"kind": kind, "role": (role.group(1) if role else ("error" if kind == "failed-assert" else
                                                                              "report")),
                         "message": message, "template": template(message),
                         "location": location.group(1) if location else None})
    return findings


class Judge:
    def __init__(self, cache: Path):
        from saxonche import PySaxonProcessor

        self._proc_cm = PySaxonProcessor(license=False)
        self.proc = self._proc_cm.__enter__()
        path = compiled_xslt(self.proc, cache)
        t0 = time.time()
        self.executable = self.proc.new_xslt30_processor().compile_stylesheet(stylesheet_file=str(path))
        self.compile_seconds = round(time.time() - t0, 1)
        print(f"[schematron] loaded the rules in {self.compile_seconds} s (SaxonC-HE {self.proc.version})")

    def check(self, path: Path) -> list[dict]:
        text = path.read_text(encoding="utf-8")
        text = re.sub(r"<!DOCTYPE[^>]*>", "", text, count=1)   # the parser would fetch the DTD from web3d.org
        node = self.proc.parse_xml(xml_text=text)
        return parse_svrl(self.executable.transform_to_string(xdm_node=node))


def files_of(args) -> list[Path]:
    files = []
    for arg in args:
        p = Path(arg)
        files += sorted(p.glob("*.x3d")) if p.is_dir() else [p]
    return files


def gate(results: dict[str, list[dict]], known: dict) -> tuple[list[str], list[str]]:
    """(failures, tightened): errors not listed or above their listed count; listed ones that shrank."""
    failures, tightened = [], []
    listed = {(d["profile"], d["template"]): d for d in known.get("disagreements", [])}
    for name, findings in results.items():
        profile = profile_of(name)
        counts = Counter(f["template"] for f in findings if f["role"] in ("error", "fatal"))
        for tmpl, count in sorted(counts.items()):
            entry = listed.get((profile, tmpl))
            if entry is None:
                example = next(f for f in findings if f["template"] == tmpl)
                failures.append(f"{name}: {count} x error not explained by disagreements.json: {example['message'][:200]} "
                                f"at {example['location']}")
            elif count > entry["count"]:
                failures.append(f"{name}: {count} x '{tmpl[:90]}', disagreements.json allows {entry['count']}")
            elif count < entry["count"]:
                tightened.append(f"{name}: '{tmpl[:90]}' fell from {entry['count']} to {count}; lower it in disagreements.json")
        for (p, tmpl), entry in listed.items():
            if p == profile and tmpl not in counts:
                tightened.append(f"{name}: '{tmpl[:90]}' no longer occurs; remove it from disagreements.json")
    return failures, tightened


def profile_of(name: str) -> str:
    stem = Path(name).stem
    return stem[len("x3d_suite_"):] if stem.startswith("x3d_suite_") else stem


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("paths", nargs="*")
    p.add_argument("--cache", default=os.environ.get("SCHEMATRON_CACHE", str(REPO / ".cache" / "schematron")))
    p.add_argument("--out", default="")
    p.add_argument("--gate", action="store_true")
    p.add_argument("--plants", action="store_true", help="check that every planted fault gives at least one error")
    args = p.parse_args(argv)
    judge = Judge(Path(args.cache))
    status = 0
    report = {"schema": "x3d-blender-io.schematron/1", "rules_sha256": VENDOR["X3dSchematronValidityChecks.sch"],
              "saxon": judge.proc.version, "files": {}}
    if args.plants:
        plants = sorted((REPO / "tests" / "plants").glob("schematron-*.x3d"))
        caught = 0
        for plant in plants:
            findings = judge.check(plant)
            errors = [f for f in findings if f["role"] in ("error", "fatal")]
            expect = plant.read_text(encoding="utf-8").split("EXPECT:", 1)[-1].split("-->", 1)[0].strip()
            hit = [f for f in errors if expect and expect in f["message"]]
            ok = bool(hit)
            caught += ok
            print(f"[schematron] plant {plant.name}: {len(errors)} error(s); expects '{expect}': "
                  f"{'CAUGHT' if ok else 'MISSED'}")
            if not ok:
                for f in errors[:5]:
                    print(f"    {f['message'][:200]}")
            report["files"][plant.name] = findings
        print(f"[schematron] planted faults caught: {caught} of {len(plants)}")
        status = 0 if plants and caught == len(plants) else 1
    for path in files_of(args.paths):
        t0 = time.time()
        findings = judge.check(path)
        report["files"][path.name] = findings
        roles = Counter(f["role"] for f in findings)
        print(f"[schematron] {path.name}: {dict(sorted(roles.items()))} in {time.time() - t0:.1f} s")
    if args.gate and args.paths:
        known = json.loads(DISAGREEMENTS.read_text()) if DISAGREEMENTS.exists() else {}
        results = {k: v for k, v in report["files"].items() if not k.startswith("schematron-")}
        failures, tightened = gate(results, known)
        for t in tightened:
            print(f"[schematron] tighten: {t}")
        for f in failures:
            print(f"[schematron] FAIL {f}")
        report["gate"] = {"failures": failures, "tightened": tightened}
        print(f"[schematron] gate: {len(failures)} unexplained error group(s); {'FAIL' if failures else 'PASS'}")
        status = status or (1 if failures else 0)
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    sys.stdout.flush()
    return status


if __name__ == "__main__":
    code = main(sys.argv[1:])
    os._exit(code)   # SaxonC's native runtime can stall at interpreter exit
