# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board: every concrete X3D 4.0 node on one table, with the rungs it stands on, measured.

The denominator is the X3D Unified Object Model 4.0 (X3DUOM): its concrete nodes, per component. Rungs per node:

  read      the importer does something with the node in a real Blender run: ``builds`` (new Blender data), ``carries``
            (the node or its fields kept as custom properties or text, so a re-export can write them back), or ``none``
            (the node vanishes). Measured by tools/node_board_probe.py (differential: the same file with and without the
            node), not read from the importer's source.
  written   the exporter wrote the element in a run: an export of a Blender scene, or the behaviour graph's emitter, and
            the file validated against x3d-4.0.xsd. ``writable`` is the weaker rung: the emitter's source names the element
            but no run observed it (Suspected).
  class     the round-trip class of tools/io_sync/parity.json (``unmeasured`` for a node written but not in the fixed-point corpus).
  event     for the 57 event nodes, the rungs of tools/behaviour_coverage.py (wired / simulated / judged / played).
  seen      how often the element occurs in the project's own X3D files (tools/node_board_frequency.json).

``--write`` regenerates docs/NODE_BOARD.md between its markers; ``--check`` exits 1 when it is stale. Inputs are committed so
a checkout without X3DUOM, Blender or the sibling repositories can still check: ``tools/node_board_nodes.json`` (made by
``--regenerate X3DUOM``), ``tools/node_board_frequency.json`` (``--frequency REPO_DIR...``) and
``tools/node_board_measured.json`` (made by tools/node_board_probe.py inside Blender). ::

    python tools/node_board.py --markdown | --json | --write | --check
    python tools/node_board.py --regenerate X3dUnifiedObjectModel-4.0.xml
    python tools/node_board.py --frequency /path/to/repoA:docs/demos /path/to/repoB
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

NODES_JSON = ROOT / "tools" / "node_board_nodes.json"
FREQ_JSON = ROOT / "tools" / "node_board_frequency.json"
MEASURED_JSON = ROOT / "tools" / "node_board_measured.json"
MAPPING_JSON = ROOT / "mapping" / "x3d_fields.json"
PARITY_JSON = ROOT / "tools" / "io_sync" / "parity.json"
DOC = ROOT / "docs" / "NODE_BOARD.md"
BEGIN, END = "<!-- board:begin", "<!-- board:end -->"
STATEMENTS = {"X3D", "head", "component", "meta", "Scene", "ROUTE", "unit", "field", "fieldValue", "IS", "connect",
              "ProtoDeclare", "ProtoInterface", "ProtoBody", "ExternProtoDeclare", "IMPORT", "EXPORT", "ProtoInstance"}

# HAND-KEPT. The cost of supporting a node well, 1 (Blender already holds the thing) to 5 (a subsystem Blender lacks), by
# component, with per-node exceptions. Used only to rank gaps: score = files that contain the node / cost.
COST_BY_COMPONENT = {
    "Shape": 2, "Grouping": 2, "Geometry3D": 2, "Geometry2D": 2, "Rendering": 2, "Texturing": 2, "Lighting": 2, "Core": 2,
    "Interpolation": 2, "Text": 2, "Time": 2, "EnvironmentalEffects": 2, "PointingDeviceSensor": 2, "Navigation": 3,
    "HAnim": 3, "EventUtilities": 3, "Followers": 3, "Picking": 3, "Networking": 3, "CubeMapTexturing": 3, "CADGeometry": 3,
    "EnvironmentalSensor": 3, "KeyDeviceSensor": 3, "RigidBodyPhysics": 4, "Geospatial": 4, "Sound": 4, "NURBS": 4,
    "Layout": 4, "Layering": 4, "Scripting": 4, "Texturing3D": 4, "TextureProjection": 4, "Shaders": 5,
    "ParticleSystems": 5, "VolumeRendering": 5, "DIS": 5,
}
COST_EXCEPTIONS = {"Billboard": 4, "Switch": 2, "LOD": 2, "Anchor": 3, "FontStyle": 2, "ScalarInterpolator": 1,
                   "ColorInterpolator": 1, "Extrusion": 2, "IndexedTriangleSet": 2, "LineSet": 2, "MetadataString": 2,
                   "MetadataDouble": 2, "MetadataInteger": 2, "MetadataFloat": 2, "MetadataBoolean": 2, "Fog": 2,
                   "ElevationGrid": 2, "Disk2D": 2, "Arc2D": 2, "ArcClose2D": 2, "Polyline2D": 2, "Polypoint2D": 2,
                   "PixelTexture": 2, "ProtoInstance": 5, "TextureCoordinate3D": 3, "NormalInterpolator": 2}


