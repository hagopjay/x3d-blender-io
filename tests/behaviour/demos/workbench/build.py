# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Writes the workbench demo: workbench.x3d and drags.json (docs/BEHAVIOUR_DEMOS.md, section 1).

    python tests/behaviour/demos/workbench/build.py

A warm workshop bench with three toys, each a drag sensor with something that follows it:

    fader  PlaneSensor (x only, -1..1)  -> the knob; a toy car on a rail through a PositionChaser (0.8 s)
    dial   CylinderSensor               -> the dial; isActive starts a 2 s colour sweep (BooleanFilter, TimeTrigger,
                                           TimeSensor, ColorInterpolator, ColorChaser 0.6 s) into the lamp
    globe  SphereSensor                 -> the globe; a moon on an arm trails it through an OrientationChaser (0.8 s)

The drag plan puts the pointer where a hand would: pixels are projected through the Viewpoint below, the same camera
the judge rebuilds the pointer's ray from (tools/behaviour_sim_judge.py).
"""

import json
import math
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path.insert(0, str(ROOT / "source"))
import behaviour_sim as bs                  # noqa: E402
from behaviour_graph import Behaviour       # noqa: E402

VIEW = {"position": (0.0, 2.3, 6.5), "orientation": (1.0, 0.0, 0.0, -0.2), "fieldOfView": math.pi / 4,
        "width": 960, "height": 600}

AMBER, ROSE, TEAL = (1.0, 0.62, 0.12), (0.95, 0.25, 0.45), (0.1, 0.75, 0.7)


def n(*values):
    return " ".join(f"{v:g}" for v in values)


def paint(base, metallic=0.0, roughness=0.6, emissive=None, name=None):
    extra = f' emissiveColor="{n(*emissive)}"' if emissive else ""
    label = f' DEF="{name}"' if name else ""
    return (f'<Appearance><PhysicalMaterial{label} baseColor="{n(*base)}" metallic="{metallic:g}" '
            f'roughness="{roughness:g}"{extra} /></Appearance>')


def shape(geometry, look):
    return f"<Shape>{look}{geometry}</Shape>"


def box(x, y, z, look, at=(0, 0, 0), name=None, rotation=None):
    label = f' DEF="{name}"' if name else ""
    turn = f' rotation="{n(*rotation)}"' if rotation else ""
    geometry = f'<Box size="{n(x, y, z)}" />'
    return f'<Transform{label} translation="{n(*at)}"{turn}>{shape(geometry, look)}</Transform>'


def cylinder(radius, height, look, at=(0, 0, 0), rotation=None):
    turn = f' rotation="{n(*rotation)}"' if rotation else ""
    geometry = f'<Cylinder radius="{radius:g}" height="{height:g}" />'
    return f'<Transform translation="{n(*at)}"{turn}>{shape(geometry, look)}</Transform>'


def sphere(radius, look, at=(0, 0, 0), scale=None, name=None):
    label = f' DEF="{name}"' if name else ""
    size = f' scale="{n(*scale)}"' if scale else ""
    geometry = f'<Sphere radius="{radius:g}" />'
    return f'<Transform{label} translation="{n(*at)}"{size}>{shape(geometry, look)}</Transform>'


WOOD, DARK_WOOD = paint((0.46, 0.27, 0.13), roughness=0.75), paint((0.24, 0.14, 0.08), roughness=0.8)
BRASS, STEEL = paint((0.95, 0.72, 0.28), 0.35, 0.4), paint((0.16, 0.17, 0.2), 0.8, 0.4)
CREAM, RED, WHEEL = paint((0.9, 0.86, 0.74), roughness=0.5), paint((0.78, 0.14, 0.1), 0.1, 0.35), paint((0.05, 0.05, 0.06))
OCEAN, LAND = paint((0.12, 0.32, 0.62), 0.1, 0.4), paint((0.25, 0.55, 0.22), roughness=0.7)
MOON = paint((0.72, 0.74, 0.8), roughness=0.9)

FADER_AT, DIAL_AT, GLOBE_AT, LAMP_AT = (-2.2, 0.1, 1.0), (0.3, 1.0, -0.78), (2.6, 1.15, 0.2), (-2.6, 0.0, -1.0)
DIAL_FACE = DIAL_AT[2] + 0.15         # the dial's top face, which looks at the camera (its local y is the world z)
MOON_AT = (1.05, 0.25, 0)             # the moon's place on its arm, in the globe's frame


def lamp():
    shade = (f'<Transform translation="{n(0, 1.55, 0)}"><Shape>'
             f'{paint((0.4, 0.34, 0.24), roughness=0.5, emissive=AMBER, name="ShadePaint")}'
             f'<Cone bottomRadius="0.55" height="0.6" /></Shape></Transform>')
    return (f'<Transform DEF="Lamp" translation="{n(*LAMP_AT)}">'
            f'{cylinder(0.3, 0.08, STEEL, (0, 0.04, 0))}{cylinder(0.04, 1.4, STEEL, (0, 0.74, 0))}{shade}</Transform>'
            f'<PointLight DEF="BenchLight" location="{n(LAMP_AT[0], 1.45, LAMP_AT[2])}" color="{n(*AMBER)}" '
            f'intensity="3" radius="9" />')


def fader():
    track = box(2.9, 0.06, 0.4, STEEL, (0, -0.07, 0)) + "".join(      # the slot and its tick marks
        box(0.03, 0.02, 0.22, CREAM, (x * 0.5, -0.03, 0)) for x in range(-4, 5))
    knob = f'<Transform DEF="Knob">{box(0.3, 0.34, 0.5, BRASS, (0, 0.14, 0))}</Transform>'
    return (f'<Transform DEF="FaderBase" translation="{n(*FADER_AT)}">{track}{knob}'
            f'<Transform DEF="FaderHit" />'
            f'<Transform translation="0 -0.035 0">{sphere(0.04, paint((1, 0.9, 0.5), emissive=AMBER), name="FaderDot")}</Transform></Transform>')


def car():
    rail = box(2.9, 0.04, 0.05, STEEL, (0, 0, -0.17)) + box(2.9, 0.04, 0.05, STEEL, (0, 0, 0.17))
    body = (box(0.62, 0.16, 0.3, RED, (0, 0.1, 0)) + box(0.3, 0.14, 0.26, RED, (-0.04, 0.25, 0)) +
            "".join(cylinder(0.075, 0.05, WHEEL, (dx, 0.075, dz), (1, 0, 0, 1.5708))
                    for dx in (-0.2, 0.2) for dz in (-0.17, 0.17)))
    return (f'<Transform DEF="CarRail" translation="{n(FADER_AT[0], 0.02, -0.3)}">{rail}'
            f'<Transform DEF="Car">{body}</Transform></Transform>')


def dial():
    ticks = "".join(
        sphere(0.025, CREAM if k % 3 else BRASS, (0.62 * math.sin(a), 0.01, -0.62 * math.cos(a)))
        for k, a in enumerate(math.radians(-135 + 30 * k) for k in range(10)))
    panel = box(2.4, 1.7, 0.2, DARK_WOOD, (DIAL_AT[0], DIAL_AT[1] - 0.1, DIAL_AT[2] - 0.2))
    knob = (f'<Transform DEF="Dial">{cylinder(0.45, 0.3, BRASS)}'
            f'{box(0.07, 0.04, 0.3, STEEL, (0, 0.16, -0.3))}{sphere(0.07, BRASS, (0, 0.2, 0))}</Transform>')
    return (f'{panel}<Transform DEF="DialBase" translation="{n(*DIAL_AT)}" rotation="1 0 0 1.5708">{knob}{ticks}'
            f'<Transform DEF="DialHit" /></Transform>')


def globe():
    land = "".join(sphere(0.2, LAND, tuple(0.5 * c for c in at), (1, 0.55, 1), None) for at in
                   ((0.0, 0.0, 1.0), (0.85, 0.3, 0.45), (-0.8, 0.2, 0.55), (0.0, 0.95, 0.3)))
    stand = cylinder(0.5, 0.1, STEEL, (GLOBE_AT[0], 0.05, GLOBE_AT[2])) + \
        cylinder(0.05, GLOBE_AT[1] - 0.6, STEEL, (GLOBE_AT[0], (GLOBE_AT[1] - 0.6) / 2 + 0.1, GLOBE_AT[2]))
    ocean = shape('<Sphere radius="0.55" />', OCEAN)
    arm = box(1.08, 0.02, 0.02, STEEL, (MOON_AT[0] / 2, MOON_AT[1] / 2, 0), rotation=(0, 0, 1, math.atan2(MOON_AT[1], MOON_AT[0])))
    return (f'{stand}<Transform DEF="GlobeBase" translation="{n(*GLOBE_AT)}">'
            f'<Transform DEF="GlobeSense"><Transform DEF="Globe">{ocean}{land}</Transform></Transform>'
            f'<Transform DEF="MoonArm">{arm}{sphere(0.15, MOON, MOON_AT)}</Transform>'
            f'<Transform DEF="GlobeHit" /></Transform>')


SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Behaviour demo: Workbench, drag, turn, spin" />
    <meta name="description" content="A workshop bench with a fader (PlaneSensor, a car chasing it), a brass dial (CylinderSensor, a colour sweep through a ColorChaser into the lamp) and a globe (SphereSensor, a moon trailing it)." />
    <meta name="generator" content="tests/behaviour/demos/workbench/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.07 0.05 0.04" />
    <Viewpoint DEF="View" description="Bench" position="{n(*VIEW['position'])}" orientation="{n(*VIEW['orientation'])}" />
    <DirectionalLight direction="-0.3 -1 -0.6" intensity="1" color="1 0.92 0.8" />
    <PointLight DEF="Fill" location="1 3.5 2" color="1 0.9 0.75" intensity="2.5" radius="14" />
    {box(9.4, 0.2, 3.6, WOOD, (0, -0.1, 0))}
    {box(9.4, 0.12, 0.3, DARK_WOOD, (0, -0.26, 1.7))}
    {box(10, 5, 0.2, paint((0.22, 0.15, 0.11), roughness=0.9), (0, 2.4, -1.9))}
    {box(0.2, 0.2, 0.2, STEEL, (-3.6, -0.5, 1.5))}
    {lamp()}
    {fader()}
    {car()}
    {dial()}
    {globe()}
  </Scene>
</X3D>
"""


