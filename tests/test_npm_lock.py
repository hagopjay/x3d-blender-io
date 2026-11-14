# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The fidelity rig's Node install is reproducible: tools/fidelity_rig/package.json pins exact versions, the committed
package-lock.json matches them and carries an integrity hash for every downloaded package, and the lock is not git-ignored.
Standard library only (the CI unit job installs ruff and x3d, nothing else); no node, no network, no Blender.

    cd tests && python -m unittest test_npm_lock
"""

from __future__ import annotations

import fnmatch
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RIG = ROOT / "tools" / "fidelity_rig"
LOCK_REL = "tools/fidelity_rig/package-lock.json"
DEP_SECTIONS = ("dependencies", "devDependencies", "optionalDependencies", "peerDependencies")

# A plain semver version, a pre-release such as 2.0.0-dev.3.10 allowed, and nothing else: no range operator, wildcard, tag, URL or alias.
EXACT_VERSION = re.compile(r"^\d+\.\d+\.\d+(-[0-9A-Za-z][0-9A-Za-z.-]*)?(\+[0-9A-Za-z.-]+)?\Z")


def _json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def _ignored_by(gitignore_text, rel_path):
    """Whether the .gitignore text (read as plain text, no git) ignores rel_path, a '/'-separated path from the .gitignore's folder.

    Covers what a lock file's ignore line can look like: plain names and globs, a leading or inner '/' (anchored), a trailing '/'
    (directories only), '!' re-includes, and the rule that nothing inside an ignored directory can be re-included.
    '**' is read as '*' and fnmatch's '*' also crosses '/', so this errs towards "ignored", never towards "fine"."""
    rules = []
    for raw in gitignore_text.splitlines():
        line = raw.rstrip()
        if not line or line.startswith("#"):
            continue
        negate = line.startswith("!")
        pat = line[1:] if negate else line
        dir_only = pat.endswith("/")
        pat = pat.rstrip("/")
        anchored = "/" in pat
        pat = pat.lstrip("/")
        if pat:
            rules.append((negate, dir_only, anchored, pat))

    parts = rel_path.split("/")
    for i in range(1, len(parts) + 1):
        is_dir = i < len(parts)
        sub = "/".join(parts[:i])
        verdict = False
        for negate, dir_only, anchored, pat in rules:
            if dir_only and not is_dir:
                continue
            hit = fnmatch.fnmatchcase(sub, pat) if anchored else fnmatch.fnmatchcase(parts[i - 1], pat)
            if hit:
                verdict = not negate
        if verdict:
            return True          # an ignored folder hides everything under it, so the first ignored step ends the walk
    return False


def _gitignore_files():
    """(.gitignore text, the lock's path relative to that file's folder) for the root and each folder down to the lock's."""
    out = []
    folder = ROOT
    rel = LOCK_REL.split("/")
    for i in range(len(rel)):
        f = folder / ".gitignore"
        if f.is_file():
            out.append((f.read_text(encoding="utf-8"), "/".join(rel[i:])))
        folder = folder / rel[i]
    return out


class PackageJsonPins(unittest.TestCase):
    def setUp(self):
        self.pkg = _json(RIG / "package.json")

    def test_there_are_dependencies_to_pin(self):
        self.assertTrue(self.pkg.get("dependencies"), "tools/fidelity_rig/package.json lists no dependencies")

    def test_every_dependency_is_an_exact_version(self):
        for section in DEP_SECTIONS:
            for name, spec in (self.pkg.get(section) or {}).items():
                self.assertRegex(spec, EXACT_VERSION, f"{section}.{name} is {spec!r}: pin an exact version (no ^ ~ * > < || x range, tag, URL or alias)")

    def test_exact_version_pattern_refuses_ranges(self):
        for good in ("16.7.1", "9.32.0", "2.0.0-dev.3.10", "1.63.0", "1.0.0+build.5"):
            self.assertRegex(good, EXACT_VERSION)
        for bad in ("^16.7.1", "~9.32.0", "*", "latest", "16.x", "16", ">=1.0.0", "1.0.0 - 2.0.0", "1.0.0 || 2.0.0", "", "file:../x",
                    "git+https://example.com/x.git", "npm:other@1.0.0", "1.0.0 ", "1.0.0\n", "v1.0.0"):
            self.assertNotRegex(bad, EXACT_VERSION)


