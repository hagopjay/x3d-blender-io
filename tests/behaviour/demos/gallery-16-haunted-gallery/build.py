# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-16-haunted-gallery.x3d: the camera drifts down a corridor of 16 portraits, yawing left and right. A
ProximitySensor per pair of portraits wakes them while the camera is near: calm canvas out, haunted canvas in, frames
rattle, a ghost rises, sconces flare.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-16-haunted-gallery.x3d")
PAIRS, STEP, TOUR = 8, 8.0, 40.0
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


def solid(c, geom, extra=""):
    return f"<Shape>{paint(c, c, extra)}{geom}</Shape>"      # solid view shows baseColor, renderers show emissive: both


def at(t, inner, rot=""):
    r = f' rotation="{rot}"' if rot else ""
    return f'<Transform translation="{t}"{r}>{inner}</Transform>'


def look(eye, fw):
    n = math.sqrt(sum(c * c for c in fw)); fw = [c / n for c in fw]
    r = [-fw[2], 0.0, fw[0]]
    n = math.hypot(r[0], r[2]); r = [r[0] / n, 0.0, r[2] / n]
    u = [r[1] * fw[2] - r[2] * fw[1], r[2] * fw[0] - r[0] * fw[2], r[0] * fw[1] - r[1] * fw[0]]
    m = [[r[0], u[0], -fw[0]], [r[1], u[1], -fw[1]], [r[2], u[2], -fw[2]]]
    angle = math.acos(max(-1.0, min(1.0, (m[0][0] + m[1][1] + m[2][2] - 1) / 2)))
    ax = [m[2][1] - m[1][2], m[0][2] - m[2][0], m[1][0] - m[0][1]]
    n = math.sqrt(sum(c * c for c in ax)) or 1.0
    return [c / n for c in ax], angle


# --- the hall -------------------------------------------------------------------------------------------------------
Z0, Z1 = 6.0, -(PAIRS * STEP) - 4.0
mid, length = (Z0 + Z1) / 2, Z0 - Z1
hall = [
    at(f(0, -0.25, mid), solid("0.25 0.18 0.14", f'<Box size="9 0.5 {length:.1f}" />')),
    at(f(0, 4.25, mid), solid("0.12 0.1 0.12", f'<Box size="9 0.5 {length:.1f}" />')),
    at(f(-4.75, 2, mid), solid("0.2 0.17 0.22", f'<Box size="0.5 4 {length:.1f}" />')),
    at(f(4.75, 2, mid), solid("0.2 0.17 0.22", f'<Box size="0.5 4 {length:.1f}" />')),
    at(f(0, 2, Z1 - 0.25), solid("0.05 0.03 0.08", '<Box size="9 4 0.5" />')),
]
for k in range(PAIRS * 2 + 1):                       # a runner of floor tiles and ceiling beams for depth cues
    z = Z0 - 1 - k * STEP / 2
    hall.append(at(f(0, 0.02, z), solid("0.5 0.1 0.12" if k % 2 else "0.12 0.1 0.3", '<Box size="2.2 0.04 3.6" />')))
    hall.append(at(f(0, 3.85, z), solid("0.3 0.22 0.15", '<Box size="9 0.3 0.4" />')))
body.extend("    " + h for h in hall)

# --- one pair of portraits per ProximitySensor ------------------------------------------------------------------------
PALE = [(0.8, 0.75, 0.6), (0.6, 0.75, 0.85), (0.75, 0.85, 0.65), (0.85, 0.65, 0.7)]


