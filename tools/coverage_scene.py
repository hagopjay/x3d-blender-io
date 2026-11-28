# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The node board as an X3D 4.0 scene: the coverage observatory (docs/coverage/).

Every concrete node of X3DUOM 4.0 (260, tools/node_board_nodes.json) is a column in the sector of its component, around
a central core. The column's colour is how the import reads the node (the board's read rung), its glowing cap says the
X3D 4.0 export writes it, and its height is how many of the project's X3D files use it (tools/node_board_frequency.json,
log scale). The seven X3D 4.1 or Web3D extension nodes that x3d.py declares beyond X3DUOM 4.0 orbit outside as spheres,
lit when the add-on writes them (mapping/x3d_fields.json). Hover a column for its numbers; click it for the node's entry
in the Web3D X3D Tooltips. The core shows the totals and a ring filled to the written share.

Everything comes from files the repository already commits, so the scene is regenerated, never edited:

    python3 tools/coverage_scene.py            # writes docs/coverage/node-board.x3d
    python3 tools/coverage_scene.py --check    # exits 1 when the committed scene is stale

The output is deterministic (fixed ordering and number formatting, no dates), so --check is a byte comparison.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
NODES = ROOT / "tools" / "node_board_nodes.json"
MEASURED = ROOT / "tools" / "node_board_measured.json"
FREQUENCY = ROOT / "tools" / "node_board_frequency.json"
MAPPING = ROOT / "mapping" / "x3d_fields.json"
OUT = ROOT / "docs" / "coverage" / "node-board.x3d"
TOOLTIPS = "https://www.web3d.org/x3d/content/X3dTooltips.html#"

# read rung -> (label, diffuse, emissive): one palette, readable on the night ground, with "none" a quiet slate
RUNGS = {
    "builds": ("builds Blender data", (0.16, 0.78, 0.74), (0.02, 0.16, 0.15)),
    "graph": ("behaviour graph", (0.62, 0.44, 0.95), (0.10, 0.06, 0.18)),
    "carries": ("kept as written (carry)", (0.98, 0.70, 0.26), (0.18, 0.11, 0.02)),
    "structural": ("structural (children read)", (0.36, 0.56, 0.92), (0.04, 0.07, 0.14)),
    "reported": ("reported, not read", (0.86, 0.44, 0.56), (0.12, 0.04, 0.06)),
    "unprobed": ("not probed", (0.55, 0.57, 0.62), (0.03, 0.03, 0.04)),
    "none": ("not read", (0.20, 0.23, 0.30), (0.01, 0.01, 0.02)),
}
CAP = (1.0, 0.93, 0.72)                 # a written node's cap: warm white, emissive
EXTRA = ["GaussianSplats", "EnvironmentLight", "FontLibrary", "HAnimPose", "InlineGeometry", "RenderedTexture", "Tangent"]

R0 = 11.0           # inner radius of the ring (the core sits inside)
PITCH = 1.0         # centre spacing of the columns
SIDE = 0.72         # column footprint
GAP = 0.055         # share of the circle left between sectors


def num(v: float) -> str:
    text = f"{v:.4f}".rstrip("0").rstrip(".")
    return "0" if text in ("-0", "") else text


def vec(*vs) -> str:
    return " ".join(num(v) for v in vs)


def load():
    uom = json.loads(NODES.read_text(encoding="utf-8"))["nodes"]
    measured = json.loads(MEASURED.read_text(encoding="utf-8"))["nodes"]
    measured = measured if isinstance(measured, dict) else {r["node"]: r for r in measured}
    files = json.loads(FREQUENCY.read_text(encoding="utf-8"))
    used = files["files_with"]
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))["nodes"]
    nodes = []
    for name, info in sorted(uom.items()):
        m = measured.get(name, {})
        nodes.append({"name": name, "component": info["component"], "level": int(info.get("level") or 1),
                      "read": m.get("read", "none"), "written": m.get("written", "no"), "files": int(used.get(name, 0))})
    extras = [{"name": n, "written": (mapping.get(n) or {}).get("export") == "written",
               "import": (mapping.get(n) or {}).get("import", "none"), "files": int(used.get(n, 0)),
               "note": (mapping.get(n) or {}).get("note")} for n in EXTRA]
    return nodes, extras, int(files["files"])


