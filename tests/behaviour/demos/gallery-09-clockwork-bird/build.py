# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-09-clockwork-bird.x3d: a brass bird flies a banking figure-eight round a clock tower; its wings flap on
SquadOrientationInterpolators, its wind-up key and two gears turn, and a click on the music box lifts the lid and
lets three notes float up.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-09-clockwork-bird.x3d")
T = 12.0
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def qmul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def axq(ax, ang):
    s = math.sin(ang / 2)
    return (math.cos(ang / 2), ax[0] * s, ax[1] * s, ax[2] * s)


def toaxis(q):
    w, x, y, z = q
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    ang = 2 * math.acos(max(-1.0, min(1.0, w)))
    s = math.sqrt(max(1e-12, 1 - w * w))
    return (x / s, y / s, z / s, ang) if ang > 1e-6 else (0, 1, 0, 0)


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


def spot(t):
    """Where the bird is at fraction t: a figure-eight, bobbing."""
    a = 2 * math.pi * t
    return (5.0 * math.sin(a), 3.2 + 0.5 * math.sin(3 * a), 3.0 * math.sin(2 * a))


# the flight: position and a banking heading
n = 72
ks, ps, os_ = [], [], []
for k in range(n + 1):
    t = k / n
    p, p2 = spot(t), spot(t + 0.002)
    vx, vz = p2[0] - p[0], p2[2] - p[2]
    yaw = math.atan2(-vz, vx)
    a = 2 * math.pi * t
    turn = (2 * math.cos(2 * a) * 3.0 * 2) / 8.0            # lateral swing -> bank
    bank = max(-0.6, min(0.6, 0.35 * turn))
    ks.append(f"{t:.5f}"); ps.append(f(*p)); os_.append(f(*toaxis(qmul(axq((0, 1, 0), yaw), axq((1, 0, 0), bank)))))

brass = paint("0.85 0.62 0.2", None, 'metallic="1" roughness="0.3"')
feather = paint("0.9 0.75 0.4", None, 'metallic="1" roughness="0.35"')
dark = paint("0.25 0.2 0.15", None, 'metallic="1" roughness="0.4"')


def wing(side, sign):
    return (f'<Transform DEF="Wing{side}" translation="0 0.1 {0.22 * sign}">'
            f'<Transform translation="0 0 {0.55 * sign}"><Shape>{feather}<Box size="0.45 0.04 1.1" /></Shape></Transform></Transform>')


bird = f'''    <Transform DEF="Bird" translation="{ps[0]}" rotation="{os_[0]}">
      <Transform scale="1.3 0.7 0.7"><Shape>{brass}<Sphere radius="0.4" /></Shape></Transform>
      <Transform translation="0.6 0.2 0"><Shape>{brass}<Sphere radius="0.2" /></Shape></Transform>
      <Transform translation="0.5 0.3 0.12"><Shape>{dark}<Sphere radius="0.04" /></Shape></Transform>
      <Transform translation="0.5 0.3 -0.12"><Shape>{dark}<Sphere radius="0.04" /></Shape></Transform>
      <Transform translation="0.85 0.17 0" rotation="0 0 1 -1.5708"><Shape>{dark}<Cone bottomRadius="0.07" height="0.3" /></Shape></Transform>
      <Transform translation="-0.75 0.05 0" rotation="0 0 1 0.2"><Shape>{feather}<Box size="0.5 0.04 0.35" /></Shape></Transform>
      <Transform DEF="Key" translation="-0.1 0.35 0"><Transform translation="0 0.15 0"><Shape>{dark}<Box size="0.04 0.3 0.04" /></Shape></Transform>
        <Transform translation="0 0.3 0"><Shape>{dark}<Box size="0.3 0.08 0.04" /></Shape></Transform></Transform>
      {wing("R", 1)}{wing("L", -1)}
    </Transform>'''

