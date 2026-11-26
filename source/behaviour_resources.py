# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The outside world a behaviour graph loads from: which URL loads, which fails, how long each takes, how long a medium lasts.

X3D leaves loading to the browser, so a simulator has to be told. ``Resources`` is that telling: a table from a URL, as
the file writes it, to what happens when something asks for it.

    Resources({"tone.wav": {"loads": 0.4, "duration": 1.0},      # ready 0.4 s after it is asked for; lasts 1 s
               "gone.png": {"fails": 0.2}})                       # refused 0.2 s after it is asked for

The table is part of the stimulus: a recording (``x3d.activity/1``, optional ``resources`` block) carries it, so a run is
reproducible. A URL the table does not name "loads at once with unknown duration" (-1, as the standard says for an unknown
duration); every such lookup is counted in ``Simulation.noted["assumed-loaded"]``, never silently.

A node's ``url`` is a list: X3D tries them in order and the first that loads wins, so a list costs the time of every
failure before it. ``resolve`` returns that outcome. Nothing here knows about Blender, a browser or a clock: the seconds
are counted from the moment the simulation asked.

Hostile tables never raise: an entry that is not a mapping, a time that is not a finite number of seconds, a name that is
not text, is dropped and listed in ``Resources.rejected``.
"""

from __future__ import annotations

import math

MAX_ENTRIES = 100_000        # a table is a stimulus, not a database; a bigger one is cut here and said so in ``rejected``


def _seconds(value):
    """``value`` as seconds (a finite number of zero or more), or None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0.0 else None


class Resources:
    """URL -> {"loads": seconds} or {"fails": seconds}, and for a medium {"duration": seconds}. See the module text."""

    __slots__ = ("table", "rejected")

    def __init__(self, table=None):
        self.table = {}
        self.rejected = []
        if isinstance(table, Resources):
            table = table.to_dict()
        if isinstance(table, dict):
            for url, entry in table.items():
                if len(self.table) >= MAX_ENTRIES:
                    self.rejected.append("more than %d entries: the rest were left out" % MAX_ENTRIES)
                    break
                self._add(url, entry)
        elif table is not None:
            self.rejected.append(f"a table is a mapping from URL to entry, not {type(table).__name__}")

    def _add(self, url, entry):
        if not isinstance(url, str):
            self.rejected.append(f"{url!r} is not a URL")
            return
        if not isinstance(entry, dict):
            self.rejected.append(f"{url!r}: an entry is a mapping, not {type(entry).__name__}")
            return
        kinds = [kind for kind in ("loads", "fails") if kind in entry]
        clean = {}
        if len(kinds) == 2:
            self.rejected.append(f"{url!r}: says both loads and fails; fails stands")
            kinds = ["fails"]
        for kind in kinds:
            seconds = _seconds(entry[kind])
            if seconds is None:
                self.rejected.append(f"{url!r}: {kind} is not a finite number of seconds; the entry was left out")
                return
            clean[kind] = seconds
        if "duration" in entry:
            duration = _seconds(entry["duration"])
            if duration is None:
                self.rejected.append(f"{url!r}: duration is not a finite number of seconds; it was left out")
            elif "fails" not in clean:
                clean.setdefault("loads", 0.0)           # a duration alone is a medium that is ready at once
                clean["duration"] = duration
        if not clean:
            self.rejected.append(f"{url!r}: the entry says neither loads nor fails; it was left out")
            return
        self.table[url] = clean

    # -- plain data ------------------------------------------------------------------------------------------

    def to_dict(self):
        """The table as plain data (what a recording holds): {url: {"loads"|"fails": s, "duration": s}}."""
        return {url: dict(entry) for url, entry in sorted(self.table.items())}

    @classmethod
    def from_dict(cls, data):
        """A table from plain data; ``None`` (an old recording with no block) is an empty table."""
        return cls(data)

    def __bool__(self):
        return bool(self.table)

    def __eq__(self, other):
        return isinstance(other, Resources) and self.table == other.table

    def __repr__(self):
        return f"Resources({self.to_dict()!r})"

    # -- what asking for a list of URLs costs ----------------------------------------------------------------

    def resolve(self, urls):
        """What happens when a node with this ``url`` list asks to load: (loaded, seconds, duration, assumed).

        The URLs are tried in order. A URL the table says fails costs its ``fails`` seconds and the next is tried; the
        first the table says loads (or does not name: it loads at once, ``assumed``) ends it, at the sum of the seconds so
        far plus its own. All failing is (False, total seconds, -1.0, False). ``duration`` is the winning entry's, or -1
        for unknown. A list with nothing in it never reaches here (nothing is asked for)."""
        total, table = 0.0, self.table
        for url in urls:
            entry = table.get(url) if isinstance(url, str) else None
            if entry is None:
                return True, total, -1.0, True
            if "fails" in entry:
                total += entry["fails"]
                continue
            return True, total + entry["loads"], entry.get("duration", -1.0), False
        return False, total, -1.0, False
