# Keeping the import and the export in sync

The add-on has two halves that must agree: the X3D **export** (Blender → X3D) and the X3D **import** (X3D →
Blender). Each half can be correct alone and the pair still lose data: the export writes something the import reads
differently, or the import builds something the export writes back differently. This page is the protocol that keeps
them together, and the reasons for it.

## The property: a round trip converges in one step

Let `E` be export and `I` be import, both with the same options. For a file `F0` that this add-on wrote:

- **Convergence (enforced, CI):** `E(I(E(I(F0))))` equals `E(I(F0))`. The second round trip changes nothing: numbers
  within tolerance, every element, field and DEF name. A round trip that does not converge damages the file a little
  more on every save. The six fixed findings S1-S6 in `parity.json` were all of this kind or caused it.
- **Fidelity (measured, reported):** `E(I(F0))` against `F0`. What one round trip changes. Every difference is either
  fixed, or listed in `tools/io_sync/parity.json` as *open* (with an owner decision if one is needed) or *by design*.

Convergence is the gate because it has no false positives: whatever the import does to a file, doing it twice must
change nothing more. Fidelity needs judgement (a written-out default, renumbered indices), so it is a ledger, not a
gate.

## The instruments

| Tool | Needs | What it does |
|---|---|---|
| `tools/io_sync/fixed_point.py SUITE_OUT OUT` | Blender | imports each export-suite file and exports it twice with the file's own options; writes `summary.txt` / `summary.json`; exit 1 when E1 → E2 is not empty |
| `tools/io_sync/x3d_diff.py A B` | Python | structural diff: children paired by DEF, then by what they hold, then by position; numeric tolerances; `--strict-defs` |
| `tools/io_sync/check_parity.py FILES` | Python | every element in real exports is declared in `parity.json` |
| `tests/test_io_parity.py` | Python | every element the emitter's source can write is declared, every declared import exists, every fixed asymmetry names a test |
| `tests/test_io_sync_bpy.py` | Blender | one failing-first test per fixed asymmetry |

CI (`suite` job) builds the 195-case export suite, then runs `check_parity.py` and `fixed_point.py` on it.

Run it locally (about 30 s):

```bash
blender -b --factory-startup --python tests/suite/x3d_test_suite.py -- --out /tmp/suite --repo "$PWD" --export
python3 tools/io_sync/fixed_point.py /tmp/suite /tmp/io-sync --blender "$(which blender)"
```

## The protocol for a change

1. **A change to one side names the other.** A new field or element in the export says how the import reads it
   back, and the reverse. `parity.json` is where that is written down; `test_io_parity` fails until it is.
2. **Decorations are undone where they are made.** When the export adds a prefix, suffix or wrapper (`OB_`, `MA_`,
   `LA_`, `CA_`, `ME_`, `_colour`, `_lines`, `_skin`), the import removes exactly that pattern, so names do not grow.
   Strip only the export's own pattern (`LA_X` inside `OB_X`), never a prefix alone, so a hand-written `LA_Lamp`
   keeps its name.
3. **An option means the same on both sides.** `color_space=AS_IS` on export and on import must be inverse
   operations for every colour the option touches (S2 was an option whose two halves disagreed on vertex colours).
4. **State the export reads, the import sets.** If the export samples `frame_start..frame_end`, the import sets
   them (S3). If the export writes DEF/USE for shared data, the import shares the data (S4).
5. **Blender's storage limits are tolerances, not bugs, and they are documented.** Custom normals are 16-bit angles:
   `Normal.vector` compares at 1e-3 (`x3d_diff.FIELD_ABS`). Anything else compares at 1e-4.
6. **Fix with a failing test first.** The test fails on the code before the fix, and the asymmetry's entry in
   `parity.json` names it.
7. **A decision that changes behaviour for every user is the owner's.** Such items stay *open* in the ledger, with
   the decision written next to them, until the owner decides. (The flat import, A1, waited for one; the owner chose
   to keep the hierarchy, and it became S7 with the old behaviour one option away.)

## Practices that carry over to any pair of readers and writers

- **Test the fixed point, not just the pair.** `read(write(x)) == x` needs an equality on the in-memory model, which is
  hard to define for a scene. `write(read(write(read(f)))) == write(read(f))` only needs a file comparison, and it
  finds the drifts that accumulate: names, colour conversions, timelines.
- **Use the writer's own conformance corpus as the reader's input.** Every feature the writer is tested on is then a
  round-trip case without writing a second corpus.
- **Compare structurally, pair by identity.** A positional diff turns one missing node into hundreds of differences.
  Pair by stable identity (DEF), then by content signature, then by position.
- **Keep a manifest of the surface,** generated from the code where possible (the emitter's element names), checked
  against real output (CI exports), and with an explicit status per entry: exact, equivalent, lossy, unmeasured.
  "Unmeasured" is a status, so gaps are visible rather than assumed.
- **Keep a ledger of known differences with an owner and a test.** A difference is fixed (with a test), open (with
  what it would take), or by design (with the reason). A new difference that is none of these fails CI.
- **Make conversions explicit and paired.** Every colour-space, unit or axis conversion has one function per side,
  named for its inverse, and a test that composes them.
- **Run both directions on the same options.** Report option-dependent differences separately from real losses (the
  first measurement here reported every Normal node of the main suite file, 169, as lost; the second export only had
  `use_normals` off).

## Status (18 Nov 2026, Blender 5.1.0, export suite on main 1e661a5)

| Profile | E0 → E1 differences: main → import fixes → hierarchy | E1 → E2 (DEFs compared literally): main → now |
|---|---|---|
| main (4.0, hierarchy, animation, normals) | 946 → 278 → 221 | 287 → 0 |
| crease (4.0, creaseAngle, AS_IS colours) | 427 → 82 → 65 | 262 → 0 |
| x41 (4.1 draft, GaussianSplats) | 462 → 164 → 98 | 261 → 0 |

"main" is 1e661a5 measured with the same tools (`fixed_point.py`, tolerances 1e-4, Normal 1e-3). Compared
leniently (a DEF spelled differently is not a difference), E1 → E2 was 27, 7 and 6 on main: most of the strict count
is names that grew by one prefix or suffix per round trip.

What remains in E0 → E1 is listed in `tools/io_sync/parity.json` as open: a TextureTransform baked into the UVs
(A5), a UV-less mesh gaining a TextureCoordinate (A6), a closed line loop repeating its first point (A7), a dithered
material as alphaMode BLEND (A8) and a collection instance coming back as copies (A12), plus written-out defaults and
renumbered indices that are equivalent.
