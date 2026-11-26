# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-03-rube-goldberg.x3d: one click on the red button cascades through ten timed stages. Every stage is a
TimeSensor; when it ends (isActive false -> BooleanFilter.inputNegate -> TimeTrigger) the next stage's clock starts.
A tour clock flies the Viewpoint along the machine.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-03-rube-goldberg.x3d")
X = [-10 + 2.2 * i for i in range(10)]                  # the centre of each stage along the bench
DUR = [1.0, 1.6, 1.2, 1.0, 1.0, 1.6, 1.2, 1.6, 1.4, 1.2]
TOTAL = sum(DUR)
body, n_route = [], 0


def f(*vals):
    return " ".join(f"{v:.4f}".rstrip("0").rstrip(".") if isinstance(v, float) else str(v) for v in vals)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def shape(geom, base, emissive=None, metallic=0.0, rough=0.5, mat=None):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    d = f' DEF="{mat}"' if mat else ""
    return (f'<Shape><Appearance><PhysicalMaterial{d} baseColor="{base}"{em} metallic="{metallic}" roughness="{rough}" />'
            f'</Appearance>{geom}</Shape>')


def put(text):
    body.append(text)


def anim(name, clock, kind, keys, values, target, field):
    """An interpolator on `clock` (a TimeSensor DEF) into target.field. values: list of tuples."""
    vals = " ".join(f(*v) if isinstance(v, tuple) else f(v) for v in values)
    put(f'    <{kind}Interpolator DEF="{name}" key="{f(*keys)}" keyValue="{vals}" />')
    route(clock, "fraction_changed", name, "set_fraction")
    route(name, "value_changed", target, field)


# -- the ten stages: clock, filter, trigger ---------------------------------------------------------------------
for i, d in enumerate(DUR):
    put(f'    <TimeSensor DEF="Stage{i}" cycleInterval="{d}" />')
    put(f'    <BooleanFilter DEF="Done{i}" />')
    put(f'    <TimeTrigger DEF="Go{i}" />')
    route(f"Stage{i}", "isActive", f"Done{i}", "set_boolean")
    if i < 9:
        route(f"Done{i}", "inputNegate", f"Go{i + 1}", "set_boolean")
    route(f"Go{i}", "triggerTime", f"Stage{i}", "startTime")
put(f'    <TimeSensor DEF="Tour" cycleInterval="{TOTAL:.2f}" />')
route("Go0", "triggerTime", "Tour", "startTime")

# -- the bench ---------------------------------------------------------------------------------------------------
bench = shape('<Box size="30 0.3 3" />', "0.16 0.12 0.1", rough=0.8)
put(f'    <Transform translation="0 -0.15 0">{bench}</Transform>')

# stage 0: the button
put(f'''    <Transform translation="{X[0]} 0.2 0.3">
      {shape('<Cylinder radius="0.5" height="0.4" />', "0.3 0.3 0.34", metallic=1.0, rough=0.4)}
      <Transform DEF="Btn" translation="0 0.3 0">
        <TouchSensor DEF="StartTouch" description="Click: start the machine" />
        {shape('<Cylinder radius="0.36" height="0.3" />', "0.9 0.1 0.1", "0.4 0.02 0.02")}
      </Transform>
    </Transform>''')
route("StartTouch", "isActive", "Press", "set_boolean")
put('    <BooleanFilter DEF="Press" />')
route("Press", "inputTrue", "Go0", "set_boolean")
anim("BtnDip", "Stage0", "Position", [0, 0.4, 1], [(0, 0.3, 0), (0, 0.05, 0), (0, 0.3, 0)], "Btn", "translation")

# stage 1: six dominoes tip one after another
for k in range(6):
    x = X[1] - 1.0 + k * 0.45
    put(f'''    <Transform DEF="Domino{k}" translation="{x:.3f} 0 0">
      <Transform translation="0 0.5 0">{shape('<Box size="0.16 1 0.5" />', "0.95 0.95 0.9")}</Transform>
    </Transform>''')
    s = k * 0.11
    anim(f"Tip{k}", "Stage1", "Orientation", [0, s, s + 0.35, 1], [(0, 0, 1, 0.0), (0, 0, 1, 0.0), (0, 0, 1, -1.45), (0, 0, 1, -1.45)], f"Domino{k}", "rotation")

