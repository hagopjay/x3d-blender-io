# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The X3D 4.0 Phong lighting model as plain numpy: the referee for tools/lighting_judge.py.

    python tools/lighting_oracle.py --write-fixtures        (writes tests/lighting/fixtures/<scene>.x3d)
    python tools/lighting_oracle.py SCENE [--reading linear|display] [--curve srgb|pow22] > picture.json

Each probe scene is one lit 4 x 4 quad at z = 0, facing +z, seen from a Viewpoint at (0, 0, 4) with fieldOfView pi / 4
on a square canvas, so every pixel's surface point, normal and view vector are known exactly. The oracle evaluates, at
each pixel centre, X3D 4.0 (ISO/IEC 19775-1:2023) 17.2.2.5 Phong lighting model, term by term:

    fragmentColor  = emissiveParameter + sum_i lightContribution_i                (no fog, no occlusion texture)
    lightContribution_i = on_i x lightColor_i x attenuation_i x spot_i x (ambient_i + diffuse_i + specular_i)
    ambient_i  = ambientIntensity_i x (Material.ambientIntensity x diffuseColor)
    diffuse_i  = intensity_i x diffuseColor x (N . L)
    specular_i = intensity_i x specularColor x (N . normalize(L + V)) ^ (shininess x 128)
    attenuation_i = 1 / max(c1 + c2 d + c3 d^2, 1);  on_i = 0 beyond radius;  "." clamped to >= 0
    spot_i = 0 from cutOffAngle out, 1 within beamWidth, (angle - cutOffAngle) / (beamWidth - cutOffAngle) between
             (beamWidth clamped to cutOffAngle)

The spec says nothing about colour spaces (X3D 4.0 17.2.2 and 12 Shape component never mention gamma or sRGB; Don
Brutzman, x3d-public, 27 Nov 2020: "The X3D specification is silent about gamma correction"). So the oracle has two
readings: 'linear' decodes every colour (Material and light colours) from sRGB, lights, and encodes the clamped sum
for the display; 'display' runs the equations on the file's numbers and shows the clamped sum as it is (the classic
OpenGL way: X_ITE 16.8.1 as it ships, X3DOM 1.8.3 with gammaCorrectionDefault "none"); 'linear-values' takes the
file's numbers as linear values, lights them and encodes the clamped sum (X3DOM 1.8.3 as it ships, X_ITE 16.8.1 with
ColorSpace LINEAR, and how X3D 4.0's PhysicalMaterial and glTF read a colour factor). 'linear-values' was added after
the first recording (27 Nov 2026), when both browsers' gamma-correct modes landed on neither of the first two. And two curves for the decoding: 'srgb' (the
IEC 61966-2-1 piecewise curve Blender uses) and 'pow22' (x^2.2, X_ITE 16.8.1's and X3DOM 1.8.3's).
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr

import numpy as np

SIZE = 64                       # pixels per side
EYE = np.array((0.0, 0.0, 4.0))
FIELD_OF_VIEW = 0.785398        # X3D's default, on the smaller (here: both) side

