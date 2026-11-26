# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""LoadSensor, AudioClip and MovieTexture: the event nodes that wait on something outside the graph (class D).

Imported by ``behaviour_sim`` (at its end, which registers the machines); import ``behaviour_sim``, not this module.

What a load takes, and whether it works, comes from ``behaviour_resources.Resources`` (a table the caller declares; a URL
it does not name loads at once). The machines follow X_ITE 16.8.1, which decides where the standard leaves room
(tools/behaviour_resources_judge.py compares the two on real files). Where X_ITE differs from the standard's text it is
written down here, once, and in docs/BEHAVIOUR_EVENT_NODES.md:

* A load is never finished in the call that asked for it: the earliest is the next ``step``. (X_ITE fetches
  asynchronously.) Events a load causes carry the time of the step that finished it.
* ``url`` is a list tried in order; a URL that fails costs its time and the next is tried (``Resources.resolve``).
* A time-dependent medium follows X3DTimeDependentNode: ``startTime`` is acted on whether or not the node is active (a
  start while active changes nothing); ``stopTime <= startTime`` is ignored; ``pauseTime <= resumeTime`` and ``resumeTime
  <= pauseTime`` are ignored; a loop starts when ``stopTime <= startTime <= now``. The TimeSensor machine keeps its own
  rules (a startTime that arrives while it runs is ignored); the two are not the same code because they are not the same
  node's rules in X_ITE.
* The clock of a medium runs only once the medium has loaded. Started before that, the node is active at once and sends
  nothing more; when the medium arrives its elapsed time begins again at 0 (``elapsedTime`` 0 is sent) and it plays from
  the start. ``duration_changed`` is sent when the medium arrives (AudioClip: before its elapsed time restarts;
  MovieTexture: after), and -1 when a load fails or the node is unloaded.
* ``elapsedTime`` is sent on every step while the node is active, not paused and has its medium: now minus the start,
  minus the time spent paused (X_ITE measures a pause on the wall clock, the simulator on the clock it is given).