def cost_of(name, component):
    return COST_EXCEPTIONS.get(name, COST_BY_COMPONENT.get(component, 3))


# ---------------------------------------------------------------------------------------------------------------
# The denominator
# ---------------------------------------------------------------------------------------------------------------

def nodes_from_x3duom(path):
    data = Path(path).read_bytes()
    root = ET.fromstring(data)
    abstract = {}
    for tag in ("AbstractNodeType", "AbstractObjectType"):
        for node in root.iter(tag):
            bases = [c.get("baseType") for c in node.iter() if c.tag in ("Inheritance", "AdditionalInheritance")]
            abstract[node.get("name")] = bases

    def ancestors(bases):
        out, todo = [], list(bases)
        while todo:
            b = todo.pop(0)
            if b not in out:
                out.append(b)
                todo += abstract.get(b, [])
        return out

    nodes = {}
    for node in root.iter("ConcreteNode"):
        definition = node.find("InterfaceDefinition")
        info = definition.find("componentInfo")
        direct = [c.get("baseType") for c in definition if c.tag in ("Inheritance", "AdditionalInheritance")]
        children = []
        fields = 0
        for f in definition.findall("field"):
            if f.get("inheritedFrom") in ("X3DNode",) or f.get("name") in ("IS", "metadata"):
                continue
            if f.get("accessType") in ("inputOnly", "outputOnly"):
                continue
            fields += 1
            if f.get("type") in ("SFNode", "MFNode") and f.get("acceptableNodeTypes"):
                children.append([f.get("name"), f.get("acceptableNodeTypes").split("|")])
        nodes[node.get("name")] = {"component": info.get("name"), "level": int(info.get("level")),
                                   "bases": ancestors(direct), "fields": fields, "accepts": children}
    return {"x3duom_sha256": hashlib.sha256(data).hexdigest(), "x3duom_version": root.get("version"),
            "nodes": dict(sorted(nodes.items()))}


def load_nodes():
    return json.loads(NODES_JSON.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------------------------------------------
# Frequency
# ---------------------------------------------------------------------------------------------------------------

def frequency_from_repos(repos):
    """Count element names over ``git ls-files '*.x3d'`` of each repository (vendor/ and node_modules/ skipped)."""
    counts, files_with, files, unparsed, instrument = Counter(), Counter(), 0, 0, {}
    for repo in repos:
        repo, _, prefix = str(repo).partition(":")        # REPO or REPO:subfolder (only files under it count)
        repo = Path(repo)
        listing = subprocess.run(["git", "ls-files", "*.x3d"], cwd=repo, capture_output=True, text=True, check=True)
        head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, capture_output=True, text=True).stdout.strip()
        n = 0
        for rel in listing.stdout.splitlines():
            if not rel or not rel.startswith(prefix) or "/vendor/" in "/" + rel or "node_modules" in rel:
                continue
            try:
                root = ET.parse(repo / rel).getroot()
            except Exception:
                unparsed += 1
                continue
            n += 1
            seen = set()
            for el in root.iter():
                if isinstance(el.tag, str):
                    tag = el.tag.split("}")[-1]
                    counts[tag] += 1
                    seen.add(tag)
            files_with.update(seen)
        files += n
        instrument[repo.name] = {"commit": head, "files": n}
    return {"instrument": "git ls-files '*.x3d' then xml.etree element counts, vendor/ and node_modules/ skipped",
            "repositories": instrument, "files": files, "unparseable": unparsed,
            "elements": dict(sorted(counts.items())), "files_with": dict(sorted(files_with.items()))}


