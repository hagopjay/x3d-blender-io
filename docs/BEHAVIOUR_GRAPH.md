# X3D behaviour graph (proof of concept)

An X3D scene's behaviour (sensors, timers, interpolators, event utilities, followers and the ROUTEs between them) as an
editable graph: plain Python data, a Blender node tree, and X3D text, kept in step.

| File | What it is |
|---|---|
| `source/behaviour_catalogue.py` | generated from the X3D Unified Object Model 4.0 by `tools/behaviour_catalogue_gen.py` (`--check` fails when stale): 45 behaviour node types with 303 fields, 32 target types |
| `source/behaviour_graph.py` | the graph without Blender: parse from X3D, validate, edit, emit, weave into a document, compare, lay out, JSON; and the scripting methods (`Behaviour`, `add`, `target`, `>>`) |
| `source/behaviour_nodes.py` | the Blender node tree `X3DBehaviourTree`: one node class per X3D node, one socket class per field type; `apply`, `read`, `target`, `import_graph` |
| `tools/behaviour_roundtrip.py` | import a file with its graph, optionally set fields, export, print the graph difference |
| `tools/behaviour_replay.cjs` | play the same real mouse clicks on two files in X_ITE and compare what the scene did |
| `tests/test_behaviour_graph.py`, `tests/test_behaviour_nodes_bpy.py` | 23 plain-Python and 17 Blender tests |
| `tests/behaviour/` | `route-demo.x3d`, the three Wire Lab worlds, and `route-cases.json` (55 ROUTE legality cases shared with the browser Wire Lab) |

## Use

* Import: tick "Behaviour as node graph" (off by default). The scene gets a node tree in `scene.x3d_behaviour_tree`.
* Edit: node editor, tree type "X3D Behaviour". A link between two field types is removed as it is made.
* Export: a scene with a tree writes it. A scene without one exports exactly as before.
* Script (no window needed):

```python
from io_scene_x3d import behaviour_graph as bg, behaviour_nodes as bn   # the package name depends on the install

b = bg.Behaviour()
click = b.add("TouchSensor", "Click", parent="Door")
timer = b.add("TimeSensor", "Timer", cycleInterval=2)
slide = b.add("PositionInterpolator", "Slide", key=[0, 1], keyValue=[(0, 0, 0), (0, 2, 0)])
door = bn.target(b, bpy.data.objects["Door"])
click.touchTime >> timer.startTime
timer.fraction_changed >> slide.set_fraction
slide.value_changed >> door.translation
bn.apply(b, bpy.context.scene)
```

## Rules the exporter keeps

1. Illegal ROUTEs are left out and named in a head `meta` line.
2. The graph's names are reserved before any other DEF: a node called `Timer` is `Timer` in the file.
3. A target is written under its name in the graph (for an imported file, the DEF it came with).
4. A ROUTE whose target is not exported is left out and counted in a head `meta` line.
5. Keyframes of an object the graph drives are not sampled into a second set of interpolators.

## Measured (22 Nov 2026; Blender 5.3.0 bpy wheel, Python 3.13.18, x3d.py 4.0.65.8, X_ITE 16.7.1 headless)

| File | ROUTEs | Default import path, re-exported | Graph path, re-exported |
|---|---|---|---|
| route-demo.x3d | 22 | 24 ROUTEs; 9 nodes with changed fields, 1 node added | 22; no difference |
| door.x3d | 3 | 2; all 3 nodes and 3 ROUTEs lost | 3; no difference |
| counter.x3d | 5 | 0; all 4 nodes and 5 ROUTEs lost | 5; no difference |
| snake.x3d | 6 | 2; all 4 nodes and 6 ROUTEs lost | 6; no difference |

Behaviour replay with real clicks: door identical before and after the Blender trip; counter differs, because the importer
does not read `visible` on a Transform (lamps that start hidden come back shown). That loss is not fixed here.

## Limits

Nobody has looked at the editor on a real screen (all runs headless). Field values are X3D text in the file's axes.
Nothing plays inside Blender. XML encoding only on import. Scripts and PROTOs are carried as XML, not edited. Targets are
Transform, Viewpoint, lights and materials. Names survive only for what the graph touches. The importer's loss report
still prints "ROUTE not imported" for ROUTEs the graph kept.