def behaviour():
    b = Behaviour()
    slide = b.add("PlaneSensor", "Slide", parent="FaderBase", minPosition=(-1, 0), maxPosition=(1, 0))
    b.add("TouchSensor", "SlideTouch", parent="FaderBase").hitPoint_changed >> b.target("Transform", "FaderHit").translation
    slide.translation_changed >> b.target("Transform", "Knob").translation
    slide.trackPoint_changed >> b.target("Transform", "FaderDot").translation
    car = b.add("PositionChaser", "CarChase", duration=0.8)
    slide.translation_changed >> car.set_destination
    car.value_changed >> b.target("Transform", "Car").translation

    turn = b.add("CylinderSensor", "Turn", parent="DialBase")
    b.add("TouchSensor", "TurnTouch", parent="DialBase").hitPoint_changed >> b.target("Transform", "DialHit").translation
    turn.rotation_changed >> b.target("Transform", "Dial").rotation
    press = b.add("BooleanFilter", "Press")
    kick = b.add("TimeTrigger", "Kick")
    sweep = b.add("TimeSensor", "Sweep", cycleInterval=2)
    colours = b.add("ColorInterpolator", "Colours", key=[0, 0.5, 1], keyValue=[AMBER, ROSE, TEAL])
    glow = b.add("ColorChaser", "GlowChase", duration=3, initialValue=AMBER, initialDestination=AMBER)
    turn.isActive >> press.set_boolean
    press.inputTrue >> kick.set_boolean
    kick.triggerTime >> sweep.startTime
    sweep.fraction_changed >> colours.set_fraction
    colours.value_changed >> glow.set_destination
    glow.value_changed >> b.target("PhysicalMaterial", "ShadePaint").emissiveColor
    glow.value_changed >> b.target("PointLight", "BenchLight").color

    roll = b.add("SphereSensor", "Roll", parent="GlobeSense")
    b.add("TouchSensor", "RollTouch", parent="GlobeSense").hitPoint_changed >> b.target("Transform", "GlobeHit").translation
    moon = b.add("OrientationChaser", "MoonChase", duration=2)
    roll.rotation_changed >> b.target("Transform", "Globe").rotation
    roll.rotation_changed >> moon.set_destination
    moon.value_changed >> b.target("Transform", "MoonArm").rotation
    return b


