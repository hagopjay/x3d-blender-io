# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-08-spirograph-chain.x3d (gallery 07 redone, much lighter): three nested rotating arms carry a pen; a
snake of 60 beads draws the path. Bead 0 plays the pen's curve (one PositionInterpolator); every other bead is a
PositionChaser that chases the bead before it (duration 0.1 s), so the whole tail is a chain with one table.   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-08-spirograph-chain.x3d")
T = 16.0
L = (2.4, 1.4, 0.7)
W = (1, -3, 5)                    # turns per cycle of each arm relative to its parent (cumulative 1, -2, 3)
K = 160                           # samples of the pen's curve
BEADS, CHASE = 60, 0.1
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def pen(k):
    t = k / K
    turns = [sum(W[:j + 1]) for j in range(3)]
    return (sum(l * math.cos(2 * math.pi * n * t) for l, n in zip(L, turns)),
            sum(l * math.sin(2 * math.pi * n * t) for l, n in zip(L, turns)))


for j, w in enumerate(W):
    segs = max(4, 4 * abs(w))
    ks = [s / segs for s in range(segs + 1)]
    body.append(f'    <OrientationInterpolator DEF="Turn{j}" key="{f(*ks)}" keyValue="{" ".join(f(0, 0, 1, 2 * math.pi * w * k) for k in ks)}" />')
    route("Clock", "fraction_changed", f"Turn{j}", "set_fraction")
    route(f"Turn{j}", "value_changed", f"Arm{j}", "rotation")


def bar(length, colour, thick):
    return (f'<Transform translation="{length / 2} 0 0"><Shape><Appearance><PhysicalMaterial baseColor="{colour}" metallic="1" roughness="0.3" />'
            f'</Appearance><Box size="{length} {thick} {thick}" /></Shape></Transform>')


hub = '<Shape><Appearance><PhysicalMaterial baseColor="0.9 0.6 0.2" metallic="1" /></Appearance><Cylinder radius="0.18" height="0.3" /></Shape>'
mech = f'''    <Transform DEF="Arm0">
      {hub}{bar(L[0], "0.7 0.7 0.75", 0.12)}
      <Transform DEF="Arm1" translation="{L[0]} 0 0.05">
        {bar(L[1], "0.5 0.7 0.9", 0.1)}
        <Transform DEF="Arm2" translation="{L[1]} 0 0.05">
          {bar(L[2], "0.9 0.5 0.6", 0.08)}
          <Transform DEF="Pen" translation="{L[2]} 0 0.05"><Shape><Appearance><PhysicalMaterial baseColor="1 1 1" emissiveColor="1 1 1" /></Appearance><Sphere radius="0.14" /></Shape></Transform>
        </Transform>
      </Transform>
    </Transform>'''

ks = [k / K for k in range(K + 1)]
pts = [pen(k) for k in range(K + 1)]
body.append(f'    <PositionInterpolator DEF="Path" key="{f(*ks)}" keyValue="{" ".join(f(x, y, 0) for x, y in pts)}" />')
route("Clock", "fraction_changed", "Path", "set_fraction")
hk = [k / 6 for k in range(7)]
for b in range(BEADS):
    cols = [colorsys.hsv_to_rgb((b / BEADS * 0.9 + k) % 1, 0.85, 1.0 - 0.5 * b / BEADS) for k in hk]
    size = 0.11 - 0.07 * b / BEADS
    body.append(f'''    <Transform DEF="Bead{b}" translation="{f(*pts[0], 0)}">
      <Shape><Appearance><PhysicalMaterial DEF="BeadPaint{b}" baseColor="1 1 1" emissiveColor="0.5 0.5 0.5" /></Appearance><Sphere radius="{size:.3f}" /></Shape></Transform>
    <ColorInterpolator DEF="Rainbow{b}" key="{f(*hk)}" keyValue="{" ".join(f(*c) for c in cols)}" />''')
    route("Clock", "fraction_changed", f"Rainbow{b}", "set_fraction")
    route(f"Rainbow{b}", "value_changed", f"BeadPaint{b}", "baseColor")
    route(f"Rainbow{b}", "value_changed", f"BeadPaint{b}", "emissiveColor")
    if b == 0:
        route("Path", "value_changed", "Bead0", "translation")
    else:
        body.append(f'    <PositionChaser DEF="Follow{b}" duration="{CHASE}" initialDestination="{f(*pts[0], 0)}" initialValue="{f(*pts[0], 0)}" />')
        route("Path" if b == 1 else f"Follow{b - 1}", "value_changed" if b > 1 else "value_changed", f"Follow{b}", "set_destination")
        route(f"Follow{b}", "value_changed", f"Bead{b}", "translation")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Gallery 08: spirograph chain" />
    <meta name="description" content="Three nested arms carry a pen; a snake of sixty chasing beads draws its path." />
    <meta name="generator" content="tests/behaviour/demos/gallery-08-spirograph-chain/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.02 0.04" />
    <Viewpoint DEF="View" description="Front" position="0 0 11" />
    <DirectionalLight direction="0 0 -1" intensity="0.9" />
    <TimeSensor DEF="Clock" cycleInterval="{T}" loop="true" />
{mech}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
