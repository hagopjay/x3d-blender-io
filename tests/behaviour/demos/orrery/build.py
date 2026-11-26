# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes orrery.x3d: a brass orrery under a star chart (see README.md). Run: python build.py

Hand-built numbers live here so the world is one readable list: four planets on arms (two with moons), each arm turned
by an OrientationInterpolator from its own looping clock; a flight to every body (TouchSensor -> TimeTrigger -> 3 s
TimeSensor -> PositionInterpolator + OrientationInterpolator into the Viewpoint); a star chart panned by the year clock
through PositionInterpolator2D -> PositionChaser2D -> TextureTransform; a lever that pauses every clock.
"""
import math
import pathlib
import random

HERE = pathlib.Path(__file__).resolve().parent

# name, orbit radius, size, colour, period (s), moon (name, orbit radius, size, period) or None
PLANETS = [
    ("Ember", 2.0, 0.22, "0.95 0.35 0.15", 4.0, None),
    ("Venus", 3.1, 0.34, "0.90 0.75 0.40", 7.0, None),
    ("Terra", 4.3, 0.40, "0.20 0.55 0.90", 12.0, ("Luna", 0.80, 0.12, 5.0)),
    ("Gale", 5.6, 0.30, "0.55 0.85 0.75", 20.0, ("Pebble", 0.62, 0.09, 9.0)),
]
YEAR = 20.0
LANE = 1.2                       # the orrery's plane, above the stage
HOME = (0.0, 3.6, 10.6)
HOME_TILT = -0.27               # radians about X (looks down at the lane)
FLY_SECONDS = 3.0
BRASS = 'baseColor="0.78 0.55 0.22" metallic="1" roughness="0.32"'


def q_mul(a, b):                 # quaternions (x, y, z, w)
    ax, ay, az, aw = a
    bx, by, bz, bw = b
    return (aw * bx + ax * bw + ay * bz - az * by, aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw, aw * bw - ax * bx - ay * by - az * bz)


def axis_angle(q):
    x, y, z, w = q
    n = math.sqrt(x * x + y * y + z * z)
    if n < 1e-12:
        return (0.0, 1.0, 0.0, 0.0)
    return (x / n, y / n, z / n, 2 * math.atan2(n, w))


def about(axis, angle):
    s = math.sin(angle / 2)
    return (axis[0] * s, axis[1] * s, axis[2] * s, math.cos(angle / 2))


def num(values):
    return " ".join(f"{v:.5f}".rstrip("0").rstrip(".") if abs(v) > 1e-9 else "0" for v in values)


def keys(count):
    return [i / count for i in range(count + 1)]


def spin_values(count):
    return [(0, 1, 0, 2 * math.pi * k) for k in keys(count)]


def view(angle_about_y, radius, height):
    """Camera at ``radius`` from the orrery's axis, ``height`` up, turned to look at the axis at LANE."""
    position = (radius * math.sin(angle_about_y), height, radius * math.cos(angle_about_y))
    pitch = -math.atan2(height - LANE, radius)
    return position, axis_angle(q_mul(about((0, 1, 0), angle_about_y), about((1, 0, 0), pitch)))


def star_chart(width=64, height=16, seed=7):
    rng = random.Random(seed)
    pixels = []
    for y in range(height):
        for x in range(width):
            glow = 0x0a1030 + (y * 2 << 8)
            pixels.append(glow)
    for _ in range(70):
        x, y = rng.randrange(width), rng.randrange(height)
        level = rng.choice((0xb0b8ff, 0xffffff, 0xffe9a0, 0x8090d0))
        pixels[y * width + x] = level
    for cx, cy in ((12, 5), (30, 9), (47, 4)):          # three brighter "constellation" crosses
        for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)):
            pixels[(cy + dy) * width + cx + dx] = 0xfff2c0 if (dx, dy) == (0, 0) else 0x6070b0
    return f"{width} {height} 3 " + " ".join(f"0x{p:06x}" for p in pixels)


