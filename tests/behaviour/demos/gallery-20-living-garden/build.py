# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-20-living-garden.x3d: four seed mounds, each its own TouchSensor chain. Click one and a plant grows (stem
scale and head rise on interpolators, leaves unfurl, the bud opens its eight petals through ONE OrientationInterpolator fanned
to all eight, and the colour goes green to petal colour). Two bees and two butterflies fly looping paths (Position and
Orientation interpolators with a look-at heading, wings flapping on fast clocks). A 30 s day clock tints the light, the
sky and the grass, and at dusk eight fireflies blink (BooleanSequencers driven by the same clock).   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-20-living-garden.x3d")
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def qmul(a, b):
    w1, x1, y1, z1 = a; w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def axq(ax, ang):
    s = math.sin(ang / 2)
    return (math.cos(ang / 2), ax[0] * s, ax[1] * s, ax[2] * s)


def toaxis(q):
    w, x, y, z = q
    if w < 0:
        w, x, y, z = -w, -x, -y, -z
    ang = 2 * math.acos(max(-1.0, min(1.0, w)))
    s = math.sqrt(max(1e-12, 1 - w * w))
    return (x / s, y / s, z / s, ang) if ang > 1e-6 else (0, 1, 0, 0)


def col(c, k=1.0):
    return f"{c[0] * k:.3f} {c[1] * k:.3f} {c[2] * k:.3f}"


def mat(base, emissive=None, extra="", defn=""):
    d = f' DEF="{defn}"' if defn else ""
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial{d} baseColor="{base}"{em} {extra} /></Appearance>'


# ---------- the day clock: noon, golden, dusk, night, dawn, noon ----------
DAY = 30.0
dk = [0, 0.3, 0.45, 0.55, 0.85, 0.95, 1]
sky = [(0.45, 0.75, 1.0), (0.95, 0.75, 0.5), (0.5, 0.3, 0.45), (0.04, 0.05, 0.16), (0.04, 0.05, 0.16), (0.9, 0.6, 0.55), (0.45, 0.75, 1.0)]
sun = [(1.0, 0.97, 0.9), (1.0, 0.7, 0.4), (0.6, 0.35, 0.5), (0.15, 0.2, 0.45), (0.15, 0.2, 0.45), (1.0, 0.7, 0.55), (1.0, 0.97, 0.9)]
grass = [(0.3, 0.65, 0.25), (0.35, 0.5, 0.2), (0.2, 0.3, 0.2), (0.04, 0.1, 0.08), (0.04, 0.1, 0.08), (0.25, 0.45, 0.2), (0.3, 0.65, 0.25)]
body.append(f'    <TimeSensor DEF="Day" cycleInterval="{DAY}" loop="true" />')
for nm, tab in (("SkyTint", sky), ("SunTint", sun), ("GrassTint", grass)):
    body.append(f'    <ColorInterpolator DEF="{nm}" key="{f(*dk)}" keyValue="{" ".join(col(c) for c in tab)}" />')
    route("Day", "fraction_changed", nm, "set_fraction")
route("SkyTint", "value_changed", "SkyMat", "baseColor")
route("SkyTint", "value_changed", "SkyMat", "emissiveColor")
route("SunTint", "value_changed", "Sun", "color")
route("GrassTint", "value_changed", "GrassMat", "baseColor")
route("GrassTint", "value_changed", "GrassMat", "emissiveColor")

