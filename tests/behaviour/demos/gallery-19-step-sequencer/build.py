# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes gallery-19-step-sequencer.x3d: a 4 x 8 visual step sequencer / light organ.
Each of the 32 pads has its own TouchSensor -> BooleanFilter -> BooleanToggle. The toggle's output fans out to the pad's lit
cap (visible), the pad's voice (visible) and the pad's own looping TimeSensor (enabled), so only lit pads pulse their row's
instrument, each with its own phase. A 4 s playhead TimeSensor drives 8 BooleanSequencers (one per column) whose output
fans out to the column's glow bar and to the four pads' flash plates in that column. There is no AND of "pad lit" and
"playhead here" (X3D has none): the playhead is a staged sweep, the gating by pad is real.   python build.py"""
import pathlib

OUT = pathlib.Path(__file__).with_name("gallery-19-step-sequencer.x3d")
ROWS, COLS, GAP = 4, 8, 1.5
BEAT = 4.0                                   # playhead lap, seconds (0.5 s per column)
PULSE = 1.0                                  # each lit pad's own clock lap
K = 8
body = []
PATTERN = ["10001001", "00100010", "11010100", "00010001"]
ROWCOL = [(0.2, 0.7, 1.0), (1.0, 0.35, 0.65), (0.4, 1.0, 0.4), (1.0, 0.75, 0.15)]       # row colours: ball, disc, bar, cone


def f(*v):
    return " ".join(("%.4f" % x).rstrip("0").rstrip(".") if isinstance(x, float) else str(x) for x in v)


def route(a, af, b, bf):
    body.append(f'    <ROUTE fromNode="{a}" fromField="{af}" toNode="{b}" toField="{bf}" />')


def paint(rgb, extra=""):
    c = f(*rgb)
    return f'<Appearance><PhysicalMaterial {extra} baseColor="{c}" emissiveColor="{c}" /></Appearance>'


def tri(t):                                   # 0 -> 1 -> 0 over one cycle
    return 1 - abs(2 * t - 1)


ks = [k / K for k in range(K + 1)]
x0, z0 = -(COLS - 1) * GAP / 2, -(ROWS - 1) * GAP / 2
pads = ""
for r in range(ROWS):
    for c in range(COLS):
        on = PATTERN[r][c] == "1"
        vis = "true" if on else "false"
        x, z = x0 + c * GAP, z0 + r * GAP
        p = f"{r}_{c}"
        ph = c / COLS                         # this pad's phase within its row's pulse
        rc = ROWCOL[r]
        dim = tuple(0.12 + 0.1 * v for v in rc)
        # the voice: a different instrument per row
        if r == 0:                            # bouncing ball: translation y
            hs = [0.35 + 1.1 * (1 - (2 * ((k / K + ph) % 1.0) - 1) ** 2) for k in range(K + 1)]
            ip = f'<PositionInterpolator DEF="Ip{p}" key="{f(*ks)}" keyValue="{" ".join(f(0, h, 0) for h in hs)}" />'
            voice = f'<Transform DEF="Voice{p}" translation="0 0.35 0" visible="{vis}"><Shape>{paint(rc)}<Sphere radius="0.24" /></Shape></Transform>'
            tgt = "translation"
        elif r == 1:                          # flashing disc: scale
            ss = [0.25 + 1.0 * tri((k / K + ph) % 1.0) for k in range(K + 1)]
            ip = f'<PositionInterpolator DEF="Ip{p}" key="{f(*ks)}" keyValue="{" ".join(f(s, 1, s) for s in ss)}" />'
            voice = f'<Transform DEF="Voice{p}" translation="0 0.45 0" scale="0.25 1 0.25" visible="{vis}"><Shape>{paint(rc)}<Cylinder radius="0.55" height="0.06" /></Shape></Transform>'
            tgt = "scale"
        elif r == 2:                          # growing bar: ONE leaf Transform, scale y and translation y moved together (a nested
            ss = [0.1 + 1.5 * tri((k / K + ph) % 1.0) for k in range(K + 1)]      # child would not inherit visible="false" at import)
            ip = f'<PositionInterpolator DEF="Ip{p}" key="{f(*ks)}" keyValue="{" ".join(f(1, s, 1) for s in ss)}" />'
            body.append(f'    <PositionInterpolator DEF="Tp{p}" key="{f(*ks)}" keyValue="{" ".join(f(0, 0.2 + 0.5 * s, 0) for s in ss)}" />')
            route(f"Clk{p}", "fraction_changed", f"Tp{p}", "set_fraction")
            route(f"Tp{p}", "value_changed", f"Voice{p}", "translation")
            voice = f'<Transform DEF="Voice{p}" translation="0 0.25 0" scale="1 0.1 1" visible="{vis}"><Shape>{paint(rc)}<Box size="0.45 1 0.45" /></Shape></Transform>'
            tgt = "scale"
        else:                                 # pulsing cone: scale AND colour (second interpolator)
            ss = [0.4 + 0.9 * tri((k / K + ph) % 1.0) for k in range(K + 1)]
            ip = f'<PositionInterpolator DEF="Ip{p}" key="{f(*ks)}" keyValue="{" ".join(f(s, s, s) for s in ss)}" />'
            cs = [tuple(min(1.0, 0.45 + 0.55 * tri((k / K + ph) % 1.0) * v) for v in rc) for k in range(K + 1)]
            body.append(f'    <ColorInterpolator DEF="Ci{p}" key="{f(*ks)}" keyValue="{" ".join(f(*cc) for cc in cs)}" />')
            voice = f'<Transform DEF="Voice{p}" translation="0 0.5 0" scale="0.4 0.4 0.4" visible="{vis}"><Shape><Appearance><PhysicalMaterial DEF="ConeMat{p}" baseColor="{f(*rc)}" emissiveColor="{f(*rc)}" /></Appearance><Cone bottomRadius="0.4" height="0.8" /></Shape></Transform>'
            route(f"Clk{p}", "fraction_changed", f"Ci{p}", "set_fraction")
            route(f"Ci{p}", "value_changed", f"ConeMat{p}", "baseColor")
            route(f"Ci{p}", "value_changed", f"ConeMat{p}", "emissiveColor")
        body.append(f"    {ip}")
        body.append(f'    <TimeSensor DEF="Clk{p}" cycleInterval="{PULSE}" loop="true" enabled="{vis}" />')
        body.append(f'    <BooleanFilter DEF="Press{p}" />')
        body.append(f'    <BooleanToggle DEF="Lit{p}" toggle="{vis}" />')
        route(f"Touch{p}", "isActive", f"Press{p}", "set_boolean")
        route(f"Press{p}", "inputTrue", f"Lit{p}", "set_boolean")
        route(f"Lit{p}", "toggle_changed", f"Cap{p}", "visible")
        route(f"Lit{p}", "toggle_changed", f"Voice{p}", "visible")
        route(f"Lit{p}", "toggle_changed", f"Clk{p}", "enabled")
        route(f"Clk{p}", "fraction_changed", f"Ip{p}", "set_fraction")
        route(f"Ip{p}", "value_changed", f"Voice{p}", tgt)
        # the pad: a dim base (the touchable), a lit cap, a white flash plate for the playhead; the voice stands on it
        basepaint = paint(dim, 'roughness="0.5"')
        pads += (f'    <Transform DEF="Pad{p}" translation="{f(x, 0.0, z)}">\n'
                 f'      <TouchSensor DEF="Touch{p}" description="Click: toggle this pad" />\n'
                 f'      <Shape>{basepaint}<Box size="1.3 0.2 1.3" /></Shape>\n'
                 f'      <Transform DEF="Cap{p}" translation="0 0.12 0" visible="{vis}"><Shape>{paint(rc)}<Box size="1.1 0.1 1.1" /></Shape></Transform>\n'
                 f'      <Transform DEF="Flash{p}" translation="0 0.19 0" visible="false"><Shape>{paint((1, 1, 1))}<Box size="1.32 0.04 1.32" /></Shape></Transform>\n'
                 f'      {voice}\n'
                 f'    </Transform>\n')

# the playhead: one lap, eight BooleanSequencers (true only in the column's slot), each fanned out to a glow bar and 4 flash plates
body.append(f'    <TimeSensor DEF="Playhead" cycleInterval="{BEAT}" loop="true" />')
glows = ""
for c in range(COLS):
    s, e = c / COLS, (c + 1) / COLS
    keys, vals = ([0, e, 1], ["true", "false", "false"]) if c == 0 else ([0, s, e, 1], ["false", "true", "false", "false"]) if c < COLS - 1 else ([0, s, 1], ["false", "true", "true"])
    body.append(f'    <BooleanSequencer DEF="Step{c}" key="{f(*keys)}" keyValue="{" ".join(vals)}" />')
    route("Playhead", "fraction_changed", f"Step{c}", "set_fraction")
    route(f"Step{c}", "value_changed", f"Glow{c}", "visible")
    for r in range(ROWS):
        route(f"Step{c}", "value_changed", f"Flash{r}_{c}", "visible")
    glows += (f'    <Transform DEF="Glow{c}" translation="{f(x0 + c * GAP, -0.12, 0.0)}" visible="false"><Shape>{paint((1, 0.95, 0.6))}'
              f'<Box size="1.4 0.08 {f(ROWS * GAP + 0.2)}" /></Shape></Transform>\n')

SCENE = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <meta name="title" content="Gallery 19: step sequencer" />
    <meta name="description" content="A 4 x 8 pad grid; click pads to light them. Lit pads pulse their row's instrument while a playhead sweeps the columns." />
    <meta name="generator" content="tests/behaviour/demos/gallery-19-step-sequencer/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.02 0.0 0.05" />
    <Viewpoint DEF="View" description="Over the pads" position="0 9.5 9.5" orientation="1 0 0 -0.78" />
    <DirectionalLight direction="0 -1 -0.4" intensity="1.0" />
    <Transform DEF="Floor" translation="0 -0.25 0"><Shape><Appearance><PhysicalMaterial baseColor="0.06 0.06 0.1" emissiveColor="0.03 0.03 0.06" /></Appearance><Box size="15 0.2 8.5" /></Shape></Transform>
{glows}{pads}
{chr(10).join(body)}
  </Scene>
</X3D>
"""
OUT.write_text(SCENE, encoding="utf-8")
print(OUT)
