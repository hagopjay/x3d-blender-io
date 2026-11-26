# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-06-solar-gauntlet.x3d: the camera flies a 24 s weave through ten gates toward a flaring sun; a
ProximitySensor at each gate lights it (isActive -> glow.visible) and pops its frame (enterTime -> a 0.6 s clock ->
scale). The camera is the Viewpoint, driven by two interpolators.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-06-solar-gauntlet.x3d")
G, TOUR = 10, 24.0
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def path(s):
    return (4.0 * math.sin(0.9 * s), 2.5 * math.cos(0.7 * s), -8.0 * s)


def look(eye, target):
    fw = [t - e for t, e in zip(target, eye)]
    n = math.sqrt(sum(c * c for c in fw)); fw = [c / n for c in fw]
    r = [-fw[2], 0.0, fw[0]]
    n = math.hypot(r[0], r[2]); r = [r[0] / n, 0.0, r[2] / n]
    u = [r[1] * fw[2] - r[2] * fw[1], r[2] * fw[0] - r[0] * fw[2], r[0] * fw[1] - r[1] * fw[0]]
    m = [[r[0], u[0], -fw[0]], [r[1], u[1], -fw[1]], [r[2], u[2], -fw[2]]]
    angle = math.acos(max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2)))
    ax = [m[2][1] - m[1][2], m[0][2] - m[2][0], m[1][0] - m[0][1]]
    n = math.sqrt(sum(c * c for c in ax)) or 1.0
    return [c / n for c in ax], angle


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


for i in range(G):
    s = i + 0.5
    x, y, z = path(s)
    ax, ang = look((x, y, z), path(s + 0.2))
    hue = [(1, 0.35, 0.1), (1, 0.7, 0.1), (0.4, 1, 0.3), (0.2, 0.8, 1), (0.7, 0.4, 1)][i % 5]
    c = f(*hue)
    steel = paint("0.55 0.55 0.6", None, 'metallic="1" roughness="0.3"')
    frame = "".join(
        f'<Transform translation="{tx} {ty} 0"><Shape>{steel}<Box size="{sx} {sy} 0.3" /></Shape></Transform>'
        for tx, ty, sx, sy in [(0, 1.85, 4.0, 0.3), (0, -1.85, 4.0, 0.3), (1.85, 0, 0.3, 4.0), (-1.85, 0, 0.3, 4.0)])
    body.append(f'''    <Transform DEF="Gate{i}" translation="{f(x, y, z)}" rotation="{f(*ax, ang)}">
      <Transform DEF="Frame{i}">{frame}</Transform>
      <Transform DEF="Glow{i}" visible="false"><Shape>{paint(c, c, 'transparency="0.55"')}<Box size="3.4 3.4 0.06" /></Shape></Transform>
    </Transform>
    <ProximitySensor DEF="Near{i}" center="{f(x, y, z)}" size="4.4 4.4 4.4" />
    <TimeSensor DEF="Pop{i}" cycleInterval="0.6" />
    <PositionInterpolator DEF="Swell{i}" key="0 0.4 1" keyValue="1 1 1 1.35 1.35 1.35 1 1 1" />''')
    route(f"Near{i}", "isActive", f"Glow{i}", "visible")
    route(f"Near{i}", "enterTime", f"Pop{i}", "startTime")
    route(f"Pop{i}", "fraction_changed", f"Swell{i}", "set_fraction")
    route(f"Swell{i}", "value_changed", f"Frame{i}", "scale")

# the camera's weave: 60 keys, looking a little way down the path
keys, pos, ori = [], [], []
n = 60
for k in range(n + 1):
    s = -0.4 + (G + 0.4) * k / n
    eye = path(s)
    ax, ang = look((eye[0], eye[1] + 0.3, eye[2]), path(s + 0.5))
    keys.append(f"{k / n:.5f}"); pos.append(f(eye[0], eye[1] + 0.3, eye[2])); ori.append(f(*ax, ang))

# the sun with its prominences
sun_z = path(G + 3)[2]
sun = f'''    <Transform translation="0 0 {sun_z:.1f}">
      <Shape>{paint("1 0.6 0.1", "1 0.5 0.05")}<Sphere radius="14" /></Shape>
    </Transform>'''
prom = []
for j in range(6):
    prom.append(f'''    <Transform DEF="Prom{j}" translation="0 0 {sun_z:.1f}">
      <Transform translation="{16 + j % 2 * 2} 0 0" rotation="0 0 1 {0.5 * j:.2f}"><Shape>{paint("1 0.8 0.3", "1 0.6 0.1")}<Cone bottomRadius="1.4" height="{6 + j % 3 * 2}" /></Shape></Transform>
    </Transform>
    <TimeSensor DEF="Flare{j}" cycleInterval="{7 + j * 1.3:.1f}" loop="true" />
    <OrientationInterpolator DEF="Arc{j}" key="0 0.5 1" keyValue="0 0 1 {j * 1.05:.3f} 0 0 1 {j * 1.05 + 3.1416:.3f} 0 0 1 {j * 1.05 + 6.2832:.3f}" />''')
    route(f"Flare{j}", "fraction_changed", f"Arc{j}", "set_fraction")
    route(f"Arc{j}", "value_changed", f"Prom{j}", "rotation")
body.append(sun)
body.extend(prom)

start_pos, start_ori = pos[0], ori[0]
SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 06: solar gauntlet" />
    <meta name="description" content="A camera flight through ten gates toward a flaring sun; ProximitySensors light each gate as you pass." />
    <meta name="generator" content="tests/behaviour/demos/gallery-06-solar-gauntlet/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.01 0.0 0.03" />
    <Viewpoint DEF="Pilot" description="Flight" position="{start_pos}" orientation="{start_ori}" />
    <DirectionalLight direction="0 -0.2 1" intensity="0.8" color="1 0.8 0.6" />
    <PointLight location="0 0 {sun_z + 20:.1f}" color="1 0.6 0.2" intensity="4000" radius="400" />
    <TimeSensor DEF="Flight" cycleInterval="{TOUR}" loop="true" />
    <PositionInterpolator DEF="FlightPos" key="{" ".join(keys)}" keyValue="{" ".join(pos)}" />
    <OrientationInterpolator DEF="FlightLook" key="{" ".join(keys)}" keyValue="{" ".join(ori)}" />
    <ROUTE fromNode="Flight" fromField="fraction_changed" toNode="FlightPos" toField="set_fraction" />
    <ROUTE fromNode="Flight" fromField="fraction_changed" toNode="FlightLook" toField="set_fraction" />
    <ROUTE fromNode="FlightPos" fromField="value_changed" toNode="Pilot" toField="position" />
    <ROUTE fromNode="FlightLook" fromField="value_changed" toNode="Pilot" toField="orientation" />
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