# ---------- four seed mounds, four plants ----------
PLANTS = [  # x, z, height, petal colour
    (-5.4, 0.4, 2.6, (0.95, 0.15, 0.2)),
    (-1.8, -0.7, 3.3, (1.0, 0.82, 0.1)),
    (1.8, 0.5, 2.4, (1.0, 0.45, 0.72)),
    (5.4, -0.4, 3.0, (0.6, 0.3, 0.95)),
]
GREEN = (0.25, 0.62, 0.2)
GROW = 5.0
NP = 8
plants = []
for p, (x, z, H, pc) in enumerate(PLANTS):
    pieces = []
    for k in range(NP):
        ring = 2 * math.pi * k / NP
        rough = 'roughness="0.5"'
        pm = mat(col(GREEN), col(GREEN, 0.3), rough, f"PetMat{p}_{k}")
        pieces.append(f'<Transform rotation="0 1 0 {ring:.4f}"><Transform DEF="Pet{p}_{k}" rotation="0 0 1 1.45">'
                      f'<Transform translation="0.6 0 0" scale="1 0.2 0.6"><Shape>{pm}<Sphere radius="0.5" /></Shape></Transform></Transform></Transform>')
    petals = "".join(pieces)
    leaf_mat = mat(col(GREEN, 0.9), col(GREEN, 0.25), 'roughness="0.6"')
    stem_mat = mat(col(GREEN, 0.85), col(GREEN, 0.2), 'roughness="0.7"')
    centre = mat(col((0.45, 0.25, 0.08)), col((0.3, 0.15, 0.04)), 'roughness="0.8"')
    mound = mat(col((0.38, 0.24, 0.13)), col((0.12, 0.07, 0.03)), 'roughness="0.95"')
    stem_r = 0.07
    plant = f'''    <Transform DEF="Mound{p}" translation="{x} 0.05 {z}">
      <TouchSensor DEF="Touch{p}" description="Click: plant a seed" />
      <Transform scale="1 0.38 1"><Shape>{mound}<Sphere radius="0.8" /></Shape></Transform>
      <Transform DEF="Stem{p}" translation="0 0.1 0" scale="1 0.01 1"><Transform translation="0 {H / 2:.3f} 0"><Shape>{stem_mat}<Cylinder radius="{stem_r}" height="{H}" /></Shape></Transform></Transform>
      <Transform DEF="LeafA{p}" translation="0 {H * 0.35:.3f} 0" rotation="0 1 0 0.6" scale="0.01 0.01 0.01"><Transform translation="0.45 0.1 0" rotation="0 0 1 0.35" scale="1 0.14 0.5"><Shape>{leaf_mat}<Sphere radius="0.5" /></Shape></Transform></Transform>
      <Transform DEF="LeafB{p}" translation="0 {H * 0.55:.3f} 0" rotation="0 1 0 3.6" scale="0.01 0.01 0.01"><Transform translation="0.45 0.1 0" rotation="0 0 1 0.35" scale="1 0.14 0.5"><Shape>{leaf_mat}<Sphere radius="0.5" /></Shape></Transform></Transform>
      <Transform DEF="Head{p}" translation="0 0.12 0">
        <Transform DEF="Bud{p}" scale="0.05 0.05 0.05">
          {petals}
          <Transform DEF="Eye{p}" translation="0 0.04 0" scale="1 0.55 1"><Shape>{centre}<Sphere radius="0.34" /></Shape></Transform>
        </Transform>
      </Transform>
    </Transform>'''
    plants.append(plant)
    body.append(f'    <BooleanFilter DEF="Press{p}" />')
    body.append(f'    <TimeTrigger DEF="Plant{p}" />')
    body.append(f'    <TimeSensor DEF="Grow{p}" cycleInterval="{GROW}" />')
    route(f"Touch{p}", "isActive", f"Press{p}", "set_boolean")
    route(f"Press{p}", "inputTrue", f"Plant{p}", "set_boolean")
    route(f"Plant{p}", "triggerTime", f"Grow{p}", "startTime")
    # stem: shoots up then settles (small overshoot)
    gk = [0, 0.5, 0.65, 1]
    body.append(f'    <PositionInterpolator DEF="StemUp{p}" key="{f(*gk)}" keyValue="1 0.01 1 1 1.05 1 1 0.98 1 1 1 1" />')
    body.append(f'    <PositionInterpolator DEF="HeadUp{p}" key="{f(*gk)}" keyValue="0 0.12 0 0 {H * 1.05 + 0.1:.3f} 0 0 {H * 0.98 + 0.1:.3f} 0 0 {H + 0.1:.3f} 0" />')
    body.append(f'    <PositionInterpolator DEF="LeafUp{p}" key="0 0.2 0.55 0.75 1" keyValue="0.01 0.01 0.01 0.01 0.01 0.01 1.1 1.1 1.1 0.95 0.95 0.95 1 1 1" />')
    body.append(f'    <PositionInterpolator DEF="BudUp{p}" key="0 0.4 0.6 1" keyValue="0.05 0.05 0.05 0.5 0.5 0.5 1 1 1 1.15 1.15 1.15" />')
    body.append(f'    <OrientationInterpolator DEF="Open{p}" key="0 0.45 0.8 0.92 1" keyValue="0 0 1 1.45 0 0 1 1.45 0 0 1 -0.12 0 0 1 0.1 0 0 1 0.02" />')
    petc = col(pc)
    bright = col(tuple(min(1, c * 1.1 + 0.05) for c in pc))
    body.append(f'    <ColorInterpolator DEF="Bloom{p}" key="0 0.45 0.8 1" keyValue="{col(GREEN)} {col(GREEN)} {petc} {bright}" />')
    for nm in (f"StemUp{p}", f"HeadUp{p}", f"LeafUp{p}", f"BudUp{p}", f"Open{p}", f"Bloom{p}"):
        route(f"Grow{p}", "fraction_changed", nm, "set_fraction")
    route(f"StemUp{p}", "value_changed", f"Stem{p}", "scale")
    route(f"HeadUp{p}", "value_changed", f"Head{p}", "translation")
    route(f"LeafUp{p}", "value_changed", f"LeafA{p}", "scale")
    route(f"LeafUp{p}", "value_changed", f"LeafB{p}", "scale")
    route(f"BudUp{p}", "value_changed", f"Bud{p}", "scale")
    for k in range(NP):
        route(f"Open{p}", "value_changed", f"Pet{p}_{k}", "rotation")
        route(f"Bloom{p}", "value_changed", f"PetMat{p}_{k}", "baseColor")
        route(f"Bloom{p}", "value_changed", f"PetMat{p}_{k}", "emissiveColor")