# flapping: a Squad through up, level, down, level (one clock, the left wing mirrors the right)
fk = [0, 0.25, 0.5, 0.75, 1]
up = [0.9, 0.0, -0.7, 0.0, 0.9]
sq = lambda sign: " ".join(f(*toaxis(axq((1, 0, 0), sign * a))) for a in up)
body.append(f'    <TimeSensor DEF="Wingbeat" cycleInterval="0.5" loop="true" />')
body.append(f'    <SquadOrientationInterpolator DEF="FlapR" key="{f(*fk)}" keyValue="{sq(-1)}" />')
body.append(f'    <SquadOrientationInterpolator DEF="FlapL" key="{f(*fk)}" keyValue="{sq(1)}" />')
route("Wingbeat", "fraction_changed", "FlapR", "set_fraction")
route("Wingbeat", "fraction_changed", "FlapL", "set_fraction")
route("FlapR", "value_changed", "WingR", "rotation")
route("FlapL", "value_changed", "WingL", "rotation")
body.append(f'    <TimeSensor DEF="Fly" cycleInterval="{T}" loop="true" />')
body.append(f'    <PositionInterpolator DEF="FlyPos" key="{" ".join(ks)}" keyValue="{" ".join(ps)}" />')
body.append(f'    <OrientationInterpolator DEF="FlyTurn" key="{" ".join(ks)}" keyValue="{" ".join(os_)}" />')
route("Fly", "fraction_changed", "FlyPos", "set_fraction")
route("Fly", "fraction_changed", "FlyTurn", "set_fraction")
route("FlyPos", "value_changed", "Bird", "translation")
route("FlyTurn", "value_changed", "Bird", "rotation")
body.append('    <TimeSensor DEF="Wind" cycleInterval="4" loop="true" />')
body.append('    <OrientationInterpolator DEF="WindTurn" key="0 0.25 0.5 0.75 1" keyValue="0 1 0 0 0 1 0 1.5708 0 1 0 3.1416 0 1 0 4.7124 0 1 0 6.2832" />')
route("Wind", "fraction_changed", "WindTurn", "set_fraction")
route("WindTurn", "value_changed", "Key", "rotation")

# the tower: a clock face and two meshing gears
gear = lambda name, x, r, teeth, speed_sign: (
    f'<Transform DEF="{name}" translation="{x} 1.5 -2.5">'
    f'<Shape>{brass}<Cylinder radius="{r}" height="0.2" /></Shape>'
    + "".join(f'<Transform rotation="0 0 1 {2 * math.pi * k / teeth:.4f}"><Transform translation="{r + 0.08} 0 0"><Shape>{brass}<Box size="0.2 0.14 0.2" /></Shape></Transform></Transform>' for k in range(teeth))
    + '</Transform>')
tower = f'''    <Transform translation="0 1.2 -2.5"><Shape>{paint("0.45 0.35 0.3", None, 'roughness="0.8"')}<Box size="2.2 2.4 1.2" /></Shape></Transform>
    <Transform translation="0 3.0 -1.85"><Shape>{paint("0.95 0.93 0.85")}<Cylinder radius="0.8" height="0.1" /></Shape></Transform>
    <Transform DEF="Hand" translation="0 3.0 -1.75"><Transform translation="0 0.35 0"><Shape>{dark}<Box size="0.08 0.7 0.04" /></Shape></Transform></Transform>
    {gear("GearA", -2.4, 0.7, 8, 1)}
    {gear("GearB", -3.75, 0.55, 6, -1)}'''
