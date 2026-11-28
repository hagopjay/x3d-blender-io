# X3D 4.0 audio graph and Blender 5.3: the sound bridge

Status: wired into the importer and the X3D 4.0 exporter, branch `export/sound-bridge`, 2026-11-28 (on top of carry).
The model and renderer are in `source/sound_graph.py` (plain Python), the Blender glue in `source/sound_bridge.py`, the
demo in `tools/sound_bridge_demo.py`, and the fixtures in `tests/sound/`. Section 8 says what the wiring does.

Words used below:

- **measured**: a render was written to a WAV and the number was read back from that file (see "Measurements").
- **untested**: the code path exists but no render has checked it.
- **aud**: Blender's Audaspace Python module, as shipped in Blender 5.3.0 (hash 02f0899d78e3). Every call named here was
  checked with `dir(aud.Sound)` and its docstring in that build.

## 1. Node table

The XSD has 21 element names in the audio graph. That is the 19 graph nodes plus `PeriodicWave`, which is a field
value of `OscillatorSource`, and `Sound`, the classic node that X3D 4 lets take graph children. Field names and
defaults were read from `x3d_mcp/src/validation/schemas/x3d-4.0.xsd`.

"Route" means how `sound_graph.Renderer` produces the node: **aud** is an `aud.Sound` operation; **numpy** means the
node is computed on samples and wrapped back with `aud.Sound.buffer`, because aud has no primitive for it; **pass**
means the signal goes through unchanged; **none** means silence.

| Node | X3D meaning | Blender equivalent | Route | Lost or approximated | Checked |
|---|---|---|---|---|---|
| OscillatorSource | Periodic tone: `frequency`, `detune` (cents), waveform from a `PeriodicWave` child (SINE when there is none) | `aud.Sound.sine/square/sawtooth/triangle(f, rate)` | aud | Nothing for SINE. For the other waves see PeriodicWave | **measured** (SINE 440, 660, 880, 4000 Hz) |
| PeriodicWave | Waveform for an oscillator: SINE, SQUARE, SAWTOOTH, TRIANGLE, or CUSTOM from `optionsReal`/`optionsImag` | aud's ideal waveforms; CUSTOM is built by additive synthesis in numpy | aud or numpy | aud's square, saw and triangle are ideal, aliased waveforms (a probe of the square read only ±1.0), while Web Audio's are band-limited. CUSTOM is normalised to a peak of 1 | untested |
| AudioClip | Audio file from `url`, with `loop` and `pitch` | `aud.Sound.file`, then `.resample`, `.loop(-1)`; a sound strip or `Speaker.sound` in bpy | aud | `pitch` is done by resampling, because `Sound.pitch(1.5)` left a 440 Hz sine at 440 Hz in a probe | untested |
| BufferAudioSource | PCM from the `buffer` field (MFFloat) or a `url`; `playbackRate`, `detune`, `loop`, `loopStart`/`loopEnd` | `aud.Sound.buffer(ndarray, rate)` or `aud.Sound.file` | aud | The layout of `buffer` is assumed to be channel-planar. `loopStart`/`loopEnd` are ignored: the whole buffer loops | untested |
| MicrophoneSource | Live device input | none | none | Everything: an offline render has no live input, so it is silence | n/a |
| StreamAudioSource | Live MediaStream input | none | none | Everything (silence) | n/a |
| ListenerPointSource | The listener's position and orientation as a graph source | none in aud. In Blender the listener is the scene camera | none | Everything (silence) | n/a |
| Gain | Sum of inputs × `gain` | `.mix()` chain, then `.volume(g)` | aud | Nothing | **measured** (×0.5) |
| BiquadFilter | Web Audio biquad of 8 types: `frequency`, `detune`, `qualityFactor` | `aud.Sound.filter(b, a)` with Web Audio's coefficient formulas | aud | X3D has no dB-gain field, so LOWSHELF, HIGHSHELF and PEAKING use 0 dB (an X3D gap). Coefficients are fixed per render: frequency is not automated | **measured** (LOWPASS) |
| Convolver | Convolution with an impulse response in `buffer`; `normalize` | `aud.ImpulseResponse(aud.Sound.buffer(ir))` with `.convolver(ir, aud.ThreadPool(n))` | aud | `normalize` uses Web Audio's RMS formula, not checked against a browser. A file-based impulse response is not supported, because X3D gives only `buffer` | untested (a probe ran it; the output was not checked) |
| Delay | Delay line: `delayTime`, capped by `maxDelayTime` | `.delay(t)` | aud | A fixed delay only: a changing `delayTime` cannot be expressed | **measured** (0.25 s) |
| DynamicsCompressor | Web Audio compressor: `threshold`, `knee`, `ratio`, `attack`, `release` | none in aud (`envelope` is an envelope follower, not a compressor) | numpy | Approximate: a feed-forward peak compressor with no lookahead and no makeup gain | untested |
| WaveShaper | Non-linear `curve` lookup; `oversample` | none in aud | numpy | `oversample` is ignored. The curve index uses Web Audio's formula | untested |
| Analyser | Pass-through with realtime FFT and level outputs | none | pass | Audio is unchanged; the analysis data is not produced | untested |
| ChannelMerger | Input *i* becomes output channel *i* | none in aud | numpy | Nothing for mono inputs; a stereo input contributes only its first channel | **measured** (2 channels) |
| ChannelSelector | Pick channel `channelSelection` from the input | none in aud | numpy | Nothing | untested |
| ChannelSplitter | Split channels to the `outputs` nodes (containerField="outputs") | none | pass | The `outputs` branches are parsed and written back but not rendered | untested |
| AudioDestination | Device output: sum, `gain`, `maxChannelCount` | WAV file (offline), or the scene mixdown | aud | Nothing offline; device choice (`mediaDeviceID`) is lost | **measured** |
| StreamAudioDestination | MediaStream output | WAV file | aud | The stream becomes a file | untested |
| SpatialSound | Positional Web Audio panner: `location`, `direction`, cone, `distanceModel`, `referenceDistance`, `maxDistance`, `rolloffFactor`, `enableHRTF`, `dopplerEnabled` | Speaker object whose `sound` is the rendered graph | aud (dry signal) + Speaker | The render here is dry (`gain` × `intensity`); spatialisation is left to the Speaker. `distanceModel` is scene-wide in Blender. HRTF, doppler and priority are not mapped | dry render **measured**; Speaker property values set and read back; the spatial result is untested |
| Sound | Classic X3D ellipsoid sound: `minFront`/`maxFront`/`minBack`/`maxBack`, `source` or graph children | Speaker | aud (dry) + Speaker | Approximate: the ellipsoid becomes a sphere of the front radii; the back radii are lost | untested |