# ---------- flying things ----------
def flight(name, cycle, cx, cy, cz, ax, ay, az, ph, n=28):
    ks, ps, os_ = [], [], []

    def spot(t):
        a = 2 * math.pi * t + ph
        return (cx + ax * math.sin(a), cy + ay * math.sin(3 * a + ph), cz + az * math.sin(2 * a))
    for i in range(n + 1):
        t = i / n
        p, p2 = spot(t), spot(t + 0.003)
        yaw = math.atan2(-(p2[2] - p[2]), p2[0] - p[0])
        ks.append(f"{t:.5f}"); ps.append(f(*p)); os_.append(f(*toaxis(axq((0, 1, 0), yaw))))
    body.append(f'    <TimeSensor DEF="{name}Clock" cycleInterval="{cycle}" loop="true" />')
    body.append(f'    <PositionInterpolator DEF="{name}Pos" key="{" ".join(ks)}" keyValue="{" ".join(ps)}" />')
    body.append(f'    <OrientationInterpolator DEF="{name}Turn" key="{" ".join(ks)}" keyValue="{" ".join(os_)}" />')
    route(f"{name}Clock", "fraction_changed", f"{name}Pos", "set_fraction")
    route(f"{name}Clock", "fraction_changed", f"{name}Turn", "set_fraction")
    route(f"{name}Pos", "value_changed", name, "translation")
    route(f"{name}Turn", "value_changed", name, "rotation")
    return ps[0], os_[0]


def flap(name, cycle, amp):
    body.append(f'    <TimeSensor DEF="{name}Beat" cycleInterval="{cycle}" loop="true" />')
    body.append(f'    <OrientationInterpolator DEF="{name}FlapR" key="0 0.5 1" keyValue="1 0 0 {-amp} 1 0 0 {amp * 0.2} 1 0 0 {-amp}" />')
    body.append(f'    <OrientationInterpolator DEF="{name}FlapL" key="0 0.5 1" keyValue="1 0 0 {amp} 1 0 0 {-amp * 0.2} 1 0 0 {amp}" />')
    for s in ("FlapR", "FlapL"):
        route(f"{name}Beat", "fraction_changed", f"{name}{s}", "set_fraction")
    route(f"{name}FlapR", "value_changed", f"{name}WingR", "rotation")
    route(f"{name}FlapL", "value_changed", f"{name}WingL", "rotation")


