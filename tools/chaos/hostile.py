"""Hostile files: inputs built to hurt a reader, each imported in its own process under a memory and time budget.

Round 1 (differential.py) made one ordinary edit at a time. This battery is the security-shaped half: files that try to
expand without bound, read files they should not, reach the network, recurse forever or arrive broken. Every case
must end FINISHED or CANCELLED, within the time and memory budget, without the sentinel text of a file outside the
scene appearing anywhere in the Blender data, and without one request to the local HTTP server that stands in for
the network. Run with the bpy wheel's Python, or give --blender to run each case in a Blender binary:

    python tools/chaos/hostile.py --out /tmp/hostile [--only NAME] [--blender PATH] [--fail-on-finding]

Each case is written under --out (nothing goes to the repository); results.json lists one row per case.
"""
from __future__ import annotations

import argparse
import gzip
import http.server
import json
import os
import resource
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
SENTINEL = "X3D-HOSTILE-SENTINEL-7f3a9c"
MEMORY_BUDGET = 6 * 1024 ** 3        # address space for the child, bytes
TIME_BUDGET = 90                     # seconds per case, import plus re-export

HEAD = "<?xml version='1.0' encoding='UTF-8'?>\n"
QUAD = ("<Shape><IndexedFaceSet solid='false' coordIndex='0 1 2 3 -1'>"
        "<Coordinate point='0 0 0 1 0 0 1 1 0 0 1 0'/></IndexedFaceSet></Shape>")


def _x3d(body: str, head: str = HEAD, doctype: str = "") -> str:
    return f"{head}{doctype}<X3D profile='Interchange' version='4.0'><Scene>{body}</Scene></X3D>\n"


def _vrml(body: str) -> str:
    return "#X3D V4.0 utf8\nPROFILE Interchange\n" + body + "\n"