**Count of the 21 element names:**

- **Native aud: 8.** OscillatorSource, AudioClip, BufferAudioSource, Gain, BiquadFilter, Convolver, Delay,
  AudioDestination. Five of these were measured: the sine oscillator, Gain, the LOWPASS filter, Delay and
  AudioDestination.
- **Exact in numpy: 3.** ChannelMerger (measured), ChannelSelector and WaveShaper.
- **Approximate: 7.** PeriodicWave (non-sine waves), DynamicsCompressor, Analyser, ChannelSplitter, SpatialSound, Sound
  and StreamAudioDestination.
- **Not at all: 3.** MicrophoneSource, StreamAudioSource and ListenerPointSource.

## 2. Topology: nesting as inputs, and aud's functional composition

In X3D, `<Gain><BiquadFilter><OscillatorSource/></BiquadFilter></Gain>` means oscillator → filter → gain. aud composes
the same way, from the inside out: `aud.Sound.sine(440).filter(b, a).volume(0.5)`. So a post-order walk of the X3D tree
is the aud expression:

```
render(node) = op_node( mix( render(c) for c in node.inputs ) ) * node.gain
```

- **Several children are summed** (Web Audio sums all connections into an input). aud's `.mix()` raised "Two readers
  with different specifiactions cannot be superposed" for mono + stereo in a probe, so `Renderer.mix` first
  rechannels every input to the widest one.
- **Every node has a `gain` field** (X3DSoundSourceNode, ProcessingNode, ChannelNode, DestinationNode). It is applied
  as `.volume(gain)` after the node's own operation.