def build():
    out, route = [], []
    add = out.append
    clocks = []                                              # every TimeSensor the lever pauses

    def spin(name, period, count=8):
        add(f'    <TimeSensor DEF="{name}Clock" cycleInterval="{period}" loop="true" />')
        add(f'    <OrientationInterpolator DEF="{name}Spin" key="{num(keys(count))}" keyValue="{num([c for v in spin_values(count) for c in v])}" />')
        route.append((f"{name}Clock", "fraction_changed", f"{name}Spin", "set_fraction"))
        route.append((f"{name}Spin", "value_changed", f"{name}Arm", "rotation"))
        clocks.append(f"{name}Clock")

    add('    <!-- the stage -->')
    add('    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />')
    add('    <Background skyColor="0.01 0.012 0.03" />')
    h, hp = HOME, HOME
    home_o = axis_angle(about((1, 0, 0), HOME_TILT))
    add(f'    <Viewpoint DEF="View" description="Home" position="{num(HOME)}" orientation="{num(home_o)}" />')
    add('    <DirectionalLight direction="-0.3 -0.8 -0.6" intensity="0.35" color="0.8 0.85 1" />')
    add(f'    <PointLight DEF="SunLight" location="0 {LANE} 0" color="1 0.78 0.45" intensity="12" radius="30" />')
    add('    <Transform translation="0 -0.1 0"><Shape><Appearance><PhysicalMaterial baseColor="0.05 0.06 0.10" roughness="0.9" /></Appearance><Box size="30 0.2 30" /></Shape></Transform>')
    add(f'    <Transform translation="0 0.12 0"><Shape><Appearance><PhysicalMaterial {BRASS} /></Appearance><Cylinder radius="6.6" height="0.24" /></Shape></Transform>')
    add(f'    <Transform translation="0 {LANE / 2 + 0.12:.3f} 0"><Shape><Appearance><PhysicalMaterial {BRASS} /></Appearance><Cylinder radius="0.12" height="{LANE:.3f}" /></Shape></Transform>')

    add('    <!-- the star chart on the back wall -->')
    add('    <Transform translation="0 3.6 -9.2"><Shape><Appearance><PhysicalMaterial DEF="ChartPaint" baseColor="1 1 1" roughness="0.8">'
        f'<PixelTexture containerField="baseTexture" image="{star_chart()}" repeatS="true" repeatT="true" />'
        f'<PixelTexture containerField="emissiveTexture" image="{star_chart()}" repeatS="true" repeatT="true" />'
        '</PhysicalMaterial><TextureTransform DEF="ChartMap" translation="0 0" /></Appearance><Box size="14 3.4 0.12" /></Shape></Transform>')
    add('    <Transform translation="0 5.5 -9.15"><Shape><Appearance><PhysicalMaterial ' + BRASS + ' /></Appearance><Box size="14.4 0.14 0.2" /></Shape></Transform>')
    add('    <Transform translation="0 1.7 -9.15"><Shape><Appearance><PhysicalMaterial ' + BRASS + ' /></Appearance><Box size="14.4 0.14 0.2" /></Shape></Transform>')

    add('    <!-- the year clock ticks the chart along like a ratchet: PositionInterpolator2D -> PositionChaser2D (glides each tick) -> TextureTransform -->')
    add(f'    <TimeSensor DEF="YearClock" cycleInterval="{YEAR}" loop="true" />')
    add('    <PositionInterpolator2D DEF="ChartPan" key="0 0.1 0.12 0.3 0.32 0.5 0.52 0.7 0.72 1" '
        'keyValue="0 0  0 0  0.6 0  0.6 0  1.2 0.3  1.2 0.3  0.6 0.3  0.6 0.3  0 0  0 0" />')   # ticks of 0.6 of the chart
    add('    <PositionChaser2D DEF="ChartSmooth" duration="1.5" initialDestination="0 0" initialValue="0 0" />')
    clocks.append("YearClock")
    route += [("YearClock", "fraction_changed", "ChartPan", "set_fraction"),
              ("ChartPan", "value_changed", "ChartSmooth", "set_destination"),
              ("ChartSmooth", "value_changed", "ChartMap", "translation")]

    add('    <!-- the sun: a body you can click, and the light at the middle -->')
    add(f'    <Transform DEF="Sun" translation="0 {LANE} 0"><TouchSensor DEF="SunTouch" description="Fly to the sun" />'
        '<Shape><Appearance><PhysicalMaterial baseColor="1 0.7 0.2" emissiveColor="1 0.62 0.15" /></Appearance><Sphere radius="0.8" /></Shape>'
        f'<Transform translation="0 1.6 0"><Shape><Appearance><PhysicalMaterial {BRASS} /></Appearance><Cone bottomRadius="0.7" height="1.7" /></Shape></Transform></Transform>')

    add('    <!-- planets on arms: each arm is turned by its own clock -->')
    for name, radius, size, colour, period, moon in PLANETS:
        add(f'    <Transform DEF="{name}Arm" translation="0 {LANE} 0">')
        add(f'      <Transform translation="{radius / 2:.3f} 0 0"><Shape><Appearance><PhysicalMaterial {BRASS} /></Appearance><Box size="{radius:.3f} 0.045 0.045" /></Shape></Transform>')
        add(f'      <Transform DEF="{name}" translation="{radius:.3f} 0 0">')
        add(f'        <TouchSensor DEF="{name}Touch" description="Fly to {name}" />')
        add(f'        <Shape><Appearance><PhysicalMaterial baseColor="{colour}" roughness="0.5" metallic="0.2" /></Appearance><Sphere radius="{size}" /></Shape>')
        if moon:
            mname, mradius, msize, mperiod = moon
            add(f'        <Transform DEF="{mname}Arm">')
            add(f'          <Transform translation="{mradius:.3f} 0 0"><Shape><Appearance><PhysicalMaterial baseColor="0.85 0.85 0.9" roughness="0.7" /></Appearance><Sphere radius="{msize}" /></Shape></Transform>')
            add('        </Transform>')
        add('      </Transform>')
        add('    </Transform>')
    for name, radius, size, colour, period, moon in PLANETS:
        spin(name, period)
        if moon:
            spin(moon[0], moon[3])

    add('    <!-- flights: every body has its own TouchSensor -> TimeTrigger -> 3 s clock -> two interpolators -->')
    stops = [("Sun", 0.0, 7.2, 2.7)] + [(name, ang, radius + 3.6, 2.0) for (name, radius, *_), ang in
                                        zip(PLANETS, (-0.85, -0.30, 0.30, 0.85))]
    for name, angle, radius, height in stops:
        position, orientation = view(angle, radius, height)
        middle = tuple((a + b) / 2 for a, b in zip(HOME, position))
        middle = (middle[0], max(HOME[1], position[1]) + 1.3, middle[2])
        add(f'    <TimeTrigger DEF="{name}Go" />')
        add(f'    <TimeSensor DEF="{name}Flight" cycleInterval="{FLY_SECONDS}" />')
        add(f'    <PositionInterpolator DEF="{name}Path" key="0 0.5 1" keyValue="{num(HOME)} {num(middle)} {num(position)}" />')
        add(f'    <OrientationInterpolator DEF="{name}Turn" key="0 1" keyValue="{num(home_o)} {num(orientation)}" />')
        route += [(f"{name}Touch", "isActive", f"{name}Go", "set_boolean"),
                  (f"{name}Go", "triggerTime", f"{name}Flight", "startTime"),
                  (f"{name}Flight", "fraction_changed", f"{name}Path", "set_fraction"),
                  (f"{name}Flight", "fraction_changed", f"{name}Turn", "set_fraction"),
                  (f"{name}Path", "value_changed", "View", "position"),
                  (f"{name}Turn", "value_changed", "View", "orientation")]

    add('    <!-- the lever: pause every clock (the toggle starts true, so the first pull sends false) -->')
    add(f'    <Transform DEF="Lever" translation="-3.9 0.5 4.4"><TouchSensor DEF="LeverTouch" description="Pause or resume the orrery" />'
        f'<Shape><Appearance><PhysicalMaterial {BRASS} /></Appearance><Box size="0.7 0.5 0.4" /></Shape>'
        '<Transform translation="0 0.55 0" rotation="0 0 1 0.5"><Shape><Appearance><PhysicalMaterial baseColor="0.8 0.1 0.1" emissiveColor="0.3 0.02 0.02" /></Appearance><Cylinder radius="0.07" height="0.9" /></Shape></Transform>'
        '<Transform translation="-0.22 1.0 0"><Shape><Appearance><PhysicalMaterial baseColor="0.9 0.2 0.2" emissiveColor="0.4 0.05 0.05" /></Appearance><Sphere radius="0.14" /></Shape></Transform></Transform>')
    add('    <BooleanFilter DEF="LeverPull" />')
    add('    <BooleanToggle DEF="Running" toggle="true" />')
    route += [("LeverTouch", "isActive", "LeverPull", "set_boolean"),
              ("LeverPull", "inputTrue", "Running", "set_boolean")]
    route += [("Running", "toggle_changed", clock, "enabled") for clock in clocks]

    head = f'''<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Followers" level="1" />
    <meta name="title" content="Behaviour demo: Orrery, a clockwork sky" />
    <meta name="description" content="A brass orrery: planets turn on their clocks, a star chart scrolls with the year, click a body to fly there." />
    <meta name="generator" content="tests/behaviour/demos/orrery/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
'''
    body = "\n".join(out) + "\n" + "\n".join(
        f'    <ROUTE fromNode="{a}" fromField="{b}" toNode="{c}" toField="{d}" />' for a, b, c, d in route) + "\n"
    (HERE / "orrery.x3d").write_text(head + body + "  </Scene>\n</X3D>\n", encoding="utf-8")


if __name__ == "__main__":
    build()
    print("wrote", HERE / "orrery.x3d")
