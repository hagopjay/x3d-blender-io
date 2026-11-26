# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-22-lava-lamp.x3d: a lava lamp in a dark room. Seven glossy blobs rise and sink in a glass tank, each on
its own pair of clocks (a slow set on mutually prime periods, a fast set on others). A PositionInterpolator makes the
path, a second one squashes and stretches the blob (scale), PositionChasers smooth both, so a change of clock never
jumps. Three buttons: HEAT enables the fast clocks and disables the slow ones, COOL does the reverse, COLOUR steps a
palette: four BooleanSequencers count the presses, each one switches on its own palette clock, and that clock drives
ColorInterpolators into ColorChasers, so the colours fade.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-22-lava-lamp.x3d")
N = 7                                                    # blobs
SLOW = [23, 29, 31, 37, 41, 43, 47]                      # seconds, mutually prime
FAST = [5, 7, 11, 13, 17, 19, 23]                        # seconds, mutually prime
SIZE = [0.62, 0.5, 0.7, 0.45, 0.56, 0.66, 0.4]
LO, HI = 2.0, 7.2                                        # blob centre height range
PAL = [                                                  # four palettes of four colours
    [(1, 0.25, 0.1), (1, 0.6, 0.1), (1, 0.2, 0.5), (1, 0.85, 0.3)],        # magma
    [(0.1, 0.6, 1), (0.1, 0.95, 0.8), (0.5, 0.3, 1), (0.25, 0.8, 1)],      # ocean
    [(0.5, 1, 0.15), (0.1, 1, 0.5), (1, 1, 0.2), (0.2, 0.9, 0.25)],        # acid
    [(1, 0.4, 0.8), (0.7, 0.4, 1), (1, 0.75, 0.9), (0.5, 0.6, 1)],         # candy
]
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra="", mat=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    flat = "" if "metallic" in extra else ' metallic="0"'            # X3D 4 PhysicalMaterial defaults to metallic 1, which draws black here
    return f'<Appearance><PhysicalMaterial {mat} baseColor="{base}"{em}{flat} {extra} /></Appearance>'


def hue_at(p, b, i):
    return PAL[p][(i + b) % 4]


steel = paint("0.08 0.08 0.1", None, 'metallic="1" roughness="0.45"')
SK = 16                                                  # samples per interpolator
ks = [i / SK for i in range(SK + 1)]

# --- the lamp: base, glass frame, cap -------------------------------------------------------------------------------
GLASS_LO, GLASS_HI, GR = 1.1, 8.1, 1.95
rods = ""
rod_paint = paint("0.6 0.75 0.8", "0.15 0.2 0.22", 'roughness="0.1"')
for k in range(8):
    a = 2 * math.pi * k / 8
    rods += (f'<Transform translation="{GR * math.cos(a):.3f} {(GLASS_LO + GLASS_HI) / 2:.3f} {GR * math.sin(a):.3f}"><Shape>{rod_paint}'
             f'<Cylinder radius="0.04" height="{GLASS_HI - GLASS_LO:.2f}" /></Shape></Transform>')
for y in (GLASS_LO, GLASS_HI):
    for k in range(16):
        a = 2 * math.pi * (k + 0.5) / 16
        rods += (f'<Transform translation="{GR * math.cos(a):.3f} {y} {GR * math.sin(a):.3f}" rotation="0 1 0 {-a - math.pi / 2:.4f}">'
                 f'<Shape>{rod_paint}<Box size="{2 * GR * math.sin(math.pi / 16) + 0.03:.3f} 0.07 0.07" /></Shape></Transform>')
tank = rods          # no translucent cylinder: the solid viewport draws it opaque and hides the blobs
base = f'''    <Transform translation="0 0.45 0"><Shape>{steel}<Cylinder radius="2.5" height="0.9" /></Shape></Transform>
    <Transform translation="0 0.95 0"><Shape>{paint("0.9 0.6 0.2", None, 'metallic="1" roughness="0.3"')}<Cylinder radius="2.1" height="0.2" /></Shape></Transform>
    <Transform translation="0 8.4 0"><Shape>{steel}<Cylinder radius="2.1" height="0.5" /></Shape></Transform>
    <Transform translation="0 9.35 0"><Shape>{paint("0.9 0.6 0.2", None, 'metallic="1" roughness="0.3"')}<Cone bottomRadius="1.5" height="1.4" /></Shape></Transform>'''

# --- the lamp colour channel: one chaser fans out to the light, base glow, pool, halo and the COLOUR button ----------
g0 = f(*PAL[0][0])
gd = f(*[0.28 * c for c in PAL[0][0]])
glow_parts = f'''    <Transform DEF="Bulb" translation="0 1.5 0"><Shape>{paint(g0, g0, 'roughness="0.2"', 'DEF="BulbPaint"')}<Sphere radius="0.35" /></Shape></Transform>
    <Transform DEF="Pool" translation="0 0.03 0"><Shape>{paint(gd, gd, '', 'DEF="PoolPaint"')}<Cylinder radius="4.4" height="0.04" /></Shape></Transform>
    <Transform DEF="Halo" translation="0 4.8 -3.5" rotation="1 0 0 1.5708"><Shape>{paint(gd, gd, '', 'DEF="HaloPaint"')}<Cylinder radius="4.6" height="0.05" /></Shape></Transform>
    <PointLight DEF="Lamp" location="0 1.5 0" color="{g0}" intensity="400" radius="14" />'''

