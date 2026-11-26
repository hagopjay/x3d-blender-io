# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-11-day-night-village.x3d: a diorama on a 24 s day. A sun and a moon ride a rotating arm, the sun light
cools from white through orange to blue night, 24 windows switch on one by one at dusk and off at dawn, stars come out, a
three-car train circles the village with a headlight that burns at night. Click the clock tower to skip to dusk is NOT
done; the day just runs.   python build.py"""
import math
import pathlib
import random

OUT = pathlib.Path(__file__).with_name("gallery-11-day-night-village.x3d")
DAY = 24.0
body = []
rng = random.Random(11)


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


body.append(f'    <TimeSensor DEF="Day" cycleInterval="{DAY}" loop="true" />')

# sun and moon on opposite ends of an arm that turns once a day
body.append('    <OrientationInterpolator DEF="Sky" key="0 0.125 0.25 0.375 0.5 0.625 0.75 0.875 1" keyValue="'
            + " ".join(f(0, 0, 1, -2 * math.pi * k / 8) for k in range(9)) + '" />')
route("Day", "fraction_changed", "Sky", "set_fraction")
route("Sky", "value_changed", "SkyArm", "rotation")
sky = f'''    <Transform translation="0 0 -7">
      <Transform DEF="SkyArm">
        <Transform translation="0 9 0"><Shape>{paint("1 0.9 0.4", "1 0.8 0.2")}<Sphere radius="0.9" /></Shape></Transform>
        <Transform translation="0 -9 0"><Shape>{paint("0.85 0.88 0.95", "0.5 0.55 0.7")}<Sphere radius="0.6" /></Shape></Transform>
      </Transform>
    </Transform>'''

# the sun light's colour through the day
sunc = ["1 0.95 0.85", "1 0.85 0.6", "1 0.5 0.2", "0.35 0.25 0.35", "0.08 0.1 0.25", "0.35 0.25 0.35", "1 0.5 0.25", "1 0.85 0.6", "1 0.95 0.85"]
body.append('    <ColorInterpolator DEF="SunTint" key="0 0.125 0.25 0.3 0.5 0.7 0.75 0.875 1" keyValue="' + " ".join(sunc) + '" />')
route("Day", "fraction_changed", "SunTint", "set_fraction")
route("SunTint", "value_changed", "SunLight", "color")

# twelve houses, two windows each, lit at night
houses = ""
spots = [(-5.5, -2.5), (-3.2, -3.4), (-0.8, -3.0), (1.6, -3.5), (4.0, -2.8), (6.2, -3.2),
         (-6.0, 1.2), (-3.4, 2.0), (-0.9, 1.4), (1.5, 2.2), (4.0, 1.6), (6.4, 2.0)]
w = 0
for i, (x, z) in enumerate(spots):
    h = 1.2 + 0.5 * (i % 3)
    houses += f'''
    <Transform translation="{x} {h / 2} {z}">
      <Shape>{paint(["0.85 0.75 0.6", "0.7 0.5 0.45", "0.6 0.65 0.75"][i % 3], None, 'roughness="0.8"')}<Box size="1.5 {h} 1.4" /></Shape>
      <Transform translation="0 {h / 2 + 0.35} 0" rotation="0 0 1 0"><Shape>{paint("0.45 0.2 0.15")}<Cone bottomRadius="1.15" height="0.8" /></Shape></Transform>'''
    for dx in (-0.4, 0.4):
        on = rng.uniform(0.25, 0.40)                  # dusk: the sun sets at 0.25 of the day
        off = rng.uniform(0.62, 0.74)                 # dawn
        houses += f'<Transform DEF="Win{w}" translation="{dx} 0.1 0.72" visible="false"><Shape>{paint("1 0.85 0.4", "1 0.8 0.3")}<Box size="0.3 0.35 0.04" /></Shape></Transform>'
        body.append(f'    <BooleanSequencer DEF="Lamp{w}" key="0 {on:.3f} {off:.3f} 1" keyValue="false true false false" />')
        route("Day", "fraction_changed", f"Lamp{w}", "set_fraction")
        route(f"Lamp{w}", "value_changed", f"Win{w}", "visible")
        w += 1
    houses += "\n    </Transform>"

stars = ""
for s in range(20):
    x, y, z = rng.uniform(-9, 9), rng.uniform(5, 9), -9.5
    on, off = rng.uniform(0.27, 0.35), rng.uniform(0.65, 0.73)
    stars += f'<Transform DEF="Star{s}" translation="{x:.2f} {y:.2f} {z}" visible="false"><Shape>{paint("1 1 0.9", "1 1 0.9")}<Sphere radius="0.08" /></Shape></Transform>'
    body.append(f'    <BooleanSequencer DEF="Twinkle{s}" key="0 {on:.3f} {off:.3f} 1" keyValue="false true false false" />')
    route("Day", "fraction_changed", f"Twinkle{s}", "set_fraction")
    route(f"Twinkle{s}", "value_changed", f"Star{s}", "visible")

# the train: three cars on a ring, each with its own delayed copy of the path
cars = ""
n = 48
for c in range(3):
    ks, ps, os_ = [], [], []
    for k in range(n + 1):
        t = (k / n) - 0.035 * c
        a = 2 * math.pi * t
        ps.append(f(8.2 * math.cos(a), 0.3, 5.2 * math.sin(a) + 0.0)); ks.append(f"{k / n:.5f}")
        os_.append(f(0, 1, 0, math.atan2(-5.2 * math.cos(a), -8.2 * math.sin(a))))
    cars += f'''
    <Transform DEF="Car{c}" translation="8.2 0.3 0">
      <Shape>{paint(["0.8 0.15 0.15", "0.2 0.4 0.8", "0.2 0.6 0.3"][c], None, 'metallic="0.3" roughness="0.5"')}<Box size="1.5 0.5 0.6" /></Shape>
      {'<PointLight DEF="Headlight" location="0 0.2 0" color="1 0.95 0.7" intensity="40" radius="8" on="false" />' if c == 0 else ""}
    </Transform>'''
    body.append(f'    <PositionInterpolator DEF="Rail{c}" key="{" ".join(ks)}" keyValue="{" ".join(ps)}" />')
    body.append(f'    <OrientationInterpolator DEF="Heading{c}" key="{" ".join(ks)}" keyValue="{" ".join(os_)}" />')
    route("Lap", "fraction_changed", f"Rail{c}", "set_fraction")
    route("Lap", "fraction_changed", f"Heading{c}", "set_fraction")
    route(f"Rail{c}", "value_changed", f"Car{c}", "translation")
    route(f"Heading{c}", "value_changed", f"Car{c}", "rotation")
body.append('    <TimeSensor DEF="Lap" cycleInterval="12" loop="true" />')
body.append('    <BooleanSequencer DEF="Beam" key="0 0.27 0.73 1" keyValue="false true false false" />')
route("Day", "fraction_changed", "Beam", "set_fraction")
route("Beam", "value_changed", "Headlight", "on")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 11: day-night village" />
    <meta name="description" content="A 24 second day: sun, moon, dusk windows, stars and a train with a headlight." />
    <meta name="generator" content="tests/behaviour/demos/gallery-11-day-night-village/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.3 0.5 0.8" />
    <Viewpoint DEF="View" description="Front" position="0 6.5 15" orientation="1 0 0 -0.3" />
    <DirectionalLight DEF="SunLight" direction="-0.3 -1 -0.4" intensity="1.0" color="1 0.95 0.85" />
    <Transform translation="0 -0.1 0"><Shape>{paint("0.25 0.5 0.25", None, 'roughness="0.95"')}<Box size="24 0.2 16" /></Shape></Transform>
{sky}
{stars}
{houses}
{cars}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