# One probe scene per term of the lighting equation. Lights are X3D fields; 'material' is a Phong Material's.
SCENES = {
    "directional": {
        "what": "a DirectionalLight alone: N . L is the same everywhere, so the picture is one colour (the colour space)",
        "lights": [{"type": "DirectionalLight", "direction": (-0.3, -0.4, -1.0), "intensity": 0.9}],
        "material": {"diffuseColor": (0.8, 0.6, 0.4)},
    },
    "point-attenuation": {
        "what": "a PointLight with attenuation 1 0.5 0.25: X3D's falloff (not 1/d^2) and N . L across the quad",
        "lights": [{"type": "PointLight", "location": (0.5, 0.3, 1.0), "attenuation": (1.0, 0.5, 0.25)}],
        "material": {"diffuseColor": (0.7, 0.7, 0.7)},
    },
    "point-radius": {
        "what": "a PointLight with radius 1.2 at 0.8 above the quad: on_i, a lit disc with a hard edge",
        "lights": [{"type": "PointLight", "location": (0.0, 0.0, 0.8), "radius": 1.2, "intensity": 0.8}],
        "material": {"diffuseColor": (0.9, 0.5, 0.3)},
    },
    "spot": {
        "what": "a tilted SpotLight, beamWidth 0.25, cutOffAngle 0.5, coloured: spot_i, linear in the angle",
        "lights": [{"type": "SpotLight", "location": (0.0, 0.0, 2.0), "direction": (0.2, 0.0, -1.0),
                    "beamWidth": 0.25, "cutOffAngle": 0.5, "color": (1.0, 0.8, 0.5)}],
        "material": {"diffuseColor": (0.8, 0.8, 0.8)},
    },
    "specular": {
        "what": "a PointLight and a shiny Material (shininess 0.3, so exponent 38.4): the Blinn-Phong highlight",
        "lights": [{"type": "PointLight", "location": (0.6, 0.6, 1.5)}],
        "material": {"diffuseColor": (0.2, 0.2, 0.5), "specularColor": (0.9, 0.9, 0.9), "shininess": 0.3},
    },
    "ambient-emissive": {
        "what": "ambientIntensity on two lights (the PointLight's ambient is attenuated, 0 1 0) and an emissiveColor",
        "lights": [{"type": "DirectionalLight", "direction": (0.0, 0.0, -1.0), "intensity": 0.3, "ambientIntensity": 0.6},
                   {"type": "PointLight", "location": (-0.8, 0.0, 0.5), "intensity": 0.4, "ambientIntensity": 0.5,
                    "attenuation": (0.0, 1.0, 0.0)}],
        "material": {"ambientIntensity": 0.5, "diffuseColor": (0.6, 0.3, 0.8), "emissiveColor": (0.1, 0.2, 0.0)},
    },
    "two-lights": {
        "what": "a red PointLight of 1.5 and a blue DirectionalLight with a specular Material: the sum, and the clamp",
        "lights": [{"type": "PointLight", "location": (-0.7, 0.0, 0.6), "color": (1.0, 0.2, 0.1), "intensity": 1.5},
                   {"type": "DirectionalLight", "direction": (0.5, 0.0, -1.0), "color": (0.2, 0.3, 1.0),
                    "intensity": 0.8}],
        "material": {"diffuseColor": (0.9, 0.9, 0.9), "specularColor": (0.5, 0.5, 0.5), "shininess": 0.1},
    },
    "headlight": {
        "what": "the NavigationInfo headlight alone (a DirectionalLight of 1 along the view) on a shiny Material. Added "
                "after the first Blender run, outside the committed ladder",
        "headlight": True,
        "lights": [{"type": "DirectionalLight", "direction": (0.0, 0.0, -1.0)}],   # the headlight, for this view
        "material": {"diffuseColor": (0.5, 0.7, 0.3), "specularColor": (0.6, 0.6, 0.6), "shininess": 0.25},
    },
}

# PhysicalMaterial probes (X3D 4.0 17.2.2.6): X3D's per-light factors around glTF 2.0's metallic-roughness BRDF.
PHYSICAL_SCENES = {
    "physical-directional": {
        "what": "a DirectionalLight of 1.2 lux on a rough dielectric: Lambert, Fresnel and GGX in the plain case",
        "lights": [{"type": "DirectionalLight", "direction": (-0.3, -0.4, -1.0), "intensity": 1.2}],
        "material": {"baseColor": (0.8, 0.5, 0.3), "metallic": 0.0, "roughness": 0.5},
    },
    "physical-metal": {
        "what": "a PointLight of 2 cd over a smooth metal: the GGX highlight and the inverse square",
        "lights": [{"type": "PointLight", "location": (0.6, 0.6, 1.2), "intensity": 2.0}],
        "material": {"baseColor": (0.9, 0.7, 0.4), "metallic": 1.0, "roughness": 0.3},
    },
    "physical-dielectric": {
        "what": "a PointLight with attenuation 1 0.5 0 on a rough dielectric with an emissiveColor: X3D's attenuation on the physical path",
        "lights": [{"type": "PointLight", "location": (-0.5, 0.2, 0.8), "intensity": 1.5, "attenuation": (1.0, 0.5, 0.0)}],
        "material": {"baseColor": (0.3, 0.6, 0.9), "metallic": 0.0, "roughness": 0.8, "emissiveColor": (0.05, 0.0, 0.1)},
    },
    "physical-spot": {
        "what": "a tilted SpotLight of 4 cd, beamWidth 0.25, cutOffAngle 0.5: whose spot ramp the physical path uses",
        "lights": [{"type": "SpotLight", "location": (0.0, 0.0, 2.0), "direction": (0.2, 0.0, -1.0), "intensity": 4.0,
                    "beamWidth": 0.25, "cutOffAngle": 0.5}],
        "material": {"baseColor": (0.8, 0.8, 0.8), "metallic": 0.2, "roughness": 0.6},
    },
    "physical-radius": {
        "what": "a PointLight with radius 1.2 at 0.8 above a fully rough surface: a hard edge, or glTF's range window",
        "lights": [{"type": "PointLight", "location": (0.0, 0.0, 0.8), "radius": 1.2, "intensity": 1.0}],
        "material": {"baseColor": (0.9, 0.5, 0.3), "metallic": 0.0, "roughness": 1.0},
    },
}
PHYSICAL_DEFAULTS = {"baseColor": (1.0, 1.0, 1.0), "metallic": 1.0, "roughness": 1.0, "emissiveColor": (0.0, 0.0, 0.0)}
SPEC_KNOBS = {"inverse_square": True, "radius": "hard", "spot": "x3d", "visibility": "separable"}