def height(files: int) -> float:
    return 0.35 + 0.9 * math.log2(1 + files)


def layout(nodes):
    """Sectors around the ring, sized by node count; inside each, columns by level then name, filled row by row
    outward."""
    by_comp = {}
    for n in nodes:
        by_comp.setdefault(n["component"], []).append(n)
    ranked = sorted(by_comp, key=lambda c: (-len(by_comp[c]), c))
    # interleave large and small (largest, smallest, next largest, ...): the small components' names spread round the
    # ring instead of crowding one arc
    comps = []
    lo, hi = 0, len(ranked) - 1
    while lo <= hi:
        comps.append(ranked[lo])
        if lo != hi:
            comps.append(ranked[hi])
        lo, hi = lo + 1, hi - 1
    total = len(nodes)
    angle = math.pi / 2                                          # start at "north" (+Z is toward the viewer; see below)
    sectors = []
    for comp in comps:
        members = sorted(by_comp[comp], key=lambda n: (n["level"], n["name"]))
        span = 2 * math.pi * (1 - GAP) * len(members) / total
        pad = 2 * math.pi * GAP / len(comps)
        cols = max(1, int(span * R0 / PITCH))
        rows = math.ceil(len(members) / cols)
        cols = math.ceil(len(members) / rows)
        placed = []
        for i, n in enumerate(members):
            row, col = divmod(i, cols)
            r = R0 + row * PITCH
            a = angle + pad / 2 + (col + 0.5) * span / cols
            placed.append((n, r, a))
        sectors.append({"component": comp, "members": placed, "mid": angle + pad / 2 + span / 2,
                        "outer": R0 + rows * PITCH, "start": angle + pad / 2, "span": span})
        angle += span + pad
    return sectors


def xy(r: float, a: float):
    # X3D: Y up; the ring lies on the XZ plane
    return r * math.cos(a), r * math.sin(a)


