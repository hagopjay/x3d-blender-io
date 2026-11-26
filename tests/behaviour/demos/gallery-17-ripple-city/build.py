# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-17-ripple-city.x3d: a 10 x 10 city of towers whose heights and colours ride a travelling wave.
Cells are grouped into classes (7 rings out from the centre, 19 diagonals); ONE PositionInterpolator (height) and ONE
ColorInterpolator per class, phase shifted by the class index, fan out by ROUTE to every tower in the class. Two clocks
play the two families; the pedestal button (TouchSensor -> BooleanFilter -> BooleanToggle) enables one clock and
disables the other, so a click swaps the ring ripple for a diagonal sweep.   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-17-ripple-city.x3d")
N, GAP, K, T = 10, 1.15, 16, 6.0
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


ks = [k / K for k in range(K + 1)]
c = (N - 1) / 2
ring = lambda i, j: int(round(math.hypot(i - c, j - c)))
diag = lambda i, j: i + j
FAMILIES = {"R": (ring, "ClockA", 1.6), "D": (diag, "ClockB", 1.2)}   # (class of a cell, clock, phase lag across all classes in cycles)
classes = {"R": sorted({ring(i, j) for i in range(N) for j in range(N)}), "D": sorted({diag(i, j) for i in range(N) for j in range(N)})}

for fam, (_, clk, lag) in FAMILIES.items():
    span = len(classes[fam])
    for cl in classes[fam]:
        ph = cl / span * lag
        hs = [0.25 + 2.6 * (0.5 + 0.5 * math.sin(2 * math.pi * (t - ph))) ** 1.5 for t in ks]
        cols = [colorsys.hsv_to_rgb((cl / span * 0.6 + t) % 1.0, 0.9, 0.75 + 0.25 * (0.5 + 0.5 * math.sin(2 * math.pi * (t - ph)))) for t in ks]
        body.append(f'    <PositionInterpolator DEF="H{fam}{cl}" key="{f(*ks)}" keyValue="{" ".join(f(1, h, 1) for h in hs)}" />')
        body.append(f'    <ColorInterpolator DEF="C{fam}{cl}" key="{f(*ks)}" keyValue="{" ".join(f(*x) for x in cols)}" />')
        route(clk, "fraction_changed", f"H{fam}{cl}", "set_fraction")
        route(clk, "fraction_changed", f"C{fam}{cl}", "set_fraction")

towers = ""
for i in range(N):
    for j in range(N):
        x, z = (i - c) * GAP, (j - c) * GAP
        towers += (f'    <Transform DEF="Tower{i}_{j}" translation="{f(x, 0.0, z)}"><Transform translation="0 0.5 0"><Shape><Appearance>'
                   f'<PhysicalMaterial DEF="Paint{i}_{j}" baseColor="0.5 0.5 0.5" emissiveColor="0.3 0.3 0.3" roughness="0.4" /></Appearance>'
                   f'<Box size="0.95 1 0.95" /></Shape></Transform></Transform>\n')
        for fam, (cls, _, _) in FAMILIES.items():
            cl = cls(i, j)
            route(f"H{fam}{cl}", "value_changed", f"Tower{i}_{j}", "scale")
            route(f"C{fam}{cl}", "value_changed", f"Paint{i}_{j}", "baseColor")
            route(f"C{fam}{cl}", "value_changed", f"Paint{i}_{j}", "emissiveColor")

body.append(f'    <TimeSensor DEF="ClockA" cycleInterval="{T}" loop="true" enabled="true" />')
body.append(f'    <TimeSensor DEF="ClockB" cycleInterval="{T * 0.8}" loop="true" enabled="false" />')
body.append('    <BooleanFilter DEF="Press" />')
body.append('    <BooleanToggle DEF="Mode" />')
body.append('    <BooleanFilter DEF="ModeOut" />')
route("ButtonTouch", "isActive", "Press", "set_boolean")
route("Press", "inputTrue", "Mode", "set_boolean")
route("Mode", "toggle_changed", "ModeOut", "set_boolean")
route("ModeOut", "inputNegate", "ClockA", "enabled")          # toggle true -> diagonal clock on, ring clock off
route("Mode", "toggle_changed", "ClockB", "enabled")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 17: ripple city" />
    <meta name="description" content="100 towers on a rainbow travelling wave; click the pedestal to swap rings for a diagonal sweep." />
    <meta name="generator" content="tests/behaviour/demos/gallery-17-ripple-city/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.0 0.06" />
    <Viewpoint DEF="View" description="Over the city" position="0 11 17" orientation="1 0 0 -0.5" />
    <DirectionalLight direction="0 -1 -0.3" intensity="1.0" />
    <Transform DEF="Ground" translation="0 -0.1 0"><Shape><Appearance><PhysicalMaterial baseColor="0.08 0.08 0.14" emissiveColor="0.04 0.04 0.08" /></Appearance><Box size="14 0.2 14" /></Shape></Transform>
{towers}
    <Transform DEF="Pedestal" translation="0 0.25 7.8">
      <TouchSensor DEF="ButtonTouch" description="Click: rings or diagonal sweep" />
      <Shape><Appearance><PhysicalMaterial baseColor="1 0.85 0.3" emissiveColor="0.9 0.6 0.1" metallic="1" /></Appearance><Cylinder radius="0.6" height="0.5" /></Shape>
    </Transform>
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