# ---------------------------------------------------------------------------------------------------------------
# The board
# ---------------------------------------------------------------------------------------------------------------

def board():
    uom = load_nodes()
    freq = json.loads(FREQ_JSON.read_text(encoding="utf-8"))
    measured = json.loads(MEASURED_JSON.read_text(encoding="utf-8"))
    mapping = json.loads(MAPPING_JSON.read_text(encoding="utf-8"))
    parity = json.loads(PARITY_JSON.read_text(encoding="utf-8"))["nodes"]
    import behaviour_coverage as cov
    events = {row["node"]: row for row in cov.coverage()["rows"]}
    rows = []
    for name, info in uom["nodes"].items():
        m = measured["nodes"].get(name, {})
        read = m.get("read", "unprobed")
        written = m.get("written", "no")            # observed | writable | no
        par = parity.get(name, {}).get("round_trip")
        in_corpus = mapping["nodes"].get(name, {}).get("export") == "written"
        if written == "observed":
            klass = par or "unmeasured"
        elif read in ("builds", "carries"):
            klass = "import_only"
        else:
            klass = "not_supported"
        ev = events.get(name)
        rows.append({"node": name, "component": info["component"], "level": info["level"], "read": read,
                     "read_evidence": m.get("read_evidence", ""), "written": written, "written_by": m.get("written_by", []),
                     "corpus": in_corpus, "class": klass, "seen": freq["elements"].get(name, 0),
                     "seen_files": freq["files_with"].get(name, 0),
                     "event": None if ev is None else {k: ev[k] for k in ("wired", "simulated", "judged", "played")}})
    return {"rows": rows, "uom": uom, "freq": freq, "measured": measured, "mapping": mapping}


def summary(data):
    rows = data["rows"]
    s = {"nodes": len(rows)}
    s["read_builds"] = sum(r["read"] == "builds" for r in rows)
    s["read_carries"] = sum(r["read"] == "carries" for r in rows)
    s["read_graph"] = sum(r["read"] == "graph" for r in rows)
    s["read_reported"] = sum(r["read"] == "reported" for r in rows)
    s["read_structural"] = sum(r["read"] == "structural" for r in rows)
    s["read_unprobed"] = sum(r["read"] == "unprobed" for r in rows)
    s["read_none"] = sum(r["read"] == "none" for r in rows)
    s["written"] = sum(r["written"] == "observed" for r in rows)
    s["writable"] = sum(r["written"] == "writable" for r in rows)
    s["round_trip"] = dict(sorted(Counter(r["class"] for r in rows).items()))
    events = [r for r in rows if r["event"]]
    s["events"] = len(events)
    for key in ("wired", "simulated", "judged", "played"):
        s[f"event_{key}"] = sum(r["event"][key] for r in events)
    return s


def by_component(data):
    out = {}
    for r in data["rows"]:
        c = out.setdefault(r["component"], {"nodes": 0, "builds": 0, "structural": 0, "carries": 0, "none": 0, "written": 0, "seen": 0})
        c["nodes"] += 1
        c[r["read"] if r["read"] in ("builds", "carries", "structural", "none") else "none"] += 1
        c["written"] += r["written"] == "observed"
        c["seen"] += r["seen"]
    return dict(sorted(out.items(), key=lambda kv: (-kv[1]["nodes"], kv[0])))


def gaps(data):
    """The uncovered nodes (not written), ranked by how often they occur times how cheap they are: frequency / cost."""
    out = []
    for r in data["rows"]:
        if r["written"] == "observed":
            continue
        cost = cost_of(r["node"], r["component"])
        out.append({"node": r["node"], "component": r["component"], "seen": r["seen"], "files": r["seen_files"],
                    "cost": cost, "score": round(r["seen_files"] / cost, 1), "read": r["read"]})
    out.sort(key=lambda g: (-g["score"], -g["seen"], g["node"]))
    return out


BASELINE_JSON = ROOT / "tools" / "node_board_measured_607fd01.json"      # the board before batch 1 (add-on 2.8.0)


