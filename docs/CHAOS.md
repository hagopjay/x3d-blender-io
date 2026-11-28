# Differential chaos testing

`tools/chaos/differential.py` makes one-edit mutants of small X3D files. Each mutant goes to six judges, and the tool
keeps every case where they disagree or one of them crashes. It is the third family of judges, after the contract and
the oracles in `docs/ORACLES.md`.

The oracles ask whether this add-on keeps a promise. The chaos round asks a different question: what does each tool
in the chain do with a file that is slightly wrong, or legal but unusual? Each mutant is one edit to one of the 12
frozen scenes (`tests/golden`), so any finding names the single change that caused it.

## The judges

| Judge | What it is | Verdict |
|---|---|---|
| own | `source/validate.py` `validate_xml_file`: XML, element names, field tokens | valid or not |
| x3dpy | Web3D's x3d.py 4.0.65.8, strict field types (`validate_with_x3d_py`, which the export gate runs) | valid or not |
| xsd | the Web3D X3D 4.0 XML Schema through xmllint (with `--xsd DIR`) | valid or not |
| schematron | the Web3D X3D Schematron (`tools/schematron`, pinned) | valid or not |
| import | this add-on's importer in bpy | FINISHED, CANCELLED or the exception |
| reexport | the default export of what the import built | ok or the exception |

## The operators (`tools/chaos/mutations.py`)

There are 19. Each makes one change:

- dropping an attribute;
- an extreme number (NaN, INF, -0, 1e39, 2147483648, `--1`);
- truncating a multi-value field;
- an out-of-range index;
- a bool spelt `TRUE`, `1` or `yes`;
- garbage text;
- a duplicate DEF;
- a dangling USE;
- a USE before its DEF;
- a USE of the wrong node type;
- dropping a node;
- duplicating a node;
- swapping two siblings;
- a wrong containerField;
- wrapping a node in a Transform with zero scale or a zero rotation axis;
- nesting the scene 50, 400 or 1,200 Groups deep;
- a different version or profile;
- a DEF that is unusual Unicode or very long;
- a broken or added ROUTE.

## Classes

Every mutant lands in one of these classes:

- `import-crash-on-valid`: the import raised on a file that every validator accepts. This is our bug.
- `import-crash-on-invalid`: the import raised on an invalid file. The import should warn and go on, so this is also
  ours.
- `reexport-crash`: the import worked, and the export of the result raised.
- `judge-crash`: a validator raised instead of answering.
- `judges-disagree`: the validators split. These rows are listed, not gated. Most of them follow from each judge's
  scope: only the XSD and the Schematron know DEF/USE, and only the Schematron knows ordering rules. The interesting
  ones become reports.
- `agree`.

`--fail-on-crash` exits 1 on any crash class:
- the contract job in CI runs 240 mutants on bpy 5.3.0;
- the nightly runs 960 on each Blender line, with a fixed seed plus the run number.

## First round (22 Nov 2026)

Measured with bpy 5.3.0, x3d.py 4.0.65.8, xmllint with the X3D 4.0 XSD that web3d.org served on 22 Nov 2026 (Last-Modified
8 Nov 2026) and the pinned Schematron. The runs used 960 mutants per seed (rng 7, 11, 23), 80 for each frozen scene.

| Run | Crash rows | Signatures |
|---|---|---|
| rng 7, add-on 2.7.1 | 68 of 960 | 5 (below) |
| rng 7 and 11, after the first five fixes | 7 of 1,920 | 3 more, hidden behind the first five |
| rng 7, 11 and 23, 2.7.2 | 0 of 2,880 | 0 |
| rng 7 on Blender 4.5.14 and 5.2.2 (no x3d.py, no XSD), 2.7.2 | 0 of 1,920 | 0 |

**Ours, fixed in 2.7.2** (each has a test in `tests/test_import_chaos_bpy.py`):

1. A bool spelt `1`, `yes` or `TRUE,` ended the import with IndexError. `getFieldAsBool` formats `f[1]` of a one-item
   list in its warning. 35 rows. Blender's own importer has the same line (Likely; read on
   projects.blender.org/extensions/io_scene_x3d main a173dfb0d5, line 804).
