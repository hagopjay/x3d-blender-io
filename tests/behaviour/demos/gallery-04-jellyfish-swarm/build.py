# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-04-jellyfish-swarm.x3d: ten jellyfish, each following a glowing lure you drag (PlaneSensor) through
its own PositionChaser (duration 0.7 s to 3.4 s), so the swarm trails and tangles. Each jelly pulses, sways and glows
on its own looping clock.   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-04-jellyfish-swarm.x3d")
N = 10
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def jelly(i):
    ang = 2 * math.pi * i / N
    ox, oy = 1.6 * math.cos(ang) * (0.6 + 0.4 * (i % 3) / 2), 1.1 * math.sin(ang) - 0.2
    r, g, b = colorsys.hsv_to_rgb(0.5 + 0.45 * i / N, 0.7, 1.0)
    bright, dim = f"{r:.3f} {g:.3f} {b:.3f}", f"{r * .35:.3f} {g * .35:.3f} {b * .35:.3f}"
    dur = 0.7 + 0.3 * i                    # the chaser's catch-up time: 0.7 s ... 3.4 s
    cycle = 1.4 + 0.17 * i
    n, sway = 8, 0.28
    ks = [k / n for k in range(n + 1)]
    key = f(*ks)
    pulse = " ".join(f(1 + 0.16 * math.sin(2 * math.pi * k), 0.78 - 0.22 * math.sin(2 * math.pi * k), 1 + 0.16 * math.sin(2 * math.pi * k)) for k in ks)
    swing = " ".join(f"0 0 1 {sway * math.sin(2 * math.pi * k + i):.4f}" for k in ks)
    glow = " ".join(bright if math.sin(2 * math.pi * k) > 0 else dim for k in ks)
    tentacles = "".join(
        f'<Transform translation="{-0.22 + 0.11 * t:.3f} -0.35 0"><Shape><Appearance><PhysicalMaterial baseColor="{dim}" emissiveColor="{dim}" transparency="0.2" /></Appearance>'
        f'<Cylinder radius="0.012" height="{0.7 + 0.1 * (t % 2):.2f}" /></Shape></Transform>' for t in range(5))
    body.append(f'''    <Transform translation="{ox:.3f} {oy:.3f} {0.06 * i:.3f}">
      <Transform DEF="Jelly{i}" translation="0 0 0">
        <Transform DEF="Bell{i}" scale="1 0.78 1">
          <Shape><Appearance><PhysicalMaterial DEF="Skin{i}" baseColor="{bright}" emissiveColor="{dim}" transparency="0.15" roughness="0.2" /></Appearance>
            <Sphere radius="0.42" /></Shape>
        </Transform>
        <Transform DEF="Tent{i}" translation="0 -0.1 0">{tentacles}</Transform>
      </Transform>
    </Transform>
    <TimeSensor DEF="Beat{i}" cycleInterval="{cycle:.3f}" loop="true" />
    <PositionInterpolator DEF="Pulse{i}" key="{key}" keyValue="{pulse}" />
    <OrientationInterpolator DEF="Sway{i}" key="{key}" keyValue="{swing}" />
    <ColorInterpolator DEF="Glow{i}" key="{key}" keyValue="{glow}" />
    <PositionChaser DEF="Chase{i}" duration="{dur:.2f}" initialDestination="0 0 0" initialValue="0 0 0" />''')
    route(f"Beat{i}", "fraction_changed", f"Pulse{i}", "set_fraction")
    route(f"Beat{i}", "fraction_changed", f"Sway{i}", "set_fraction")
    route(f"Beat{i}", "fraction_changed", f"Glow{i}", "set_fraction")
    route(f"Pulse{i}", "value_changed", f"Bell{i}", "scale")
    route(f"Sway{i}", "value_changed", f"Tent{i}", "rotation")
    route(f"Glow{i}", "value_changed", f"Skin{i}", "emissiveColor")
    route(f"Glow{i}", "value_changed", f"Skin{i}", "baseColor")
    route("Drag", "translation_changed", f"Chase{i}", "set_destination")
    route(f"Chase{i}", "value_changed", f"Jelly{i}", "translation")


for i in range(N):
    jelly(i)

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Gallery 04: jellyfish swarm" />
    <meta name="description" content="Drag the glowing lure; ten jellyfish follow, each through its own PositionChaser." />
    <meta name="generator" content="tests/behaviour/demos/gallery-04-jellyfish-swarm/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.0 0.03 0.08" />
    <Viewpoint DEF="View" description="Front" position="0 0 9" />
    <DirectionalLight direction="0 -0.3 -1" intensity="0.7" />
    <Transform DEF="Lure" translation="0 0 0">
      <PlaneSensor DEF="Drag" description="Drag the lure" minPosition="-4.5 -2.4" maxPosition="4.5 2.4" autoOffset="true" />
      <Shape><Appearance><PhysicalMaterial baseColor="1 0.9 0.4" emissiveColor="1 0.8 0.2" /></Appearance><Sphere radius="0.22" /></Shape>
      <PointLight DEF="LureLight" location="0 0 0.4" color="1 0.9 0.5" intensity="40" radius="8" on="false" />
    </Transform>
    <ROUTE fromNode="Drag" fromField="translation_changed" toNode="Lure" toField="translation" />
    <ROUTE fromNode="Drag" fromField="isActive" toNode="LureLight" toField="on" />
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
