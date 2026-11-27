# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-21-transforming-robot.x3d: a plain orange cube on a platform. Click it and a chain of six clocks
(isActive -> BooleanFilter.inputNegate -> TimeTrigger -> next clock) unfolds it: legs swing down and the body rises,
the front panels swing open into arms, the head extrudes, the antenna, eyes and chest lamp light, the robot waves,
then dances. Click again: one fold clock plays the first four stages backwards (a ScalarInterpolator 1 -> 0 feeds
the same interpolators). Hinges nest up to seven Transforms deep.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-21-transforming-robot.x3d")
PI = math.pi
body = []
DUR = {"U1": 2.2, "U2": 1.8, "U3": 1.2, "U4": 1.0, "U5": 2.4, "U6": 3.0, "F": 3.0}


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def shp(geom, base, em=None, extra=""):
    e = f' emissiveColor="{em}"' if em else ""
    return f'<Shape><Appearance><PhysicalMaterial baseColor="{base}"{e} {extra} /></Appearance>{geom}</Shape>'


def box(w, h, d, base, em=None, extra=""):
    return shp(f'<Box size="{f(w, h, d)}" />', base, em, extra)


def tf(name, tr=None, rot=None, sc=None, vis=None, inner=""):
    a = f' DEF="{name}"' if name else ""
    a += f' translation="{f(*tr)}"' if tr else ""
    a += f' rotation="{f(*rot)}"' if rot else ""
    a += f' scale="{f(*sc)}"' if sc else ""
    a += ' visible="false"' if vis is False else ""
    return f"<Transform{a}>{inner}</Transform>"


ease = lambda u: u * u * (3 - 2 * u)


def keys_for(n, delay=0.0):
    return [0.0] + [delay + (1 - delay) * k / n for k in range(1, n + 1)] if delay else [k / n for k in range(n + 1)]


def oi(name, axis, angles, src, target, rev=False, keys=None, delay=0.0):
    ks = keys or keys_for(len(angles) - 1, delay)
    if delay and not keys:
        angles = [angles[0]] + angles
        ks = [0.0] + [delay + (1 - delay) * k / (len(angles) - 2) for k in range(len(angles) - 1)]
    body.append(f'    <OrientationInterpolator DEF="{name}" key="{f(*ks)}" keyValue="{" ".join(f(*axis, a) for a in angles)}" />')
    route(src, "fraction_changed", name, "set_fraction")
    route(name, "value_changed", target, "rotation")
    if rev:
        route("Rev", "value_changed", name, "set_fraction")


def pi_(name, vecs, src, target, field, rev=False, keys=None):
    ks = keys or [k / (len(vecs) - 1) for k in range(len(vecs))]
    body.append(f'    <PositionInterpolator DEF="{name}" key="{f(*ks)}" keyValue="{" ".join(f(*v) for v in vecs)}" />')
    route(src, "fraction_changed", name, "set_fraction")
    route(name, "value_changed", target, field)
    if rev:
        route("Rev", "value_changed", name, "set_fraction")


