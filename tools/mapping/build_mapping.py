# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the X3D half of the mapping table and docs/MAPPING.md (plain Python; needs the x3d package, x3d.py).

    python tools/mapping/build_mapping.py SUITE_OUT [--out mapping/x3d_fields.json] [--doc docs/MAPPING.md] [--check]

Rows come from the standard, not from the code: one row per node of x3d.py 4.0.65.8 and one per field of each node
(the v3 plan's R6: "the mapping table is sized to the standard"). Each row then says what this add-on does with it:

  export   written      the suite's exports (SUITE_OUT/*.x3d, tests/suite) contain this element / attribute
           default_only the element is written but this field never appears in the corpus with a value
           not_written  the export never writes the element
  import   (node level, from tools/io_sync/parity.json for the nodes the export writes, otherwise "named" when the node's
           name appears as a string in source/import_x3d.py, else "none"); field level "named" when the field's name is
           read with getField*/getFieldAs* anywhere in the importer. Static, so graded Suspected; the import-side sweep
           replaces it.
  class    exact | equivalent | lossy (parity.json round_trip of a written node, per written field) | default_only |
           import_only | not_supported | not_applicable (inputOnly / outputOnly event fields, which no file stores)

``--check`` regenerates in memory and exits 1 when the committed table or doc differ: the table must change in the
same pull request as the code (v2 gate rule "a feature lands with its rows"). The Blender half lives in
source/mapping/blender_rna.json (it ships with the add-on: the loss receipt reads it); this script copies its counts
into the doc.
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import inspect
import json
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCHEMA = "x3d-blender-io.mapping-x3d/1"
STATEMENTS_WRITTEN = {"X3D", "head", "component", "meta", "Scene", "ROUTE", "unit", "field", "fieldValue", "IS",
                      "connect", "ProtoDeclare", "ProtoInterface", "ProtoBody", "ExternProtoDeclare", "IMPORT", "EXPORT"}
STRUCTURAL_ATTRIBUTES = {"DEF", "USE", "containerField", "class", "id", "style"}
SKIP_FIELDS = {"IS", "_parentNode", "_containerField", "metadata"}


def x3d_nodes():
    import x3d

    nodes, statements = {}, {}
    for name, cls in inspect.getmembers(x3d, inspect.isclass):
        if name.startswith("_") or not hasattr(cls, "FIELD_DECLARATIONS"):
            continue
        try:
            decls = cls.FIELD_DECLARATIONS()
        except Exception:
            continue
        bases = [b.__name__ for b in cls.__mro__]
        fields = {}
        for fname, default, ftype, access, owner in decls:
            if fname in SKIP_FIELDS:
                continue
            xml_name = fname[:-1] if fname.endswith("_") else fname
            fields[xml_name] = {"type": ftype.__name__, "access": access.__name__, "default": _jsonable(default),
                                "declared_by": owner}
        entry = {"abstract_bases": [b for b in bases if b.startswith("_X3D")], "fields": fields}
        (nodes if "_X3DNode" in bases else statements)[name] = entry
    return nodes, statements, getattr(x3d, "__version__", None) or _x3d_version()


def _x3d_version():
    try:
        from importlib.metadata import version

        return version("x3d")
    except Exception:
        return None


def _jsonable(value):
    if isinstance(value, (bool, int, float, str)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return str(value)


def container_defaults():
    """{node: default containerField} from x3d.py, so a child element counts as its parent's SFNode/MFNode field."""
    import x3d

    out = {}
    for name, cls in inspect.getmembers(x3d, inspect.isclass):
        try:
            for fname, default, *_ in cls.FIELD_DECLARATIONS():
                if fname == "_containerField":
                    out[name] = default
        except Exception:
            continue
    return out


def corpus(paths):
    """{element: {"count": n, "attrs": Counter}} over every .x3d under ``paths``; a child element is counted as the
    parent's field named by its containerField (explicit, else x3d.py's default for the child)."""
    defaults = container_defaults()
    seen = defaultdict(lambda: {"count": 0, "attrs": Counter(), "children": Counter()})
    files = []
    for arg in paths:
        p = Path(arg)
        files += sorted(p.glob("*.x3d")) if p.is_dir() else [p]   # the export's own files, not copied references
    for f in files:
        data = f.read_bytes()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        for el in ET.fromstring(data).iter():
            if not isinstance(el.tag, str):
                continue
            tag = el.tag.split("}")[-1]
            seen[tag]["count"] += 1
            for attr in el.attrib:
                seen[tag]["attrs"][attr.split("}")[-1]] += 1
            for child in el:
                if isinstance(child.tag, str):
                    ctag = child.tag.split("}")[-1]
                    field = child.attrib.get("containerField") or defaults.get(ctag)
                    if field:
                        seen[tag]["children"][field] += 1
    return seen, [f.name for f in files]


def importer_names():
    text = (REPO / "source" / "import_x3d.py").read_text(encoding="utf-8")
    strings = set(re.findall(r"['\"]([A-Za-z][A-Za-z0-9_]*)['\"]", text))
    fields = set(re.findall(r"getField(?:As\w+)?\(\s*['\"]([A-Za-z][A-Za-z0-9_]*)['\"]", text))
    return strings, fields


def build(suite_out):
    nodes, statements, x3d_version = x3d_nodes()
    seen, files = corpus(suite_out)
    parity = json.loads((REPO / "tools" / "io_sync" / "parity.json").read_text())["nodes"]
    import_strings, import_fields = importer_names()
    rows = {}
    counts = Counter()
    field_counts = Counter()
    for name in sorted(nodes):
        decl = nodes[name]
        written = name in seen
        par = parity.get(name)
        node_import = (par or {}).get("import") if par else ("named" if name in import_strings else "none")
        if written:
            node_class = (par or {}).get("round_trip", "undeclared")
        elif node_import != "none":
            node_class = "import_only"
        else:
            node_class = "not_supported"
        counts[node_class] += 1
        frows = {}
        attrs = (seen[name]["attrs"] + seen[name]["children"]) if written else Counter()
        for fname, f in sorted(decl["fields"].items()):
            if f["access"] in ("inputOnly", "outputOnly"):
                cls, export = "not_applicable", "not_written"
            elif written and fname in attrs:
                cls, export = node_class if node_class in ("exact", "equivalent", "lossy") else node_class, "written"
            elif written:
                cls, export = "default_only", "default_only"
            else:
                cls, export = node_class, "not_written"
            fimport = "named" if (node_import != "none" and fname in import_fields) else ("structural" if fname in
                                                                                          STRUCTURAL_ATTRIBUTES else "none")
            frows[fname] = {"type": f["type"], "access": f["access"], "default": f["default"], "export": export,
                            "import": fimport, "class": cls}
            field_counts[cls] += 1
        rows[name] = {"class": node_class, "export": "written" if written else "not_written", "import": node_import,
                      "note": (par or {}).get("note"),
                      "fields": frows}
    stmt_rows = {}
    for name in sorted(statements):
        stmt_rows[name] = {"export": "written" if name in seen else "not_written",
                           "attributes_written": sorted(seen[name]["attrs"]) if name in seen else []}
    undeclared_attrs = []
    for tag, info in sorted(seen.items()):
        known = set(nodes.get(tag, statements.get(tag, {"fields": {}}))["fields"]) | STRUCTURAL_ATTRIBUTES
        if tag in ("X3D",):
            known |= {"version", "profile", "noNamespaceSchemaLocation", "xsd"}
        for attr in sorted(info["attrs"]):
            if attr not in known:
                undeclared_attrs.append(f"{tag}@{attr}")
    blender = json.loads((REPO / "source" / "mapping" / "blender_rna.json").read_text())
    return {
        "schema": SCHEMA,
        "about": ("The X3D half of the mapping table: every node and field of X3D 4.0 as x3d.py declares it, and what this "
                  "add-on's X3D 4.0 export and import do with it. Generated by tools/mapping/build_mapping.py; do not edit "
                  "by hand. Field classes: see the script's docstring."),
        "instruments": {"x3d.py": x3d_version, "corpus": files, "parity": "tools/io_sync/parity.json",
                        "importer_scan": "source/import_x3d.py string literals (Suspected)"},
        "totals": {"nodes": len(nodes), "fields": sum(len(n["fields"]) for n in nodes.values()),
                   "statements": len(statements), "node_classes": dict(sorted(counts.items())),
                   "field_classes": dict(sorted(field_counts.items())),
                   "nodes_written": sum(1 for r in rows.values() if r["export"] == "written"),
                   "fields_written": sum(1 for r in rows.values() for f in r["fields"].values() if f["export"] == "written"),
                   "blender_rows": len(blender["rows"]), "blender_patterns": len(blender["patterns"])},
        "attributes_not_in_x3d_py": undeclared_attrs,
        "nodes": rows,
        "statements": stmt_rows,
    }


CLASS_ORDER = ["exact", "equivalent", "lossy", "undeclared", "unmeasured", "import_only", "default_only",
               "not_applicable", "not_supported"]


def render_doc(table):
    t = table["totals"]
    blender = json.loads((REPO / "source" / "mapping" / "blender_rna.json").read_text())
    bcounts = Counter(r["class"] for r in blender["rows"])
    bgrades = Counter(r["grade"] for r in blender["rows"])
    lines = [
        "# Mapping table v1",
        "",
        "Generated by `tools/mapping/build_mapping.py` from x3d.py "
        f"{table['instruments']['x3d.py']} and the export suite's files; CI fails when this page or "
        "`mapping/x3d_fields.json` is out of date. The Blender half is `source/mapping/blender_rna.json`, checked by the "
        "perturbation sweep (`tools/io_sync/perturb.py --check`).",
        "",
        "## X3D side",
        "",
        f"{t['nodes']} nodes and {t['fields']} fields (x3d.py {table['instruments']['x3d.py']}; plus {t['statements']} "
        f"statements). The export writes {t['nodes_written']} nodes and {t['fields_written']} fields in the corpus "
        f"({', '.join(table['instruments']['corpus'])}).",
        "",
        "| Node class | Nodes | Fields |",
        "|---|---:|---:|",
    ]
    fc = Counter()
    for row in table["nodes"].values():
        fc[row["class"]] += len(row["fields"])
    for cls in CLASS_ORDER:
        if t["node_classes"].get(cls):
            lines.append(f"| {cls} | {t['node_classes'][cls]} | {fc[cls]} |")
    lines += ["", "| Field class | Fields |", "|---|---:|"]
    for cls in CLASS_ORDER:
        if t["field_classes"].get(cls):
            lines.append(f"| {cls} | {t['field_classes'][cls]} |")
    lines += ["", "### Nodes the export writes", "",
              "| Node | Round trip | Import | Fields written | Fields default only |", "|---|---|---|---:|---:|"]
    for name, row in sorted(table["nodes"].items()):
        if row["export"] != "written":
            continue
        fw = sum(1 for f in row["fields"].values() if f["export"] == "written")
        fd = sum(1 for f in row["fields"].values() if f["export"] == "default_only")
        lines.append(f"| {name} | {row['class']} | {row['import']} | {fw} | {fd} |")
    lines += ["", "### Nodes read on import only (named in the importer's source; Suspected)", ""]
    lines.append(", ".join(n for n, r in sorted(table["nodes"].items()) if r["class"] == "import_only") or "none")
    lines += ["", "## Blender side", "",
              f"{len(blender['rows'])} rows and {len(blender['patterns'])} pattern rows over the probe's datablocks "
              f"({blender['probe']['scope']}); measured with {blender['probe']['instrument']} on Blender "
              f"{blender['probe']['measured_on'].get('blender')} in {len(blender['probe']['states'])} starting states.",
              "", "| Class | Rows |", "|---|---:|"]
    for cls in ("carried", "approximated", "clamped", "dropped", "editor_only"):
        lines.append(f"| {cls} | {bcounts.get(cls, 0)} |")
    lines += ["", "| Grade of the class claim | Rows |", "|---|---:|"]
    for grade in ("Confirmed", "Likely", "Suspected"):
        lines.append(f"| {grade} | {bgrades.get(grade, 0)} |")
    lines += ["", "### Losses with a receipt entry", "", "| Row | Class | Rule | Reason |", "|---|---|---|---|"]
    for row in blender["rows"]:
        if row.get("receipt"):
            rule = dict(row["receipt"])
            lines.append(f"| `{row['id']}` | {row['class']} | `{json.dumps(rule, sort_keys=True)}` | {row['reason']} |")
    lines += ["", "### Dropped with no per-scene entry", "", "| Row | Why no entry |", "|---|---|"]
    for row in blender["rows"]:
        if row["class"] == "dropped" and not row.get("receipt"):
            lines.append(f"| `{row['id']}` | {row.get('why_no_receipt', '')} |")
    lines.append("")
    return "\n".join(lines)


def dump(table):
    """The table as JSON with one line per node, so a pull request's diff shows which nodes changed."""
    head = {k: v for k, v in table.items() if k not in ("nodes", "statements")}
    out = ["{"]
    for key, value in head.items():
        out.append(f" {json.dumps(key)}: {json.dumps(value, sort_keys=False)},")
    for section in ("nodes", "statements"):
        out.append(f" {json.dumps(section)}: {{")
        items = list(table[section].items())
        for i, (name, row) in enumerate(items):
            out.append(f"  {json.dumps(name)}: {json.dumps(row, separators=(',', ':'))}{',' if i < len(items) - 1 else ''}")
        out.append(" }," if section == "nodes" else " }")
    out.append("}")
    return "\n".join(out) + "\n"


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("suite_out", nargs="+")
    p.add_argument("--out", default=str(REPO / "mapping" / "x3d_fields.json"))
    p.add_argument("--doc", default=str(REPO / "docs" / "MAPPING.md"))
    p.add_argument("--check", action="store_true")
    args = p.parse_args(argv)
    table = build(args.suite_out)
    text = dump(table)
    doc = render_doc(table)
    if args.check:
        bad = []
        for path, new in ((args.out, text), (args.doc, doc)):
            old = Path(path).read_text(encoding="utf-8") if Path(path).exists() else ""
            if old != new:
                bad.append(path)
        if table["attributes_not_in_x3d_py"]:
            print("attributes the export writes that X3D 4.0 does not declare:", table["attributes_not_in_x3d_py"])
            bad.append("attributes_not_in_x3d_py")
        if table["totals"]["node_classes"].get("undeclared"):
            print("written nodes with no parity.json row:",
                  [n for n, r in table["nodes"].items() if r["class"] == "undeclared"])
            bad.append("undeclared nodes")
        for path in bad:
            print(f"out of date: {path} (run tools/mapping/build_mapping.py {' '.join(args.suite_out)})")
        print(f"[mapping] {table['totals']['nodes']} nodes, {table['totals']['fields']} fields; "
              f"{table['totals']['nodes_written']} nodes and {table['totals']['fields_written']} fields written; "
              f"{'FAIL' if bad else 'PASS'}")
        return 1 if bad else 0
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text, encoding="utf-8")
    Path(args.doc).write_text(doc, encoding="utf-8")
    print(f"[mapping] wrote {args.out} ({len(text):,} bytes, sha256 {hashlib.sha256(text.encode()).hexdigest()[:12]}) "
          f"and {args.doc}")
    print(json.dumps(table["totals"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
