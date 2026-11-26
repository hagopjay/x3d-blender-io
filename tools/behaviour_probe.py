# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes tests/behaviour/probe.x3d: one click drives every kind of node the simulator runs, so the judge
(tools/behaviour_sim_judge.py) can compare each of them with X_ITE. Built with the scripting methods.

    python tools/behaviour_probe.py
"""

import json
import math
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


def build_spline():
    """probe-spline.x3d: EaseInEaseOut, the three Spline interpolators and SquadOrientationInterpolator, each set up
    to show what X_ITE does where the standard leaves room: uneven keys, a closed curve, velocities that are normalised,
    fewer velocities than keys, ease-in plus ease-out above 1, and rotations about changing axes."""
    b = Behaviour()
    touch = b.add("TouchSensor", "Touch", parent="Pad")
    a, bb, c, d, e = (b.target("Transform", name) for name in "ABCDE")
    paint_a, paint_d = b.target("Material", "APaint"), b.target("Material", "DPaint")
    timer = b.add("TimeSensor", "Timer", cycleInterval=2)
    touch.touchTime >> timer.startTime

    ease = b.add("EaseInEaseOut", "Ease", key=[0, 0.5, 1], easeInEaseOut=[(0, 0.6), (0.3, 0.3), (0.7, 0)])
    timer.fraction_changed >> ease.set_fraction
    eased_hop = b.add("PositionInterpolator", "EasedHop", key=[0, 1], keyValue=[(-3, 3, 0), (-3, 4.5, 0)])
    ease.modifiedFraction_changed >> eased_hop.set_fraction
    eased_hop.value_changed >> a.translation
    steep = b.add("EaseInEaseOut", "Steep", key=[0, 1], easeInEaseOut=[(0.8, 0.9), (0.9, 0.6)])   # 0.9 + 0.9 > 1
    timer.fraction_changed >> steep.set_fraction
    fade = b.add("ScalarInterpolator", "Fade", key=[0, 1], keyValue=[0, 0.8])
    steep.modifiedFraction_changed >> fade.set_fraction
    fade.value_changed >> paint_a.transparency

    path = b.add("SplinePositionInterpolator", "Path", key=[0, 0.2, 0.7, 1],
                 keyValue=[(-1.5, 3, 0), (-1, 4, 0.5), (-2, 4.5, -0.5), (-1.5, 3, 0)])
    timer.fraction_changed >> path.set_fraction
    path.value_changed >> bb.translation
    loop = b.add("SplinePositionInterpolator", "Loop", closed=True, key=[0, 0.25, 0.5, 0.75, 1],
                 keyValue=[(0, 3, 0), (0.6, 3.6, 0), (0, 4.2, 0), (-0.6, 3.6, 0), (0, 3, 0)])
    timer.fraction_changed >> loop.set_fraction
    loop.value_changed >> c.translation
    flat = b.add("SplinePositionInterpolator2D", "Flat", key=[0, 0.5, 1], keyValue=[(0, 0), (1, 1), (2, 0)],
                 keyVelocity=[(2, 0), (0, 2), (2, 0)])   # normalizeVelocity on a vector spline fails to load in X_ITE 16.7.1
    timer.fraction_changed >> flat.set_fraction
    soft = b.add("PositionDamper2D", "Soft2D", tau=0.2)
    flat.value_changed >> soft.set_destination
    soft.value_changed >> b.target("TextureTransform", "PadTexture").translation
    wave = b.add("SplineScalarInterpolator", "Wave", key=[0, 0.3, 0.6, 1], keyValue=[0, 0.9, 0.2, 0.7],
                 keyVelocity=[1, -2], normalizeVelocity=True)         # fewer velocities than keys, normalised
    timer.fraction_changed >> wave.set_fraction
    wave.value_changed >> paint_d.transparency
    tide = b.add("SplineScalarInterpolator", "Tide", key=[0, 0.4, 0.5, 1], keyValue=[0.1, 0.6, 0.3, 0.9],
                 keyVelocity=[1, 0.5, -1, 2], normalizeVelocity=True)  # the last velocity is not normalised
    timer.fraction_changed >> tide.set_fraction
    tide.value_changed >> b.target("Material", "CPaint").transparency
    swing = b.add("SquadOrientationInterpolator", "Swing", key=[0, 0.3, 0.7, 1],
                  keyValue=[(0, 1, 0, 0), (0, 1, 0, 1.5), (1, 0, 0, 1.2), (0, 0, 1, 2.5)])
    timer.fraction_changed >> swing.set_fraction
    swing.value_changed >> e.rotation
    return b


DRAG_SCENE = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D profile="Immersive" version="4.0">
  <head>
    <meta name="title" content="Behaviour simulator probe: drag sensors"/>
    <meta name="generator" content="x3d-blender-io tools/behaviour_probe.py"/>
  </head>
  <Scene>
    <NavigationInfo type='"NONE"'/>
    <Viewpoint position="0 0.5 10"/>
    <Transform DEF="CylBase" translation="-3 0.5 0" rotation="1 0 0 0.35">
      <Transform DEF="Spinner"><Shape><Appearance><Material diffuseColor="0.9 0.5 0.2"/></Appearance><Box size="1.6 0.9 1.6"/></Shape></Transform>
      <Transform DEF="SpinHit"/>
      <Transform DEF="SpinDot"><Shape><Appearance><Material diffuseColor="1 1 1" emissiveColor="1 0.9 0.2"/></Appearance><Sphere radius="0.07"/></Shape></Transform>
    </Transform>
    <Transform DEF="DiskBase" translation="0 -1.6 0" rotation="1 0 0 1.45">
      <Transform DEF="Dial"><Shape><Appearance><Material diffuseColor="0.3 0.7 0.9"/></Appearance><Box size="1.8 0.3 1.8"/></Shape></Transform>
      <Transform DEF="TurnHit"/>
    </Transform>
    <Transform DEF="AxleBase" translation="-1.5 2.3 0">
      <Transform DEF="AxleSpin"><Transform translation="0 0 -1.5"><Shape><Appearance><Material diffuseColor="0.9 0.8 0.3"/></Appearance><Box size="1 0.6 1"/></Shape></Transform></Transform>
      <Transform DEF="AxleHit"/>
    </Transform>
    <Transform DEF="RearBase" translation="1.5 2.3 0">
      <Transform DEF="RearSpin"><Transform translation="0 0 -1.5"><Shape><Appearance><Material diffuseColor="0.8 0.4 0.9"/></Appearance><Box size="1 0.6 1"/></Shape></Transform></Transform>
      <Transform DEF="RearHit"/>
    </Transform>
    <Transform DEF="BallBase" translation="3 0.5 0">
      <Transform DEF="Ball"><Shape><Appearance><Material diffuseColor="0.6 0.9 0.4"/></Appearance><Box size="1.3 1.3 1.3"/></Shape></Transform>
      <Transform DEF="RollHit"/>
      <Transform DEF="RollDot"><Shape><Appearance><Material diffuseColor="1 1 1" emissiveColor="1 0.9 0.2"/></Appearance><Sphere radius="0.07"/></Shape></Transform>
    </Transform>
  </Scene>
</X3D>
"""