def make_cases(out: Path, port: int) -> list[dict]:
    """Write every case under ``out``; return [{name, path, family, why}]."""
    out.mkdir(parents=True, exist_ok=True)
    secret = out / "secret.txt"
    secret.write_text(SENTINEL + "\n", encoding="utf-8")
    (out / "secret.dtd").write_text(f"<!ENTITY leak '{SENTINEL}'>\n", encoding="utf-8")
    net = f"http://127.0.0.1:{port}"
    cases: list[tuple[str, str, str, bytes | str]] = []

    def add(name, family, why, data, suffix=".x3d"):
        cases.append((name + suffix, family, why, data))

    # -- expansion --------------------------------------------------------------------------------------------------
    laughs = "".join(f"<!ENTITY l{i} '{('&l%d;' % (i - 1)) * 10}'>" for i in range(1, 10))
    add("billion_laughs", "expansion", "ten levels of ten-fold entities: 10^9 copies of one string",
        _x3d(f"<WorldInfo title='&l9;'/>{QUAD}", doctype=f"<!DOCTYPE X3D [<!ENTITY l0 'ha'>{laughs}]>"))
    add("quadratic_blowup", "expansion", "one 50 kB entity referenced 40,000 times",
        _x3d("<WorldInfo title='" + "&a;" * 40000 + f"'/>{QUAD}",
             doctype="<!DOCTYPE X3D [<!ENTITY a '" + "x" * 50000 + "'>]>"))
    big = b"<X3D profile='Interchange' version='4.0'><Scene>" + b" " * (1536 * 1024 ** 2) + b"</Scene></X3D>"
    cases.append(("gzip_bomb.x3dz", "expansion", "1.5 GB of spaces in a 1.5 MB gzip", gzip.compress(big, 9)))
    del big
    inner = gzip.compress(_x3d(QUAD).encode())
    cases.append(("gzip_in_gzip.x3dz", "expansion", "a gzip whose content is another gzip", gzip.compress(inner)))
    # an Inline fan-out: each level inlines the next one ten times, five levels deep (10^5 instances)
    for level in range(5, 0, -1):
        child = f"fan{level + 1}.x3d" if level < 5 else None
        body = "".join(f"<Inline url='\"{child}\"'/>" for _ in range(10)) if child else QUAD
        (out / f"fan{level}.x3d").write_text(_x3d(body), encoding="utf-8")
    (out / "fan6.x3d").write_text(_x3d(QUAD), encoding="utf-8")

    # -- reading what it should not ---------------------------------------------------------------------------------
    add("xxe_file_entity", "disclosure", "an external entity naming a local file",
        _x3d(f"<WorldInfo title='x'><MetadataString name='a' value='\"&leak;\"'/></WorldInfo>{QUAD}",
             doctype=f"<!DOCTYPE X3D [<!ENTITY leak SYSTEM 'file://{secret}'>]>"))
    add("xxe_text_entity", "disclosure", "an external entity in element text (a Script body)",
        _x3d(f"<Script DEF='S'>&leak;</Script>{QUAD}",
             doctype=f"<!DOCTYPE X3D [<!ENTITY leak SYSTEM 'file://{secret}'>]>"))
    add("xxe_parameter_entity", "disclosure", "a parameter entity pulling a local DTD that defines the entity",
        _x3d(f"<WorldInfo title='&leak;'/>{QUAD}",
             doctype=f"<!DOCTYPE X3D [<!ENTITY % ext SYSTEM 'file://{out / 'secret.dtd'}'> %ext;]>"))
    add("external_dtd_network", "network", "a DOCTYPE whose system id is an http url",
        _x3d(QUAD, doctype=f"<!DOCTYPE X3D PUBLIC 'ISO//Web3D//DTD X3D 4.0//EN' '{net}/x3d-4.0.dtd'>"))
    add("xinclude_file", "disclosure", "an XInclude of a local file",
        _x3d(f"<Group xmlns:xi='http://www.w3.org/2001/XInclude'><xi:include href='file://{secret}' parse='text'/>"
             f"</Group>{QUAD}"))
    add("inline_network", "network", "an Inline whose url is http",
        _x3d(f"<Inline url='\"{net}/a.x3d\"'/>{QUAD}"))
    add("image_network", "network", "an ImageTexture whose url is http",
        _x3d(f"<Shape><Appearance><ImageTexture url='\"{net}/t.png\"'/></Appearance>"
             "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedFaceSet></Shape>"))
    add("script_network", "network", "a Script whose url is http (a Script must never be fetched or run)",
        _x3d(f"<Script DEF='S' url='\"{net}/s.js\"'/>{QUAD}"))
    add("inline_dev_zero", "expansion", "an Inline of /dev/zero, a file that never ends",
        _x3d(f"<Inline url='\"/dev/zero\"'/>{QUAD}"))
    add("image_dev_zero", "expansion", "an ImageTexture of /dev/zero",
        _x3d("<Shape><Appearance><ImageTexture url='\"/dev/zero\"'/></Appearance>"
             "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedFaceSet></Shape>"))

    # -- recursion --------------------------------------------------------------------------------------------------
    add("inline_self", "recursion", "an Inline of the file itself", _x3d(f"<Inline url='\"inline_self.x3d\"'/>{QUAD}"))
    (out / "cycle_b.x3d").write_text(_x3d(f"<Inline url='\"inline_cycle_a.x3d\"'/>{QUAD}"), encoding="utf-8")
    add("inline_cycle_a", "recursion", "a inlines b and b inlines a", _x3d(f"<Inline url='\"cycle_b.x3d\"'/>{QUAD}"))
    add("inline_fanout", "recursion", "Inline fan-out, ten per level, five levels (100,000 copies)",
        _x3d("".join("<Inline url='\"fan2.x3d\"'/>" for _ in range(10))))
    add("use_inside_own_def", "recursion", "a Group that USEs itself inside its own DEF",
        _x3d(f"<Group DEF='A'>{QUAD}<Group USE='A'/></Group>"))
    add("proto_self_instance", "recursion", "a ProtoDeclare whose body instances itself",
        _x3d("<ProtoDeclare name='P'><ProtoBody><Group><ProtoInstance name='P'/></Group></ProtoBody></ProtoDeclare>"
             f"<ProtoInstance name='P'/>{QUAD}"))
    add("proto_mutual", "recursion", "two ProtoDeclares that instance each other",
        _x3d("<ProtoDeclare name='P'><ProtoBody><Group><ProtoInstance name='Q'/></Group></ProtoBody></ProtoDeclare>"
             "<ProtoDeclare name='Q'><ProtoBody><Group><ProtoInstance name='P'/></Group></ProtoBody></ProtoDeclare>"
             f"<ProtoInstance name='P'/>{QUAD}"))
    for depth in (5000, 100000):
        add(f"deep_groups_{depth}", "recursion", f"{depth:,} nested Groups",
            _x3d("<Group>" * depth + QUAD + "</Group>" * depth))
    # 2,000, not 5,000: the import and export still walk the ancestry of every node (quadratic in depth, about 16 s
    # here at 2,000 and 120 s at 5,000; docs/CHAOS.md lists it for 2.7.4)
    add("deep_transforms_2000", "recursion", "2,000 nested Transforms (a matrix product per level)",
        _x3d("<Transform translation='0 0.001 0'>" * 2000 + QUAD + "</Transform>" * 2000))

    # -- broken bytes -----------------------------------------------------------------------------------------------
    whole = _x3d(f"<Transform DEF='T'>{QUAD}</Transform>")
    add("truncated_mid_tag", "broken", "the file cut off inside a start tag", whole[: whole.index("coordIndex") + 5])
    add("truncated_mid_attribute", "broken", "the file cut off inside an attribute value",
        whole[: whole.index("point='") + 12])
    add("truncated_before_close", "broken", "the file without its last closing tags", whole[: whole.rindex("</Scene>")])
    add("utf16_declared_utf8", "broken", "UTF-16 bytes with a BOM and an encoding='UTF-8' declaration",
        "﻿".encode("utf-16-le") + whole.encode("utf-16-le"))
    add("latin1_bytes", "broken", "a DEF in Latin-1 bytes, which are not UTF-8",
        whole.replace("DEF='T'", "DEF='Téè'").encode("latin-1"))
    add("nul_bytes", "broken", "NUL bytes inside an attribute", whole.replace("DEF='T'", "DEF='T\0\0'"))
    add("bom_only", "broken", "a UTF-8 BOM and nothing else", b"\xef\xbb\xbf")
    add("png_renamed", "broken", "PNG bytes in a file named .x3d", b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 8)
    cases.append(("not_gzip.x3dz", "broken", "plain text named .x3dz", whole))
    add("no_x3d_root", "broken", "well-formed XML whose root is not X3D", HEAD + "<Scene><Group/></Scene>")
    add("two_scenes", "broken", "an X3D with two Scene elements",
        HEAD + f"<X3D profile='Interchange' version='4.0'><Scene>{QUAD}</Scene><Scene>{QUAD}</Scene></X3D>")

    # -- numbers and sizes ------------------------------------------------------------------------------------------
    add("int_5000_digits", "numbers", "a coordIndex entry 5,000 digits long (Python refuses int() over 4,300)",
        whole.replace("coordIndex='0 1 2 3 -1'", "coordIndex='0 1 2 " + "9" * 5000 + " -1'"))
    add("float_5000_digits", "numbers", "a point coordinate 5,000 digits long",
        whole.replace("point='0 0 0", "point='" + "9" * 5000 + " 0 0"))
    add("float_exponent_huge", "numbers", "a float of 1e999999 (INF) and one of -1e-999999",
        whole.replace("point='0 0 0", "point='1e999999 -1e-999999 0"))
    add("int_negative_huge", "numbers", "a coordIndex entry of -2147483649",
        whole.replace("coordIndex='0 1 2 3 -1'", "coordIndex='0 1 2 -2147483649 -1'"))
    add("name_1mb", "numbers", "a DEF one million characters long", whole.replace("DEF='T'", "DEF='" + "N" * 10 ** 6 + "'"))
    add("element_name_100k", "numbers", "an unknown element whose name is 100,000 letters",
        _x3d("<" + "Q" * 100000 + "/>" + QUAD))
    add("attributes_100k", "numbers", "one element with 100,000 unknown attributes",
        _x3d("<Group " + " ".join(f"a{i}='1'" for i in range(100000)) + f">{QUAD}</Group>"))
    add("mfstring_100k", "numbers", "a WorldInfo info of 100,000 strings",
        _x3d("<WorldInfo info='" + " ".join('"s"' for _ in range(100000)) + f"'/>{QUAD}"))
    add("unterminated_mfstring", "numbers", "an MFString whose quote never closes",
        _x3d(f"<WorldInfo info='\"abc'/>{QUAD}"))
    add("route_flood", "numbers", "50,000 ROUTEs between two nodes",
        _x3d("<TimeSensor DEF='C'/><PositionInterpolator DEF='P' key='0 1' keyValue='0 0 0 1 1 1'/>"
             + "<ROUTE fromNode='C' fromField='fraction_changed' toNode='P' toField='set_fraction'/>" * 50000 + QUAD))
    add("coordinate_points_2m", "numbers", "one Coordinate with 2,000,000 points and one triangle",
        _x3d("<Shape><IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='"
             + " ".join("0 0 0" for _ in range(2000000)) + "'/></IndexedFaceSet></Shape>"))

    # -- the allocation budget: a count in the file, not the data, sets a size ---------------------------------------
    add("elevation_grid_huge", "budget", "an ElevationGrid of 100,000 x 100,000 with four heights",
        _x3d("<Shape><ElevationGrid xDimension='100000' zDimension='100000' height='0 0 0 0'/></Shape>" + QUAD))
    add("elevation_grid_negative", "budget", "an ElevationGrid of -3 x 4",
        _x3d("<Shape><ElevationGrid xDimension='-3' zDimension='4' height='0 0 0 0'/></Shape>" + QUAD))
    add("sphere_subdivision_zero", "budget", "an X3DOM Sphere subdivision of 0 (divides by zero)",
        _x3d("<Shape><Sphere subdivision='0 0'/></Shape>" + QUAD))
    add("sphere_subdivision_huge", "budget", "an X3DOM Sphere subdivision of 100,000 x 100,000",
        _x3d("<Shape><Sphere subdivision='100000 100000'/></Shape>" + QUAD))
    add("cylinder_subdivision_zero", "budget", "a Cylinder subdivision of 0",
        _x3d("<Shape><Cylinder subdivision='0'/></Shape><Shape><Cone subdivision='-5'/></Shape>" + QUAD))
    add("cylinder_subdivision_huge", "budget", "a Cylinder subdivision of 50,000,000",
        _x3d("<Shape><Cylinder subdivision='50000000'/></Shape>" + QUAD))
    add("pixel_texture_huge", "budget", "a PixelTexture that says 100,000 x 100,000 and holds one pixel",
        _x3d("<Shape><Appearance><PixelTexture image='100000 100000 3 0xFF0000'/></Appearance>"
             "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedFaceSet></Shape>"))
    add("pixel_texture_short_header", "budget", "a PixelTexture image with two header numbers",
        _x3d("<Shape><Appearance><PixelTexture image='2 2'/></Appearance>"
             "<IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 1 0 0 1 1 0'/></IndexedFaceSet></Shape>"))
    add("animation_long_cycle", "budget", "a TimeSensor of 47,000 s driving 48 keys (the round trip that grew 22,000x)",
        _x3d("<Transform DEF='T'>" + QUAD + "</Transform><TimeSensor DEF='C' cycleInterval='47000' loop='true'/>"
             "<PositionInterpolator DEF='P' key='" + " ".join(f"{i / 47:.6f}" for i in range(48)) + "' keyValue='"
             + " ".join(f"{i} 0 0" for i in range(48)) + "'/>"
             "<ROUTE fromNode='C' fromField='fraction_changed' toNode='P' toField='set_fraction'/>"
             "<ROUTE fromNode='P' fromField='value_changed' toNode='T' toField='set_translation'/>"))
    add("leading_zero_index", "numbers", "a coordIndex with a zero-padded entry (010)",
        whole.replace("coordIndex='0 1 2 3 -1'", "coordIndex='00 01 02 03 -1'"))
    add("nan_in_points", "numbers", "NaN and INF inside a point list and a key list",
        _x3d("<Transform DEF='T'><Shape><IndexedFaceSet coordIndex='0 1 2 -1'><Coordinate point='0 0 0 NaN 0 0 1 INF 0'/>"
             "</IndexedFaceSet></Shape></Transform><TimeSensor DEF='C' loop='true'/>"
             "<PositionInterpolator DEF='P' key='0 NaN 1' keyValue='0 0 0 1 1 1 2 2 2'/>"
             "<ROUTE fromNode='C' fromField='fraction_changed' toNode='P' toField='set_fraction'/>"
             "<ROUTE fromNode='P' fromField='value_changed' toNode='T' toField='set_translation'/>"))

    # -- ClassicVRML ------------------------------------------------------------------------------------------------
    vquad = ("Shape { geometry IndexedFaceSet { coordIndex [ 0 1 2 3 -1 ] "
             "coord Coordinate { point [ 0 0 0, 1 0 0, 1 1 0, 0 1 0 ] } } }")
    add("vrml_unbalanced_open", "vrml", "a ClassicVRML file with an opening brace that never closes",
        _vrml("Group { children [ " + vquad), ".x3dv")
    add("vrml_unbalanced_close", "vrml", "a ClassicVRML file with 1,000 extra closing braces",
        _vrml(vquad + " }" * 1000), ".x3dv")
    add("vrml_unterminated_string", "vrml", "a ClassicVRML string that never closes",
        _vrml('WorldInfo { title "abc ' + vquad), ".x3dv")
    add("vrml_deep_groups", "vrml", "5,000 nested ClassicVRML Groups",
        _vrml("Group { children [ " * 5000 + vquad + " ] }" * 5000), ".x3dv")
    add("vrml_use_cycle", "vrml", "a ClassicVRML Group that USEs itself",
        _vrml(f"DEF A Group {{ children [ {vquad} USE A ] }}"), ".x3dv")
    add("vrml_proto_self", "vrml", "a ClassicVRML PROTO whose body instances itself",
        _vrml(f"PROTO P [ ] {{ Group {{ children [ P {{ }} ] }} }} P {{ }} {vquad}"), ".x3dv")
    add("vrml_externproto_network", "vrml", "a ClassicVRML EXTERNPROTO whose url is http",
        _vrml(f'EXTERNPROTO E [ ] "{net}/e.wrl" E {{ }} {vquad}'), ".x3dv")
    add("vrml_inline_self", "vrml", "a VRML 2.0 Inline of the file itself",
        "#VRML V2.0 utf8\nInline { url \"vrml_inline_self.wrl\" }\n", ".wrl")
    (out / "vcycle_b.wrl").write_text('#VRML V2.0 utf8\nInline { url "vrml_inline_cycle_a.wrl" }\n', encoding="utf-8")
    add("vrml_inline_cycle_a", "vrml", "VRML a inlines b and b inlines a",
        '#VRML V2.0 utf8\nInline { url "vcycle_b.wrl" }\n', ".wrl")
    add("vrml_int_5000_digits", "vrml", "a ClassicVRML coordIndex entry 5,000 digits long",
        _vrml(vquad.replace("0 1 2 3 -1", "0 1 2 " + "9" * 5000 + " -1")), ".x3dv")
    add("vrml_comment_only", "vrml", "a ClassicVRML file that is one long comment", _vrml("#" + "c" * 10 ** 6), ".x3dv")

    # -- replay: the rules the receipt-to-rule engine (x3d.loom kit/loomkit/r2r) found still live in 2.7.3 --------
    grid = " ".join(f"{x} {y} 0" for y in range(5) for x in range(5))
    red = " ".join("1 0 0" for _ in range(25))
    uvs = " ".join(f"{x / 4} {y / 4}" for y in range(5) for x in range(5))
    sq = "0 0 0 1 0 0 1 1 0 0 1 0"

    def shape(node, fields, kids):
        return f"<Shape><{node} {fields}>{kids}</{node}></Shape>"
    add("r2r_coordinate_double", "replay", "triangle sets and a face set on CoordinateDouble (AttributeError)",
        _x3d("".join(shape(n, f, f"<CoordinateDouble point='{sq}'/>") for n, f in (
            ("IndexedTriangleSet", "index='0 1 2 0 2 3'"), ("IndexedTriangleStripSet", "index='0 1 3 2'"),
            ("IndexedTriangleFanSet", "index='0 1 2 3'"), ("IndexedFaceSet", "coordIndex='0 1 2 3 -1'")))))
    add("r2r_metadata_boolean", "replay", "a MetadataBoolean, which the export's semantic check refused",
        _x3d(f"<WorldInfo title='t'><MetadataBoolean containerField='metadata' name='f' value='true false'/>"
             f"</WorldInfo>{QUAD}"))
    add("r2r_its_color_huge", "replay", "an IndexedTriangleSet index of 2147483647 with Color (IndexError)",
        _x3d(shape("IndexedTriangleSet", "index='0 2147483647 2 3 4 5'",
                   f"<Coordinate point='{grid}'/><Color color='{red}'/>")))
    add("r2r_itss_uv_huge", "replay", "an IndexedTriangleStripSet index past the points with TextureCoordinate",
        _x3d(shape("IndexedTriangleStripSet", "index='0 1 2 19311470'",
                   f"<Coordinate point='{grid}'/><TextureCoordinate point='{uvs}'/>")))
    add("r2r_itfs_three_fans", "replay", "an IndexedTriangleFanSet of three fans (RuntimeError)",
        _x3d(shape("IndexedTriangleFanSet", "index='0 1 2 3 -1 5 6 7 -1 10 11 12 13 -1'",
                   f"<Coordinate point='{grid}'/>")))
    add("r2r_ifs_cull_huge", "replay", "an IndexedFaceSet on the vertex-cull path with an index past the points",
        _x3d(shape("IndexedFaceSet", "creaseAngle='1' coordIndex='0 2147483638 2 3 -1'",
                   f"<Coordinate point='{grid}'/>")))

    rows = []
    for name, family, why, data in cases:
        path = out / name
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8", errors="surrogatepass")
        else:
            path.write_bytes(data)
        rows.append({"name": Path(name).stem, "file": name, "path": str(path), "family": family, "why": why,
                     "bytes": path.stat().st_size})
    return rows