glass = mat("0.95 0.97 1.0", "0.5 0.55 0.6", 'transparency="0.45" roughness="0.1"')
yellow = mat("1.0 0.8 0.1", "0.35 0.25 0.0", 'roughness="0.5"')
black = mat("0.1 0.08 0.05", None, 'roughness="0.6"')
bees = []
for b, (cyc, cx, cy, cz, ax, ay, az, ph) in enumerate([(16, 0.0, 3.1, 1.2, 6.2, 0.6, 1.8, 0.0), (21, 0.5, 2.2, 1.8, 5.2, 0.5, 1.4, 2.0)]):
    nm = f"Bee{b}"
    p0, o0 = flight(nm, cyc, cx, cy, cz, ax, ay, az, ph)
    flap(nm, 0.14, 0.9)
    bees.append(f'''    <Transform DEF="{nm}" translation="{p0}" rotation="{o0}">
      <Transform scale="1.25 0.8 0.8"><Shape>{yellow}<Sphere radius="0.17" /></Shape></Transform>
      <Transform translation="-0.07 0 0" scale="0.2 1 1"><Shape>{black}<Sphere radius="0.14" /></Shape></Transform>
      <Transform translation="0.2 0.03 0"><Shape>{black}<Sphere radius="0.09" /></Shape></Transform>
      <Transform DEF="{nm}WingR" translation="0 0.12 0.06"><Transform translation="0 0 0.12"><Shape>{glass}<Box size="0.18 0.01 0.26" /></Shape></Transform></Transform>
      <Transform DEF="{nm}WingL" translation="0 0.12 -0.06"><Transform translation="0 0 -0.12"><Shape>{glass}<Box size="0.18 0.01 0.26" /></Shape></Transform></Transform>
    </Transform>''')
flies = []
for b, (cyc, cx, cy, cz, ax, ay, az, ph, c1, c2) in enumerate([
        (26, -1.0, 2.6, 2.4, 6.0, 0.8, 1.6, 1.0, (1.0, 0.55, 0.1), (0.25, 0.1, 0.05)),
        (31, 1.0, 1.7, 2.2, 5.4, 0.7, 1.2, 4.0, (0.3, 0.55, 1.0), (0.05, 0.1, 0.4))]):
    nm = f"Fly{b}"
    p0, o0 = flight(nm, cyc, cx, cy, cz, ax, ay, az, ph)
    flap(nm, 0.55, 1.0)
    wm = mat(col(c1), col(c1, 0.4), 'roughness="0.4"')
    dm = mat(col(c2), None, 'roughness="0.4"')

    def wing(side, sg):
        return (f'<Transform DEF="{nm}Wing{side}" translation="0 0.04 {0.03 * sg}"><Transform translation="0 0 {0.26 * sg}"><Shape>{wm}<Box size="0.34 0.012 0.5" /></Shape></Transform>'
                f'<Transform translation="-0.1 0.007 {0.2 * sg}"><Shape>{dm}<Box size="0.12 0.012 0.18" /></Shape></Transform></Transform>')
    flies.append(f'''    <Transform DEF="{nm}" translation="{p0}" rotation="{o0}">
      <Transform scale="3 0.6 0.6"><Shape>{dm}<Sphere radius="0.06" /></Shape></Transform>
      {wing("R", 1)}{wing("L", -1)}
    </Transform>''')