READINGS = ("linear", "display", "linear-values")
LIGHT_DEFAULTS = {"intensity": 1.0, "ambientIntensity": 0.0, "color": (1.0, 1.0, 1.0), "attenuation": (1.0, 0.0, 0.0),
                  "radius": 100.0, "beamWidth": math.pi * 3.0 / 16.0, "cutOffAngle": math.pi / 2.0,
                  "direction": (0.0, 0.0, -1.0), "location": (0.0, 0.0, 0.0)}
MATERIAL_DEFAULTS = {"ambientIntensity": 0.2, "diffuseColor": (0.8, 0.8, 0.8), "emissiveColor": (0.0, 0.0, 0.0),
                     "shininess": 0.2, "specularColor": (0.0, 0.0, 0.0), "transparency": 0.0}   # X3D 4.0 12.4.5


def decode(value, curve):
    value = np.clip(np.asarray(value, dtype=float), 0.0, None)
    if curve == "pow22":
        return value ** 2.2
    return np.where(value <= 0.04045, value / 12.92, ((value + 0.055) / 1.055) ** 2.4)


def encode(value, curve):
    value = np.clip(np.asarray(value, dtype=float), 0.0, 1.0)
    if curve == "pow22":
        return value ** (1.0 / 2.2)
    return np.where(value <= 0.0031308, 12.92 * value, 1.055 * value ** (1.0 / 2.4) - 0.055)


def surface(size=SIZE):
    """Each pixel centre's point on the quad (size, size, 3), row 0 at the top, and the view vector V there."""
    half = math.tan(FIELD_OF_VIEW / 2.0)
    centres = (np.arange(size) + 0.5) / size * 2.0 - 1.0
    x, y = np.meshgrid(centres * half, -centres * half)
    direction = np.stack((x, y, -np.ones_like(x)), axis=-1)
    point = EYE + direction * EYE[2]          # the ray meets z = 0 at t = 4
    view = EYE - point
    view /= np.linalg.norm(view, axis=-1, keepdims=True)
    return point, view


def light_fields(light):
    fields = dict(LIGHT_DEFAULTS)
    fields.update(light)
    return fields