body.append('    <TimeSensor DEF="Tick" cycleInterval="6" loop="true" />')
body.append('    <OrientationInterpolator DEF="TickTurn" key="0 0.25 0.5 0.75 1" keyValue="0 0 1 0 0 0 1 -1.5708 0 0 1 -3.1416 0 0 1 -4.7124 0 0 1 -6.2832" />')
body.append('    <OrientationInterpolator DEF="TurnA" key="0 0.25 0.5 0.75 1" keyValue="0 0 1 0 0 0 1 1.5708 0 0 1 3.1416 0 0 1 4.7124 0 0 1 6.2832" />')
body.append('    <OrientationInterpolator DEF="TurnB" key="0 0.25 0.5 0.75 1" keyValue="0 0 1 0 0 0 1 -2.0944 0 0 1 -4.1888 0 0 1 -6.2832 0 0 1 -8.3776" />')
route("Tick", "fraction_changed", "TickTurn", "set_fraction")
route("Tick", "fraction_changed", "TurnA", "set_fraction")
route("Tick", "fraction_changed", "TurnB", "set_fraction")
route("TickTurn", "value_changed", "Hand", "rotation")
route("TurnA", "value_changed", "GearA", "rotation")
route("TurnB", "value_changed", "GearB", "rotation")

# the music box: click it, the lid lifts and three notes float up
notes = "".join(
    f'<Transform DEF="Note{i}" translation="{3.6 + 0.25 * i} 0.9 1.2" visible="false"><Shape>{paint("1 0.9 0.3", "1 0.8 0.2")}<Sphere radius="0.12" /></Shape></Transform>' for i in range(3))
box = f'''    <Transform DEF="MusicBox" translation="3.6 0.4 1.2">
      <TouchSensor DEF="BoxTouch" description="Click: play the music box" />
      <Shape>{paint("0.5 0.2 0.2", None, 'roughness="0.6"')}<Box size="1.2 0.8 0.8" /></Shape>
    </Transform>
    <Transform DEF="Lid" translation="3.0 0.8 1.2"><Transform translation="0.6 0.05 0"><Shape>{paint("0.6 0.25 0.25")}<Box size="1.2 0.1 0.8" /></Shape></Transform></Transform>
    {notes}'''
body.append('    <BooleanFilter DEF="BoxPress" />')
body.append('    <TimeTrigger DEF="BoxGo" />')
body.append('    <TimeSensor DEF="Tune" cycleInterval="2.4" />')
body.append('    <OrientationInterpolator DEF="LidOpen" key="0 0.15 0.85 1" keyValue="0 0 1 0 0 0 1 1.1 0 0 1 1.1 0 0 1 0" />')
route("BoxTouch", "isActive", "BoxPress", "set_boolean")
route("BoxPress", "inputTrue", "BoxGo", "set_boolean")
route("BoxGo", "triggerTime", "Tune", "startTime")
route("Tune", "fraction_changed", "LidOpen", "set_fraction")
route("LidOpen", "value_changed", "Lid", "rotation")
for i in range(3):
    s0 = 0.1 + 0.2 * i
    body.append(f'    <PositionInterpolator DEF="Float{i}" key="0 {s0:.2f} 1" keyValue="{3.6 + 0.25 * i} 0.9 1.2 {3.6 + 0.25 * i} 0.9 1.2 {3.6 + 0.9 * i / 2 - 0.4} {3.4 + i * 0.4} 1.2" />')
    route("Tune", "fraction_changed", f"Float{i}", "set_fraction")
    route(f"Float{i}", "value_changed", f"Note{i}", "translation")
    route("Tune", "isActive", f"Note{i}", "visible")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 09: clockwork bird" />
    <meta name="description" content="A brass bird flaps round a clock tower; click the music box for notes." />
    <meta name="generator" content="tests/behaviour/demos/gallery-09-clockwork-bird/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.35 0.5 0.75" />
    <Viewpoint DEF="View" description="Front" position="0 3.6 9.5" orientation="1 0 0 -0.12" />
    <DirectionalLight direction="-0.4 -1 -0.6" intensity="1.0" />
    <Transform translation="0 -0.1 0"><Shape>{paint("0.3 0.45 0.25", None, 'roughness="0.9"')}<Box size="20 0.2 12" /></Shape></Transform>
{tower}
{box}
{bird}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
