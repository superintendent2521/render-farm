"""Executed inside Blender. Arguments follow the ``--`` separator."""
from __future__ import annotations

import sys
import json
import time
from pathlib import Path

# Blender runs scripts with its bundled Python and does not inherit the worker
# interpreter's site-packages search path. Add the package root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

from renderfarm.blender_device import configure_cycles_device


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 1:
        raise RuntimeError("expected: batch manifest path")
    manifest_path = Path(args[0])
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scene = bpy.context.scene
    prefs = bpy.context.preferences.addons["cycles"].preferences
    configure_cycles_device(scene, prefs, manifest["device"])
    total = len(manifest["frames"])
    for index, item in enumerate(manifest["frames"], 1):
        started = time.monotonic()
        print(f"Blend Farm: rendering frame {item['frame']} ({index}/{total})", flush=True)
        scene.frame_set(int(item["frame"]))
        scene.render.filepath = item["output"]
        scene.render.image_settings.file_format = item["output_format"]
        output_color_mode = scene.render.image_settings.color_mode
        output_quality = scene.render.image_settings.quality
        bpy.ops.render.render(write_still=True)
        scene.render.image_settings.file_format = "JPEG"
        scene.render.image_settings.color_mode = "RGB"
        scene.render.image_settings.quality = 80
        scene.render.filepath = item["preview"]
        bpy.data.images["Render Result"].save_render(item["preview"], scene=scene)
        # Preview encoding must not leak into the next frame's original output.
        scene.render.image_settings.file_format = item["output_format"]
        scene.render.image_settings.color_mode = output_color_mode
        scene.render.image_settings.quality = output_quality
        print(f"Blend Farm: frame {item['frame']} rendered in {time.monotonic() - started:.2f}s", flush=True)


main()
