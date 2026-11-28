# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""X3D 4.0 Sound component audio graph <-> Blender Audaspace (``aud``), see docs/SOUND_BRIDGE.md.

Three layers, the first two plain Python (no Blender):

* ``parse_graph(elem)``: an ElementTree element of an audio-graph node -> ``AudioNode`` tree. Fields are kept as the
  raw strings written in the file, in file order, so ``to_xml`` writes them back unchanged.
* ``plan(node)``: ``AudioNode`` -> ``PlanStep`` tree: what each node becomes (an aud call, a numpy step wrapped in
  ``aud.Sound.buffer``, a pass-through, or silence) plus a note for anything approximated or dropped.
* ``render(node, aud, ...)``: build the aud expression. ``aud`` (and numpy) are parameters, so nothing here imports
  Blender.

Topology: in X3D a node's ``children`` are its inputs (Web Audio "connect" by nesting). Several inputs are summed,
as Web Audio sums every connection into an input, then the node's operation applies, then its ``gain`` field.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field

SOURCES = ("OscillatorSource", "BufferAudioSource", "AudioClip", "MicrophoneSource", "StreamAudioSource",
           "ListenerPointSource")
PROCESSING = ("Gain", "BiquadFilter", "Convolver", "Delay", "DynamicsCompressor", "WaveShaper", "Analyser")
CHANNEL = ("ChannelMerger", "ChannelSelector", "ChannelSplitter")
DESTINATIONS = ("AudioDestination", "StreamAudioDestination", "SpatialSound", "Sound")
HELPERS = ("PeriodicWave",)
AUDIO_NODES = SOURCES + PROCESSING + CHANNEL + DESTINATIONS + HELPERS   # 21 element names (19 graph nodes + 2 helpers)

# How each node is rendered. "aud": an aud.Sound operation. "numpy": computed in numpy and wrapped back with
# aud.Sound.buffer (aud has no primitive for it). "pass": signal passes unchanged. "none": silence, not rendered.
KIND = {
    "OscillatorSource": "aud", "AudioClip": "aud", "BufferAudioSource": "aud",
    "MicrophoneSource": "none", "StreamAudioSource": "none", "ListenerPointSource": "none",
    "Gain": "aud", "BiquadFilter": "aud", "Convolver": "aud", "Delay": "aud",
    "DynamicsCompressor": "numpy", "WaveShaper": "numpy", "Analyser": "pass",
    "ChannelMerger": "numpy", "ChannelSelector": "numpy", "ChannelSplitter": "pass",
    "AudioDestination": "aud", "StreamAudioDestination": "aud", "SpatialSound": "aud", "Sound": "aud",
    "PeriodicWave": "aud",
}

# Defaults from x3d-4.0.xsd (only those the renderer reads).
DEFAULTS = {
    "gain": "1", "enabled": "true", "startTime": "0", "stopTime": "0", "pauseTime": "0", "resumeTime": "0",
    "frequency": None, "detune": "0", "qualityFactor": "1", "type": None, "delayTime": "0", "maxDelayTime": "1",
    "attack": "0.003", "knee": "30", "ratio": "12", "release": "0.25", "threshold": "-24", "curve": "",
    "channelSelection": "0", "maxChannelCount": "2", "pitch": "1.0", "loop": "false", "playbackRate": "1",
    "buffer": "", "numberOfChannels": "0", "sampleRate": "0", "normalize": "false", "url": "",
    "optionsReal": "", "optionsImag": "", "intensity": "1",
}
NODE_DEFAULTS = {("OscillatorSource", "frequency"): "440", ("BiquadFilter", "frequency"): "350",
                 ("BiquadFilter", "type"): "LOWPASS", ("PeriodicWave", "type"): "SQUARE"}


