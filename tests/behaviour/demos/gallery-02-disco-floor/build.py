# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-02-disco-floor.x3d: an 8x8 floor whose 64 tiles each own a ColorInterpolator and a
PositionInterpolator on one master clock, so a rainbow ripples out of the centre and the tiles bounce; a mirror ball
turns, the camera orbits (Viewpoint interpolators), and the DJ deck toggles a strobe.   python build.py"""
import colorsys
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-02-disco-floor.x3d")
G, KEYS, BEAT = 8, 24, 6.0           # tiles per side, samples per cycle, seconds per cycle


def axis_angle_look_at(eye, target):
    """X3D orientation (axis, angle) that turns a camera looking down -z, up +y, to look from eye at target."""
    f = [t - e for t, e in zip(target, eye)]
    n = math.sqrt(sum(c * c for c in f)); f = [c / n for c in f]
    r = [f[1] * 0 - f[2] * 1, f[2] * 0 - f[0] * 0, f[0] * 1 - f[1] * 0]          # f x up(0,1,0)
    r = [-f[2], 0.0, f[0]]
    n = math.hypot(r[0], r[2]); r = [r[0] / n, 0.0, r[2] / n]
    u = [r[1] * f[2] - r[2] * f[1], r[2] * f[0] - r[0] * f[2], r[0] * f[1] - r[1] * f[0]]
    # columns: right, up, -forward
    m = [[r[0], u[0], -f[0]], [r[1], u[1], -f[1]], [r[2], u[2], -f[2]]]
    tr = m[0][0] + m[1][1] + m[2][2]
    angle = math.acos(max(-1.0, min(1.0, (tr - 1) / 2)))
    ax = [m[2][1] - m[1][2], m[0][2] - m[2][0], m[1][0] - m[0][1]]
    n = math.sqrt(sum(c * c for c in ax)) or 1.0
    return [c / n for c in ax], angle


def tile(ix, iy):
    x, z = (ix - (G - 1) / 2) * 0.9, (iy - (G - 1) / 2) * 0.9
    d = math.hypot(ix - (G - 1) / 2, iy - (G - 1) / 2)
    ks = [k / KEYS for k in range(KEYS + 1)]
    cols, pos = [], []
    for k in ks:
        phase = k - d * 0.11
        hue = phase % 1.0
        pulse = 0.5 + 0.5 * math.cos(2 * math.pi * (phase * 2))
        r, g, b = colorsys.hsv_to_rgb(hue, 0.9, 0.25 + 0.75 * pulse)
        cols.append(f"{r:.3f} {g:.3f} {b:.3f}")
        pos.append(f"{x:.3f} {0.28 * max(0.0, math.sin(2 * math.pi * phase)):.3f} {z:.3f}")
    key = " ".join(f"{k:.5f}" for k in ks)
    i = f"{ix}_{iy}"
    return f"""    <Transform DEF="Tile{i}" translation="{x:.3f} 0 {z:.3f}">
      <Shape><Appearance><PhysicalMaterial DEF="TilePaint{i}" baseColor="0.05 0.05 0.05" emissiveColor="0.2 0.2 0.2" roughness="0.3" /></Appearance>
        <Box size="0.82 0.12 0.82" /></Shape>
    </Transform>
    <ColorInterpolator DEF="TileHue{i}" key="{key}" keyValue="{" ".join(cols)}" />
    <PositionInterpolator DEF="TileHop{i}" key="{key}" keyValue="{" ".join(pos)}" />
    <ROUTE fromNode="Beat" fromField="fraction_changed" toNode="TileHue{i}" toField="set_fraction" />
    <ROUTE fromNode="Beat" fromField="fraction_changed" toNode="TileHop{i}" toField="set_fraction" />
    <ROUTE fromNode="TileHue{i}" fromField="value_changed" toNode="TilePaint{i}" toField="emissiveColor" />
    <ROUTE fromNode="TileHue{i}" fromField="value_changed" toNode="TilePaint{i}" toField="baseColor" />
    <ROUTE fromNode="TileHop{i}" fromField="value_changed" toNode="Tile{i}" toField="translation" />
