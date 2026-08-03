"""Executed inside Blender. Arguments follow the ``--`` separator."""
from __future__ import annotations

import sys

import bpy


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 5:
        raise RuntimeError("expected: frame output format preview device")
    frame, output, output_format, preview, device = args
    scene = bpy.context.scene
    scene.frame_set(int(frame))
    scene.render.filepath = output
    scene.render.image_settings.file_format = output_format
    if scene.render.engine == "CYCLES" and device != "AUTO":
        scene.cycles.device = "CPU" if device == "CPU" else "GPU"
        prefs = bpy.context.preferences.addons["cycles"].preferences
        try:
            prefs.compute_device_type = device
            prefs.get_devices()
            for item in prefs.devices:
                item.use = item.type == device
        except Exception as exc:
            print(f"Device configuration warning: {exc}")
    bpy.ops.render.render(write_still=True)
    scene.render.image_settings.file_format = "JPEG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.quality = 80
    scene.render.filepath = preview
    bpy.data.images["Render Result"].save_render(preview, scene=scene)


main()