def seq(name, keys, vals, src, target, rev=True):
    body.append(f'    <BooleanSequencer DEF="{name}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route(src, "fraction_changed", name, "set_fraction")
    route(name, "value_changed", target, "visible")
    if rev:
        route("Rev", "value_changed", name, "set_fraction")


def sweep(a0, a1, n=6):
    return [a0 + (a1 - a0) * ease(k / n) for k in range(n + 1)]


def wave_keys(n, amp, start=0.0, end=1.0):
    """zero at the ends, a swing of +-amp between: n half cycles"""
    ks = [0.0] + [start + (end - start) * (k + 0.5) / n for k in range(n)] + [1.0]
    vs = [0.0] + [amp * (1 if k % 2 == 0 else -1) for k in range(n)] + [0.0]
    return ks, vs


# -- the clocks: touch -> toggle -> filter -> GoUnfold / GoFold; U1..U6 chained by falling edges -------------
for n, d in DUR.items():
    body.append(f'    <TimeSensor DEF="{n}" cycleInterval="{d}" />')
for n in ("GoUnfold", "GoFold", "Go2", "Go3", "Go4", "Go5", "Go6"):
    body.append(f'    <TimeTrigger DEF="{n}" />')
for n in ("Press", "Dir", "Edge1", "Edge2", "Edge3", "Edge4", "Edge5"):
    body.append(f'    <BooleanFilter DEF="{n}" />')
body.append('    <BooleanToggle DEF="Flip" />')
route("Touch", "isActive", "Press", "set_boolean")
route("Press", "inputTrue", "Flip", "set_boolean")
route("Flip", "toggle_changed", "Dir", "set_boolean")
route("Dir", "inputTrue", "GoUnfold", "set_boolean")      # first click: true -> unfold
route("Dir", "inputNegate", "GoFold", "set_boolean")      # second click: false -> negated true -> fold
route("GoUnfold", "triggerTime", "U1", "startTime")
route("GoFold", "triggerTime", "F", "startTime")
for i in range(1, 6):
    route(f"U{i}", "isActive", f"Edge{i}", "set_boolean")
    route(f"Edge{i}", "inputNegate", f"Go{i + 1}", "set_boolean")
    route(f"Go{i + 1}", "triggerTime", f"U{i + 1}", "startTime")
body.append('    <ScalarInterpolator DEF="Rev" key="0 1" keyValue="1 0" />')
route("F", "fraction_changed", "Rev", "set_fraction")

# -- stage 1: legs swing down, the body rises ---------------------------------------------------------------
RISE = [(0, 0.8 + 1.6 * math.sin(PI * k / 16), 0) for k in range(9)]
pi_("Rise", RISE, "U1", "Body", "translation", rev=True)
legs = ""
for side, s in (("R", 1), ("L", -1)):
    oi(f"HipSwing{side}", (0, 0, s), sweep(PI, 0), "U1", f"Hip{side}", rev=True)
    oi(f"KneeSwing{side}", (0, 0, s), sweep(PI, 0), "U1", f"Knee{side}", rev=True)
    pi_(f"KneeSlide{side}", [(0, -0.8, 0.32 * (1 - ease(k / 6))) for k in range(7)], "U1", f"Knee{side}", "translation", rev=True)
    foot = tf(f"Ankle{side}", (0, -0.7, 0), None, None, None, tf(None, (0, -0.05, 0.1), None, None, None, box(0.36, 0.1, 0.5, "0.15 0.15 0.18")))
    shin = tf(f"Knee{side}", (0, -0.8, 0.32), (0, 0, s, PI), None, None,
              tf(None, (0, -0.35, 0), None, None, None, box(0.26, 0.7, 0.26, "0.3 0.4 0.62")) + foot)
    legs += tf(f"Hip{side}", (s * 1.0, -0.8, 0), (0, 0, s, PI), None, None,
               tf(None, (0, -0.4, 0), None, None, None, box(0.3, 0.8, 0.3, "0.4 0.52 0.75")) + shin)

# power studs round the platform light up one by one while the legs open
studs = ""
for i in range(8):
    a = 2 * PI * i / 8
    studs += tf(f"Stud{i}", (3.0 * math.cos(a), 0.45, 3.0 * math.sin(a)), None, None, False, shp('<Sphere radius="0.14" />', "0.2 1 0.9", "0.1 0.9 0.8"))
    seq(f"StudOn{i}", [0.0, max(0.02, i / 9), 1.0], ["false", "true", "true"], "U1", f"Stud{i}")

# -- stage 2: the front panels swing open into arms, the forearms unfold ---------------------------------------
arms = ""
for side, s in (("R", 1), ("L", -1)):
    oi(f"DoorSwing{side}", (0, s, 0), sweep(0, PI), "U2", f"ShoulderY{side}", rev=True)
    oi(f"ElbowSwing{side}", (0, 0, 1), sweep(PI, 0), "U2", f"Elbow{side}", rev=True, delay=0.35)
    pi_(f"ElbowSlide{side}", [(-s * 0.8, 0, 0.14 * (1 - ease(k / 6))) for k in range(7)], "U2", f"Elbow{side}", "translation", rev=True)
    hand = tf(f"Wrist{side}", (-s * 0.7, 0, 0), None, None, None,
              tf(None, (-s * 0.14, 0, 0), None, None, None, shp('<Sphere radius="0.18" />', "0.9 0.45 0.1")))
    fore = tf(f"Elbow{side}", (-s * 0.8, 0, 0.14), (0, 0, 1, PI), None, None,
              tf(None, (-s * 0.35, 0, 0), None, None, None, box(0.7, 0.5, 0.1, "0.4 0.52 0.75")) + hand)
    raised = tf(f"ShoulderZ{side}", None, None, None, None,
                tf(None, (-s * 0.4, 0, 0), None, None, None, box(0.8, 0.7, 0.12, "0.3 0.4 0.62")) + fore)
    arms += tf(f"ShoulderY{side}", (s * 0.8, 0.4, 0.88), None, None, None, raised)

# -- stage 3: the head extrudes (scale from a flat lid), sockets appear ---------------------------------------
pi_("HeadGrow", [(1, 0.1 + 0.9 * ease(k / 6), 1) for k in range(7)], "U3", "HeadRise", "scale", rev=True)
seq("SocketsOn", [0.0, 0.6, 1.0], ["false", "true", "true"], "U3", "Sockets")
seq("SocketsOnB", [0.0, 0.6, 1.0], ["false", "true", "true"], "U3", "SocketsB")

# -- stage 4: antenna rises, eyes and chest lamp light --------------------------------------------------------
oi("AntennaUp", (0, 0, 1), sweep(1.4, 0), "U4", "AntHinge", rev=True)
seq("AntennaOn", [0.0, 0.05, 1.0], ["false", "true", "true"], "U4", "AntHinge")
seq("EyesLit", [0.0, 0.3, 1.0], ["false", "true", "true"], "U4", "Eyes")
seq("ChestLit", [0.0, 0.6, 1.0], ["false", "true", "true"], "U4", "ChestLamp")
body.append('    <TimeSensor DEF="Pulse" cycleInterval="0.8" loop="true" enabled="false" />')
route("Flip", "toggle_changed", "Pulse", "enabled")
pi_("PulseScale", [(1, 1, 1), (1.6, 1.6, 1.6), (1, 1, 1)], "Pulse", "ChestLamp", "scale")

# -- stage 5: the right arm raises and the hand waves ---------------------------------------------------------
oi("WaveRaise", (0, 0, -1), [0, 1.4, 1.4, 0], "U5", "ShoulderZR", keys=[0, 0.18, 0.82, 1])
wk, wv = wave_keys(8, 0.6, 0.18, 0.82)
oi("WaveHand", (0, 0, 1), wv, "U5", "WristR", keys=wk)
wk2, wv2 = wave_keys(4, 0.08, 0.1, 0.9)
oi("WaveHead", (0, 1, 0), wv2, "U5", "HeadYaw", keys=wk2)

# -- stage 6: the dance: bounce, twist, arms flap alternately, head turns, a foot taps --------------------------
pi_("DanceBounce", [(0, 0.28 * (k % 2), 0) for k in range(17)], "U6", "Bounce", "translation")
twist = [0.0] + [0.5 * (1 if k % 2 == 0 else -1) for k in range(8)] + [0.0]
oi("DanceTwist", (0, 1, 0), twist, "U6", "Robot", keys=[0] + [(k + 0.5) / 8 for k in range(8)] + [1])
flapR = [0.0] + [1.0 * (k % 2) + 0.2 for k in range(8)] + [0.0]
flapL = [0.0] + [1.0 * ((k + 1) % 2) + 0.2 for k in range(8)] + [0.0]
fk = [0] + [(k + 0.5) / 8 for k in range(8)] + [1]
oi("FlapR", (0, 0, -1), flapR, "U6", "ShoulderZR", keys=fk)
oi("FlapL", (0, 0, 1), flapL, "U6", "ShoulderZL", keys=fk)
hk, hv = wave_keys(6, 0.6, 0.0, 1.0)
oi("DanceHead", (0, 1, 0), hv, "U6", "HeadYaw", keys=hk)
tk, tv = wave_keys(8, 0.5, 0.0, 1.0)
oi("FootTap", (1, 0, 0), [abs(v) for v in tv], "U6", "AnkleR", keys=tk)

# -- check the legs clear the platform while they swing (same maths as the interpolators) -----------------------
lo = 9.0
for k in range(0, 101):
    t = k / 100
    by = 0.8 + 1.6 * math.sin(PI * t / 2)                         # (the 9-key table is a close fit)
    a = PI * (1 - ease(t))
    ankle = (by - 0.8) - 0.8 * math.cos(a) - 0.7 * math.cos(2 * a)
    lo = min(lo, ankle)
assert lo > 0.04, f"a foot would dip into the platform: ankle height {lo:.3f}"

head = tf("HeadYaw", (0, 0.8, 0), None, None, None,
          tf("HeadRise", None, None, (1, 0.1, 1), None,
             tf(None, (0, 0.35, 0), None, None, None, box(0.9, 0.7, 0.8, "0.78 0.8 0.86", None, 'metallic="0.3" roughness="0.4"'))
             + tf("Sockets", (-0.2, 0.42, 0.41), None, None, False, box(0.24, 0.16, 0.04, "0.1 0.1 0.12"))
             + tf("SocketsB", (0.2, 0.42, 0.41), None, None, False, box(0.24, 0.16, 0.04, "0.1 0.1 0.12"))
             + tf("Eyes", None, None, None, False,
                  tf(None, (-0.2, 0.42, 0.44), None, None, None, shp('<Sphere radius="0.07" />', "0.3 0.95 1", "0.2 0.9 1"))
                  + tf(None, (0.2, 0.42, 0.44), None, None, None, shp('<Sphere radius="0.07" />', "0.3 0.95 1", "0.2 0.9 1")))
             + tf("AntHinge", (0.28, 0.7, 0), (0, 0, 1, 1.4), None, False,
                  tf(None, (0, 0.25, 0), None, None, None, shp('<Cylinder radius="0.035" height="0.5" />', "0.6 0.6 0.65"))
                  + tf(None, (0, 0.52, 0), None, None, None, shp('<Sphere radius="0.09" />', "1 0.2 0.2", "1 0.1 0.1")))))

torso = tf("Torso", None, None, None, None,
           box(1.6, 1.6, 1.6, "0.9 0.45 0.1", None, 'metallic="0.3" roughness="0.5"'))
chest = (tf(None, (0, -0.35, 0.82), (1, 0, 0, PI / 2), None, None, shp('<Cylinder radius="0.3" height="0.06" />', "0.15 0.15 0.18"))
         + tf("ChestLamp", (0, -0.35, 0.86), None, None, False, shp('<Sphere radius="0.17" />', "1 0.85 0.2", "1 0.75 0.1"))
         + tf(None, (-0.66, -0.66, 0.82), None, None, None, shp('<Sphere radius="0.07" />', "0.7 0.7 0.72"))
         + tf(None, (0.66, -0.66, 0.82), None, None, None, shp('<Sphere radius="0.07" />', "0.7 0.7 0.72")))
robot = tf("Robot", (0, 0.4, 0), None, None, None,
           tf("Bounce", None, None, None, None,
              tf("Body", (0, 0.8, 0), None, None, None, '<TouchSensor DEF="Touch" description="Click the robot: unfold or fold" />' + torso + chest + legs + arms + head)))

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 21: transforming robot" />
    <meta name="description" content="Click the orange cube: it unfolds panel by panel into a robot that waves and dances. Click again to fold it." />
    <meta name="generator" content="tests/behaviour/demos/gallery-21-transforming-robot/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.04 0.08 0.14" />
    <Viewpoint DEF="Cam" description="Platform" position="0 2.7 9.6" orientation="1 0 0 -0.05" />
    <DirectionalLight direction="-0.3 -0.6 -0.7" intensity="1.0" />
    <Transform translation="0 -0.1 0">{box(40, 0.2, 30, "0.1 0.12 0.15", None, 'roughness="0.9"')}</Transform>
    <Transform translation="0 0.2 0">{shp('<Cylinder radius="3.3" height="0.4" />', "0.25 0.28 0.33", None, 'metallic="0.6" roughness="0.4"')}</Transform>
    {studs}
    {robot}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT, "min ankle clearance %.2f" % lo)