# ----------------------------------------------------------------------------------------------------- model
@dataclass
class AudioNode:
    tag: str
    attrs: dict = field(default_factory=dict)       # raw attribute strings as written, insertion order = file order
    children: list = field(default_factory=list)    # AudioNode, or ET.Element for non-audio content kept verbatim
    text: str | None = None
    tail: str | None = None

    @property
    def container_field(self) -> str | None:
        return self.attrs.get("containerField")

    @property
    def inputs(self) -> list:
        """Audio inputs: AudioNode children that are not PeriodicWave and not a ChannelSplitter's outputs."""
        return [c for c in self.children if isinstance(c, AudioNode) and c.tag != "PeriodicWave"
                and c.container_field != "outputs"]

    def raw(self, name: str) -> str | None:
        if name in self.attrs:
            return self.attrs[name]
        return NODE_DEFAULTS.get((self.tag, name), DEFAULTS.get(name))

    def num(self, name: str) -> float:
        return float(self.raw(name))

    def flag(self, name: str) -> bool:
        return (self.raw(name) or "false").strip().lower() == "true"

    def floats(self, name: str) -> list:
        return [float(x) for x in (self.raw(name) or "").replace(",", " ").split()]

    def strings(self, name: str) -> list:
        import shlex
        try:
            return shlex.split(self.raw(name) or "")
        except ValueError:
            return []


def parse_graph(elem: ET.Element, defs: dict | None = None) -> AudioNode:
    """One element (and its subtree) -> AudioNode. Non-audio children are kept as Elements for the round trip."""
    defs = {} if defs is None else defs
    node = AudioNode(elem.tag, dict(elem.attrib), [], elem.text, elem.tail)
    if "DEF" in elem.attrib:
        defs[elem.attrib["DEF"]] = node
    for ch in elem:
        node.children.append(parse_graph(ch, defs) if ch.tag in AUDIO_NODES else ch)
    return node


def find_graphs(root: ET.Element) -> list:
    """Top-level audio-graph roots in a document: destination nodes not nested in another audio node."""
    out, defs = [], {}

    def walk(e, inside):
        if e.tag in AUDIO_NODES and not inside:
            if e.tag in DESTINATIONS:
                out.append(parse_graph(e, defs))
            return
        for c in e:
            walk(c, inside or e.tag in AUDIO_NODES)
    walk(root, False)
    return out


def to_xml(node: AudioNode) -> ET.Element:
    e = ET.Element(node.tag, dict(node.attrs))
    e.text, e.tail = node.text, node.tail
    for c in node.children:
        e.append(to_xml(c) if isinstance(c, AudioNode) else c)
    return e


# ----------------------------------------------------------------------------------------------------- plan
@dataclass
class PlanStep:
    tag: str
    kind: str                 # aud | numpy | pass | none
    op: str                   # human-readable aud expression fragment
    notes: list = field(default_factory=list)
    inputs: list = field(default_factory=list)

    def walk(self):
        yield self
        for i in self.inputs:
            yield from i.walk()

    def lines(self, depth=0):
        out = ["  " * depth + f"{self.tag} [{self.kind}] {self.op}"]
        out += ["  " * depth + f"  ~ {n}" for n in self.notes]
        for i in self.inputs:
            out += i.lines(depth + 1)
        return out


def oscillator_frequency(node: AudioNode) -> float:
    """Web Audio computedFrequency = frequency * 2^(detune/1200)."""
    return node.num("frequency") * 2.0 ** (node.num("detune") / 1200.0)


def waveform(node: AudioNode) -> tuple:
    """(type, real, imag) for an OscillatorSource; no PeriodicWave child means SINE (Web Audio's default)."""
    pw = next((c for c in node.children if isinstance(c, AudioNode) and c.tag == "PeriodicWave"), None)
    if pw is None:
        return "SINE", [], []
    return pw.raw("type").upper(), pw.floats("optionsReal"), pw.floats("optionsImag")


