# Gallery 27: the X3D event machine

## The idea
A teaching world for someone learning X3D's behaviour graph. Eight labelled stations sit on a snaking path (two rows of
four), one node type each, with the node and field named in 3D Text at every stage. Click the green button and ONE event
relays station to station. Between stations a glowing bead rides a wire while that hop is live, and a small label on each
wire names the ROUTE chain it stands for. Each stage lasts 3 s and each wire 2.5 s, deliberately slowed (real events are
instant) so you can follow them.

## The graph in one paragraph
`TouchSensor.isActive` -> `BooleanFilter.set_boolean` -> `inputTrue` -> `TimeTrigger` -> `T1.startTime`. Every later hop is
the same real chain: `Tk.isActive` -> `BooleanFilter.inputNegate` (the falling edge) -> `TimeTrigger.triggerTime` ->
`Wk.startTime` (the wire clock), then `Wk.isActive` falling -> `BooleanFilter` -> `TimeTrigger` -> `T(k+1).startTime`. Each
`Tk.isActive` also lights its plinth (`visible`). Stations: 1 TouchSensor (ring + flash via PositionInterpolator and
ColorInterpolator), 2 BooleanFilter (two doors slide, an orb glows), 3 TimeSensor (`fraction_changed` grows a bar, three
BooleanSequencer lamps), 4 PositionInterpolator + ColorInterpolator (bouncing, recolouring cube), 5 OrientationInterpolator
(two turns), 6 BooleanSequencer (six bulbs, one lit at a time), 7 PositionChaser (a flag jumps through `set_destination`, the
ball glides after it), 8 ColorInterpolator -> ColorChaser (plate colour) plus eight sparks. 138 nodes, 163 ROUTEs, 101 ROUTE
sources, procedural (`build.py`), no assets.

## How to play
Import `gallery-27-x3d-learn.x3d` with the behaviour graph, press Play, click the green button on the first station (back
left). The run takes about 42 s. Clicking again after it ends replays it; clicking mid-run starts a second overlapping relay
(stage 1 is idle again), which is harmless but muddled. Esc stops and restores everything.

## Checked
| What | Number | Instrument |
|---|---|---|
| `check` | 138 nodes, 163 ROUTEs, 101 ROUTE sources (= `streams`) | `tools/behaviour_demo.py check` |
| Host-eyes | pass (grade C, as for the other demos), `not_applied` empty, restored, overlaps 0 | Blender 5.3.0 window, show run 3 of 3 |
| act_ok | true on all three runs | `act.py` in the live window |
| Stage lamps | all 8 lit, in order 1..8; beads 1..7 seen | polled 4 Hz |
| Station effects | fill bar scale 0.01 -> 1.0; cube height 1.0 -> 2.61 m; spinner turned 3.1 rad max; 6 of 6 bulbs seen; ball x -4.2 -> -1.8; 8 sparks at once | world transforms read from Blender |
| Second click | one ray-checked click on the button (1 candidate point, hit `Start`) restarted stage 1 | `scene.ray_cast` + event queue |

Runs 1 and 2 passed too; run 1's camera was too far (the machine filled a third of the frame), run 2's too close (stations
7 and 8 were clipped), so I changed the layout to two rows and the camera before run 3. The act measures that effects
START from rest, not their arcs.

## Not checked
- No X_ITE trace or judge: `judges` is empty and no `x_ite.json` exists. The relay was NOT compared event for event against
  X_ITE, and the sim-vs-X_ITE `judge` was not run.
- Mutants were not run, and the full Blender test suite was not run.
- Look: in the 1600x1000 window the whole machine is in frame, but the small station labels are hard to read in the
  screenshots (the title is clear), and everything shows the importer's selection outline. Not checked at other window sizes.
- The labels were not checked for overlap beyond looking at stage 4 and 7 screenshots.
- ColorChaser plate colour was not measured (only that the plate stays routed); stage 8 is judged by the sparks.

## Findings for Loom
1. The camera frame is 16:9 and the eye-test viewport is the left half of a split window, so a scene meant to be read
   needs about 28 units across at the camera: two runs went to framing alone (screenshots `1-import` of runs 1 and 2).
2. A chain of TimeSensor -> BooleanFilter.inputNegate -> TimeTrigger -> startTime relayed 8 stages with no ROUTE ignored
   (`not_applied` empty, stage order 1..8), so the falling-edge idiom works in Play.
3. Text nodes import as Blender FONT objects that follow their parents and hold their position, but they take the
   importer's selection outline like everything else, which hurts legibility.
