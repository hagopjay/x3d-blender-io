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
