# SPDX-FileCopyrightText: 2026 HagopJay
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Record what X_ITE's Geospatial component computes, for ``tests/test_behaviour_geo.py``.

    python3 tools/behaviour_geo_probe.py <x_ite dist dir> [--out tests/behaviour/geo_conversions.json]

Builds the cases below (several ellipsoids, both hemispheres, UTM zones on both sides of the equator and the zone
boundary, the poles, the date line, GeoOrigin with and without ``rotateYUp``, the interpolator's slerp), asks X_ITE with
``tools/behaviour_geo_probe.cjs`` (Node and Playwright's Chromium, no network) and writes cases and answers together. Run
it again only to add cases: the file is X_ITE's own record, and the tests compare ``source/behaviour_geo.py`` with it.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

POINTS_GD = [          # latitude, longitude, elevation: both hemispheres, both sides of the meridian, the date line, the poles
    (48.8, 2.3, 35.0), (-33.9, 151.2, 58.0), (0.0, 0.0, 0.0), (37.8, -122.4, 16.0), (-54.8, -68.3, 5.0),
    (64.1, -21.9, 100.0), (-1.0, -77.5, 2850.0), (89.9, 10.0, 0.0), (-89.9, -170.0, 1200.0), (0.5, 179.99, -30.0),
    (35.0, -179.5, 8848.0), (-0.001, 0.001, 0.0),
]
POINTS_UTM = [         # northing, easting, elevation as in the zone's own grid (north and south of the equator)
    (5411000.0, 452000.0, 35.0), (6420000.0, 700000.0, 100.0), (3328000.0, 334000.0, 0.0), (100000.0, 500000.0, 10.0),
    (9000000.0, 250000.0, 0.0), (9800000.0, 166000.0, 5.0), (1000000.0, 833000.0, 0.0), (8200000.0, 500000.0, 2000.0),
]
SYSTEMS_GD = [["GD", "WE"], ["GD", "BR"], ["GD", "IN", "longitude_first"], ["GD", "MARS"], ["GD", "RF"], ["GD", "CC"],
              ["GD"], ["GDC", "WD"], ["GD", "MOON"], ["GD", "URANUS"], ["WE", "GD"], ["GD", "WE", "bogus"], [], ["WM"]]
SYSTEMS_UTM = [["UTM", "Z31"], ["UTM", "Z31", "S"], ["UTM", "Z17", "WE"], ["UTM", "Z56", "S", "WE"], ["UTM", "Z1"],
               ["UTM", "Z60", "S"], ["UTM", "Z33", "easting_first"], ["UTM", "Z33", "S", "easting_first"],
               ["UTM", "Z10", "BR"], ["UTM", "Z31", "IN", "S"], ["UTM", "Z0"], ["UTM", "Z99"], ["UTM"], ["UTM", "Z31", "MARS"]]
SYSTEMS_GC = [["GC"], ["GCC"], ["GS", "WE"]]
ORIGINS = [None,
           {"geoSystem": ["GD", "WE"], "geoCoords": [48.8, 2.3, 0.0], "rotateYUp": False},
           {"geoSystem": ["GD", "WE"], "geoCoords": [48.8, 2.3, 0.0], "rotateYUp": True},
           {"geoSystem": ["GD", "WE"], "geoCoords": [-33.9, 151.2, 40.0], "rotateYUp": True},
           {"geoSystem": ["GD", "WE", "longitude_first"], "geoCoords": [151.2, -33.9, 40.0], "rotateYUp": True},
           {"geoSystem": ["UTM", "Z31"], "geoCoords": [5411000.0, 452000.0, 0.0], "rotateYUp": True},
           {"geoSystem": ["GC"], "geoCoords": [4200000.0, 170000.0, 4780000.0], "rotateYUp": True},
           {"geoSystem": ["GD", "WE"], "geoCoords": [90.0, 0.0, 0.0], "rotateYUp": True},
           {"geoSystem": ["GD", "WE"], "geoCoords": [-90.0, 30.0, 0.0], "rotateYUp": False},
           {"geoSystem": ["GD", "MARS"], "geoCoords": [10.0, 20.0, 0.0], "rotateYUp": True}]


def cases():
    out = []
    for system in SYSTEMS_GD:
        for point in POINTS_GD:
            out.append({"op": "convert", "geoSystem": system, "in": list(point)})
    for system in SYSTEMS_UTM:
        for point in POINTS_UTM:
            out.append({"op": "convert", "geoSystem": system, "in": list(point)})
    for system in SYSTEMS_GC:
        out.append({"op": "convert", "geoSystem": system, "in": [4200000.0, 170000.0, 4780000.0]})
    # apply: geocentric points, on the surface and off it, the poles included
    geocentric = [(4200000.0, 170000.0, 4780000.0), (-2700000.0, 4700000.0, -3300000.0), (6378137.0, 0.0, 0.0),
                  (0.0, 0.0, 6356752.3), (0.0, 0.0, -6400000.0), (0.0, 6378137.0, 0.0), (-6378137.0, 1.0, 1.0),
                  (1.0, 1.0, 1.0), (100.0, 200.0, 300.0), (3900000.0, 1000000.0, 5000000.0), (1.5e7, 2e6, -4e6)]
    for system in SYSTEMS_GD + SYSTEMS_UTM + SYSTEMS_GC:
        for point in geocentric:
            out.append({"op": "apply", "geoSystem": system, "in": list(point)})
    # a Geo node's frame: coordinates in, local coordinates out and back
    for origin in ORIGINS:
        for system, point, local in (
                (["GD", "WE"], (48.81, 2.31, 120.0), (3.0, 4.5, -2.0)),
                (["GD", "WE"], (-33.8, 151.3, 10.0), (-100.0, 2.0, 55.0)),
                (["UTM", "Z31"], (5412000.0, 453000.0, 50.0), (10.0, 20.0, 30.0)),
                (["UTM", "Z56", "S"], (6250000.0, 334000.0, 20.0), (-5.0, 0.0, 5.0)),
                (["GC"], (4201000.0, 171000.0, 4781000.0), (0.0, 1.6, 12.0)),
                (["GD", "BR", "longitude_first"], (2.31, 48.81, 120.0), (1.0, 1.0, 1.0))):
            out.append({"op": "local", "geoSystem": system, "origin": origin, "in": list(point)})
            out.append({"op": "geo", "geoSystem": system, "origin": origin, "in": list(local)})
    for a, b, t in (((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 0.5), ((1.0, 2.0, 3.0), (-3.0, 2.0, 1.0), 0.25),
                    ((6378137.0, 0.0, 0.0), (0.0, 6378137.0, 0.0), 0.3), ((1.0, 0.0, 0.0), (-1.0, 0.0, 0.0), 0.5),
                    ((1.0, 0.0, 0.0), (2.0, 0.0, 0.0), 0.5), ((0.0, 0.0, 0.0), (1.0, 2.0, 3.0), 0.5),
                    ((4200000.0, 170000.0, 4780000.0), (-2700000.0, 4700000.0, -3300000.0), 0.7),
                    ((1.0, 0.0, 0.0), (0.0, -1.0, 0.0), 1.0), ((1.0, 1.0, 0.0), (1.0, 1.0, 1e-9), 0.5),
                    ((3.0, 4.0, 0.0), (-4.0, 3.0, 0.0), 0.0)):
        out.append({"op": "slerp", "a": list(a), "b": list(b), "t": t})
    return out


def record(dist, work=None):
    work = Path(work or HERE)
    listed = cases()
    source = work / "geo_cases.json"
    source.write_text(json.dumps(listed), encoding="utf-8")
    env = {**__import__("os").environ}
    result = subprocess.run(["node", str(HERE / "behaviour_geo_probe.cjs"), str(dist), str(source)], capture_output=True,
                            text=True, env=env, check=True)
    source.unlink()
    answers = json.loads(result.stdout)
    assert len(answers) == len(listed)
    return {"instrument": "tools/behaviour_geo_probe.cjs on X_ITE 16.8.1 (Chromium, software GL)", "cases": listed,
            "answers": answers}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("dist", help="X_ITE 16.8.1's dist directory")
    parser.add_argument("--out", default=str(ROOT / "tests" / "behaviour" / "geo_conversions.json"))
    args = parser.parse_args(argv)
    data = record(args.dist, work=Path(args.out).parent)
    Path(args.out).write_text(json.dumps(data, separators=(",", ":")) + "\n", encoding="utf-8")
    missing = sum(1 for a in data["answers"] if a is None)
    print(f"{args.out}: {len(data['cases'])} cases, {missing} that X_ITE threw on")
    return 0


if __name__ == "__main__":
    sys.exit(main())