# -- the child: one import, one re-export, one scan ---------------------------------------------------------------

def _scan_for_sentinel(bpy) -> list[str]:
    """Every place in bpy.data where the sentinel text appears: names, custom properties, text blocks."""
    hits = []

    def walk(value, where):
        if isinstance(value, str):
            if SENTINEL in value:
                hits.append(where)
        elif hasattr(value, "keys") and hasattr(value, "__getitem__"):
            for key in value.keys():
                walk(value[key], f"{where}[{key!r}]")
        elif isinstance(value, (list, tuple)):
            for i, item in enumerate(value):
                walk(item, f"{where}[{i}]")

    for attr in dir(bpy.data):
        collection = getattr(bpy.data, attr, None)
        if not hasattr(collection, "__iter__") or not hasattr(collection, "rna_type") or attr.startswith("_"):
            continue
        try:
            items = list(collection)
        except Exception:
            continue
        for item in items:
            name = getattr(item, "name", "")
            if isinstance(name, str) and SENTINEL in name:
                hits.append(f"{attr}:{name[:40]}")
            try:
                for key in item.keys():
                    walk(item[key], f"{attr}:{name[:40]}[{key!r}]")
            except Exception:
                pass
            if attr == "texts" and SENTINEL in item.as_string():
                hits.append(f"texts:{name[:40]}")
    return hits