- **Inputs vs other children.** `PeriodicWave` (containerField `periodicWave`) and ChannelSplitter children with
  containerField `outputs` are not inputs. Non-audio children such as metadata are kept as XML for the round trip.
- **DEF/USE fan-out.** One output feeding two places becomes the same sub-expression rendered twice. That matches Web
  Audio only because every route here is deterministic. A USE is kept as written, but rendering a USE'd node is
  untested.
- **Cycles** (a Delay feedback loop) cannot be written by nesting in X3D. aud has `.echo(delay, feedback, mix)` if one
  were wanted.
- **The numpy boundary.** aud generators are infinite (`length == -1`), so the renderer limits everything to the render
  duration. A numpy step calls `.limit(0, dur).cache().data()`, works on the array, and wraps the result back with
  `aud.Sound.buffer`. After that the chain is aud again.

## 3. Time

- **X3D** times (`startTime`, `stopTime`, `pauseTime`, `resumeTime`) are absolute: seconds since 1970 on the browser
  clock. `startTime=0` therefore means "already started". `stopTime <= startTime` means "never stops".
- **Offline clock.** `Renderer(epoch=...)` sets which X3D time is t = 0 of the render (default 0). On a source:
  - start before the clock: the source joins part-way (`limit(skip, …)`);
  - start after: `.delay(start)`;
  - `stopTime`: cuts at that clock time;
  - `pauseTime`…`resumeTime`: a silent gap (`limit + join(silence) + join(rest)`), and the source's elapsed time does
    not advance during it. The fixture `spatial_delay_window` measured onset 0.25 s and offset 1.25 s for Delay 0.25
    with stopTime 1. The pause test measured sound before 0.5 s, silence from 0.51 to 0.99 s, sound from 1.0 to 1.5 s,
    and silence after 1.51 s.
- **Processing nodes** also inherit X3DTimeDependentNode. Their start, stop and pause are not applied (the plan notes
  this), because their meaning for a filter is not settled.
- **Blender frames.** In bpy, a time maps to `frame = frame_start + t * fps / fps_base`. Two ways to place a rendered
  graph: (a) bake the graph to a WAV and put it on a Speaker, or as a sequencer sound strip with
  `frame_start = frame(startTime)`; (b) keep the X3D times as data and recompute on export. X3D `TimeSensor`/ROUTE
  driving `startTime` at runtime cannot be baked: that is behaviour, the behaviour graph's job.
- **Offline only.** aud renders to a WAV ahead of time. There is no live graph, so values that change over time
  (ROUTEd `frequency`, automation) are frozen at their file values.

## 4. SpatialSound and Sound against Speaker objects

`sound_graph.speaker_settings` maps the fields. `--speaker` in the demo sets them on a real Speaker and reads them
back. Measured in the `spatial_delay_window` run:

| X3D field | Speaker property | Read back |
|---|---|---|
| `gain` × `intensity` | `volume` | 0.5 |
| `referenceDistance` | `distance_reference` | 1.0 |
| `maxDistance` | `distance_max` | 50.0 |
| `rolloffFactor` | `attenuation` | 1.0 |
| `coneInnerAngle` (radians) | `cone_angle_inner` (degrees) | 90.0002 (from 1.5708 rad) |
| `coneOuterAngle` | `cone_angle_outer` | 180.0004 |
| `coneOuterGain` | `cone_volume_outer` | 0.25 |
| `location` + parent transforms, `direction` | object location and rotation | location set from `location` only (the parent Transform is not applied in the demo) |
| `distanceModel` LINEAR/INVERSE/EXPONENTIAL | Scene audio distance model (scene-wide) | not set; per-sound values would collide |
| `enableHRTF`, `dopplerEnabled`, `priority`, `spatialize=false` | none (scene doppler settings are global) | lost |

The cone angles do not match exactly: the 1.5708 and 3.1416 written in X3D are rounded values of π/2 and π. Whether
Blender's cone angle is the full angle, as in Web Audio, is **untested**. `Sound`'s ellipsoid becomes the front radii
on a spherical Speaker, which is approximate.

## 5. Round trip: what Blender stores so the export writes the same graph back

aud expressions are not Blender data: nothing persists in the .blend file except Speakers, sounds and strips. As built
(section 8):

