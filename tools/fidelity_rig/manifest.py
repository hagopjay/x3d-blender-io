"""Per-scene manifest and validator-gate helpers for the fidelity rig (imported by compare.py).

`validate(glb)` runs validate_glb.mjs (Khronos glTF Validator) and returns the validator summary dict that goes into a
results.json row and a manifest. `write_manifest(...)` writes out/LABEL/<scene>/manifest.json, schema id
"x3d-blender-io.glb-manifest/v1": what went in (x3d path and sha256, add-on git revision, Blender version, BLENDER_X3D_*
options) and what came out (glb sha256 and bytes, validator summary, extensions, triangle, material and draw-call counts).
No timestamps, so the same inputs give the same manifest."""
import hashlib, json, os, subprocess

RIG = os.path.dirname(os.path.abspath(__file__))
SCHEMA = "x3d-blender-io.glb-manifest/v1"


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def validate(glb, max_warnings=None, node="node", timeout=300):
    """Run validate_glb.mjs on `glb`. Returns a dict with validator_ok and the "validator" summary (or "validator_error"
    when the validator could not run: that fails the gate too, it never passes silently)."""
    cmd = [node, os.path.join(RIG, "validate_glb.mjs"), glb, "--quiet"]
    if max_warnings is not None:
        cmd += ["--max-warnings", str(max_warnings)]
    report_path = glb + ".validation.json"
    if os.path.exists(report_path):   # a crash that writes no report must not be read as this glb's earlier report
        os.remove(report_path)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return dict(validator_ok=False, validator_error=f"validate_glb.mjs did not run: {e}")
    if r.returncode not in (0, 1) or not os.path.exists(report_path):
        return dict(validator_ok=False, validator_error=f"validate_glb.mjs exit {r.returncode}: {(r.stderr or r.stdout).strip()[-400:]}")
    rep = json.load(open(report_path))
    summary = dict(
        version=rep["validatorVersion"], errors=rep["numErrors"], warnings=rep["numWarnings"], infos=rep["numInfos"],
        hints=rep["numHints"], triangles=rep["totalTriangleCount"], drawCalls=rep["drawCallCount"],
        materials=rep["materialCount"], extensionsUsed=rep["extensionsUsed"], extensionsRequired=rep["extensionsRequired"],
        extensionsNotValidated=rep["extensionsNotValidated"],
        sha256=rep["sha256"], bytes=rep["bytes"],
        issues=[i for i in rep["issues"] if i["severity"] in ("ERROR", "WARNING")])
    return dict(validator_ok=(r.returncode == 0), validator=summary)


def git_revision(repo):
    """(commit, dirty) of the checkout holding the add-on source dir `repo`; ("unknown", None) outside a git checkout.
    `dirty` is whether files under that dir differ from the commit."""
    try:
        rev = subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], capture_output=True, text=True, timeout=30)
        if rev.returncode != 0:
            return "unknown", None
        dirty = subprocess.run(["git", "-C", repo, "status", "--porcelain", "--", "."], capture_output=True, text=True, timeout=30)
        return rev.stdout.strip(), (bool(dirty.stdout.strip()) if dirty.returncode == 0 else None)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown", None


def write_manifest(outdir, scene, x3d, glb, validation, leg, addon_src, env=None):
    """Write outdir/manifest.json and return it. `validation` is validate()'s return value, `leg` the blender_leg.py LEG dict."""
    env = os.environ if env is None else env
    v = validation.get("validator") or {}
    commit, dirty = git_revision(addon_src)
    manifest = dict(
        schema=SCHEMA, scene=scene,
        source=dict(x3d=x3d, sha256=sha256_file(x3d)),
        addon=dict(git_revision=commit, source_dirty=dirty),
        blender=leg.get("blender", "unknown"),
        options={k: env[k] for k in sorted(env) if k.startswith("BLENDER_X3D_") or k == "X3D_SPLAT_IMPORT"},   # every importer input that changes the glb
        glb=dict(file=os.path.basename(glb), sha256=v.get("sha256") or sha256_file(glb), bytes=v.get("bytes") or os.path.getsize(glb)),
        validator=dict(ok=validation["validator_ok"], **({k: v[k] for k in ("version", "errors", "warnings", "infos", "hints")} if v else {}),
                       **({"error": validation["validator_error"]} if "validator_error" in validation else {})),
        extensionsUsed=v.get("extensionsUsed"), extensionsRequired=v.get("extensionsRequired"),
        extensionsNotValidated=v.get("extensionsNotValidated"),
        counts=dict(triangles=v.get("triangles"), materials=v.get("materials"), drawCalls=v.get("drawCalls")))
    with open(os.path.join(outdir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    return manifest
