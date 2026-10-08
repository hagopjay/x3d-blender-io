# SPDX-FileCopyrightText: 2026 OpenAI
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