# stage 2: a ball rolls down a ramp
put(f'''    <Transform translation="{X[2]} 0.55 0" rotation="0 0 1 -0.35">{shape('<Box size="3 0.12 1" />', "0.35 0.35 0.4")}</Transform>
    <Transform DEF="Ball" translation="{X[2] - 1.3} 1.4 0">{shape('<Sphere radius="0.28" />', "0.2 0.6 1", "0.02 0.08 0.2", 0.8, 0.2, mat="BallPaint")}</Transform>''')
anim("Roll", "Stage2", "Position", [0, 0.3, 1], [(X[2] - 1.3, 1.4, 0), (X[2] - 1.3, 1.4, 0), (X[2] + 1.6, 0.4, 0)], "Ball", "translation")

# stage 3: a seesaw flips and throws a second ball
put(f'''    <Transform translation="{X[3]} 0.3 0">{shape('<Cone bottomRadius="0.3" height="0.6" />', "0.5 0.4 0.2")}
      <Transform DEF="Plank" translation="0 0.35 0" rotation="0 0 1 0.35">{shape('<Box size="2.4 0.1 0.8" />', "0.8 0.55 0.25")}</Transform></Transform>
    <Transform DEF="Pebble" translation="{X[3] + 0.9} 0.85 0">{shape('<Sphere radius="0.18" />', "1 0.8 0.1", "0.4 0.3 0.0")}</Transform>''')
anim("Flip", "Stage3", "Orientation", [0, 0.25, 1], [(0, 0, 1, 0.35), (0, 0, 1, -0.35), (0, 0, 1, -0.35)], "Plank", "rotation")
arc = [(X[3] + 0.9 + t * 1.2, 0.85 + 2.2 * math.sin(math.pi * t), 0) for t in [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]]
anim("Fly", "Stage3", "Position", [0, 0.25, 0.4, 0.55, 0.7, 0.85, 1], [arc[0]] + arc, "Pebble", "translation")

# stage 4: the lever lifts a flag
put(f'''    <Transform DEF="Lever" translation="{X[4] - 0.6} 0.3 0">
      <Transform translation="0.6 0 0">{shape('<Box size="1.2 0.1 0.2" />', "0.7 0.7 0.75", metallic=1.0, rough=0.3)}</Transform></Transform>
    <Transform translation="{X[4] + 0.7} 0 0">{shape('<Cylinder radius="0.03" height="2.4" />', "0.7 0.7 0.7")}
      <Transform DEF="Flag" translation="0.3 0.35 0">{shape('<Box size="0.55 0.35 0.03" />', "0.9 0.2 0.5", "0.3 0.02 0.12")}</Transform></Transform>''')
anim("Pry", "Stage4", "Orientation", [0, 1], [(0, 0, 1, 0.0), (0, 0, 1, 0.5)], "Lever", "rotation")
anim("Raise", "Stage4", "Position", [0, 0.2, 1], [(0.3, 0.35, 0), (0.3, 0.35, 0), (0.3, 2.0, 0)], "Flag", "translation")

# stage 5: a bell rings (five decaying swings) and flashes gold
put(f'''    <Transform translation="{X[5]} 2.4 0">{shape('<Box size="0.1 0.1 0.1" />', "0.4 0.4 0.4")}
      <Transform DEF="Bell" translation="0 0 0">
        <Transform translation="0 -0.5 0">{shape('<Cone bottomRadius="0.4" height="0.8" />', "0.8 0.6 0.1", "0.0 0.0 0.0", 1.0, 0.25, mat="BellPaint")}</Transform>
      </Transform></Transform>''')
anim("Ring", "Stage5", "Orientation", [0, .15, .3, .45, .6, .75, .9, 1], [(0, 0, 1, a) for a in (0.0, 0.5, -0.4, 0.3, -0.2, 0.12, -0.05, 0.0)], "Bell", "rotation")
anim("Flash", "Stage5", "Color", [0, 0.15, 1], [(0, 0, 0), (1, 0.8, 0.2), (0, 0, 0)], "BellPaint", "emissiveColor")