def evaluate(scene, reading="linear", curve="srgb", size=SIZE):
    """(picture, on): the display value of every pixel in [0, 1] (size, size, 3), and which lights reach it
    (size, size, lights), for the jump mask."""
    spec = SCENES[scene] if isinstance(scene, str) else scene
    material = dict(MATERIAL_DEFAULTS)
    material.update(spec["material"])

    def work(colour):
        return decode(colour, curve) if reading == "linear" else np.asarray(colour, dtype=float)

    encoded = reading in ("linear", "linear-values")

    point, view = surface(size)
    normal = np.array((0.0, 0.0, 1.0))
    diffuse, specular = work(material["diffuseColor"]), work(material["specularColor"])
    total = np.broadcast_to(work(material["emissiveColor"]), point.shape).copy()
    reached = []
    for light in spec["lights"]:
        fields = light_fields(light)
        kind = fields["type"]
        if kind == "DirectionalLight":
            towards = -np.array(fields["direction"], dtype=float)
            towards = np.broadcast_to(towards / np.linalg.norm(towards), point.shape)
            distance = np.zeros(point.shape[:2])
        else:
            offset = np.array(fields["location"], dtype=float) - point
            distance = np.linalg.norm(offset, axis=-1)
            towards = offset / distance[..., None]
        on = np.ones(point.shape[:2])
        attenuation = np.ones(point.shape[:2])
        spot = np.ones(point.shape[:2])
        if kind != "DirectionalLight":
            radius = fields["radius"]
            on = np.where((radius < 0.0) | (distance <= radius), 1.0, 0.0)
            c1, c2, c3 = fields["attenuation"]
            attenuation = 1.0 / np.maximum(c1 + c2 * distance + c3 * distance * distance, 1.0)
        if kind == "SpotLight":
            axis = np.array(fields["direction"], dtype=float)
            axis /= np.linalg.norm(axis)
            angle = np.arccos(np.clip(-(towards @ axis), -1.0, 1.0))
            cut_off = fields["cutOffAngle"]
            beam = min(fields["beamWidth"], cut_off)
            between = (angle - cut_off) / (beam - cut_off) if beam < cut_off else np.zeros_like(angle)
            spot = np.where(angle >= cut_off, 0.0, np.where(angle <= beam, 1.0, between))
        n_dot_l = np.maximum(towards @ normal, 0.0)
        half = towards + view
        half /= np.linalg.norm(half, axis=-1, keepdims=True)
        n_dot_h = np.maximum(half @ normal, 0.0)
        ambient = fields["ambientIntensity"] * material["ambientIntensity"] * diffuse
        terms = (ambient + fields["intensity"] * diffuse * n_dot_l[..., None]
                 + fields["intensity"] * specular * (n_dot_h ** (material["shininess"] * 128.0))[..., None])
        total += (on * attenuation * spot)[..., None] * work(fields["color"]) * terms
        reached.append(on)
    picture = encode(total, curve) if encoded else np.clip(total, 0.0, 1.0)
    return picture, np.stack(reached, axis=-1)