# (sensor, its TouchSensor, the parent Transform's translation and rotation, the press point on the box in the parent's
# coordinates, the pointer's path after the press in pixels, right and down)
DRAGS = [
    ("Spin", "SpinTouch", (-3, 0.5, 0), (1, 0, 0, 0.35), (0.3, 0.1, 0.8),
     [(12 * k, 0) for k in range(1, 21)] + [(240 - 15 * k, 4 * k) for k in range(1, 13)]),
    ("Turn", "TurnTouch", (0, -1.6, 0), (1, 0, 0, 1.45), (0.55, 0.15, 0.25),
     # an arc about the dial's centre on screen, in radians from the press: inside the limits, past 0.9, back past -0.6
     ("arc", [0.1 * k for k in range(1, 7)] + [0.6 - 0.1 * k for k in range(1, 15)] + [-0.8 + 0.1 * k for k in range(1, 22)])),
    ("Roll", "RollTouch", (3, 0.5, 0), (0, 0, 1, 0), (0.2, 0.25, 0.65),
     [(-9 * k, -6 * k) for k in range(1, 15)] + [(-126 - 20 * k, -84 + 5 * k) for k in range(1, 16)]),
    ("Spin", "SpinTouch", (-3, 0.5, 0), (1, 0, 0, 0.35), (0.3, 0.1, 0.8),
     [(-10 * k, 2 * k) for k in range(1, 16)]),
    # boxes behind their sensor's origin: the press lands on the far side of the virtual cylinder and sphere
    ("Axle", "AxleTouch", (-1.5, 2.3, 0), (0, 0, 1, 0), (0.2, 0.1, -1.0), [(9 * k, -2 * k) for k in range(1, 16)]),
    ("Rear", "RearTouch", (1.5, 2.3, 0), (0, 0, 1, 0), (-0.15, 0.1, -1.0), [(-7 * k, 5 * k) for k in range(1, 16)]),
    ("Roll", "RollTouch", (3, 0.5, 0), (0, 0, 1, 0), (0.2, 0.25, 0.65),
     [(8 * k, 7 * k) for k in range(1, 12)]),
]
VIEW = {"position": (0.0, 0.5, 10.0), "fieldOfView": math.pi / 4, "width": 960, "height": 600}