def portrait(i, side):
    """One painting facing into the hall, built in its own frame (+z toward the room)."""
    s = -1 if side == "L" else 1
    x, z = 4.4 * s, -(i + 0.5) * STEP + 3.0
    tag = f"{i}{side}"
    pale = f(*PALE[(i + (side == "R")) % 4])
    face = f(0.85, 0.75, 0.6)
    frame = "".join(at(f(tx, ty, 0), solid("0.7 0.5 0.15", f'<Box size="{sx} {sy} 0.2" />', 'metallic="1" roughness="0.4"'))
                    for tx, ty, sx, sy in [(0, 1.15, 2.6, 0.25), (0, -1.15, 2.6, 0.25), (1.2, 0, 0.25, 2.5), (-1.2, 0, 0.25, 2.5)])
    calm = (at("0 0 0", solid(pale, '<Box size="2.2 2.1 0.06" />'))
            + at("0 -0.5 0.05", solid("0.3 0.25 0.35", '<Sphere radius="0.8" />'))
            + at("0 0.3 0.1", solid(face, '<Sphere radius="0.45" />'))
            + at("-0.16 0.38 0.5", solid("0.1 0.1 0.1", '<Sphere radius="0.06" />'))
            + at("0.16 0.38 0.5", solid("0.1 0.1 0.1", '<Sphere radius="0.06" />')))
    wake = (at("0 0 0.02", solid("0.45 0.02 0.04", '<Box size="2.2 2.1 0.06" />'))
            + at("0 -0.5 0.06", solid("0.05 0.02 0.08", '<Sphere radius="0.8" />'))
            + at("0 0.3 0.1", solid("0.75 0.8 0.65", '<Sphere radius="0.52" />'))
            + at("-0.2 0.4 0.55", solid("1 0.9 0.1", '<Sphere radius="0.13" />'))
            + at("0.2 0.4 0.55", solid("1 0.9 0.1", '<Sphere radius="0.13" />'))
            + at("0 0.05 0.58", solid("0.02 0 0", '<Box size="0.3 0.28 0.05" />'))
            + at("-0.7 0.8 0.1", solid("0.9 0.2 0.1", '<Cone bottomRadius="0.1" height="0.5" />'), "0 0 1 0.6")
            + at("0.7 0.8 0.1", solid("0.9 0.2 0.1", '<Cone bottomRadius="0.1" height="0.5" />'), "0 0 1 -0.6"))
    rot = f(0, 1, 0, math.pi / 2 if side == "L" else -math.pi / 2)
    body.append(f'''    <Transform translation="{f(x, 1.9, z)}" rotation="{rot}">
      <Transform DEF="Frame{tag}">{frame}</Transform>
      <Transform DEF="Calm{tag}">{calm}</Transform>
      <Transform DEF="Wake{tag}" visible="false">{wake}</Transform>
    </Transform>''')
    return tag, x, z


for i in range(PAIRS):
    zc = -(i + 0.5) * STEP + 3.0
    tags = [portrait(i, "L"), portrait(i, "R")]
    # sconces either side of the pair, flames lit while awake
    for sx in (-4.1, 4.1):
        body.append(f'''    <Transform translation="{f(sx, 2.7, zc + 2.2)}">
      {solid("0.35 0.3 0.3", '<Cylinder radius="0.12" height="0.25" />')}
      <Transform DEF="Flame{i}{"L" if sx < 0 else "R"}" translation="0 0.3 0" visible="false">{solid("1 0.55 0.1", '<Cone bottomRadius="0.14" height="0.45" />')}</Transform>
    </Transform>''')
    # the ghost that rises between the paintings
    gx = -2.4 if i % 2 == 0 else 2.4
    body.append(f'''    <Transform DEF="Ghost{i}" translation="{f(gx, 0.6, zc)}" visible="false">
      {solid("0.85 0.95 1", '<Sphere radius="0.35" />', 'transparency="0.35"')}
      {at("0 -0.45 0", solid("0.8 0.9 1", '<Cone bottomRadius="0.4" height="0.7" />', 'transparency="0.35"'), "1 0 0 3.1416")}
      {at("-0.12 0.05 0.3", solid("0.05 0.05 0.1", '<Sphere radius="0.07" />'))}
      {at("0.12 0.05 0.3", solid("0.05 0.05 0.1", '<Sphere radius="0.07" />'))}
    </Transform>''')
    body.append(f'''    <ProximitySensor DEF="Near{i}" center="{f(0, 1.9, zc)}" size="9 4 6" />
    <BooleanFilter DEF="Asleep{i}" />
    <TimeSensor DEF="Rattle{i}" cycleInterval="1.2" />
    <OrientationInterpolator DEF="Shake{i}" key="0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1" keyValue="0 0 1 0 0 0 1 0.2 0 0 1 -0.18 0 0 1 0.16 0 0 1 -0.14 0 0 1 0.12 0 0 1 -0.09 0 0 1 0.07 0 0 1 -0.04 0 0 1 0.02 0 0 1 0" />
    <TimeSensor DEF="Rise{i}" cycleInterval="3" />
    <PositionInterpolator DEF="Float{i}" key="0 0.5 1" keyValue="{f(gx, 0.6, zc)} {f(gx * 0.6, 1.9, zc - 1.0)} {f(gx, 2.9, zc)}" />''')
    route(f"Near{i}", "isActive", f"Asleep{i}", "set_boolean")
    for tag, _, _ in tags:
        route(f"Near{i}", "isActive", f"Wake{tag}", "visible")
        route(f"Asleep{i}", "inputNegate", f"Calm{tag}", "visible")
        route(f"Shake{i}", "value_changed", f"Frame{tag}", "rotation")
    route(f"Near{i}", "isActive", f"Ghost{i}", "visible")
    route(f"Near{i}", "isActive", f"Flame{i}L", "visible")
    route(f"Near{i}", "isActive", f"Flame{i}R", "visible")
    route(f"Near{i}", "enterTime", f"Rattle{i}", "startTime")
    route(f"Rattle{i}", "fraction_changed", f"Shake{i}", "set_fraction")
    route(f"Near{i}", "enterTime", f"Rise{i}", "startTime")
    route(f"Rise{i}", "fraction_changed", f"Float{i}", "set_fraction")
    route(f"Float{i}", "value_changed", f"Ghost{i}", "translation")