1. **Store the graph as written, not the render.** The Speaker keeps the SpatialSound's XML text exactly as carry read
   it (`x3d_sound_graph`). That is simpler than a JSON model and loses nothing: `to_xml(parse_graph(e))` gives back the
   same tags, attribute strings in order and nesting (`tests/test_sound_graph.py::RoundTrip`), so the text and the model
   are the same thing, and the export reparses the text only when it has an edit to merge.
2. **The baked WAV is a cache.** The Speaker plays it in Blender (packed into the .blend). The export ignores it.
3. **Edits made in Blender** to the mapped Speaker properties are merged into those fields only, so an untouched raw
   string such as `gain="0.50"` survives. An edit is a difference from what Blender held right after the import
   (`x3d_sound_applied`), not from the file's value: Blender clamps `volume` to 0..1, so `gain="2"` would otherwise look
   edited on every export.
4. **Hand-made Speakers** without a stored graph are still not written by the X3D 4.0 export (reported as skipped).
   `SpatialSound` → `AudioClip` with the sound file as url is the obvious mapping; not built.
5. **Carry stays underneath.** The bridge takes only graphs it can render faithfully. A graph with a USE in it, one a
   ROUTE touches, one with a node the model does not know, a SpatialSound under a USE'd Transform, or one whose render
   fails stays carried as the file wrote it.

## 6. Honest limits

- **Analyser**: realtime FFT and level outputs exist only in a running browser. Offline, the bridge could write the
  spectrum of the render as metadata; that is not built.
- **MicrophoneSource, StreamAudioSource, StreamAudioDestination**: no device or stream in a batch render. They become
  silence, or a file.
- **Convolver**: needs the impulse response inline in `buffer`; X3D has no url for it. Large impulse responses make the
  X3D file large. aud's convolver is FFT-based and needs a ThreadPool argument: the 1-argument call raised `TypeError`
  in a probe.
- **DynamicsCompressor** and **WaveShaper** oversampling: aud has neither, so they go through numpy (approximation
  noted above).
- **Band-limited oscillators**: aud's square, saw and triangle alias. Web Audio's do not.
- **Automation and modulation**: aud has `.modulate()` (ring modulation) and `AnimateableProperty` on sequencer
  handles, but X3D AudioParam automation is not in the X3D field set. ROUTEd changes are frozen.
- **aud quirks found** (probes in Blender 5.3.0, 2026-11-27):
  - `Sound.write` wrote 97792 frames for a 96000-frame buffer (buffersize 4096), and 96768 frames with 1024 or 0, the
    extra frames non-zero. The demo writes WAVs with the stdlib `wave` module instead.
  - `Sound.file(...).data()` returned 9984 frames for a 9600-frame WAV.
  - `rechannel(2).limit(0, 0.01)` gave 479 frames, not 480.
  - `Sound.pitch(1.5)` on a sine had no effect.
  - The renderer therefore pads or trims arrays to exactly duration × rate.
- **Not built yet (checkpoint)**: ChannelSplitter output branches, the shelf/peak dB gain, `loopStart`/`loopEnd`,
  processing-node timing, Speaker object transforms from parent Transforms, the bpy import/export wiring, and checks of
  the untested rows above.

## 7. Measurements (2026-11-27, Blender 5.3.0, 48 kHz, 2.0 s renders)

Command: `Blender -b --factory-startup --python tools/sound_bridge_demo.py -- tests/sound/<f>.x3d /tmp/sound_<f>.wav`.

The numbers come from the WAV written (16-bit PCM) and read back with `wave`:

- the FFT is a 1 s Hann window from the first sample above 1e-3, with 1 Hz bins;
- the probe level is the bin at that frequency relative to the dominant bin;
- onset and offset are the first and last sample above 1e-3.

