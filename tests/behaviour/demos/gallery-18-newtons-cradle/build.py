# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-18-newtons-cradle.x3d: a Newton's cradle of six balls whose physics is faked by interpolator curves.
Click ball i to choose the outcome: balls 0, 1, 2 lift 1, 2, 3 balls from the left end; balls 5, 4, 3 lift 1, 2, 3 from the
right end. The lifted balls fall, the far end kicks out the same number, they swing back, the first end kicks out again
(smaller), and so on, over an 8 s run that then settles. Six clocks (one per choice) lock each other out while one runs.
python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-18-newtons-cradle.x3d")
RUN = 8.0                       # seconds per run
AMP = 0.58                      # lift angle in radians
N = 6                           # balls
SPACING, PIVOT_Y, DROP = 1.0, 4.1, 3.0
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


def bx(i):
    return (i - (N - 1) / 2) * SPACING


# choices: (name, side of the lifted group, k balls lifted, ball you click)
CHOICES = [("L1", "L", 1, 0), ("L2", "L", 2, 1), ("L3", "L", 3, 2), ("R3", "R", 3, 3), ("R2", "R", 2, 4), ("R1", "R", 1, 5)]


def swing(t0, t1, amp):
    """Pendulum quarter-swings: out over [t0, mid], back over [mid, t1], sampled every 0.25 s; returns [(t, angle)]."""
    mid, pts, t = (t0 + t1) / 2, [], t0
    while t <= t1 + 1e-9:
        u = (t - t0) / (mid - t0) if t <= mid else (t1 - t) / (t1 - mid)
        pts.append((t, amp * math.sin(math.pi / 2 * u) if t <= mid else amp * math.sin(math.pi / 2 * u)))
        t += 0.25
    return pts


def curve(lifted):
    """Angle samples (sign applied later) for a lifted group (lift 0-1 s, fall 1-2 s, 4-6 s echo) or a kicked group (2-4, 6-8)."""
    if lifted:
        up = [(0.25 * j, AMP * math.sin(math.pi / 2 * (0.25 * j))) for j in range(5)]            # 0..1 s: rise
        down = [(1.0 + 0.25 * j, AMP * math.cos(math.pi / 2 * (0.25 * j))) for j in range(1, 5)]   # 1..2 s: fall onto the stack
        echo = swing(4.0, 6.0, AMP * 0.55)
        return up + down + echo + [(8.0, 0.0)]
    first, second = swing(2.0, 4.0, AMP), swing(6.0, 8.0, AMP * 0.3)
    return [(0.0, 0.0)] + first + second


def oi(name, pts, sign):
    ks, vs, last = [], [], None
    for t, a in pts:
        if last is not None and t <= last + 1e-9:
            continue                                        # duplicate time (e.g. 2.0 appears in two segments)
        ks.append(round(t / RUN, 4))
        vs.append(f"0 0 1 {sign * a:.4f}")
        last = t
    body.append(f'    <OrientationInterpolator DEF="{name}" key="{f(*ks)}" keyValue="{" ".join(vs)}" />')


def seq(name, hits):
    ks, vs = [0.0], ["false"]
    for h in hits:
        ks += [round(h / RUN, 4), round((h + 0.4) / RUN, 4)]
        vs += ["true", "false"]
    ks.append(1.0); vs.append("false")
    body.append(f'    <BooleanSequencer DEF="{name}" key="{f(*ks)}" keyValue="{" ".join(vs)}" />')