# --- swaying chandeliers (always running) -----------------------------------------------------------------------------
for j in range(4):
    z = -(j * 2 + 1) * STEP / 1.0 + 2.0
    body.append(f'''    <Transform DEF="Lamp{j}" translation="{f(0, 3.7, z)}">
      {at("0 -0.7 0", solid("0.8 0.7 0.3", '<Cylinder radius="0.03" height="1.4" />'))}
      {at("0 -1.4 0", solid("1 0.85 0.5", '<Sphere radius="0.25" />'))}
    </Transform>
    <TimeSensor DEF="Sway{j}" cycleInterval="{4 + j * 0.7:.1f}" loop="true" />
    <OrientationInterpolator DEF="Swing{j}" key="0 0.25 0.5 0.75 1" keyValue="0 0 1 0 0 0 1 0.2 0 0 1 0 0 0 1 -0.2 0 0 1 0" />''')
    route(f"Sway{j}", "fraction_changed", f"Swing{j}", "set_fraction")
    route(f"Swing{j}", "value_changed", f"Lamp{j}", "rotation")

# --- the camera: a drift down the middle, yawing from wall to wall ---------------------------------------------------------
keys, pos, ori = [], [], []
n = 100
for k in range(n + 1):
    u = k / n
    z = 2.0 + (Z1 + 3.0 - 2.0) * u
    yaw = 0.75 * math.sin(2 * math.pi * 5 * u)
    eye = (0.3 * math.sin(2 * math.pi * 3 * u), 1.7 + 0.08 * math.sin(2 * math.pi * 20 * u), z)
    fw = (-math.sin(yaw) * math.cos(0.05), -0.05, -math.cos(yaw) * math.cos(0.05))
    ax, ang = look(eye, fw)
    keys.append(f"{u:.5f}"); pos.append(f(*eye)); ori.append(f(*ax, ang))

start_pos, start_ori = pos[0], ori[0]
SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 16: haunted gallery" />
    <meta name="description" content="A camera drifts down a hall of portraits; ProximitySensors wake each pair as it passes." />
    <meta name="generator" content="tests/behaviour/demos/gallery-16-haunted-gallery/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.01 0.04" />
    <Viewpoint DEF="Visitor" description="Visitor" position="{start_pos}" orientation="{start_ori}" />
    <PointLight location="0 3 {mid:.1f}" color="0.6 0.6 1" intensity="900" radius="80" />
    <TimeSensor DEF="Drift" cycleInterval="{TOUR}" loop="true" />
    <PositionInterpolator DEF="DriftPos" key="{" ".join(keys)}" keyValue="{" ".join(pos)}" />
    <OrientationInterpolator DEF="DriftLook" key="{" ".join(keys)}" keyValue="{" ".join(ori)}" />
    <ROUTE fromNode="Drift" fromField="fraction_changed" toNode="DriftPos" toField="set_fraction" />
    <ROUTE fromNode="Drift" fromField="fraction_changed" toNode="DriftLook" toField="set_fraction" />
    <ROUTE fromNode="DriftPos" fromField="value_changed" toNode="Visitor" toField="position" />
    <ROUTE fromNode="DriftLook" fromField="value_changed" toNode="Visitor" toField="orientation" />
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