def evaluate_physical(scene, knobs=None, curve="srgb", size=SIZE):
    """(picture, on) for a PhysicalMaterial probe. Colours are linear values (glTF's reading, and both browsers',
    see docs/LIGHTING.md); the clamped sum is encoded for the display. The BRDF is glTF 2.0 Appendix B:
    c_diff = lerp(base, 0, metallic), f0 = lerp(0.04, base, metallic), alpha = roughness^2,
    F = f0 + (1 - f0)(1 - V.H)^5, D = alpha^2 / (pi ((N.H)^2 (alpha^2 - 1) + 1)^2),
    f = (1 - metallic)(1 - F_dielectric) base / pi + F D Vis (Appendix B's mix of the dielectric and metal BRDFs;
    knob mix 'shortcut': (1 - F) c_diff / pi), radiance = f x E x (N . L), E = intensity x color (/ d^2 for a point or spot
    light when inverse_square). knobs (SPEC_KNOBS is the spec's reading):
      inverse_square  True / False
      radius          'hard' (X3D on_i) / 'window' (KHR_lights_punctual: clamp(1 - (d/r)^4)) / 'window2' (its square)
      spot            'x3d' (Table 17.4, linear in the angle) / 'gltf' (t^2 in the cosine) / 'smooth' (smoothstep in the cosine)
      visibility      'separable' (Smith G1(L) G1(V) / (4 N.L N.V), as Appendix B writes it) / 'correlated' (height-correlated)"""
    knobs = dict(SPEC_KNOBS, **(knobs or {}))
    spec = PHYSICAL_SCENES[scene] if isinstance(scene, str) else scene
    material = dict(PHYSICAL_DEFAULTS)
    material.update(spec["material"])
    point, view = surface(size)
    normal = np.array((0.0, 0.0, 1.0))
    base = np.asarray(material["baseColor"], dtype=float)
    metallic, roughness = float(material["metallic"]), float(material["roughness"])
    c_diff = base * (1.0 - metallic)
    f0 = 0.04 * (1.0 - metallic) + base * metallic
    alpha = roughness * roughness
    a2 = alpha * alpha
    n_dot_v = np.maximum(view @ normal, 1e-6)
    total = np.broadcast_to(np.asarray(material["emissiveColor"], dtype=float), point.shape).copy()
    reached = []
    for light in spec["lights"]:
        fields = light_fields(light)
        kind = fields["type"]
        if kind == "DirectionalLight":
            towards = -np.array(fields["direction"], dtype=float)
            towards = np.broadcast_to(towards / np.linalg.norm(towards), point.shape)
            distance = np.ones(point.shape[:2])
            irradiance = np.full(point.shape[:2], fields["intensity"])
            on = np.ones(point.shape[:2])
        else:
            offset = np.array(fields["location"], dtype=float) - point
            distance = np.linalg.norm(offset, axis=-1)
            towards = offset / distance[..., None]
            c1, c2, c3 = fields["attenuation"]
            irradiance = fields["intensity"] / np.maximum(c1 + c2 * distance + c3 * distance * distance, 1.0)
            if knobs["inverse_square"]:
                irradiance = irradiance / (distance * distance)
            radius = fields["radius"]
            if knobs["radius"] == "hard" or radius < 0.0:
                on = np.where((radius < 0.0) | (distance <= radius), 1.0, 0.0)
            else:
                window = np.clip(1.0 - (distance / radius) ** 4, 0.0, 1.0)
                on = window if knobs["radius"] == "window" else window * window
        if kind == "SpotLight":
            axis = np.array(fields["direction"], dtype=float)
            axis /= np.linalg.norm(axis)
            cosine = np.clip(-(towards @ axis), -1.0, 1.0)
            cut_off = fields["cutOffAngle"]
            beam = min(fields["beamWidth"], cut_off)
            if knobs["spot"] == "x3d":
                angle = np.arccos(cosine)
                ramp = (angle - cut_off) / (beam - cut_off) if beam < cut_off else (angle < cut_off).astype(float)
                spot = np.clip(ramp, 0.0, 1.0)
            else:
                outer, inner = math.cos(cut_off), math.cos(beam)
                t = np.clip((cosine - outer) / max(inner - outer, 1e-3), 0.0, 1.0)
                spot = t * t if knobs["spot"] == "gltf" else t * t * (3.0 - 2.0 * t)
            irradiance = irradiance * spot
        n_dot_l = np.maximum(towards @ normal, 0.0)
        half = towards + view
        half /= np.linalg.norm(half, axis=-1, keepdims=True)
        n_dot_h = np.maximum(half @ normal, 0.0)
        v_dot_h = np.maximum(np.einsum("...i,...i", view, half), 0.0)
        fresnel = f0 + (1.0 - f0) * ((1.0 - v_dot_h) ** 5)[..., None]
        distribution = a2 / (math.pi * (n_dot_h * n_dot_h * (a2 - 1.0) + 1.0) ** 2)
        safe_l = np.maximum(n_dot_l, 1e-6)
        if knobs["visibility"] == "separable":
            g1 = lambda x: 2.0 * x / (x + np.sqrt(a2 + (1.0 - a2) * x * x))
            visibility = g1(safe_l) * g1(n_dot_v) / (4.0 * safe_l * n_dot_v)
        else:
            visibility = 0.5 / (safe_l * np.sqrt(n_dot_v * n_dot_v * (1.0 - a2) + a2)
                                + n_dot_v * np.sqrt(safe_l * safe_l * (1.0 - a2) + a2))
        if knobs.get("mix", "appendix") == "appendix":
            # glTF 2.0 Appendix B as written: mix(dielectric_brdf, metal_brdf, metallic), the dielectric's diffuse
            # weighted by its own Fresnel (f0 = 0.04), not by the mixed one
            dielectric = 0.04 + 0.96 * ((1.0 - v_dot_h) ** 5)[..., None]
            brdf = (1.0 - metallic) * (1.0 - dielectric) * base / math.pi + fresnel * (distribution * visibility)[..., None]
        else:   # the common shortcut: (1 - F) c_diff / pi with F from the mixed f0
            brdf = (1.0 - fresnel) * c_diff / math.pi + fresnel * (distribution * visibility)[..., None]
        radiance = brdf * (irradiance * on * n_dot_l)[..., None] * np.asarray(fields["color"], dtype=float)
        total += radiance
        reached.append(on > 0.0 if knobs["radius"] == "hard" else np.ones(point.shape[:2], dtype=bool))
    return encode(total, curve), np.stack(reached, axis=-1).astype(float)


