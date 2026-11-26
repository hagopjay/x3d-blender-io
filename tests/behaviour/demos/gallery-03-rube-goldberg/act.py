# SPDX-FileCopyrightText: 2026 HagopJay
# SPDX-License-Identifier: GPL-3.0-or-later
"""Live-window act for gallery-03-rube-goldberg: click the red button, let ten stages cascade, shoot each second or so,
then check that something in every stage moved."""


def act(rig, ctx):
    scene, name = ctx["scene"], ctx["name"]
    # The importer tags every object it makes from a DEF'd Transform with `x3d_def`; Blender can give the animated one
    # a suffixed name (a nested transform becomes "Lever.001"), so watch every object that carries the DEF.
    watch = {"button": "Btn", "domino": "Domino5", "ball": "Ball", "seesaw": "Plank", "pebble": "Pebble", "lever": "Lever",
             "flag": "Flag", "bell": "Bell", "rocket": "Rocket", "spark": "Spark3", "banner": "Banner"}
    group = {k: [o for o in scene.objects if o.get("x3d_def") == v] for k, v in watch.items()}
    pose = lambda os: tuple(tuple(round(v, 2) for v in (*o.matrix_basis.translation, *o.matrix_basis.to_quaternion())) for o in os)
    objs = group
    cam = scene.camera
    cam0 = tuple(round(v, 2) for v in cam.matrix_world.translation)

    def run(label):
        """Sample every watched pose for 15 s, a screenshot per second; returns the poses seen."""
        seen = {k: set() for k in objs}
        for second in range(1, 16):
            for _ in range(10):
                yield 0.1
                for k, o in objs.items():
                    seen[k].add(pose(o))
            rig.shot(f"{name}-act-{label}-{second:02d}")
        return seen

    # run 1: the eye test's own click, a moment ago, started the machine; ride along with the camera tour
    first = yield from run("tour")
    cam1 = tuple(round(v, 2) for v in cam.matrix_world.translation)
    # run 2: the tour ended on a wide shot where the whole bench shows; click the button again
    point = next((rig.screen_point(o) for o in objs["button"] if rig.screen_point(o)), None)
    second = {k: set() for k in objs}
    if point:
        rig.mouse(*point)
        yield 0.3
        rig.mouse(*point, "LEFTMOUSE", "PRESS")
        yield 0.1
        rig.mouse(*point, "LEFTMOUSE", "RELEASE")
        second = yield from run("again")
    rig.note(name, "act_numbers", {"run1_poses": {k: len(v) for k, v in first.items()}, "run2_poses": {k: len(v) for k, v in second.items()},
                                   "camera": [cam0, cam1], "button_in_view_for_run2": point is not None})
    rig.note(name, "act_ok", all(len(v) > 1 for k, v in second.items()) and all(len(v) > 1 for k, v in first.items() if k != "button") and cam0 != cam1)
