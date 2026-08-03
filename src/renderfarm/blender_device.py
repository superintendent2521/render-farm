from __future__ import annotations


def configure_cycles_device(scene, preferences, requested: str) -> list[str]:
    """Select a Cycles backend and return the enabled device names.

    This module deliberately does not import bpy so the selection policy can be
    tested outside Blender. Blender's Cycles preferences object is passed in.
    """
    requested = requested.upper()
    if requested == "AUTO":
        print(f"Blend Farm: render engine={scene.render.engine}, device=AUTO", flush=True)
        return []
    if requested == "CPU":
        if scene.render.engine == "CYCLES":
            scene.cycles.device = "CPU"
        print(f"Blend Farm: render engine={scene.render.engine}, device=CPU", flush=True)
        return ["CPU"]
    if scene.render.engine != "CYCLES":
        raise RuntimeError(
            f"{requested} was requested, but the scene render engine is "
            f"{scene.render.engine}; CUDA/OPTIX/HIP selection only applies to Cycles"
        )

    try:
        preferences.compute_device_type = requested
        # get_devices() refreshes the collection exposed by preferences.devices.
        preferences.get_devices()
    except Exception as exc:
        raise RuntimeError(f"Cycles could not initialize the {requested} backend: {exc}") from exc

    devices = list(preferences.devices)
    selected = [item for item in devices if item.type == requested]
    if not selected:
        available = ", ".join(f"{item.name} ({item.type})" for item in devices) or "none"
        raise RuntimeError(
            f"Cycles found no {requested} GPU. Available devices: {available}"
        )

    # Do not silently use the CPU alongside the requested GPU backend.
    selected_ids = {id(item) for item in selected}
    for item in devices:
        item.use = id(item) in selected_ids
    scene.cycles.device = "GPU"
    names = [item.name for item in selected]
    print(
        f"Blend Farm: render engine=CYCLES, backend={requested}, "
        f"enabled devices={', '.join(names)}; CPU fallback=disabled",
        flush=True,
    )
    return names