2. One coordIndex far past the points made the importer pad the point list up to that index:
   - `5000000` built 5,000,001 vertices for one quad;
   - `2147483647` raised MemoryError.
   The XSD, the Schematron and x3d.py all accept such a file, because none of them checks an index against the point
   count. 9 rows. This one is also in Blender's importer (Likely, line 1824). Now each distinct out-of-range index
   adds one vertex at the origin, and the faces keep their count and order.
3. The same far index on a coloured or textured mesh made `pad_values` pad the colours or texture coordinates the same
   way. 5 rows; this one is ours only.
4. A scale of `1 1 --1` parses as two numbers, and `translateScale` indexed the third. 1 row. This is also in
   Blender's importer (Likely, line 1567).
5. A Viewpoint fieldOfView of INF raised "math domain error". 1 row.
6. A NaN scale imported, and then the re-export raised `LinAlgError` in `matrix_safety.inverted64`. 2 rows.
7. A PointLight radius of -1 (X_ITE's "unlimited") imported, and then the export failed its own x3d.py check, because
   X3D's range is [0, inf). 1 row. It is now written as 1e9, with a warning.
8. The x3d.py validator walked a scene 1,200 Groups deep by recursion and raised RecursionError. 21 rows. It now
   uses an explicit stack.

**Our validator was too lenient** (fixed; `tests/test_validate_semantic.py`):
- It read SFBool as `text.lower() == "true"`, so `TRUE`, `1` and `yes` passed, as false.
- It did not check the width of SFVec3f, SFRotation or SFColor values, or that an MF vector list is a whole number of
  values.

**Other judges:**
- x3d.py 4.0.65.8: `assertValidSFVec3f` and six other fixed-width checks accept the wrong number of components
  (`Box(size=(1, 1))` writes `size='1 1'`), while the matching `isValid` functions say no (Confirmed). Drafted as
  Web3D report 04; held.
- The Schematron judge cannot read a file nested more than 100 elements deep. SaxonC's XML parser stops at
  `jdk.xml.maxElementDepth` 100, so for such a file the judge gives no verdict rather than a pass.
- Disagreements that follow from each judge's scope, so not bugs:
  - DEF/USE checks: only the XSD and the Schematron have them;
  - zero rotation axes: only the Schematron objects;
  - head and Scene order: only the XSD checks it;
  - index values below -1: only x3d.py rejects them.

## Second round (2.7.3, 22 Nov 2026): the export side, the round trip and hostile files

The first round only mutated files. The second adds two more tools, a shrinker, and the guards they asked for.

### The tools

| Tool | What it does | Gate |
|---|---|---|
| `tools/chaos/scene_chaos.py` | Builds one of the 12 frozen scenes in bpy and applies one of 22 edits to the Blender scene (below). It exports with random options (version 3.3/4.0/4.1, units, scale, triangulation, path mode, ...), judges the file (own validator, x3d.py, XSD, nan/inf tokens), then imports it and checks the **fixed point**: import, export with defaults, import, export again. The last two exports, in canonical form, must agree. | contract job: 46 cases (`--per-op 2`); nightly: 276 x 2 seeds on every Blender line |
| `tools/chaos/hostile.py` | 67 hostile files, each imported and re-exported in its own process under a 6 GB memory limit, a 2 GB file-size limit and a 90 s timeout. A local HTTP server counts network hits, and a sentinel file detects disclosure into names, custom properties or text blocks. A traceback, a hang, a network hit, a disclosure or more than 64 MB written fails the case. | contract job: all 67; nightly: all 67 in each Blender binary |
| `tools/chaos/shrink.py` | Delta debugging: removes elements, then attributes, then halves of value lists, while the crash signature stays the same. `differential.py --shrink` shrinks one example per crash group. | the planted bool crash shrank from 1,884 to 248 bytes in 32 imports |

The 22 scene edits: extreme vertices (NaN, INF, 1e30), all vertices at one point, an empty mesh, one vertex, odd names
(Hebrew, empty, a byte-order mark, `a<b>&'"c`, 64-character), colliding names, many material slots, out-of-range
material values, broken textures (no image, a folder, a missing file), extreme and zero scales, 200 or 1,500 parents
deep, shape keys, modifiers, extreme cameras and lights, animation (fps 1/1000, long timelines), custom properties,
attributes, other object types, collections, linked data and custom normals.

The hostile files: expansion (billion laughs, quadratic blow-up, a 1.5 GB gzip bomb, gzip in gzip, an Inline fan-out
of ten per level five levels deep), disclosure and network (XXE file, text and parameter entities, an external DTD,
XInclude, Inline, ImageTexture and Script URLs on the network or on `/dev/zero`), recursion (Inline self and cycles,
USE inside its own DEF, PROTO self and mutual instances, 5,000 and 100,000 nested Groups, 2,000 nested Transforms),
broken bytes (truncated, UTF-16 declared as UTF-8, Latin-1, NUL bytes, a BOM only, a PNG renamed, not gzip, no X3D
root, two Scenes), numbers (5,000-digit ints and floats, 1e999, a 1 MB name, a 100,000-character element name,
100,000 attributes, 100,000 strings, 2 million points, a ROUTE flood), budgets (huge or negative ElevationGrid,
Sphere/Cylinder subdivision 0 and huge, a huge or short PixelTexture, a 47,000 s animation, `08` as an index, NaN in
points), and 11 classic VRML cases.

### Classes

Scene chaos: `export-crash`, `export-refused`, `judge-crash`, `export-invalid`, `export-bad-number` (a nan or inf
token), a crash or refusal at each later step, `fixed-point-drift`, and `ok`. All of these are gated. Listed, not gated:

- `float32-noise`: the last digit of a float32 moved (relative 1e-6, absolute 2e-5). Lines are aligned first (difflib),
  so one added line is reported as itself.
- `budget-resampled`: the export hit its animation sample budget and said so.
- `float32-range`: a 1e30 or 1e-30 location or scale, or inf, which Blender's float32 matrices cannot carry through a
  parent.
- `info-meta-names`: the `info` meta lists Blender datablock names, which Blender suffixes on import (`.001`).

### Measured

bpy 5.3.0 unless named; x3d.py 4.0.65.8; xmllint with the X3D 4.0, 4.1 and 3.3 XSDs. The "before" rows ran the 2.7.2
source (903c1e5) through the same judges (`X3D_ADDON_SOURCE`).

| Run | Gated | Signatures |
|---|---|---|
| Scene chaos rng 7, 2.7.2 | 35 of 276 (7 export crashes, 1 NaN written, 27 drifts) | 9 |
| Scene chaos rng 7 and 11, 2.7.3 | 0 of 552 | 0 |
| Scene chaos rng 23 (a seed no fix was made from), first 2.7.3 build | 2 of 276 | 2, both fixed |
| Scene chaos rng 7, 11 and 23, 2.7.3 final, with the XSD | 0 of 828; listed: 206 float32-noise, 3 budget-resampled, 2 info-meta-names, 1 float32-range | 0 |
| Scene chaos rng 7 quick, Blender 4.5.14 and 5.2.2 | 0 of 46 each | 0 |
| Hostile files, 2.7.2 on Blender 5.2.2 | 26 of 67 | 20 |
| Hostile files, 2.7.3 on Blender 5.2.2 and on bpy 5.3.0 | 0 of 67 each (96 s for all 67; slowest 14 s) | 0 |

**Ours, fixed in 2.7.3** (tests in `tests/test_chaos_round2_bpy.py` and `tests/test_chaos_round2.py`):

1. **A texture on `/dev/zero` filled the disk.** The re-export with path mode COPY copied the image file, and
   `bpy_extras.io_utils.path_reference_copy` (Blender core) copies a device forever; the first run filled a 50 GB disk.
   `source/file_safety.py` now copies only regular files, in chunks, within 4 GiB per export
   (`BLENDER_X3D_MAX_COPY_BYTES`). The import also refuses to read devices, pipes, sockets and folders.
2. **Entity declarations ended the import with a traceback.** Billion laughs, the quadratic blow-up and the three XXE
   files were refused (safely) by raising out of the operator. The import now cancels with the reason as a warning.
3. **Broken bytes ended the import with a traceback**: truncated files, NUL bytes, a BOM only, a PNG renamed, gzip in
   gzip. Now a clean cancel: "Not a well-formed X3D file, not importing ...".
4. **UTF-16 and Latin-1 files did not import.** The XML is now read as bytes: a UTF-16 BOM is honoured, and bytes that
   are not UTF-8 are read as cp1252, with a warning. An encoding name Python does not know is read as UTF-8.
5. **Classic VRML**: an Inline was loaded twice and then raised TypeError, an Inline of itself or a cycle did not stop,
   and 5,000 nested Groups raised RecursionError in the PROTO, DEF and ROUTE tables (now loops).
6. **Deep files**: 100,000 nested Groups raised RecursionError (the import now runs with a recursion limit of 50,000),
   and each node's world matrix was recomputed from the root, quadratic in depth (now cached).
7. **Inline fan-out**: 100,000 Inline loads ran past 90 s. At most 1,000 per import load (`BLENDER_X3D_MAX_INLINES`); the
   rest stay as marked empties. Each Inline file also deselected every object and updated the whole depsgraph; both now
   happen once per import. 90 s or more became 6 s.
8. **A count in the file set an allocation** (`source/budget.py`): ElevationGrid dimensions, Sphere/Cylinder/Cone
   subdivision (0 divided by zero; 50,000,000 used 5 GB; 4,096 x 4,096 still crashed at 6 GB, so the clamp is
   [3, 1,024]), PixelTexture width x height, and key counts. Over 16,777,216 elements a node is skipped with a warning
   (`BLENDER_X3D_MAX_ELEMENTS`).
9. **A long animation grew every round trip.** A 48-key, 47,000 s animation came back as 1,048,574 keys (48 MB), and
   the next import did not finish in three minutes. The export samples at most 10,000 frames
   (`BLENDER_X3D_MAX_ANIMATION_SAMPLES`), and the import keeps at most 65,536 keys per object.
10. **Numbers**: a NaN or INF field value now gives the field's default with a warning, and `08` is read as 8 (it was
    read as an octal literal and refused).
