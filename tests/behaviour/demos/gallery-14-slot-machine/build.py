# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-14-slot-machine.x3d: pull the lever (TouchSensor). Three reels spin and slow down one after another
(each of 6 symbols per reel is shown by its own BooleanSequencer, with gaps that grow: the reel decelerates) and all stop on
the red 7; then a jackpot: the sign pulses, 12 lamps flash, fourteen coins fly from the tray. Fully deterministic: it is a toy
that always pays out.   python build.py"""
import math
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-14-slot-machine.x3d")
SPIN, WIN = 4.0, 3.0
STOPS = (2.0, 3.0, 4.0)                # when each reel has stopped (seconds into the spin)
STEPS = (14, 17, 20)                   # symbol changes before each reel stops
body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(base, emissive=None, extra=""):
    em = f' emissiveColor="{emissive}"' if emissive else ""
    return f'<Appearance><PhysicalMaterial baseColor="{base}"{em} {extra} /></Appearance>'


# -- the chain: lever -> Spin -> Jackpot --------------------------------------------------------------------
body.append(f'    <TimeSensor DEF="Spin" cycleInterval="{SPIN}" />')
body.append(f'    <TimeSensor DEF="Win" cycleInterval="{WIN}" />')
body.append('    <TimeSensor DEF="Pull" cycleInterval="0.7" />')
body.append('    <BooleanFilter DEF="Press" />')
body.append('    <BooleanFilter DEF="SpinDone" />')
body.extend(f'    <TimeTrigger DEF="{n}" />' for n in ("GoSpin", "GoWin"))
route("LeverTouch", "isActive", "Press", "set_boolean")
route("Press", "inputTrue", "GoSpin", "set_boolean")
route("GoSpin", "triggerTime", "Spin", "startTime")
route("GoSpin", "triggerTime", "Pull", "startTime")
route("Spin", "isActive", "SpinDone", "set_boolean")
route("SpinDone", "inputNegate", "GoWin", "set_boolean")
route("GoWin", "triggerTime", "Win", "startTime")

# -- symbols: 0 = red seven (the jackpot), 1 cherry, 2 lemon, 3 bell, 4 star, 5 bar ---------------------------
SYMS = [
    ('<Shape>{p0}<Box size="0.55 0.8 0.15" /></Shape>', "0.9 0.1 0.1", "0.6 0.0 0.0"),
    ('<Shape>{p}<Sphere radius="0.28" /></Shape>', "0.85 0.05 0.2", None),
    ('<Transform scale="1.3 0.8 1"><Shape>{p}<Sphere radius="0.3" /></Shape></Transform>', "1 0.9 0.1", None),
    ('<Shape>{p}<Cone bottomRadius="0.3" height="0.6" /></Shape>', "0.95 0.7 0.1", "0.3 0.2 0.0"),
    ('<Transform rotation="0 0 1 0.785"><Shape>{p}<Box size="0.45 0.45 0.12" /></Shape></Transform>', "0.9 0.9 0.3", "0.4 0.4 0.0"),
    ('<Shape>{p}<Box size="0.8 0.25 0.12" /></Shape>', "0.15 0.15 0.18", None),
]
reels = ""
for r in range(3):
    x = -1.3 + 1.3 * r
    t_stop, n = STOPS[r], STEPS[r]
    # change times t_stop * (j/n)^2: the gaps grow, so the reel slows down, ending at t_stop (as fractions of the spin)
    times = [t_stop / SPIN * (j / n) ** 2 for j in range(n + 1)]
    off = (-n) % 6                                  # symbol(j) = (j + off) mod 6, so the last step shows symbol 0
    reels += f'    <Transform translation="{x} 2.3 0.65">\n'
    for s in range(6):
        geom, base, em = SYMS[s]
        shape = geom.replace("{p0}", paint(base, em)).replace("{p}", paint(base, em))
        reels += f'      <Transform DEF="Sym{r}{s}" visible="false">{shape}</Transform>\n'
        # the symbol is on from its step's time until the next step; build keys/values
        keys, vals, state = [0.0], ["false"], False
        for j in range(n + 1):
            on = ((j + off) % 6) == s
            if on != state:
                keys.append(round(times[j], 4)); vals.append("true" if on else "false"); state = on
        if keys[-1] < 1.0:
            keys.append(1.0); vals.append(vals[-1])
        # drop duplicate keys (rounded equal times)
        ck, cv = [], []
        for k, v in zip(keys, vals):
            if ck and k <= ck[-1]:
                cv[-1] = v
            else:
                ck.append(k); cv.append(v)
        body.append(f'    <BooleanSequencer DEF="Show{r}{s}" key="{f(*ck)}" keyValue="{" ".join(cv)}" />')
        route("Spin", "fraction_changed", f"Show{r}{s}", "set_fraction")
        route(f"Show{r}{s}", "value_changed", f"Sym{r}{s}", "visible")
    reels += "    </Transform>\n"

# -- the cabinet, the lever, lamps, sign, coins --------------------------------------------------------------
cabinet = f'''    <Transform translation="0 1.8 0">
      <Shape>{paint("0.55 0.1 0.15", None, 'metallic="0.3" roughness="0.4"')}<Box size="5.2 4.2 1.0" /></Shape>
    </Transform>
    <Transform translation="0 2.3 0.52"><Shape>{paint("0.9 0.9 0.85")}<Box size="4.2 1.2 0.1" /></Shape></Transform>
    <Transform translation="0 0.35 0.5"><Shape>{paint("0.3 0.3 0.34", None, 'metallic="1"')}<Box size="2.4 0.5 0.8" /></Shape></Transform>
    <Transform DEF="Sign" translation="0 4.3 0.1"><Shape>{paint("1 0.8 0.2", "0.4 0.3 0.0", 'DEF="SignPaint"')}<Box size="3.6 0.7 0.3" /></Shape></Transform>
    <Transform translation="2.9 2.4 0"><Shape>{paint("0.6 0.6 0.65", None, 'metallic="1"')}<Cylinder radius="0.12" height="0.6" /></Shape>
      <Transform DEF="Lever" translation="0 0.3 0">
        <TouchSensor DEF="LeverTouch" description="Pull the lever" />
        <Transform translation="0 0.8 0"><Shape>{paint("0.8 0.8 0.85", None, 'metallic="1"')}<Cylinder radius="0.07" height="1.6" /></Shape></Transform>
        <Transform translation="0 1.7 0"><Shape>{paint("0.9 0.1 0.1", "0.4 0.0 0.0")}<Sphere radius="0.28" /></Shape></Transform>
      </Transform></Transform>'''
body.append('    <OrientationInterpolator DEF="PullDown" key="0 0.4 1" keyValue="0 0 1 0 0 0 1 -1.3 0 0 1 0" />')
route("Pull", "fraction_changed", "PullDown", "set_fraction")
route("PullDown", "value_changed", "Lever", "rotation")

lamps = ""
for i in range(12):
    a = 2 * math.pi * i / 12
    lamps += f'<Transform DEF="Lamp{i}" translation="{2.3 * math.cos(a) * 1.05:.2f} {1.8 + 2.0 * math.sin(a):.2f} 0.58" visible="false"><Shape>{paint("1 0.9 0.4", "1 0.8 0.2")}<Sphere radius="0.13" /></Shape></Transform>'
    # chase during the spin (4 laps), flash all together in the win
    ks, vs = [0.0], ["false"]
    for lap in range(4):
        s = lap / 4 + i / 12 / 4
        ks += [round(s, 4), round(s + 0.03, 4)]; vs += ["true", "false"]
    ks.append(1.0); vs.append("false")
    body.append(f'    <BooleanSequencer DEF="Chase{i}" key="{f(*ks)}" keyValue="{" ".join(vs)}" />')
    route("Spin", "fraction_changed", f"Chase{i}", "set_fraction")
    route(f"Chase{i}", "value_changed", f"Lamp{i}", "visible")
    body.append(f'    <BooleanSequencer DEF="Flash{i}" key="0 0.1 0.2 0.3 0.4 0.5 0.6 0.7 0.8 0.9 1" keyValue="true false true false true false true false true false false" />')
    route("Win", "fraction_changed", f"Flash{i}", "set_fraction")
    route(f"Flash{i}", "value_changed", f"Lamp{i}", "visible")
body.append('    <ColorInterpolator DEF="SignGlow" key="0 0.2 0.4 0.6 0.8 1" keyValue="0.4 0.3 0 1 0.8 0.1 0.4 0.3 0 1 0.2 0.2 1 0.8 0.1 0.4 0.3 0" />')
route("Win", "fraction_changed", "SignGlow", "set_fraction")
route("SignGlow", "value_changed", "SignPaint", "emissiveColor")
route("SignGlow", "value_changed", "SignPaint", "baseColor")

coins = ""
gold = paint("1 0.85 0.2", "0.5 0.4 0.0", 'metallic="1"')
for c in range(14):
    vx = -2.4 + 5.0 * (c / 13)
    s0 = 0.04 * c
    coins += f'<Transform DEF="Coin{c}" translation="0 0.7 1.0" rotation="1 0 0 1.5708" visible="false"><Shape>{gold}<Cylinder radius="0.2" height="0.05" /></Shape></Transform>'
    # a fountain arc from the tray: up, over, down onto the floor
    pts = [(0.0, 0.7, 1.0), (vx * 0.35, 3.0, 1.6), (vx * 0.7, 3.6, 2.3), (vx, 0.15, 3.0)]
    ks = [0.0, s0 + 0.12, s0 + 0.35, 0.99 if s0 + 0.55 > 0.99 else s0 + 0.55]
    ks = sorted(set(round(min(k, 0.99), 3) for k in ks))
    while len(ks) < 4:
        ks.append(round(ks[-1] + 0.001, 3))
    body.append(f'    <PositionInterpolator DEF="Fly{c}" key="{f(*ks)}" keyValue="{" ".join(f(*q) for q in pts)}" />')
    route("Win", "fraction_changed", f"Fly{c}", "set_fraction")
    route(f"Fly{c}", "value_changed", f"Coin{c}", "translation")
    route("Win", "isActive", f"Coin{c}", "visible")

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 14: slot machine" />
    <meta name="description" content="Pull the lever: three decelerating reels, a jackpot of flashing lamps and flying coins." />
    <meta name="generator" content="tests/behaviour/demos/gallery-14-slot-machine/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.04 0.02 0.08" />
    <Viewpoint DEF="View" description="Front" position="0 2.6 11" orientation="1 0 0 -0.08" />
    <DirectionalLight direction="-0.2 -0.4 -1" intensity="1.0" />
    <PointLight location="0 3 5" color="1 0.9 0.8" intensity="80" radius="20" />
    <Transform translation="0 -0.1 0"><Shape>{paint("0.12 0.1 0.15", None, 'roughness="0.9"')}<Box size="20 0.2 12" /></Shape></Transform>
{cabinet}
{reels}
    {lamps}
    {coins}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
