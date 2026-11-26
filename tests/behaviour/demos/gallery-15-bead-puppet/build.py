# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-15-bead-puppet.x3d: a string puppet made of six floating beads (head, torso, two hands, two feet).
You drag the crossbar sideways (PlaneSensor, x only); every bead hangs from it on a string and follows through its own
PositionChaser (0.25 s to 1.5 s), so the figure stretches out behind the bar and pulls back together when you let go.
Hands swing and feet shuffle on looping interpolators; a spotlight ring and the bar colour answer isActive.
python build.py"""
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-15-bead-puppet.x3d")
body = []
BAR_Y = 4.4


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def mat(base, emissive=None, d=None, rough=0.5, metallic=0.0):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    dd = f' DEF="{d}"' if d else ""
    return f'<Appearance><PhysicalMaterial{dd} baseColor="{base}"{em} roughness="{rough}" metallic="{metallic}" /></Appearance>'


# name, resting (x, y), lag in seconds, shape xml, colour
parts = [
    ("Head", (0.0, 2.75), 0.25, '<Sphere radius="0.34" />', "0.95 0.75 0.55"),
    ("Torso", (0.0, 1.85), 0.45, '<Box size="0.7 1.0 0.4" />', "0.85 0.2 0.25"),
    ("HandL", (-0.95, 1.7), 0.8, '<Sphere radius="0.2" />', "0.95 0.75 0.55"),
    ("HandR", (0.95, 1.7), 1.0, '<Sphere radius="0.2" />', "0.95 0.75 0.55"),
    ("FootL", (-0.38, 0.55), 1.2, '<Box size="0.38 0.2 0.55" />', "0.15 0.3 0.8"),
    ("FootR", (0.38, 0.55), 1.5, '<Box size="0.38 0.2 0.55" />', "0.15 0.3 0.8"),
]
swing = {"HandL": (0.45, 2.4, "0 0 1"), "HandR": (-0.45, 3.1, "0 0 1"), "FootL": (0.0, 1.6, "0 0 1"), "FootR": (0.0, 1.9, "0 0 1")}
for name, (px, py), lag, shape, col in parts:
    sway = ""
    if name in ("HandL", "HandR"):
        # hands rock about a point above them, like a puppet's arms hanging from the shoulder
        amp, period, _ = swing[name]
        sway_open = f'<Transform DEF="Rock{name}" translation="0 0.5 0"><Transform translation="0 -0.5 0">'
        sway_close = "</Transform></Transform>"
        body.append(f'''    <TimeSensor DEF="RockClock{name}" cycleInterval="{period}" loop="true" />
    <OrientationInterpolator DEF="RockSwing{name}" key="0 0.25 0.5 0.75 1" keyValue="0 0 1 0 0 0 1 {amp} 0 0 1 0 0 0 1 {-amp} 0 0 1 0" />''')
        route(f"RockClock{name}", "fraction_changed", f"RockSwing{name}", "set_fraction")
        route(f"RockSwing{name}", "value_changed", f"Rock{name}", "rotation")
    else:
        sway_open = sway_close = ""
    if name.startswith("Foot"):
        period = swing[name][1]
        lift = "0 0 0 0 0.18 0 0 0 0 0 0 0 0 0 0" if name == "FootL" else "0 0 0 0 0 0 0 0 0 0 0.18 0 0 0 0"   # one foot lifts in the first half, the other in the second
        sway_open = f'<Transform DEF="Shuffle{name}">'
        sway_close = "</Transform>"
        body.append(f'''    <TimeSensor DEF="ShuffleClock{name}" cycleInterval="{period}" loop="true" />
    <PositionInterpolator DEF="ShuffleStep{name}" key="0 0.25 0.5 0.75 1" keyValue="{lift}" />''')
        route(f"ShuffleClock{name}", "fraction_changed", f"ShuffleStep{name}", "set_fraction")
        route(f"ShuffleStep{name}", "value_changed", f"Shuffle{name}", "translation")
    string_h = BAR_Y - py
    body.append(f'''    <Transform DEF="{name}">
      <Transform translation="{px} {py} 0">
        {sway_open}<Shape>{mat(col, rough=0.35)}{shape}</Shape>{sway_close}
      </Transform>
      <Transform translation="{px} {py + string_h / 2:.3f} 0"><Shape>{mat("0.8 0.8 0.75", "0.35 0.35 0.3")}<Cylinder radius="0.012" height="{string_h:.3f}" /></Shape></Transform>
    </Transform>
    <PositionChaser DEF="Lag{name}" duration="{lag}" initialDestination="0 0 0" initialValue="0 0 0" />''')
    route("Pull", "translation_changed", f"Lag{name}", "set_destination")
    route(f"Lag{name}", "value_changed", name, "translation")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Gallery 15: bead puppet" />
    <meta name="description" content="Drag the crossbar; six beads hang from it and follow through PositionChasers of different speeds." />
    <meta name="generator" content="tests/behaviour/demos/gallery-15-bead-puppet/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.06 0.04 0.1" />
    <Viewpoint DEF="View" description="Front" position="0 2.5 9" orientation="1 0 0 -0.03" />
    <DirectionalLight direction="-0.3 -0.6 -0.8" intensity="1.1" color="1 0.95 0.85" />
    <PointLight DEF="Spot" location="0 5.5 4" color="1 0.85 0.6" intensity="500" radius="30" />
    <Transform translation="0 -0.15 0"><Shape>{mat("0.25 0.12 0.3", rough=0.7)}<Box size="14 0.3 5" /></Shape></Transform>
    <Transform translation="0 2.6 -2.6"><Shape>{mat("0.4 0.1 0.2", rough=0.9)}<Box size="14 6.4 0.2" /></Shape></Transform>
    <Transform DEF="Glow" translation="0 0.02 0" scale="1 0.02 0.55" visible="false"><Shape>{mat("1 0.8 0.35", "1 0.7 0.2")}<Cylinder radius="2.6" height="1" /></Shape></Transform>
    <Transform DEF="Pull">
      <PlaneSensor DEF="Drag" description="Drag the crossbar sideways" autoOffset="true" minPosition="-4 0" maxPosition="4 0" />
      <Transform translation="0 {BAR_Y} 0">
        <Shape>{mat("0.75 0.5 0.2", d="BarPaint", rough=0.4)}<Box size="2.2 0.16 0.3" /></Shape>
        <Transform translation="0 0.35 0"><Shape>{mat("0.75 0.5 0.2", rough=0.4)}<Box size="0.16 0.7 0.16" /></Shape></Transform>
      </Transform>
    </Transform>
    <ROUTE fromNode="Drag" fromField="translation_changed" toNode="Pull" toField="translation" />
    <ROUTE fromNode="Drag" fromField="isActive" toNode="Glow" toField="visible" />
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