def scene(nodes, extras, corpus):
    sectors = layout(nodes)
    written = sum(1 for n in nodes if n["written"] == "observed")
    reads = {k: sum(1 for n in nodes if n["read"] == k) for k in RUNGS}
    out = []
    w = out.append
    w('<?xml version="1.0" encoding="UTF-8"?>\n')
    w('<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">\n')
    w('<X3D profile="Immersive" version="4.0" xmlns:xsd="http://www.w3.org/2001/XMLSchema-instance" '
      'xsd:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">\n  <head>\n')
    w('    <meta name="title" content="x3d-blender-io coverage observatory: the X3D 4.0 node board"/>\n')
    w('    <meta name="description" content=' + quoteattr(
        f"Every concrete node of X3D 4.0 (X3DUOM 4.0, {len(nodes)} nodes in {len(sectors)} components) as a column around "
        f"a core: colour is how the Blender import reads it, a glowing cap means the X3D 4.0 export writes it "
        f"({written} of {len(nodes)}), height is how many of the project's {corpus} X3D files use it (log scale). "
        f"The {len(extras)} X3D 4.1 or extension nodes x3d.py declares orbit outside. Generated by tools/coverage_scene.py "
        f"from tools/node_board_measured.json; hover a column for its numbers, click it for its X3D Tooltips entry.") + '/>\n')
    w('    <meta name="generator" content="tools/coverage_scene.py (x3d-blender-io)"/>\n')
    w('    <meta name="license" content="GPL-3.0-or-later"/>\n  </head>\n  <Scene>\n')
    w('    <WorldInfo title="Coverage observatory"/>\n')
    w('    <NavigationInfo type=\'"EXAMINE" "ANY"\' headlight="false"/>\n')
    w('    <Background skyAngle="0.9 1.45 1.571" skyColor="0.012 0.016 0.035 0.03 0.04 0.09 0.07 0.08 0.17 0.11 0.1 0.2" '
      'groundAngle="1.571" groundColor="0.01 0.012 0.02 0.02 0.022 0.04"/>\n')
    w('    <Viewpoint DEF="Overview" description="Overview" position="0 46 38" orientation="-1 0 0 0.88" fieldOfView="0.78"/>\n')
    w('    <Viewpoint DEF="Map" description="Map, from above" position="0 72 0.01" orientation="-1 0 0 1.5706" fieldOfView="0.7"/>\n')
    w('    <Viewpoint DEF="Street" description="Among the columns" position="0 3.2 25" orientation="-1 0 0 0.08" fieldOfView="0.9"/>\n')
    w('    <DirectionalLight direction="-0.4 -1 -0.6" intensity="0.85" color="0.85 0.88 1"/>\n')
    w('    <DirectionalLight direction="0.6 -0.5 0.8" intensity="0.35" color="1 0.8 0.65"/>\n')
    w('    <PointLight location="0 6 0" intensity="0.8" radius="40" color="1 0.86 0.6"/>\n')
    # the ground: a dark disc, and a faint ring under each component
    w('    <Transform translation="0 -0.06 0">\n      <Shape><Appearance><Material diffuseColor="0.03 0.035 0.06" '
      'specularColor="0.05 0.055 0.07" shininess="0.3"/></Appearance><Cylinder radius="160" height="0.1"/></Shape>\n    </Transform>\n')
    # the unit column and the shared looks: one Box, scaled per node, and one Appearance per rung
    for key, (label, diffuse, emissive) in RUNGS.items():
        w(f'    <!-- {label} -->\n')
    first_box = True
    first_look = set()
    w('    <Group DEF="Columns">\n')
    for sector in sectors:
        comp = sector["component"]
        w(f'      <Group DEF={quoteattr("C_" + comp)}>\n')
        for n, r, a in sector["members"]:
            x, z = xy(r, a)
            h = height(n["files"])
            rung = n["read"] if n["read"] in RUNGS else "none"
            label, diffuse, emissive = RUNGS[rung]
            desc = (f'{n["name"]} · {comp} level {n["level"]} · read: {label} · '
                    f'{"written by the X3D 4.0 export" if n["written"] == "observed" else "not written"} · '
                    f'in {n["files"]} of {corpus} files')
            w(f'        <Anchor description={quoteattr(desc)} url={quoteattr(json.dumps(TOOLTIPS + n["name"]))}>\n')
            w(f'          <Transform translation="{vec(x, h / 2, z)}" rotation="0 1 0 {num(-a)}" scale="{vec(SIDE, h, SIDE)}">\n')
            look = f'R_{rung}'
            if look in first_look:
                app = f'<Appearance USE="{look}"/>'
            else:
                first_look.add(look)
                app = (f'<Appearance DEF="{look}"><Material diffuseColor="{vec(*diffuse)}" emissiveColor="{vec(*emissive)}" '
                       f'specularColor="0.35 0.35 0.4" shininess="0.35"/></Appearance>')
            box = '<Box USE="Unit"/>' if not first_box else '<Box DEF="Unit" size="1 1 1"/>'
            first_box = False
            w(f'            <Shape>{app}{box}</Shape>\n          </Transform>\n')
            if n["written"] == "observed":
                cap = 'Cap' if 'Cap' in first_look else None
                if cap:
                    capapp = '<Appearance USE="Cap"/>'
                else:
                    first_look.add('Cap')
                    capapp = (f'<Appearance DEF="Cap"><Material diffuseColor="{vec(*CAP)}" emissiveColor="{vec(*CAP)}"/>'
                              '</Appearance>')
                w(f'          <Transform translation="{vec(x, h + 0.06, z)}" rotation="0 1 0 {num(-a)}" '
                  f'scale="{vec(SIDE * 0.86, 0.12, SIDE * 0.86)}">\n'
                  f'            <Shape>{capapp}<Box USE="Unit"/></Shape>\n          </Transform>\n')
            w('        </Anchor>\n')
        w('      </Group>\n')
    w('    </Group>\n')
    # component names on the floor beyond each sector, turned to face the centre's viewer
    w('    <Group DEF="Labels">\n')
    small = 0
    for sector in sectors:
        k = len(sector["members"])
        stagger = 0.0
        if k < 6:                       # neighbouring small sectors: alternate two radii so their names do not collide
            stagger = 1.5 * (small % 2)
            small += 1
        r = sector["outer"] + 1.3 + stagger
        x, z = xy(r, sector["mid"])
        n_w = sum(1 for n, _r, _a in sector["members"] if n["written"] == "observed")
        text = json.dumps(sector["component"]) + " " + json.dumps(f'{n_w} of {k} written')
        scale = 1.0 if k >= 10 else (0.82 if k >= 5 else 0.66)
        w(f'      <Transform translation="{vec(x, 1.0, z)}" scale="{vec(scale, scale, scale)}">\n'
          '        <Billboard axisOfRotation="0 0 0">\n'
          f'          <Shape><Appearance USE="LabelLook"/>'
          f'<Text string={quoteattr(text)}><FontStyle USE="LabelFont"/></Text></Shape>\n'
          '        </Billboard>\n      </Transform>\n')
    w('    </Group>\n')
    # under each sector, a floor arc: gold for the share the export writes, dim for the rest
    w('    <Group DEF="SectorArcs">\n')
    for sector in sectors:
        k = len(sector["members"])
        n_w = sum(1 for n, _r, _a in sector["members"] if n["written"] == "observed")
        a0, span = sector["start"], sector["span"]
        steps = max(4, int(24 * span))
        w(f'      <Shape><Appearance USE="ArcDim"/><Extrusion spine="{arc(R0 - 1.0, a0, a0 + span, steps, 0.02)}" '
          f'crossSection="{square(0.14)}" creaseAngle="0.8"/></Shape>\n')
        if n_w:
            a1 = a0 + span * n_w / k
            w(f'      <Shape><Appearance USE="ArcLit"/><Extrusion spine="{arc(R0 - 1.0, a0, a1, max(3, int(steps * n_w / k)), 0.05)}" '
              f'crossSection="{square(0.2)}" creaseAngle="0.8"/></Shape>\n')
    w('    </Group>\n')
    # the core: totals and a ring filled to the written share
    share = written / len(nodes)
    w('    <Group DEF="Core">\n')
    w('      <Shape><Appearance><Material diffuseColor="0.06 0.07 0.12" emissiveColor="0.02 0.025 0.05"/></Appearance>'
      f'<Extrusion spine="{arc(7.2, 0.0, 2 * math.pi, 96)}" crossSection="{square(0.16)}" beginCap="false" endCap="false" '
      'creaseAngle="0.8"/></Shape>\n')
    w('      <Shape><Appearance><Material diffuseColor="1 0.93 0.72" emissiveColor="0.95 0.78 0.45"/></Appearance>'
      f'<Extrusion spine="{arc(7.2, math.pi / 2, math.pi / 2 - 2 * math.pi * share, max(8, int(96 * share)))}" '
      f'crossSection="{square(0.3)}" creaseAngle="0.8"/></Shape>\n')
    lines = [f"{written} of {len(nodes)}", "X3D 4.0 nodes written",
             f"read: {reads['builds']} build, {reads['carries']} carried, {reads['graph']} graph",
             f"{reads['structural']} structural, {reads['none']} not read"]
    w('      <Transform translation="0 4.4 0">\n        <Billboard axisOfRotation="0 0 0">\n'
      '          <Shape><Appearance><Material diffuseColor="1 0.95 0.82" emissiveColor="1 0.93 0.75"/></Appearance>'
      f'<Text string={quoteattr(" ".join(json.dumps(s) for s in lines[:1]))}>'
      '<FontStyle family=\'"SANS"\' style="BOLD" size="2.2" justify=\'"MIDDLE" "MIDDLE"\'/></Text></Shape>\n'
      '          <Transform translation="0 -1.75 0"><Shape><Appearance USE="LabelLook"/>'
      f'<Text string={quoteattr(" ".join(json.dumps(s) for s in lines[1:]))}>'
      '<FontStyle family=\'"SANS"\' size="0.62" spacing="1.25" justify=\'"MIDDLE" "BEGIN"\'/></Text></Shape></Transform>\n'
      '        </Billboard>\n      </Transform>\n')
    w('    </Group>\n')
    # the 4.1 and extension nodes, on an outer orbit
    w('    <Group DEF="Beyond40">\n')
    orbit = max(s["outer"] for s in sectors) + 6.5
    for i, e in enumerate(extras):
        a = math.pi / 2 + (i - (len(extras) - 1) / 2) * 0.16
        x, z = xy(orbit, a)
        y = 3.2
        lit = e["written"]
        mat = ('<Material diffuseColor="1 0.93 0.72" emissiveColor="0.95 0.8 0.5"/>' if lit else
               '<Material diffuseColor="0.3 0.34 0.48" emissiveColor="0.05 0.06 0.1" transparency="0.35"/>')
        desc = (f'{e["name"]} · X3D 4.1 draft or extension (not in X3DUOM 4.0) · '
                f'{"written by the X3D 4.1 export, read by the import" if lit else "not supported yet"} · '
                f'in {e["files"]} of {corpus} files')
        w(f'      <Anchor description={quoteattr(desc)} url={quoteattr(json.dumps(TOOLTIPS + e["name"]))}>\n'
          f'        <Transform translation="{vec(x, y, z)}"><Shape><Appearance>{mat}</Appearance>'
          f'<Sphere radius="{num(0.55 if lit else 0.4)}"/></Shape></Transform>\n      </Anchor>\n')
    x, z = xy(orbit, math.pi / 2)
    w(f'      <Transform translation="{vec(x, 5.0, z)}">\n        <Billboard axisOfRotation="0 1 0">\n'
      '          <Shape><Appearance USE="LabelLook"/><Text string=\'"beyond X3DUOM 4.0: X3D 4.1 draft and extensions"\'>'
      '<FontStyle USE="LabelFont"/></Text></Shape>\n        </Billboard>\n      </Transform>\n')
    w('    </Group>\n')
    w('  </Scene>\n</X3D>\n')
    text = "".join(out)
    # the shared label look and font are DEF'd on first use: move the DEF to the first occurrence
    text = text.replace('<Appearance USE="LabelLook"/>',
                        '<Appearance DEF="LabelLook"><Material diffuseColor="0.78 0.82 0.92" emissiveColor="0.55 0.6 0.72"/>'
                        '</Appearance>', 1)
    text = text.replace('<Appearance USE="ArcDim"/>',
                        '<Appearance DEF="ArcDim"><Material diffuseColor="0.12 0.14 0.22" emissiveColor="0.05 0.06 0.1"/></Appearance>', 1)
    text = text.replace('<Appearance USE="ArcLit"/>',
                        '<Appearance DEF="ArcLit"><Material diffuseColor="1 0.9 0.62" emissiveColor="0.95 0.75 0.4"/></Appearance>', 1)
    text = text.replace('<FontStyle USE="LabelFont"/>',
                        '<FontStyle DEF="LabelFont" family=\'"SANS"\' size="0.62" justify=\'"MIDDLE" "MIDDLE"\'/>', 1)
    return text


def arc(r: float, a0: float, a1: float, steps: int, y: float = 0.15) -> str:
    pts = []
    for i in range(steps + 1):
        a = a0 + (a1 - a0) * i / steps
        x, z = xy(r, a)
        pts.append(vec(x, y, z))
    return " ".join(pts)


def square(s: float) -> str:
    h = s / 2
    return vec(h, h, h, -h, -h, -h, -h, h, h, h)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when the committed scene is stale")
    ap.add_argument("--out", type=Path, default=OUT)
    args = ap.parse_args(argv)
    nodes, extras, corpus = load()
    text = scene(nodes, extras, corpus)
    if args.check:
        current = args.out.read_text(encoding="utf-8") if args.out.exists() else ""
        if current != text:
            print(f"{args.out.relative_to(ROOT)} is stale: run python3 tools/coverage_scene.py", file=sys.stderr)
            return 1
        print(f"{args.out.relative_to(ROOT)} is current")
        return 0
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out.relative_to(ROOT)}: {len(nodes)} nodes, {len(extras)} beyond 4.0, {len(text)} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main())