| Fixture | Graph | Measured | Predicted |
|---|---|---|---|
| `osc_lowpass_gain.x3d` | (440 Hz + 4000 Hz) → LOWPASS 1000 Hz, Q 0 dB → Gain 0.5 → AudioDestination (mono) | 96000 frames, 2.0 s; dominant 440.0 Hz; 4000 Hz at −24.9 dB relative to 440 Hz; peak 0.574 | Biquad \|H(4000)\|/\|H(440)\| = −24.9 dB (`biquad_magnitude`); peak ≤ 0.5 × (1.0884 + 0.0616) = 0.575 |
| `merger_two_osc.x3d` | ChannelMerger(440 Hz, 660 Hz × 0.5) → AudioDestination (2 ch) | 2 channels; dominant L 440.0 Hz, R 660.0 Hz; peak L 1.0, R 0.5; cross-channel leak at 660 Hz in L −187.7 dB | L = 440 at 1.0, R = 660 at 0.5 |
| `spatial_delay_window.x3d` | 880 Hz stopTime 1 → Delay 0.25 → SpatialSound gain 0.5 | dominant 880.0 Hz; peak 0.5; onset 0.25 s; offset 1.25 s | 880 Hz, 0.5, 0.25 s to 1.25 s |

All three fixtures validate against `x3d-4.0.xsd` with lxml (`x3d_mcp/.venv/bin/python`).

Tests:

- `python3 -m unittest test_sound_graph`: 19 tests, no Blender.
- `Blender … run_tests_in_blender.py -- test_sound_graph_bpy`: 4 tests. They render the fixtures and the pause case,
  and check the frequency, level and timing figures above.

## 8. Wiring into the importer and exporter (2026-11-28)

**Import** (`import_x3d.place_carried` → `sound_bridge`). Carry finds the audio graphs first (`find_carried`), so the
bridge sees exactly what carry would keep. For each carried item:

- **SpatialSound:** rendered for the scene's frame range (at most 60 s) at 48 kHz, written as 16-bit WAV, loaded and
  packed. A Speaker object is made with `speaker_settings` applied, parented to the object of the nearest Transform (or
  at the top of the scene), at `location`. Its −Z axis points along `direction`; −Z is OpenAL's forward, which audaspace
  follows, but that convention has not been checked by ear or by a mixdown. The XML moves from carry to the Speaker.
- **AudioDestination, StreamAudioDestination:** they stay carried. A sound strip in the sequencer plays the render, at
  the scene's first frame on a free channel, marked `x3d_sound_cache`. The export ignores the strip: deleting it
  changes nothing in the file.
- **A Transform that holds only carried nodes** now gets an Empty (`rebuild_hierarchy`). Before this, carry reported
  "its Transform made no object; not carried" and dropped the node. All three fixtures in `tests/sound/` are shaped
  like that.

**Export** (`extract.py`). A Speaker with `x3d_sound_graph` is not written as a Transform. Its XML, with edits merged
(`sound_bridge.speaker_graph_xml`), joins its parent's carried nodes (or the scene's). From there it is written by the
carry writer, so its DEFs are reserved, USEs are checked and ROUTEs are kept, as for any carried node. The fields
merged are `intensity` (from `volume` ÷ `gain`), `referenceDistance`, `maxDistance`, `rolloffFactor`,
`coneInnerAngle`, `coneOuterAngle`, `coneOuterGain`, `location` and `direction`. A turned Speaker keeps the file's
`direction` length. Deleting the Speaker drops the graph.

**Tests** (`tests/test_sound_bridge_bpy.py`, 10, Blender 5.3.0):

- import → Speaker, its WAV measured: 880 Hz, peak 0.5, sound from 0.25 s to 1.25 s;
- destination → strip (440 Hz dominant, 4000 Hz at −24.9 dB) and the graph unchanged in the export;
- the graph back inside its Transform with the same tags, attributes and nesting;
- edits reach only their fields; a turn writes `direction`; a clamped volume is not an edit;
- deleting the Speaker drops the graph;
- a routed graph and a graph with a USE stay carried;
- a second round trip writes the same file.

Every export validates against `x3d-4.0.xsd`.

**Still open:**

- A mixdown of a placed Speaker (`bpy.ops.sound.mixdown`), to measure distance attenuation against Web Audio's
  INVERSE formula and to confirm the −Z convention.
- Hand-made Speakers as SpatialSound + AudioClip.
- The classic `Sound` node with graph children: it is imported by `importAudio`, which knows only AudioClip.
- The untested rows of section 1: the square, saw, triangle and CUSTOM waves, the other 7 biquad types against
  `biquad_magnitude`, the convolver with a known impulse response, ChannelSelector, WaveShaper and the compressor.
