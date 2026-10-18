#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""
x3d_browser_check.py  -  load the exported test-suite scene in X_ITE (headless Chromium) and look at it
==========================================================================================================

The Python validator proves the FILE is right.  This script proves a real X3D browser agrees:

  1. the scene loads without X_ITE errors / warnings          (console log, de-duplicated and grouped)
  2. the animation clock is running                           (two screenshots of the animation zone differ)
  3. every zone tour viewpoint (CAM_Zxx) can be bound         (-> one screenshot per zone, saved as PNG)
  4. a self-contained contact sheet pairs every screenshot with the plain-English "what you should see"
     text from the manifest.                                  (--report browser_report.html)

    python3 x3d_browser_check.py OUT_DIR [--file x3d_suite_main.x3d] [--shots DIR] [--report FILE.html]
                                 [--zones Z04,Z11] [--size 960x600] [--xite-dist DIR_OR_URL] [--gpu] [--json FILE]

Needs:  pip install playwright   (+ a Chromium: `playwright install chromium`, or any Chrome via --chrome PATH).
X_ITE : by default the pinned CDN build 16.5.1 is used; for offline use pass --xite-dist <dir containing
        x_ite.min.js, x_ite.css and assets/>  (e.g. node_modules/x_ite/dist after `npm i x_ite@16.5.1`).

