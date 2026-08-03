from pathlib import Path
from zipfile import ZipFile, ZipInfo

import pytest

from renderfarm.storage import LocalStorage, StorageError, sha256_file, validate_project_archive


def make_zip(path: Path, files: dict[str, bytes]):
    with ZipFile(path, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)


def test_valid_project_and_local_storage(tmp_path):
    project = tmp_path / "project.zip"
    make_zip(project, {"scene/main.blend": b"BLENDER", "textures/a.png": b"PNG"})
    assert validate_project_archive(project, 1024, 4096) == "scene/main.blend"
    store = LocalStorage(tmp_path / "objects")
    store.put_file("jobs/one/project.zip", project)
    copied = tmp_path / "copy.zip"
    store.copy_to("jobs/one/project.zip", copied)
    assert sha256_file(copied) == sha256_file(project)
    assert store.size() == project.stat().st_size


@pytest.mark.parametrize("files", [
    {"../escape.blend": b"x"},
    {"one.blend": b"x", "two.blend": b"x"},
    {"readme.txt": b"x"},
])
def test_archive_rejects_unsafe_or_ambiguous_input(tmp_path, files):
    project = tmp_path / "bad.zip"
    make_zip(project, files)
    with pytest.raises(StorageError):
        validate_project_archive(project, 1024, 4096)


def test_archive_rejects_symlink(tmp_path):
    project = tmp_path / "link.zip"
    with ZipFile(project, "w") as archive:
        item = ZipInfo("scene.blend")
        item.create_system = 3
        item.external_attr = 0o120777 << 16
        archive.writestr(item, b"target")
    with pytest.raises(StorageError):
        validate_project_archive(project, 1024, 4096)