# --- blobs ---------------------------------------------------------------------------------------------------------------
phase = [2 * math.pi * k / N * 3 % (2 * math.pi) for k in range(N)]
wob = [(1, 2), (2, 1), (1, 1), (2, 3), (1, 3), (3, 1), (2, 2)]
blob_xml = ""
for b in range(N):
    ph, r, (mx, mz) = phase[b], SIZE[b], wob[b]
    pts, sq = [], []
    for k in ks:
        a = 2 * math.pi * k + ph
        y = LO + (HI - LO) * (1 - math.cos(a)) / 2
        x = 0.65 * math.sin(2 * math.pi * k * mx + ph * 1.7) * (1 - 0.15 * r)
        z = 0.65 * math.cos(2 * math.pi * k * mz + ph * 0.6) * (1 - 0.15 * r)
        pts.append((x, y, z))
        s = abs(math.sin(a))
        sy = 0.8 + 0.55 * s
        sq.append((1 / math.sqrt(sy), sy, 1 / math.sqrt(sy)))
    c0 = f(*hue_at(0, b, int(round(0))))
    blob_xml += f'''    <Transform DEF="Blob{b}" translation="{f(*pts[0])}" scale="{f(*sq[0])}">
      <Shape>{paint(c0, c0, 'roughness="0.12"', f'DEF="Paint{b}"')}<Sphere radius="{r}" /></Shape>
    </Transform>
    <Transform DEF="Drop{b}" translation="{f(*pts[0])}">
      <Shape>{paint(c0, c0, 'roughness="0.12"', f'DEF="DropPaint{b}"')}<Sphere radius="0.13" /></Shape>
    </Transform>
'''
    body.append(f'    <TimeSensor DEF="Slow{b}" cycleInterval="{SLOW[b]}" loop="true" />')
    body.append(f'    <TimeSensor DEF="Fast{b}" cycleInterval="{FAST[b]}" loop="true" enabled="false" />')
    body.append(f'    <PositionInterpolator DEF="Path{b}" key="{f(*ks)}" keyValue="{" ".join(f(*p) for p in pts)}" />')
    body.append(f'    <PositionInterpolator DEF="Squish{b}" key="{f(*ks)}" keyValue="{" ".join(f(*s) for s in sq)}" />')
    body.append(f'    <PositionChaser DEF="Glide{b}" duration="1.6" initialDestination="{f(*pts[0])}" initialValue="{f(*pts[0])}" />')
    body.append(f'    <PositionChaser DEF="Soft{b}" duration="0.9" initialDestination="{f(*sq[0])}" initialValue="{f(*sq[0])}" />')
    body.append(f'    <PositionChaser DEF="Trail{b}" duration="2.6" initialDestination="{f(*pts[0])}" initialValue="{f(*pts[0])}" />')
    body.append(f'    <ColorChaser DEF="Skin{b}" duration="2.2" initialDestination="{c0}" initialValue="{c0}" />')
    for clock in (f"Slow{b}", f"Fast{b}"):
        route(clock, "fraction_changed", f"Path{b}", "set_fraction")
        route(clock, "fraction_changed", f"Squish{b}", "set_fraction")
    route(f"Path{b}", "value_changed", f"Glide{b}", "set_destination")
    route(f"Squish{b}", "value_changed", f"Soft{b}", "set_destination")
    route(f"Glide{b}", "value_changed", f"Blob{b}", "translation")
    route(f"Soft{b}", "value_changed", f"Blob{b}", "scale")
    route(f"Glide{b}", "value_changed", f"Trail{b}", "set_destination")
    route(f"Trail{b}", "value_changed", f"Drop{b}", "translation")
    for target in (f"Paint{b}", f"DropPaint{b}"):
        route(f"Skin{b}", "value_changed", target, "baseColor")
        route(f"Skin{b}", "value_changed", target, "emissiveColor")

