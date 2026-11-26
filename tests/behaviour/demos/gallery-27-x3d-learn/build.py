# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-27-x3d-learn.x3d: THE X3D EVENT MACHINE, a teaching world. Eight stations on a snaking path, one node
type each, every one labelled in 3D text with the node and the field that carries its event. Click the green
TouchSensor button and ONE event relays station to station: each hop is a real chain of ROUTEs
(TimeSensor.isActive -> BooleanFilter.set_boolean, inputNegate -> TimeTrigger.set_boolean, triggerTime -> the next
TimeSensor.startTime), and a glowing bead rides each wire while that hop is live. Each station then plays its own node
(BooleanFilter doors, TimeSensor fill bar, Position + Color interpolators, OrientationInterpolator, BooleanSequencer
bulbs, PositionChaser ball, ColorChaser plate).   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-27-x3d-learn.x3d")
STAGE, WIRE, FINALE = 3.0, 2.5, 3.5          # seconds: a station plays, a wire carries the event, the finale
CAM = (0.0, 19.1, 13.7)
PITCH = math.atan2(CAM[1], CAM[2])
body = []                                     # routes and logic nodes (after the visible scene)
scene = []                                    # visible geometry


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, em=None, mdef=None, extra=""):
    d = f' DEF="{mdef}"' if mdef else ""
    e = f' emissiveColor="{em}"' if em else ""
    return f'<Appearance><PhysicalMaterial{d} baseColor="{base}"{e} {extra} /></Appearance>'


def shape(geom, base, em=None, mdef=None, extra=""):
    return f"<Shape>{paint(base, em, mdef, extra)}{geom}</Shape>"


def tr(name, pos, inner, extra=""):
    d = f' DEF="{name}"' if name else ""
    return f'<Transform{d} translation="{f(*pos)}"{extra}>{inner}</Transform>'


def text(lines, base, pos, size_scale=1.0, middle=True):
    """Floating label: lines is [(string, size)], tilted to face the camera; each line its own Text."""
    out, y = "", 0.0
    for s, size in lines:
        size *= size_scale
        just = '&quot;MIDDLE&quot;' if middle else '&quot;BEGIN&quot;'
        out += tr(None, (0, y, 0), shape(f'<Text string="&quot;{s}&quot;"><FontStyle size="{size}" justify="{just}" /></Text>', base, base))
        y -= size * 1.4
    return tr(None, pos, out, f' rotation="1 0 0 {-PITCH:.4f}"')


