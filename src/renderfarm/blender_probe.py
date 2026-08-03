"""Executed inside Blender by ``blend-farm-worker doctor``."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Blender runs scripts with its bundled Python and does not inherit the worker
# interpreter's site-packages search path. Add the package root explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bpy

from renderfarm.blender_device import configure_cycles_device


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    if len(args) != 1:
        raise RuntimeError("expected render device")
    requested = args[0]
    scene = bpy.context.scene
    if requested not in {"AUTO", "CPU"}:
        # The factory-startup scene is only a probe; changing its engine does not
        # alter any submitted project.
        scene.render.engine = "CYCLES"
    prefs = bpy.context.preferences.addons["cycles"].preferences
    names = configure_cycles_device(scene, prefs, requested)
    print("BLEND_FARM_PROBE=" + json.dumps({"device": requested, "devices": names}), flush=True)


main()
