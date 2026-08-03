"""Executed inside Blender. Arguments follow the ``--`` separator."""
from __future__ import annotations

import sys

import bpy

from renderfarm.blender_device import configure_cycles_device


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 5:
        raise RuntimeError("expected: frame output format preview device")
    frame, output, output_format, preview, device = args
    scene = bpy.context.scene
    scene.frame_set(int(frame))
    scene.render.filepath = output
    scene.render.image_settings.file_format = output_format
    prefs = bpy.context.preferences.addons["cycles"].preferences
    configure_cycles_device(scene, prefs, device)
    bpy.ops.render.render(write_still=True)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.quality = 80
    scene.render.filepath = preview
    bpy.data.images["Render Result"].save_render(preview, scene=scene)


main()