* A medium that is not looping ends on the first step its position is past its duration (not at it: X_ITE's audio and
  video clocks run a little behind the frame clock, so at exactly the duration the clip is still playing; in the probes 9
  ends in 10 fell where this puts them and one a frame earlier, and the judge allows that one frame): an AudioClip counts real seconds whatever its
  ``pitch`` (X_ITE's audio clock does not scale; the sound itself does), a MovieTexture counts media seconds that run at
  ``speed * max(pitch, 0)``. A duration of -1 (unknown) never ends by itself. ``elapsedTime`` is sent once more on the
  step that ends it, then ``isActive`` goes false.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET

try:
    from . import behaviour_graph as bg
    from .behaviour_sim import _Machine
except ImportError:  # imported as plain modules: tests, tools/
    import behaviour_graph as bg
    from behaviour_sim import _Machine

IDLE, LOADING, LOADED, FAILED = 0, 1, 2, 3       # X_ITE's NOT_STARTED, IN_PROGRESS, COMPLETE, FAILED states
RATE_LOW, RATE_HIGH = 0.0625, 16.0               # what a media element plays at (Chromium's range; outside it X_ITE falls back to 1)
SLACK = 1e-9                                     # seconds: a load due "at" a step's time is done at it, whatever the last bit of the sum says
URL_TYPES = ("ImageTexture", "Inline", "AudioClip", "MovieTexture")     # nodes a LoadSensor watches by their load state


def _count(sim, name):
    sim.noted[name] = sim.noted.get(name, 0) + 1


class _UrlObject(_Machine):
    """X3DUrlObject: ``url``, ``load`` and a load state. A ROUTE can set ``load`` and ``url`` while the scene runs.

    A scene node (ImageTexture, Inline, AudioClip, MovieTexture) kept where the scene has it: what a ROUTE sends it is
    also reported as a change (the Player lists it), and its own events travel on."""
    ticks = True
    records = True
    quiet = False               # a child only a LoadSensor knows has no ROUTEs: what it would send goes nowhere

    def setup(self):
        self.state, self.due, self.outcome, self.found = IDLE, None, False, -1.0
        self.watchers = []
        self.before = 0.0       # the step before the one that finished a load (X_ITE's clocks are anchored to it)

    def emit(self, name, value):
        if not self.quiet:
            self.sim._emit(self.id, name, value)

    # -- asking ----------------------------------------------------------------------------------------------

    def start(self, now):
        self.request(now)

    def request(self, now):
        """X3DUrlObject.requestImmediateLoad: nothing while it is loading or loaded (a failed load is not retried), nothing
        when ``load`` is false; no URL means unload; otherwise the load begins and ends as the table says."""
        if self.state in (LOADING, LOADED, FAILED) or not self.f["load"]:
            return
        urls = self.f["url"]
        if not urls:
            self.unload(now)
            return
        loaded, seconds, duration, assumed = self.sim.resources.resolve(urls)
        if assumed:
            _count(self.sim, "assumed-loaded")
        self.outcome, self.found = loaded, duration
        self.due = now + seconds
        self._state(LOADING, now)

    def unload(self, now):
        if self.state == IDLE:
            return
        self.due = None
        self.unloaded(now)
        self._state(IDLE, now)

    def unloaded(self, now):
        pass

    def _state(self, state, now):
        self.state = state
        for watcher in self.watchers:
            watcher.child_changed(self, now)

    def finish(self, now):
        self.due = None
        if self.outcome:
            self.arrived(now)
            self._state(LOADED, now)
        else:
            self.refused(now)
            self._state(FAILED, now)

    def arrived(self, now):
        pass

    def refused(self, now):
        pass

    # -- events and time -------------------------------------------------------------------------------------

    def changed(self, name, now):
        if name == "load":
            if self.f["load"]:
                self.request(now)
            else:
                self.unload(now)
        elif name == "url" and self.f["load"]:
            self.due = None
            self._state(IDLE, now)                 # X_ITE: not started again, then asked again (the old medium is dropped)
            self.replaced(now)
            self.request(now)

    def replaced(self, now):
        pass

    def tick(self, now, dt):
        if self.due is not None and now >= self.due - SLACK and self.state == LOADING:
            self.before = now - dt
            self.finish(now)


_FIRES = {"start": "_start", "pause": "_pause", "resume": "_resume", "stop": "_stop"}


class _Clock(_UrlObject):
    """X3DTimeDependentNode + X3DSoundSourceNode: a medium with startTime, stopTime, pauseTime, resumeTime and loop."""
    unit = "AudioClip"

    def setup(self):
        super().setup()
        self.active = self.paused = False
        self.medium = False                    # has the medium (a decoded clip) arrived
        self.begun, self.paused_at, self.paused_for = 0.0, 0.0, 0.0
        self.position, self.mark = 0.0, 0.0    # media seconds played, and when that was last brought up to date (a MovieTexture's clock)
        self.timers = {}                       # "start" | "pause" | "resume" | "stop" -> the time it fires (X_ITE's timeouts)

    # -- the medium ------------------------------------------------------------------------------------------

    def start(self, now):
        super().start(now)
        self._loop(now)

    def arrived(self, now):
        self._arrive(now)

    def _arrive(self, now):
        self.emit("duration_changed", self.found)
        self._media(now)

    def _media(self, now):
        """X3DSoundSourceNode.setMediaElement: the elapsed time starts again; an active node starts playing."""
        # the elapsed time is anchored to the frame before the one that delivered the medium: X_ITE finishes a load between
        # frames, with the last frame's time, so the first elapsedTime after "0" is one frame long
        self.medium, self.position, self.mark = True, 0.0, self.before
        self.begun, self.paused_at, self.paused_for = self.before, self.before, 0.0
        if self.active and not self.paused:
            self._played(self.before)

    def refused(self, now):
        self.medium = False
        self.emit("duration_changed", -1.0)

    def unloaded(self, now):
        self.medium = False
        self.emit("duration_changed", -1.0)

    def replaced(self, now):
        self.medium = False

    def _played(self, now):
        """set_start: the clip plays from its start; its elapsed time is 0."""
        if self.medium:
            self.position, self.mark = 0.0, now
            self.emit("elapsedTime", 0.0)

    # -- X3DTimeDependentNode ----------------------------------------------------------------------------------

    def changed(self, name, now):
        f = self.f
        if name == "enabled":
            if f["enabled"]:
                self._loop(now)
            else:
                self._stop(now)
        elif name == "loop":
            self._loop(now)
        elif name == "startTime":
            if f["enabled"]:
                self.timers.pop("start", None)
                if f["startTime"] <= now:
                    self._start(now)
                else:
                    self.timers["start"] = f["startTime"]
        elif name == "pauseTime":
            if f["enabled"]:
                self.timers.pop("pause", None)
                if f["pauseTime"] <= f["resumeTime"]:
                    return
                if f["pauseTime"] <= now:
                    self._pause(now)
                else:
                    self.timers["pause"] = f["pauseTime"]
        elif name == "resumeTime":
            if f["enabled"]:
                self.timers.pop("resume", None)
                if f["resumeTime"] <= f["pauseTime"]:
                    return
                if f["resumeTime"] <= now:
                    self._resume(now)
                else:
                    self.timers["resume"] = f["resumeTime"]
        elif name == "stopTime":
            if f["enabled"]:
                self.timers.pop("stop", None)
                if f["stopTime"] <= f["startTime"]:
                    return
                if f["stopTime"] <= now:
                    self._stop(now)
                else:
                    self.timers["stop"] = f["stopTime"]
        else:
            super().changed(name, now)

    def _loop(self, now):
        f = self.f
        if f["enabled"] and f["loop"] and f["stopTime"] <= f["startTime"] and f["startTime"] <= now:
            self._start(now)

    def _start(self, now):
        if not self.active:
            self.begun, self.paused_at, self.paused_for = now, now, 0.0
            self.active = True
            self.emit("isActive", True)
            if self.medium and not self.paused:
                self._played(now)

    def _pause(self, now):
        if self.active and not self.paused:
            self.paused = True
            self.emit("isPaused", True)
            self.paused_at = now

    def _resume(self, now):
        if self.active and self.paused:
            self.paused = False
            self.emit("isPaused", False)
            self.paused_for += now - self.paused_at
            self.mark = now

    def _stop(self, now):
        if self.active:
            if self.paused:
                self.paused = False
                self.emit("isPaused", False)
            self.active = False
            self.emit("isActive", False)

    def tick(self, now, dt):
        if self.timers:
            for name, when in sorted(self.timers.items(), key=lambda item: item[1]):
                if now >= when and name in self.timers:
                    del self.timers[name]
                    if self.f["enabled"]:
                        getattr(self, _FIRES[name])(now)
        if self.state == LOADING and self.due is not None and now >= self.due - SLACK:
            self.before = now - dt
            self.finish(now)
        if self.active and not self.paused and self.medium:
            elapsed = now - self.begun - self.paused_for
            self.emit("elapsedTime", elapsed)
            if self._over(now, elapsed):
                self._stop(now)

    def _over(self, now, elapsed):
        """The clip has played to its end (and is not looping)."""
        duration = self.found
        if duration < 0 or self.f["loop"]:
            return False
        return elapsed > duration


class _AudioClip(_Clock):
    """AudioClip. Its end is counted in real seconds, whatever ``pitch`` says (see the module text)."""


class _MovieTexture(_Clock):
    """MovieTexture. Its position runs at ``speed * max(pitch, 0)`` media seconds a second."""
    unit = "MovieTexture"

    def _arrive(self, now):
        self._media(now)
        self.emit("duration_changed", self.found)

    def rate(self):
        rate = self.f["speed"] * max(self.f["pitch"], 0.0)
        return rate if RATE_LOW <= rate <= RATE_HIGH or rate == 0.0 else 1.0

    def _over(self, now, elapsed):
        duration = self.found
        self.position += (now - self.mark) * self.rate()
        self.mark = now
        if duration < 0 or self.f["loop"]:
            return False
        return self.position > duration


class _LoadSensor(_Machine):
    """LoadSensor: isActive, isLoaded, loadTime, progress and timeOut over the url objects in its children."""
    ticks = True

    def setup(self):
        self.watching, self.private, self.active = [], [], False
        self.aborted, self.deadline = False, None

    def _children(self):
        """The url objects among its children: a child that is a node of the scene (a DEF the graph holds and the
        simulation runs) or one only this sensor knows (read from the markup inside it)."""
        sim = self.sim
        node = sim.graph.nodes[self.id]
        found = []
        if not node.content:
            return found
        try:
            root = ET.fromstring(f"<c>{node.content}</c>")
        except ET.ParseError:
            return found
        for element in root:
            tag = element.tag.rsplit("}", 1)[-1]
            name = element.get("USE") or element.get("DEF")
            machine = sim.machines.get(name) if name else None
            if isinstance(machine, _UrlObject):
                found.append(machine)
            elif tag in URL_TYPES and not element.get("USE"):
                fields = {key: value for key, value in element.attrib.items() if key not in ("DEF", "USE", "containerField")}
                private = _TYPES[tag](sim, bg.Node(id=name or f"{self.id}.{len(self.private)}", node_type=tag,
                                                   role=bg.TARGET, fields=fields))
                private.quiet = True
                self.private.append(private)
                found.append(private)
            elif tag not in URL_TYPES:
                _count(sim, "not-a-url-object")
        return found

    def start(self, now):
        self.reset(now)

    def reset(self, now):
        self.remove()
        if not self.f["enabled"]:
            return
        if not self.watching:
            self.watching = self._children()
        for child in self.watching:
            child.request(now)                      # a node the scene holds is asked for before the sensor looks
            child.watchers.append(self)
        self.count(now)

    def remove(self):
        self.deadline = None
        for child in self.watching:
            if self in child.watchers:
                child.watchers.remove(self)

    def child_changed(self, child, now):
        if child.state != IDLE:
            self.count(now)

    def count(self, now):
        children = self.watching
        if children:
            complete = failed = 0
            for child in children:
                if child.state == LOADED:
                    complete += 1
                elif child.state == FAILED:
                    failed += 1
            loaded, progress = complete == len(children), complete / len(children)
            if self.aborted or failed or loaded:
                self.deadline = None
                self._active(False)
                self.emit("isLoaded", loaded)
                self.emit("progress", progress)
                if loaded:
                    self.emit("loadTime", now)
            elif self.active:
                self.emit("progress", progress)
            else:
                self._active(True)
                self.emit("progress", progress)
                self.timed_out(now)
        else:
            self._active(False)
            self.emit("isLoaded", False)
            self.emit("progress", 0.0)

    def _active(self, value):
        self.active = value
        self.emit("isActive", value)

    def timed_out(self, now):
        """set_timeOut__: while active, the clock runs again from now."""
        if not self.active:
            return
        self.deadline = None
        self.aborted = False
        if self.f["timeOut"] > 0:
            self.deadline = now + self.f["timeOut"]

    def abort(self, now):
        self.deadline = None
        self.aborted = True
        if self.f["enabled"]:
            self.count(now)

    def changed(self, name, now):
        if name == "enabled":
            if self.f["enabled"]:
                self.reset(now)
            else:
                self.abort(now)
                self.remove()
        elif name == "timeOut":
            self.timed_out(now)
        elif name == "children":
            self.watching = []
            self.reset(now)

    def tick(self, now, dt):
        for child in self.private:
            child.tick(now, dt)
        if self.deadline is not None and now >= self.deadline:
            self.deadline = None
            self.abort(now)


_TYPES = {"ImageTexture": _UrlObject, "Inline": _UrlObject, "AudioClip": _AudioClip, "MovieTexture": _MovieTexture}
MACHINES = {"LoadSensor": _LoadSensor}                       # event nodes the graph holds as nodes
SCENE_MACHINES = _TYPES                                      # scene nodes (targets) that run: by node type