# -- clocks, press chain, lock -------------------------------------------------------------------------------
body.append('    <BooleanToggle DEF="Round" />')
body.append('    <BooleanFilter DEF="RoundF" />')
for c, side, k, ball in CHOICES:
    body.append(f'    <TimeSensor DEF="Run{c}" cycleInterval="{RUN}" />')
    body.append(f'    <BooleanFilter DEF="Press{c}" />')
    body.append(f'    <TimeTrigger DEF="Go{c}" />')
    body.append(f'    <BooleanFilter DEF="Busy{c}" />')
    route(f"Touch{ball}", "isActive", f"Press{c}", "set_boolean")
    route(f"Press{c}", "inputTrue", f"Go{c}", "set_boolean")
    route(f"Go{c}", "triggerTime", f"Run{c}", "startTime")
    route(f"Run{c}", "isActive", f"Busy{c}", "set_boolean")
    route(f"Busy{c}", "inputTrue", "Round", "set_boolean")                 # each run flips the round lamps
    route(f"Busy{c}", "inputNegate", "Ready", "visible")                   # ready lamp: dark while a run is going
    route(f"Run{c}", "isActive", f"Chosen{ball}", "visible")               # the lamp under the clicked ball
    for c2, *_ in CHOICES:
        if c2 != c:
            route(f"Busy{c}", "inputNegate", f"Run{c2}", "enabled")        # lock: the other clocks are off while this runs
route("Round", "toggle", "RoundA", "visible")
route("Round", "toggle", "RoundF", "set_boolean")
route("RoundF", "inputNegate", "RoundB", "visible")

# -- the curves --------------------------------------------------------------------------------------------------
for c, side, k, ball in CHOICES:
    lift = list(range(k)) if side == "L" else list(range(N - k, N))
    kick = list(range(N - k, N)) if side == "L" else list(range(k))
    s_lift = -1 if side == "L" else 1
    oi(f"Lift{c}", curve(True), s_lift)
    oi(f"Kick{c}", curve(False), -s_lift)
    route(f"Run{c}", "fraction_changed", f"Lift{c}", "set_fraction")
    route(f"Run{c}", "fraction_changed", f"Kick{c}", "set_fraction")
    for i in lift:
        route(f"Lift{c}", "value_changed", f"Pivot{i}", "rotation")
    for i in kick:
        route(f"Kick{c}", "value_changed", f"Pivot{i}", "rotation")
    # sparks at the impacts: t=2 and 6 where the lifted group meets the stack, t=4 where the kicked group returns
    gap_l, gap_r = (k - 1, N - 1 - k) if side == "L" else (N - 1 - k, k - 1)
    gap_lift_side, gap_kick_side = gap_l, gap_r
    if gap_lift_side == gap_kick_side:
        seq(f"Spark{c}a", [2.0, 4.0, 6.0])
        route(f"Run{c}", "fraction_changed", f"Spark{c}a", "set_fraction")
        route(f"Spark{c}a", "value_changed", f"Gap{gap_lift_side}", "visible")
    else:
        seq(f"Spark{c}a", [2.0, 6.0])
        seq(f"Spark{c}b", [4.0])
        route(f"Run{c}", "fraction_changed", f"Spark{c}a", "set_fraction")
        route(f"Run{c}", "fraction_changed", f"Spark{c}b", "set_fraction")
        route(f"Spark{c}a", "value_changed", f"Gap{gap_lift_side}", "visible")
        route(f"Spark{c}b", "value_changed", f"Gap{gap_kick_side}", "visible")