def biquad_coefficients(ftype: str, f0: float, q: float, gain_db: float, rate: float) -> tuple:
    """Web Audio API BiquadFilterNode coefficients (W3C Web Audio 1.0, sec. 1.13.4, from the RBJ cookbook).

    For LOWPASS/HIGHPASS Web Audio reads Q in dB; for the others Q is linear. Returns (b, a) with a[0] == 1.
    X3D's BiquadFilter has no gain (dB) field of its own: the node ``gain`` field is the linear output gain, so the
    shelf/peaking gain is 0 dB here (see docs, an X3D gap).
    """
    f0 = max(1e-6, min(f0, rate / 2 * 0.9999))
    w0 = 2 * math.pi * f0 / rate
    cw, sw = math.cos(w0), math.sin(w0)
    A = 10 ** (gain_db / 40)
    t = ftype.upper()
    if t in ("LOWPASS", "HIGHPASS"):
        alpha = sw / (2 * 10 ** (q / 20))
    else:
        alpha = sw / (2 * max(q, 1e-6))
    if t == "LOWPASS":
        b = [(1 - cw) / 2, 1 - cw, (1 - cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "HIGHPASS":
        b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "BANDPASS":
        b = [alpha, 0, -alpha]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "NOTCH":
        b = [1, -2 * cw, 1]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "ALLPASS":
        b = [1 - alpha, -2 * cw, 1 + alpha]; a = [1 + alpha, -2 * cw, 1 - alpha]
    elif t == "PEAKING":
        b = [1 + alpha * A, -2 * cw, 1 - alpha * A]; a = [1 + alpha / A, -2 * cw, 1 - alpha / A]
    elif t in ("LOWSHELF", "HIGHSHELF"):
        s = 1.0
        alpha = sw / 2 * math.sqrt((A + 1 / A) * (1 / s - 1) + 2)
        k = 2 * math.sqrt(A) * alpha
        if t == "LOWSHELF":
            b = [A * ((A + 1) - (A - 1) * cw + k), 2 * A * ((A - 1) - (A + 1) * cw), A * ((A + 1) - (A - 1) * cw - k)]
            a = [(A + 1) + (A - 1) * cw + k, -2 * ((A - 1) + (A + 1) * cw), (A + 1) + (A - 1) * cw - k]
        else:
            b = [A * ((A + 1) + (A - 1) * cw + k), -2 * A * ((A - 1) + (A + 1) * cw), A * ((A + 1) + (A - 1) * cw - k)]
            a = [(A + 1) - (A - 1) * cw + k, 2 * ((A - 1) - (A + 1) * cw), (A + 1) - (A - 1) * cw - k]
    else:
        raise ValueError(f"unknown BiquadFilter type {ftype!r}")
    return [x / a[0] for x in b], [x / a[0] for x in a]


def biquad_magnitude(b, a, f: float, rate: float) -> float:
    """|H(e^jw)| of a biquad at frequency f: the prediction the measured renders are checked against."""
    w = 2 * math.pi * f / rate
    z1, z2 = complex(math.cos(-w), math.sin(-w)), complex(math.cos(-2 * w), math.sin(-2 * w))
    return abs((b[0] + b[1] * z1 + b[2] * z2) / (a[0] + a[1] * z1 + a[2] * z2))


def _timing_notes(node: AudioNode) -> list:
    notes = []
    if node.tag in SOURCES and (node.num("pauseTime") or node.num("resumeTime")):
        notes.append("pauseTime/resumeTime rendered as a silent gap (offline clock)")
    if node.tag in PROCESSING and any(node.num(t) for t in ("startTime", "stopTime", "pauseTime", "resumeTime")):
        notes.append("start/stop/pause on a processing node ignored (untested meaning)")
    return notes


def plan(node: AudioNode) -> PlanStep:
    t, k = node.tag, KIND.get(node.tag, "none")
    notes, op = _timing_notes(node), ""
    g = node.num("gain") if node.raw("gain") is not None else 1.0
    if t == "OscillatorSource":
        wt, re, im = waveform(node)
        f = oscillator_frequency(node)
        if wt == "CUSTOM":
            k, op = "numpy", f"additive PeriodicWave {len(re)}/{len(im)} terms at {f:g} Hz -> aud.Sound.buffer"
            notes.append("CUSTOM wave synthesised in numpy, normalised to peak 1 like Web Audio")
        else:
            op = f"aud.Sound.{wt.lower()}({f:g})"
            if wt != "SINE":
                notes.append(f"aud {wt.lower()} is the ideal (aliased) waveform; Web Audio builds it band-limited")
    elif t == "AudioClip":
        op = f"aud.Sound.file({(node.strings('url') or ['?'])[0]!r})"
        if node.num("pitch") != 1:
            op += f".resample(rate/{node.num('pitch'):g}) (pitch)"
        if node.flag("loop"):
            op += ".loop(-1)"
    elif t == "BufferAudioSource":
        if node.floats("buffer"):
            k, op = "numpy", f"aud.Sound.buffer({len(node.floats('buffer'))} samples)"
            notes.append("MFFloat buffer read channel-planar (numberOfChannels blocks); layout untested against a browser")
        else:
            op = f"aud.Sound.file({(node.strings('url') or ['?'])[0]!r})"
        if node.num("playbackRate") != 1 or node.num("detune"):
            notes.append("playbackRate/detune applied by resampling")
        if node.raw("loopStart") not in (None, "0") or node.raw("loopEnd") not in (None, "0"):
            notes.append("loopStart/loopEnd ignored: whole buffer loops")
    elif t in ("MicrophoneSource", "StreamAudioSource"):
        op = "aud.Sound.silence()"
        notes.append("live input: no offline equivalent, rendered as silence")
    elif t == "ListenerPointSource":
        op = "aud.Sound.silence()"
        notes.append("listener-as-source has no aud equivalent; the Blender listener is the scene camera")
    elif t == "Gain":
        op = f"sum(inputs).volume({g:g})"
    elif t == "BiquadFilter":
        ft = node.raw("type").upper()
        f = node.num("frequency") * 2.0 ** (node.num("detune") / 1200.0)
        op = f"sum(inputs).filter(b, a)  # Web Audio {ft} f0={f:g} Q={node.num('qualityFactor'):g}"
        if ft in ("LOWSHELF", "HIGHSHELF", "PEAKING"):
            notes.append("X3D has no BiquadFilter dB-gain field; shelf/peak gain taken as 0 dB")
    elif t == "Convolver":
        op = f"sum(inputs).convolver(aud.ImpulseResponse({len(node.floats('buffer'))} samples))"
        if node.flag("normalize"):
            notes.append("normalize: Web Audio's RMS normalisation formula, untested against a browser")
        if not node.floats("buffer"):
            k, op = "pass", "no impulse response: pass-through"
            notes.append("empty buffer, passed through")
    elif t == "Delay":
        d = min(node.num("delayTime"), node.num("maxDelayTime"))
        op = f"sum(inputs).delay({d:g})"
    elif t == "DynamicsCompressor":
        op = "numpy feed-forward compressor (threshold/knee/ratio/attack/release)"
        notes.append("aud has no compressor: numpy approximation, no lookahead or makeup gain; untested vs Web Audio")
    elif t == "WaveShaper":
        op = f"numpy curve lookup ({len(node.floats('curve'))} points)"
        if (node.raw("oversample") or "NONE").upper() != "NONE":
            notes.append("oversample ignored")
    elif t == "Analyser":
        op = "pass-through"
        notes.append("analysis data (FFT, levels) is not produced: realtime only")
    elif t == "ChannelMerger":
        op = "numpy: input i -> channel i"
    elif t == "ChannelSelector":
        op = f"numpy: channel {int(node.num('channelSelection'))}"
    elif t == "ChannelSplitter":
        op = "pass-through of the multichannel input"
        if any(isinstance(c, AudioNode) and c.container_field == "outputs" for c in node.children):
            notes.append("'outputs' branches are kept for the round trip but not rendered")
    elif t in DESTINATIONS:
        op = f"sum(inputs).volume({g:g})"
        if t == "AudioDestination":
            op += f".rechannel(<= {int(node.num('maxChannelCount'))})"
        if t == "StreamAudioDestination":
            notes.append("stream output written to the WAV file instead")
        if t in ("SpatialSound", "Sound"):
            op += f" * intensity {node.num('intensity'):g}"
            notes.append("spatialisation not rendered here: dry signal; position/cone/distance belong on a Speaker")
    if node.raw("enabled") is not None and not node.flag("enabled"):
        notes.append("enabled=false: " + ("silence" if t in SOURCES else "bypass (pass-through)"))
    if t not in DESTINATIONS + ("Gain",) and g != 1:
        op += f" * gain {g:g}"
    inputs = [] if t in SOURCES else [plan(c) for c in node.inputs]
    return PlanStep(t, k, op, notes, inputs)


def summary(step: PlanStep) -> dict:
    out = {"aud": 0, "numpy": 0, "pass": 0, "none": 0, "notes": []}
    for s in step.walk():
        out[s.kind] += 1
        out["notes"] += [f"{s.tag}: {n}" for n in s.notes]
    return out


# ----------------------------------------------------------------------------------------------------- render
class Renderer:
    """Build aud.Sound expressions for an AudioNode tree. Every sound is limited to ``duration`` seconds so numpy
    steps can call ``.data()``; channel counts are matched with ``rechannel`` before mixing (aud refuses to mix
    different specs)."""

    def __init__(self, aud, np, rate: int = 48000, duration: float = 2.0, epoch: float = 0.0, base_dir: str = "."):
        self.aud, self.np, self.rate, self.dur, self.epoch, self.base = aud, np, rate, duration, epoch, base_dir

    # helpers
    def silence(self, ch=1):
        s = self.aud.Sound.silence(self.rate).limit(0, self.dur)
        return s.rechannel(ch) if ch > 1 else s

    def channels(self, s) -> int:
        return int(s.specs[1])

    def from_array(self, arr):
        arr = self.np.ascontiguousarray(arr, dtype=self.np.float32)
        if arr.ndim == 1:
            arr = arr[:, None]
        n = int(round(self.dur * self.rate))
        if arr.shape[0] < n:
            arr = self.np.vstack([arr, self.np.zeros((n - arr.shape[0], arr.shape[1]), self.np.float32)])
        return self.aud.Sound.buffer(arr[:n], self.rate)

    def array(self, s):
        """Samples of s as (n, ch), exactly dur*rate frames (cache first: data() of an uncached chain may drop or add
        a few frames)."""
        d = self.np.asarray(s.limit(0, self.dur).cache().data(), dtype=self.np.float32)
        n = int(round(self.dur * self.rate))
        if d.shape[0] < n:
            d = self.np.vstack([d, self.np.zeros((n - d.shape[0], d.shape[1]), self.np.float32)])
        return d[:n]

    def mix(self, sounds):
        if not sounds:
            return self.silence()
        ch = max(self.channels(s) for s in sounds)
        out = None
        for s in sounds:
            s = s.rechannel(ch) if self.channels(s) != ch else s
            out = s if out is None else out.mix(s)
        return out.limit(0, self.dur)

    def schedule(self, s, node):
        """X3DTimeDependentNode fields on a source, on an offline clock whose t=0 is ``epoch``. startTime/stopTime
        are clock times (stopTime <= startTime: no stop); a pause holds the source's elapsed time until resumeTime
        (no resume: silent to the end); stopTime still stops at its clock time."""
        start = node.num("startTime") - self.epoch
        stop = node.num("stopTime") - self.epoch
        pause, resume = node.num("pauseTime") - self.epoch, node.num("resumeTime") - self.epoch
        begin = max(start, 0.0)
        skip = begin - start                         # started before the clock: join part-way
        end = min(stop, self.dur) if stop > start else self.dur
        if end <= begin:
            return self.silence(self.channels(s))
        if begin < pause < end:
            first = pause - start                    # elapsed source time at the pause
            gap = (resume - pause) if resume > pause else self.dur
            s = s.limit(skip, first).join(self.silence(self.channels(s)).limit(0, gap)).join(
                s.limit(first, first + self.dur))
        else:
            s = s.limit(skip, skip + self.dur)
        s = s.limit(0, end - begin)
        if begin > 0:
            s = s.delay(begin)
        return s.limit(0, self.dur)

    # node dispatch
    def render(self, node: AudioNode):
        t = node.tag
        if node.raw("enabled") is not None and not node.flag("enabled"):
            if t in SOURCES:
                return self.silence()
            return self.mix([self.render(c) for c in node.inputs])
        fn = getattr(self, "r_" + t, None)
        s = fn(node) if fn else self.silence()
        g = node.num("gain") if t not in ("Gain",) + DESTINATIONS else 1.0
        if t in ("SpatialSound", "Sound"):
            g = node.num("gain") * node.num("intensity") if node.raw("gain") is not None else node.num("intensity")
        if g != 1:
            s = s.volume(g)
        return s.limit(0, self.dur)

    def r_OscillatorSource(self, n):
        wt, re, im = waveform(n)
        f = oscillator_frequency(n)
        if wt == "CUSTOM":
            np = self.np
            t = np.arange(int(self.dur * self.rate) + 1) / self.rate
            y = np.zeros_like(t)
            for k in range(1, max(len(re), len(im))):
                a = re[k] if k < len(re) else 0.0
                b = im[k] if k < len(im) else 0.0
                y += a * np.cos(2 * np.pi * k * f * t) + b * np.sin(2 * np.pi * k * f * t)
            peak = np.abs(y).max()
            s = self.from_array(y / peak if peak > 0 else y)
        else:
            s = getattr(self.aud.Sound, {"SINE": "sine", "SQUARE": "square", "SAWTOOTH": "sawtooth",
                                         "TRIANGLE": "triangle"}[wt])(f, self.rate)
        return self.schedule(s, n)

    def _file(self, n):
        import os
        for u in n.strings("url"):
            p = u if os.path.isabs(u) else os.path.join(self.base, u)
            if os.path.exists(p):
                return self.aud.Sound.file(p).resample(self.rate, 2)
        return None

    def r_AudioClip(self, n):
        s = self._file(n)
        if s is None:
            return self.silence()
        if n.num("pitch") != 1:     # Sound.pitch() had no effect on generators in a probe; resample instead
            s = self.aud.Sound.buffer(self.array(s), self.rate / n.num("pitch")).resample(self.rate, 2)
        if n.flag("loop"):
            s = s.loop(-1)
        return self.schedule(s, n)

    def r_BufferAudioSource(self, n):
        data = n.floats("buffer")
        if data:
            ch = max(1, int(n.num("numberOfChannels")))
            sr = n.num("sampleRate") or self.rate
            frames = len(data) // ch
            arr = self.np.array(data[: frames * ch], dtype=self.np.float32).reshape(ch, frames).T
            s = self.aud.Sound.buffer(self.np.ascontiguousarray(arr), sr)
        else:
            s = self._file(n)
            if s is None:
                return self.silence()
        factor = n.num("playbackRate") * 2.0 ** (n.num("detune") / 1200.0)
        if factor != 1:
            s = self.aud.Sound.buffer(self.array(s), self.rate * factor)
        if s.specs[0] != self.rate:
            s = s.resample(self.rate, 2)
        if n.flag("loop"):
            s = s.loop(-1)
        return self.schedule(s, n)

    def r_Gain(self, n):
        return self.mix([self.render(c) for c in n.inputs]).volume(n.num("gain"))

    def r_BiquadFilter(self, n):
        f = n.num("frequency") * 2.0 ** (n.num("detune") / 1200.0)
        b, a = biquad_coefficients(n.raw("type"), f, n.num("qualityFactor"), 0.0, self.rate)
        return self.mix([self.render(c) for c in n.inputs]).filter(b, a)

    def r_Delay(self, n):
        d = max(0.0, min(n.num("delayTime"), n.num("maxDelayTime")))
        s = self.mix([self.render(c) for c in n.inputs])
        return s.delay(d) if d > 0 else s

    def r_Convolver(self, n):
        s = self.mix([self.render(c) for c in n.inputs])
        ir = n.floats("buffer")
        if not ir:
            return s
        ir = self.np.array(ir, dtype=self.np.float32)
        if n.flag("normalize"):   # Web Audio calculateNormalizationScale (power -> 1/power * 0.00125 calibration)
            power = float(self.np.sqrt(self.np.sum(ir ** 2) / len(ir)))
            ir = ir * ((1.0 / max(power, 1e-6)) * 0.00125)
        resp = self.aud.ImpulseResponse(self.aud.Sound.buffer(ir[:, None], self.rate))
        ch = self.channels(s)
        out = s.rechannel(1).convolver(resp, self.aud.ThreadPool(2)) if ch == 1 else s.convolver(resp, self.aud.ThreadPool(2))
        return out

    def r_DynamicsCompressor(self, n):
        np = self.np
        x = self.array(self.mix([self.render(c) for c in n.inputs]))
        thr, knee, ratio = n.num("threshold"), n.num("knee"), max(1.0, n.num("ratio"))
        att = math.exp(-1.0 / max(1.0, n.num("attack") * self.rate))
        rel = math.exp(-1.0 / max(1.0, n.num("release") * self.rate))
        level = np.abs(x).max(axis=1)
        env = np.zeros_like(level)
        e = 0.0
        for i, v in enumerate(level):            # peak follower
            c = att if v > e else rel
            e = c * e + (1 - c) * v
            env[i] = e
        db = 20 * np.log10(np.maximum(env, 1e-9))
        over = db - thr
        gr = np.where(over <= -knee / 2, 0.0,
                      np.where(over >= knee / 2, over * (1 - 1 / ratio),
                               (1 - 1 / ratio) * (over + knee / 2) ** 2 / (2 * max(knee, 1e-9))))
        return self.from_array(x * (10 ** (-gr / 20))[:, None])

    def r_WaveShaper(self, n):
        np = self.np
        x = self.array(self.mix([self.render(c) for c in n.inputs]))
        curve = np.array(n.floats("curve"), dtype=np.float64)
        if len(curve) < 2:
            return self.from_array(x)
        v = (len(curve) - 1) / 2.0 * (np.clip(x, -1, 1) + 1)   # Web Audio WaveShaper curve index
        return self.from_array(np.interp(v, np.arange(len(curve)), curve))

    def r_Analyser(self, n):
        return self.mix([self.render(c) for c in n.inputs])

    def r_ChannelMerger(self, n):
        arrs = [self.array(self.render(c))[:, 0] for c in n.inputs]
        if not arrs:
            return self.silence()
        return self.from_array(self.np.stack(arrs, axis=1))

    def r_ChannelSelector(self, n):
        x = self.array(self.mix([self.render(c) for c in n.inputs]))
        i = int(n.num("channelSelection"))
        return self.from_array(x[:, i] if i < x.shape[1] else self.np.zeros(x.shape[0], self.np.float32))

    def r_ChannelSplitter(self, n):
        return self.mix([self.render(c) for c in n.inputs])

    def _dest(self, n):
        return self.mix([self.render(c) for c in n.inputs])

    def r_AudioDestination(self, n):
        s = self._dest(n).volume(n.num("gain"))
        m = int(n.num("maxChannelCount"))
        return s.rechannel(m) if 0 < m < self.channels(s) else s

    r_StreamAudioDestination = _dest
    r_SpatialSound = _dest
    r_Sound = _dest


def render(node: AudioNode, aud, np, **kw):
    """aud.Sound for the graph under ``node`` (limited to ``duration``)."""
    return Renderer(aud, np, **kw).render(node)


# ----------------------------------------------------------------------------------------------------- Speaker
def speaker_settings(node: AudioNode) -> dict:
    """SpatialSound/Sound fields -> Blender Speaker properties (bpy names). Values only; applying them is bpy's job."""
    if node.tag == "SpatialSound":
        return {
            "volume": node.num("gain") * node.num("intensity") if node.raw("gain") is not None else node.num("intensity"),
            "distance_reference": float(node.attrs.get("referenceDistance", "1")),
            "distance_max": float(node.attrs.get("maxDistance", "10000")),
            "attenuation": float(node.attrs.get("rolloffFactor", "1")),
            "cone_angle_inner": math.degrees(float(node.attrs.get("coneInnerAngle", "6.2832"))),
            "cone_angle_outer": math.degrees(float(node.attrs.get("coneOuterAngle", "6.2832"))),
            "cone_volume_outer": float(node.attrs.get("coneOuterGain", "0")),
            "_distanceModel": node.attrs.get("distanceModel", "INVERSE"),
        }
    if node.tag == "Sound":
        return {"volume": node.num("intensity"),
                "distance_reference": float(node.attrs.get("minFront", "1")),
                "distance_max": float(node.attrs.get("maxFront", "10")),
                "attenuation": 1.0,
                "_distanceModel": "LINEAR (ellipsoid min/max approximated by front radii)"}
    return {}