# ---------- fireflies at dusk ----------
ffs = []
glow = mat("0.9 1.0 0.3", "0.9 1.0 0.2", 'roughness="0.3"')
for i in range(8):
    hx, hy, hz = -6.5 + 1.9 * i, 0.8 + 0.5 * ((i * 3) % 4), -1.4 + 1.1 * ((i * 5) % 4)
    cyc = 4.0 + 0.7 * i
    ffs.append(f'    <Transform DEF="Glim{i}" translation="{hx:.2f} {hy:.2f} {hz:.2f}" visible="false"><Shape>{glow}<Sphere radius="0.07" /></Shape></Transform>')
    n = 6
    ks = [j / n for j in range(n + 1)]
    pts = [(hx + 0.6 * math.sin(2 * math.pi * j / n + i), hy + 0.35 * math.sin(4 * math.pi * j / n + i), hz + 0.5 * math.cos(2 * math.pi * j / n + i)) for j in range(n)]
    pts.append(pts[0])
    body.append(f'    <TimeSensor DEF="Drift{i}" cycleInterval="{cyc}" loop="true" />')
    body.append(f'    <PositionInterpolator DEF="Wander{i}" key="{f(*ks)}" keyValue="{" ".join(f(*q) for q in pts)}" />')
    route(f"Drift{i}", "fraction_changed", f"Wander{i}", "set_fraction")
    route(f"Wander{i}", "value_changed", f"Glim{i}", "translation")
    # blink only between dusk (0.46) and dawn (0.88), a pattern that depends on the firefly
    keys, vals = [0.0], ["false"]
    t, on = 0.46 + 0.004 * i, True
    while t < 0.88:
        keys.append(round(t, 4)); vals.append("true" if on else "false")
        t += (0.014 + 0.003 * ((i + len(keys)) % 4)) if on else (0.010 + 0.004 * ((i * 2 + len(keys)) % 3))
        on = not on
    keys.append(0.9); vals.append("false")
    body.append(f'    <BooleanSequencer DEF="Blink{i}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route("Day", "fraction_changed", f"Blink{i}", "set_fraction")
    route(f"Blink{i}", "value_changed", f"Glim{i}", "visible")

# ---------- scenery: grass tufts and two clouds ----------
tufts = []
blade = mat("0.3 0.62 0.22", "0.08 0.2 0.05", 'roughness="0.8"')
for i in range(26):
    gx = -9 + 18.0 * ((i * 0.618) % 1.0)
    gz = -2.6 + 5.4 * ((i * 0.381 + 0.13) % 1.0)
    tufts.append(f'    <Transform translation="{gx:.2f} 0.1 {gz:.2f}" rotation="0 1 0 {i:.2f}"><Transform translation="0 0.17 0" rotation="0 0 1 0.2"><Shape>{blade}<Cone bottomRadius="0.06" height="{0.34 + 0.12 * (i % 3):.2f}" /></Shape></Transform>'
                 f'<Transform translation="0.06 0.14 0" rotation="0 0 1 -0.35"><Shape>{blade}<Cone bottomRadius="0.05" height="0.28" /></Shape></Transform></Transform>')
cloud_m = mat("1 1 1", "0.9 0.9 0.95", 'roughness="1"')
clouds = []
for c, (cy, cyc, x0) in enumerate([(6.4, 48, -8), (5.6, 64, 3)]):
    clouds.append(f'    <Transform DEF="Cloud{c}" translation="{x0} {cy} -5">' + "".join(
        f'<Transform translation="{dx} {dy} 0" scale="1 0.55 0.6"><Shape>{cloud_m}<Sphere radius="{r}" /></Shape></Transform>'
        for dx, dy, r in ((0, 0, 1.0), (1.0, -0.1, 0.8), (-0.9, -0.1, 0.75), (0.3, 0.3, 0.7))) + '</Transform>')
    body.append(f'    <TimeSensor DEF="Drifting{c}" cycleInterval="{cyc}" loop="true" />')
    body.append(f'    <PositionInterpolator DEF="CloudPath{c}" key="0 0.5 1" keyValue="-9 {cy} -5 0 {cy} -5 9 {cy} -5" />')
    route(f"Drifting{c}", "fraction_changed", f"CloudPath{c}", "set_fraction")
    route(f"CloudPath{c}", "value_changed", f"Cloud{c}", "translation")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="Interpolation" level="2" />
    <component name="Lighting" level="1" />
    <meta name="title" content="Gallery 20: living garden" />
    <meta name="description" content="Click a seed mound: a plant grows and blooms. Bees and butterflies fly, the day turns to dusk and fireflies blink." />
    <meta name="generator" content="tests/behaviour/demos/gallery-20-living-garden/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.45 0.75 1.0" />
    <Viewpoint DEF="View" description="Garden" position="0 5.2 10.5" orientation="1 0 0 -0.32" />
    <DirectionalLight DEF="Sun" direction="-0.4 -1 -0.5" intensity="1.0" color="1 0.97 0.9" />
    <Transform translation="0 10 -9"><Shape>{mat("0.45 0.75 1.0", "0.45 0.75 1.0", "", "SkyMat")}<Box size="70 50 0.2" /></Shape></Transform>
    <Transform translation="0 -0.1 0"><Shape>{mat("0.3 0.65 0.25", "0.3 0.65 0.25", 'roughness="0.9"', "GrassMat")}<Box size="24 0.2 14" /></Shape></Transform>
{chr(10).join(tufts)}
{chr(10).join(clouds)}
{chr(10).join(plants)}
{chr(10).join(bees)}
{chr(10).join(flies)}
{chr(10).join(ffs)}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
