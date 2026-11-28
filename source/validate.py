# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

import gzip
import keyword
import math
import re
from dataclasses import dataclass, field
from xml.etree.ElementTree import ParseError
from xml.etree import ElementTree as ET

try:
    from .x3d_nodes import FIELD_TYPES, KNOWN_ELEMENTS
except ImportError:  # tests and tools import the source folder as top-level modules
    from x3d_nodes import FIELD_TYPES, KNOWN_ELEMENTS

_GZIP_MAGIC = b"\x1f\x8b"


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _parse_file(filepath: str) -> ET.ElementTree:
    """Parse an .x3d file, reading a gzip-compressed one (x3dz) transparently by its magic bytes."""
    with open(filepath, "rb") as handle:
        head = handle.read(2)
    if head == _GZIP_MAGIC:
        with gzip.open(filepath, "rb") as handle:
            return ET.ElementTree(ET.fromstring(handle.read()))
    return ET.parse(filepath)


def validate_xml_file(filepath: str) -> ValidationResult:
    try:
        tree = _parse_file(filepath)
    except (ParseError, OSError, EOFError, gzip.BadGzipFile) as exc:
        return ValidationResult(valid=False, errors=[f"XML parse error: {exc}"])

    return validate_xml_tree(tree)


def validate_xml_text(xml_text: str) -> ValidationResult:
    try:
        root = ET.fromstring(xml_text)
    except ParseError as exc:
        return ValidationResult(valid=False, errors=[f"XML parse error: {exc}"])

    return validate_xml_tree(ET.ElementTree(root))


def validate_xml_tree(tree: ET.ElementTree) -> ValidationResult:
    root = tree.getroot()

    if root.tag != "X3D":
        return ValidationResult(valid=False, errors=[f"Unexpected root node: {root.tag}"])

    if root.attrib.get("version") not in {"4.0", "4.1", "3.3", "3.0"}:
        return ValidationResult(valid=False, errors=[f"Unsupported X3D version: {root.attrib.get('version')}"])

    warnings = []
    if root.find("Scene") is None:
        warnings.append("No Scene element found.")

    errors = unknown_element_errors(root) + field_value_errors(root)
    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)


_REAL = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?\Z")
_INTEGER = re.compile(r"[+-]?(?:\d+|0[xX][0-9a-fA-F]+)\Z")
_BOOLEAN = {"true", "false", "TRUE", "FALSE"}


def _bad_tokens(value: str, kind: str) -> list[str]:
    bad = []
    for token in value.replace(",", " ").split():
        if kind == "b":
            ok = token in _BOOLEAN
        elif kind == "i":
            ok = _INTEGER.match(token) is not None
        else:
            ok = _REAL.match(token) is not None and math.isfinite(float(token))
        if not ok:
            bad.append(token)
    return bad


def field_value_errors(root) -> list[str]:
    """Check the attributes whose X3D type is boolean, integer or real, by node and field name.

    Strings are left alone, so ``title="Infinity"``, ``<meta content="NaN">`` and ``DEF="inf"`` stay legal; a real field
    must hold finite decimal numbers (``1e999`` overflows and is refused, as are ``nan`` and ``inf``), an integer field
    whole numbers, a boolean field ``true`` or ``false``. One error per node and field, with the first bad token.
    """
    errors = []
    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str) or "USE" in element.attrib:
            continue
        declared = _field_kinds(tag)
        for name, value in element.attrib.items():
            kind = declared.get(name)
            if kind is None:
                continue
            bad = _bad_tokens(value, kind)
            if bad:
                what = {"b": "boolean", "i": "integer", "f": "finite real"}[kind]
                label = "Non-finite number" if kind == "f" and bad[0].lstrip("+-").lower() in ("nan", "inf", "infinity") \
                    else "Invalid value"
                errors.append(f"{label} {bad[0]!r} in <{tag} {name}> (expected {what})")
    return errors


_KIND_CACHE: dict[str, dict[str, str]] = {}


def _field_kinds(tag: str) -> dict[str, str]:
    kinds = _KIND_CACHE.get(tag)
    if kinds is None:
        kinds = dict(item.split(":") for item in FIELD_TYPES.get(tag, "").split(",") if item)
        _KIND_CACHE[tag] = kinds
    return kinds


def unknown_element_errors(root) -> list[str]:
    """One error per distinct element name that is not an X3D node or structural element (``<Banana>``)."""
    seen: dict[str, int] = {}
    for element in root.iter():
        tag = element.tag
        if not isinstance(tag, str):  # comments and processing instructions
            continue
        if tag not in KNOWN_ELEMENTS:
            seen[tag] = seen.get(tag, 0) + 1
    return [f"Unknown X3D element <{tag}> ({count}x)" for tag, count in sorted(seen.items())]


def validate_with_x3d_py(filepath: str) -> ValidationResult | None:
    """Semantic check through the Web3D ``x3d`` Python package when installed.

    Returns None when the package is unavailable so callers can treat the
    check as optional. Field-type and range assertions in x3d.py surface as
    errors; unknown nodes or fields surface as warnings.
    """

    try:
        import x3d.x3d as x3d_module  # noqa: F401
    except Exception:
        return None
    try:
        from x3d.x3d import X3D as _X3D  # noqa: F401
    except Exception:
        return None
    try:
        import xml.etree.ElementTree as ET
    except Exception:  # pragma: no cover
        return None
    try:
        tree = _parse_file(filepath)
    except (ParseError, OSError, EOFError, gzip.BadGzipFile) as exc:
        return ValidationResult(valid=False, errors=[f"XML parse error: {exc}"])
    return validate_tree_with_x3d_py(tree.getroot(), x3d_module)