# -- the cradle ---------------------------------------------------------------------------------------------------
BALLS = ["0.9 0.2 0.15", "0.95 0.55 0.1", "0.95 0.85 0.2", "0.3 0.75 0.3", "0.15 0.65 0.8", "0.3 0.35 0.9"]
steel = paint("0.62 0.63 0.68", None, 'metallic="1" roughness="0.3"')
wood = paint("0.45 0.28 0.14", None, 'roughness="0.8"')
phi = math.atan2(0.8, DROP - 0.5)
slen = math.hypot(0.8, DROP - 0.5)
pivots = ""
for i in range(N):
    col = BALLS[i]
    glow = " ".join(f"{float(v) * 0.35:.2f}" for v in col.split())
    strings = "".join(
        f'<Transform translation="0 {-(DROP - 0.5) / 2:.3f} {z * 0.4:.2f}" rotation="1 0 0 {z * phi:.4f}"><Shape>{paint("0.85 0.85 0.8")}<Cylinder radius="0.02" height="{slen:.3f}" /></Shape></Transform>'
        for z in (1, -1))
    pivots += f'''    <Transform DEF="Pivot{i}" translation="{bx(i):.2f} {PIVOT_Y} 0">
      {strings}
      <Transform DEF="Ball{i}" translation="0 {-DROP} 0">
        <TouchSensor DEF="Touch{i}" description="Click to lift {[k for c, s, k, b in CHOICES if b == i][0]} from the {'left' if i < 3 else 'right'}" />
        <Shape>{paint(col, glow, 'metallic="0.6" roughness="0.25"')}<Sphere radius="0.5" /></Shape>
      </Transform>
    </Transform>
'''
frame = f'''    <Transform translation="0 -0.15 0"><Shape>{wood}<Box size="10.6 0.3 3.0" /></Shape></Transform>
    <Transform translation="0 {PIVOT_Y + 0.15} 0"><Shape>{wood}<Box size="10.0 0.3 0.3" /></Shape></Transform>
    <Transform translation="0 {PIVOT_Y + 0.15} 0.9"><Shape>{wood}<Box size="10.0 0.2 0.2" /></Shape></Transform>
    <Transform translation="0 {PIVOT_Y + 0.15} -0.9"><Shape>{wood}<Box size="10.0 0.2 0.2" /></Shape></Transform>
'''
for x in (-4.9, 4.9):
    for z in (-0.9, 0.9):
        frame += f'    <Transform translation="{x} {(PIVOT_Y + 0.15) / 2:.2f} {z}"><Shape>{wood}<Cylinder radius="0.12" height="{PIVOT_Y + 0.3:.2f}" /></Shape></Transform>\n'

# pips on the front of the base (how many balls that click lifts) and the lamp that lights under the clicked ball
pips, lamps = "", ""
for c, side, k, ball in CHOICES:
    for p in range(k):
        px = bx(ball) + (p - (k - 1) / 2) * 0.24
        pips += f'    <Transform translation="{px:.2f} 0.02 1.25"><Shape>{paint("0.95 0.95 0.9", "0.3 0.3 0.3")}<Cylinder radius="0.08" height="0.04" /></Shape></Transform>\n'
    lamps += f'    <Transform DEF="Chosen{ball}" translation="{bx(ball):.2f} 0.03 0.7" visible="false"><Shape>{paint("1 0.9 0.2", "1 0.8 0.1")}<Cylinder radius="0.38" height="0.04" /></Shape></Transform>\n'
sparks = ""
for g in range(N - 1):
    gx = (bx(g) + bx(g + 1)) / 2
    sparks += f'    <Transform DEF="Gap{g}" translation="{gx:.2f} {PIVOT_Y - DROP:.2f} 0.55" visible="false"><Shape>{paint("1 0.95 0.5", "1 0.9 0.3")}<Sphere radius="0.22" /></Shape></Transform>\n'
panel = f'''    <Transform DEF="Ready" translation="-3.6 0.05 1.25"><Shape>{paint("0.2 0.9 0.3", "0.1 0.7 0.2")}<Cylinder radius="0.18" height="0.05" /></Shape></Transform>
    <Transform DEF="RoundA" translation="3.3 0.05 1.25" visible="false"><Shape>{paint("0.9 0.4 0.9", "0.6 0.2 0.6")}<Cylinder radius="0.14" height="0.05" /></Shape></Transform>
    <Transform DEF="RoundB" translation="3.8 0.05 1.25"><Shape>{paint("0.4 0.7 0.95", "0.2 0.4 0.6")}<Cylinder radius="0.14" height="0.05" /></Shape></Transform>
'''

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 18: Newton's cradle" />
    <meta name="description" content="Click a ball to choose how many lift: the far end kicks out as many. Physics faked by keyframes." />
    <meta name="generator" content="tests/behaviour/demos/gallery-18-newtons-cradle/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.05 0.06 0.1" />
    <Viewpoint DEF="View" description="Front" position="0 2.6 11.5" orientation="1 0 0 -0.06" />
    <DirectionalLight direction="-0.3 -0.5 -1" intensity="1.0" />
    <PointLight location="0 5 6" color="1 0.95 0.9" intensity="90" radius="25" />
    <Transform translation="0 -0.4 0"><Shape>{paint("0.14 0.15 0.2", None, 'roughness="0.9"')}<Box size="30 0.2 14" /></Shape></Transform>
{frame}{pivots}{pips}{lamps}{sparks}{panel}{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