def interp(kind, name, keys, vals, src, dst, dstf):
    body.append(f'    <{kind} DEF="{name}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route(src, "fraction_changed", name, "set_fraction")
    if dst:
        route(name, "value_changed", dst, dstf)


def v3(*a):
    return f(*a)


# -- the path of stations: (x, z) --------------------------------------------------------------------------
POS = {1: (-9, -4), 2: (-3, -4), 3: (3, -4), 4: (9, -4), 5: (9, 4), 6: (3, 4), 7: (-3, 4), 8: (-9, 4)}
COL = {1: "0.15 0.85 0.3", 2: "0.95 0.75 0.15", 3: "0.2 0.7 0.95", 4: "0.85 0.3 0.85", 5: "1 0.5 0.15", 6: "0.95 0.95 0.3", 7: "0.3 0.9 0.8", 8: "0.95 0.3 0.4"}
LABEL = {
    1: ([("TouchSensor", 0.5), ("isActive  false > true", 0.3), ("click the green button", 0.26)]),
    2: ([("BooleanFilter", 0.5), ("inputTrue / inputNegate", 0.3), ("lets one edge through", 0.26)]),
    3: ([("TimeSensor", 0.5), ("fraction_changed 0 .. 1", 0.3), ("cycleInterval 3 s", 0.26)]),
    4: ([("Position + Color", 0.46), ("Interpolator", 0.46), ("value_changed", 0.3), ("keys become values", 0.26)]),
    5: ([("Orientation", 0.46), ("Interpolator", 0.46), ("value_changed > rotation", 0.28), ("two full turns", 0.26)]),
    6: ([("BooleanSequencer", 0.46), ("value_changed > visible", 0.28), ("a lit bulb walks the arc", 0.26)]),
    7: ([("PositionChaser", 0.46), ("set_destination", 0.3), ("glides after the target", 0.26)]),
    8: ([("ColorChaser", 0.46), ("set_destination > colour", 0.28), ("finale: the route is done", 0.26)]),
}
DIM = "0.18 0.2 0.26"

# -- the relay: Touch -> F0 -> G1 -> T1; Tk -> Fk -> Hk -> Wk -> Gk -> T(k+1) -----------------------------------
body.append('    <BooleanFilter DEF="PressFilter" />')
body.append('    <TimeTrigger DEF="Go1" />')
route("StartTouch", "isActive", "PressFilter", "set_boolean")
route("PressFilter", "inputTrue", "Go1", "set_boolean")
for k in range(1, 9):
    body.append(f'    <TimeSensor DEF="T{k}" cycleInterval="{FINALE if k == 8 else STAGE}" />')
route("Go1", "triggerTime", "T1", "startTime")
for k in range(1, 8):
    body.append(f'    <TimeSensor DEF="W{k}" cycleInterval="{WIRE}" />')
    for tag in ("a", "b"):
        body.append(f'    <BooleanFilter DEF="Edge{k}{tag}" />')
        body.append(f'    <TimeTrigger DEF="Fire{k}{tag}" />')
    route(f"T{k}", "isActive", f"Edge{k}a", "set_boolean")
    route(f"Edge{k}a", "inputNegate", f"Fire{k}a", "set_boolean")
    route(f"Fire{k}a", "triggerTime", f"W{k}", "startTime")
    route(f"W{k}", "isActive", f"Edge{k}b", "set_boolean")
    route(f"Edge{k}b", "inputNegate", f"Fire{k}b", "set_boolean")
    route(f"Fire{k}b", "triggerTime", f"T{k + 1}", "startTime")

# -- ground, title, light, camera ----------------------------------------------------------------------------
scene.append(tr(None, (0, -0.15, 0), shape('<Box size="36 0.3 30" />', "0.07 0.08 0.11", None, None, 'roughness="0.9"')))
scene.append(text([("THE X3D EVENT MACHINE", 0.95), ("click the green button: one event runs ROUTE by ROUTE through eight nodes", 0.38),
                   ("each stage lasts 3 s, slowed so you can follow", 0.3)], "0.95 0.95 1", (0, 0.8, -9.5), 1.0))

# -- stations ---------------------------------------------------------------------------------------------
for k in range(1, 9):
    x, z = POS[k]
    c = COL[k]
    parts = shape('<Box size="3 0.3 3" />', "0.16 0.17 0.22", None, None, 'roughness="0.8"')
    parts_g = tr(f"Lamp{k}", (0, 0.12, 0), shape('<Box size="3.3 0.2 3.3" />', c, c), ' visible="false"')
    s = tr(f"Station{k}", (x, 0.15, z), parts) + tr(f"Glow{k}", (x, 0.15, z), parts_g)
    scene.append(s)
    scene.append(text([(a, b) for a, b in LABEL[k]], c, (x, 2.0, z + 2.0)))
    scene.append(text([(str(k), 0.9)], c, (x - 1.0, 1.3, z - 1.9)))

# S1 TouchSensor: the green button (first sensed mesh in the file) with an expanding ring and a flash
x, z = POS[1]
btn = (f'<TouchSensor DEF="StartTouch" description="Click: start the event" />'
       + shape('<Cylinder radius="1.15" height="0.7" />', "0.1 0.75 0.2", "0.05 0.5 0.1", "BtnMat"))
scene.insert(0, tr("Start", (x, 0.65, z), btn))
scene.append(tr("Ring1", (x, 0.35, z), shape('<Cylinder radius="1.3" height="0.06" />', "0.4 1 0.5", "0.3 0.9 0.4"), ' visible="false"'))
scene.append(tr("Halo1", (x, 0.34, z), shape('<Cylinder radius="1.4" height="0.05" />', "0.2 0.5 0.25", "0.1 0.4 0.15")))
body.append('    <TimeSensor DEF="Idle" cycleInterval="2" loop="true" />')
interp("PositionInterpolator", "HaloPulse", [0, 0.5, 1], ["1 1 1", "1.18 1 1.18", "1 1 1"], "Idle", "Halo1", "scale")
route("T1", "isActive", "Ring1", "visible")
interp("PositionInterpolator", "RingGrow", [0, 1], ["1 1 1", "2.3 1 2.3"], "T1", "Ring1", "scale")
interp("ColorInterpolator", "BtnFlash", [0, 0.2, 1], ["0.1 0.75 0.2", "1 1 1", "0.1 0.75 0.2"], "T1", "BtnMat", "baseColor")
route("BtnFlash", "value_changed", "BtnMat", "emissiveColor")

# S2 BooleanFilter: two doors slide apart, an orb glows behind them
x, z = POS[2]
for nm, sx in (("DoorL", -0.7), ("DoorR", 0.7)):
    scene.append(tr(f"{nm}2", (x + sx, 1.2, z + 0.5), shape('<Box size="1.3 1.8 0.3" />', "0.7 0.55 0.1", "0.3 0.2 0.0")))
    interp("PositionInterpolator", f"{nm}Slide", [0, 0.25, 0.75, 1], [v3(x + sx, 1.2, z + 0.5), v3(x + sx * 2.4, 1.2, z + 0.5), v3(x + sx * 2.4, 1.2, z + 0.5), v3(x + sx, 1.2, z + 0.5)], "T2", f"{nm}2", "translation")
scene.append(tr("Orb2", (x, 1.2, z - 0.3), shape('<Sphere radius="0.55" />', "1 0.9 0.3", "1 0.8 0.2"), ' visible="false"'))
route("T2", "isActive", "Orb2", "visible")

# S3 TimeSensor: a fill bar grows with fraction_changed, three tick lamps follow it
x, z = POS[3]
scene.append(tr(None, (x, 0.65, z), shape('<Box size="2.8 0.35 0.6" />', "0.12 0.14 0.2")))
scene.append(tr("Fill3", (x - 1.4, 0.65, z + 0.05), tr(None, (1.4, 0, 0), shape('<Box size="2.8 0.3 0.5" />', "0.2 0.7 0.95", "0.1 0.5 0.8")), ' scale="0.01 1 1"'))
interp("PositionInterpolator", "FillGrow", [0, 1], ["0.01 1 1", "1 1 1"], "T3", "Fill3", "scale")
for i in range(3):
    t = (i + 1) / 4
    scene.append(tr(None, (x - 0.8 + i * 0.8, 1.4, z), shape('<Sphere radius="0.18" />', DIM)))
    scene.append(tr(f"Tick3_{i}", (x - 0.8 + i * 0.8, 1.4, z), shape('<Sphere radius="0.26" />', "0.4 0.9 1", "0.3 0.8 1"), ' visible="false"'))
    interp("BooleanSequencer", f"TickSeq3_{i}", [0, t, 1], ["false", "true", "true"], "T3", f"Tick3_{i}", "visible")

# S4 Position + Color Interpolator: a cube bounces and changes colour
x, z = POS[4]
scene.append(tr("Cube4", (x, 1.0, z), shape('<Box size="1.3 1.3 1.3" />', "0.2 0.3 0.9", "0.1 0.15 0.6", "Mat4")))
interp("PositionInterpolator", "CubeBounce", [0, 0.5, 1], [v3(x, 1.0, z), v3(x, 2.8, z), v3(x, 1.0, z)], "T4", "Cube4", "translation")
interp("ColorInterpolator", "CubeColour", [0, 0.33, 0.66, 1], ["0.2 0.3 0.9", "0.9 0.2 0.8", "1 0.85 0.2", "0.2 0.3 0.9"], "T4", "Mat4", "baseColor")
route("CubeColour", "value_changed", "Mat4", "emissiveColor")

# S5 OrientationInterpolator: a turntable spinner makes two full turns
x, z = POS[5]
scene.append(tr(None, (x, 0.5, z), shape('<Cylinder radius="1.35" height="0.25" />', "0.25 0.22 0.2")))
scene.append(tr("Spin5", (x, 1.0, z), shape('<Box size="2.4 0.3 0.5" />', "1 0.5 0.15", "0.6 0.25 0.05")
                + tr(None, (1.35, 0, 0), shape('<Cone bottomRadius="0.4" height="0.7" />', "0.95 0.95 0.9"), ' rotation="0 0 1 -1.5708"')))
interp("OrientationInterpolator", "SpinKeys", [0, 0.25, 0.5, 0.75, 1], ["0 1 0 0", "0 1 0 3.1416", "0 1 0 6.2832", "0 1 0 9.4248", "0 1 0 12.5664"], "T5", "Spin5", "rotation")

# S6 BooleanSequencer: six bulbs on an arc, a lit one walks along it
x, z = POS[6]
for i in range(6):
    bx, by = x - 1.25 + i * 0.5, 0.9 + 0.5 * math.sin(math.pi * i / 5)
    scene.append(tr(None, (bx, by, z), shape('<Sphere radius="0.22" />', DIM)))
    scene.append(tr(f"Bulb6_{i}", (bx, by, z), shape('<Sphere radius="0.3" />', "1 1 0.4", "1 0.95 0.2"), ' visible="false"'))
    ts, te = i / 6, (i + 1) / 6
    if i == 0:
        keys, vals = [0, te, 1], ["true", "false", "false"]
    elif i == 5:
        keys, vals = [0, ts, 0.999], ["false", "true", "false"]
    else:
        keys, vals = [0, ts, te, 1], ["false", "true", "false", "false"]
    interp("BooleanSequencer", f"BulbSeq6_{i}", keys, vals, "T6", f"Bulb6_{i}", "visible")

# S7 PositionChaser: the flag jumps to new targets, the ball glides after it
x, z = POS[7]
scene.append(tr(None, (x, 0.45, z), shape('<Box size="3.4 0.12 0.6" />', "0.2 0.25 0.3")))
scene.append(tr("Ball7", (x - 1.2, 0.95, z), shape('<Sphere radius="0.5" />', "0.3 0.9 0.8", "0.15 0.6 0.55")))
scene.append(tr("Flag7", (x - 1.2, 2.2, z), shape('<Cone bottomRadius="0.35" height="0.7" />', "1 0.35 0.3", "0.8 0.15 0.1"), ' rotation="1 0 0 3.1416"'))
xs = [-1.2, -1.2, 1.2, 1.2, -0.2, -0.2, 1.2, 1.2]
ks = [0, 0.2, 0.21, 0.45, 0.46, 0.7, 0.71, 1]
body.append(f'    <PositionInterpolator DEF="TargetKeys" key="{f(*ks)}" keyValue="{" ".join(v3(x + a, 0.95, z) for a in xs)}" />')
body.append(f'    <PositionInterpolator DEF="FlagKeys" key="{f(*ks)}" keyValue="{" ".join(v3(x + a, 2.2, z) for a in xs)}" />')
body.append(f'    <PositionChaser DEF="Chase7" duration="0.8" initialDestination="{v3(x - 1.2, 0.95, z)}" initialValue="{v3(x - 1.2, 0.95, z)}" />')
route("T7", "fraction_changed", "TargetKeys", "set_fraction")
route("T7", "fraction_changed", "FlagKeys", "set_fraction")
route("TargetKeys", "value_changed", "Chase7", "set_destination")
route("Chase7", "value_changed", "Ball7", "translation")
route("FlagKeys", "value_changed", "Flag7", "translation")

# S8 finale: ColorInterpolator -> ColorChaser lights a plate; eight sparks burst out
x, z = POS[8]
scene.append(tr(None, (x, 0.95, z), shape('<Box size="3 0.7 1.8" />', "0.15 0.15 0.18", "0.0 0.0 0.0", "Mat8")))
body.append('    <ColorInterpolator DEF="PlateKeys" key="0 0.25 0.5 0.75 1" keyValue="0.95 0.8 0.2 0.95 0.2 0.8 0.2 0.9 0.95 0.5 0.95 0.2 0.95 0.8 0.2" />')
body.append('    <ColorChaser DEF="PlateChase" duration="0.5" initialDestination="0.15 0.15 0.18" initialValue="0.15 0.15 0.18" />')
route("T8", "fraction_changed", "PlateKeys", "set_fraction")
route("PlateKeys", "value_changed", "PlateChase", "set_destination")
route("PlateChase", "value_changed", "Mat8", "baseColor")
route("PlateChase", "value_changed", "Mat8", "emissiveColor")
body.append('    <PositionInterpolator DEF="SparkShrink" key="0 1" keyValue="1 1 1 0.2 0.2 0.2" />')
route("T8", "fraction_changed", "SparkShrink", "set_fraction")
for i in range(8):
    a = i / 8 * 2 * math.pi
    d = (math.cos(a) * 3.2, 0.0, math.sin(a) * 2.4)
    scene.append(tr(f"Spark8_{i}", (x, 2.0, z), shape('<Sphere radius="0.28" />', COL[(i % 8) + 1], COL[(i % 8) + 1]), ' visible="false"'))
    interp("PositionInterpolator", f"SparkFly{i}", [0, 1], [v3(x, 1.8, z), v3(x + d[0], 3.4, z + d[2])], "T8", f"Spark8_{i}", "translation")
    route("T8", "isActive", f"Spark8_{i}", "visible")
    route("SparkShrink", "value_changed", f"Spark8_{i}", "scale")

# -- stage lamps (plinth glow) and the wires with their beads ---------------------------------------------------
for k in range(1, 9):
    route(f"T{k}", "isActive", f"Lamp{k}", "visible")
for k in range(1, 8):
    (xa, za), (xb, zb) = POS[k], POS[k + 1]
    dx, dz = xb - xa, zb - za
    n = math.hypot(dx, dz)
    ux, uz = dx / n, dz / n
    p0 = (xa + ux * 1.7, 0.7, za + uz * 1.7)
    p1 = (xb - ux * 1.7, 0.7, zb - uz * 1.7)
    length = math.hypot(p1[0] - p0[0], p1[2] - p0[2])
    mid = ((p0[0] + p1[0]) / 2, 0.7, (p0[2] + p1[2]) / 2)
    size = (length, 0.12, 0.12) if abs(dx) > 0 else (0.12, 0.12, length)
    scene.append(tr(None, mid, shape(f'<Box size="{f(*size)}" />', "0.3 0.32 0.4")))
    gsize = (length, 0.2, 0.2) if abs(dx) > 0 else (0.2, 0.2, length)
    scene.append(tr(f"WireGlow{k}", mid, shape(f'<Box size="{f(*gsize)}" />', "1 0.95 0.5", "1 0.85 0.3"), ' visible="false"'))
    scene.append(tr(f"Bead{k}", p0, shape('<Sphere radius="0.4" />', "1 1 0.7", "1 0.9 0.4"), ' visible="false"'))
    route(f"W{k}", "isActive", f"WireGlow{k}", "visible")
    route(f"W{k}", "isActive", f"Bead{k}", "visible")
    interp("PositionInterpolator", f"BeadRide{k}", [0, 1], [v3(*p0), v3(*p1)], f"W{k}", f"Bead{k}", "translation")
    scene.append(text([("ROUTE chain", 0.26), ("isActive true>false", 0.22), ("inputNegate", 0.22), ("triggerTime > startTime", 0.22)], "1 0.95 0.6", (mid[0], 2.0, mid[2] + (0.9 if abs(dx) > 0 else 0.0)), 1.0))

HOME_O = (1, 0, 0, round(-PITCH, 4))
SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <component name="Text" level="1" />
    <meta name="title" content="Gallery 27: the X3D event machine" />
    <meta name="description" content="Click the green button: one event relays through eight stations, one X3D node type each, over visible ROUTEs." />
    <meta name="generator" content="tests/behaviour/demos/gallery-27-x3d-learn/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.03 0.04 0.08" />
    <Viewpoint DEF="Cam" description="Overview" position="{f(*CAM)}" orientation="{f(*HOME_O)}" />
    <DirectionalLight direction="-0.3 -0.9 -0.4" intensity="1.0" />
{chr(10).join("    " + s for s in scene)}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
