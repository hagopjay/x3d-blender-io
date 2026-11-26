# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Writes piano.x3d (and keys.json) next to this file: a grand piano seen from above its keyboard.

    python tests/behaviour/demos/piano/build.py

Keyboard mode (a KeySensor listens): any key strikes the hammer and flashes the stand lamp, Shift / Ctrl / Alt light
three pedals, an arrow or F key goes down an Integer chain. Click the sheet and a StringSensor listens instead (X3D lets
one key device sensor listen at a time): the typed line is shown by a small Script (X3D cannot route a SFString into a
MFString), Enter stamps it onto the sheet and hands the keyboard back to the KeySensor.
"""
import json
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
WHITE = 14                                  # white keys, C to B and C to B again
BLACK_AFTER = (0, 1, 3, 4, 5)               # a black key follows C, D, F, G and A of every octave


def paint(name, base, emissive=None, roughness=0.5, metallic=0.0, transparency=None):
    extra = (f' emissiveColor="{emissive}"' if emissive else "") + (f' transparency="{transparency}"' if transparency is not None else "")
    return (f'<Appearance><PhysicalMaterial DEF="{name}" baseColor="{base}" roughness="{roughness}" '
            f'metallic="{metallic}"{extra}/></Appearance>')


def box(size, material):
    return f'<Shape>{material}<Box size="{size}"/></Shape>'


def keys():
    out = []
    for i in range(WHITE):
        x = round(-1.3 + 0.1 + 0.2 * i, 3)
        out.append(f'    <Transform DEF="White{i + 1}" translation="{x} 0.84 0.45">{box("0.19 0.05 0.7", paint(f"WhitePaint{i + 1}", "0.93 0.91 0.86", roughness=0.35))}</Transform>')
    for i in range(WHITE - 1):
        if i % 7 in BLACK_AFTER:
            x = round(-1.3 + 0.2 * (i + 1), 3)
            out.append(f'    <Transform DEF="Black{i + 1}" translation="{x} 0.885 0.3">{box("0.11 0.07 0.42", paint(f"BlackPaint{i + 1}", "0.03 0.03 0.04", roughness=0.3))}</Transform>')
    return "\n".join(out)


def pedal(name, x, label):
    return f"""    <Transform DEF="{name}Pedal" translation="{x} 0.1 1.25">{box("0.22 0.05 0.5", paint(f"{name}Brass", "0.8 0.6 0.25", roughness=0.25, metallic=0.9))}</Transform>
    <Transform DEF="{name}Glow" translation="{x} 0.17 1.25" visible="false">{box("0.3 0.03 0.6", paint(f"{name}GlowPaint", "1 0.75 0.2", emissive="1 0.6 0.1"))}</Transform>"""


ECHO = lambda name: f"""    <Script DEF="{name}"><field name="set_line" type="SFString" accessType="inputOnly"/><field name="line" type="MFString" accessType="outputOnly"/><![CDATA[ecmascript:
function set_line (value) {{ line = new MFString (value); }}
]]></Script>"""

WORLD = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" profile="Immersive" version="4.0" xsi:noNamespaceSchemaLocation="https://www.web3d.org/specifications/x3d-4.0.xsd">
  <head>
    <component name="EventUtilities" level="1" />
    <component name="KeyDeviceSensor" level="2" />
    <meta name="title" content="Piano: type and it plays" />
    <meta name="description" content="A grand piano seen from above its keyboard. Any key strikes the hammer, Shift Ctrl Alt light the pedals, click the sheet to type a line, Enter stamps it." />
    <meta name="generator" content="tests/behaviour/demos/piano/build.py" />
    <meta name="license" content="GPL-3.0-or-later" />
  </head>
  <Scene>
    <NavigationInfo type="&quot;NONE&quot;" headlight="false" />
    <Background skyColor="0.05 0.04 0.06" />
    <Viewpoint DEF="View" description="Over the keyboard" position="0 4.0 2.5" orientation="1 0 0 -0.93" fieldOfView="0.9" />
    <DirectionalLight direction="-0.3 -1 -0.4" intensity="0.9" />
    <PointLight DEF="Hall" location="0 3 1" color="1 0.92 0.8" intensity="2" radius="9" />
    <Transform translation="0 -0.05 0">{box("8 0.1 6", paint("FloorPaint", "0.22 0.14 0.09", roughness=0.7))}</Transform>
    <Transform DEF="Body" translation="0 0.4 -1.4">{box("3.4 0.8 2.6", paint("LacquerPaint", "0.02 0.02 0.03", roughness=0.15, metallic=0.1))}</Transform>
    <Transform DEF="Lid" translation="0 1.55 -2.1" rotation="1 0 0 0.75">{box("3.3 0.05 2.3", paint("LidPaint", "0.02 0.02 0.03", roughness=0.15, metallic=0.1))}</Transform>
    <Transform DEF="Keybed" translation="0 0.76 0.35">{box("2.9 0.1 1.0", paint("KeybedPaint", "0.12 0.07 0.04", roughness=0.5))}</Transform>
    <Transform DEF="KeySlip" translation="0 0.88 -0.08">{box("2.9 0.18 0.1", paint("SlipPaint", "0.05 0.05 0.06", roughness=0.2))}</Transform>
{keys()}
    <Transform DEF="Hammer" translation="0 0.97 0.12">{box("2.8 0.05 0.07", paint("FeltPaint", "0.65 0.1 0.1", roughness=0.9))}</Transform>
{pedal("Soft", -0.35, "una corda")}
{pedal("Sost", 0.0, "sostenuto")}
{pedal("Sustain", 0.35, "sustain")}
    <Transform DEF="LyreBar" translation="0 0.24 1.0">{box("1.2 0.05 0.05", paint("LyrePaint", "0.7 0.5 0.2", roughness=0.3, metallic=0.9))}</Transform>
    <!-- the music stand: a board on the case, the sheet on it, a lamp and a lever -->
    <Transform DEF="Stand" translation="0 1.1 -0.5">{box("0.1 0.7 0.05", paint("StandPaint", "0.05 0.05 0.06", roughness=0.3))}</Transform>
    <Transform DEF="Sheet" translation="0 1.62 -0.62" rotation="1 0 0 -0.3">
      <TouchSensor DEF="SheetTouch" description="Click the sheet, then type" />
      {box("1.5 0.85 0.03", paint("SheetPaint", "0.95 0.93 0.85", roughness=0.9))}
      <Transform translation="0 0.12 0.03"><Shape>{paint("InkPaint", "0.05 0.05 0.08", roughness=0.9)}<Text DEF="SheetText" string='"click the sheet and type"'><FontStyle size="0.13" justify='"MIDDLE" "MIDDLE"' /></Text></Shape></Transform>
    </Transform>
    <Transform DEF="Line" translation="0 1.3 0.2" rotation="1 0 0 -0.93">
      <Shape>{paint("LineInk", "1 0.85 0.4", emissive="0.5 0.35 0.1", roughness=0.6)}<Text DEF="LineText" string='"type here"'><FontStyle size="0.17" justify='"MIDDLE" "MIDDLE"' /></Text></Shape>
    </Transform>
    <Transform DEF="Lamp" translation="-1.0 1.75 -0.6">
      <Transform translation="0 -0.28 0">{box("0.05 0.56 0.05", paint("LampPole", "0.8 0.6 0.25", roughness=0.25, metallic=0.9))}</Transform>
      <Shape>{paint("ShadePaint", "0.1 0.4 0.25", roughness=0.4)}<Cone bottomRadius="0.2" height="0.22" /></Shape>
      <Transform DEF="LampGlow" translation="0 -0.2 0.0"><Shape>{paint("GlowPaint", "1 0.9 0.5", emissive="1 0.85 0.4", transparency=1)}<Sphere radius="0.18" /></Shape></Transform>
    </Transform>
    <Transform DEF="KeysLight" translation="-1.25 0.99 -0.08"><Shape>{paint("KeysLightPaint", "1 0.7 0.2", emissive="1 0.6 0.1")}<Sphere radius="0.05" /></Shape></Transform>
    <Transform DEF="TypeLight" translation="1.25 0.99 -0.08" visible="false"><Shape>{paint("TypeLightPaint", "0.3 0.6 1", emissive="0.2 0.5 1")}<Sphere radius="0.05" /></Shape></Transform>
    <Transform DEF="Caption" translation="0 0.89 -0.02" rotation="1 0 0 -0.4">
      <Shape>{paint("CaptionInk", "0.9 0.9 0.95", emissive="0.4 0.4 0.45", roughness=0.6)}<Text DEF="CaptionText" string='"last key"'><FontStyle size="0.07" justify='"MIDDLE" "MIDDLE"' /></Text></Shape>
    </Transform>
    <Transform DEF="Lever" translation="1.0 1.3 -0.5">
      <TouchSensor DEF="LockTouch" description="Click: forbid or allow Backspace" />
      {box("0.18 0.3 0.1", paint("LeverPaint", "0.8 0.6 0.25", roughness=0.25, metallic=0.9))}
      <Transform DEF="AllowedLight" translation="0 0.26 0.0"><Shape>{paint("AllowedPaint", "0.2 1 0.35", emissive="0.1 0.9 0.2")}<Sphere radius="0.07" /></Shape></Transform>
    </Transform>

    <KeySensor DEF="Keys" description="Keyboard mode" />
    <StringSensor DEF="Typed" enabled="false" description="Typing mode" />
{ECHO("EchoLine")}
{ECHO("EchoSheet")}
    <Script DEF="EchoKey"><field name="set_press" type="SFString" accessType="inputOnly"/><field name="set_release" type="SFString" accessType="inputOnly"/><field name="line" type="MFString" accessType="outputOnly"/><![CDATA[ecmascript:
function set_press (value) {{ line = new MFString ('down ' + JSON.stringify (value)); }}
function set_release (value) {{ line = new MFString ('up ' + JSON.stringify (value)); }}
]]></Script>

    <!-- any key: the hammer strikes, the lamp flashes -->
    <BooleanFilter DEF="Strike" />
    <TimeTrigger DEF="StrikeTrigger" />
    <TimeSensor DEF="HammerClock" cycleInterval="0.25" />
    <PositionInterpolator DEF="HammerDip" key="0 0.4 1" keyValue="0 0.97 0.12 0 0.90 0.12 0 0.97 0.12" />
    <ScalarInterpolator DEF="LampFlash" key="0 0.3 1" keyValue="1 0.1 1" />
    <ROUTE fromNode="Keys" fromField="isActive" toNode="Strike" toField="set_boolean" />
    <ROUTE fromNode="Strike" fromField="inputTrue" toNode="StrikeTrigger" toField="set_boolean" />
    <ROUTE fromNode="StrikeTrigger" fromField="triggerTime" toNode="HammerClock" toField="startTime" />
    <ROUTE fromNode="HammerClock" fromField="fraction_changed" toNode="HammerDip" toField="set_fraction" />
    <ROUTE fromNode="HammerClock" fromField="fraction_changed" toNode="LampFlash" toField="set_fraction" />
    <ROUTE fromNode="HammerDip" fromField="value_changed" toNode="Hammer" toField="translation" />
    <ROUTE fromNode="LampFlash" fromField="value_changed" toNode="GlowPaint" toField="transparency" />
    <!-- the modifiers light the pedals while held -->
    <ROUTE fromNode="Keys" fromField="shiftKey" toNode="SoftGlow" toField="visible" />
    <ROUTE fromNode="Keys" fromField="altKey" toNode="SostGlow" toField="visible" />
    <ROUTE fromNode="Keys" fromField="controlKey" toNode="SustainGlow" toField="visible" />
    <!-- arrows and F keys: the code is kept, and sent on when the key comes up -->
    <BooleanFilter DEF="KeyUp" />
    <IntegerTrigger DEF="ActionCode" />
    <IntegerTrigger DEF="LastAction" />
    <ROUTE fromNode="Keys" fromField="actionKeyPress" toNode="ActionCode" toField="integerKey" />
    <ROUTE fromNode="Keys" fromField="isActive" toNode="KeyUp" toField="set_boolean" />
    <ROUTE fromNode="KeyUp" fromField="inputNegate" toNode="ActionCode" toField="set_boolean" />
    <ROUTE fromNode="ActionCode" fromField="triggerValue" toNode="LastAction" toField="integerKey" />
    <IntegerTrigger DEF="ReleaseCode" />
    <ROUTE fromNode="Keys" fromField="actionKeyRelease" toNode="ReleaseCode" toField="integerKey" />
    <!-- the character of every key, shown on the caption through a Script -->
    <ROUTE fromNode="Keys" fromField="keyPress" toNode="EchoKey" toField="set_press" />
    <ROUTE fromNode="Keys" fromField="keyRelease" toNode="EchoKey" toField="set_release" />
    <ROUTE fromNode="EchoKey" fromField="line" toNode="CaptionText" toField="string" />
    <!-- which sensor has the keyboard: only one key device sensor listens at a time -->
    <ROUTE fromNode="Keys" fromField="enabled_changed" toNode="KeysLight" toField="visible" />
    <ROUTE fromNode="Typed" fromField="enabled_changed" toNode="TypeLight" toField="visible" />
    <!-- the sheet takes the keyboard; Enter gives it back -->
    <BooleanFilter DEF="SheetPress" />
    <BooleanFilter DEF="TypingDone" />
    <ROUTE fromNode="SheetTouch" fromField="isActive" toNode="SheetPress" toField="set_boolean" />
    <ROUTE fromNode="SheetPress" fromField="inputTrue" toNode="Typed" toField="enabled" />
    <ROUTE fromNode="Typed" fromField="isActive" toNode="TypingDone" toField="set_boolean" />
    <ROUTE fromNode="TypingDone" fromField="inputNegate" toNode="Keys" toField="enabled" />
    <!-- the typed line and the stamp, through a Script (a SFString cannot be routed into a MFString) -->
    <ROUTE fromNode="Typed" fromField="enteredText" toNode="EchoLine" toField="set_line" />
    <ROUTE fromNode="EchoLine" fromField="line" toNode="LineText" toField="string" />
    <ROUTE fromNode="Typed" fromField="finalText" toNode="EchoSheet" toField="set_line" />
    <ROUTE fromNode="EchoSheet" fromField="line" toNode="SheetText" toField="string" />
    <!-- the lever: forbid or allow Backspace, with a green light while it is allowed -->
    <BooleanFilter DEF="LeverPress" />
    <BooleanToggle DEF="Allow" toggle="true" />
    <ROUTE fromNode="LockTouch" fromField="isActive" toNode="LeverPress" toField="set_boolean" />
    <ROUTE fromNode="LeverPress" fromField="inputTrue" toNode="Allow" toField="set_boolean" />
    <ROUTE fromNode="Allow" fromField="toggle_changed" toNode="Typed" toField="deletionAllowed" />
    <ROUTE fromNode="Allow" fromField="toggle_changed" toNode="AllowedLight" toField="visible" />
  </Scene>
</X3D>
"""