def physical_fixture(scene):
    spec = PHYSICAL_SCENES[scene]
    text = fixture(scene, spec)
    material = " ".join(f"{key}='{_vec(value) if isinstance(value, (tuple, list)) else f'{value:g}'}'"
                        for key, value in spec["material"].items())
    return re.sub(r"<Material [^>]*/>", f"<PhysicalMaterial {material}/>", text)


def jump_mask(on):
    """True where a pixel or one of its 8 neighbours is reached by a different set of lights (a radius edge)."""
    keep = np.ones(on.shape[:2], dtype=bool)
    padded = np.pad(on, ((1, 1), (1, 1), (0, 0)), mode="edge")
    rows, cols = on.shape[:2]
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            neighbour = padded[1 + dy:1 + dy + rows, 1 + dx:1 + dx + cols]
            keep &= (neighbour == on).all(axis=-1)
    return ~keep


def _vec(values):
    return " ".join(f"{float(v):g}" for v in values)


def fixture(scene, spec=None):
    """The probe scene as an X3D 4.0 file: no headlight, a black background, the quad with explicit normals."""
    spec = spec or SCENES[scene]
    lights = []
    for light in ([] if spec.get("headlight") else spec["lights"]):
        fields = {key: value for key, value in light.items() if key != "type"}
        attributes = " ".join(f"{key}='{_vec(value) if isinstance(value, (tuple, list)) else f'{value:g}'}'"
                              for key, value in fields.items())
        lights.append(f"    <{light['type']} {attributes}/>")
    material = " ".join(f"{key}='{_vec(value) if isinstance(value, (tuple, list)) else f'{value:g}'}'"
                        for key, value in spec["material"].items())
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 4.0//EN" "https://www.web3d.org/specifications/x3d-4.0.dtd">
<X3D profile='Interchange' version='4.0'>
  <head>
    <meta name='title' content='lighting probe: {scene}'/>
    <meta name='description' content={quoteattr(spec["what"])}/>
    <meta name='generator' content='tools/lighting_oracle.py'/>
  </head>
  <Scene>
    <NavigationInfo headlight='{"true" if spec.get("headlight") else "false"}'/>
    <Background skyColor='0 0 0'/>
    <Viewpoint position='0 0 4' fieldOfView='{FIELD_OF_VIEW:g}' description='probe'/>
{chr(10).join(lights)}
    <Shape>
      <Appearance>
        <Material {material}/>
      </Appearance>
      <IndexedFaceSet solid='false' coordIndex='0 1 2 3 -1'>
        <Coordinate point='-2 -2 0 2 -2 0 2 2 0 -2 2 0'/>
        <Normal vector='0 0 1 0 0 1 0 0 1 0 0 1'/>
      </IndexedFaceSet>
    </Shape>
  </Scene>
</X3D>
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("scene", nargs="?")
    parser.add_argument("--reading", default="linear", choices=READINGS)
    parser.add_argument("--curve", default="srgb", choices=("srgb", "pow22"))
    parser.add_argument("--write-fixtures", action="store_true")
    args = parser.parse_args()
    if args.write_fixtures:
        folder = Path(__file__).resolve().parents[1] / "tests" / "lighting" / "fixtures"
        folder.mkdir(parents=True, exist_ok=True)
        for scene in SCENES:
            (folder / f"{scene}.x3d").write_text(fixture(scene), encoding="utf-8")
            print(folder / f"{scene}.x3d")
        for scene in PHYSICAL_SCENES:
            (folder / f"{scene}.x3d").write_text(physical_fixture(scene), encoding="utf-8")
            print(folder / f"{scene}.x3d")
        return
    picture, on = evaluate(args.scene, args.reading, args.curve)
    json.dump({"scene": args.scene, "reading": args.reading, "curve": args.curve, "size": SIZE,
               "levels": np.round(picture * 255.0, 3).tolist(), "jump": jump_mask(on).tolist()}, sys.stdout)


if __name__ == "__main__":
    main()
