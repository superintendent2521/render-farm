from types import SimpleNamespace

import pytest

from renderfarm.blender_device import configure_cycles_device


class Preferences:
    def __init__(self, devices):
        self.devices = devices
        self.compute_device_type = "NONE"

    def get_devices(self):
        return None


def scene(engine="CYCLES"):
    return SimpleNamespace(
        render=SimpleNamespace(engine=engine),
        cycles=SimpleNamespace(device="CPU"),
    )


def device(name, kind):
    return SimpleNamespace(name=name, type=kind, use=True)


def test_cuda_selects_gpu_and_disables_cpu():
    cpu = device("Intel CPU", "CPU")
    gpu = device("Tesla T4", "CUDA")
    render_scene = scene()

    selected = configure_cycles_device(render_scene, Preferences([cpu, gpu]), "CUDA")

    assert selected == ["Tesla T4"]
    assert render_scene.cycles.device == "GPU"
    assert not cpu.use
    assert gpu.use


def test_requested_gpu_must_exist():
    with pytest.raises(RuntimeError, match="no OPTIX GPU"):
        configure_cycles_device(scene(), Preferences([device("Intel CPU", "CPU")]), "OPTIX")


def test_gpu_backend_requires_cycles():
    with pytest.raises(RuntimeError, match="only applies to Cycles"):
        configure_cycles_device(scene("BLENDER_EEVEE_NEXT"), Preferences([]), "CUDA")