def run_one(path: Path, out: Path) -> dict:
    sys.path.insert(0, str(HERE))
    from differential import ImportJudge, _signature

    judge = ImportJudge()
    bpy = judge.bpy
    t0 = time.time()
    imp, exp = judge.run(path, out)      # it silences the add-on's output itself
    row = {"import": imp, "reexport": exp, "seconds": round(time.time() - t0, 2)}
    try:
        row["leaks"] = _scan_for_sentinel(bpy)
    except Exception as exc:  # the scan must not hide the result
        row["leaks"] = [f"scan raised {_signature(exc)}"]
    row["max_rss_mb"] = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024)
    return row


# -- the parent: a fresh process per case --------------------------------------------------------------------------

class _CountingHandler(http.server.BaseHTTPRequestHandler):
    hits: list[str] = []

    def do_GET(self):  # noqa: N802
        _CountingHandler.hits.append(self.path)
        self.send_response(404)
        self.end_headers()

    def log_message(self, *args):
        pass


FILE_BUDGET = 2 * 1024 ** 3          # the largest file the child may write: the first run filled a 50 GB disk


def _limit_child():
    import signal

    resource.setrlimit(resource.RLIMIT_AS, (MEMORY_BUDGET, MEMORY_BUDGET))
    resource.setrlimit(resource.RLIMIT_FSIZE, (FILE_BUDGET, FILE_BUDGET))
    signal.signal(signal.SIGXFSZ, signal.SIG_IGN)    # a write past the budget raises OSError instead of killing


