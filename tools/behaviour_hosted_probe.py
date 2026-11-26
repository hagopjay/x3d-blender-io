# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The probes of the hosted nodes (class E of docs/BEHAVIOUR_EVENT_NODES.md): Script and CollisionSensor.

    python tools/behaviour_hosted_probe.py --write            # tests/behaviour/probe-script.x3d and the collision world

Script. ``probe-script.x3d`` has two Scripts written in JavaScript (a counter and a threshold) that talk to each other and
to the world; X_ITE runs the JavaScript. ``HANDLERS`` holds the same two scripts written as Python handlers, which the
simulator runs through ``Simulation.host``. The judge (tools/behaviour_sim_judge.py, ``handlers=HANDLERS``) compares every
stream the Scripts send with what X_ITE's JavaScript sent, so a Script with a handler is judged like any other node.
Record it with::

    python tools/behaviour_sim_judge.py --sources tests/behaviour/probe-script.x3d > sources.json
    node tools/behaviour_sim_judge.cjs <x_ite 16.8.1 dist> tests/behaviour/probe-script.x3d sources.json 3 3 --hold=200 --gap=2600 \\
        > tests/behaviour/x_ite_traces/probe-script.json

CollisionSensor. X_ITE has no CollisionSensor the simulator can be compared with: its events come from a physics engine
(Ammo.js), and the simulator has none. ``consistency/probe-collision.x3d`` is a ball that falls onto a floor, recorded on
X_ITE 16.8.1 with ``--seconds 4``. ``stimulus_from`` turns the recorded ``isActive`` events into the simulator's contact
stimulus and ``check`` runs the simulator on it and compares the times of its ``isActive`` events with X_ITE's, within
``TOLERANCE``. That is a consistency check of the stimulus path, not an agreement between two implementations (the
stimulus is X_ITE's own output), and the recording lives outside ``x_ite_traces/`` so that the coverage table does not
count it as judged. Record it with::

    python tools/behaviour_sim_judge.py --sources tests/behaviour/consistency/probe-collision.x3d > sources.json
    node tools/behaviour_sim_judge.cjs <x_ite 16.8.1 dist> tests/behaviour/consistency/probe-collision.x3d sources.json 0 4 \\
        > tests/behaviour/consistency/probe-collision.json
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
sys.path.insert(0, str(ROOT / "tools"))
import behaviour_graph as bg      # noqa: E402
import behaviour_sim as bs        # noqa: E402

WORLDS = ROOT / "tests" / "behaviour"
TOLERANCE = 0.0335     # seconds: two frames at 60 Hz. X_ITE stamps an event with the frame it was found in.

SCRIPT_WORLD = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Full" version="4.0">
  <head>
    <meta name="title" content="probe-script.x3d"/>
    <meta name="description" content="Two Scripts, a counter and a threshold, that X_ITE runs as JavaScript and the simulator runs as Python handlers (tools/behaviour_hosted_probe.py)."/>
  </head>
  <Scene>
    <Viewpoint position="0 0 10"/>
    <Transform DEF="Pad"><Shape><Appearance><Material diffuseColor="0.2 0.3 0.5"/></Appearance><Box size="12 4 0.2"/></Shape><TouchSensor DEF="Touch"/></Transform>
    <Transform DEF="Marker" translation="0 3 0"><Shape><Sphere radius="0.2"/></Shape></Transform>
    <Switch DEF="Pick" whichChoice="-1"><Shape><Sphere radius="0.1"/></Shape></Switch>
    <TimeSensor DEF="Timer" cycleInterval="2"/>
    <ScalarInterpolator DEF="Ramp" key="0 0.5 1" keyValue="0 1 0"/>
    <Script DEF="Counter">
      <field name="bump" type="SFTime" accessType="inputOnly"/>
      <field name="rearm" type="SFBool" accessType="inputOutput" value="true"/>
      <field name="step" type="SFInt32" accessType="initializeOnly" value="2"/>
      <field name="count" type="SFInt32" accessType="outputOnly"/>
      <field name="label" type="SFString" accessType="outputOnly"/>
      <field name="history" type="MFFloat" accessType="outputOnly"/>
<![CDATA[ecmascript:
var n = 0, hist = [];
function initialize() { label = 'ready'; }
function bump(value, time) {
  if (!rearm) { return; }
  n += step; count = n; label = 'n=' + n;
  hist.push(n); if (hist.length > 3) { hist.shift(); }
  history = new MFFloat(...hist);
}
function set_rearm(value, time) { if (value) { n = 0; hist = []; count = 0; } }
]]>
    </Script>
    <Script DEF="Threshold">
      <field name="level" type="SFFloat" accessType="inputOnly"/>
      <field name="hits" type="SFInt32" accessType="inputOnly"/>
      <field name="note" type="SFString" accessType="inputOnly"/>
      <field name="history" type="MFFloat" accessType="inputOnly"/>
      <field name="limit" type="SFFloat" accessType="inputOutput" value="0.5"/>
      <field name="over" type="SFBool" accessType="outputOnly"/>
      <field name="crossings" type="SFInt32" accessType="outputOnly"/>
      <field name="at" type="SFVec3f" accessType="outputOnly"/>
<![CDATA[ecmascript:
var above = false, c = 0;
function level(value, time) {
  at = new SFVec3f(value, value * 2, 0);
  var now = value > limit;
  if (now != above) { above = now; c++; over = now; crossings = c; }
}
function hits(value, time) { crossings = c * 1000 + value; }
function note(value, time) { }
function history(value, time) { }
]]>
    </Script>
    <ROUTE fromNode="Touch" fromField="touchTime" toNode="Counter" toField="bump"/>
    <ROUTE fromNode="Touch" fromField="touchTime" toNode="Timer" toField="startTime"/>
    <ROUTE fromNode="Timer" fromField="fraction_changed" toNode="Ramp" toField="set_fraction"/>
    <ROUTE fromNode="Ramp" fromField="value_changed" toNode="Threshold" toField="level"/>
    <ROUTE fromNode="Counter" fromField="count" toNode="Threshold" toField="hits"/>
    <ROUTE fromNode="Counter" fromField="label" toNode="Threshold" toField="note"/>
    <ROUTE fromNode="Counter" fromField="history" toNode="Threshold" toField="history"/>
    <ROUTE fromNode="Threshold" fromField="over" toNode="Counter" toField="set_rearm"/>
    <ROUTE fromNode="Threshold" fromField="at" toNode="Marker" toField="set_translation"/>
    <ROUTE fromNode="Threshold" fromField="crossings" toNode="Pick" toField="set_whichChoice"/>
  </Scene>
</X3D>
"""


def counter(field, value, time, state):
    """The Counter script above, as a handler: the same arithmetic, the same fields in the same order."""
    if field == "initialize":
        return [("label", "ready")]
    if field == "bump":
        if not state["rearm"]:
            return []
        n = state.get("n", 0) + state["step"]
        hist = (state.get("hist", []) + [n])[-3:]
        state["n"], state["hist"] = n, hist
        return [("count", n), ("label", f"n={n}"), ("history", [float(h) for h in hist])]
    if field == "rearm" and value:
        state["n"], state["hist"] = 0, []
        return [("count", 0)]
    return []


def threshold(field, value, time, state):
    """The Threshold script above, as a handler."""
    if field == "level":
        sent = [("at", (value, value * 2, 0.0))]
        now = value > state["limit"]
        if now != state.get("above", False):
            state["above"], state["c"] = now, state.get("c", 0) + 1
            sent += [("over", now), ("crossings", state["c"])]
        return sent
    if field == "hits":
        return [("crossings", state.get("c", 0) * 1000 + value)]
    return []


HANDLERS = {"Counter": counter, "Threshold": threshold}

COLLISION_WORLD = """<?xml version="1.0" encoding="UTF-8"?>
<X3D profile="Full" version="4.0">
  <head>
    <component name="RigidBodyPhysics" level="2"/>
    <meta name="title" content="probe-collision.x3d"/>
    <meta name="description" content="A ball that falls onto a floor, and two CollisionSensors (one disabled). X_ITE's physics decides when they touch; the simulator is told (tools/behaviour_hosted_probe.py)."/>
  </head>
  <Scene>
    <Viewpoint position="0 1 12"/>
    <RigidBodyCollection DEF="Physics" gravity="0 -9.8 0">
      <RigidBody DEF="Floor" containerField="bodies" fixed="true" position="0 -1 0">
        <CollidableShape DEF="FloorShape" containerField="geometry"><Shape containerField="shape"><Box size="10 0.2 4"/></Shape></CollidableShape>
        <Box containerField="massDensityModel" size="10 0.2 4"/>
      </RigidBody>
      <RigidBody DEF="Ball" containerField="bodies" position="0 60 0" mass="1">
        <CollidableShape DEF="BallShape" containerField="geometry"><Shape containerField="shape"><Sphere radius="0.5"/></Shape></CollidableShape>
        <Sphere containerField="massDensityModel" radius="0.5"/>
      </RigidBody>
      <CollisionCollection DEF="Rules" containerField="collider">
        <CollidableShape USE="FloorShape" containerField="collidables"/>
        <CollidableShape USE="BallShape" containerField="collidables"/>
      </CollisionCollection>
    </RigidBodyCollection>
    <CollisionSensor DEF="Hit"><CollisionCollection USE="Rules" containerField="collider"/></CollisionSensor>
    <CollisionSensor DEF="Off" enabled="false"><CollisionCollection USE="Rules" containerField="collider"/></CollisionSensor>
  </Scene>
</X3D>
"""

# X_ITE reports a contact for the collection when either body of a pair is one of its collidables; here both are, so the
# names the stimulus gives are the two shapes of the world above.
COLLIDING = ["FloorShape", "BallShape"]


def stimulus_from(trace, sensor="Hit"):
    """The simulator's contact calls for ``sensor``, from the ``isActive`` events X_ITE recorded: [(time, active)]."""
    return [(when, str(value).lower() == "true") for when, node, field, value in sorted(trace["events"], key=lambda e: e[0])
            if node == sensor and field == "isActive"]


def check(world_path, trace, tolerance=TOLERANCE):
    """Run the simulator on the contact stimulus taken from ``trace`` and compare the times of its ``isActive`` events
    with X_ITE's. Returns {"x_ite": [...], "simulator": [...], "worst_gap": seconds, "agree": bool, "disabled_sent": n}.
    A consistency check, not a judgement: see the module text."""
    graph = bg.Behaviour.from_x3d(pathlib.Path(world_path).read_text(encoding="utf-8"))
    sim = bs.Simulation(graph, log_size=10 ** 6)
    began = trace["began"]
    sim.start(began)
    theirs = stimulus_from(trace)
    frame = 1.0 / 60.0           # the simulator is stepped on its own 60 Hz grid; a contact is applied at the next step
    for when, active in theirs:
        applied = began + frame * math.ceil((when - began) / frame - 1e-9)
        sim.step(applied)
        sim.contact("Hit", active, COLLIDING if active else (), COLLIDING if active else (), applied)
        sim.contact("Off", active, COLLIDING if active else (), COLLIDING if active else (), applied)   # a disabled sensor is silent
    ours = [(when, value) for when, node, field, value in sim.log if node == "Hit" and field == "isActive"]
    worst = max((abs(a[0] - b[0]) for a, b in zip(theirs, ours)), default=0.0)
    disabled = [e for e in sim.log if e[1] == "Off"]
    return {"x_ite": theirs, "simulator": ours, "worst_gap": worst, "tolerance": tolerance,
            "agree": len(theirs) == len(ours) > 0 and [a[1] for a in theirs] == [b[1] for b in ours] and worst <= tolerance,
            "disabled_sent": len(disabled)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--write", action="store_true", help="write the two worlds")
    args = parser.parse_args(argv)
    if args.write:
        (WORLDS / "consistency").mkdir(exist_ok=True)
        (WORLDS / "probe-script.x3d").write_text(SCRIPT_WORLD, encoding="utf-8")
        (WORLDS / "consistency" / "probe-collision.x3d").write_text(COLLISION_WORLD, encoding="utf-8")
        print("wrote tests/behaviour/probe-script.x3d and tests/behaviour/consistency/probe-collision.x3d")
    return 0


if __name__ == "__main__":
    sys.exit(main())
