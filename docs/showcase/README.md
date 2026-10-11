# Checkable 3D: research showcase

A static page that shows the project's research findings on X3D in the AI era, with the X3D scenes running live in the browser through [X_ITE](https://create3000.github.io/x_ite/) 16.4.3.

Open `index.html` from any static web server (X_ITE fetches its components lazily, so `file://` will not work):

```sh
cd docs/showcase && python3 -m http.server 8000
# then http://localhost:8000/
```

With GitHub Pages set to serve `main` from `/docs`, the page is at `https://hagopjay.github.io/x3d-blender-io/showcase/`.

## What is here

| Path | What |
| --- | --- |
| `index.html` | The page: numbers, the validation loop, a 12-demo theatre, findings, splats, the Blender ecosystem ranking, spec questions, timeline, changelog. No build step. |
| `scenes/*.x3d` | 24 X3D 4.0 and 4.1 files behind the demos. Four fail validation on purpose (`repair-0-written`, `profile-tables`, `geolod-no-origin`, `annotation`): each is the "before" half of a finding. |
| `scenes/verdicts.json` | The validator fork's verdict on every scene, shown under each demo. Rebuild with `tools/showcase_verdicts.py`. |
| `img/posters/*.webp` | Stills of each scene from headless X_ITE 16.4.3 (Chromium, SwiftShader, 960×600), shown until the viewer presses "Load live 3D". |
| `img/*.webp` | Figures: Cycles vs X_ITE, the splat training run, the exporter light fix, evolved elites, the bench contact sheet. |

X_ITE is loaded from `vendor/x_ite/` when present (for hosts that block CDNs), otherwise from jsDelivr pinned at 16.4.3.

## Sources of the numbers

Every number on the page names the tool that measured it. The underlying runs:

- X3D-Bench slice (30 prompts, 6 categories, 8 Oct 2026) and the 120-run, four-writer rerun (11 Oct 2026): validator fork `integration/validator-fixes` @ c9c9788 plus headless X_ITE 16.4.3.
- Cycles vs X_ITE (SSIM 0.905, ΔE2000 4.50) and synthetic-to-splat (132,923 splats, SSIM 0.977): Blender 5.2.2 Cycles, gsplat 15,000 steps on one NVIDIA L4, the add-on's X3D 4.1 writer.
- `stilllife-splats-24k.x3d` is that trained model cut to the 24,000 splats with the largest opacity × size, colour only (SH degree 0), and re-exported by this add-on so the repository stays small.
- Stars: HYG v4.1 catalogue, every star within 50 light-years, two splats each.
- Ecosystem ranking: the daily watch of Blender, X_ITE, glTF and splat projects, 11 Oct 2026.

## Updating

1. Add or replace a scene in `scenes/`, then run `X3D_MCP_SRC=<x3d_mcp>/src python3 tools/showcase_verdicts.py`.
2. Add a poster at `img/posters/<scene>.webp` (960×600 from X_ITE).
3. Add or edit the entry in the `DEMOS` array in `index.html`, and a line in the Changelog section.
