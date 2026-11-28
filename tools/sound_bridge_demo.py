# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Render an X3D 4.0 audio graph to a WAV with Blender's aud, then measure the WAV.

    Blender -b --factory-startup --python tools/sound_bridge_demo.py -- IN.x3d OUT.wav [--duration 2] [--speaker]

Prints the plan (what each node became, what was approximated), then duration, peak per channel and the dominant
FFT frequency per channel, all measured from OUT.wav as written (read back with the stdlib ``wave`` module).
With --speaker, also adds a Speaker object per SpatialSound/Sound carrying the rendered WAV and the mapped fields.
"""

from __future__ import annotations

import json
import os
import sys
import wave
import xml.etree.ElementTree as ET

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "source"))
import sound_graph as sg  # noqa: E402

RATE = 48000


def measure(path: str, probe_hz=()) -> dict:
    """Measured from the WAV file: frames, duration, peak per channel, dominant frequency per channel (Hann FFT,
    1 Hz bins over the loudest 1 s window), and the spectrum level at ``probe_hz`` relative to the dominant peak."""
    with wave.open(path, "rb") as w:
        ch, sw, rate, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    if sw != 2:
        raise ValueError("expected 16-bit PCM")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float64).reshape(-1, ch) / 32768.0
    out = {"file": path, "channels": ch, "rate": rate, "frames": int(x.shape[0]),
           "duration_s": round(x.shape[0] / rate, 4), "peak": [], "dominant_hz": [], "probe_db": [],
           "onset_s": [], "offset_s": []}
    for c in range(ch):
        y = x[:, c]
        out["peak"].append(round(float(np.abs(y).max()), 4))
        loud = np.nonzero(np.abs(y) > 1e-3)[0]
        out["onset_s"].append(round(loud[0] / rate, 4) if len(loud) else None)
        out["offset_s"].append(round((loud[-1] + 1) / rate, 4) if len(loud) else None)
        if not len(loud):
            out["dominant_hz"].append(None); out["probe_db"].append({})
            continue
        seg = y[loud[0]: loud[0] + rate]
        seg = np.pad(seg, (0, rate - len(seg)))
        spec = np.abs(np.fft.rfft(seg * np.hanning(rate)))
        k = int(np.argmax(spec))
        out["dominant_hz"].append(round(k * rate / rate, 1))
        out["probe_db"].append({str(f): round(float(20 * np.log10(max(spec[int(round(f))], 1e-12) / spec[k])), 1)
                                for f in probe_hz})
    return out


def write_wav(samples: np.ndarray, path: str) -> None:
    """16-bit PCM via the stdlib. Not aud.Sound.write: in Blender 5.3 it wrote 97792 frames for a 96000-frame
    aud.Sound.buffer (buffersize 4096; 96768 with 1024 or 0), the extra frames non-zero (probe 2026-11-27)."""
    pcm = (np.clip(samples, -1.0, 32767 / 32768) * 32768).round().astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(samples.shape[1]); w.setsampwidth(2); w.setframerate(RATE)
        w.writeframes(pcm.tobytes())


def add_speaker(node: sg.AudioNode, wav: str):
    import bpy
    st = sg.speaker_settings(node)
    spk = bpy.data.speakers.new(node.attrs.get("DEF", node.tag))
    spk.sound = bpy.data.sounds.load(wav)
    applied = {}
    for k, v in st.items():
        if not k.startswith("_") and hasattr(spk, k):
            setattr(spk, k, v)
            applied[k] = round(getattr(spk, k), 4)
    ob = bpy.data.objects.new(spk.name, spk)
    bpy.context.scene.collection.objects.link(ob)
    loc = node.attrs.get("location", "0 0 0").split()
    ob.location = [float(v) for v in loc]   # parent Transform not applied here (importer's job)
    return {"speaker": spk.name, "applied": applied, "distanceModel(X3D)": st.get("_distanceModel")}


def main(argv):
    import aud
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    dur = 2.0
    speaker = "--speaker" in args
    if "--duration" in args:
        i = args.index("--duration"); dur = float(args[i + 1]); del args[i:i + 2]
    args = [a for a in args if a != "--speaker"]
    src, dst = args[0], args[1]
    root = ET.parse(src).getroot()
    graphs = sg.find_graphs(root)
    if not graphs:
        print("no audio graph found"); return 1
    report = {"input": src, "graphs": []}
    sounds = []
    for g in graphs:
        p = sg.plan(g)
        print("\n".join(p.lines()))
        s = sg.summary(p)
        report["graphs"].append({"root": g.tag, "DEF": g.attrs.get("DEF"), "kinds": {k: s[k] for k in
                                 ("aud", "numpy", "pass", "none")}, "approximations": s["notes"]})
        sounds.append(sg.render(g, aud, np, rate=RATE, duration=dur, base_dir=os.path.dirname(os.path.abspath(src))))
    r = sg.Renderer(aud, np, rate=RATE, duration=dur)
    final = sounds[0] if len(sounds) == 1 else r.mix(sounds)
    write_wav(r.array(final), dst)                 # exactly duration * RATE frames
    probes = [440, 660, 880, 4000]
    report["measured"] = measure(dst, probes)
    if speaker:
        report["speakers"] = [add_speaker(g, dst) for g in graphs if g.tag in ("SpatialSound", "Sound")]
    print(json.dumps(report, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