"""


def camera():
    n, radius, height = 32, 9.5, 5.5
    ks, ps, os_ = [], [], []
    for s in range(n + 1):
        a = 2 * math.pi * s / n
        eye = (radius * math.sin(a), height, radius * math.cos(a))
        ax, ang = axis_angle_look_at(eye, (0, 0.4, 0))
        ks.append(f"{s / n:.5f}"); ps.append("%.3f %.3f %.3f" % eye); os_.append("%.5f %.5f %.5f %.5f" % (*ax, ang))
    return " ".join(ks), " ".join(ps), " ".join(os_)


ck, cp, co = camera()
START_LOOK = " ".join(co.split(" ")[0:4])      # the bind pose is the orbit's first key, so Stop restores what Play started from
BALL_KEYS = " ".join(f"{k / 4:.2f}" for k in range(5))
BALL = " ".join(f"0 1 0 {k * math.pi / 2:.5f}" for k in range(5))
SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 02: disco floor" />
    <meta name="description" content="64 tiles ripple rainbow out of the centre on one clock; the camera orbits; click the DJ deck for strobe." />
    <meta name="generator" content="tests/behaviour/demos/gallery-02-disco-floor/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.01 0.0 0.03" />
    <Viewpoint DEF="Cam" description="Orbit" position="{cp.split(" ")[0:3] and " ".join(cp.split(" ")[0:3])}" orientation="{START_LOOK}" />
    <DirectionalLight direction="-0.2 -1 -0.4" intensity="0.25" />
    <TimeSensor DEF="Beat" cycleInterval="{BEAT}" loop="true" />
    <TimeSensor DEF="Orbit" cycleInterval="24" loop="true" />
    <TimeSensor DEF="BallClock" cycleInterval="5" loop="true" />
    <PositionInterpolator DEF="CamPos" key="{ck}" keyValue="{cp}" />
    <OrientationInterpolator DEF="CamLook" key="{ck}" keyValue="{co}" />
    <ROUTE fromNode="Orbit" fromField="fraction_changed" toNode="CamPos" toField="set_fraction" />
    <ROUTE fromNode="Orbit" fromField="fraction_changed" toNode="CamLook" toField="set_fraction" />
    <ROUTE fromNode="CamPos" fromField="value_changed" toNode="Cam" toField="position" />
    <ROUTE fromNode="CamLook" fromField="value_changed" toNode="Cam" toField="orientation" />
{"".join(tile(ix, iy) for ix in range(G) for iy in range(G))}    <Transform DEF="BallSpin" translation="0 4.2 0">
      <Shape><Appearance><PhysicalMaterial baseColor="0.9 0.9 0.95" metallic="1" roughness="0.05" emissiveColor="0.15 0.15 0.2" /></Appearance>
        <Sphere radius="0.7" /></Shape>
      <Transform translation="0 0.95 0"><Shape><Appearance><PhysicalMaterial baseColor="0.4 0.4 0.4" /></Appearance><Cylinder radius="0.02" height="1.2" /></Shape></Transform>
    </Transform>
    <OrientationInterpolator DEF="BallTurn" key="{BALL_KEYS}" keyValue="{BALL}" />
    <ROUTE fromNode="BallClock" fromField="fraction_changed" toNode="BallTurn" toField="set_fraction" />
    <ROUTE fromNode="BallTurn" fromField="value_changed" toNode="BallSpin" toField="rotation" />
    <PointLight DEF="Strobe" location="0 5 0" color="1 1 1" intensity="400" radius="25" on="false" />
    <Transform DEF="Deck" translation="-5 0.3 -5">
      <TouchSensor DEF="DeckTouch" description="Click: strobe" />
      <Shape><Appearance><PhysicalMaterial baseColor="0.8 0.1 0.3" emissiveColor="0.5 0.0 0.1" /></Appearance><Box size="1.4 0.8 1.0" /></Shape>
    </Transform>
    <BooleanFilter DEF="DeckPress" />
    <BooleanToggle DEF="StrobeFlip" />
    <ROUTE fromNode="DeckTouch" fromField="isActive" toNode="DeckPress" toField="set_boolean" />
    <ROUTE fromNode="DeckPress" fromField="inputTrue" toNode="StrobeFlip" toField="set_boolean" />
    <ROUTE fromNode="StrobeFlip" fromField="toggle_changed" toNode="Strobe" toField="on" />
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