11. **Export crashes** (7 in the rng 7 baseline, 2 more in other seeds):
    - a material index past every slot (KeyError, X3D 3.3; now clamped to the last slot);
    - a triangulated X3D 3.3 mesh with two materials (TypeError: the triangle loop ran past the face count);
    - Metallic or Roughness outside [0, 1] (2.0, 1e6, 1e39): the export gate refused the file; now clamped;
    - 1,500 parents deep (RecursionError in the world-matrix walk, now a loop);
    - an Image Texture node with no image (AttributeError, X3D 3.3).
12. **NaN and INF written into X3D 3.3 files**: a NaN vertex or a -inf scale was written as `nan` or `inf`, which x3d.py
    accepts and no browser reads. The 3.3 writer now writes 0 and logs the count.
13. **Round-trip drift, each now a fixed point:**
    - an IndexedFaceSet without texture coordinates gained them after one round trip: the import makes the spec's default
      ones, and the export wrote them back (20 of 276). The import marks them with a fingerprint
      (`source/default_uv.py`); the export leaves them out while they are unchanged.
    - a half turn about A is a half turn about -A, and float32 picked either (6 of 276). One spelling now: angle in
      [0, pi], and at pi the axis whose first non-zero part is positive.
    - a zero scale on one axis lost the rotation (0.7653 rad, then 0.4832): Blender's decompose() makes the flat axis up.
      `matrix_safety.decompose_exact` rebuilds it from the other two, on import and on export.
    - the 3.3 writer kept `<`, `>`, `&`, a byte-order mark and `-` in a DEF that the 4.0 writer spells `_`, so the name
      changed on the next trip. Both writers now spell DEFs the same way.

