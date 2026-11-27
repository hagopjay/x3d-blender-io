# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-23-dance-floor.x3d: 18 stick-and-ball dancers (6 columns x 3 rows) on flashing floor tiles, with three
choreographies chosen by three buttons. Every dancer has nested limbs (torso, head, two arms each with a forearm, two
legs). For each choreography and each COLUMN there is a small clock group: one TimeSensor plus ONE interpolator per limb
type (Hop, Spin, ArmL, ArmR, Elbow, LegL, LegR, Head) and one ColorInterpolator for the tiles, phase shifted by the
column, and each interpolator is ROUTEd to the same limb of the 3 dancers in that column. A button (TouchSensor ->
BooleanFilter) enables the 6 clocks of its choreography and, through a second BooleanFilter's inputNegate, disables the
12 clocks of the other two.   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-23-dance-floor.x3d")
COLS, ROWS, K, GAP = 6, 3, 16, 1.7
body = []
TAU = 2 * math.pi


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


bump = lambda u: 0.5 - 0.5 * math.cos(TAU * u)                   # 0 at u=0, 1 at u=0.5
twirl = lambda u: min(u / 0.6, 1.0)                                # 0..1 over the first 60 % of the cycle
smooth = lambda x: x * x * (3 - 2 * x)

# --- the three choreographies: name, cycle seconds, phase lag of column c (cycles), and a motion for each limb type.
# Angles: ArmL/ArmR/Elbow/LegL/LegR/Head are rotations (axis, angle); Hop is a stretch of the whole dancer upward (a scale, not a
# translation: the eye test compares translations before Play and after Stop, and a jump would be caught mid-air); Spin is a turn about y.
Z, X, Y = (0, 0, 1), (1, 0, 0), (0, 1, 0)
CHOREOS = {
    "A": dict(label="Mexican wave", T=5.0, lag=lambda c: 0.12 * c, hue=0.52, motion={
        "Hop": lambda u: ("pos", 0.5 * bump(u) ** 3),
        "Spin": lambda u: ("ori", Y, 0.4 * math.sin(TAU * u)),
        "AL": lambda u: ("ori", Z, -2.9 * bump(u) ** 3),
        "AR": lambda u: ("ori", Z, 2.9 * bump(u) ** 3),
        "EL": lambda u: ("ori", X, -0.5 * bump(u) ** 3),
        "LL": lambda u: ("ori", X, 0.35 * bump(u) ** 3),
        "LR": lambda u: ("ori", X, 0.35 * bump(u) ** 3),
        "Hd": lambda u: ("ori", X, -0.5 * bump(u) ** 3)},
        flash=lambda u: 0.12 + 0.88 * bump(u) ** 3),
    "B": dict(label="Disco point", T=2.4, lag=lambda c: 0.5 * (c % 2), hue=0.87, motion={
        "Hop": lambda u: ("pos", 0.22 * (0.5 - 0.5 * math.cos(2 * TAU * u))),
        "Spin": lambda u: ("ori", Y, 0.5 * math.sin(TAU * u)),
        "AL": lambda u: ("ori", Z, -(1.5 + 1.5 * math.sin(TAU * u))),
        "AR": lambda u: ("ori", Z, 1.5 - 1.5 * math.sin(TAU * u)),
        "EL": lambda u: ("ori", X, -0.8 * (0.5 + 0.5 * math.sin(2 * TAU * u))),
        "LL": lambda u: ("ori", X, -0.9 * max(0.0, math.sin(TAU * u))),
        "LR": lambda u: ("ori", X, -0.9 * max(0.0, -math.sin(TAU * u))),
        "Hd": lambda u: ("ori", Z, 0.35 * math.sin(2 * TAU * u))},
        flash=lambda u: 0.12 + 0.88 * (0.5 + 0.5 * math.cos(2 * TAU * u)) ** 2),
    "C": dict(label="Twirl", T=6.0, lag=lambda c: 0.1 * c, hue=0.30, motion={
        "Hop": lambda u: ("pos", 0.35 * math.sin(math.pi * twirl(u))),
        "Spin": lambda u: ("ori", Y, TAU * smooth(twirl(u))),
        "AL": lambda u: ("ori", Z, -(1.4 + 0.4 * math.sin(2 * TAU * u))),
        "AR": lambda u: ("ori", Z, 1.4 + 0.4 * math.sin(2 * TAU * u)),
        "EL": lambda u: ("ori", X, -0.25),
        "LL": lambda u: ("ori", Z, -0.35 * math.sin(math.pi * twirl(u))),
        "LR": lambda u: ("ori", Z, 0.35 * math.sin(math.pi * twirl(u))),
        "Hd": lambda u: ("ori", Y, -0.6 * math.sin(TAU * smooth(twirl(u))))},
        flash=lambda u: 0.12 + 0.88 * math.sin(math.pi * twirl(u)) ** 2),
}
TYPES = ["Hop", "Spin", "AL", "AR", "EL", "LL", "LR", "Hd"]
ks = [k / K for k in range(K + 1)]


