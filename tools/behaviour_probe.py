# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes tests/behaviour/probe.x3d: one click drives every kind of node the simulator runs, so the judge
(tools/behaviour_sim_judge.py) can compare each of them with X_ITE. Built with the scripting methods.

    python tools/behaviour_probe.py
"""

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "source"))
from behaviour_graph import Behaviour       # noqa: E402

BOXES = "".join(
    f'    <Transform DEF="{name}" translation="{x} 3 0"><Shape><Appearance><Material DEF="{name}Paint" '
    f'diffuseColor="0.6 0.6 0.6"/></Appearance><Box size="0.6 0.6 0.6"/></Shape></Transform>\n'
    for name, x in (("A", -3), ("B", -1.5), ("C", 0), ("D", 1.5), ("E", 3)))

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D profile="Immersive" version="4.0">
  <head>
    <component name="EventUtilities" level="1"/>
    <component name="Followers" level="1"/>
    <meta name="title" content="Behaviour simulator probe"/>
    <meta name="generator" content="x3d-blender-io tools/behaviour_probe.py"/>
  </head>
  <Scene>
    <NavigationInfo type='"NONE"'/>
    <Viewpoint position="0 0 10"/>
    <Transform DEF="Pad"><Shape><Appearance><Material diffuseColor="0.2 0.3 0.5"/></Appearance><Box size="12 4 0.2"/></Shape></Transform>
{BOXES}    <Switch DEF="Pick" whichChoice="-1"><Shape><Sphere radius="0.1"/></Shape></Switch>
  </Scene>
</X3D>
"""


def build():
    b = Behaviour()
    touch = b.add("TouchSensor", "Touch", parent="Pad")
    a, bb, c, d, e = (b.target("Transform", name) for name in "ABCDE")
    paint_a, paint_b = b.target("Material", "APaint"), b.target("Material", "BPaint")
    pick = b.target("Switch", "Pick")

    timer = b.add("TimeSensor", "Timer", cycleInterval=2)
    touch.touchTime >> timer.startTime

    # triggers and event utilities
    by_bool = b.add("TimeTrigger", "ByBool")
    short = b.add("TimeSensor", "Short", cycleInterval=0.5)
    touch.isActive >> by_bool.set_boolean
    by_bool.triggerTime >> short.startTime
    number = b.add("IntegerTrigger", "Number", integerKey=7)
    touch.isActive >> number.set_boolean
    number.triggerValue >> pick.whichChoice
    yes = b.add("BooleanTrigger", "Yes")
    touch.touchTime >> yes.set_triggerTime
    flip = b.add("BooleanToggle", "Flip")
    yes.triggerTrue >> flip.set_boolean
    sieve = b.add("BooleanFilter", "Sieve")
    flip.toggle >> sieve.set_boolean
    sieve.inputTrue >> a.visible
    sieve.inputFalse >> bb.visible
    sieve.inputNegate >> c.visible
    blink = b.add("BooleanSequencer", "Blink", key=[0, 0.3, 0.6], keyValue=[True, False, True])
    timer.fraction_changed >> blink.set_fraction
    blink.value_changed >> d.visible
    count = b.add("IntegerSequencer", "Count", key=[0, 0.25, 0.5, 0.75], keyValue=[3, 1, 4, 1])
    short.fraction_changed >> count.set_fraction
    count.value_changed >> pick.whichChoice

    # interpolators
    colour = b.add("ColorInterpolator", "Colour", key=[0, 0.5, 1], keyValue=[(1, 0, 0), (0, 1, 0), (0.2, 0.2, 1)])
    timer.fraction_changed >> colour.set_fraction
    colour.value_changed >> paint_a.diffuseColor
    turn = b.add("OrientationInterpolator", "Turn", key=[0, 0.5, 1],
                 keyValue=[(0, 1, 0, 0), (0, 1, 0, 2.5), (1, 0, 0, 1.2)])
    timer.fraction_changed >> turn.set_fraction
    turn.value_changed >> a.rotation
    level = b.add("ScalarInterpolator", "Level", key=[0, 0.5, 1], keyValue=[0, 0.8, 0.1])
    timer.fraction_changed >> level.set_fraction
    level.value_changed >> paint_a.transparency
    hop = b.add("PositionInterpolator", "Hop", key=[0, 0.25, 0.5, 1],
                keyValue=[(-3, 3, 0), (-3, 4, 0), (-2, 4, 1), (-3, 3, 0)])
    timer.fraction_changed >> hop.set_fraction
    hop.value_changed >> a.translation

    # followers
    soft_place = b.add("PositionDamper", "SoftPlace", initialValue=(-1.5, 3, 0), initialDestination=(-1.5, 3, 0),
                       tau=0.2, order=3)
    hop.value_changed >> soft_place.set_destination
    soft_place.value_changed >> bb.translation
    soft_turn = b.add("OrientationDamper", "SoftTurn", tau=0.2, order=1)
    turn.value_changed >> soft_turn.set_destination
    soft_turn.value_changed >> bb.rotation
    soft_colour = b.add("ColorDamper", "SoftColour", initialValue=(0.6, 0.6, 0.6), initialDestination=(0.6, 0.6, 0.6),
                        tau=0.3, order=2)
    colour.value_changed >> soft_colour.set_destination
    soft_colour.value_changed >> paint_b.diffuseColor
    soft_level = b.add("ScalarDamper", "SoftLevel", tau=0.15, order=1)
    level.value_changed >> soft_level.set_destination
    soft_level.value_changed >> paint_b.transparency

    step = b.add("PositionInterpolator", "Step", key=[0, 0.2, 0.2, 0.6, 0.6, 1],
                 keyValue=[(0, 3, 0), (0, 3, 0), (0, 4, 0), (0, 4, 0), (1, 3, 0), (1, 3, 0)])
    timer.fraction_changed >> step.set_fraction
    chase_place = b.add("PositionChaser", "ChasePlace", initialValue=(0, 3, 0), initialDestination=(0, 3, 0), duration=0.4)
    step.value_changed >> chase_place.set_destination
    chase_place.value_changed >> c.translation
    level_step = b.add("ScalarInterpolator", "LevelStep", key=[0, 0.3, 0.3, 1], keyValue=[0, 0, 0.9, 0.9])
    timer.fraction_changed >> level_step.set_fraction
    chase_level = b.add("ScalarChaser", "ChaseLevel", duration=0.5)
    level_step.value_changed >> chase_level.set_destination
    paint_e = b.target("Material", "EPaint")
    chase_level.value_changed >> paint_e.transparency
    turn_step = b.add("OrientationInterpolator", "TurnStep", key=[0, 0.4, 0.4, 1],
                      keyValue=[(0, 0, 1, 0), (0, 0, 1, 0), (0, 0, 1, 1.5), (0, 0, 1, 1.5)])
    timer.fraction_changed >> turn_step.set_fraction
    chase_turn = b.add("OrientationChaser", "ChaseTurn", duration=0.5)
    turn_step.value_changed >> chase_turn.set_destination
    chase_turn.value_changed >> e.rotation
    return b


if __name__ == "__main__":
    graph = build()
    target = ROOT / "tests" / "behaviour" / "probe.x3d"
    target.write_text(graph.weave(SCENE), encoding="utf-8")
    print(target, len(graph.nodes), "nodes", len(graph.routes), "ROUTEs", graph.check())