class LockMatchesPackageJson(unittest.TestCase):
    def setUp(self):
        self.pkg = _json(RIG / "package.json")
        lock_path = RIG / "package-lock.json"
        self.assertTrue(lock_path.is_file(), "tools/fidelity_rig/package-lock.json is missing (run npm install --package-lock-only there)")
        self.lock = _json(lock_path)
        self.packages = self.lock.get("packages")
        self.assertIsInstance(self.packages, dict, "the lock has no 'packages' map: lockfileVersion 2 or 3 is needed")
        self.assertIn(self.lock.get("lockfileVersion"), (2, 3))

    def test_lock_root_names_the_same_dependencies_as_package_json(self):
        root = self.packages.get("")
        self.assertIsNotNone(root, "the lock has no root entry")
        self.assertEqual(root.get("name"), self.pkg.get("name"))
        for section in DEP_SECTIONS:
            self.assertEqual(root.get(section) or {}, self.pkg.get(section) or {}, f"{section} in the lock's root differs from package.json")

    def test_every_root_dependency_is_locked_at_its_pin(self):
        for section in DEP_SECTIONS:
            for name, pin in (self.pkg.get(section) or {}).items():
                entry = self.packages.get(f"node_modules/{name}")
                self.assertIsNotNone(entry, f"{name} has no entry in the lock")
                self.assertEqual(entry.get("version"), pin, f"{name} is locked at {entry.get('version')}, package.json pins {pin}")

    def test_every_downloaded_entry_has_an_integrity_hash(self):
        resolved = {k: e for k, e in self.packages.items() if k and "resolved" in e}
        self.assertTrue(resolved, "no lock entry has a resolved URL")
        for key, entry in resolved.items():
            self.assertTrue(entry.get("integrity"), f"{key} has a resolved URL but no integrity hash")
            self.assertRegex(entry["integrity"], r"^sha(256|384|512)-[A-Za-z0-9+/]+={0,2}$", f"{key}: integrity is not an SRI hash")

    def test_every_installed_entry_says_where_it_comes_from(self):
        for key, entry in self.packages.items():
            if not key or entry.get("inBundle"):
                continue
            self.assertIn("resolved", entry, f"{key} has no resolved URL, so npm ci has nothing to check an integrity hash against")

    def test_resolved_urls_are_https_downloads(self):
        for key, entry in self.packages.items():
            if key and "resolved" in entry:
                self.assertRegex(entry["resolved"], r"^https://", f"{key} resolves to {entry['resolved']!r}: no file:, git+ or http: sources")
            self.assertFalse(entry.get("link"), f"{key} is a link to a local folder")


class LockIsCommitted(unittest.TestCase):
    def test_gitignore_matcher_reads_the_patterns_it_must(self):
        lock = LOCK_REL
        for text in ("tools/fidelity_rig/package-lock.json\n", "/tools/fidelity_rig/package-lock.json\n", "package-lock.json\n", "*.json\n",
                     "*-lock.json\n", "tools/fidelity_rig/\n", "tools/\n", "/tools\n", "tools/fidelity_rig/*\n", "tools/*/package-lock.json\n",
                     "tools/fidelity_rig/package-lock.json   \n", "package-lock.json\n!package-lock.json.bak\n", "tools/\n!tools/fidelity_rig/package-lock.json\n"):
            self.assertTrue(_ignored_by(text, lock), f"the matcher missed {text!r}")
        for text in ("", "# package-lock.json\n", "tools/fidelity_rig/node_modules/\n", "tools/fidelity_rig/out/\n", "/package-lock.json\n",
                     "package-lock.json\n!tools/fidelity_rig/package-lock.json\n", "node_modules/\n", "*.zip\n"):
            self.assertFalse(_ignored_by(text, lock), f"the matcher flagged {text!r}")
        self.assertTrue(_ignored_by("tools/fidelity_rig/node_modules/\n", "tools/fidelity_rig/node_modules/x_ite/package.json"))

    def test_the_lock_is_not_gitignored(self):
        files = _gitignore_files()
        self.assertTrue(files, "no .gitignore found")
        for text, rel in files:
            self.assertFalse(_ignored_by(text, rel), f"a .gitignore ignores {LOCK_REL} (as {rel!r} in its folder): the lock must be committed")

    def test_node_modules_stay_ignored(self):
        root_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertTrue(_ignored_by(root_text, "tools/fidelity_rig/node_modules/x_ite/package.json"), "tools/fidelity_rig/node_modules must stay ignored")


if __name__ == "__main__":
    unittest.main()