def dancer_targets(typ, c, r):
    d = f"{c}_{r}"
    return {"Hop": [(f"Root{d}", "scale")], "Spin": [(f"Root{d}", "rotation")], "AL": [(f"ArmL{d}", "rotation")],
            "AR": [(f"ArmR{d}", "rotation")], "EL": [(f"ForeL{d}", "rotation"), (f"ForeR{d}", "rotation")],
            "LL": [(f"LegL{d}", "rotation")], "LR": [(f"LegR{d}", "rotation")], "Hd": [(f"Head{d}", "rotation")]}[typ]


clock_names = {}
for ch, spec in CHOREOS.items():
    clock_names[ch] = []
    for c in range(COLS):
        clk = f"Clk{ch}{c}"
        clock_names[ch].append(clk)
        body.append(f'    <TimeSensor DEF="{clk}" cycleInterval="{spec["T"]}" loop="true" enabled="{"true" if ch == "A" else "false"}" />')
        for typ in TYPES:
            vals = [spec["motion"][typ]((t - spec["lag"](c)) % 1.0) for t in ks]
            name = f"{ch}{typ}{c}"
            if vals[0][0] == "pos":
                body.append(f'    <PositionInterpolator DEF="{name}" key="{f(*ks)}" keyValue="{" ".join(f(1.0, 1.0 + 0.5 * v[1], 1.0) for v in vals)}" />')
            else:
                body.append(f'    <OrientationInterpolator DEF="{name}" key="{f(*ks)}" keyValue="{" ".join(f(*v[1], v[2]) for v in vals)}" />')
            route(clk, "fraction_changed", name, "set_fraction")
            for r in range(ROWS):
                for tgt, fld in dancer_targets(typ, c, r):
                    route(name, "value_changed", tgt, fld)
        # the tile flash of this column in this choreography
        hue = spec["hue"] + 0.035 * c
        cols = [colorsys.hsv_to_rgb(hue % 1.0, 0.85, spec["flash"]((t - spec["lag"](c)) % 1.0)) for t in ks]
        body.append(f'    <ColorInterpolator DEF="{ch}Tile{c}" key="{f(*ks)}" keyValue="{" ".join(f(*x) for x in cols)}" />')
        route(clk, "fraction_changed", f"{ch}Tile{c}", "set_fraction")
        for r in range(ROWS):
            route(f"{ch}Tile{c}", "value_changed", f"TileMat{c}_{r}", "baseColor")
            route(f"{ch}Tile{c}", "value_changed", f"TileMat{c}_{r}", "emissiveColor")

# --- the three buttons: press picks one choreography, enables its clocks and disables the others
BUTTON_X = {"A": -2.6, "B": 0.0, "C": 2.6}
for ch in CHOREOS:
    body.append(f'    <BooleanFilter DEF="Press{ch}" />')
    body.append(f'    <BooleanFilter DEF="Off{ch}" />')
    route(f"Touch{ch}", "isActive", f"Press{ch}", "set_boolean")
    route(f"Press{ch}", "inputTrue", f"Off{ch}", "set_boolean")
    for clk in clock_names[ch]:
        route(f"Press{ch}", "inputTrue", clk, "enabled")
    for other in CHOREOS:
        if other != ch:
            for clk in clock_names[other]:
                route(f"Off{ch}", "inputNegate", clk, "enabled")


