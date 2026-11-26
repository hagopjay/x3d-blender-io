# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-07-spirograph.x3d: three nested rotating arms (Transforms inside Transforms, one OrientationInterpolator
each) carry a pen; a comet tail of 40 beads replays the pen's path, each bead from the same curve a little later
(a PositionInterpolator with shifted keys), and a rainbow runs down the tail.   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-07-spirograph.x3d")
T = 20.0                          # one closed figure
L = (2.6, 1.5, 0.8)               # arm lengths
W = (1, -3, 7)                    # whole turns per cycle (so the curve closes)
K = 144                           # samples per cycle
BEADS, LAG = 40, 2                # beads, samples between beads
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def pen(k):
    t = k / K
    x = sum(l * math.cos(2 * math.pi * sum(W[:j + 1]) * t) for j, l in enumerate(L))
    y = sum(l * math.sin(2 * math.pi * sum(W[:j + 1]) * t) for j, l in enumerate(L))
    return x, y


# the arms are nested: arm j turns W[j] times per cycle relative to its parent, so the pen's turns add up
for j, (l, w) in enumerate(zip(L, W)):
    segs = max(4, 4 * abs(w))
    ks = [s / segs for s in range(segs + 1)]
    angs = [2 * math.pi * w * k for k in ks]
    body.append(f'    <OrientationInterpolator DEF="Turn{j}" key="{f(*ks)}" keyValue="{" ".join(f(0, 0, 1, a) for a in angs)}" />')
    route("Clock", "fraction_changed", f"Turn{j}", "set_fraction")
    route(f"Turn{j}", "value_changed", f"Arm{j}", "rotation")

def bar(length, colour, thick):
    """An arm: a box from the pivot (the origin) out to `length` along x."""
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

for b in range(BEADS):
    ks = [k / K for k in range(K + 1)]
    pts = [pen((k - b * LAG) % K) for k in range(K + 1)]
    hues = [(b / BEADS * 0.8 + k / K) % 1 for k in range(0, K + 1, 12)]
    cols = [colorsys.hsv_to_rgb(h, 0.85, 1.0 - 0.55 * b / BEADS) for h in hues]
    hk = [k / K for k in range(0, K + 1, 12)]
    size = 0.1 - 0.06 * b / BEADS
    body.append(f'''    <Transform DEF="Bead{b}" translation="{f(*pts[0], 0)}">
      <Shape><Appearance><PhysicalMaterial DEF="BeadPaint{b}" baseColor="1 1 1" emissiveColor="0.5 0.5 0.5" /></Appearance><Sphere radius="{size:.3f}" /></Shape></Transform>
    <PositionInterpolator DEF="Trace{b}" key="{f(*ks)}" keyValue="{" ".join(f(x, y, 0) for x, y in pts)}" />
    <ColorInterpolator DEF="Rainbow{b}" key="{f(*hk)}" keyValue="{" ".join(f(*c) for c in cols)}" />''')
    route("Clock", "fraction_changed", f"Trace{b}", "set_fraction")
    route(f"Trace{b}", "value_changed", f"Bead{b}", "translation")
    route("Clock", "fraction_changed", f"Rainbow{b}", "set_fraction")
    route(f"Rainbow{b}", "value_changed", f"BeadPaint{b}", "baseColor")
    route(f"Rainbow{b}", "value_changed", f"BeadPaint{b}", "emissiveColor")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 07: spirograph" />
    <meta name="description" content="Three nested rotating arms carry a pen; forty beads replay its path as a rainbow comet tail." />
    <meta name="generator" content="tests/behaviour/demos/gallery-07-spirograph/build.py" />
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
