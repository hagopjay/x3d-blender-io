# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-24-marimba-balls.x3d: a marimba of 10 coloured bars played by falling balls. Each bar has a ball parked
on the rail above it. A song is a looping master TimeSensor plus one BooleanSequencer per ball whose true window releases
that ball (TimeTrigger -> fall clock). The fall clock's end (isActive false -> BooleanFilter.inputNegate -> TimeTrigger) is
the landing: it starts the bar's flash/dip clock and the ball's rebound clock. Three buttons pick the song (one master
clock enabled, the others disabled); a click on a bar starts its flash clock directly.   python build.py"""
import colorsys
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-24-marimba-balls.x3d")
N = 10                                         # bars
FALL, BOUNCE, BARLAP = 0.45, 1.5, 1.6          # seconds: ball fall, ball rebound and lift, bar flash
RAIL_Y, REST_Y = 6.24, 0.48                    # parked ball centre, ball centre resting on a bar
GAP = 1.15
XS = [(n - (N - 1) / 2) * GAP for n in range(N)]
LEN = [3.4 - 0.2 * n for n in range(N)]
COL = [colorsys.hsv_to_rgb(0.0 + 0.075 * n, 0.85, 1.0) for n in range(N)]

# songs: (bar, landing time in seconds from the song's start); a bar's ball needs about 2 s between its landings
S0 = [(i, 0.6 + 0.45 * i) for i in range(N)] + [(0, 6.5), (4, 6.5), (8, 6.5)]                      # climb, then a chord
ORDER1 = [5, 6, 4, 7, 3, 8, 2, 9, 1, 0]
S1, t = [], 0.6
for i, b in enumerate(ORDER1):                                                                     # zigzag, swung
    if i:
        t += 0.35 if i % 2 else 0.6
    S1.append((b, round(t, 2)))
ORDER2, GAPS2 = [0, 2, 4, 6, 8, 9, 7, 5, 3, 1], [0.9, 0.8, 0.7, 0.6, 0.5, 0.45, 0.4, 0.4, 0.4]
S2, t = [(0, 0.6)], 0.6
for b, g in zip(ORDER2[1:], GAPS2):                                                                # skips, accelerating
    t += g
    S2.append((b, round(t, 2)))
SONGS = [S0, S1, S2]
LAP = [round(max(tt for _, tt in s) + 2.0, 2) for s in SONGS]
BTN = [(-2.6, (1.0, 0.8, 0.2)), (0.0, (0.2, 0.9, 0.95)), (2.6, (0.95, 0.3, 0.8))]                  # song buttons

body = []


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def mat(name, rgb, extra=""):
    c = f(*rgb)
    return f'<PhysicalMaterial DEF="{name}" {extra} baseColor="{c}" emissiveColor="{c}" />'


def parab(u0, u1, y0, h, pts):
    """a hop from u0 to u1 off height y0, peak y0 + h, sampled at pts+1 keys"""
    out = []
    for i in range(pts + 1):
        s = i / pts
        out.append((round(u0 + (u1 - u0) * s, 4), y0 + h * (1 - (2 * s - 1) ** 2)))
    return out


# the ball's rebound: three hops, a rest, then it is lifted back to the rail
hops = parab(0.0, 0.2, REST_Y, 1.9, 4) + parab(0.2, 0.34, REST_Y, 0.8, 4)[1:] + parab(0.34, 0.44, REST_Y, 0.25, 2)[1:]
lift = []
for i in range(1, 5):
    s = i / 4
    lift.append((round(0.75 + 0.25 * s, 4), REST_Y + (RAIL_Y - REST_Y) * s * s * (3 - 2 * s)))
BOUNCE_KEYS = hops + [(0.75, REST_Y)] + lift
FALL_KEYS = [(round(i / 10, 2), REST_Y + (RAIL_Y - REST_Y) * (1 - (i / 10) ** 2)) for i in range(11)]


def tri(rgb):
    return " ".join(f(*c) for c in rgb)


bars = balls = ""
for n in range(N):
    x = XS[n]
    barmat = mat('Mat%d' % n, COL[n], 'roughness="0.35"')
    # the bar: a Transform that dips, a touch sensor, a box; its colour flashes. The ball shares the bar's appearance.
    bars += (f'    <Transform DEF="Bar{n}" translation="{f(x, 0.0, 0.0)}">\n'
             f'      <TouchSensor DEF="Touch{n}" description="Click: strike this bar" />\n'
             f'      <Shape><Appearance DEF="App{n}">{barmat}</Appearance>'
             f'<Box size="1 0.28 {f(LEN[n])}" /></Shape>\n'
             f'    </Transform>\n')
    balls += (f'    <Transform DEF="Ball{n}" translation="{f(x, RAIL_Y, 0.0)}"><Shape><Appearance USE="App{n}" />'
              f'<Sphere radius="0.34" /></Shape></Transform>\n')
    ks = [k for k, _ in FALL_KEYS]
    body.append(f'    <TimeTrigger DEF="Rel{n}" />')
    body.append(f'    <TimeSensor DEF="FallClk{n}" cycleInterval="{FALL}" />')
    body.append(f'    <PositionInterpolator DEF="FallIp{n}" key="{f(*ks)}" keyValue="{" ".join(f(x, y, 0.0) for _, y in FALL_KEYS)}" />')
    body.append(f'    <BooleanFilter DEF="Land{n}" />')
    body.append(f'    <TimeTrigger DEF="Hit{n}" />')
    body.append(f'    <TimeSensor DEF="BounceClk{n}" cycleInterval="{BOUNCE}" />')
    body.append(f'    <PositionInterpolator DEF="BounceIp{n}" key="{f(*[k for k, _ in BOUNCE_KEYS])}" '
                f'keyValue="{" ".join(f(x, y, 0.0) for _, y in BOUNCE_KEYS)}" />')
    body.append(f'    <TimeSensor DEF="BarClk{n}" cycleInterval="{BARLAP}" />')
    body.append(f'    <PositionInterpolator DEF="BarDip{n}" key="0 0.06 0.5 0.8 1" keyValue="{" ".join(f(x, y, 0.0) for y in (0.0, -0.22, -0.15, 0.05, 0.0))}" />')
    body.append(f'    <ColorInterpolator DEF="BarGlow{n}" key="0 0.1 1" keyValue="{tri([COL[n], (1.0, 1.0, 1.0), COL[n]])}" />')
    route(f"Rel{n}", "triggerTime", f"FallClk{n}", "startTime")
    route(f"FallClk{n}", "fraction_changed", f"FallIp{n}", "set_fraction")
    route(f"FallIp{n}", "value_changed", f"Ball{n}", "translation")
    route(f"FallClk{n}", "isActive", f"Land{n}", "set_boolean")
    route(f"Land{n}", "inputNegate", f"Hit{n}", "set_boolean")
    route(f"Hit{n}", "triggerTime", f"BarClk{n}", "startTime")
    route(f"Hit{n}", "triggerTime", f"BounceClk{n}", "startTime")
    route(f"BounceClk{n}", "fraction_changed", f"BounceIp{n}", "set_fraction")
    route(f"BounceIp{n}", "value_changed", f"Ball{n}", "translation")
    route(f"Touch{n}", "touchTime", f"BarClk{n}", "startTime")
    route(f"BarClk{n}", "fraction_changed", f"BarDip{n}", "set_fraction")
    route(f"BarClk{n}", "fraction_changed", f"BarGlow{n}", "set_fraction")
    route(f"BarDip{n}", "value_changed", f"Bar{n}", "translation")
    route(f"BarGlow{n}", "value_changed", f"Mat{n}", "baseColor")
    route(f"BarGlow{n}", "value_changed", f"Mat{n}", "emissiveColor")

# songs: a master clock and one sequencer per ball it uses
for s, song in enumerate(SONGS):
    on = "true" if s == 0 else "false"
    body.append(f'    <TimeSensor DEF="Song{s}" cycleInterval="{LAP[s]}" loop="true" enabled="{on}" />')
    by_bar = {}
    for b, tt in song:
        by_bar.setdefault(b, []).append(tt)
    for b, times in sorted(by_bar.items()):
        # true from the release time until just before this ball's next release (or the lap's end), so a late player step
        # cannot skip a note: the sequencer still sends true when the clock jumps past the window
        keys, vals = [0.0], ["false"]
        for i, tt in enumerate(times):
            keys.append(round((tt - FALL) / LAP[s], 5))
            vals.append("true")
            if i + 1 < len(times):
                keys.append(round((times[i + 1] - FALL - 0.3) / LAP[s], 5))
                vals.append("false")
        keys.append(1.0)
        vals.append("true")
        body.append(f'    <BooleanSequencer DEF="Drop{s}_{b}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
        route(f"Song{s}", "fraction_changed", f"Drop{s}_{b}", "set_fraction")
        route(f"Drop{s}_{b}", "value_changed", f"Rel{b}", "set_boolean")

# song buttons: press -> restart that song's clock (startTime first, then enabled one hop later), light its lamp, switch the others off
btns = ""
for s, (bx, rgb) in enumerate(BTN):
    btnmat = mat('BtnMat%d' % s, rgb, 'roughness="0.4"')
    lampon = 'true' if s == 0 else 'false'
    btns += (f'    <Transform DEF="Btn{s}" translation="{f(bx, -0.86, 2.7)}">\n'
             f'      <TouchSensor DEF="Pick{s}" description="Click: play song {s + 1}" />\n'
             f'      <Shape><Appearance DEF="BtnApp{s}">{btnmat}</Appearance><Cylinder radius="0.62" height="0.26" /></Shape>\n'
             f'    </Transform>\n'
             f'    <Transform DEF="Lamp{s}" translation="{f(bx, -0.45, 2.7)}" visible="{lampon}">'
             f'<Shape><Appearance><PhysicalMaterial baseColor="1 1 1" emissiveColor="1 1 1" /></Appearance><Sphere radius="0.3" /></Shape></Transform>\n')
    body.append(f'    <BooleanFilter DEF="Press{s}" />')
    body.append(f'    <BooleanFilter DEF="Off{s}" />')
    body.append(f'    <TimeTrigger DEF="Restart{s}" />')
    route(f"Pick{s}", "isActive", f"Press{s}", "set_boolean")
    route(f"Press{s}", "inputTrue", f"Restart{s}", "set_boolean")
    route(f"Restart{s}", "triggerTime", f"Song{s}", "startTime")
    body.append(f'    <BooleanFilter DEF="Go{s}" />')                   # one hop later than Restart, so startTime lands first
    route(f"Press{s}", "inputTrue", f"Go{s}", "set_boolean")
    route(f"Go{s}", "inputTrue", f"Song{s}", "enabled")
    route(f"Press{s}", "inputTrue", f"Lamp{s}", "visible")
    route(f"Press{s}", "inputTrue", f"Off{s}", "set_boolean")
    for t_ in range(3):
        if t_ != s:
            route(f"Off{s}", "inputNegate", f"Song{t_}", "enabled")
            route(f"Off{s}", "inputNegate", f"Lamp{t_}", "visible")

# the frame: a rail overhead on two posts, a base under the bars, a dark floor
wood = '<Appearance DEF="Wood"><PhysicalMaterial baseColor="0.35 0.2 0.1" emissiveColor="0.12 0.07 0.04" roughness="0.7" /></Appearance>'
span = XS[-1] - XS[0] + 1.6
frame = (f'    <Transform DEF="Rail" translation="0 5.8 0"><Shape>{wood}<Box size="{f(span)} 0.2 0.7" /></Shape></Transform>\n'
         f'    <Transform DEF="PostL" translation="{f(-span / 2 + 0.2, 2.6, -0.5)}"><Shape><Appearance USE="Wood" /><Cylinder radius="0.12" height="6.4" /></Shape></Transform>\n'
         f'    <Transform DEF="PostR" translation="{f(span / 2 - 0.2, 2.6, -0.5)}"><Shape><Appearance USE="Wood" /><Cylinder radius="0.12" height="6.4" /></Shape></Transform>\n'
         f'    <Transform DEF="Base" translation="0 -0.3 0"><Shape><Appearance USE="Wood" /><Box size="{f(span)} 0.18 1.3" /></Shape></Transform>\n'
         f'    <Transform DEF="Floor" translation="0 -1.1 0"><Shape><Appearance><PhysicalMaterial baseColor="0.07 0.06 0.12" emissiveColor="0.03 0.025 0.06" /></Appearance><Box size="30 0.2 14" /></Shape></Transform>\n')

NL = chr(10)
SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 24: marimba played by falling balls" />
    <meta name="description" content="Ten coloured bars; balls drop from a rail and bounce on them to play a song. Three buttons pick the song; a click on a bar strikes it." />
    <meta name="generator" content="tests/behaviour/demos/gallery-24-marimba-balls/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.03 0.02 0.09" />
    <Viewpoint DEF="View" description="Facing the marimba" position="0 4.5 12" orientation="1 0 0 -0.2" />
    <DirectionalLight direction="0 -1 -0.5" intensity="1.0" />
{bars}{balls}{btns}{frame}
{NL.join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT, "laps", LAP)