# -- the drag plan: where a hand would press and move, in the pixels of a 960 x 600 X_ITE canvas ----------------------

def pixel(world):
    """Window pixels (from the top left) of a world point seen through VIEW."""
    turn = bs._Rot.axis_angle(*VIEW["orientation"]).inverse()
    x, y, z = turn.rotate(bs._v_sub(world, VIEW["position"]))
    f = VIEW["height"] / (2 * math.tan(VIEW["fieldOfView"] / 2))
    return VIEW["width"] / 2 + f * x / -z, VIEW["height"] / 2 - f * y / -z


def drag_plan():
    px = lambda p: [round(c) for c in p]                                    # noqa: E731
    # fader: grab the knob, slide right past +1 (the limit is 1 m = about 111 px), back left past -1, and stop at +0.4;
    # the pointer wanders up and down as a hand does, which a one-axis PlaneSensor ignores. Then a second, short grab
    # of the knob where it stopped, to show autoOffset: the next drag starts where the last one ended.
    knob = pixel((FADER_AT[0], FADER_AT[1] + 0.31, FADER_AT[2]))
    xs = [10 * k for k in range(1, 15)] + [140 - 10 * k for k in range(1, 29)] + [-140 + 10 * k for k in range(1, 20)]
    fader_path = [[round(knob[0] + x), round(knob[1] + 14 * math.sin(i / 3))] for i, x in enumerate(xs)]
    again = pixel((FADER_AT[0] + xs[-1] / 111, FADER_AT[1] + 0.31, FADER_AT[2]))
    second_path = [[round(again[0] - 10 * k), round(again[1] + 6 * math.sin(k))] for k in range(1, 9)]
    # dial: press on the brass face, then turn the pointer three quarters of a turn about the dial's centre on screen
    centre = pixel((DIAL_AT[0], DIAL_AT[1], DIAL_FACE))
    start = pixel((DIAL_AT[0] + 0.32 * math.cos(-0.6), DIAL_AT[1] + 0.32 * math.sin(-0.6), DIAL_FACE))
    radius, theta = math.hypot(start[0] - centre[0], start[1] - centre[1]), math.atan2(start[1] - centre[1], start[0] - centre[0])
    dial_path = [px((centre[0] + radius * math.cos(theta + 0.12 * k), centre[1] + radius * math.sin(theta + 0.12 * k)))
                 for k in range(1, 40)]
    # globe: press a little off its middle, sweep up and to the right, then back across and down
    middle = pixel(GLOBE_AT)
    press = (middle[0] - 14, middle[1] + 10)
    globe_path = [px((press[0] + 9 * k, press[1] - 6 * k)) for k in range(1, 17)] + \
        [px((press[0] + 144 - 7 * k, press[1] - 96 + 9 * k)) for k in range(1, 17)]
    return {"view": {**VIEW, "position": list(VIEW["position"]), "orientation": list(VIEW["orientation"])},
            "drags": [{"sensor": "Slide", "touch": "SlideTouch", "at": px(knob), "path": fader_path},
                      {"sensor": "Slide", "touch": "SlideTouch", "at": px(again), "path": second_path},
                      {"sensor": "Turn", "touch": "TurnTouch", "at": px(start), "path": dial_path},
                      {"sensor": "Roll", "touch": "RollTouch", "at": px(press), "path": globe_path}]}


if __name__ == "__main__":
    graph = behaviour()
    (HERE / "workbench.x3d").write_text(graph.weave(SCENE), encoding="utf-8")
    (HERE / "drags.json").write_text(json.dumps(drag_plan(), indent=1) + "\n", encoding="utf-8")
    print(HERE / "workbench.x3d", len(graph.nodes), "nodes", len(graph.routes), "ROUTEs", graph.check())
