# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-12-kaleidoscope.x3d: a mandala of 12 mirrored sectors (6 turns x 2 mirrors). Each of 8 "petals" has ONE
PositionInterpolator, one scale pulse and one ColorInterpolator whose outputs are routed to the same petal in all 12
sectors, so the symmetry is exact and the world has 8 x 3 animations instead of 288. The hub (TouchSensor) pauses and
resumes it (a ROUTE to the clocks' `enabled`).   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-12-kaleidoscope.x3d")
T, SECTORS, PETALS, K = 12.0, 6, 8, 24
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


GEOMS = ['<Sphere radius="0.28" />', '<Box size="0.45 0.45 0.12" />', '<Cone bottomRadius="0.25" height="0.55" />', '<Cylinder radius="0.2" height="0.5" />']
ks = [k / K for k in range(K + 1)]
for s in range(PETALS):
    a, b, ph = (1, 2, 3, 2, 1, 3, 2, 1)[s], (2, 1, 2, 3, 3, 1, 1, 2)[s], 0.13 * s
    pts = [(2.9 + 1.7 * math.sin(2 * math.pi * (a * t + ph)), 1.5 * math.sin(2 * math.pi * (b * t + ph * 2)) * (0.5 + 0.5 * math.cos(2 * math.pi * t))) for t in ks]
    puls = [0.8 + 0.5 * math.sin(2 * math.pi * ((s % 3 + 1) * t)) for t in ks]
    hue = s / PETALS
    cols = [colorsys.hsv_to_rgb((hue + 0.25 * math.sin(2 * math.pi * t)) % 1, 0.8, 0.55 + 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * (a * t + ph)))) for t in ks]
    body.append(f'    <PositionInterpolator DEF="Path{s}" key="{f(*ks)}" keyValue="{" ".join(f(x, y, 0) for x, y in pts)}" />')
    body.append(f'    <PositionInterpolator DEF="Pulse{s}" key="{f(*ks)}" keyValue="{" ".join(f(p, p, p) for p in puls)}" />')
    body.append(f'    <ColorInterpolator DEF="Hue{s}" key="{f(*ks)}" keyValue="{" ".join(f(*c) for c in cols)}" />')
    for fld in ("Path", "Pulse", "Hue"):
        route("Beat", "fraction_changed", f"{fld}{s}", "set_fraction")

sectors = ""
for i in range(SECTORS):
    for j in (0, 1):
        sy = 1 if j == 0 else -1
        sectors += f'    <Transform translation="0 0 0" rotation="0 0 1 {math.pi * 2 * i / SECTORS:.4f}" scale="1 {sy} 1">\n'
        for s in range(PETALS):
            sectors += (f'      <Transform DEF="Petal{i}{j}{s}" translation="3 0 {0.02 * s:.2f}"><Shape><Appearance><PhysicalMaterial DEF="Paint{i}{j}{s}" baseColor="1 1 1" emissiveColor="0.4 0.4 0.4" roughness="0.3" /></Appearance>'
                        f'{GEOMS[s % 4]}</Shape></Transform>\n')
            route(f"Path{s}", "value_changed", f"Petal{i}{j}{s}", "translation")
            route(f"Pulse{s}", "value_changed", f"Petal{i}{j}{s}", "scale")
            route(f"Hue{s}", "value_changed", f"Paint{i}{j}{s}", "baseColor")
            route(f"Hue{s}", "value_changed", f"Paint{i}{j}{s}", "emissiveColor")
        sectors += "    </Transform>\n"

# the whole mandala turns slowly
n = 12
rk = [k / n for k in range(n + 1)]
body.append(f'    <OrientationInterpolator DEF="Drift" key="{f(*rk)}" keyValue="{" ".join(f(0, 0, 1, 2 * math.pi * k) for k in rk)}" />')
route("Slow", "fraction_changed", "Drift", "set_fraction")
route("Drift", "value_changed", "Mandala", "rotation")
body.append(f'    <TimeSensor DEF="Beat" cycleInterval="{T}" loop="true" />')
body.append('    <TimeSensor DEF="Slow" cycleInterval="60" loop="true" />')

# the hub: click to pause or resume (first click sends true; negated it disables the clocks)
body.append('    <BooleanFilter DEF="HubPress" />')
body.append('    <BooleanToggle DEF="Halt" />')
body.append('    <BooleanFilter DEF="Running" />')
route("HubTouch", "isActive", "HubPress", "set_boolean")
route("HubPress", "inputTrue", "Halt", "set_boolean")
route("Halt", "toggle_changed", "Running", "set_boolean")
route("Running", "inputNegate", "Beat", "enabled")
route("Running", "inputNegate", "Slow", "enabled")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 12: kaleidoscope" />
    <meta name="description" content="A mandala of 12 mirrored sectors driven by 24 animations; click the hub to pause." />
    <meta name="generator" content="tests/behaviour/demos/gallery-12-kaleidoscope/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.01 0.0 0.02" />
    <Viewpoint DEF="View" description="Front" position="0 0 14" />
    <DirectionalLight direction="0 0 -1" intensity="1.0" />
    <Transform DEF="Mandala">
{sectors}
    </Transform>
    <Transform DEF="Hub" rotation="1 0 0 1.5708">
      <TouchSensor DEF="HubTouch" description="Click: pause or resume" />
      <Shape><Appearance><PhysicalMaterial baseColor="1 0.9 0.5" emissiveColor="0.8 0.6 0.2" metallic="1" /></Appearance><Cylinder radius="0.55" height="0.4" /></Shape>
    </Transform>
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
