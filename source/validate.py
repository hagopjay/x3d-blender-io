# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from dataclasses import dataclass, field
from xml.etree.ElementTree import ParseError
from xml.etree import ElementTree as ET


@dataclass(slots=True)
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validate_xml_file(filepath: str) -> ValidationResult:
    try:
        tree = ET.parse(filepath)
    except ParseError as exc:
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

    return ValidationResult(valid=True, warnings=warnings)


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
        tree = ET.parse(filepath)
    except ParseError as exc:
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
        return text.lower() == "true"
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
    if field_type.startswith("SF"):
        if field_type in {"SFFloat", "SFDouble", "SFTime", "SFInt32"}:
            return numbers[0] if numbers else 0
        return tuple(numbers)
    width = (("ColorRGBA", 4), ("Color", 3), ("Vec2", 2), ("Vec3", 3), ("Vec4", 4), ("Rotation", 4))
    for key, size in width:
        if key in field_type and "Matrix" not in field_type:
            return [tuple(numbers[index:index + size]) for index in range(0, len(numbers), size)]
    return numbers


def validate_tree_with_x3d_py(root, x3d_module) -> ValidationResult:
    errors: list[str] = []
    warnings: list[str] = []

    def visit(element):
        tag = element.tag
        if tag in {"X3D", "head", "meta", "component", "unit", "Scene"}:
            for child in element:
                visit(child)
            return
        node_class = getattr(x3d_module, tag, None)
        if node_class is None:
            warnings.append(f"<{tag}>: unknown X3D node")
            return
        if "USE" not in element.attrib:
            declared = {}
            try:
                declared = {entry[0]: entry for entry in node_class.FIELD_DECLARATIONS()}
            except Exception:
                declared = {}
            for name, value in element.attrib.items():
                if name in _SKIP_ATTRIBUTES:
                    continue
                if name not in declared:
                    warnings.append(f"<{tag}>: unknown field {name!r}")
                    continue
                try:
                    node_class(**{name: _coerce_field(value, declared[name])})
                except SystemExit as exc:  # x3d.py halts on some HAnim problems
                    errors.append(f"<{tag} {name}=...>: x3d.py halted ({exc})")
                except Exception as exc:
                    errors.append(f"<{tag} {name}=...>: {exc}")
        for child in element:
            visit(child)

    visit(root)
    return ValidationResult(valid=not errors, errors=errors, warnings=warnings)
