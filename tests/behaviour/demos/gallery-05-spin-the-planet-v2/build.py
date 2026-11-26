# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-05-spin-the-planet-v2.x3d: grab a planet (SphereSensor) and spin it; five moons, each behind its own
OrientationChaser (0.4 s to 4 s), swing round after it and settle. A sun cycles colour, moons tumble, 16 stars twinkle
(BooleanSequencers), rings glow while you hold the planet. Version 2: a full turn is four keys, never three (a step of
exactly pi has no shortest way round).   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-05-spin-the-planet-v2.x3d")
body = []
late = []          # v2: every ROUTE goes after the nodes it names (X_ITE drops a ROUTE written before its DEFs)


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    late.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def mat(base, emissive=None, d=None, rough=0.5, metallic=0.0):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    dd = f' DEF="{d}"' if d else ""
    return f'<Appearance><PhysicalMaterial{dd} baseColor="{base}"{em} roughness="{rough}" metallic="{metallic}" /></Appearance>'


# the planet: ocean ball with continents (so a spin can be seen), a ring that glows while held
blobs = "".join(
    f'<Transform translation="{1.08 * math.cos(la) * math.cos(lo):.3f} {1.08 * math.sin(la):.3f} {1.08 * math.cos(la) * math.sin(lo):.3f}" '
    f'rotation="0 1 0 {-lo:.3f}"><Shape>{mat("0.25 0.7 0.3")}<Sphere radius="{r}" /></Shape></Transform>'
    for la, lo, r in [(0.5, 0.2, 0.35), (-0.3, 1.5, 0.4), (0.1, 3.0, 0.3), (-0.6, 4.4, 0.35), (0.8, 5.3, 0.25), (0.0, 0.0, 0.25)])
moons = [(2.1, 0.0, 0.0), (2.9, 0.4, 2.3), (3.7, -0.5, 4.2), (4.5, 0.3, 1.1), (5.3, -0.2, 5.4)]
duration = [0.4, 0.9, 1.6, 2.6, 4.0]
for i, ((rad, h, phase), dur) in enumerate(zip(moons, duration)):
    shade = 0.45 + 0.11 * i
    body.append(f'''    <Transform DEF="Arm{i}">
      <Transform translation="{rad * math.cos(phase):.3f} {h} {rad * math.sin(phase):.3f}">
        <Transform DEF="Tumble{i}"><Shape>{mat(f"{shade:.2f} {shade:.2f} {shade + 0.1:.2f}", d=f"MoonPaint{i}")}<Sphere radius="{0.26 + 0.05 * (i % 3)}" /></Shape>
          <Transform translation="0.28 0 0"><Shape>{mat("0.9 0.4 0.2")}<Box size="0.12 0.12 0.12" /></Shape></Transform></Transform>
      </Transform>
    </Transform>
    <OrientationChaser DEF="Swing{i}" duration="{dur}" initialDestination="0 1 0 0" initialValue="0 1 0 0" />
    <TimeSensor DEF="Roll{i}" cycleInterval="{2 + i}" loop="true" />
    <OrientationInterpolator DEF="Tum{i}" key="0 0.3333 0.6667 1" keyValue="0 0 1 0 0 0 1 2.0944 0 0 1 4.1888 0 0 1 6.2832" />''')
    route("Planet", "rotation_changed", f"Swing{i}", "set_destination")
    route(f"Swing{i}", "value_changed", f"Arm{i}", "rotation")
    route(f"Roll{i}", "fraction_changed", f"Tum{i}", "set_fraction")
    route(f"Tum{i}", "value_changed", f"Tumble{i}", "rotation")

stars = []
for s in range(16):
    a = s * 2.399963
    x, y = 12 * math.cos(a) * (0.4 + 0.6 * ((s * 7) % 16) / 16), 6 * math.sin(a) * (0.4 + 0.6 * ((s * 5) % 16) / 16) + 1
    stars.append(f'''    <Transform DEF="Star{s}" translation="{x:.2f} {y:.2f} -6">
      <Shape>{mat("1 1 0.9", "1 1 0.9")}<Sphere radius="0.07" /></Shape></Transform>
    <TimeSensor DEF="Twinkle{s}" cycleInterval="{1.1 + 0.37 * s % 3:.2f}" loop="true" />
    <BooleanSequencer DEF="Blink{s}" key="0 0.7 0.85 1" keyValue="true false true true" />''')
    route(f"Twinkle{s}", "fraction_changed", f"Blink{s}", "set_fraction")
    route(f"Blink{s}", "value_changed", f"Star{s}", "visible")
body.extend(stars)

sun = " ".join(["1 0.9 0.6", "1 0.6 0.3", "0.9 0.5 0.9", "0.6 0.8 1", "1 0.9 0.6"])
SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Gallery 05: spin the planet" />
    <meta name="description" content="Drag the planet to spin it; five moons follow through OrientationChasers of different speeds." />
    <meta name="generator" content="tests/behaviour/demos/gallery-05-spin-the-planet-v2/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.01 0.01 0.04" />
    <Viewpoint DEF="View" description="Front" position="0 2.6 9.5" orientation="1 0 0 -0.22" />
    <PointLight DEF="SunLight" location="-9 3 4" color="1 0.9 0.6" intensity="900" radius="40" />
    <Transform translation="-9 3 4"><Shape>{mat("1 0.9 0.5", "1 0.8 0.3", d="SunPaint")}<Sphere radius="0.9" /></Shape></Transform>
    <TimeSensor DEF="SunClock" cycleInterval="12" loop="true" />
    <ColorInterpolator DEF="SunHue" key="0 0.25 0.5 0.75 1" keyValue="{sun}" />
    <ROUTE fromNode="SunClock" fromField="fraction_changed" toNode="SunHue" toField="set_fraction" />
    <ROUTE fromNode="SunHue" fromField="value_changed" toNode="SunLight" toField="color" />
    <ROUTE fromNode="SunHue" fromField="value_changed" toNode="SunPaint" toField="emissiveColor" />
    <ROUTE fromNode="SunHue" fromField="value_changed" toNode="SunPaint" toField="baseColor" />
    <Transform DEF="Planet">
      <SphereSensor DEF="Spin" description="Drag to spin the planet" autoOffset="true" />
      <Shape>{mat("0.1 0.35 0.8", rough=0.3)}<Sphere radius="1" /></Shape>
      {blobs}
      <Transform DEF="Ring" scale="1 0.04 1" visible="false"><Shape>{mat("1 0.8 0.3", "1 0.7 0.2")}<Cylinder radius="1.8" height="1" /></Shape></Transform>
    </Transform>
    <ROUTE fromNode="Spin" fromField="rotation_changed" toNode="Planet" toField="rotation" />
    <ROUTE fromNode="Spin" fromField="isActive" toNode="Ring" toField="visible" />
{chr(10).join(body)}
{chr(10).join(late)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
