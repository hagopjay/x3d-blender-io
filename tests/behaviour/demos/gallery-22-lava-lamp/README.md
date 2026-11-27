# Gallery 22: lava lamp

**Idea.** A lava lamp in a dark room: seven glossy blobs (spheres that squash and stretch as they move) rise and sink in a
glass-framed tank on slow, mutually prime clocks, each trailed by a small droplet. The lamp's light, base glow and a dim
backdrop change colour. Three buttons on a console: **HEAT** (fast clocks), **COOL** (slow clocks), **COLOUR** (next palette).

**Graph.** Per blob: a slow `TimeSensor` (23, 29, 31, 37, 41, 43, 47 s, all prime) and a fast one (5, 7, 11, 13, 17, 19, 23 s,
all prime, `enabled=false`) feed the same pair of PositionInterpolators: `Path` (the height, with a sideways wobble) and
`Squish` (the `scale`: stretched while moving, flat at the turns). Each goes through a PositionChaser (so switching clocks
never makes a blob jump) into the blob's `translation` and `scale`; a third chaser makes the droplet trail the blob.
`HeatF` and `CoolF` (BooleanFilters on the button TouchSensors) enable one set of clocks and disable the other by ROUTEs
to `enabled`: `inputTrue` of one button and `inputFalse` of the other, so either button is safe to press twice. COLOUR:
four BooleanSequencers count the presses in step (`next`); sequencer *p* says "palette *p* is current" and enables
`PalClock p`. That clock drives 7 + 2 ColorInterpolators (each blob walks the four palette colours, offset by its number,
so neighbours blend) into ColorChasers (`Skin0..6`, `LampTone`, `BackTone`, 2.2 s), which fan out to the blobs' and
droplets' `baseColor` and `emissiveColor`, the PointLight `color`, the bulb, the console button, and a dim backdrop and
pool. A BooleanToggle lights a spark on the COLOUR button; two pilot lamps show HEAT or COOL. 145 nodes, 224 ROUTEs,
111 ROUTE sources, built by `build.py`.

**Play.** Import with "Behaviour graph" on, press Play. Click the red button (left) for HEAT, the blue one (middle) for COOL,
the third (it wears the lamp's colour) for COLOUR. Esc stops.

## Checked

| What | Instrument | Result |
|---|---|---|
| Live window | `tools/behaviour_demo.py show gallery-22-lava-lamp`, Blender 5.3 | Host-eyes **pass**; `act_ok` true; `not_applied` empty |
| HEAT / COOL | summed height change of the 7 blobs per second of the player clock (world positions, 8 s windows, after 3 s to settle) | COOL 2.2 m/s, HEAT 6.4 m/s (2.9x), COOL again 1.87 m/s |
| COLOUR | lamp light colour read from Blender data after each of 3 presses + 4 s | (1.0, 0.31, 0.10) magma, then (0.27, 0.53, 1.0), (0.11, 1.0, 0.38), (0.67, 0.46, 1.0); largest channel change 0.9 |
| Look | screenshots read by eye (`act-*.png`) | blobs of different sizes, stretched and flattened, in the same hue as the backdrop and lamp; the buttons wear the colours |

## Not checked

- X_ITE judging: none (`judges` is empty; no trace recorded).
- The solid viewport shows `baseColor`, ignores scene lights and draws transparency opaque, so I could not see a glowing tank,
  a lit room or real glass. The room is dark only as far as the harness window's own background lets it be. A translucent
  glass cylinder hid every blob (opaque in the viewport), so the glass is a frame of 8 rods and two rings of boxes.
- Whether the blobs "merge": they overlap and share colours, nothing deforms into each other.
- The act ran 3 COLOUR presses, so the fourth palette wrap-around (back to magma) was not seen.
- Speed numbers are noisy: the player steps at ~5 Hz and the chasers lag 1.6 s.

## Findings for Loom

1. **X3D 4 `PhysicalMaterial` defaults to `metallic=1`**; imported as is, every shape without `metallic="0"` drew black
   in the viewport (my first run's blobs were near black). Evidence: the saved .blend read Metallic 1.0 on materials with no `metallic` field.
2. **Transparency is not drawn as blending in the solid viewport**, so a `transparency="0.9"` glass cylinder hid its contents (screenshot of the second run).
3. **`BooleanFilter.inputFalse` makes a clean "other button released" signal** for exclusive modes: two buttons set each
   other's clock groups on/off with no state node, in Play (COOL, HEAT, COOL in the act).
4. **A looping TimeSensor with `enabled=false` imports with an INFO "play-once, disabled or delayed start is not kept"**
   for each such timer (Fast0..6, PalClock1..3), yet Play enables them by ROUTE and they run (the speeds above).
5. **Four BooleanSequencers fed the same `next` stay in lock step** and act as a one-hot decoder of a press counter.