def moves(data):
    """Nodes whose read or written rung differs from the 2.8.0 baseline, with their rank among the gaps then."""
    base = json.loads(BASELINE_JSON.read_text(encoding="utf-8"))["nodes"]
    before = dict(data)
    before["measured"] = {"nodes": base}
    before["rows"] = [dict(r, read=base[r["node"]]["read"], written=base[r["node"]]["written"]) for r in data["rows"]]
    rank = {g["node"]: i for i, g in enumerate(gaps(before), 1)}
    out = []
    for r in data["rows"]:
        b = base[r["node"]]
        if (b["read"], b["written"]) != (r["read"], r["written"]):
            out.append({"node": r["node"], "component": r["component"], "files": r["seen_files"], "rank": rank.get(r["node"]),
                        "read": (b["read"], r["read"]), "written": (b["written"], r["written"])})
    out.sort(key=lambda m: (m["rank"] is None, m["rank"] or 0, m["node"]))
    return out


def _mark(flag):
    return "yes" if flag else "-"


def markdown(data=None, top=30):
    data = data or board()
    s = summary(data)
    uom, freq, measured = data["uom"], data["freq"], data["measured"]
    lines = [
        f"{s['nodes']} concrete X3D 4.0 nodes (X3DUOM {uom['x3duom_version']}, sha256 `{uom['x3duom_sha256'][:12]}`). "
        f"**Read**: {s['read_builds']} build Blender data, {s['read_graph']} go to the behaviour graph, {s['read_carries']} are "
        f"carried, {s['read_structural']} are grouping nodes that dissolve into their children, {s['read_reported']} are dropped "
        f"with a report line, {s['read_none']} leave no trace, {s['read_unprobed']} unprobed. "
        f"**Written**: {s['written']} observed in a validated export run, {s['writable']} more named by the emitter but not "
        f"observed. Event nodes: {s['events']} ({s['event_wired']} wired, {s['event_simulated']} simulated, "
        f"{s['event_judged']} judged, {s['event_played']} played).",
        "",
        f"Instruments: read and written are `tools/node_board_probe.py` on Blender {measured['instrument']['blender']} "
        f"(`tools/node_board_measured.json`); validation is {measured['instrument']['validator']}; round-trip class is "
        "`tools/io_sync/parity.json` (`unmeasured`: written, but not in the fixed-point corpus); frequency is "
        f"`tools/node_board_frequency.json` ({freq['files']} files: "
        + ", ".join(f"{k} {v['files']} at `{v['commit']}`" for k, v in freq["repositories"].items()) + ").",
        "",
        "| round-trip class | nodes |", "|---|---:|",
    ]
    for k, v in s["round_trip"].items():
        lines.append(f"| {k} | {v} |")
    lines += ["", "| component | nodes | read: builds | carries | none | written | seen in files |", "|---|---:|---:|---:|---:|---:|---:|"]
    totals = Counter()
    for comp, c in by_component(data).items():
        lines.append(f"| {comp} | {c['nodes']} | {c['builds']} | {c['carries']} | {c['none']} | {c['written']} | {c['seen']} |")
        totals.update(c)
    lines.append(f"| **all** | {totals['nodes']} | {totals['builds']} | {totals['carries']} | {totals['none']} | "
                 f"{totals['written']} | {totals['seen']} |")
    ranked = gaps(data)
    extra = sorted(set(data["mapping"]["nodes"]) - set(uom["nodes"]))
    lines += ["", "### 268 against 260", "",
              f"docs/MAPPING.md counts {len(data['mapping']['nodes'])} nodes because x3d.py "
              f"{data['mapping']['instruments']['x3d.py']} declares {len(extra)} classes that X3DUOM 4.0 has no concrete node for "
              f"({', '.join(extra)}): X3D is the document's root element (a statement in the object model; x3d.py derives it "
              "from the node base), and the other seven are X3D 4.1 or Web3D extension nodes that x3d.py already carries. "
              f"Every one of the {len(uom['nodes'])} concrete nodes of the object model is in x3d.py, none is missing. This board "
              "counts the object model's 260 because the standard, not a Python binding, is the denominator; the "
              "extras are listed in docs/MAPPING.md.", ""]
    lines += [f"### The first {top} gaps, ranked", "",
              "Score is the number of the project's X3D files that contain the node, divided by cost (1 cheap to 5 a subsystem; "
              "hand-kept in `tools/node_board.py`, `COST_BY_COMPONENT` and `COST_EXCEPTIONS`); occurrences break ties. "
              "A gap is a node not yet written. Files, not occurrences, because a few generated files hold most of the "
              "occurrences of some nodes (FloatVertexAttribute: 11493 in 35 files).", "",
              "| # | node | component | occurrences | files | cost | score | read |", "|---:|---|---|---:|---:|---:|---:|---|"]
    for i, g in enumerate(ranked[:top], 1):
        lines.append(f"| {i} | {g['node']} | {g['component']} | {g['seen']} | {g['files']} | {g['cost']} | {g['score']} | {g['read']} |")
    if BASELINE_JSON.is_file():
        lines += ["", "### Moved since 2.8.0 (607fd01)", "",
                  "Rung changes against `tools/node_board_measured_607fd01.json`, with the node's rank among the gaps at "
                  "607fd01. A node's *written* rung moves only when a run of the exporter wrote it and the file validated.", "",
                  "| node | component | files | rank at 2.8.0 | read | written |", "|---|---|---:|---:|---|---|"]
        for m in moves(data):
            lines.append(f"| {m['node']} | {m['component']} | {m['files']} | {m['rank'] or '-'} | "
                         f"{m['read'][0]} to {m['read'][1] if m['read'][0] != m['read'][1] else 'same'} | "
                         f"{m['written'][0]} to {m['written'][1] if m['written'][0] != m['written'][1] else 'same'} |")
    lines += ["", "### Every node", "",
              "| node | component | read | written | class | seen | event rungs (wired/sim/judged/played) |",
              "|---|---|---|---|---|---:|---|"]
    for r in sorted(data["rows"], key=lambda r: (r["component"], r["node"])):
        ev = "-" if not r["event"] else "/".join(_mark(r["event"][k]) for k in ("wired", "simulated", "judged", "played"))
        lines.append(f"| {r['node']} | {r['component']} | {r['read']} | {r['written']} | {r['class']} | {r['seen']} | {ev} |")
    return "\n".join(lines) + "\n"


