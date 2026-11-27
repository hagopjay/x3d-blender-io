# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-25-weather-machine.x3d: a small island (house, five trees, a lighthouse) under a sky you control with
four buttons: RAIN, SNOW, STORM, SUN. Exactly one weather runs at a time. Each button's press fans out through
BooleanFilters: `inputTrue` turns its own weather on, a negated copy turns the other three off (ROUTEs to each weather
group's TimeSensor `enabled`, to the group's `visible`, to a pilot lamp). A one-shot clock per button selects that weather's
column in eight shared interpolators (ground, roofs, leaves, sky, sea, clouds, sun light, cloud size); ColorChasers and a
PositionChaser smooth the change.   python build.py"""
import math
import pathlib
import random

OUT = pathlib.Path(__file__).with_name("gallery-25-weather-machine.x3d")
body, scene = [], []
rng = random.Random(25)
GY = 0.3                                  # top of the island
WEATHER = ["Rain", "Snow", "Storm", "Sun"]
ROUGH = 'roughness="0.9"'


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


defined = set()


def app(name, base=None, emissive=None, extra=""):
    """An Appearance: the first use DEFs it (and its PhysicalMaterial `<name>Mat`), later uses USE it."""
    if name in defined:
        return f'<Appearance USE="{name}" />'
    defined.add(name)
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance DEF="{name}"><PhysicalMaterial DEF="{name}Mat" baseColor="{base}"{em} {extra} /></Appearance>'


def phased(n, m, fn, wrap_end):
    """Keys and values of a looping sawtooth fn(u), u in 0..1, shifted by m/n of a cycle: the same path, a different phase."""
    keys, vals = [], []
    for j in range(n + 1):
        t = j / n
        if 0 < m < n and j == n - m:                      # the wrap: end of the path, then straight back to its start
            keys.append(t - 0.002)
            vals.append(fn(1.0))
        u = ((j + m) % n) / n
        keys.append(t)
        vals.append(fn(1.0) if (m == 0 and j == n) else fn(u))
    return keys, vals


def interp(kind, name, keys, vals):
    body.append(f'    <{kind} DEF="{name}" key="{" ".join("%.4f" % k for k in keys)}" keyValue="{" ".join(f(*v) for v in vals)}" />')


def clock(name, seconds, on, loop=True):
    body.append(f'    <TimeSensor DEF="{name}" cycleInterval="{seconds}" loop="{str(loop).lower()}" enabled="{str(on).lower()}" />')


def shape(a, geom):
    return f"<Shape>{a}{geom}</Shape>"


# ---------------------------------------------------------------- the world: sky, sea, island
scene.append(f'<Transform translation="0 8 -16"><Shape>{app("Sky", "0.45 0.7 1", "0.45 0.7 1")}<Box size="80 40 0.2" /></Shape></Transform>')
scene.append(f'<Transform translation="0 -0.4 2"><Shape>{app("Sea", "0.15 0.45 0.75", None, ROUGH)}<Box size="80 0.2 44" /></Shape></Transform>')
scene.append(f'<Transform translation="0 -0.05 0"><Shape>{app("Sand", "0.85 0.78 0.55")}<Cylinder radius="5.6" height="0.5" /></Shape></Transform>')
scene.append(f'<Transform DEF="Ground"><Shape>{app("Grass", "0.3 0.65 0.25", None, ROUGH)}<Cylinder radius="5" height="0.6" /></Shape></Transform>')

# house with a gable roof (two tilted boards), a door, two lit windows, a chimney
scene.append(f'''<Transform translation="-2.4 {GY} 0.8">
      <Transform translation="0 0.75 0"><Shape>{app("Wall", "0.9 0.85 0.75")}<Box size="2.6 1.5 1.9" /></Shape></Transform>
      <Transform DEF="RoofL" translation="-0.62 1.82 0" rotation="0 0 1 0.72"><Shape>{app("Roof", "0.75 0.25 0.18")}<Box size="1.9 0.14 2.2" /></Shape></Transform>
      <Transform DEF="RoofR" translation="0.62 1.82 0" rotation="0 0 1 -0.72"><Shape>{app("Roof")}<Box size="1.9 0.14 2.2" /></Shape></Transform>
      <Transform translation="0.7 2.3 -0.3"><Shape>{app("Brick", "0.5 0.3 0.25")}<Box size="0.35 0.9 0.35" /></Shape></Transform>
      <Transform translation="0 0.5 0.97"><Shape>{app("Door", "0.4 0.25 0.15")}<Box size="0.5 0.9 0.06" /></Shape></Transform>
      <Transform translation="-0.85 0.85 0.97"><Shape>{app("Glass", "1 0.85 0.4", "1 0.8 0.3")}<Box size="0.4 0.4 0.06" /></Shape></Transform>
      <Transform translation="0.85 0.85 0.97"><Shape>{app("Glass")}<Box size="0.4 0.4 0.06" /></Shape></Transform>
    </Transform>''')

# five pine trees: a trunk and two cones sharing one leaf material
for i, (x, z, s) in enumerate([(-4.0, -1.2, 1.0), (-3.4, 2.6, 0.85), (0.4, 2.7, 0.9), (1.3, -2.9, 1.1), (4.0, 1.8, 0.95)]):
    scene.append(f'''<Transform translation="{x} {GY} {z}" scale="{s} {s} {s}">
      <Transform translation="0 0.45 0"><Shape>{app("Trunk", "0.4 0.27 0.15")}<Cylinder radius="0.16" height="0.9" /></Shape></Transform>
      <Transform translation="0 1.45 0"><Shape>{app("Leaf", "0.2 0.62 0.25")}<Cone bottomRadius="0.85" height="1.5" /></Shape></Transform>
      <Transform translation="0 2.3 0"><Shape>{app("Leaf")}<Cone bottomRadius="0.6" height="1.2" /></Shape></Transform>
    </Transform>''')

# the lighthouse: three stripes, a lit lantern room, a cap
LX, LZ, LH = 3.1, -1.6, 4.6
stripe = [("0.85 0.15 0.15", 0.55), ("0.95 0.95 0.95", 0.5), ("0.85 0.15 0.15", 0.45)]
tower = ""
for k, (c, r) in enumerate(stripe):
    tower += f'<Transform translation="0 {0.75 + 1.5 * k} 0"><Shape>{app("Stripe" + str(k % 2), c)}<Cylinder radius="{r}" height="1.5" /></Shape></Transform>\n      '
scene.append(f'''<Transform translation="{LX} {GY} {LZ}">
      {tower}<Transform translation="0 {LH + 0.4} 0"><Shape>{app("Lantern", "1 0.92 0.5", "1 0.9 0.4")}<Box size="0.8 0.8 0.8" /></Shape></Transform>
      <Transform translation="0 {LH + 1.15} 0"><Shape>{app("Stripe0")}<Cone bottomRadius="0.65" height="0.8" /></Shape></Transform>
    </Transform>''')

# ---------------------------------------------------------------- clouds (size chased per weather)
clouds = ""
for i, (x, y, z) in enumerate([(-9.0, 6.6, -5), (-4.4, 7.9, -6), (0.4, 7.1, -4), (4.8, 7.8, -5.5), (9.2, 6.8, -7)]):
    puffs = "".join(f'<Transform translation="{dx} {dy} 0" scale="{sx} {sy} {sx}"><Shape>{app("CloudP", "0.97 0.97 1", None, ROUGH)}<Sphere radius="1" /></Shape></Transform>'
                    for dx, dy, sx, sy in [(-1.3, -0.1, 1.0, 0.8), (0, 0.3, 1.4, 1.1), (1.4, -0.1, 1.1, 0.85), (0.2, -0.35, 1.9, 0.6)])
    clouds += f'<Transform DEF="Cloud{i}" translation="{x} {y} {z}" scale="0.45 0.45 0.45">{puffs}</Transform>\n    '
scene.append(clouds)

# ---------------------------------------------------------------- RAIN group: 60 streaks on 3 clocks x 4 phases, 18 splashes
clock("RainA", 0.9, False)
clock("RainB", 1.1, False)
clock("RainC", 1.3, False)
clock("SplashClk", 0.8, False)
fall = lambda u: (0.0, 8.0 - 7.7 * u, 0.0)                # noqa: E731
for c, cl in enumerate("ABC"):
    for m in range(4):
        keys, vals = phased(4, m, fall, True)
        interp("PositionInterpolator", f"Fall{cl}{m}", keys, vals)
        route(f"Rain{cl}", "fraction_changed", f"Fall{cl}{m}", "set_fraction")
drops = ""
for i in range(60):
    cl, m = "ABC"[i % 3], (i // 3) % 4
    x, z = rng.uniform(-9.5, 9.5), rng.uniform(-4.5, 5.5)
    drops += (f'<Transform DEF="Drop{i}" translation="0 8 0"><Transform translation="{x:.2f} 0 {z:.2f}" rotation="0 0 1 0.14">'
              + ("<Shape DEF=\"DropShape\">" + app("Drop", "0.2 0.4 0.9", "0.25 0.45 0.9") + "<Cylinder radius=\"0.05\" height=\"0.95\" /></Shape>" if i == 0 else '<Shape USE="DropShape" />')
              + "</Transform></Transform>\n      ")
    route(f"Fall{cl}{m}", "value_changed", f"Drop{i}", "translation")
ring = lambda u: (0.15 + 1.25 * u, 1.0, 0.15 + 1.25 * u)    # noqa: E731
for m in range(4):
    keys, vals = phased(4, m, ring, True)
    interp("PositionInterpolator", f"Ring{m}", keys, vals)
    route("SplashClk", "fraction_changed", f"Ring{m}", "set_fraction")
splash = ""
for i in range(18):
    r, a = 4.3 * math.sqrt(rng.random()), rng.uniform(0, 2 * math.pi)
    x, z = r * math.cos(a), r * math.sin(a)
    if abs(x + 2.4) < 1.6 and abs(z - 0.8) < 1.3:           # not inside the house
        x += 3.6
    splash += (f'<Transform DEF="Splash{i}" translation="{x:.2f} {GY + 0.03} {z:.2f}" scale="0.15 1 0.15">'
               + ("<Transform><Shape DEF=\"SplashShape\">" + app("Splash", "0.75 0.88 1", "0.6 0.8 1") + "<Cylinder radius=\"0.3\" height=\"0.02\" /></Shape></Transform>" if i == 0 else '<Shape USE="SplashShape" />')
               + "</Transform>\n      ")
    route(f"Ring{i % 4}", "value_changed", f"Splash{i}", "scale")
scene.append(f'<Transform DEF="RainGrp" visible="false">\n      {drops}{splash}</Transform>')

# ---------------------------------------------------------------- SNOW group: 36 flakes on 2 clocks x 4 phases
clock("SnowA", 7, False)
clock("SnowB", 9, False)
drift = lambda u: (0.55 * math.sin(4 * math.pi * u), 8.0 - 7.7 * u, 0.35 * math.cos(4 * math.pi * u))    # noqa: E731
for cl in "AB":
    for m in range(4):
        keys, vals = phased(16, 4 * m, drift, True)
        interp("PositionInterpolator", f"Drift{cl}{m}", keys, vals)
        route(f"Snow{cl}", "fraction_changed", f"Drift{cl}{m}", "set_fraction")
flakes = ""
for i in range(36):
    cl, m = "AB"[i % 2], (i // 2) % 4
    x, z = rng.uniform(-9.5, 9.5), rng.uniform(-4.5, 5.5)
    s = rng.uniform(0.8, 1.7)
    flakes += (f'<Transform DEF="Flake{i}" translation="0 8 0"><Transform translation="{x:.2f} 0 {z:.2f}" scale="{s:.2f} {s:.2f} {s:.2f}">'
               + ("<Shape DEF=\"FlakeShape\">" + app("Flake", "1 1 1", "0.9 0.95 1") + "<Sphere radius=\"0.07\" /></Shape>" if i == 0 else '<Shape USE="FlakeShape" />')
               + "</Transform></Transform>\n      ")
    route(f"Drift{cl}{m}", "value_changed", f"Flake{i}", "translation")
scene.append(f'<Transform DEF="SnowGrp" visible="false">\n      {flakes}</Transform>')

# ---------------------------------------------------------------- STORM: flashes (back plate, a white-out strip, three bolts, a light), lighthouse beam
clock("StormClk", 8, False)
clock("SweepClk", 4, False)
scene.append(f'<Transform DEF="FlashBack" translation="0 8 -15" visible="false"><Shape>{app("Flash", "1 1 1", "1 1 1")}<Box size="80 40 0.2" /></Shape></Transform>')
scene.append(f'<Transform DEF="FlashFront" translation="0 8.6 9" visible="false"><Shape>{app("Flash")}<Box size="60 5 0.1" /></Shape></Transform>')
scene.append(f'<PointLight DEF="BoltLight" location="0 9 2" color="0.8 0.85 1" intensity="400" radius="40" on="false" />')
unit = f'<Shape DEF="BoltBox">{app("Bolt", "1 1 0.85", "1 1 0.8")}<Box size="1 1 1" /></Shape>'
for tag, bx, bz in (("A", -4.0, -3.0), ("B", 0.8, -6.5), ("C", 6.6, -2.4)):
    pts = [(bx, 7.8), (bx + 0.7, 6.2), (bx - 0.2, 4.9), (bx + 0.7, 3.2), (bx, 2.0), (bx + 0.5, GY)]
    segs = ""
    for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        ang = math.atan2(x1 - x0, y1 - y0)
        segs += (f'<Transform translation="{(x0 + x1) / 2:.2f} {(y0 + y1) / 2:.2f} {bz}" rotation="0 0 1 {-ang:.4f}" scale="0.2 {L:.2f} 0.2">'
                 + (unit if (tag == "A" and x0 == bx and y0 == 7.8) else '<Shape USE="BoltBox" />') + "</Transform>\n      ")
    scene.append(f'<Transform DEF="Bolt{tag}" visible="false">\n      {segs}</Transform>')
for k, (key, vals) in enumerate([("0 0.10 0.16 0.20 0.26 1", "false true false true false false"),
                                 ("0 0.45 0.50 0.55 0.60 1", "false true false true false false"),
                                 ("0 0.80 0.90 1", "false true false false")]):
    body.append(f'    <BooleanSequencer DEF="Flash{k}" key="{key}" keyValue="{vals}" />')
    route("StormClk", "fraction_changed", f"Flash{k}", "set_fraction")
    for tgt in ("FlashBack", "BoltLight", "Bolt" + "ABC"[k]) + (("FlashFront",) if k == 2 else ()):
        route(f"Flash{k}", "value_changed", tgt, "on" if tgt == "BoltLight" else "visible")
beam = f'''<Transform translation="{LX} {GY + LH + 0.4} {LZ}">
      <Transform DEF="BeamArm">
        <Transform translation="4 0 0" scale="8 0.22 0.5"><Shape USE="BoltBox" /></Transform>
        <Transform translation="-4 0 0" scale="8 0.22 0.5"><Shape USE="BoltBox" /></Transform>
      </Transform>
    </Transform>'''
interp("OrientationInterpolator", "Sweep", [0, 0.25, 0.5, 0.75, 1], [(0, 1, 0, a * math.pi / 2) for a in range(5)])
route("SweepClk", "fraction_changed", "Sweep", "set_fraction")
route("Sweep", "value_changed", "BeamArm", "rotation")
scene.append(f'<Transform DEF="StormGrp" visible="false">{beam}</Transform>')

# ---------------------------------------------------------------- SUN group: sun with turning rays, 4 birds; a rainbow of 7 arcs revealed one by one
clock("SunSpin", 14, True)
clock("BirdClk", 10, True)
clock("FlapClk", 0.6, True)
body.append('    <TimeSensor DEF="Reveal" cycleInterval="6" loop="false" />')
rays = "".join(f'<Transform rotation="0 0 1 {k * math.pi / 4:.4f}"><Transform translation="0 2.3 0">' + ("<Shape DEF=\"RayShape\">" + app("Ray", "1 0.85 0.3", "1 0.8 0.2") + "<Box size=\"0.28 1.0 0.1\" /></Shape>" if k == 0 else '<Shape USE="RayShape" />') + "</Transform></Transform>" for k in range(8))
interp("OrientationInterpolator", "SpinRays", [0, 0.25, 0.5, 0.75, 1], [(0, 0, 1, -a * math.pi / 2) for a in range(5)])
route("SunSpin", "fraction_changed", "SpinRays", "set_fraction")
route("SpinRays", "value_changed", "SunRays", "rotation")
path = lambda z: (lambda u: (-12 + 24 * u, 5.9 + 0.4 * math.sin(6 * math.pi * u), z))     # noqa: E731
interp("OrientationInterpolator", "FlapL", [0, 0.5, 1], [(0, 0, 1, -0.55), (0, 0, 1, 0.5), (0, 0, 1, -0.55)])
interp("OrientationInterpolator", "FlapR", [0, 0.5, 1], [(0, 0, 1, 0.55), (0, 0, 1, -0.5), (0, 0, 1, 0.55)])
route("FlapClk", "fraction_changed", "FlapL", "set_fraction")
route("FlapClk", "fraction_changed", "FlapR", "set_fraction")
birds = ""
for b in range(4):
    keys, vals = phased(12, 3 * b, path(-1.5 - 0.7 * b), True)
    interp("PositionInterpolator", f"Fly{b}", keys, vals)
    route("BirdClk", "fraction_changed", f"Fly{b}", "set_fraction")
    route(f"Fly{b}", "value_changed", f"Bird{b}", "translation")
    route("FlapL", "value_changed", f"WingL{b}", "rotation")
    route("FlapR", "value_changed", f"WingR{b}", "rotation")
    wing = lambda side: (f'<Transform DEF="Wing{side}{b}"><Transform translation="{-0.5 if side == "L" else 0.5} 0 0">'    # noqa: E731
                         + ("<Shape DEF=\"WingShape\">" + app("Wing", "0.2 0.2 0.25") + "<Box size=\"0.95 0.05 0.3\" /></Shape>" if (b == 0 and side == "L") else '<Shape USE="WingShape" />')
                         + "</Transform></Transform>")
    birds += (f'<Transform DEF="Bird{b}" translation="-12 6.4 -2"><Shape>{app("Wing")}<Box size="0.5 0.16 0.22" /></Shape>'
              + wing("L") + wing("R") + "</Transform>\n      ")
scene.append(f'<Transform DEF="SunGrp">\n      <Transform translation="-8.5 7.0 -9"><Shape>{app("Sun", "1 0.9 0.35", "1 0.85 0.25")}<Sphere radius="1.4" /></Shape>'
             f'<Transform DEF="SunRays">{rays}</Transform></Transform>\n      {birds}</Transform>')
rainbow = ["0.9 0.1 0.1", "1 0.5 0.1", "1 0.9 0.15", "0.2 0.75 0.25", "0.2 0.5 1", "0.3 0.2 0.8", "0.6 0.2 0.75"]
circle = " ".join(f(math.cos(a * math.pi / 4) * 0.14, math.sin(a * math.pi / 4) * 0.14) for a in range(9))
for i, col in enumerate(rainbow):
    R = 5.2 + 0.28 * i
    spine = " ".join(f(R * math.cos(math.pi * s / 14), R * math.sin(math.pi * s / 14), 0.0) for s in range(15))
    scene.append(f'<Transform DEF="Arc{i}" translation="0 {GY} -6.5"><Shape>{app("Arc" + str(i), col, col)}<Extrusion crossSection="{circle}" spine="{spine}" solid="false" creaseAngle="1.2" beginCap="false" endCap="false" /></Shape></Transform>')
    body.append(f'    <BooleanSequencer DEF="Show{i}" key="0 {0.08 + 0.1 * i:.3f} 1" keyValue="false true true" />')
    route("Reveal", "fraction_changed", f"Show{i}", "set_fraction")
    route(f"Show{i}", "value_changed", f"Arc{i}", "visible")

# ---------------------------------------------------------------- the four buttons and what a press does
BTN = {"Rain": (-3.9, "0.2 0.4 0.9"), "Snow": (-1.3, "0.85 0.92 1"), "Storm": (1.3, "0.35 0.2 0.5"), "Sun": (3.9, "1 0.8 0.2")}
panel = f'<Transform translation="0 -0.1 8.4"><Shape>{app("Panel", "0.25 0.25 0.3")}<Box size="11 0.5 2.6" /></Shape></Transform>'
icons = {
    "Rain": "".join(f'<Transform translation="{dx} 0.45 0" rotation="0 0 1 0.2"><Shape USE="DropShape" /></Transform>' for dx in (-0.3, 0, 0.3)),
    "Snow": "".join(f'<Transform translation="{dx} 0.4 {dz}"><Shape USE="FlakeShape" /></Transform>' for dx, dz in ((-0.25, 0.1), (0.25, 0.1), (0, -0.2))),
    "Storm": '<Transform translation="0 0.5 0" scale="0.15 0.55 0.15" rotation="0 0 1 0.4"><Shape USE="BoltBox" /></Transform>',
    "Sun": '<Transform translation="0 0.45 0" scale="0.3 0.3 0.3"><Shape><Appearance USE="Sun" /><Sphere radius="1" /></Shape></Transform>',
}
for k, w in enumerate(WEATHER):
    x, col = BTN[w]
    scene.append(f'''<Transform DEF="Btn{w}" translation="{x} 0.3 8.2">
      <TouchSensor DEF="Touch{w}" description="Click: {w.upper()}" />
      <Shape>{app("Btn" + w, col, col)}<Cylinder radius="0.75" height="0.3" /></Shape>
      {icons[w]}
    </Transform>''')
    scene.append(f'<Transform DEF="Pilot{w}" translation="{x} 0.4 9.3" visible="{str(w == "Sun").lower()}"><Shape>{app("Pilot", "0.4 1 0.4", "0.3 1 0.3")}<Sphere radius="0.17" /></Shape></Transform>')

for w in WEATHER:                                         # per weather: P (press), N (negated press), G (gate), H (state), Off (a false when it turns off)
    for tag in ("PNGHX" if w in ("Storm", "Sun") else "PNGH"):
        body.append(f'    <BooleanFilter DEF="{tag}{w}" />')
    body.append(f'    <TimeTrigger DEF="Trig{w}" />')
    clock(f"Tone{w}", 0.8, True, loop=False)
    body.append(f'    <ScalarInterpolator DEF="Sel{w}" key="0 1" keyValue="{WEATHER.index(w) / 3:.6f} {WEATHER.index(w) / 3:.6f}" />')
    route(f"Touch{w}", "isActive", f"P{w}", "set_boolean")
    route(f"P{w}", "inputTrue", f"N{w}", "set_boolean")
    route(f"P{w}", "inputTrue", f"G{w}", "set_boolean")
    route(f"P{w}", "inputTrue", f"Trig{w}", "set_boolean")
    route(f"Trig{w}", "triggerTime", f"Tone{w}", "startTime")
    if w == "Sun":
        route("TrigSun", "triggerTime", "Reveal", "startTime")        # the rainbow is drawn one arc at a time each time SUN is pressed
    route(f"Tone{w}", "fraction_changed", f"Sel{w}", "set_fraction")
    route(f"G{w}", "inputNegate", f"H{w}", "set_boolean")
    for other in WEATHER:
        if other != w:
            route(f"N{w}", "inputNegate", f"G{other}", "set_boolean")
    route(f"H{w}", "inputNegate", f"{w}Grp" if w != "Sun" else "SunGrp", "visible")
    route(f"H{w}", "inputNegate", f"Pilot{w}", "visible")
    if w in ("Storm", "Sun"):
        route(f"H{w}", "inputNegate", f"X{w}", "set_boolean")
for w, clocks in {"Rain": ["RainA", "RainB", "RainC", "SplashClk"], "Snow": ["SnowA", "SnowB"], "Storm": ["StormClk", "SweepClk"], "Sun": ["SunSpin", "BirdClk", "FlapClk"]}.items():
    for c in clocks:
        route(f"H{w}", "inputNegate", c, "enabled")
for tgt in ("FlashBack", "FlashFront", "BoltA", "BoltB", "BoltC"):          # a flash must not stay lit when the storm is switched off mid-flash
    route("XStorm", "inputFalse", tgt, "visible")
route("XStorm", "inputFalse", "BoltLight", "on")
for i in range(7):
    route("XSun", "inputFalse", f"Arc{i}", "visible")

# Play does not apply `visible="false"` on a group Transform at import (only on shapes), so one event at start hides the three
# idle weathers' groups and the bolts; a clock that loops far longer than any run sends it once, as the first fraction.
body.append('    <TimeSensor DEF="Boot" cycleInterval="100000" loop="true" />')
body.append('    <BooleanSequencer DEF="BootHide" key="0 1" keyValue="false false" />')
route("Boot", "fraction_changed", "BootHide", "set_fraction")
for tgt in ("RainGrp", "SnowGrp", "StormGrp", "BoltA", "BoltB", "BoltC"):
    route("BootHide", "value_changed", tgt, "visible")

# the weather's column in each shared tone interpolator (keys 0, 1/3, 2/3, 1 = rain, snow, storm, sun), through a chaser
col = lambda *cs: [tuple(float(v) for v in c.split()) for c in cs]    # noqa: E731
TONES = {                       # rain, snow, storm, sun
    "Grass": ("0.18 0.42 0.2", "0.95 0.97 1", "0.12 0.28 0.14", "0.3 0.65 0.25"),
    "Roof": ("0.4 0.15 0.12", "0.96 0.97 1", "0.25 0.1 0.1", "0.75 0.25 0.18"),
    "Leaf": ("0.12 0.4 0.18", "0.8 0.9 0.85", "0.08 0.25 0.12", "0.2 0.62 0.25"),
    "Sky": ("0.42 0.5 0.6", "0.8 0.84 0.9", "0.12 0.1 0.2", "0.45 0.7 1"),
    "Sea": ("0.15 0.3 0.45", "0.45 0.55 0.65", "0.05 0.1 0.2", "0.15 0.45 0.75"),
    "CloudP": ("0.55 0.58 0.65", "0.9 0.92 0.96", "0.2 0.18 0.25", "0.97 0.97 1"),
}
KEYS = "0 0.333333 0.666667 1"
for name, cs in TONES.items():
    body.append(f'    <ColorInterpolator DEF="Tone{name}" key="{KEYS}" keyValue="{" ".join(cs)}" />')
    body.append(f'    <ColorChaser DEF="Chase{name}" duration="2.5" initialDestination="{cs[3]}" initialValue="{cs[3]}" />')
    for w in WEATHER:
        route(f"Sel{w}", "value_changed", f"Tone{name}", "set_fraction")
    route(f"Tone{name}", "value_changed", f"Chase{name}", "set_destination")
    route(f"Chase{name}", "value_changed", f"{name}Mat", "baseColor")
    if name in ("Sky", "CloudP"):
        route(f"Chase{name}", "value_changed", f"{name}Mat", "emissiveColor")
lights = ("0.6 0.65 0.75", "0.85 0.9 1", "0.35 0.3 0.5", "1 0.95 0.85")
body.append(f'    <ColorInterpolator DEF="ToneLight" key="{KEYS}" keyValue="{" ".join(lights)}" />')
body.append(f'    <ColorChaser DEF="ChaseLight" duration="2.5" initialDestination="{lights[3]}" initialValue="{lights[3]}" />')
sizes = ("1.3 1.1 1.3", "1.0 0.9 1.0", "2.0 1.6 2.0", "0.45 0.45 0.45")
body.append(f'    <PositionInterpolator DEF="ToneSize" key="{KEYS}" keyValue="{" ".join(sizes)}" />')
body.append(f'    <PositionChaser DEF="ChaseSize" duration="2.5" initialDestination="{sizes[3]}" initialValue="{sizes[3]}" />')
for w in WEATHER:
    route(f"Sel{w}", "value_changed", "ToneLight", "set_fraction")
    route(f"Sel{w}", "value_changed", "ToneSize", "set_fraction")
route("ToneLight", "value_changed", "ChaseLight", "set_destination")
route("ChaseLight", "value_changed", "SunLight", "color")
route("ToneSize", "value_changed", "ChaseSize", "set_destination")
for i in range(5):
    route("ChaseSize", "value_changed", f"Cloud{i}", "scale")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Interpolation" level="2" />
    <component name="Followers" level="1" />
    <component name="PointingDeviceSensor" level="1" />
    <component name="Lighting" level="1" />
    <component name="Geometry3D" level="2" />
    <meta name="title" content="Gallery 25: weather machine" />
    <meta name="description" content="A small island under a sky with four buttons: rain, snow, storm, sun. Exactly one weather runs at a time." />
    <meta name="generator" content="tests/behaviour/demos/gallery-25-weather-machine/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.45 0.7 1" />
    <Viewpoint DEF="View" description="Front" position="0 5 19.5" orientation="1 0 0 -0.12" fieldOfView="0.95" />
    <DirectionalLight DEF="SunLight" direction="-0.3 -1 -0.5" intensity="1.0" color="1 0.95 0.85" />
    {panel}
    {chr(10).join("    " + s for s in scene)}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
