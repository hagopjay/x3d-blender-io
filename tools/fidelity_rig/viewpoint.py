"""X3D viewpoint helpers shared by compare.py, gate.py and the audit: the world pose, field of view and clip range of the
first Viewpoint / OrthoViewpoint / GeoViewpoint in a document (what X_ITE binds). Plain Python and numpy; the GeoViewpoint
case imports the add-on's geospatial.py from the source folder passed in as `src`."""
import re, sys, xml.etree.ElementTree as ET
import numpy as np


def _floats(text, n):
    v = [float(x) for x in (text or "").replace(",", " ").split()]
    return v[:n] if len(v) >= n else None


def _rot(axis_angle):
    x, y, z, a = axis_angle
    n = np.linalg.norm([x, y, z]) or 1.0
    x, y, z = x / n, y / n, z / n
    c, s_, C = np.cos(a), np.sin(a), 1 - np.cos(a)
    return np.array([[c + x*x*C, x*y*C - z*s_, x*z*C + y*s_], [y*x*C + z*s_, c + y*y*C, y*z*C - x*s_],
                     [z*x*C - y*s_, z*y*C + x*s_, c + z*z*C]])


def geo_viewpoint(vp, src):
    """The pose of a GeoViewpoint in X3D's geocentric scene space, with the clip range that holds the globe (the
    add-on's own geospatial.py does the geodesy; X_ITE's render is the reference it is compared with)."""
    sys.path.insert(0, src)   # geospatial.py is plain Python and numpy, so it imports without Blender
    import geospatial
    system = geospatial.parse_geo_system(re.findall(r'"([^"]*)"', vp.get("geoSystem") or '"GD" "WE"'))
    pos = np.array(geospatial.to_geocentric(system, *(_floats(vp.get("position"), 3) or [0, 0, 100000])))
    frame = geospatial.local_frame(system, pos)
    height = geospatial.geocentric_to_geodetic(system, *pos)[2]
    far = float(np.linalg.norm(pos) + system.a)
    origin = vp.find("GeoOrigin")   # the scene's coordinates are the geocentric ones minus the origin, turned with rotateYUp
    if origin is not None:
        origin_system = geospatial.parse_geo_system(re.findall(r'"([^"]*)"', origin.get("geoSystem") or '"GD" "WE"'))
        o = np.array(geospatial.to_geocentric(origin_system, *(_floats(origin.get("geoCoords"), 3) or [0, 0, 0])))
        turn = geospatial.local_frame(system, o) if (origin.get("rotateYUp") or "").lower() == "true" else np.eye(3)
        pos, frame = (pos - o) @ turn, turn.T @ frame
    rot = frame @ _rot(_floats(vp.get("orientation"), 4) or [0, 0, 1, 0])
    return dict(position=[float(v) for v in pos], forward=[float(v) for v in -rot[:, 2]], up=[float(v) for v in rot[:, 1]],
                fov=float((_floats(vp.get("fieldOfView"), 1) or [0.785398])[0]),
                minZ=max(0.01 * height, 0.1), maxZ=far)


def first_viewpoint(path, src=None):
    """World position, rotation matrix and fieldOfView of the first Viewpoint in document order (what X_ITE binds)."""
    root = ET.parse(path).getroot()
    parents = {child: parent for parent in root.iter() for child in parent}
    vp = next((e for e in root.iter() if e.tag in ("Viewpoint", "OrthoViewpoint", "GeoViewpoint")), None)
    if vp is None:
        return None
    if vp.tag == "GeoViewpoint":   # a geocentric pose; a Transform above it is not applied
        return geo_viewpoint(vp, src)
    M = np.eye(4)
    node = parents.get(vp)
    chain = []
    while node is not None:
        if node.tag == "Transform":
            chain.append(node)
        node = parents.get(node)
    for t in reversed(chain):
        T = np.eye(4); T[:3, 3] = _floats(t.get("translation"), 3) or [0, 0, 0]
        R = np.eye(4); R[:3, :3] = _rot(_floats(t.get("rotation"), 4) or [0, 0, 1, 0])
        S = np.diag((_floats(t.get("scale"), 3) or [1, 1, 1]) + [1])
        C = np.eye(4); C[:3, 3] = _floats(t.get("center"), 3) or [0, 0, 0]
        SR = np.eye(4); SR[:3, :3] = _rot(_floats(t.get("scaleOrientation"), 4) or [0, 0, 1, 0])
        M = M @ T @ C @ R @ SR @ S @ np.linalg.inv(SR) @ np.linalg.inv(C)
    pos = np.array((_floats(vp.get("position"), 3) or [0, 0, 10]) + [1.0])
    rot = _rot(_floats(vp.get("orientation"), 4) or [0, 0, 1, 0])
    world_pos = (M @ pos)[:3]
    world_rot = M[:3, :3] @ rot
    world_rot = world_rot / np.linalg.norm(world_rot, axis=0)
    view = dict(position=[float(v) for v in world_pos], forward=[float(v) for v in -world_rot[:, 2]],
                up=[float(v) for v in world_rot[:, 1]], fov=0.785398)
    if vp.tag == "OrthoViewpoint":   # fieldOfView is the four extents minX minY maxX maxY
        view["ortho"] = _floats(vp.get("fieldOfView"), 4) or [-1.0, -1.0, 1.0, 1.0]
    else:
        view["fov"] = float((_floats(vp.get("fieldOfView"), 1) or [0.785398])[0])
    return view