_SKIP_ATTRIBUTES = {"DEF", "USE", "containerField", "class", "id", "style"}


def _coerce_field(value: str, declaration):
    """Turn an attribute string into the Python value x3d.py expects."""
    field_type = declaration[2] if len(declaration) > 2 else ""
    if callable(field_type):  # x3d.py stores FieldType.SFVec3f etc. as functions
        field_type = getattr(field_type, "__name__", str(field_type))
    text = value.strip()
    if field_type == "SFBool":
        # X3D's XML encoding spells SFBool true or false only. lower() == "true" read "TRUE", "1" and "yes" as false
        # and passed them, though the importer crashed on two of them (chaos round, 22 Nov 2026)
        if text not in ("true", "false"):
            raise ValueError(f"{value!r} is not an SFBool (true or false)")
        return text == "true"
    if field_type == "MFBool":
        # MFBool was read as numbers, so every MetadataBoolean (value='true false') failed the semantic check with
        # "could not convert string to float: 'true'" and the export was refused (receipt-to-rule engine, 23 Nov 2026)
        tokens = text.replace(",", " ").split()
        bad = [token for token in tokens if token not in ("true", "false")]
        if bad:
            raise ValueError(f"{bad[0]!r} is not an MFBool value (true or false)")
        return [token == "true" for token in tokens]
    if field_type == "SFString":
        return value
    if field_type == "MFString":
        parts = []
        current = []
        in_quote = False
        escaped = False
        for char in text:
            if escaped:
                current.append(char)
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                if in_quote:
                    parts.append("".join(current))
                    current = []
                in_quote = not in_quote
            elif in_quote:
                current.append(char)
        return parts
    numbers = [float(token) for token in text.replace(",", " ").split()]
    if field_type.startswith("SFInt") or field_type.startswith("MFInt"):
        numbers = [int(number) for number in numbers]
    width = (("ColorRGBA", 4), ("Color", 3), ("Vec2", 2), ("Vec3", 3), ("Vec4", 4), ("Rotation", 4), ("Quaternion", 4))
    size = next((n for key, n in width if key in field_type and "Matrix" not in field_type), None)
    if field_type.startswith("SF"):
        if field_type in {"SFFloat", "SFDouble", "SFTime", "SFInt32"}:
            if len(numbers) != 1:
                raise ValueError(f"{value!r} has {len(numbers)} numbers; {field_type} takes 1")
            return numbers[0]
        # x3d.py 4.0.65.8's assertValidSFVec3f and its kin accept a tuple of any length (Box(size=(1, 1)) writes
        # size='1 1'), so the width is checked here
        if size is not None and len(numbers) != size:
            raise ValueError(f"{value!r} has {len(numbers)} numbers; {field_type} takes {size}")
        return tuple(numbers)
    if size is not None:
        if len(numbers) % size:
            raise ValueError(f"{len(numbers)} numbers is not a whole number of {field_type} values ({size} each)")
        return [tuple(numbers[index:index + size]) for index in range(0, len(numbers), size)]
    return numbers


def _each_enumeration_value_valid(node_class, py_name, coerced, exc) -> bool:
    """x3d.py 4.0.65.8 checks an MFString enumeration field as one string against its single-value choices, so a field
    that lists several allowed values (CollisionCollection appliedParameters '"BOUNCE" "FRICTION_COEFFICIENT_2"', which
    the standard allows) was refused. Such a field is valid when each of its values is."""
    if "does not match allowed enumerations" not in str(exc) or not isinstance(coerced, (list, tuple)) or len(coerced) < 2:
        return False
    try:
        for item in coerced:
            node_class(**{py_name: [item]})
    except Exception:
        return False
    return True


def validate_tree_with_x3d_py(root, x3d_module) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    def check(element):
        tag = element.tag
        node_class = getattr(x3d_module, tag, None)
        if node_class is None:
            warnings.append(f"<{tag}>: unknown X3D node")
            return False
        if "USE" not in element.attrib:
            declared = {}
            try:
                declared = {entry[0]: entry for entry in node_class.FIELD_DECLARATIONS()}
            except Exception:
                declared = {}
            for name, value in element.attrib.items():
                if name in _SKIP_ATTRIBUTES:
                    continue
                # x3d.py appends "_" to fields named after Python keywords (global -> global_)
                py_name = name + "_" if keyword.iskeyword(name) else name
                if py_name not in declared:
                    warnings.append(f"<{tag}>: unknown field {name!r}")
                    continue
                coerced = None
                try:
                    coerced = _coerce_field(value, declared[py_name])
                    node_class(**{py_name: coerced})
                except SystemExit as exc:  # x3d.py halts on some HAnim problems
                    errors.append(f"<{tag} {name}=...>: x3d.py halted ({exc})")
                except Exception as exc:
                    if not _each_enumeration_value_valid(node_class, py_name, coerced, exc):
                        errors.append(f"<{tag} {name}=...>: {exc}")
        return True

    # An explicit stack, not recursion: a scene nested 1,200 Groups deep (legal X3D) raised RecursionError here, so
    # the validator crashed instead of answering (chaos round, 22 Nov 2026). Children are visited in document order.
    stack = [root]
    while stack:
        element = stack.pop()
        if element.tag in {"X3D", "head", "meta", "component", "unit", "Scene"} or check(element):
            stack.extend(reversed(list(element)))
    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