**Judges fixed:** the XSD judge now passes `--huge` to xmllint (a 1,500-deep export is past libxml2's default depth of
256, which it reported as invalid).

**Outside findings, recorded, not sent:**

- Blender core `bpy_extras.io_utils.path_reference_copy` copies a non-regular file (`/dev/zero`) until the disk is full
  (Confirmed through this add-on; Likely in every exporter that uses it with path mode COPY).
- x3d.py 4.0.65.8 accepts `nan` in a Coordinate `point` (Confirmed).
- On the bpy 5.3.0 wheel, 100,000 nested Groups raised RecursionError in 2.7.2; in the Blender 5.2.2 binary they did not
  (a bigger default stack, Suspected).

**Known, listed for 2.7.4:** depth is still quadratic in places (1,000 levels 1.3 s, 2,000 about 16 s, 5,000 about
121 s); the remaining hot spots are the per-node ancestry scans in the importer and `exported_parent` in extract.

## Third round (2.7.4, 23 Nov 2026): the rules the receipt-to-rule engine found still live

This round had no new mutator. The receipt-to-rule engine (x3d.loom `kit/loomkit/r2r`, loom #164) read the 2.7.1
crash receipts, induced 28 candidate rules ("an IndexedTriangleSet index past the points with a Color child crashes"),
and replayed them on 2.7.3. Six rules still crashed, and its sweep of 514 real files found two more failing files.
Each was reproduced on 2.7.3 main (8e56437), fixed, and kept as a `replay` case in `tools/chaos/hostile.py` (so the
contract job gates it) and a test in `tests/test_chaos_round3_bpy.py`.

| Rule (grade from the engine) | 2.7.3 signature | Fix in 2.7.4 |
|---|---|---|
| A triangle set on CoordinateDouble (2 real files) | AttributeError at `importMesh_ReadVertices` | Every geometry reads Coordinate or CoordinateDouble (`COORDINATE_SPECS`); one with neither has no vertices, with a warning |
| A MetadataBoolean (1 real file; the engine also explained it as "a USE before its DEF", Suspected, the same file) | the export refused: `could not convert string to float: 'true'` | The semantic check (`validate._coerce_field`) reads MFBool as true/false; it read it as numbers, so every MetadataBoolean and BooleanSequencer keyValue was refused |
| An IndexedTriangleSet index past the points, with Color | IndexError at `importMesh_ApplyColors` | Each distinct out-of-range index is one added vertex at the origin (as `validate_points_field` does for IndexedFaceSet); a vertex past the colours is white |
| The same in an IndexedTriangleStripSet, with Color or TextureCoordinate | IndexError at `ApplyColors` / `ApplyUVs` | Same, and texture coordinates are padded with (0, 0) |
| An IndexedTriangleFanSet of three or more fans | RuntimeError at `importMesh_IndexedTriangleFanSet` | The third fan restarted at the wrong index (`i = j + 2`, not `i + j + 2`); strips and fans are now split at -1, and a run under three indices is dropped |
| An IndexedFaceSet with few indices and many points (the vertex cull path) and an index past the points | IndexError at `importMesh_IndexedFaceSet` | The cull path reads such an index as one vertex at the origin, as the uncut path does |

Also: the triangle sets clean their index field (`clean_index_field`), an IndexedTriangleSet drops a triangle that has
-1, a stripCount or fanCount past the vertices stops at the last one (a count of two billion no longer builds a list
that long), and a Normal list of the wrong length is padded or cut instead of failing `foreach_set`.

### Measured

bpy 5.3.0; the "before" column ran the 2.7.3 source through the same judge (`X3D_ADDON_SOURCE`).

| Run | 2.7.3 | 2.7.4 |
|---|---|---|
| The 8 repro files (6 rules, 2 real files), import then re-export, each under a 6 GB limit | 8 of 8 crash | 0 of 8 (Confirmed) |
| The 6 `replay` hostile cases | 6 of 6 findings (the three-fan case also took 35 s and 4.4 GB before raising) | 0 of 6 (Confirmed) |
| All hostile files (67 from round 2 plus the 6 `replay` cases) | | 0 of 73 (Confirmed) |
| Scene chaos rng 7 and 23, per-op 2 | | 0 gated of 46 each (Confirmed) |
| Scene chaos rng 11, per-op 2, first 2.7.4 build | | 1 gated of 46: `export-invalid`, fixed below; then 0 of 46 (Confirmed) |
| Full bpy test suite with strict validation | 1,075 tests | 1,082 tests, OK (Confirmed) |

**One more, from scene chaos (rng 11).** An Alpha of 1e39 on a Principled BSDF (Blender stores float32 max) wrote
`transparency="-340282346638528859811704183484516925440.000"` in the X3D 3.3 writer, which x3d.py refuses
(`assertZeroToOne`) and which has no export gate. The 3.3 writer now clamps transparency and shininess to [0, 1], NaN
giving the default. The X3D 4 writer was already gated.

**What the engine taught this round** (Likely): a rule replayed on the next release is a regression test that writes
itself. Five of the six live rules were one fault each; the sixth (MetadataBoolean) was also explained, at Suspected,
by a second rule on the same single file ("a USE before its DEF"), which the fix closed too. One file behind a rule is
not enough to tell which of its features is the cause; the engine said so by grading it Suspected.

## Fourth round (2.9.1, 28 Nov 2026): the receipt-to-rule weekly run

The engine's weekly run (x3d.loom #240, `runs/r2r-weekly-20261128/`) replayed every kept rule on 2.9.0 against 2,300
real files. Nothing regressed from 2.7.4, and it found four old defects, all Confirmed on 2.9.0 and 2.7.4. 2.9.1
fixes them; tests are in `tests/test_chaos_round4_bpy.py`.

| Defect | 2.9.0 | 2.9.1 |
|---|---|---|
| A Sound whose source is an OscillatorSource, or an empty `<Sound/>` (real file: x3d.loom `x3d.threejs/bridge/fixtures/Sound.x3d`) | AttributeError in `importAudio`: the url was read before the None check | a speaker with no sound, and a warning naming the source that is not imported |
| An Extrusion whose crossSection points are all equal (real file: x3d.ml `obj-05.x3d`, written by a language model), or one point | ZeroDivisionError / TypeError | skipped with a warning (it sweeps no surface); a flat cap no longer divides by zero |
| Animation export: every object sampled at every frame, the parent inverted once per child per frame, and float32 noise read as motion | x3d.loom `0-0-feel-lab.x3d` (67 KB, 5 interpolators) exported as 45.5 MB in 36 s | 1.6 MB in 5 s (bpy 5.3.0, Confirmed) |
| A bold or italic Text entered edit mode, and each mode switch evaluated every text | `segment-sphere.x3d` (646 Text, 2 bold) imported in 23 s here (43 s in the weekly run) | 3.1 s (Confirmed) |

The export now samples only an object that can move: it, or an ancestor between it and its exported parent, has an
action, NLA tracks, drivers, constraints or a rigid body (or its parent moves it through a bone or vertex). It inverts
each parent once per frame, and a channel within float32 noise (relative 1e-6, absolute 1e-7) of its first value is
still. One test changed for this: the behaviour-presets acceptance test expected a scale interpolator on a turning
Door, which was float32 noise in its scale.

**Tried and not kept**: thinning keys that the interpolators reproduce from their neighbours (lerp, slerp) took the
same level to 0.66 MB, but it broke the round-trip fixed point: the re-export picked slightly different keys (the
suite's orbiting child, 108 then 105 values). A thinning that is a fixed point is listed for a later round.

| Run (bpy 5.3.0 unless named) | 2.9.1 |
|---|---|
| The two real crash files (Sound.x3d, obj-05.x3d), each under a 6 GB limit | 2 of 2 crash on 2.9.0, 0 of 2 on 2.9.1 (Confirmed) |
| Hostile files, with 2 new `replay` cases for the two crashes | 0 of 75 (Confirmed) |
| Scene chaos rng 7, 11, 23 (per-op 2) | 0 gated of 46 each (Confirmed) |
| Full bpy test suite with strict validation | 1,709 tests OK (Confirmed) |
| Export suite on Blender 5.2.2: conformance, fixed point with the first-trip budget, invariants, mapping check | 148 of 148; PASS; PASS; PASS (Confirmed) |
