# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later
"""Image metrics for the scorecard: FLIP (flip-evaluator 1.7, LDR, default 67 pixels per degree), mean |delta|, thumbnails.

Definitions (every number in the report comes from these):
  flip mean            NVIDIA FLIP LDR, reference vs test, sRGB 8-bit images as float32 in [0, 1], inputsRGB=True, default 67 ppd
                       (flip-evaluator reports the ppd it used), mean of the per-pixel error map over the WHOLE frame. 0 identical,
                       lower is better, scale 0..1. FLIP is not symmetric: the reference is the first image.
  geometry mean        the same error map averaged over the geometry pixels only. Background rule: the background colour is the most
                       frequent exact RGB among the four corner pixels of the reference (ties: top-left, top-right, bottom-left,
                       bottom-right); a pixel is background when reference and test both equal it exactly; every other pixel is
                       geometry. geometry_fraction is the share of geometry pixels. Known limit: a backdrop that differs between the
                       two images (a gradient Background in one renderer, a flat colour in the other) counts as geometry.
  mean abs             mean |reference - test| over all pixels and channels on the 8-bit scale 0..255 (the fidelity rig's
                       mean_abs_delta), whole frame; geometry variant over the geometry pixels as above.
Images of different size are REFUSED (ValueError), never resized."""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

HEAT_NOTE = "FLIP error map, flip-evaluator's magma colour map, 0 (dark) .. 1 (bright)"


def load_rgb8(path) -> np.ndarray:
    """An image file as uint8 HxWx3 sRGB (alpha is composited over black)."""
    im = Image.open(path)
    im.load()
    if im.mode in ("RGBA", "LA", "PA") or (im.mode == "P" and "transparency" in im.info):
        rgba = np.asarray(im.convert("RGBA"), dtype=np.float64)
        return np.ascontiguousarray(np.round(rgba[..., :3] * rgba[..., 3:4] / 255.0).astype(np.uint8))
    return np.ascontiguousarray(np.asarray(im.convert("RGB")))


def corner_colour(img8: np.ndarray):
    h, w = img8.shape[:2]
    cs = [tuple(int(x) for x in img8[y, x]) for (y, x) in ((0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1))]
    best = max(cs, key=lambda c: (cs.count(c), -cs.index(c)))
    return best


def geometry_mask(ref8: np.ndarray, test8: np.ndarray) -> np.ndarray:
    bg = np.array(corner_colour(ref8))
    return ~(np.all(ref8 == bg, axis=-1) & np.all(test8 == bg, axis=-1))


def _flip(ref8, test8, magma=False):
    import flip_evaluator
    ref_f = np.ascontiguousarray(ref8.astype(np.float32) / 255.0)
    test_f = np.ascontiguousarray(test8.astype(np.float32) / 255.0)
    out, mean, used = flip_evaluator.evaluate(ref_f, test_f, "LDR", inputsRGB=True, applyMagma=magma, computeMeanError=True, parameters={})
    return np.asarray(out, dtype=np.float32), float(mean), used


def flip_pair(ref8: np.ndarray, test8: np.ndarray, want_heat: bool = False) -> dict:
    """FLIP of `test8` against `ref8` (equal-size uint8 RGB). Returns mean, geometry_mean, geometry_fraction, p95, max, ppd and, when
    asked, `heat` (uint8 HxWx3 magma error map)."""
    if ref8.shape != test8.shape:
        raise ValueError(f"image sizes differ: {ref8.shape[1]}x{ref8.shape[0]} vs {test8.shape[1]}x{test8.shape[0]}; nothing is resized")
    err, mean, used = _flip(ref8, test8)
    err = err.reshape(ref8.shape[0], ref8.shape[1])
    geo = geometry_mask(ref8, test8)
    out = dict(mean=mean, geometry_mean=(float(err[geo].mean()) if geo.any() else None), geometry_fraction=float(geo.mean()),
               p95=float(np.percentile(err, 95)), max=float(err.max()), ppd=float(used.get("ppd", 0.0)))
    if want_heat:
        magma, _, _ = _flip(ref8, test8, magma=True)
        out["heat"] = np.clip(np.round(magma.reshape(ref8.shape) * 255.0), 0, 255).astype(np.uint8)
    return out


def mean_abs_pair(ref8: np.ndarray, test8: np.ndarray) -> dict:
    if ref8.shape != test8.shape:
        raise ValueError(f"image sizes differ: {ref8.shape[1]}x{ref8.shape[0]} vs {test8.shape[1]}x{test8.shape[0]}")
    d = np.abs(ref8.astype(np.int16) - test8.astype(np.int16)).astype(np.float64)
    geo = geometry_mask(ref8, test8)
    return dict(mean_abs=float(d.mean()), mean_abs_geometry=(float(d[geo].mean()) if geo.any() else None))


def pair_metrics(ref_path, test_path, heat_path=None) -> dict:
    """FLIP and mean |delta| of one image file against another; writes the magma error map to heat_path when given."""
    ref8, test8 = load_rgb8(ref_path), load_rgb8(test_path)
    f = flip_pair(ref8, test8, want_heat=bool(heat_path))
    heat = f.pop("heat", None)
    if heat_path is not None and heat is not None:
        Image.fromarray(heat).save(heat_path)
    f.update(mean_abs_pair(ref8, test8))
    return f


def thumbnail_bytes(path, size=192, fmt="PNG") -> bytes:
    """A downscaled copy (LANCZOS) of an image file as PNG or JPEG bytes (the report embeds it as a data: URI)."""
    im = Image.open(path).convert("RGB")
    im.thumbnail((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    if fmt.upper() == "JPEG":
        im.save(buf, "JPEG", quality=82, optimize=True)
    else:
        im.save(buf, "PNG", optimize=True)
    return buf.getvalue()