def build_drag():
    """probe-drag.x3d: two CylinderSensors (one seen side on, one seen down its axis, so X_ITE uses its disk) and a
    SphereSensor, each with a TouchSensor beside it whose hitPoint_changed says where the press landed."""
    b = Behaviour()
    spin = b.add("CylinderSensor", "Spin", parent="CylBase")
    b.add("TouchSensor", "SpinTouch", parent="CylBase").hitPoint_changed >> b.target("Transform", "SpinHit").translation
    spin.rotation_changed >> b.target("Transform", "Spinner").rotation
    spin.trackPoint_changed >> b.target("Transform", "SpinDot").translation
    turn = b.add("CylinderSensor", "Turn", parent="DiskBase", minAngle=-0.6, maxAngle=0.9)
    b.add("TouchSensor", "TurnTouch", parent="DiskBase").hitPoint_changed >> b.target("Transform", "TurnHit").translation
    turn.rotation_changed >> b.target("Transform", "Dial").rotation
    axle = b.add("CylinderSensor", "Axle", parent="AxleBase", autoOffset=False)
    b.add("TouchSensor", "AxleTouch", parent="AxleBase").hitPoint_changed >> b.target("Transform", "AxleHit").translation
    axle.rotation_changed >> b.target("Transform", "AxleSpin").rotation
    rear = b.add("SphereSensor", "Rear", parent="RearBase")
    b.add("TouchSensor", "RearTouch", parent="RearBase").hitPoint_changed >> b.target("Transform", "RearHit").translation
    rear.rotation_changed >> b.target("Transform", "RearSpin").rotation
    roll = b.add("SphereSensor", "Roll", parent="BallBase", offset=(0, 1, 0, 0.3))
    b.add("TouchSensor", "RollTouch", parent="BallBase").hitPoint_changed >> b.target("Transform", "RollHit").translation
    roll.rotation_changed >> b.target("Transform", "Ball").rotation
    roll.trackPoint_changed >> b.target("Transform", "RollDot").translation
    return b


def drag_plan():
    """Where to press (window pixels, from the top left as a browser counts them) and where to move, for the recorder."""
    import sys as _sys
    _sys.path.insert(0, str(ROOT / "source"))
    import behaviour_sim as bs
    out = []
    for sensor, touch, translation, rotation, local, path in DRAGS:
        world = bs._v_add(bs._Rot.axis_angle(*rotation).rotate(local), translation)
        view = bs._v_sub(world, VIEW["position"])
        f = 1 / math.tan(VIEW["fieldOfView"] / 2)
        aspect = VIEW["width"] / VIEW["height"]
        ndc = (view[0] / -view[2] * f / aspect, view[1] / -view[2] * f)
        x = round((ndc[0] + 1) / 2 * VIEW["width"])
        y = round((1 - (ndc[1] + 1) / 2) * VIEW["height"])
        if path and path[0] == "arc":       # turn about the parent's origin as seen on screen
            centre = bs._v_sub(tuple(float(c) for c in translation), VIEW["position"])
            cx = ((centre[0] / -centre[2] * f / aspect) + 1) / 2 * VIEW["width"]
            cy = (1 - ((centre[1] / -centre[2] * f) + 1) / 2) * VIEW["height"]
            radius, start = math.hypot(x - cx, y - cy), math.atan2(y - cy, x - cx)
            points = [[round(cx + radius * math.cos(start - a)), round(cy + radius * math.sin(start - a))] for a in path[1]]
        else:
            points = [[x + dx, y + dy] for dx, dy in path]
        out.append({"sensor": sensor, "touch": touch, "at": [x, y], "path": points})
    return {"view": VIEW, "drags": out}


if __name__ == "__main__":
    for name, graph, title in (("probe.x3d", build(), "Behaviour simulator probe"),
                               ("probe-spline.x3d", build_spline(), "Behaviour simulator probe: splines and easing")):
        target = ROOT / "tests" / "behaviour" / name
        scene = SCENE.replace("Behaviour simulator probe", title)
        if name != "probe.x3d":      # EaseInEaseOut and the Spline nodes are Interpolation 4, Squad is 5
            scene = scene.replace('<component name="Followers" level="1"/>',
                                  '<component name="Followers" level="1"/>\n    <component name="Interpolation" level="5"/>')
            scene = scene.replace('<Material diffuseColor="0.2 0.3 0.5"/></Appearance>',    # a 2D target
                                  '<Material diffuseColor="0.2 0.3 0.5"/><TextureTransform DEF="PadTexture"/></Appearance>')
        target.write_text(graph.weave(scene), encoding="utf-8")
        print(target, len(graph.nodes), "nodes", len(graph.routes), "ROUTEs", graph.check())
    graph = build_drag()
    target = ROOT / "tests" / "behaviour" / "probe-drag.x3d"
    target.write_text(graph.weave(DRAG_SCENE), encoding="utf-8")
    (ROOT / "tests" / "behaviour" / "probe-drag.drags.json").write_text(json.dumps(drag_plan(), indent=1) + "\n")
    print(target, len(graph.nodes), "nodes", len(graph.routes), "ROUTEs", graph.check())
