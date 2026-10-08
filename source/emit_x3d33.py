# SPDX-FileCopyrightText: 2026 OpenAI
#
# SPDX-License-Identifier: GPL-3.0-or-later

from __future__ import annotations

from .ir import IRScene


def export_ir_scene(file, ir_scene: IRScene, *, generator: str = "io_scene_x3d") -> None:
    """Minimal legacy emitter scaffold kept separate from the X3D 4.0 path."""

    write = file.write
    write('<?xml version="1.0" encoding="UTF-8"?>\n')
    write('<!DOCTYPE X3D PUBLIC "ISO//Web3D//DTD X3D 3.3//EN" "https://www.web3d.org/specifications/x3d-3.3.dtd">\n')
    write('<X3D version="3.3" profile="Immersive">\n')
    write('  <head>\n')
    write(f'    <meta name="generator" content="{generator}" />\n')
    if ir_scene.metadata.title:
        write(f'    <meta name="title" content="{ir_scene.metadata.title}" />\n')
    write('  </head>\n')
    write('  <Scene>\n')
    write('    <WorldInfo title="Legacy Scaffold Export" info=\'"Legacy emitter scaffold only; geometry not migrated yet."\' />\n')
    write('  </Scene>\n')
    write('</X3D>\n')

