# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-10-ferris-wheel.x3d: a night fair. One OrientationInterpolator turns the wheel; its mirror image (the same
angles, negated) is routed to all twelve gondolas, so they stay upright as they ride round. Twenty-four rim bulbs chase
round on BooleanSequencers. Click the ticket booth to stop the wheel, click again to start it.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-10-ferris-wheel.x3d")
SPIN, R, GONDOLAS, BULBS = 18.0, 4.2, 12, 24
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


steel = paint("0.75 0.75 0.8", None, 'metallic="1" roughness="0.35"')
palette = ["1 0.3 0.3", "1 0.7 0.2", "0.4 0.9 0.4", "0.3 0.7 1", "0.8 0.4 1", "1 0.5 0.8"]

# the wheel: a rim of 24 bars, 12 spokes, twelve gondolas that hang from the rim
rim = "".join(
    f'<Transform translation="{R * math.cos(a):.3f} {R * math.sin(a):.3f} 0" rotation="0 0 1 {a + math.pi / 2:.4f}"><Shape>{steel}<Box size="{2 * R * math.sin(math.pi / 24) + 0.05:.3f} 0.14 0.3" /></Shape></Transform>'
    for a in [2 * math.pi * k / 24 for k in range(24)])
spokes = "".join(
    f'<Transform rotation="0 0 1 {2 * math.pi * k / GONDOLAS:.4f}"><Transform translation="{R / 2} 0 0"><Shape>{steel}<Box size="{R} 0.08 0.12" /></Shape></Transform></Transform>'
    for k in range(GONDOLAS))
gondolas = ""
for k in range(GONDOLAS):
    a = 2 * math.pi * k / GONDOLAS
    c = palette[k % 6]
    gondolas += f'''
      <Transform translation="{R * math.cos(a):.3f} {R * math.sin(a):.3f} 0">
        <Transform DEF="Cab{k}"><Transform translation="0 -0.55 0">
          <Shape>{paint(c, None, 'roughness="0.4"')}<Box size="0.9 0.6 0.7" /></Shape>
          <Transform translation="0 0.45 0"><Shape>{steel}<Cylinder radius="0.02" height="0.4" /></Shape></Transform>
        </Transform></Transform>
      </Transform>'''
bulbs = ""
for b in range(BULBS):
    a = 2 * math.pi * (b + 0.5) / BULBS
    bulbs += f'<Transform DEF="Bulb{b}" translation="{(R + 0.12) * math.cos(a):.3f} {(R + 0.12) * math.sin(a):.3f} 0.2"><Shape>{paint("1 0.9 0.5", "1 0.85 0.4")}<Sphere radius="0.1" /></Shape></Transform>'
wheel = f'''    <Transform translation="0 5.4 0">
      <Transform DEF="Wheel">
        {rim}{spokes}{gondolas}
        {bulbs}
        <Shape>{paint("0.9 0.4 0.2", None, 'metallic="1"')}<Cylinder radius="0.35" height="0.5" /></Shape>
      </Transform>
    </Transform>
    <Transform translation="-2.2 2.7 0" rotation="0 0 1 0.6"><Shape>{steel}<Box size="0.25 6.0 0.25" /></Shape></Transform>
    <Transform translation="2.2 2.7 0" rotation="0 0 1 -0.6"><Shape>{steel}<Box size="0.25 6.0 0.25" /></Shape></Transform>'''

# one clock; the wheel's angles, and the same angles negated for the cabins
n = 12
ks = [k / n for k in range(n + 1)]
angs = [2 * math.pi * k for k in ks]
body.append(f'    <TimeSensor DEF="Spin" cycleInterval="{SPIN}" loop="true" />')
body.append(f'    <OrientationInterpolator DEF="Turn" key="{f(*ks)}" keyValue="{" ".join(f(0, 0, 1, a) for a in angs)}" />')
body.append(f'    <OrientationInterpolator DEF="Level" key="{f(*ks)}" keyValue="{" ".join(f(0, 0, 1, -a) for a in angs)}" />')
route("Spin", "fraction_changed", "Turn", "set_fraction")
route("Spin", "fraction_changed", "Level", "set_fraction")
route("Turn", "value_changed", "Wheel", "rotation")
for k in range(GONDOLAS):
    route("Level", "value_changed", f"Cab{k}", "rotation")

# bulbs chase: bulb b is on for a quarter of the 1.5 s lap, starting at its place
body.append('    <TimeSensor DEF="Chase" cycleInterval="1.5" loop="true" />')
for b in range(BULBS):
    s = b / BULBS
    e = (s + 0.25) % 1.0
    if s + 0.25 <= 1.0:
        keys, vals = [0, s, s + 0.25, 1.0], ["false", "true", "false", "false"]
        if s == 0:
            keys, vals = [0, 0.25, 1.0], ["true", "false", "false"]
    else:
        keys, vals = [0, e, s, 1.0], ["true", "false", "true", "true"]
    body.append(f'    <BooleanSequencer DEF="Flash{b}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route("Chase", "fraction_changed", f"Flash{b}", "set_fraction")
    route(f"Flash{b}", "value_changed", f"Bulb{b}", "visible")

# the ticket booth: click to stop the wheel and the bulbs, click again to go (the first click sends true; negated, it is "enabled false")
booth = f'''    <Transform DEF="Booth" translation="6 0.8 2">
      <TouchSensor DEF="BoothTouch" description="Click: stop or start the wheel" />
      <Shape>{paint("0.8 0.15 0.15", None, 'roughness="0.6"')}<Box size="1.6 1.6 1.2" /></Shape>
      <Transform translation="0 1.0 0"><Shape>{paint("1 0.9 0.4", "0.6 0.5 0.1")}<Cone bottomRadius="1.1" height="0.7" /></Shape></Transform>
    </Transform>'''
body.append('    <BooleanFilter DEF="BoothPress" />')
body.append('    <BooleanToggle DEF="Halt" />')
body.append('    <BooleanFilter DEF="Running" />')
route("BoothTouch", "isActive", "BoothPress", "set_boolean")
route("BoothPress", "inputTrue", "Halt", "set_boolean")
route("Halt", "toggle_changed", "Running", "set_boolean")
route("Running", "inputNegate", "Spin", "enabled")
route("Running", "inputNegate", "Chase", "enabled")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 10: Ferris wheel" />
    <meta name="description" content="A night-fair wheel whose cabins stay upright; click the booth to stop it." />
    <meta name="generator" content="tests/behaviour/demos/gallery-10-ferris-wheel/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.02 0.08" />
    <Viewpoint DEF="View" description="Front" position="0 5 15" orientation="1 0 0 -0.05" />
    <DirectionalLight direction="-0.2 -0.5 -1" intensity="0.8" />
    <PointLight location="0 5.4 4" color="1 0.85 0.6" intensity="120" radius="20" />
    <Transform translation="0 -0.1 0"><Shape>{paint("0.1 0.15 0.1", None, 'roughness="0.9"')}<Box size="24 0.2 10" /></Shape></Transform>
{wheel}
{booth}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