PLAN = {"keys": [
    {"press": "a"}, {"press": "Enter"}, {"press": "Escape"}, {"press": "Tab"}, {"press": "Delete"}, {"press": "Home"},
    {"press": "PageDown"}, {"press": "Shift+A"}, {"press": "Control+b"}, {"press": "Alt+c"},
    {"press": "ArrowUp"}, {"press": "F2"}, {"press": "ArrowLeft"},
    {"down": "Shift"}, {"click": "SheetTouch", "at": [390, 90]}, {"up": "Shift"}, {"type": "Hello Pianos"}, {"press": "Backspace"},
    {"click": "LockTouch", "at": [630, 180]}, {"press": "Backspace"}, {"click": "LockTouch", "at": [630, 180]},
    {"type": "!"}, {"press": "Backspace"}, {"type": "!"}, {"press": "Enter"},
    {"press": "z"}, {"click": "SheetTouch", "at": [390, 90]}, {"type": "ok"}, {"press": "Enter"},
    {"click": "SheetTouch", "at": [390, 90]}, {"press": "Enter"}, {"type": "x"}, {"press": "Backspace"},
    {"press": "Backspace"}, {"press": "Escape"}, {"press": "q"}], "gap_ms": 150}

if __name__ == "__main__":
    (HERE / "piano.x3d").write_text(WORLD, encoding="utf-8")
    (HERE / "keys.json").write_text(json.dumps(PLAN, indent=1) + "\n", encoding="utf-8")
    print("wrote", HERE / "piano.x3d", "and", HERE / "keys.json")