Exit code 1 when X_ITE reports an error-level message, the scene fails to load, or the animation never moves.
Metals look dark without an EnvironmentLight: that is a property of the exporter output, not a failure here.
"""
from __future__ import annotations

import argparse
import base64
import collections
import functools
import html
import http.server
import io
import json
import os
import re
import sys
import threading

DEFAULT_XITE = "https://cdn.jsdelivr.net/npm/x_ite@16.5.1/dist"

VIEWER = """<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="{xite}/x_ite.css"><script src="{xite}/x_ite.min.js"></script>
<style>html,body{{margin:0;background:#202428}}x3d-canvas{{display:block;width:{w}px;height:{h}px}}</style></head>
<body><x3d-canvas id="c" src="{src}" contentScale="1"></x3d-canvas></body></html>"""

PROBE_JS = """() => {
  const B = X3D.getBrowser(document.getElementById('c')); const s = B.currentScene;
  const types = {}; for (const n of s.rootNodes) { try { const t = n.getNodeTypeName(); types[t] = (types[t] || 0) + 1; } catch (e) {} }
  let timer = null; try { const t = s.getNamedNode('SceneTimer'); timer = { cycleInterval: t.cycleInterval, loop: t.loop, isActive: t.isActive }; } catch (e) {}
  return { world: s.worldURL, roots: s.rootNodes.length, profile: s.getProfile() ? s.getProfile().name : null,
           spec: s.specificationVersion, rootTypes: types, timer, version: B.version, name: B.name };
}"""

# jump instantly (a software-GL browser renders ~1 fps; an animated viewpoint transition would be caught half-way)
BIND_JS = """(def) => { const B = X3D.getBrowser(document.getElementById('c'));
  try { B.getActiveNavigationInfo().transitionType = ['TELEPORT']; } catch (e) {}
  let vp = null; try { vp = B.currentScene.getNamedNode(def); } catch (e) { return {ok: false, err: String(e)}; }
  vp.set_bind = true; return {ok: true}; }"""

IS_BOUND_JS = """(def) => { try { return X3D.getBrowser(document.getElementById('c')).currentScene.getNamedNode(def).isBound === true; } catch (e) { return false; } }"""


def make_handler(root, xite_dir, viewer_html):
    class H(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def translate_path(self, path):
            p = path.split("?", 1)[0]
            if xite_dir and p.startswith("/_xite/"):
                return os.path.join(xite_dir, p[len("/_xite/"):])
            return super().translate_path(path)

        def do_GET(self):
            if self.path.split("?", 1)[0] == "/_viewer.html":
                body = viewer_html.encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            super().do_GET()
    return functools.partial(H, directory=root)


def thumb_b64(png: bytes, width=420):
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(png)).convert("RGB")
        im.thumbnail((width, width * 10))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return "image/jpeg", base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return "image/png", base64.b64encode(png).decode()


def pixel_diff(a: bytes, b: bytes) -> float:
    """Fraction of pixels that differ noticeably between two screenshots (0..1)."""
    try:
        from PIL import Image, ImageChops
        ia, ib = Image.open(io.BytesIO(a)).convert("L"), Image.open(io.BytesIO(b)).convert("L")
        d = ImageChops.difference(ia, ib).point(lambda v: 255 if v > 12 else 0)
        return d.histogram()[255] / (ia.size[0] * ia.size[1])
    except Exception:
        return 0.0 if a == b else 1.0


def classify(text: str) -> str:
    t = text.lower()
    if any(k in t for k in ("error", "exception", "failed", "invalid", "unknown node", "not found", "cannot")):
        return "error"
    if any(k in t for k in ("warn", "unsupported", "ignored", "deprecated", "no such")):
        return "warning"
    return "info"


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("out_dir")
    ap.add_argument("--file", default="x3d_suite_main.x3d")
    ap.add_argument("--shots", default=None, help="directory for per-zone PNG screenshots (default OUT_DIR/browser_shots)")
    ap.add_argument("--report", default=None, help="write a self-contained HTML contact sheet")
    ap.add_argument("--json", default=None)
    ap.add_argument("--zones", default=None, help="comma list, e.g. Z04,Z11 (default: all with a CAM_ viewpoint)")
    ap.add_argument("--size", default="960x600")
    ap.add_argument("--settle", type=float, default=4.0, help="seconds to let textures load after the scene parses")
    ap.add_argument("--zone-wait", type=float, default=2.5, help="seconds to render after binding a zone viewpoint")
    ap.add_argument("--xite-dist", default=DEFAULT_XITE)
    ap.add_argument("--chrome", default=None, help="path of a Chrome/Chromium executable")
    ap.add_argument("--gpu", action="store_true", help="use the machine's GPU instead of software WebGL")
    a = ap.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        sys.exit("playwright is missing:  pip install playwright && playwright install chromium")

    out_dir = os.path.abspath(a.out_dir)
    manifest = json.load(open(os.path.join(out_dir, "x3d_suite_manifest.json"), encoding="utf-8"))
    w, h = (int(x) for x in a.size.lower().split("x"))
    shots = a.shots or os.path.join(out_dir, "browser_shots")
    os.makedirs(shots, exist_ok=True)

    if os.path.isdir(a.xite_dist):
        xite_url, xite_dir = "/_xite", os.path.abspath(a.xite_dist)
    else:
        xite_url, xite_dir = a.xite_dist.rstrip("/"), None
    viewer = VIEWER.format(xite=xite_url, src=a.file, w=w, h=h)
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(out_dir, xite_dir, viewer))
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    zones = [z["id"] for z in manifest["zones"] if z.get("status") == "ok"]
    if a.zones:
        want = {x.strip().lower() for x in a.zones.split(",")}
        zones = [z for z in zones if z.lower() in want or next((q["name"] for q in manifest["zones"] if q["id"] == z), "").lower() in want]
    expect_by_zone = collections.defaultdict(list)
    for c in manifest["cases"]:
        expect_by_zone[c["zone"]].append(c)

    logs, result = [], {"file": a.file, "zones": {}, "console": {}, "load": None, "animation": None, "problems": []}
    launch_args = ["--lang=en-US", "--ignore-gpu-blocklist", "--enable-webgl"]
    if not a.gpu:
        launch_args += ["--use-angle=swiftshader", "--use-gl=angle", "--enable-unsafe-swiftshader"]
    env = dict(os.environ, LANG="en_US.UTF-8")
    env.pop("LC_ALL", None)

    with sync_playwright() as p:
        kw = {"executable_path": a.chrome} if a.chrome else {}
        browser = p.chromium.launch(env=env, args=launch_args, **kw)
        ctx = browser.new_context(locale="en-US", viewport={"width": w, "height": h})
        page = ctx.new_page()
        page.on("console", lambda m: logs.append((m.type, m.text)))
        page.on("pageerror", lambda e: logs.append(("pageerror", str(e))))
        page.on("requestfailed", lambda r: logs.append(("requestfailed", f"{r.url} ({r.failure})")))
        page.on("response", lambda r: logs.append(("http404", r.url)) if r.status >= 400 else None)
        page.goto(f"http://127.0.0.1:{port}/_viewer.html")
        try:
            page.wait_for_function(
                "() => { try { const B = X3D.getBrowser(document.getElementById('c')); return B.currentScene.rootNodes.length > 0; } catch (e) { return false; } }",
                timeout=60000)
            result["load"] = page.evaluate(PROBE_JS)
        except Exception as exc:
            result["problems"].append(f"scene did not load within 60 s: {exc}")
        page.wait_for_timeout(int(a.settle * 1000))

        if result["load"]:
            for zid in zones:
                res = page.evaluate(BIND_JS, f"CA_CAM_{zid}")
                if not res.get("ok"):
                    result["zones"][zid] = {"shot": None, "note": f"no viewpoint CA_CAM_{zid}: {res.get('err')}"}
                    continue
                bound = False
                for _ in range(40):                       # up to ~20 s: binding happens on the next rendered frame
                    if page.evaluate(IS_BOUND_JS, f"CA_CAM_{zid}"):
                        bound = True
                        break
                    page.wait_for_timeout(500)
                page.wait_for_timeout(int(a.zone_wait * 1000))
                png = page.screenshot()
                path = os.path.join(shots, f"{zid}.png")
                open(path, "wb").write(png)
                result["zones"][zid] = {"shot": path, "png": png, "bound": bound}
                if not bound:
                    result["problems"].append(f"viewpoint CA_CAM_{zid} never became bound")
            # animation: two shots of the animation zone (Z13, or the first zone when photographing a different file), 1.1 s apart
            anim_zone = "Z13" if "Z13" in result["zones"] else (zones[0] if zones else None)
            if anim_zone and result["zones"].get(anim_zone, {}).get("png"):
                page.evaluate(BIND_JS, f"CA_CAM_{anim_zone}")
                page.wait_for_timeout(300)
                s1 = page.screenshot()
                page.wait_for_timeout(1100)
                s2 = page.screenshot()
                d = pixel_diff(s1, s2)
                result["animation"] = {"zone": anim_zone, "changed_pixel_fraction": round(d, 5)}
                if d < 0.0005:
                    result["problems"].append(f"{anim_zone} did not change between two screenshots: nothing is animating (TimeSensor not running?)")
        browser.close()
    srv.shutdown()

    grouped = collections.OrderedDict()
    for typ, text in logs:
        sev = "error" if typ in ("error", "pageerror", "requestfailed", "http404") else classify(text) if typ in ("warning", "warn") else \
            ("warning" if typ == "warning" else classify(text) if "x_ite" in text.lower() else "info")
        key = (sev, re.sub(r"\d+(\.\d+)?", "#", text)[:200])
        grouped.setdefault(key, {"sev": sev, "text": text[:400], "n": 0})["n"] += 1
    result["console"] = list(grouped.values())
    errors = [g for g in result["console"] if g["sev"] == "error"]
    for g in errors:
        result["problems"].append(f"console error x{g['n']}: {g['text'][:200]}")

    # ------------------------------------------------------------------ console report
    print(f"\nX_ITE browser check  -  {a.file}  ({xite_url})")
    if result["load"]:
        L = result["load"]
        print(f"  loaded: {L['roots']} root nodes, profile {L['profile']}, spec {L['spec']}, {L['name']} {L['version']}")
        print(f"  root node types: {L['rootTypes']}")
        print(f"  timer : {L['timer']}")
    print(f"  zones photographed: {sum(1 for z in result['zones'].values() if z.get('shot'))}/{len(zones)}  -> {shots}")
    if result["animation"]:
        print(f"  {result['animation']['zone']} changed {result['animation']['changed_pixel_fraction'] * 100:.2f}% of its pixels in 1.1 s (animation clock check)")
    for sev in ("error", "warning"):
        for g in (x for x in result["console"] if x["sev"] == sev):
            print(f"  [{sev}] x{g['n']}  {g['text'][:160]}")
    if not any(g["sev"] in ("error", "warning") for g in result["console"]):
        print("  console: no X_ITE errors or warnings")
    for pr in result["problems"]:
        print("  PROBLEM:", pr)

    # ------------------------------------------------------------------ contact sheet
    if a.report:
        cards = []
        zname = {z["id"]: z for z in manifest["zones"]}
        for zid in zones:
            z = result["zones"].get(zid, {})
            if z.get("png"):
                mime, b64 = thumb_b64(z["png"])
                img = f'<img alt="{zid}" src="data:{mime};base64,{b64}">'
            else:
                img = f'<div class="noshot">{html.escape(z.get("note") or "not photographed")}</div>'
            core = [c for c in expect_by_zone[zid] if c["tier"] == "CORE"]
            items = "".join(f"<li><b>{html.escape(c['title'])}</b><br><span>{html.escape(c['expect'])}</span></li>" for c in core[:8])
            more = f"<p class=more>+ {len(core) - 8} more CORE cases in X3D_TEST_EXPECTATIONS.md</p>" if len(core) > 8 else ""
            cards.append(f'<section class="card"><h2>{zid} <small>{html.escape(zname.get(zid, {}).get("title", ""))}</small></h2>{img}<ul>{items}</ul>{more}</section>')
        cons = "".join(f'<tr class="{g["sev"]}"><td>{g["sev"]}</td><td>{g["n"]}</td><td>{html.escape(g["text"][:300])}</td></tr>' for g in result["console"] if g["sev"] != "info") \
            or '<tr><td colspan=3>No X_ITE errors or warnings.</td></tr>'
        doc = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>X3D Browser Contact Sheet</title><style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#14181f;--mute:#5b6573;--line:#dfe3e8;--bad:#c62828;--warn:#b26a00}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0f1317;--card:#171c22;--ink:#e8ecf1;--mute:#9aa5b3;--line:#2a323b;--bad:#ff6b6b;--warn:#f2b04c}}}}
body{{margin:0;background:var(--bg);color:var(--ink);font:15px/1.5 system-ui,sans-serif}}main{{max-width:1180px;margin:0 auto;padding:20px 16px 60px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr));gap:14px}}.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:12px 14px}}
.card h2{{font-size:1.05rem;margin:.1rem 0 .5rem}}.card small{{color:var(--mute);font-weight:400}}img{{width:100%;border-radius:8px;border:1px solid var(--line);display:block}}
ul{{padding-left:1.1rem;margin:.6rem 0 0;font-size:.86rem}}li{{margin:.35rem 0}}li span{{color:var(--mute)}}.noshot{{padding:30px;text-align:center;color:var(--mute);border:1px dashed var(--line);border-radius:8px}}
table{{border-collapse:collapse;width:100%;font-size:.85rem}}td{{border-top:1px solid var(--line);padding:4px 8px}}tr.error td:first-child{{color:var(--bad)}}tr.warning td:first-child{{color:var(--warn)}}.more{{font-size:.8rem;color:var(--mute)}}
</style></head><body><main><h1>X3D export in X_ITE - contact sheet</h1>
<p style="color:var(--mute)">{html.escape(a.file)} - X_ITE {html.escape(str((result['load'] or {}).get('version')))} - headless Chromium, {'GPU' if a.gpu else 'software'} WebGL. Each card: what X_ITE drew + what a correct export should show.</p>
<h3>Console</h3><table>{cons}</table><h3>Zones</h3><div class="grid">{''.join(cards)}</div></main></body></html>"""
        open(a.report, "w", encoding="utf-8").write(doc)
        print(f"  contact sheet -> {a.report}")

    if a.json:
        slim = {k: v for k, v in result.items()}
        slim["zones"] = {k: {kk: vv for kk, vv in v.items() if kk != "png"} for k, v in result["zones"].items()}
        json.dump(slim, open(a.json, "w", encoding="utf-8"), indent=1)
    sys.exit(1 if result["problems"] else 0)


if __name__ == "__main__":
    main()
