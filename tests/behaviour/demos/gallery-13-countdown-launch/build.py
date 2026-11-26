# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-13-countdown-launch.x3d: click the launch button. A 10 s countdown (a seven-segment digit made of seven
BooleanSequencers) with pad lights blinking faster and faster; when it ends (isActive -> BooleanFilter.inputNegate ->
TimeTrigger) the rocket lifts off on a 6 s flight with a flame, twelve smoke puffs and a shaking camera that tilts up to
follow it.   python build.py"""
import math
import pathlib
import random

OUT = pathlib.Path(__file__).with_name("gallery-13-countdown-launch.x3d")
COUNT, FLY = 10.0, 6.0
body = []
rng = random.Random(13)


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


# -- the clocks, chained: button -> Count -> Fly -------------------------------------------------------------
body.append(f'    <TimeSensor DEF="Count" cycleInterval="{COUNT}" />')
body.append(f'    <TimeSensor DEF="Fly" cycleInterval="{FLY}" />')
for name in ("GoCount", "GoFly"):
    body.append(f'    <TimeTrigger DEF="{name}" />')
body.append('    <BooleanFilter DEF="Press" />')
body.append('    <BooleanFilter DEF="CountDone" />')
route("ButtonTouch", "isActive", "Press", "set_boolean")
route("Press", "inputTrue", "GoCount", "set_boolean")
route("GoCount", "triggerTime", "Count", "startTime")
route("Count", "isActive", "CountDone", "set_boolean")
route("CountDone", "inputNegate", "GoFly", "set_boolean")
route("GoFly", "triggerTime", "Fly", "startTime")

# -- the seven-segment digit: segments a..g, digits 9 down to 0, one second each --------------------------
SEG = {0: "abcdef", 1: "bc", 2: "abdeg", 3: "abcdg", 4: "bcfg", 5: "acdfg", 6: "acdefg", 7: "abc", 8: "abcdefg", 9: "abcdfg"}
GEO = {"a": (0, 1, 1.0, 0.18), "b": (0.5, 0.5, 0.18, 1.0), "c": (0.5, -0.5, 0.18, 1.0), "d": (0, -1, 1.0, 0.18),
       "e": (-0.5, -0.5, 0.18, 1.0), "f": (-0.5, 0.5, 0.18, 1.0), "g": (0, 0, 1.0, 0.18)}
segs = ""
for name, (x, y, w, h) in GEO.items():
    segs += f'<Transform DEF="Seg{name}" translation="{x} {y} 0" visible="false"><Shape>{paint("1 0.2 0.1", "1 0.15 0.05")}<Box size="{w} {h} 0.12" /></Shape></Transform>'
    # on during the seconds whose digit uses this segment: second s shows digit 9 - s
    keys, vals, prev = [0.0], ["false"], False
    for s in range(10):
        on = name in SEG[9 - s]
        if on != prev:
            keys.append(s / 10); vals.append("true" if on else "false"); prev = on
    keys.append(1.0); vals.append("false")
    body.append(f'    <BooleanSequencer DEF="Show{name}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route("Count", "fraction_changed", f"Show{name}", "set_fraction")
    route(f"Show{name}", "value_changed", f"Seg{name}", "visible")
display = f'<Transform translation="-6 3.2 0" scale="1.4 1.4 1.4"><Shape>{paint("0.1 0.1 0.12")}<Box size="1.6 2.6 0.1" /></Shape><Transform translation="0 0 0.1">{segs}</Transform></Transform>'

# -- pad lights, blinking faster as the count runs out -----------------------------------------------------
lights = ""
for i in range(8):
    x = -3.5 + i * 1.0
    lights += f'<Transform DEF="Lamp{i}" translation="{x} 0.3 3" visible="false"><Shape>{paint("1 0.9 0.3", "1 0.8 0.2")}<Sphere radius="0.18" /></Shape></Transform>'
    ts = [1 - (1 - k / 28) ** 2 for k in range(29)]      # blink times bunch toward the end
    off = (i % 2) * 0.5 / 28
    keys = [0.0] + [min(0.999, t + off) for t in ts[1:]] + [1.0]
    keys = sorted(set(round(k, 4) for k in keys))
    vals = ["true" if (j % 2 == (i % 2)) else "false" for j in range(len(keys))]
    vals[0], vals[-1] = "false", "false"
    body.append(f'    <BooleanSequencer DEF="Blink{i}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route("Count", "fraction_changed", f"Blink{i}", "set_fraction")
    route(f"Blink{i}", "value_changed", f"Lamp{i}", "visible")

# -- the rocket: held on the pad during the count, then a launch curve -------------------------------------
PAD = (0.0, 1.4, 0.0)
n = 24
fk = [k / n for k in range(n + 1)]
ys = [PAD[1] + 0.55 * (t * FLY) ** 2.2 for t in fk]            # accelerating: ~ 0.55 t^2.2 m
body.append(f'    <PositionInterpolator DEF="Lift" key="{f(*fk)}" keyValue="{" ".join(f(0, y, 0) for y in ys)}" />')
body.append(f'    <PositionInterpolator DEF="OnPad" key="0 1" keyValue="{f(*PAD)} {f(*PAD)}" />')
route("Fly", "fraction_changed", "Lift", "set_fraction")
route("Lift", "value_changed", "Rocket", "translation")
route("Count", "fraction_changed", "OnPad", "set_fraction")
route("OnPad", "value_changed", "Rocket", "translation")
body.append('    <OrientationInterpolator DEF="Wobble" key="0 0.5 1" keyValue="0 0 1 0 0 0 1 0.06 0 0 1 0" />')
body.append('    <TimeSensor DEF="Rumble" cycleInterval="0.15" loop="true" />')
body.append('    <OrientationInterpolator DEF="Shake" key="0 0.25 0.5 0.75 1" keyValue="0 0 1 0 0 0 1 0.025 0 0 1 0 0 0 1 -0.025 0 0 1 0" />')
route("Rumble", "fraction_changed", "Shake", "set_fraction")
route("Shake", "value_changed", "Rocket", "rotation")
route("Fly", "isActive", "Flame", "visible")
body.append('    <TimeSensor DEF="Flicker" cycleInterval="0.2" loop="true" />')
body.append('    <PositionInterpolator DEF="Lick" key="0 0.5 1" keyValue="1 1 1 0.7 1.4 0.7 1 1 1" />')
route("Flicker", "fraction_changed", "Lick", "set_fraction")
route("Lick", "value_changed", "Flame", "scale")
rocket = f'''    <Transform DEF="Rocket" translation="{f(*PAD)}">
      <Shape>{paint("0.95 0.95 0.98", None, 'metallic="0.4" roughness="0.3"')}<Cylinder radius="0.5" height="2.4" /></Shape>
      <Transform translation="0 1.7 0"><Shape>{paint("0.9 0.15 0.1")}<Cone bottomRadius="0.5" height="1.0" /></Shape></Transform>
      <Transform translation="0.6 -0.9 0" rotation="0 0 1 -0.5"><Shape>{paint("0.9 0.15 0.1")}<Box size="0.15 0.9 0.5" /></Shape></Transform>
      <Transform translation="-0.6 -0.9 0" rotation="0 0 1 0.5"><Shape>{paint("0.9 0.15 0.1")}<Box size="0.15 0.9 0.5" /></Shape></Transform>
      <Transform translation="0 -0.9 0.6" rotation="1 0 0 0.5"><Shape>{paint("0.9 0.15 0.1")}<Box size="0.5 0.9 0.15" /></Shape></Transform>
      <Transform translation="0 0.3 0.52"><Shape>{paint("0.2 0.5 0.9", "0.1 0.3 0.6")}<Sphere radius="0.18" /></Shape></Transform>
      <Transform DEF="Flame" translation="0 -2.0 0" rotation="1 0 0 3.1416" visible="false"><Shape>{paint("1 0.6 0.1", "1 0.5 0.05")}<Cone bottomRadius="0.4" height="1.6" /></Shape></Transform>
    </Transform>'''

# -- smoke: twelve puffs that appear one after another as the rocket leaves, drift out and grow -------------
puffs = ""
smoke = paint("0.85 0.85 0.85", None, 'transparency="0.35"')
for p in range(12):
    s0 = 0.02 + 0.07 * p
    dx, dz = rng.uniform(-3, 3), rng.uniform(-1, 3)
    puffs += f'<Transform DEF="Puff{p}" translation="0 1 0" visible="false"><Shape>{smoke}<Sphere radius="0.6" /></Shape></Transform>'
    body.append(f'    <PositionInterpolator DEF="Drift{p}" key="0 {s0:.3f} 1" keyValue="0 1 0 0 1.2 0 {dx:.2f} 0.6 {dz:.2f}" />')
    body.append(f'    <PositionInterpolator DEF="Grow{p}" key="0 {s0:.3f} 1" keyValue="0.3 0.3 0.3 0.4 0.4 0.4 2.6 2.6 2.6" />')
    route("Fly", "fraction_changed", f"Drift{p}", "set_fraction")
    route("Fly", "fraction_changed", f"Grow{p}", "set_fraction")
    route(f"Drift{p}", "value_changed", f"Puff{p}", "translation")
    route(f"Grow{p}", "value_changed", f"Puff{p}", "scale")
    body.append(f'    <BooleanSequencer DEF="Puffing{p}" key="0 {s0:.3f} 1" keyValue="false true true" />')
    route("Fly", "fraction_changed", f"Puffing{p}", "set_fraction")
    route(f"Puffing{p}", "value_changed", f"Puff{p}", "visible")

# -- the camera: constant during the count (so a second launch starts from home), then shakes and tilts up --
HOME_P, HOME_O = (0.0, 3.0, 20.0), (1, 0, 0, -0.1)
ck, cp, co = [], [], []
for k in range(n + 1):
    t = k / n
    y = ys[k]
    look = math.atan2(y - 3.0, 20.0)
    shake = 0.25 * t * rng.uniform(-1, 1)
    ck.append(f"{t:.4f}"); cp.append(f(shake, 3.0 + 0.1 * t * 6 + shake * 0.5, 20.0 + 0.0)); co.append(f(1, 0, 0, -0.1 + min(1.2, look * 0.8)))
body.append(f'    <PositionInterpolator DEF="CamFly" key="{" ".join(ck)}" keyValue="{" ".join(cp)}" />')
body.append(f'    <OrientationInterpolator DEF="CamTilt" key="{" ".join(ck)}" keyValue="{" ".join(co)}" />')
body.append(f'    <PositionInterpolator DEF="CamHomeP" key="0 1" keyValue="{f(*HOME_P)} {f(*HOME_P)}" />')
body.append(f'    <OrientationInterpolator DEF="CamHomeO" key="0 1" keyValue="{f(*HOME_O)} {f(*HOME_O)}" />')
route("Fly", "fraction_changed", "CamFly", "set_fraction")
route("Fly", "fraction_changed", "CamTilt", "set_fraction")
route("Count", "fraction_changed", "CamHomeP", "set_fraction")
route("Count", "fraction_changed", "CamHomeO", "set_fraction")
for src, dst in (("CamFly", "position"), ("CamTilt", "orientation"), ("CamHomeP", "position"), ("CamHomeO", "orientation")):
    route(src, "value_changed", "Cam", dst)

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 13: countdown launch" />
    <meta name="description" content="Click the button: a 10 second countdown, then liftoff with flame, smoke and a shaking camera." />
    <meta name="generator" content="tests/behaviour/demos/gallery-13-countdown-launch/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.05 0.08 0.2" />
    <Viewpoint DEF="Cam" description="Pad" position="{f(*HOME_P)}" orientation="{f(*HOME_O)}" />
    <DirectionalLight direction="-0.3 -0.7 -0.6" intensity="1.0" />
    <Transform translation="0 -0.1 0"><Shape>{paint("0.3 0.3 0.28", None, 'roughness="0.9"')}<Box size="40 0.2 30" /></Shape></Transform>
    <Transform translation="0 0.15 0"><Shape>{paint("0.4 0.4 0.45", None, 'metallic="0.6"')}<Cylinder radius="2" height="0.3" /></Shape></Transform>
    <Transform translation="-2.6 3 0"><Shape>{paint("0.55 0.2 0.15")}<Box size="0.4 6 0.4" /></Shape></Transform>
    <Transform translation="-1.7 5.6 0"><Shape>{paint("0.55 0.2 0.15")}<Box size="1.8 0.3 0.3" /></Shape></Transform>
    <Transform DEF="Button" translation="4 0.5 3">
      <TouchSensor DEF="ButtonTouch" description="Click: launch" />
      <Shape>{paint("0.9 0.1 0.1", "0.5 0.0 0.0")}<Cylinder radius="0.7" height="1.0" /></Shape>
    </Transform>
    {display}
    {lights}
{rocket}
    {puffs}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