# stage 6: a lamp lights (on for the stage; the bulb glows)
put(f'''    <Transform translation="{X[6]} 0.9 0">{shape('<Cylinder radius="0.05" height="1.8" />', "0.3 0.3 0.3")}
      <Transform translation="0 1.0 0">{shape('<Sphere radius="0.32" />', "0.3 0.25 0.1", "0.05 0.04 0.0", mat="BulbPaint")}</Transform></Transform>
    <PointLight DEF="Lamp" location="{X[6]} 2.1 0.5" color="1 0.85 0.5" intensity="60" radius="12" on="false" />''')
route("Stage6", "isActive", "Lamp", "on")
anim("Glow", "Stage6", "Color", [0, 0.2, 1], [(0.05, 0.04, 0), (1, 0.85, 0.3), (1, 0.85, 0.3)], "BulbPaint", "emissiveColor")

# stage 7: the rocket climbs
put(f'''    <Transform DEF="Rocket" translation="{X[7]} 0.6 0">
      {shape('<Cylinder radius="0.22" height="1.0" />', "0.9 0.9 0.95", metallic=0.6, rough=0.3)}
      <Transform translation="0 0.7 0">{shape('<Cone bottomRadius="0.22" height="0.4" />', "0.9 0.2 0.1")}</Transform>
    </Transform>''')
anim("Climb", "Stage7", "Position", [0, 0.25, 0.7, 1], [(X[7], 0.6, 0), (X[7], 0.7, 0), (X[7], 3.4, 0), (X[7], 5.2, 0)], "Rocket", "translation")

# stage 8: fireworks burst where the rocket stopped
for k in range(12):
    a = 2 * math.pi * k / 12
    hue = [(1, 0.2, 0.2), (1, 0.7, 0.1), (0.3, 1, 0.3), (0.2, 0.6, 1), (0.8, 0.3, 1), (1, 0.3, 0.7)][k % 6]
    c = "%g %g %g" % hue
    put(f'''    <Transform DEF="Spark{k}" translation="{X[8] - 2 * 0 + (X[7] - X[8])} 3.6 0" visible="false">
      {shape('<Sphere radius="0.14" />', c, c)}</Transform>''')
    route("Stage8", "isActive", f"Spark{k}", "visible")
    ends = (X[7] + 1.7 * math.cos(a), 3.6 + 1.7 * math.sin(a), 0.4 * math.sin(3 * a))
    anim(f"Burst{k}", "Stage8", "Position", [0, 1], [(X[7], 3.6, 0), ends], f"Spark{k}", "translation")

# stage 9: the banner unrolls
put(f'''    <Transform DEF="Banner" translation="{X[9]} 0.3 -0.2">
      {shape('<Box size="2.2 0.9 0.06" />', "0.1 0.7 0.3", "0.02 0.3 0.08", mat="BannerPaint")}</Transform>''')
anim("Hoist", "Stage9", "Position", [0, 1], [(X[9], 0.3, -0.2), (X[9], 2.2, -0.2)], "Banner", "translation")
anim("Party", "Stage9", "Color", [0, 0.33, 0.66, 1], [(0.02, 0.3, 0.08), (0.9, 0.2, 0.2), (0.2, 0.3, 0.9), (0.95, 0.8, 0.1)], "BannerPaint", "emissiveColor")

# -- the camera follows the machine ---------------------------------------------------------------------------
t, ks, ps, os_ = 0.0, [], [], []
for i in range(10):
    ks.append(t / TOTAL)
    ps.append((X[i] - 0.4, 2.0, 7.0))
    os_.append((1, 0, 0, -0.22))
    t += DUR[i]
ks.append(1.0); ps.append((0.0, 4.0, 17.0)); os_.append((1, 0, 0, -0.2))
anim("TourPos", "Tour", "Position", ks, ps, "Cam", "position")
anim("TourLook", "Tour", "Orientation", ks, os_, "Cam", "orientation")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 03: Rube Goldberg machine" />
    <meta name="description" content="Press the red button: ten timed stages cascade, and the camera rides along." />
    <meta name="generator" content="tests/behaviour/demos/gallery-03-rube-goldberg/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.03 0.04 0.08" />
    <Viewpoint DEF="Cam" description="Tour" position="{f(*ps[0])}" orientation="{f(*os_[0])}" />
    <DirectionalLight direction="-0.3 -1 -0.5" intensity="0.9" />
    <PointLight location="0 6 6" intensity="60" radius="30" />
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