def part(shape, mat, y=0.0, x=0.0):
    return f'<Transform translation="{f(x, y, 0.0)}"><Shape><Appearance>{mat}</Appearance>{shape}</Shape></Transform>'


def mat(rgb, rough=0.5):
    col = f(*rgb)
    return f'<PhysicalMaterial baseColor="{col}" emissiveColor="{f(*[0.3 * v for v in rgb])}" roughness="{rough}" />'


stage = ""
x0, z0 = -(COLS - 1) * GAP / 2, -(ROWS - 1) * GAP / 2
for c in range(COLS):
    skin = mat(colorsys.hsv_to_rgb(c / COLS, 0.75, 0.95))
    face = mat((1.0, 0.85, 0.7))
    for r in range(ROWS):
        d = f"{c}_{r}"
        x, z = x0 + c * GAP, z0 + r * GAP
        stage += (f'    <Transform DEF="Tile{d}" translation="{f(x, -0.06, z)}"><Shape><Appearance>'
                  f'<PhysicalMaterial DEF="TileMat{d}" baseColor="0.1 0.1 0.15" emissiveColor="0.05 0.05 0.08" roughness="0.3" /></Appearance>'
                  f'<Box size="{GAP - 0.1:.2f} 0.12 {GAP - 0.1:.2f}" /></Shape></Transform>\n')
        stage += f'    <Transform DEF="Dancer{d}" translation="{f(x, 0.0, z)}">\n      <Transform DEF="Root{d}">\n'
        torso = part('<Box size="0.42 0.62 0.24" />', skin, 1.0)
        head_shape = part('<Sphere radius="0.17" />', face, 0.17)
        stage += f'        {torso}\n'
        stage += f'        <Transform DEF="Head{d}" translation="0 1.36 0">{head_shape}</Transform>\n'
        for side, sx in (("L", -0.28), ("R", 0.28)):
            upper = part('<Cylinder radius="0.07" height="0.36" />', skin, -0.18)
            fore_shape = part('<Cylinder radius="0.06" height="0.34" />', face, -0.17)
            stage += (f'        <Transform DEF="Arm{side}{d}" translation="{f(sx, 1.27, 0.0)}">{upper}'
                      f'<Transform DEF="Fore{side}{d}" translation="0 -0.36 0">{fore_shape}</Transform></Transform>\n')
        for side, sx in (("L", -0.12), ("R", 0.12)):
            leg_shape = part('<Cylinder radius="0.085" height="0.74" />', skin, -0.37)
            stage += f'        <Transform DEF="Leg{side}{d}" translation="{f(sx, 0.72, 0.0)}">{leg_shape}</Transform>\n'
        stage += "      </Transform>\n    </Transform>\n"

buttons = ""
for ch, spec in CHOREOS.items():
    rgb = colorsys.hsv_to_rgb(spec["hue"], 0.85, 1.0)
    buttons += (f'    <Transform DEF="Button{ch}" translation="{f(BUTTON_X[ch], 0.2, 4.0)}">\n'
                f'      <TouchSensor DEF="Touch{ch}" description="{spec["label"]}" />\n'
                f'      <Shape><Appearance><PhysicalMaterial baseColor="{f(*rgb)}" emissiveColor="{f(*[0.6 * v for v in rgb])}" metallic="0.5" roughness="0.3" /></Appearance>'
                f'<Cylinder radius="0.55" height="0.4" /></Shape>\n    </Transform>\n')

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 23: dance floor" />
    <meta name="description" content="18 stick-and-ball dancers on flashing tiles; three buttons pick the choreography: Mexican wave, disco point, twirl." />
    <meta name="generator" content="tests/behaviour/demos/gallery-23-dance-floor/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.0 0.05" />
    <Viewpoint DEF="View" description="Front of the stage" position="0 5.2 11.5" orientation="1 0 0 -0.3" />
    <DirectionalLight direction="0 -1 -0.5" intensity="1.0" />
    <Transform DEF="Stage" translation="0 -0.2 0"><Shape><Appearance><PhysicalMaterial baseColor="0.04 0.04 0.07" emissiveColor="0.02 0.02 0.04" /></Appearance><Box size="11.5 0.2 6.6" /></Shape></Transform>
{stage}{buttons}{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