# --- the palette: four clocks (one runs at a time), colour interpolators, chasers ---------------------------------------
body.append(f'    <ColorChaser DEF="BackTone" duration="2.2" initialDestination="{f(*[0.28 * c for c in PAL[0][0]])}" initialValue="{f(*[0.28 * c for c in PAL[0][0]])}" />')
body.append(f'    <ColorChaser DEF="LampTone" duration="2.2" initialDestination="{g0}" initialValue="{g0}" />')
for p in range(4):
    body.append(f'    <TimeSensor DEF="PalClock{p}" cycleInterval="13" loop="true" enabled="{"true" if p == 0 else "false"}" />')
    for b in range(N):
        vals = [hue_at(p, b, i) for i in range(5)]
        body.append(f'    <ColorInterpolator DEF="Mix{p}_{b}" key="0 0.25 0.5 0.75 1" keyValue="{" ".join(f(*v) for v in vals)}" />')
        route(f"PalClock{p}", "fraction_changed", f"Mix{p}_{b}", "set_fraction")
        route(f"Mix{p}_{b}", "value_changed", f"Skin{b}", "set_destination")
    vals = [PAL[p][(i * 3) % 4] for i in range(5)]
    body.append(f'    <ColorInterpolator DEF="Tone{p}" key="0 0.25 0.5 0.75 1" keyValue="{" ".join(f(*v) for v in vals)}" />')
    route(f"PalClock{p}", "fraction_changed", f"Tone{p}", "set_fraction")
    route(f"Tone{p}", "value_changed", "LampTone", "set_destination")
    dim = [tuple(0.28 * c for c in PAL[p][(i * 3) % 4]) for i in range(5)]      # the backdrop is a dim copy of the tone, so blobs stand out
    body.append(f'    <ColorInterpolator DEF="Dim{p}" key="0 0.25 0.5 0.75 1" keyValue="{" ".join(f(*v) for v in dim)}" />')
    route(f"PalClock{p}", "fraction_changed", f"Dim{p}", "set_fraction")
    route(f"Dim{p}", "value_changed", "BackTone", "set_destination")
for target in ("BulbPaint", "ColourPaint"):
    for fld in ("baseColor", "emissiveColor"):
        route("LampTone", "value_changed", target, fld)
for target in ("PoolPaint", "HaloPaint"):
    for fld in ("baseColor", "emissiveColor"):
        route("BackTone", "value_changed", target, fld)
route("LampTone", "value_changed", "Lamp", "color")

# --- the control panel -----------------------------------------------------------------------------------------------------
def button(name, x, colour, lamp_colour, mat=""):
    return f'''    <Transform DEF="{name}Btn" translation="{x} 1.1 5.6">
      <TouchSensor DEF="{name}Touch" description="{name}" />
      <Shape>{paint(colour, colour, 'roughness="0.25"', mat)}<Cylinder radius="0.6" height="0.4" /></Shape>
    </Transform>
    <Transform DEF="{name}Lamp" translation="{x} 1.55 4.85"{' visible="false"' if name == "Heat" else ""}><Shape>{paint(lamp_colour, lamp_colour)}<Sphere radius="0.2" /></Shape></Transform>'''


panel = f'''    <Transform translation="0 0.45 5.6"><Shape>{steel}<Box size="8.4 0.9 2.4" /></Shape></Transform>
{button("Heat", -2.6, "1 0.2 0.1", "1 0.5 0.2")}
{button("Cool", 0, "0.15 0.5 1", "0.4 0.9 1")}
{button("Colour", 2.6, g0, "1 1 1", 'DEF="ColourPaint"')}
    <Transform DEF="ColourSpark" translation="2.6 1.9 5.6" visible="false"><Shape>{paint("1 1 1", "1 1 1")}<Sphere radius="0.14" /></Shape></Transform>'''

for k in ("Heat", "Cool", "Colour"):
    body.append(f'    <BooleanFilter DEF="{k}F" />')
    route(f"{k}Touch", "isActive", f"{k}F", "set_boolean")
for b in range(N):
    route("HeatF", "inputTrue", f"Fast{b}", "enabled")
    route("HeatF", "inputFalse", f"Slow{b}", "enabled")
    route("CoolF", "inputTrue", f"Slow{b}", "enabled")
    route("CoolF", "inputFalse", f"Fast{b}", "enabled")
route("HeatF", "inputTrue", "HeatLamp", "visible")
route("CoolF", "inputFalse", "HeatLamp", "visible")
route("CoolF", "inputTrue", "CoolLamp", "visible")
route("HeatF", "inputFalse", "CoolLamp", "visible")
# COLOUR: four sequencers count the presses in step; sequencer p says "palette p is current" and enables PalClock p
body.append('    <BooleanToggle DEF="Spark" />')
route("ColourF", "inputTrue", "Spark", "set_boolean")
route("Spark", "toggle_changed", "ColourSpark", "visible")
for p in range(4):
    vals = ["true" if (i + 1) % 4 == p else "false" for i in range(4)]
    body.append(f'    <BooleanSequencer DEF="Step{p}" key="0 0.25 0.5 0.75" keyValue="{" ".join(vals)}" />')
    route("ColourF", "inputTrue", f"Step{p}", "next")
    route(f"Step{p}", "value_changed", f"PalClock{p}", "enabled")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Gallery 22: lava lamp" />
    <meta name="description" content="Seven blobs rise and sink in a glass tank; HEAT, COOL and COLOUR buttons." />
    <meta name="generator" content="tests/behaviour/demos/gallery-22-lava-lamp/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.01 0.01 0.025" />
    <Viewpoint DEF="View" description="Front" position="0 5.2 17" orientation="1 0 0 -0.09" />
    <DirectionalLight direction="0 -0.3 -1" intensity="0.5" />
    <Transform translation="0 -0.06 0"><Shape>{paint("0.03 0.03 0.04", None, 'roughness="0.9"')}<Cylinder radius="14" height="0.12" /></Shape></Transform>
{tank}
{base}
{glow_parts}
{blob_xml}{panel}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