def written(doc_text, table):
    start = doc_text.index(BEGIN)
    start = doc_text.index("\n", start) + 1
    end = doc_text.index(END)
    return doc_text[:start] + table + doc_text[end:]


def is_stale(doc=DOC):
    text = Path(doc).read_text(encoding="utf-8")
    return written(text, markdown()) != text


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--markdown", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--write", action="store_true", help="replace the table between the markers in docs/NODE_BOARD.md")
    p.add_argument("--check", action="store_true", help="exit 1 when docs/NODE_BOARD.md is stale")
    p.add_argument("--regenerate", metavar="X3DUOM")
    p.add_argument("--frequency", nargs="+", metavar="REPO")
    args = p.parse_args(argv)
    if args.regenerate:
        NODES_JSON.write_text(json.dumps(nodes_from_x3duom(args.regenerate), indent=0, separators=(",", ":")) + "\n", encoding="utf-8")
        print(f"wrote {NODES_JSON}")
        return 0
    if args.frequency:
        FREQ_JSON.write_text(json.dumps(frequency_from_repos(args.frequency), indent=1) + "\n", encoding="utf-8")
        print(f"wrote {FREQ_JSON}")
        return 0
    if args.write:
        DOC.write_text(written(DOC.read_text(encoding="utf-8"), markdown()), encoding="utf-8")
        print(f"wrote the board into {DOC}")
        return 0
    if args.check:
        stale = is_stale()
        print("docs/NODE_BOARD.md is stale: run tools/node_board.py --write" if stale else "docs/NODE_BOARD.md is current")
        return 1 if stale else 0
    if args.json:
        print(json.dumps({"summary": summary(board()), "by_component": by_component(board())}, indent=1))
        return 0
    print(markdown(), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