def _tree_bytes(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file()) if path.exists() else 0


def judge_case(row: dict, result: dict | None, returncode: int, seconds: float, hits: list[str]) -> list[str]:
    """The findings for one case; an empty list is a pass."""
    findings = []
    if result is None:
        findings.append("timeout" if returncode is None else f"process died (exit {returncode})")
    else:
        imp, exp = result["import"], result["reexport"]
        if imp["result"] not in ("FINISHED", "CANCELLED"):
            findings.append(f"import {imp['result']}: {imp.get('exception', '')}")
        if exp["result"] not in ("ok", "FINISHED", "SKIPPED"):
            findings.append(f"re-export {exp['result']}: {exp.get('exception', '')}")
        if result["leaks"]:
            findings.append(f"sentinel read into the scene: {result['leaks'][:3]}")
    if seconds > TIME_BUDGET * 0.9:
        findings.append(f"slow: {seconds:.0f} s")
    if hits:
        findings.append(f"network: {len(hits)} request(s) {hits[:3]}")
    return findings


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--" in argv:
        argv = argv[argv.index("--") + 1:]
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--only", action="append", default=[], help="run only these case names (repeatable)")
    parser.add_argument("--blender", help="run each case in this Blender binary instead of the bpy wheel")
    parser.add_argument("--fail-on-finding", action="store_true")
    parser.add_argument("--one", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.one:
        result = run_one(args.one, args.out)
        (args.out / (args.one.name + ".result.json")).write_text(json.dumps(result, indent=1), encoding="utf-8")
        return 0

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _CountingHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    port = server.server_address[1]
    cases = make_cases(args.out, port)
    if args.only:
        cases = [c for c in cases if c["name"] in args.only]
    env = dict(os.environ, BLENDER_X3D_RECEIPT="0")
    rows, failed = [], 0
    for case in cases:
        _CountingHandler.hits = []
        if args.blender:
            cmd = [args.blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", __file__, "--"]
        else:
            cmd = [sys.executable, __file__]
        work = args.out / "runs" / case["name"]
        work.mkdir(parents=True, exist_ok=True)
        cmd += ["--out", str(work), "--one", case["path"]]
        result_file = work / (case["file"] + ".result.json")
        t0 = time.time()
        try:
            proc = subprocess.run(cmd, env=env, preexec_fn=_limit_child, capture_output=True, timeout=TIME_BUDGET)
            returncode = proc.returncode
            tail = (proc.stdout + proc.stderr)[-800:].decode("utf-8", "replace")
        except subprocess.TimeoutExpired:
            returncode, tail = None, "timeout"
        seconds = time.time() - t0
        result = json.loads(result_file.read_text()) if result_file.exists() else None
        findings = judge_case(case, result, returncode, seconds, list(_CountingHandler.hits))
        written = _tree_bytes(work) - (result_file.stat().st_size if result_file.exists() else 0)
        if written > 64 * 1024 ** 2:
            findings.append(f"wrote {written / 1024 ** 2:.0f} MB next to the re-export")
        shutil.rmtree(work, ignore_errors=True)         # this case's own scratch folder, made above
        row = dict(case, seconds=round(seconds, 1), findings=findings, result=result)
        if result is None:
            row["process_tail"] = tail
        rows.append(row)
        failed += bool(findings)
        state = "FINDING" if findings else "ok"
        imp = result["import"]["result"] if result else "-"
        print(f"[hostile] {state:8s} {case['name']:28s} {imp:10s} {seconds:6.1f} s "
              f"{(result or {}).get('max_rss_mb', '-')!s:>6} MB  {'; '.join(findings)}", flush=True)
    server.shutdown()
    (args.out / "results.json").write_text(json.dumps(rows, indent=1), encoding="utf-8")
    print(f"[hostile] {len(rows)} cases, {failed} with findings", flush=True)
    return 1 if (failed and args.fail_on_finding) else 0


if __name__ == "__main__":
    sys.exit(main())
