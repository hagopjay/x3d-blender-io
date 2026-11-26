# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-01-pendulum-wave.x3d: 15 pendulums, each on its own looping TimeSensor, drifting in and out of
phase. Click the beam (TouchSensor) and every clock restarts together.   python build.py"""
import colorsys
import math
import pathlib

N, WAVE = 15, 12.0           # pendulum i swings 6+i times per 12 s, so the whole row realigns every 12 s
AMP, KEYS = 0.62, 24         # swing amplitude (rad); sine sampled at KEYS steps per cycle
OUT = pathlib.Path(__file__).with_name("gallery-01-pendulum-wave.x3d")


def sine_keys():
    ks = [i / KEYS for i in range(KEYS + 1)]
    return ks, [math.sin(2 * math.pi * k) * AMP for k in ks]


def pendulum(i):
    x = (i - (N - 1) / 2) * 0.5
    length = 2.6 - 0.04 * abs(i - 7)
    hue = i / N
    r, g, b = colorsys.hsv_to_rgb(hue, 0.75, 1.0)
    ks, angles = sine_keys()
    key = " ".join(f"{k:.5f}" for k in ks)
    rot = " ".join(f"0 0 1 {a:.5f}" for a in angles)
    dim = f"{r * .25:.3f} {g * .25:.3f} {b * .25:.3f}"
    hot = f"{r:.3f} {g:.3f} {b:.3f}"
    cols = " ".join(c for k in ks for c in [dim if abs(math.sin(2 * math.pi * k)) < .5 else hot])
    cycle = WAVE / (6 + i)
    return f"""    <Transform DEF="Pivot{i}" translation="{x:.3f} 3.2 0">
      <Transform translation="0 {-length / 2:.3f} 0">
        <Shape><Appearance><PhysicalMaterial baseColor="0.7 0.7 0.75" metallic="1" roughness="0.3" /></Appearance>
          <Cylinder radius="0.012" height="{length:.3f}" /></Shape>
      </Transform>
      <Transform translation="0 {-length:.3f} 0">
        <Shape><Appearance><PhysicalMaterial DEF="BobPaint{i}" baseColor="{hot}" emissiveColor="{dim}" metallic="0.2" roughness="0.25" /></Appearance>
          <Sphere radius="0.19" /></Shape>
      </Transform>
    </Transform>
    <TimeSensor DEF="Clock{i}" cycleInterval="{cycle:.5f}" loop="true" />
    <OrientationInterpolator DEF="Swing{i}" key="{key}" keyValue="{rot}" />
    <ColorInterpolator DEF="Glow{i}" key="{key}" keyValue="{cols}" />
    <ROUTE fromNode="Clock{i}" fromField="fraction_changed" toNode="Swing{i}" toField="set_fraction" />
    <ROUTE fromNode="Swing{i}" fromField="value_changed" toNode="Pivot{i}" toField="rotation" />
    <ROUTE fromNode="Clock{i}" fromField="fraction_changed" toNode="Glow{i}" toField="set_fraction" />
    <ROUTE fromNode="Glow{i}" fromField="value_changed" toNode="BobPaint{i}" toField="emissiveColor" />
    <ROUTE fromNode="Restart" fromField="touchTime" toNode="Clock{i}" toField="stopTime" />
    <ROUTE fromNode="Again" fromField="triggerTime" toNode="Clock{i}" toField="startTime" />
"""


SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 01: pendulum wave" />
    <meta name="description" content="15 pendulums, 15 clocks, one beautiful drift. Click the beam: stop all, a 0.05 s gap, start all, in phase." />
    <meta name="generator" content="tests/behaviour/demos/gallery-01-pendulum-wave/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.02 0.05" />
    <Viewpoint DEF="View" description="Front" position="0 1.6 9" orientation="1 0 0 -0.05" />
    <DirectionalLight direction="-0.3 -1 -0.6" intensity="0.8" />
    <PointLight location="0 4 4" intensity="30" radius="20" color="1 0.95 0.9" />
    <Transform translation="0 -1.2 0">
      <Shape><Appearance><PhysicalMaterial baseColor="0.08 0.09 0.13" roughness="0.8" /></Appearance><Box size="14 0.2 6" /></Shape>
    </Transform>
    <Transform DEF="Beam" translation="0 3.25 0">
      <TouchSensor DEF="Restart" description="Click: restart all clocks in phase" />
      <Shape><Appearance><PhysicalMaterial baseColor="0.35 0.22 0.1" roughness="0.5" /></Appearance><Box size="8.2 0.16 0.3" /></Shape>
    </Transform>
    <Transform translation="-4.2 1.0 0"><Shape><Appearance><PhysicalMaterial baseColor="0.35 0.22 0.1" /></Appearance><Box size="0.2 4.4 0.3" /></Shape></Transform>
    <Transform translation="4.2 1.0 0"><Shape><Appearance><PhysicalMaterial baseColor="0.35 0.22 0.1" /></Appearance><Box size="0.2 4.4 0.3" /></Shape></Transform>
    <TimeSensor DEF="Gap" cycleInterval="0.05" />
    <BooleanFilter DEF="GapDone" />
    <TimeTrigger DEF="Again" />
    <ROUTE fromNode="Restart" fromField="touchTime" toNode="Gap" toField="startTime" />
    <ROUTE fromNode="Gap" fromField="isActive" toNode="GapDone" toField="set_boolean" />
    <ROUTE fromNode="GapDone" fromField="inputNegate" toNode="Again" toField="set_boolean" />
{"".join(pendulum(i) for i in range(N))}  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
